"""Thermal temporal profile and harmonization (P4.2).

Builds the temporal observation layer on top of the audited P4.1
thermal foundation. Two physical quantities stay explicitly distinct:

* MODIS LST (``land_surface_temperature_day``, band ``LST_Day_1km``)
  is land-surface / skin temperature, from
  ``MODIS/061/MOD11A2`` (8-day primary).
* ERA5-Land ``temperature_mean`` (band ``temperature_2m``) is
  modelled 2 m air temperature, from
  ``ECMWF/ERA5_LAND/DAILY_AGGR``.

This module establishes observation profiles and an explicit
temporal harmonization contract. It performs no thermal
interpretation: no anomaly, no stress, no Z-score, no percentile,
no breakpoint, no persistence, no rapid-change, no risk, and no
pest/disease signal.

Source-native temporal semantics (audited, not assumed)
-------------------------------------------------------
Both production metrics return a single period temporal mean
(``collection.mean()`` reduced spatially, ``value`` is the mean):

* ``_ModisLstMetric.compute`` aggregates as
  ``"time mean, then spatial mean"`` over whatever window it is
  given. The registry declares ``MOD11A2`` as an 8-day composite
  (a simple mean of daily retrievals with no QA filtering; the
  final yearly composite spans 5-6 days) and ``MOD11A1`` as daily.
* ``_ERA5Metric.compute`` aggregates the same way over the daily
  reanalysis collection (``"time mean, then spatial mean"``).

The profile layer therefore exposes calendar-month window means:
each point re-runs the metric's own verified ``compute`` on that
month's sub-context (the P1.1 sibling-compute pattern). A point
carries exactly the value, quality, coverage, and provenance the
metric itself would publish for that month.

Representations deliberately NOT offered
----------------------------------------
* DAILY: a single-day window (``start == end``) is rejected by the
  repository's own ``validate_date_range`` (``end > start`` is
  required), and labelling a two-date ``(day, next_day)`` window as
  one daily observation would silently shift the EE
  ``filterDate`` (end-exclusive) semantics. Daily observations are
  therefore not representable without changing metric semantics.
* 8_DAY: the production metric emits window means, not native
  8-day composite slots; inventing an 8-day grid anchored at an
  assumed epoch would be new temporal arithmetic, not reuse.
* Only ``MONTHLY`` (calendar months via the repository's
  ``get_monthly_periods``) is offered, for both sources
  independently, and the harmonized representation is monthly.

MODIS fallback semantics (audited, preserved)
---------------------------------------------
``_ModisLstMetric`` declares
``dataset_ids = (MOD11A2, MOD11A1)`` but its ``compute`` resolves
only ``primary_dataset()`` (MOD11A2) and never queries MOD11A1.
The profile layer reuses ``compute`` verbatim, so each point has
exactly one selected source, recorded in its provenance as
``source_dataset_id`` (with ``fallback_from`` as the metric left
it). Fallback observations are never treated as an additional
independent sensor and are never double-counted: MOD11A1 is
declared metadata (``fallback_dataset_id`` on the LST profile),
not a contributing observation.

Missingness, quality, provenance
--------------------------------
* Chronological calendar-month points; exact windows preserved
  (point window == sub-context window == provenance
  requested dates).
* Missing months stay missing (``value=None``): no
  interpolation, no zero-fill, no nearest-observation
  substitution, no silent date shifting, no gap bridging.
* A month outside source coverage becomes ``"unavailable"``
  without an EE call (per-month ``can_attempt`` gate, plus a
  whole-window fast path). A month with no scenes or no valid
  pixels keeps the metric's own ``"insufficient"`` verdict.
  Point quality strings are preserved verbatim: the profile
  layer never upgrades or downgrades them.
* Every point preserves source dataset, band, physical quantity,
  native/output units, scale/offset, aggregation method, source
  temporal resolution, image count, coverage, quality,
  masking/quality policy, limitations, and full provenance.

Harmonization contract
----------------------
``harmonize_thermal_monthly`` pairs one LST monthly profile with
one air-temperature monthly profile by calendar month. Each side
was aggregated independently by its own production path; pairing
is not averaging. A harmonized month carries ``lst_celsius`` and
``air_temperature_celsius`` as separate observations, never one
``temperature`` scalar, never their mean, and never a derived
canopy temperature. Period quality is the preserved per-source
pair, not a weakest-wins reduction, because the two sides are
independent physical quantities.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Type

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext
from app.services.agriculture.climate import (
    ERA5_DAILY,
    TemperatureMeanMetric,
)
from app.services.agriculture.thermal import (
    MODIS_LST_8DAY,
    MODIS_LST_DAILY,
    LandSurfaceTemperatureDayMetric,
)
from app.utils.dates import get_monthly_periods, validate_date_range

logger = get_logger(__name__)

__all__ = [
    "LST_METRIC_KEY",
    "AIR_METRIC_KEY",
    "LST_SOURCE_BAND",
    "AIR_SOURCE_BAND",
    "THERMAL_PROFILE_KIND_LST",
    "THERMAL_PROFILE_KIND_AIR",
    "PHYSICAL_QUANTITY_LST",
    "PHYSICAL_QUANTITY_LST_LABEL",
    "PHYSICAL_QUANTITY_AIR",
    "PHYSICAL_QUANTITY_AIR_LABEL",
    "STEP_CALENDAR_MONTH",
    "HARMONIZATION_MONTHLY",
    "HARMONIZATION_METHOD",
    "SUPPORTED_THERMAL_PROFILE_METRICS",
    "ThermalProfilePoint",
    "ThermalSourceProfile",
    "ThermalHarmonizedPeriod",
    "ThermalHarmonizedProfile",
    "month_windows",
    "usable_values",
    "thermal_metadata",
    "build_thermal_source_profile",
    "build_lst_profile",
    "build_air_temperature_profile",
    "harmonize_thermal_monthly",
    "build_thermal_harmonized_monthly",
]

#: Production metric key read for land-surface temperature.
LST_METRIC_KEY = "land_surface_temperature_day"

#: Production metric key read for modelled 2 m air temperature.
AIR_METRIC_KEY = "temperature_mean"

#: MODIS band read for the LST profile (daytime retrieval).
LST_SOURCE_BAND = "LST_Day_1km"

#: ERA5-Land band read for the air-temperature profile.
AIR_SOURCE_BAND = "temperature_2m"

#: Profile-kind identifiers. Deliberately distinct: the two
#: quantities must never be requested or stored under one
#: generic ``temperature_profile`` name.
THERMAL_PROFILE_KIND_LST = "LST_PROFILE"
THERMAL_PROFILE_KIND_AIR = "AIR_TEMPERATURE_PROFILE"

#: Physical-quantity identifiers carried on every observation.
PHYSICAL_QUANTITY_LST = "land_surface_temperature"
PHYSICAL_QUANTITY_LST_LABEL = "land-surface / skin temperature"
PHYSICAL_QUANTITY_AIR = "air_temperature_2m"
PHYSICAL_QUANTITY_AIR_LABEL = "modelled 2 m air temperature"

#: The only source-native step offered (see module docstring).
STEP_CALENDAR_MONTH = "calendar_month"

#: The only harmonized representation offered.
HARMONIZATION_MONTHLY = "MONTHLY"

#: Harmonization method published on every harmonized period.
HARMONIZATION_METHOD = (
    "independent calendar-month window means paired by month; "
    "each source aggregated by its own production metric "
    "(time mean, then spatial mean); no cross-source averaging"
)

#: Metric classes eligible for thermal profiles, keyed by registry key.
SUPPORTED_THERMAL_PROFILE_METRICS: Dict[str, Type[Metric]] = {
    LST_METRIC_KEY: LandSurfaceTemperatureDayMetric,
    AIR_METRIC_KEY: TemperatureMeanMetric,
}

#: Profile kind by supported metric key.
_PROFILE_KIND_BY_METRIC: Dict[str, str] = {
    LST_METRIC_KEY: THERMAL_PROFILE_KIND_LST,
    AIR_METRIC_KEY: THERMAL_PROFILE_KIND_AIR,
}

#: Physical quantity by supported metric key.
_QUANTITY_BY_METRIC: Dict[str, str] = {
    LST_METRIC_KEY: PHYSICAL_QUANTITY_LST,
    AIR_METRIC_KEY: PHYSICAL_QUANTITY_AIR,
}

#: Declared (never queried) fallback dataset by supported metric key.
_FALLBACK_BY_METRIC: Dict[str, Optional[str]] = {
    LST_METRIC_KEY: MODIS_LST_DAILY,
    AIR_METRIC_KEY: None,
}

#: Scientific limitations restated on the profile layer so that a
#: reader of a profile alone cannot mistake either quantity.
_LST_PROFILE_LIMITATIONS: Tuple[str, ...] = (
    "This is land surface temperature, the radiometric skin temperature "
    "of everything in the pixel. It is NOT canopy temperature and NOT "
    "leaf temperature.",
    "Daytime overpass is roughly 10:30 local solar time, which is not "
    "the daily maximum surface temperature.",
    "The 8-day composite averages daily retrievals without filtering "
    "by quality, so a single cloudy day can bias the mean.",
    "A monthly mean hides sub-monthly extremes; it is not a heat-wave "
    "record.",
    "LST and 2 m air temperature are different physical quantities and "
    "must never be averaged together; their difference is not a "
    "measured canopy temperature.",
)

_AIR_PROFILE_LIMITATIONS: Tuple[str, ...] = (
    "This is modelled 2 m air temperature from reanalysis, not a field "
    "measurement. It is NOT canopy temperature and NOT leaf temperature.",
    "Modelled at roughly 11 km, it is only defensible as regional "
    "context, not within-field conditions.",
    "A monthly mean hides sub-monthly extremes; it is not a heat-wave "
    "record.",
    "LST and 2 m air temperature are different physical quantities and "
    "must never be averaged together; their difference is not a "
    "measured canopy temperature.",
)

_HARMONIZED_LIMITATIONS: Tuple[str, ...] = (
    "Each side of a harmonized month is an independent observation of "
    "its own physical quantity. LST remains land-surface / skin "
    "temperature; ERA5 remains modelled 2 m air temperature.",
    "The two sides must never be averaged into one temperature scalar "
    "and their difference must never be presented as canopy temperature.",
)


# --------------------------------------------------------------------------
# Observation types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ThermalProfilePoint:
    """One monthly observation of one thermal quantity.

    A missing observation is ``value=None`` with the quality the
    failed window reported (``"unavailable"`` when nothing ran at
    all, ``"insufficient"`` when the metric ran but found no usable
    data). Missing is structural: consumers must render gaps, never
    interpolate and never substitute a neighbour.
    """

    window_start: str
    window_end: str
    value: Optional[float]
    unit: str = ""
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None
    image_count: Optional[int] = None
    source_dataset_id: str = ""
    source_band: str = ""
    physical_quantity: str = ""
    aggregation_method: str = ""
    temporal_resolution: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "value": self.value,
            "unit": self.unit,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "source_dataset_id": self.source_dataset_id,
            "source_band": self.source_band,
            "physical_quantity": self.physical_quantity,
            "aggregation_method": self.aggregation_method,
            "temporal_resolution": self.temporal_resolution,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalProfilePoint":
        """Rebuild a point from :meth:`to_dict` output."""
        return cls(
            window_start=payload["window_start"],
            window_end=payload["window_end"],
            value=payload.get("value"),
            unit=payload.get("unit", ""),
            quality=payload.get("quality", "unavailable"),
            coverage_percent=payload.get("coverage_percent"),
            image_count=payload.get("image_count"),
            source_dataset_id=payload.get("source_dataset_id", ""),
            source_band=payload.get("source_band", ""),
            physical_quantity=payload.get("physical_quantity", ""),
            aggregation_method=payload.get("aggregation_method", ""),
            temporal_resolution=payload.get("temporal_resolution", ""),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class ThermalSourceProfile:
    """A chronological sequence of monthly observations, one quantity.

    ``profile_kind`` is ``LST_PROFILE`` or ``AIR_TEMPERATURE_PROFILE``;
    the two are never interchangeable. ``dataset_id`` names the
    selected (primary) source; ``fallback_dataset_id`` names the
    declared-but-unqueried fallback, if any, so the fallback
    contract is visible without contributing observations.
    """

    profile_kind: str
    metric_key: str
    dataset_id: Optional[str]
    fallback_dataset_id: Optional[str]
    band: str
    unit: str
    physical_quantity: str
    physical_quantity_label: str
    measurement_basis: str
    temporal_resolution: str
    aggregation_method: str
    window_start: str
    window_end: str
    step: str = STEP_CALENDAR_MONTH
    limitations: Tuple[str, ...] = ()
    points: Tuple[ThermalProfilePoint, ...] = field(default_factory=tuple)

    @property
    def n_points(self) -> int:
        """Total months emitted, including missing ones."""
        return len(self.points)

    @property
    def n_usable(self) -> int:
        """Months carrying a finite value."""
        return sum(1 for point in self.points if _is_usable_value(point.value))

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "profile_kind": self.profile_kind,
            "metric_key": self.metric_key,
            "dataset_id": self.dataset_id,
            "fallback_dataset_id": self.fallback_dataset_id,
            "band": self.band,
            "unit": self.unit,
            "physical_quantity": self.physical_quantity,
            "physical_quantity_label": self.physical_quantity_label,
            "measurement_basis": self.measurement_basis,
            "temporal_resolution": self.temporal_resolution,
            "aggregation_method": self.aggregation_method,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "limitations": list(self.limitations),
            "points": [point.to_dict() for point in self.points],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalSourceProfile":
        """Rebuild a profile from :meth:`to_dict` output."""
        return cls(
            profile_kind=payload["profile_kind"],
            metric_key=payload["metric_key"],
            dataset_id=payload.get("dataset_id"),
            fallback_dataset_id=payload.get("fallback_dataset_id"),
            band=payload.get("band", ""),
            unit=payload.get("unit", ""),
            physical_quantity=payload.get("physical_quantity", ""),
            physical_quantity_label=payload.get(
                "physical_quantity_label", ""
            ),
            measurement_basis=payload.get("measurement_basis", ""),
            temporal_resolution=payload.get("temporal_resolution", ""),
            aggregation_method=payload.get("aggregation_method", ""),
            window_start=payload["window_start"],
            window_end=payload["window_end"],
            step=payload.get("step", STEP_CALENDAR_MONTH),
            limitations=tuple(payload.get("limitations") or ()),
            points=tuple(
                ThermalProfilePoint.from_dict(item)
                for item in payload.get("points") or ()
            ),
        )


@dataclass(frozen=True)
class ThermalHarmonizedPeriod:
    """One calendar month holding two independent observations.

    ``lst`` and ``air`` are the source-native monthly points (or
    ``None`` when that source had no usable observation for the
    month). They are stored side by side, never merged: there is no
    combined temperature, no mean of the two, and no derived canopy
    value anywhere on this type.
    """

    window_start: str
    window_end: str
    lst: Optional[ThermalProfilePoint] = None
    air: Optional[ThermalProfilePoint] = None
    harmonization_method: str = HARMONIZATION_METHOD
    contributing_lst_windows: Tuple[Tuple[str, str], ...] = ()
    contributing_air_windows: Tuple[Tuple[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "lst_celsius": self.lst.value if self.lst is not None else None,
            "lst": self.lst.to_dict() if self.lst is not None else None,
            "air_temperature_celsius": (
                self.air.value if self.air is not None else None
            ),
            "air": self.air.to_dict() if self.air is not None else None,
            "harmonization_method": self.harmonization_method,
            "contributing_lst_windows": [
                list(window) for window in self.contributing_lst_windows
            ],
            "contributing_air_windows": [
                list(window) for window in self.contributing_air_windows
            ],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalHarmonizedPeriod":
        """Rebuild a period from :meth:`to_dict` output."""
        lst_payload = payload.get("lst")
        air_payload = payload.get("air")
        return cls(
            window_start=payload["window_start"],
            window_end=payload["window_end"],
            lst=(
                ThermalProfilePoint.from_dict(lst_payload)
                if lst_payload is not None
                else None
            ),
            air=(
                ThermalProfilePoint.from_dict(air_payload)
                if air_payload is not None
                else None
            ),
            harmonization_method=payload.get(
                "harmonization_method", HARMONIZATION_METHOD
            ),
            contributing_lst_windows=tuple(
                (window[0], window[1])
                for window in payload.get("contributing_lst_windows") or ()
            ),
            contributing_air_windows=tuple(
                (window[0], window[1])
                for window in payload.get("contributing_air_windows") or ()
            ),
        )


@dataclass(frozen=True)
class ThermalHarmonizedProfile:
    """Chronological monthly pairing of LST with air temperature."""

    window_start: str
    window_end: str
    step: str = STEP_CALENDAR_MONTH
    harmonization: str = HARMONIZATION_MONTHLY
    harmonization_method: str = HARMONIZATION_METHOD
    limitations: Tuple[str, ...] = _HARMONIZED_LIMITATIONS
    periods: Tuple[ThermalHarmonizedPeriod, ...] = field(
        default_factory=tuple
    )

    @property
    def n_periods(self) -> int:
        """Total months emitted, including months missing on one side."""
        return len(self.periods)

    @property
    def n_with_lst(self) -> int:
        """Months carrying a finite LST observation."""
        return sum(
            1
            for period in self.periods
            if period.lst is not None
            and _is_usable_value(period.lst.value)
        )

    @property
    def n_with_air(self) -> int:
        """Months carrying a finite air-temperature observation."""
        return sum(
            1
            for period in self.periods
            if period.air is not None
            and _is_usable_value(period.air.value)
        )

    @property
    def n_with_both(self) -> int:
        """Months carrying both observations."""
        return sum(
            1
            for period in self.periods
            if period.lst is not None
            and period.air is not None
            and _is_usable_value(period.lst.value)
            and _is_usable_value(period.air.value)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form; JSON-serialisable."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "harmonization": self.harmonization,
            "harmonization_method": self.harmonization_method,
            "limitations": list(self.limitations),
            "periods": [period.to_dict() for period in self.periods],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ThermalHarmonizedProfile":
        """Rebuild a profile from :meth:`to_dict` output."""
        return cls(
            window_start=payload["window_start"],
            window_end=payload["window_end"],
            step=payload.get("step", STEP_CALENDAR_MONTH),
            harmonization=payload.get(
                "harmonization", HARMONIZATION_MONTHLY
            ),
            harmonization_method=payload.get(
                "harmonization_method", HARMONIZATION_METHOD
            ),
            limitations=tuple(payload.get("limitations") or ()),
            periods=tuple(
                ThermalHarmonizedPeriod.from_dict(item)
                for item in payload.get("periods") or ()
            ),
        )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _is_usable_value(value: Any) -> bool:
    """Finite numbers only: None, NaN, infinities, and bools are gaps."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def month_windows(start_date: str, end_date: str) -> List[Tuple[str, str]]:
    """Calendar-month sub-windows intersecting ``[start_date, end_date]``.

    Thin wrapper over the repository's :func:`get_monthly_periods`
    so thermal profile code depends on one documented month
    semantic (edge months snap to calendar-month boundaries, as in
    P1.1 and the phenology calendar-month means).
    """
    return [
        (window_start, window_end)
        for window_start, window_end in get_monthly_periods(
            start_date, end_date
        )
    ]


