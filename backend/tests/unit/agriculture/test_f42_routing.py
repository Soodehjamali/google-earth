"""F4.2 production-path tests — bundle enrichment + consistency lifecycle.

These tests exercise the real ``/analysis`` assembly
(``_build_evidence_bundles`` + ``SynthesisEngine.synthesise``), NOT
``evaluate_domain`` with hand-mixed bundles. They prove that the
existing synthesis rules fire when their declared inputs exist in
their real registry domains, that missing evidence stays missing,
that enrichment never fabricates or duplicates, and that the
consistency-check lifecycle runs inside bundle construction.

No GEE. No network. No ``ee`` import. No methodology changes.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from app.services.agriculture.catalog import clear_registry


@pytest.fixture(autouse=True)
def _registered():
    from app.services.agriculture import ensure_registered

    clear_registry()
    ensure_registered()
    yield
    clear_registry()


def _prov():
    from app.services.agriculture.types import (
        MeasurementBasis,
        Provenance,
        QualityLevel,
        TemporalKind,
    )

    return Provenance(
        source_dataset_id="TEST/SOURCE",
        source_dataset_name="Test source",
        measurement_basis=MeasurementBasis.DERIVED,
        quality_level=QualityLevel.GOOD,
        temporal_kind=TemporalKind.OBSERVATION,
        requested_start="2024-06-01",
        requested_end="2024-09-01",
    )


def _ok(key: str, value: float, unit: str = "index"):
    from app.services.agriculture.types import MetricResult

    return SimpleNamespace(
        result=MetricResult(
            metric_key=key,
            display_name=key,
            display_name_fa=key,
            value=value,
            unit=unit,
            provenance=_prov(),
        )
    )


def _unavailable(key: str):
    from app.services.agriculture.types import MetricResult

    return SimpleNamespace(
        result=MetricResult.unavailable(
            metric_key=key,
            display_name=key,
            display_name_fa=key,
            reason="not_supported",
            message="nope",
            unit="index",
        )
    )


def _assemble(outcomes: Dict[str, Any]):
    from app.api.v1.agriculture import _build_evidence_bundles

    return _build_evidence_bundles(outcomes)


def _synthesise(bundles):
    from app.services.agriculture.synthesis import SynthesisEngine

    return SynthesisEngine().synthesise(
        bundles,
        time_start=date(2024, 6, 1),
        time_end=date(2024, 9, 1),
    )


def _rule_ids(summary) -> list:
    return [s.rule_id for s in summary.statements]


# --- water ------------------------------------------------------------------


def test_water_rules_fire_via_production_path():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {
            "precipitation_anomaly": _ok("precipitation_anomaly", -0.8, "mm"),
            "soil_moisture_rootzone_anomaly": _ok(
                "soil_moisture_rootzone_anomaly", -0.6, "m3/m3"
            ),
            "evapotranspiration_anomaly": _ok(
                "evapotranspiration_anomaly", -0.4, "mm"
            ),
        }
    )
    water = bundles[SynthesisDomain.WATER]
    assert {
        "precipitation_anomaly",
        "soil_moisture_rootzone_anomaly",
        "evapotranspiration_anomaly",
    }.issubset({i.metric_key for i in water.items})
    synthesis = _synthesise(bundles)
    assert (
        "water_below_baseline"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.WATER])
    )


# --- vegetation ---------------------------------------------------------------


def test_vegetation_rules_fire_via_production_path():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {
            "ndvi_anomaly_absolute": _ok("ndvi_anomaly_absolute", -0.15),
            "ndvi_anomaly_relative": _ok("ndvi_anomaly_relative", -0.25),
        }
    )
    synthesis = _synthesise(bundles)
    assert (
        "vegetation_below_historical"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.VEGETATION])
    )


# --- thermal ------------------------------------------------------------------


def test_thermal_rule_fires_via_production_path():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble({"lst_day_anomaly": _ok("lst_day_anomaly", 2.5, "K")})
    synthesis = _synthesise(bundles)
    assert (
        "thermal_above_baseline"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.THERMAL])
    )


# --- soil ---------------------------------------------------------------------


def test_soil_rule_fires_via_production_path():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {"soil_moisture_rootzone_anomaly": _ok("soil_moisture_rootzone_anomaly", -0.7)}
    )
    synthesis = _synthesise(bundles)
    assert (
        "soil_moisture_below_baseline"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.SOIL])
    )


# --- phenology ----------------------------------------------------------------


def test_phenology_rule_fires_via_production_path():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {"season_timing_history": _ok("season_timing_history", 12.0, "days")}
    )
    synthesis = _synthesise(bundles)
    assert (
        "phenology_later_onset"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.PHENOLOGY])
    )


# --- previously reachable rules -------------------------------------------------


def test_productivity_and_historical_rules_still_work():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {
            "seasonal_vegetation_productivity_indicator": _ok(
                "seasonal_vegetation_productivity_indicator", -0.3
            ),
            "ndvi_percentile_context": _ok("ndvi_percentile_context", 10.0),
        }
    )
    synthesis = _synthesise(bundles)
    assert (
        "productivity_below_baseline"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.PRODUCTIVITY])
    )
    assert (
        "historical_low_percentile"
        in _rule_ids(synthesis.domain_summaries[SynthesisDomain.HISTORICAL])
    )


# --- cross-domain ---------------------------------------------------------------


def test_cross_domain_rules_still_work():
    bundles = _assemble(
        {
            "precipitation_anomaly": _ok("precipitation_anomaly", -0.8, "mm"),
            "soil_moisture_rootzone_anomaly": _ok(
                "soil_moisture_rootzone_anomaly", -0.6, "m3/m3"
            ),
            "evapotranspiration_anomaly": _ok(
                "evapotranspiration_anomaly", -0.4, "mm"
            ),
            "ndvi_anomaly_absolute": _ok("ndvi_anomaly_absolute", -0.15),
            "lst_day_anomaly": _ok("lst_day_anomaly", 2.5, "K"),
        }
    )
    synthesis = _synthesise(bundles)
    cross_ids = [s.rule_id for s in synthesis.cross_domain_statements]
    assert "cross_water_vegetation_below" in cross_ids
    assert "cross_water_thermal_opposite" in cross_ids


# --- missing evidence -------------------------------------------------------------


def test_missing_inputs_do_not_fire():
    from app.services.agriculture.synthesis import SynthesisDomain

    # Only one of three required water inputs: rule must stay silent.
    bundles = _assemble({"precipitation_anomaly": _ok("precipitation_anomaly", -0.8)})
    synthesis = _synthesise(bundles)
    assert (
        _rule_ids(synthesis.domain_summaries[SynthesisDomain.WATER]) == []
    )


def test_unusable_inputs_are_not_enriched():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {
            "precipitation_anomaly": _ok("precipitation_anomaly", -0.8, "mm"),
            "soil_moisture_rootzone_anomaly": _unavailable(
                "soil_moisture_rootzone_anomaly"
            ),
            "evapotranspiration_anomaly": _ok(
                "evapotranspiration_anomaly", -0.4, "mm"
            ),
        }
    )
    water = bundles[SynthesisDomain.WATER]
    assert "soil_moisture_rootzone_anomaly" not in {
        i.metric_key for i in water.items
    }
    synthesis = _synthesise(bundles)
    assert (
        _rule_ids(synthesis.domain_summaries[SynthesisDomain.WATER]) == []
    )


# --- integrity ----------------------------------------------------------------------


def test_enrichment_never_fabricates_or_duplicates():
    outcomes = {
        "precipitation_anomaly": _ok("precipitation_anomaly", -0.8, "mm"),
        "soil_moisture_rootzone_anomaly": _ok(
            "soil_moisture_rootzone_anomaly", -0.6, "m3/m3"
        ),
        "ndvi": _ok("ndvi", 0.6),
        "lst_day_anomaly": _ok("lst_day_anomaly", 2.5, "K"),
    }
    bundles = _assemble(outcomes)
    seen: Dict[str, int] = {}
    for bundle in bundles.values():
        keys = [i.metric_key for i in bundle.items]
        assert len(keys) == len(set(keys)), f"duplicates in {bundle.name}"
        for key in keys:
            assert key in outcomes, f"fabricated {key} in {bundle.name}"
            seen[key] = seen.get(key, 0) + 1
    # Home bundles keep their own items; enrichment only shares references.
    assert seen["precipitation_anomaly"] >= 1
    assert seen["ndvi"] == 1


# --- consistency lifecycle --------------------------------------------------------------


def test_compatible_bundle_lifecycle_unchanged():
    from app.services.agriculture.evidence import ConsistencyStatus
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {
            "ndvi": _ok("ndvi", 0.6),
            "evi": _ok("evi", 0.5),
        }
    )
    veg = bundles[SynthesisDomain.VEGETATION]
    # Pairwise checks run (entries recorded) but nothing conflicts:
    # no critical status, sufficiency assessed as before.
    assert all(
        c.status != ConsistencyStatus.CONFLICTING for c in veg.conflicts
    )
    assert veg.sufficiency is not None
    assert not veg.has_conflicts


def test_incompatible_units_produce_conflict_aware_sufficiency():
    from app.services.agriculture.synthesis import SynthesisDomain

    bundles = _assemble(
        {
            "temperature_mean": _ok("temperature_mean", 25.0, "degC"),
            "precipitation": _ok("precipitation", 100.0, "mm"),
        }
    )
    climate = bundles[SynthesisDomain.CLIMATE]
    assert len(climate.conflicts) > 0
    assert climate.has_conflicts
    assert climate.sufficiency is not None
    assert any(
        "conflict" in reason.lower()
        for reason in climate.sufficiency.key_reasons
    )
