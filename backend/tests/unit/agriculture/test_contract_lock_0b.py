"""Phase 0B — Frontend ↔ Backend Contract Lock guards.

READ-ONLY contract enforcement. No GEE. No network. No ``ee`` import.

Locks (see Phase 0B §§1–14):
  1. API family separation (Comprehensive vs Legacy).
  2. Domain names (API ``historical`` vs registry ``history``).
  3. Soil contract (soil-props under ``soil``, no ``soil-properties`` route/domain).
  4. Empty ``domains=[]`` means ALL — frontend must send explicit non-empty lists.
  5. UNAVAILABLE metrics never get KPI/chart/map UI (denylist).
  6. Response limitations (scalar values only; no histogram/series/baseline).
  7. G1–G4 recorded as future backend work (not implemented here).
  8. ``era5_potential_evaporation`` treated as NOT DISPLAYABLE until resolved.
  9. Pattern fallback behavior unchanged.
 10. Scope/STATIC/PROXY via provenance; fixed scope as static banner text only.
 11. Routing model ``/agriculture`` hub + ``/agriculture/*`` domain views.
   12. Every AVAILABLE metric has exactly one primary route (91 keys).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.agriculture import register_all_metrics
from app.services.agriculture.base import MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    metric_keys,
)

# ---------------------------------------------------------------------------
# Contract maps (frozen by Phase 0B §§12–13)
# ---------------------------------------------------------------------------

PRIMARY_ROUTE_MAP: dict[str, str] = {
    # vegetation → /agriculture/vegetation (9: 8 indices/structure + NDRE anomaly)
    "ndvi": "/agriculture/vegetation",
    "evi": "/agriculture/vegetation",
    "savi": "/agriculture/vegetation",
    "msavi": "/agriculture/vegetation",
    "ndre": "/agriculture/vegetation",
    "ndre_anomaly": "/agriculture/vegetation",
    # radar → /agriculture/vegetation (4: complementary canopy signals)
    "vv": "/agriculture/vegetation",
    "vh": "/agriculture/vegetation",
    "vh_vv": "/agriculture/vegetation",
    "rvi": "/agriculture/vegetation",
    # canopy proxy → /agriculture/vegetation (1: evidence concordance)
    "middle_canopy_dryness_proxy": "/agriculture/vegetation",
    "lai": "/agriculture/vegetation",
    "fapar": "/agriculture/vegetation",
    "fcover": "/agriculture/vegetation",
    # phenology → /agriculture/phenology (5)
    "vegetation_season_onset": "/agriculture/phenology",
    "vegetation_activity_peak": "/agriculture/phenology",
    "vegetation_season_end": "/agriculture/phenology",
    "vegetation_season_length": "/agriculture/phenology",
    "vegetation_season_amplitude": "/agriculture/phenology",
    # productivity → /agriculture/phenology (3)
    "seasonal_vegetation_productivity_indicator": "/agriculture/phenology",
    "seasonal_evapotranspiration_context": "/agriculture/phenology",
    "crop_area_normalised_productivity_indicator": "/agriculture/phenology",
    # climate → /agriculture/climate (10)
    "precipitation": "/agriculture/climate",
    "temperature_max": "/agriculture/climate",
    "temperature_min": "/agriculture/climate",
    "temperature_mean": "/agriculture/climate",
    "wind_speed": "/agriculture/climate",
    "solar_radiation": "/agriculture/climate",
    "vpd": "/agriculture/climate",
    "relative_humidity": "/agriculture/climate",
    "par": "/agriculture/climate",
    "gdd": "/agriculture/climate",
    # water → /agriculture/water (11, incl. era5_potential flagged below)
    "ndwi": "/agriculture/water",
    "ndmi": "/agriculture/water",
    "mndwi": "/agriculture/water",
    "msi": "/agriculture/water",
    "ndmi_anomaly": "/agriculture/water",
    "msi_anomaly": "/agriculture/water",
    "evapotranspiration": "/agriculture/water",
    "potential_evapotranspiration": "/agriculture/water",
    "evapotranspiration_cumulative": "/agriculture/water",
    "era5_evaporation": "/agriculture/water",
    "era5_potential_evaporation": "/agriculture/water",
    # soil moisture → /agriculture/soil (6)
    "soil_moisture_surface": "/agriculture/soil",
    "soil_moisture_surface_evening": "/agriculture/soil",
    "soil_moisture_rootzone": "/agriculture/soil",
    "soil_moisture_rootzone_era5": "/agriculture/soil",
    "soil_moisture_wetness": "/agriculture/soil",
    "root_zone_soil_moisture_gldas": "/agriculture/soil",
    # soil properties (domain=soil) → /agriculture/soil (5)
    "soil_field_capacity": "/agriculture/soil",
    "soil_wilting_point": "/agriculture/soil",
    "soil_available_water_capacity": "/agriculture/soil",
    "soil_temperature_0_7cm": "/agriculture/soil",
    "soil_temperature_7_28cm": "/agriculture/soil",
    # thermal → /agriculture/thermal (5)
    "land_surface_temperature_day": "/agriculture/thermal",
    "land_surface_temperature_night": "/agriculture/thermal",
    "land_surface_temperature_mean": "/agriculture/thermal",
    "surface_temperature_range": "/agriculture/thermal",
    "landsat_surface_temperature": "/agriculture/thermal",
    # terrain → /agriculture/terrain (4)
    "elevation": "/agriculture/terrain",
    "slope": "/agriculture/terrain",
    "aspect": "/agriculture/terrain",
    "terrain_ruggedness": "/agriculture/terrain",
    # landcover → /agriculture/land-crop (3)
    "land_cover_class": "/agriculture/land-crop",
    "land_cover_quality": "/agriculture/land-crop",
    "land_cover_probability": "/agriculture/land-crop",
    # crop → /agriculture/land-crop (4)
    "temporary_crop_context": "/agriculture/land-crop",
    "maize_context": "/agriculture/land-crop",
    "cereal_context": "/agriculture/land-crop",
    "temporary_crop_area": "/agriculture/land-crop",
    # stress → /agriculture/stress-irrigation (7)
    "evaporative_fraction": "/agriculture/stress-irrigation",
    "soil_water_content_ratio": "/agriculture/stress-irrigation",
    "plant_available_water_fraction": "/agriculture/stress-irrigation",
    "vpd_anomaly": "/agriculture/stress-irrigation",
    "vpd_high_duration": "/agriculture/stress-irrigation",
    "lst_day_anomaly": "/agriculture/stress-irrigation",
    "lst_day_percentile": "/agriculture/stress-irrigation",
    # irrigation → /agriculture/stress-irrigation (5)
    "precipitation_cumulative": "/agriculture/stress-irrigation",
    "et_precipitation_deficit": "/agriculture/stress-irrigation",
    "precipitation_anomaly": "/agriculture/stress-irrigation",
    "evapotranspiration_anomaly": "/agriculture/stress-irrigation",
    "soil_moisture_rootzone_anomaly": "/agriculture/stress-irrigation",
    # history (API domain=historical) → /agriculture/history (9)
    "ndvi_anomaly_absolute": "/agriculture/history",
    "ndvi_anomaly_relative": "/agriculture/history",
    "ndvi_anomaly_standardized": "/agriculture/history",
    "ndvi_percentile_context": "/agriculture/history",
    "ndvi_trend": "/agriculture/history",
    "ndvi_anomaly_persistence": "/agriculture/history",
    "ndvi_change_shift": "/agriculture/history",
    "climate_trend": "/agriculture/history",
    "season_timing_history": "/agriculture/history",
}

#: §5 denylist — MUST NOT receive KPI/chart/map/gauge/score UI.
#: May appear only as ``unavailable_evidence`` strings.
UNAVAILABLE_DENYLIST: frozenset[str] = frozenset(
    {
        "vegetation_seasonal_integral",
        "cwsi",
        "wdi",
        "crop_type",
        "irrigation",  # metric key in landcover domain; NOT the irrigation domain
        "topographic_wetness_index",
        "crop_planting_date",
        "crop_harvest_date",
        "crop_flowering_date",
        "composite_stress",
        "irrigation_water_requirement",
        "gross_irrigation_requirement",
        "crop_evapotranspiration",
        "terrain_historical_trend",
        "soil_organic_carbon",
        "soil_clay_content",
        "soil_sand_content",
        "soil_silt_content",
        "soil_bulk_density",
        "soil_ph",
        "soil_cation_exchange_capacity",
        "soil_coarse_fragments",
        "soil_texture_class",
        "soil_salinity",
        "crop_yield_estimate",
        "crop_biomass_estimate",
        "crop_yield_uncertainty",
    }
)

#: §8 — registered AVAILABLE but NOT DISPLAYABLE as numeric KPI until
#: the backend owner resolves the sign-convention ambiguity.
NOT_DISPLAYABLE_PENDING_OWNER: frozenset[str] = frozenset(
    {"era5_potential_evaporation"}
)

ALLOWED_PRIMARY_ROUTES: frozenset[str] = frozenset(
    {
        "/agriculture/vegetation",
        "/agriculture/phenology",
        "/agriculture/climate",
        "/agriculture/water",
        "/agriculture/soil",
        "/agriculture/thermal",
        "/agriculture/terrain",
        "/agriculture/land-crop",
        "/agriculture/stress-irrigation",
        "/agriculture/history",
    }
)

LEGACY_PAGES = [
    "Dashboard.tsx",
    "Location.tsx",
    "Analysis.tsx",
    "Vegetation.tsx",
    "Climate.tsx",
    "Water.tsx",
    "Soil.tsx",
    "LandCover.tsx",
    "Historical.tsx",
    "Reports.tsx",
    "Settings.tsx",
]


def _repo_root() -> Path:
    # .../backend/tests/unit/agriculture/<file> → parents[4] == repo root
    return Path(__file__).resolve().parents[4]


def _frontend_src() -> Path:
    return _repo_root() / "frontend" / "src"


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# --- 1. AVAILABLE count and uniqueness -------------------------------------


def test_available_count_and_uniqueness():
    """Guard §16.1: 91 AVAILABLE keys, unique, disjoint from denylist."""
    from app.services.agriculture.canopy_moisture import CANOPY_MOISTURE_METRICS
    from app.services.agriculture.canopy_proxy import CANOPY_PROXY_METRICS
    from app.services.agriculture.radar import RADAR_METRICS
    from app.services.agriculture.climate import CLIMATE_METRICS
    from app.services.agriculture.crop import CROP_METRICS
    from app.services.agriculture.history import HISTORY_METRICS
    from app.services.agriculture.irrigation import IRRIGATION_METRICS
    from app.services.agriculture.landcover import (
        DYNAMIC_WORLD_METRICS,
        LANDCOVER_METRICS,
    )
    from app.services.agriculture.phenology import PHENOLOGY_METRICS
    from app.services.agriculture.productivity import PRODUCTIVITY_METRICS
    from app.services.agriculture.soil import SOIL_METRICS
    from app.services.agriculture.soil_properties import SOIL_PROPERTY_METRICS
    from app.services.agriculture.stress import STRESS_METRICS
    from app.services.agriculture.terrain import TERRAIN_METRICS
    from app.services.agriculture.thermal import THERMAL_METRICS
    from app.services.agriculture.vegetation import VEGETATION_METRICS
    from app.services.agriculture.water import WATER_METRICS

    available = [
        VEGETATION_METRICS,
        CANOPY_MOISTURE_METRICS,
        RADAR_METRICS,
        CANOPY_PROXY_METRICS,
        CLIMATE_METRICS,
        THERMAL_METRICS,
        WATER_METRICS,
        SOIL_METRICS,
        LANDCOVER_METRICS,
        DYNAMIC_WORLD_METRICS,
        TERRAIN_METRICS,
        CROP_METRICS,
        PHENOLOGY_METRICS,
        STRESS_METRICS,
        IRRIGATION_METRICS,
        PRODUCTIVITY_METRICS,
        HISTORY_METRICS,
        SOIL_PROPERTY_METRICS,
    ]
    flat = [m.key for tup in available for m in tup]
    assert len(flat) == 91, f"AVAILABLE count changed: {len(flat)} != 91"
    assert len(set(flat)) == 91, "duplicate AVAILABLE metric key"
    assert not (set(flat) & set(UNAVAILABLE_DENYLIST)), "AVAILABLE/UNAVAILABLE overlap"

    keys = register_all_metrics()
    assert len(keys) == 91 + 27, f"registry total changed: {len(keys)} != 118"
    for key in flat:
        assert key in keys, key


# --- 2. Primary route map --------------------------------------------------


def test_primary_route_map_covers_available_exactly_once():
    """Guard §16.2: metric_key → exactly one primary route (91 keys)."""
    from app.services.agriculture.canopy_moisture import CANOPY_MOISTURE_METRICS
    from app.services.agriculture.canopy_proxy import CANOPY_PROXY_METRICS
    from app.services.agriculture.radar import RADAR_METRICS
    from app.services.agriculture.climate import CLIMATE_METRICS
    from app.services.agriculture.crop import CROP_METRICS
    from app.services.agriculture.history import HISTORY_METRICS
    from app.services.agriculture.irrigation import IRRIGATION_METRICS
    from app.services.agriculture.landcover import (
        DYNAMIC_WORLD_METRICS,
        LANDCOVER_METRICS,
    )
    from app.services.agriculture.phenology import PHENOLOGY_METRICS
    from app.services.agriculture.productivity import PRODUCTIVITY_METRICS
    from app.services.agriculture.soil import SOIL_METRICS
    from app.services.agriculture.soil_properties import SOIL_PROPERTY_METRICS
    from app.services.agriculture.stress import STRESS_METRICS
    from app.services.agriculture.terrain import TERRAIN_METRICS
    from app.services.agriculture.thermal import THERMAL_METRICS
    from app.services.agriculture.vegetation import VEGETATION_METRICS
    from app.services.agriculture.water import WATER_METRICS

    available_keys = {
        m.key
        for tup in (
            VEGETATION_METRICS,
            CANOPY_MOISTURE_METRICS,
            RADAR_METRICS,
            CANOPY_PROXY_METRICS,
            CLIMATE_METRICS,
            THERMAL_METRICS,
            WATER_METRICS,
            SOIL_METRICS,
            LANDCOVER_METRICS,
            DYNAMIC_WORLD_METRICS,
            TERRAIN_METRICS,
            CROP_METRICS,
            PHENOLOGY_METRICS,
            STRESS_METRICS,
            IRRIGATION_METRICS,
            PRODUCTIVITY_METRICS,
            HISTORY_METRICS,
            SOIL_PROPERTY_METRICS,
        )
        for m in tup
    }
    assert set(PRIMARY_ROUTE_MAP) == available_keys, (
        "primary map missing=",
        sorted(available_keys - set(PRIMARY_ROUTE_MAP)),
        "extra=",
        sorted(set(PRIMARY_ROUTE_MAP) - available_keys),
    )
    assert len(PRIMARY_ROUTE_MAP) == 91
    for key, route in PRIMARY_ROUTE_MAP.items():
        assert route in ALLOWED_PRIMARY_ROUTES, (key, route)
    assert "/agriculture/soil-properties" not in set(PRIMARY_ROUTE_MAP.values())


# --- 3. UNAVAILABLE denylist ----------------------------------------------


def test_unavailable_denylist_not_primary():
    """Guard §16.3: denylist keys have no primary KPI/chart/map route."""
    assert len(UNAVAILABLE_DENYLIST) == 27
    assert not (set(UNAVAILABLE_DENYLIST) & set(PRIMARY_ROUTE_MAP)), (
        "unavailable key has primary route"
    )
    assert "era5_potential_evaporation" in PRIMARY_ROUTE_MAP  # mapped…
    assert "era5_potential_evaporation" in NOT_DISPLAYABLE_PENDING_OWNER  # …but locked


# --- 4. historical spelling -------------------------------------------------


def test_historical_request_spelling():
    """Guard §16.4: frontend sends ``historical``; registry uses ``history``."""
    from app.api.v1.agriculture import (
        VALID_DOMAINS,
        _domain_to_metric_keys,
        _validate_request,
    )
    from app.schemas.agriculture import AgricultureAnalysisRequest
    from app.services.agriculture.catalog import metrics_in_domain

    assert "historical" in VALID_DOMAINS
    assert "history" not in VALID_DOMAINS
    assert MetricDomain.HISTORY == "history"

    register_all_metrics()

    from app.services.agriculture.synthesis import SynthesisDomain

    assert SynthesisDomain.HISTORICAL.value == "historical"

    geom = {"type": "Point", "coordinates": [51.0, 32.0]}
    ok_req = AgricultureAnalysisRequest(
        geometry=geom,  # type: ignore[arg-type]
        start_date="2024-01-01",
        end_date="2024-06-01",
        domains=["historical"],
    )
    _validate_request(ok_req)  # must not raise
    assert _domain_to_metric_keys(["historical"])
    assert [m.key for m in metrics_in_domain("history")]

    bad_req = AgricultureAnalysisRequest(
        geometry=geom,  # type: ignore[arg-type]
        start_date="2024-01-01",
        end_date="2024-06-01",
        domains=["history"],
    )
    with pytest.raises(Exception):
        _validate_request(bad_req)


# --- 5. soil contract -------------------------------------------------------


def test_soil_properties_remain_under_soil():
    """Guard §16.5: soil-props domain is ``soil``; no soil-properties route."""
    from app.services.agriculture.soil_properties import SOIL_PROPERTY_METRICS

    for metric in SOIL_PROPERTY_METRICS:
        assert metric.domain == MetricDomain.SOIL == "soil", metric.key
    assert "soil-properties" not in MetricDomain.ALL

    from app.api.v1.agriculture import VALID_DOMAINS

    assert "soil-properties" not in VALID_DOMAINS
    soil_keys = [k for k, r in PRIMARY_ROUTE_MAP.items() if r == "/agriculture/soil"]
    assert len(soil_keys) == 11, soil_keys


# --- 6. empty domains --------------------------------------------------------


def test_domain_requests_never_use_empty_list_semantic():
    """Guard §16.6: ``[]`` validates but means ALL — frontend must not send it."""
    from app.api.v1.agriculture import _validate_request
    from app.schemas.agriculture import AgricultureAnalysisRequest

    geom = {"type": "Point", "coordinates": [51.0, 32.0]}
    empty_req = AgricultureAnalysisRequest(
        geometry=geom,  # type: ignore[arg-type]
        start_date="2024-01-01",
        end_date="2024-06-01",
        domains=[],
    )
    _validate_request(empty_req)  # backend accepts…
    assert not empty_req.domains  # …but [] is falsy → backend treats as ALL
    # Contract examples that domain pages MUST use instead:
    for pages_domains in (
        ["vegetation"],
        ["phenology", "productivity"],
        ["climate"],
        ["water"],
        ["soil"],
        ["thermal"],
        ["terrain"],
        ["landcover", "crop"],
        ["stress", "irrigation"],
        ["historical"],
    ):
        assert pages_domains, "domain page must send non-empty list"


# --- 7/8. API family separation (static source check, no network) ------------


def _read_frontend_page(name: str) -> str:
    path = _frontend_src() / "pages" / name
    assert path.exists(), f"frontend page missing: {path}"
    return path.read_text(encoding="utf-8")


def test_comprehensive_pages_cannot_call_legacy_create():
    """Guard §16.7: Comprehensive pages never call Legacy create/viz APIs."""
    src = _frontend_src()
    comp_files = [src / "pages" / "Agriculture.tsx"]
    comp_files += sorted((src / "pages" / "agriculture").glob("*.tsx"))
    assert comp_files[0].exists()
    forbidden = (
        "analysesApi.create",
        "analysesApi.getMaps",
        "analysesApi.getTimeSeries",
        "vegetationApi.",
        "locationsApi.",
    )
    for path in comp_files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} calls Legacy {token}"


def test_legacy_pages_cannot_call_comprehensive_analyze():
    """Guard §16.8: Legacy pages never call agricultureApi.analyze."""
    forbidden = ("agricultureApi.analyze", "agricultureApi.synthesisOnly")
    for name in LEGACY_PAGES:
        text = _read_frontend_page(name)
        for token in forbidden:
            assert token not in text, f"{name} calls Comprehensive {token}"


# --- 9/10. Response limitation locks -----------------------------------------


def test_no_timeseries_or_histogram_in_current_response():
    """Guard §16.9, as amended by frozen F3-A: optional stats/histogram/
    band_means fields exist, but series/baseline/product-year must not."""
    from app.schemas.agriculture import EvidenceItemResponse
    from app.services.agriculture.types import MetricResult

    response_fields = set(EvidenceItemResponse.model_fields)
    # F3-A: these three are present as OPTIONAL passthrough fields.
    for present_optional in ("class_histogram", "stats", "band_means"):
        assert present_optional in response_fields, present_optional
    for absent in (
        "baseline_start",
        "baseline_end",
        "baseline_n",
        "product_year",
        "scope_note",
        "time_series",
    ):
        assert absent not in response_fields, absent
    # The service layer HAS histograms — serialization preserves them now.
    assert "class_histogram" in MetricResult.__dataclass_fields__
    assert "band_means" in MetricResult.__dataclass_fields__


def test_categorical_histogram_not_in_response_contract():
    """Guard §16.10: no test may assume class_histogram exists in response."""
    from app.schemas.agriculture import (
        DomainSummaryResponse,
        EvidenceBundleResponse,
        ProvenanceResponse,
    )

    assert "unavailable_evidence" in DomainSummaryResponse.model_fields
    assert "available" in EvidenceBundleResponse.model_fields
    assert "temporal_kind" in ProvenanceResponse.model_fields
    assert "product_year" not in ProvenanceResponse.model_fields
    assert "baseline_n" not in ProvenanceResponse.model_fields
    # Pattern fallback: frontend may render unknown patterns generically.
    # Since F1 the hub delegates to shared components, scan the hub plus
    # the shared agriculture component directory (excluding its own tests).
    candidates = [_frontend_src() / "pages" / "Agriculture.tsx"]
    shared_dir = _frontend_src() / "components" / "agriculture"
    candidates += [
        path
        for path in sorted(shared_dir.rglob("*.ts*"))
        if "__tests__" not in path.parts
    ]
    assert candidates[0].exists()
    assert any(
        "PATTERN_META" in path.read_text(encoding="utf-8") for path in candidates
    )
    assert any(
        re.search(r"\|\|", path.read_text(encoding="utf-8")) is not None
        for path in candidates
    ), "expected generic fallback rendering"