def usable_values(profile: ThermalSourceProfile) -> List[float]:
    """Finite observation values in chronological order, gaps dropped.

    Structural selection for later phases. This helper selects; it
    never fills, smooths, or otherwise transforms.
    """
    return [
        float(point.value)
        for point in profile.points
        if _is_usable_value(point.value)
    ]


def thermal_metadata(metric_key: str) -> Dict[str, Any]:
    """Source identity contract for a supported thermal metric.

    Reports the production dataset, band, physical quantity,
    measurement basis, and temporal resolution from the metric and
    registry themselves — nothing here is inferred.
    """
    if metric_key not in SUPPORTED_THERMAL_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_THERMAL_PROFILE_METRICS))
        raise ValueError(
            f"Thermal profiles are not supported for {metric_key!r}. "
            f"Supported thermal metrics: {supported}."
        )
    probe = SUPPORTED_THERMAL_PROFILE_METRICS[metric_key]()
    dataset = probe.primary_dataset()
    band_name = _band_for(metric_key)
    band_spec = dataset.band(band_name)
    return {
        "metric_key": metric_key,
        "profile_kind": _PROFILE_KIND_BY_METRIC[metric_key],
        "dataset_id": dataset.id,
        "fallback_dataset_id": _FALLBACK_BY_METRIC[metric_key],
        "band": band_name,
        "physical_quantity": _QUANTITY_BY_METRIC[metric_key],
        "measurement_basis": probe.measurement_basis.value,
        "temporal_resolution": dataset.temporal_resolution,
        "unit": probe.unit,
        "native_unit": band_spec.unit,
        "scale_factor": band_spec.scale_factor,
        "offset": band_spec.offset,
    }


