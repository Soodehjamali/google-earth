"""NOAA GFS Forecast Provider with Phase 2 DEM Elevation Correction.

Task 3.1: Forecast adapter module providing standardized hourly/multi-hourly
forecast time-series with lapse-rate elevation correction, lead-time uncertainty,
and honest cadence disclosure.
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.services.agriculture.quality_gating import (
    correct_temperature_for_elevation,
    DEFAULT_QUALITY_CONFIG,
    QualityGatingConfig,
)

logger = get_logger(__name__)

#: Dataset specifications for NOAA/GFS0P25
NOAA_GFS_DATASET_ID = "NOAA/GFS0P25"
GFS_SPATIAL_RESOLUTION_M = 27830.0  # ~0.25 degrees at equator
GFS_CELL_RADIUS_M = 13915.0         # 27.83km / 2 for cell footprint buffer

#: Default lead-time temperature uncertainty table in degrees Celsius.
#: Flagged as "needs calibration" in documentation and output.
DEFAULT_LEAD_TIME_UNCERTAINTY_TABLE: Tuple[Tuple[float, float], ...] = (
    (24.0, 1.0),        # 0 to 24h: ±1.0 °C (placeholder / needs calibration)
    (48.0, 1.5),        # 24 to 48h: ±1.5 °C (placeholder / needs calibration)
    (72.0, 2.0),        # 48 to 72h: ±2.0 °C (placeholder / needs calibration)
    (120.0, 2.5),       # 72 to 120h: ±2.5 °C (placeholder / needs calibration)
    (240.0, 3.5),       # 120 to 240h: ±3.5 °C (placeholder / needs calibration)
    (float("inf"), 4.5),# > 240h: ±4.5 °C (placeholder / needs calibration)
)


def get_lead_time_uncertainty(lead_hours: float, table: Optional[Tuple[Tuple[float, float], ...]] = None) -> float:
    """Lookup lead-time uncertainty (in °C) based on forecast horizon hours."""
    lookup = table or DEFAULT_LEAD_TIME_UNCERTAINTY_TABLE
    for max_h, unc in lookup:
        if lead_hours <= max_h:
            return unc
    return 4.5


@dataclass(frozen=True)
class ForecastTimestep:
    """One timestep in the meteorological forecast series."""

    timestamp_utc: str
    lead_hours: float
    temperature_2m_c: float
    temperature_2m_c_raw: float
    elevation_delta_m: float
    elevation_correction_c: float
    elevation_uncertainty_c: float
    lead_time_uncertainty_c: float
    total_uncertainty_c: float
    lower_bound_c: float
    upper_bound_c: float
    is_interpolated: bool
    relative_humidity_percent: Optional[float] = None
    wind_speed_10m_mps: Optional[float] = None
    # Deprecated backwards-compatibility aliases
    temperature_min_c: Optional[float] = None
    temperature_max_c: Optional[float] = None

    def __post_init__(self):
        if self.temperature_min_c is None:
            self.temperature_min_c = self.lower_bound_c
        if self.temperature_max_c is None:
            self.temperature_max_c = self.upper_bound_c


@dataclass
class ForecastResult:
    """Structured response from a ForecastProvider."""

    series: List[ForecastTimestep]
    source: str
    issue_time_utc: Optional[str]
    native_spatial_resolution_m: float
    native_temporal_resolution_h: int
    quality_state: str
    site_elevation_m: float
    cell_elevation_m: float
    horizon_hours: int
    disclaimer_fa: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ForecastProvider(ABC):
    """Abstract interface for meteorological forecast providers."""

    @abstractmethod
    async def get_hourly_forecast(
        self,
        geometry: Any,
        horizon_h: int = 72,
    ) -> ForecastResult:
        """Fetch forecast series up to horizon_h for the given geometry.

        Args:
            geometry: GeoJSON mapping, Shapely shape, or EE Geometry.
            horizon_h: Forecast horizon in hours (max 384 for GFS).

        Returns:
            ForecastResult carrying elevation-corrected series and provenance.
        """
        pass


class NoaaGfsForecastProvider(ForecastProvider):
    """NOAA/GFS0P25 forecast implementation via Google Earth Engine.

    Real temporal resolution disclosure:
      - 0 to 120 hours (Days 0-5): 1-hourly native resolution.
      - 120 to 384 hours (Days 5-16): 3-hourly native resolution.
      - Any intermediate hours generated for a uniform hourly series beyond
        120h are explicitly flagged with is_interpolated=True.
    """

    def __init__(
        self,
        quality_config: Optional[QualityGatingConfig] = None,
        uncertainty_table: Optional[Tuple[Tuple[float, float], ...]] = None,
    ):
        self.quality_config = quality_config or DEFAULT_QUALITY_CONFIG
        self.uncertainty_table = uncertainty_table or DEFAULT_LEAD_TIME_UNCERTAINTY_TABLE

    async def get_hourly_forecast(
        self,
        geometry: Any,
        horizon_h: int = 72,
    ) -> ForecastResult:
        import ee
        from app.services.earth_engine.authentication import initialize_earth_engine

        initialize_earth_engine()

        # Build EE geometry
        if isinstance(geometry, dict):
            ee_geom = ee.Geometry(geometry)
        elif hasattr(geometry, "__geo_interface__"):
            ee_geom = ee.Geometry(geometry.__geo_interface__)
        elif isinstance(geometry, ee.Geometry):
            ee_geom = geometry
        else:
            raise ValueError(f"Unsupported geometry type for forecast: {type(geometry)}")

        # 1. Derive elevations from NASADEM (Phase 2 consistency)
        from app.services.agriculture.terrain import NASADEM, TERRAIN_WORKING_SCALE
        dem = ee.Image(NASADEM).select(["elevation"])

        # Site elevation
        site_raw = dem.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=ee_geom,
            scale=TERRAIN_WORKING_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()
        z_site = float(site_raw["elevation"]) if site_raw and site_raw.get("elevation") is not None else 1000.0

        # Grid cell elevation (averaged over GFS cell footprint ~28km)
        cell_geom = ee_geom.centroid().buffer(GFS_CELL_RADIUS_M)
        cell_raw = dem.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=cell_geom,
            scale=TERRAIN_WORKING_SCALE,
            maxPixels=1e9,
            bestEffort=True,
        ).getInfo()
        z_cell = float(cell_raw["elevation"]) if cell_raw and cell_raw.get("elevation") is not None else z_site

        # 2. Query GFS collection
        # Look back up to 36 hours to find the latest completed run
        now_utc = datetime.now(timezone.utc)
        start_search = (now_utc - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S")

        ic = (
            ee.ImageCollection(NOAA_GFS_DATASET_ID)
            .filterDate(start_search, now_utc.strftime("%Y-%m-%dT%H:%M:%S"))
            .filterBounds(ee_geom)
        )

        # Get the latest creation_time
        latest_img = ic.sort("system:time_start", False).first().getInfo()
        if not latest_img:
            # Fallback to wider search if recent ingestion delayed
            ic = ee.ImageCollection(NOAA_GFS_DATASET_ID).filterBounds(ee_geom).limit(100)
            latest_img = ic.sort("system:time_start", False).first().getInfo()
            if not latest_img:
                raise RuntimeError("No NOAA/GFS0P25 forecast imagery available in Earth Engine")

        creation_time_ms = latest_img["properties"].get("creation_time")
        if not creation_time_ms:
            creation_time_ms = latest_img["properties"].get("system:time_start")

        # Filter to the single model run and up to horizon_h
        run_collection = (
            ee.ImageCollection(NOAA_GFS_DATASET_ID)
            .filter(ee.Filter.eq("creation_time", creation_time_ms))
            .filter(ee.Filter.lte("forecast_hours", horizon_h))
            .filterBounds(ee_geom)
            .sort("forecast_hours", True)
        )

        # Issue time
        issue_time_str = (
            datetime.fromtimestamp(creation_time_ms / 1000.0, tz=timezone.utc).isoformat()
            if creation_time_ms
            else None
        )

        # Batch-sample all forecast hours in a single GEE roundtrip
        centroid_geom = ee_geom.centroid()
        sampled_fc = (
            run_collection.select([
                "temperature_2m_above_ground",
                "relative_humidity_2m_above_ground",
                "u_component_of_wind_10m_above_ground",
                "v_component_of_wind_10m_above_ground",
            ])
            .map(
                lambda img: ee.Feature(
                    None,
                    img.reduceRegion(
                        reducer=ee.Reducer.mean(),
                        geometry=centroid_geom,
                        scale=GFS_SPATIAL_RESOLUTION_M,
                        bestEffort=True,
                    ),
                )
                .set("forecast_hours", img.get("forecast_hours"))
                .set("forecast_time", img.get("forecast_time"))
                .set("img_id", img.id())
            )
        )

        fc_info = sampled_fc.getInfo()
        features = fc_info.get("features", [])

        # Process each timestep in memory without additional network calls
        series: List[ForecastTimestep] = []
        for feat in features:
            props = feat.get("properties", {})
            lead_h = float(props.get("forecast_hours", 0))
            forecast_time_ms = props.get("forecast_time")
            if not forecast_time_ms:
                forecast_time_ms = creation_time_ms + int(lead_h * 3600 * 1000)

            ts_utc = datetime.fromtimestamp(forecast_time_ms / 1000.0, tz=timezone.utc).isoformat()

            t_val = props.get("temperature_2m_above_ground")
            # GEE's NOAA/GFS0P25 provides temperature_2m_above_ground directly in degrees Celsius
            t_raw_c = float(t_val) if t_val is not None else 15.0

            rh = props.get("relative_humidity_2m_above_ground")
            rh_pct = float(rh) if rh is not None else None

            u = props.get("u_component_of_wind_10m_above_ground")
            v = props.get("v_component_of_wind_10m_above_ground")
            wind_speed = math.sqrt(float(u)**2 + float(v)**2) if (u is not None and v is not None) else None

            # Apply Phase 2 elevation correction
            # Night detection: UTC hour for Iran (~UTC+3.5) night is roughly 15:30 to 02:30 UTC
            hour_utc = datetime.fromtimestamp(forecast_time_ms / 1000.0, tz=timezone.utc).hour
            is_night = hour_utc >= 16 or hour_utc <= 3

            corr = correct_temperature_for_elevation(
                t_cell=t_raw_c,
                z_cell=z_cell,
                z_site=z_site,
                is_night_minimum=is_night,
                config=self.quality_config,
            )

            # Lead-time uncertainty
            lead_unc = get_lead_time_uncertainty(lead_h, self.uncertainty_table)
            # Quadrature total uncertainty: sqrt(elev_unc^2 + lead_unc^2)
            total_unc = round(math.sqrt(corr.uncertainty_c**2 + lead_unc**2), 2)

            series.append(
                ForecastTimestep(
                    timestamp_utc=ts_utc,
                    lead_hours=lead_h,
                    temperature_2m_c=corr.corrected_value,
                    temperature_2m_c_raw=corr.raw_value,
                    elevation_delta_m=round(z_site - z_cell, 1),
                    elevation_correction_c=corr.delta_c,
                    elevation_uncertainty_c=corr.uncertainty_c,
                    lead_time_uncertainty_c=lead_unc,
                    total_uncertainty_c=total_unc,
                    lower_bound_c=round(corr.corrected_value - total_unc, 2),
                    upper_bound_c=round(corr.corrected_value + total_unc, 2),
                    temperature_min_c=round(corr.corrected_value - total_unc, 2),
                    temperature_max_c=round(corr.corrected_value + total_unc, 2),
                    is_interpolated=False,
                    relative_humidity_percent=round(rh_pct, 1) if rh_pct is not None else None,
                    wind_speed_10m_mps=round(wind_speed, 1) if wind_speed is not None else None,
                )
            )

        # Sort by lead_hours
        series.sort(key=lambda x: x.lead_hours)

        return ForecastResult(
            series=series,
            source=NOAA_GFS_DATASET_ID,
            issue_time_utc=issue_time_str,
            native_spatial_resolution_m=GFS_SPATIAL_RESOLUTION_M,
            native_temporal_resolution_h=1 if horizon_h <= 120 else 3,
            quality_state="coarse_context",
            site_elevation_m=round(z_site, 1),
            cell_elevation_m=round(z_cell, 1),
            horizon_hours=horizon_h,
            disclaimer_fa=(
                "داده‌های پیش‌بینی هواشناسی از مدل جهانی GFS (تفکیک ~۲۸ کیلومتر) استخراج شده و "
                "بر اساس تراز ارتفاعی مدل رقومی زمین (NASADEM) تصحیح فیزیکی گردیده‌اند. "
                "عدم قطعیت زمان پیش‌بینی و افت ارتفاعی به شکل بازه اطمینان لحاظ شده است (نیازمند کالیبراسیون محلی)."
            ),
            metadata={
                "model_run_creation_time_ms": creation_time_ms,
                "total_timesteps": len(series),
                "elevation_lapse_rate_c_per_km": self.quality_config.default_lapse_rate_c_per_km,
            },
        )


class FakeForecastProvider(ForecastProvider):
    """Deterministic fake forecast provider for testing without network or credentials."""

    def __init__(
        self,
        base_tmin_c: float = 1.0,
        base_tmax_c: float = 18.0,
        z_site_m: float = 1450.0,
        z_cell_m: float = 1150.0,
        start_time_utc: Optional[datetime] = None,
        quality_config: Optional[QualityGatingConfig] = None,
        uncertainty_table: Optional[Tuple[Tuple[float, float], ...]] = None,
    ):
        from app.core.config import settings
        from app.core.exceptions import AppException

        if getattr(settings, "is_production", False) or getattr(settings, "APP_ENV", "") == "production":
            raise AppException(
                message="Fake forecast provider is unreachable in production configuration",
                code="ERR_FORBIDDEN",
                reason="Production environment forbids synthetic/fake forecast data.",
                status_code=403,
            )

        self.base_tmin_c = base_tmin_c
        self.base_tmax_c = base_tmax_c
        self.z_site_m = z_site_m
        self.z_cell_m = z_cell_m
        self.start_time_utc = start_time_utc or datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
        self.quality_config = quality_config or DEFAULT_QUALITY_CONFIG
        self.uncertainty_table = uncertainty_table or DEFAULT_LEAD_TIME_UNCERTAINTY_TABLE

    async def get_hourly_forecast(
        self,
        geometry: Any,
        horizon_h: int = 72,
    ) -> ForecastResult:
        series: List[ForecastTimestep] = []

        # Generate hourly timesteps
        for h in range(horizon_h + 1):
            ts = self.start_time_utc + timedelta(hours=h)
            hour = ts.hour
            # Diurnal curve: Tmin at 05:00 local (~01:30 UTC), Tmax at 14:00 local (~10:30 UTC)
            # Use smooth cosine diurnal cycle
            diurnal_phase = (hour - 2) * (2 * math.pi / 24.0)
            amplitude = (self.base_tmax_c - self.base_tmin_c) / 2.0
            midpoint = (self.base_tmax_c + self.base_tmin_c) / 2.0
            t_raw = midpoint - amplitude * math.cos(diurnal_phase)

            # Native cadence disclosure: GFS is 1-hourly up to 120h, 3-hourly past 120h
            is_native = (h <= 120) or (h % 3 == 0)
            is_interpolated = not is_native

            is_night = (hour >= 16 or hour <= 3)

            corr = correct_temperature_for_elevation(
                t_cell=t_raw,
                z_cell=self.z_cell_m,
                z_site=self.z_site_m,
                is_night_minimum=is_night,
                config=self.quality_config,
            )

            lead_unc = get_lead_time_uncertainty(float(h), self.uncertainty_table)
            total_unc = round(math.sqrt(corr.uncertainty_c**2 + lead_unc**2), 2)

            series.append(
                ForecastTimestep(
                    timestamp_utc=ts.isoformat(),
                    lead_hours=float(h),
                    temperature_2m_c=corr.corrected_value,
                    temperature_2m_c_raw=corr.raw_value,
                    elevation_delta_m=round(self.z_site_m - self.z_cell_m, 1),
                    elevation_correction_c=corr.delta_c,
                    elevation_uncertainty_c=corr.uncertainty_c,
                    lead_time_uncertainty_c=lead_unc,
                    total_uncertainty_c=total_unc,
                    lower_bound_c=round(corr.corrected_value - total_unc, 2),
                    upper_bound_c=round(corr.corrected_value + total_unc, 2),
                    temperature_min_c=round(corr.corrected_value - total_unc, 2),
                    temperature_max_c=round(corr.corrected_value + total_unc, 2),
                    is_interpolated=is_interpolated,
                    relative_humidity_percent=45.0,
                    wind_speed_10m_mps=2.5,
                )
            )

        return ForecastResult(
            series=series,
            source="deterministic_fake",
            issue_time_utc=self.start_time_utc.isoformat(),
            native_spatial_resolution_m=GFS_SPATIAL_RESOLUTION_M,
            native_temporal_resolution_h=1 if horizon_h <= 120 else 3,
            quality_state="coarse_context",
            site_elevation_m=round(self.z_site_m, 1),
            cell_elevation_m=round(self.z_cell_m, 1),
            horizon_hours=horizon_h,
            disclaimer_fa="داده‌های پیش‌بینی شبیه‌سازی‌شده (Fake Provider) جهت آزمایش و اعتبارسنجی سیستم.",
            metadata={
                "provider": "FakeForecastProvider",
                "total_timesteps": len(series),
            },
        )