def _band_for(metric_key: str) -> str:
    if metric_key == LST_METRIC_KEY:
        return LST_SOURCE_BAND
    return AIR_SOURCE_BAND


def _limitations_for(metric_key: str) -> Tuple[str, ...]:
    if metric_key == LST_METRIC_KEY:
        return _LST_PROFILE_LIMITATIONS
    return _AIR_PROFILE_LIMITATIONS


def _missing_point(
    window_start: str,
    window_end: str,
    unit: str,
    metric_key: str,
    source_dataset_id: str,
    temporal_resolution: str,
    quality: str = "unavailable",
) -> ThermalProfilePoint:
    return ThermalProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=None,
        unit=unit,
        quality=quality,
        coverage_percent=None,
        image_count=None,
        source_dataset_id=source_dataset_id,
        source_band=_band_for(metric_key),
        physical_quantity=_QUANTITY_BY_METRIC[metric_key],
        aggregation_method="time mean, then spatial mean",
        temporal_resolution=temporal_resolution,
        provenance={},
    )


def _point_from_result(
    window_start: str,
    window_end: str,
    metric_key: str,
    unit: str,
    result: Any,
) -> ThermalProfilePoint:
    """Translate one sub-window metric result into a profile point.

    The selected source is read from the result's own provenance
    (the production metric's selection), never assumed. Quality,
    coverage, and image count are preserved verbatim.
    """
    value = result.value if _is_usable_value(result.value) else None
    provenance = getattr(result, "provenance", None)
    quality = "unavailable"
    image_count: Optional[int] = None
    source_dataset_id = ""
    source_band = _band_for(metric_key)
    aggregation_method = "time mean, then spatial mean"
    temporal_resolution = ""
    provenance_dict: Dict[str, Any] = {}
    if provenance is not None:
        quality_level = provenance.quality_level
        quality = (
            quality_level.value
            if hasattr(quality_level, "value")
            else str(quality_level)
        )
        image_count = provenance.image_count
        source_dataset_id = provenance.source_dataset_id or ""
        bands = list(getattr(provenance, "bands", None) or ())
        if bands:
            source_band = bands[0]
        aggregation_method = (
            provenance.aggregation_method or aggregation_method
        )
        provenance_dict = provenance.to_dict()
        try:
            from app.services.agriculture.registry import get_dataset

            temporal_resolution = get_dataset(
                source_dataset_id
            ).temporal_resolution
        except Exception:  # noqa: BLE001 - resolution is metadata, never fatal
            temporal_resolution = ""
    coverage: Optional[float] = None
    stats = getattr(result, "stats", None)
    if stats is not None:
        raw_coverage = getattr(stats, "coverage_percent", None)
        if isinstance(raw_coverage, (int, float)) and math.isfinite(
            raw_coverage
        ):
            coverage = float(raw_coverage)
    return ThermalProfilePoint(
        window_start=window_start,
        window_end=window_end,
        value=float(value) if value is not None else None,
        unit=unit,
        quality=quality,
        coverage_percent=coverage,
        image_count=image_count,
        source_dataset_id=source_dataset_id,
        source_band=source_band,
        physical_quantity=_QUANTITY_BY_METRIC[metric_key],
        aggregation_method=aggregation_method,
        temporal_resolution=temporal_resolution,
        provenance=provenance_dict,
    )


# --------------------------------------------------------------------------
# Source-native profile builders
# --------------------------------------------------------------------------


def build_thermal_source_profile(
    metric_key: str, context: MetricContext
) -> ThermalSourceProfile:
    """Build the monthly observation profile for one thermal quantity.

    Every intersecting calendar month is emitted exactly once, in
    chronological order, by running the quantity's own production
    ``compute`` on that month's sub-context (geometry, scale, cloud
    tolerance, and options carried over unchanged). A month that
    lies outside source coverage becomes an ``"unavailable"``
    point without an EE call; a month that cannot be computed —
    no scenes, full masking, non-finite reduction, or a raised
    exception — becomes a missing point carrying the metric's own
    verdict, never a zero and never an interpolation of its
    neighbours.

    Raises:
        ValueError: when ``metric_key`` is not a supported thermal
            profile metric.
        DateRangeError: when the requested window is malformed or
            empty, via the repository's own window validation.
    """
    if metric_key not in SUPPORTED_THERMAL_PROFILE_METRICS:
        supported = ", ".join(sorted(SUPPORTED_THERMAL_PROFILE_METRICS))
        raise ValueError(
            f"Thermal profiles are not supported for {metric_key!r}. "
            f"Supported thermal metrics: {supported}."
        )
    validate_date_range(context.start_date, context.end_date)

    metric_cls = SUPPORTED_THERMAL_PROFILE_METRICS[metric_key]
    probe = metric_cls()
    meta = thermal_metadata(metric_key)
    unit = probe.unit

    windows = month_windows(context.start_date, context.end_date)

    can_attempt, _reason = probe.can_attempt(context)
    if not can_attempt:
        logger.warning(
            "Thermal profile for %s: requested window %s to %s is "
            "outside the source coverage, emitting %d missing month(s) "
            "without running observations.",
            metric_key,
            context.start_date,
            context.end_date,
            len(windows),
        )
        return ThermalSourceProfile(
            profile_kind=_PROFILE_KIND_BY_METRIC[metric_key],
            metric_key=metric_key,
            dataset_id=meta["dataset_id"],
            fallback_dataset_id=meta["fallback_dataset_id"],
            band=meta["band"],
            unit=unit,
            physical_quantity=meta["physical_quantity"],
            physical_quantity_label=(
                PHYSICAL_QUANTITY_LST_LABEL
                if metric_key == LST_METRIC_KEY
                else PHYSICAL_QUANTITY_AIR_LABEL
            ),
            measurement_basis=meta["measurement_basis"],
            temporal_resolution=meta["temporal_resolution"],
            aggregation_method="time mean, then spatial mean",
            window_start=context.start_date,
            window_end=context.end_date,
            limitations=_limitations_for(metric_key),
            points=tuple(
                _missing_point(
                    window_start,
                    window_end,
                    unit,
                    metric_key,
                    meta["dataset_id"],
                    meta["temporal_resolution"],
                )
                for window_start, window_end in windows
            ),
        )

    points: List[ThermalProfilePoint] = []
    for window_start, window_end in windows:
        sub_context = replace(
            context, start_date=window_start, end_date=window_end
        )
        sub_can_attempt, _sub_reason = probe.can_attempt(sub_context)
        if not sub_can_attempt:
            points.append(
                _missing_point(
                    window_start,
                    window_end,
                    unit,
                    metric_key,
                    meta["dataset_id"],
                    meta["temporal_resolution"],
                )
            )
            continue
        try:
            result = metric_cls().compute(sub_context)
        except Exception as exc:  # noqa: BLE001 - one month cannot sink the profile
            logger.warning(
                "Thermal profile for %s: month %s to %s failed (%s); "
                "recording a missing observation.",
                metric_key,
                window_start,
                window_end,
                type(exc).__name__,
            )
            points.append(
                _missing_point(
                    window_start,
                    window_end,
                    unit,
                    metric_key,
                    meta["dataset_id"],
                    meta["temporal_resolution"],
                )
            )
            continue
        if result is None:
            points.append(
                _missing_point(
                    window_start,
                    window_end,
                    unit,
                    metric_key,
                    meta["dataset_id"],
                    meta["temporal_resolution"],
                )
            )
            continue
        points.append(
            _point_from_result(window_start, window_end, metric_key, unit, result)
        )

    return ThermalSourceProfile(
        profile_kind=_PROFILE_KIND_BY_METRIC[metric_key],
        metric_key=metric_key,
        dataset_id=meta["dataset_id"],
        fallback_dataset_id=meta["fallback_dataset_id"],
        band=meta["band"],
        unit=unit,
        physical_quantity=meta["physical_quantity"],
        physical_quantity_label=(
            PHYSICAL_QUANTITY_LST_LABEL
            if metric_key == LST_METRIC_KEY
            else PHYSICAL_QUANTITY_AIR_LABEL
        ),
        measurement_basis=meta["measurement_basis"],
        temporal_resolution=meta["temporal_resolution"],
        aggregation_method="time mean, then spatial mean",
        window_start=context.start_date,
        window_end=context.end_date,
        limitations=_limitations_for(metric_key),
        points=tuple(points),
    )


def build_lst_profile(context: MetricContext) -> ThermalSourceProfile:
    """Build the MODIS land-surface temperature monthly profile.

    Source-native ``LST_PROFILE``: daytime LST window means from
    ``MODIS/061/MOD11A2`` via the production
    ``land_surface_temperature_day`` metric.
    """
    return build_thermal_source_profile(LST_METRIC_KEY, context)


def build_air_temperature_profile(
    context: MetricContext,
) -> ThermalSourceProfile:
    """Build the ERA5-Land 2 m air-temperature monthly profile.

    Source-native ``AIR_TEMPERATURE_PROFILE``: modelled air
    temperature window means from ``ECMWF/ERA5_LAND/DAILY_AGGR``
    band ``temperature_2m`` via the production ``temperature_mean``
    metric.
    """
    return build_thermal_source_profile(AIR_METRIC_KEY, context)


# --------------------------------------------------------------------------
# Harmonization
# --------------------------------------------------------------------------


def harmonize_thermal_monthly(
    lst_profile: ThermalSourceProfile,
    air_profile: ThermalSourceProfile,
) -> ThermalHarmonizedProfile:
    """Pair an LST profile with an air-temperature profile by month.

    Each side must be the matching source-native profile kind; a
    swapped or foreign profile is rejected rather than paired.
    The union of calendar months from both profiles is emitted in
    chronological order; a month present on only one side, or
    missing a usable observation on one side, still yields a
    period with that side recorded as missing. No value is ever
    created where the source had none, the two sides are never
    averaged, and no canopy quantity is derived.

    Period-level quality is the preserved per-source pair, not a
    weakest-wins reduction: the sides are independent physical
    quantities and must not share one verdict.

    Raises:
        ValueError: when either profile is not the expected thermal
            source kind.
    """
    if lst_profile.profile_kind != THERMAL_PROFILE_KIND_LST:
        raise ValueError(
            f"harmonize_thermal_monthly expects an {THERMAL_PROFILE_KIND_LST} "
            f"profile for lst, got {lst_profile.profile_kind!r}."
        )
    if air_profile.profile_kind != THERMAL_PROFILE_KIND_AIR:
        raise ValueError(
            f"harmonize_thermal_monthly expects an "
            f"{THERMAL_PROFILE_KIND_AIR} profile for air, got "
            f"{air_profile.profile_kind!r}."
        )

    lst_by_window = {
        (point.window_start, point.window_end): point
        for point in lst_profile.points
    }
    air_by_window = {
        (point.window_start, point.window_end): point
        for point in air_profile.points
    }
    ordered_windows = sorted(set(lst_by_window) | set(air_by_window))

    periods: List[ThermalHarmonizedPeriod] = []
    for window_start, window_end in ordered_windows:
        lst_point = lst_by_window.get((window_start, window_end))
        air_point = air_by_window.get((window_start, window_end))
        periods.append(
            ThermalHarmonizedPeriod(
                window_start=window_start,
                window_end=window_end,
                lst=lst_point,
                air=air_point,
                harmonization_method=HARMONIZATION_METHOD,
                contributing_lst_windows=(
                    ((lst_point.window_start, lst_point.window_end),)
                    if lst_point is not None
                    else ()
                ),
                contributing_air_windows=(
                    ((air_point.window_start, air_point.window_end),)
                    if air_point is not None
                    else ()
                ),
            )
        )

    if ordered_windows:
        window_start = ordered_windows[0][0]
        window_end = ordered_windows[-1][1]
    else:
        window_start = lst_profile.window_start
        window_end = lst_profile.window_end

    return ThermalHarmonizedProfile(
        window_start=window_start,
        window_end=window_end,
        periods=tuple(periods),
    )


def build_thermal_harmonized_monthly(
    context: MetricContext,
) -> ThermalHarmonizedProfile:
    """Build both source profiles for one window and pair them monthly.

    Convenience over :func:`build_lst_profile`,
    :func:`build_air_temperature_profile`, and
    :func:`harmonize_thermal_monthly` sharing a single context, so
    both sides cover the same calendar months.
    """
    lst_profile = build_lst_profile(context)
    air_profile = build_air_temperature_profile(context)
    return harmonize_thermal_monthly(lst_profile, air_profile)
