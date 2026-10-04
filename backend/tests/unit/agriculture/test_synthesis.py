"""Tests for the Agricultural Intelligence Synthesis Layer (Phase P).

All tests are deterministic, seed-independent, and validate
bidirectional documentation claims.  No GEE calls, no database.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Dict, List, Optional, Sequence

import pytest

from app.services.agriculture.evidence import (
    ConsistencyStatus,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceItem,
    EvidenceStatus,
    SufficiencyLevel,
)
from app.services.agriculture.synthesis import (
    AgriculturalSynthesis,
    CROSS_DOMAIN_RULES,
    DEFAULT_RULES,
    HISTORICAL_RULES,
    PHENOLOGY_RULES,
    PRODUCTIVITY_RULES,
    SOIL_RULES,
    SynthesisDomain,
    SynthesisEngine,
    SynthesisRule,
    SynthesisStatement,
    THERMAL_RULES,
    VEGETATION_RULES,
    WATER_RULES,
    PatternState,
    DomainSummary,
)
from app.services.agriculture.types import QualityLevel


# ---------------------------------------------------------------------------
# 1. Helpers
# ---------------------------------------------------------------------------


def _make_item(
    metric_key: str,
    value: Optional[float],
    quality: QualityLevel = QualityLevel.GOOD,
    status: EvidenceStatus = EvidenceStatus.DERIVED,
    unit: str = "index",
    start: Optional[date] = None,
    end: Optional[date] = None,
    source: str = "era5_land",
) -> EvidenceItem:
    return EvidenceItem(
        metric_key=metric_key,
        value=value,
        unit=unit,
        status=status,
        temporal_start=start or date(2024, 7, 1),
        temporal_end=end or date(2024, 7, 31),
        quality_level=quality,
        provenance=None,
        source_dataset_id=source,
    )


def _make_bundle(
    name: str,
    items: List[EvidenceItem],
    conflicts: Optional[List[EvidenceConflict]] = None,
) -> EvidenceBundle:
    bundle = EvidenceBundle(
        name=name,
        items=items,
        conflicts=conflicts or [],
    )
    bundle.assess_sufficiency()
    return bundle


def _water_bundle(
    precip: float = -0.8,
    soil: float = -0.6,
    et: float = -0.4,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "water",
        [
            _make_item("precipitation_anomaly", precip, quality, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", soil, quality, source="smap_l4"),
            _make_item("evapotranspiration_anomaly", et, quality, source="modis_et"),
        ],
    )


def _veg_bundle(
    ndvi_abs: float = -0.15,
    ndvi_rel: float = -0.25,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "vegetation",
        [
            _make_item("ndvi_anomaly_absolute", ndvi_abs, quality, source="modis_ndvi"),
            _make_item("ndvi_anomaly_relative", ndvi_rel, quality, source="sentinel2_ndvi"),
        ],
    )


def _thermal_bundle(
    lst: float = 2.5,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "thermal",
        [_make_item("lst_day_anomaly", lst, quality, unit="K", source="modis_lst")],
    )


def _soil_bundle(
    sm: float = -0.7,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "soil",
        [_make_item("soil_moisture_rootzone_anomaly", sm, quality)],
    )


def _phenology_bundle(
    timing: float = 12.0,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "phenology",
        [_make_item("season_timing_history", timing, quality, unit="days", source="modis_phenology")],
    )


def _productivity_bundle(
    pvpi: float = -0.3,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "productivity",
        [_make_item("seasonal_vegetation_productivity_indicator", pvpi, quality, source="modis_productivity")],
    )


def _historical_bundle(
    pct: float = 15.0,
    quality: QualityLevel = QualityLevel.GOOD,
) -> EvidenceBundle:
    return _make_bundle(
        "historical",
        [_make_item("ndvi_percentile_context", pct, quality, unit="percent", source="modis_ndvi")],
    )


# ---------------------------------------------------------------------------
# 2. Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_default_rules_is_list(self) -> None:
        assert isinstance(DEFAULT_RULES, list)
        assert len(DEFAULT_RULES) > 0

    def test_domain_rule_lists(self) -> None:
        assert len(WATER_RULES) == 3
        assert len(VEGETATION_RULES) == 2
        assert len(THERMAL_RULES) == 1
        assert len(SOIL_RULES) == 1
        assert len(PHENOLOGY_RULES) == 2
        assert len(PRODUCTIVITY_RULES) == 1
        assert len(HISTORICAL_RULES) == 1
        assert len(CROSS_DOMAIN_RULES) == 2

    def test_all_rules_are_synthesis_rule(self) -> None:
        for rule in DEFAULT_RULES:
            assert isinstance(rule, SynthesisRule)

    def test_all_domains_covered(self) -> None:
        domains = {r.domain for r in DEFAULT_RULES}
        expected = {
            SynthesisDomain.WATER,
            SynthesisDomain.VEGETATION,
            SynthesisDomain.THERMAL,
            SynthesisDomain.SOIL,
            SynthesisDomain.PHENOLOGY,
            SynthesisDomain.PRODUCTIVITY,
            SynthesisDomain.HISTORICAL,
            SynthesisDomain.CROSS_DOMAIN,
        }
        assert domains == expected


# ---------------------------------------------------------------------------
# 3. PatternState and SynthesisDomain
# ---------------------------------------------------------------------------


class TestEnums:
    def test_pattern_states(self) -> None:
        assert PatternState.BELOW_CONTEXT.value == "below_context"
        assert PatternState.NEAR_CONTEXT.value == "near_context"
        assert PatternState.ABOVE_CONTEXT.value == "above_context"
        assert PatternState.MIXED_EVIDENCE.value == "mixed_evidence"
        assert PatternState.SUFFICIENT.value == "sufficient"
        assert PatternState.LIMITED.value == "limited"
        assert PatternState.INSUFFICIENT.value == "insufficient"
        assert PatternState.COHERENT.value == "coherent"
        assert PatternState.CONFLICTING.value == "conflicting"
        assert PatternState.UNAVAILABLE.value == "unavailable"

    def test_synthesis_domains(self) -> None:
        assert SynthesisDomain.VEGETATION.value == "vegetation"
        assert SynthesisDomain.WATER.value == "water"
        assert SynthesisDomain.THERMAL.value == "thermal"
        assert SynthesisDomain.SOIL.value == "soil"
        assert SynthesisDomain.CLIMATE.value == "climate"
        assert SynthesisDomain.CROP.value == "crop"
        assert SynthesisDomain.PHENOLOGY.value == "phenology"
        assert SynthesisDomain.PRODUCTIVITY.value == "productivity"
        assert SynthesisDomain.HISTORICAL.value == "historical"
        assert SynthesisDomain.CROSS_DOMAIN.value == "cross_domain"


# ---------------------------------------------------------------------------
# 4. SynthesisRule
# ---------------------------------------------------------------------------


class TestSynthesisRule:
    def test_rule_creation(self) -> None:
        rule = SynthesisRule(
            rule_id="test_rule",
            domain=SynthesisDomain.WATER,
            inputs=("precip",),
            conditions=lambda e, v: True,
            output_pattern=PatternState.COHERENT,
            statement="Test.",
            scientific_basis="Test basis.",
        )
        assert rule.rule_id == "test_rule"
        assert rule.domain == SynthesisDomain.WATER
        assert rule.min_sources == 2

    def test_rules_have_unique_ids(self) -> None:
        ids = [r.rule_id for r in DEFAULT_RULES]
        assert len(ids) == len(set(ids))

    def test_rules_have_statements(self) -> None:
        for rule in DEFAULT_RULES:
            assert len(rule.statement) > 0

    def test_rules_have_scientific_basis(self) -> None:
        for rule in DEFAULT_RULES:
            assert len(rule.scientific_basis) > 0

    def test_rules_have_inputs(self) -> None:
        for rule in DEFAULT_RULES:
            assert len(rule.inputs) > 0


# ---------------------------------------------------------------------------
# 5. Water rules
# ---------------------------------------------------------------------------


class TestWaterRules:
    def test_water_below_baseline_fires(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_below_baseline" in rule_ids

    def test_water_below_baseline_not_enough_evidence(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=0.1, et=0.1)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_below_baseline" not in rule_ids

    def test_water_mixed_fires(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=0.5, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_mixed_evidence" in rule_ids

    def test_water_above_baseline_fires(self) -> None:
        bundle = _water_bundle(precip=0.8, soil=0.6, et=0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_above_baseline" in rule_ids

    def test_water_below_and_mixed_not_both(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_mixed_evidence" not in rule_ids

    def test_water_statement_mentions_historical(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        stmt = next(s for s in result.statements if s.rule_id == "water_below_baseline")
        assert "baseline" in stmt.statement.lower()

    def test_water_rule_has_limitations(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        stmt = next(s for s in result.statements if s.rule_id == "water_below_baseline")
        assert len(stmt.limitations) > 0


# ---------------------------------------------------------------------------
# 6. Vegetation rules
# ---------------------------------------------------------------------------


class TestVegetationRules:
    def test_veg_below_fires(self) -> None:
        bundle = _veg_bundle(ndvi_abs=-0.15, ndvi_rel=-0.25)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "vegetation_below_historical" in rule_ids

    def test_veg_above_fires(self) -> None:
        bundle = _veg_bundle(ndvi_abs=0.15, ndvi_rel=0.25)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "vegetation_above_historical" in rule_ids

    def test_veg_below_not_above(self) -> None:
        bundle = _veg_bundle(ndvi_abs=-0.15, ndvi_rel=-0.25)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.VEGETATION, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "vegetation_above_historical" not in rule_ids


# ---------------------------------------------------------------------------
# 7. Thermal rules
# ---------------------------------------------------------------------------


class TestThermalRules:
    def test_thermal_above_fires(self) -> None:
        bundle = _thermal_bundle(lst=2.5)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.THERMAL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "thermal_above_baseline" in rule_ids

    def test_thermal_below_not_fire(self) -> None:
        bundle = _thermal_bundle(lst=-2.5)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.THERMAL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "thermal_above_baseline" not in rule_ids

    def test_thermal_statement_mentions_lst(self) -> None:
        bundle = _thermal_bundle(lst=2.5)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.THERMAL, bundle)
        stmt = result.statements[0]
        assert "temperature" in stmt.statement.lower() or "lst" in stmt.statement.lower()


# ---------------------------------------------------------------------------
# 8. Soil rules
# ---------------------------------------------------------------------------


class TestSoilRules:
    def test_soil_below_fires(self) -> None:
        bundle = _soil_bundle(sm=-0.7)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.SOIL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "soil_moisture_below_baseline" in rule_ids

    def test_soil_above_not_fire(self) -> None:
        bundle = _soil_bundle(sm=0.5)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.SOIL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "soil_moisture_below_baseline" not in rule_ids


# ---------------------------------------------------------------------------
# 9. Phenology rules
# ---------------------------------------------------------------------------


class TestPhenologyRules:
    def test_phenology_later_fires(self) -> None:
        bundle = _phenology_bundle(timing=12.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PHENOLOGY, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "phenology_later_onset" in rule_ids

    def test_phenology_earlier_fires(self) -> None:
        bundle = _phenology_bundle(timing=-5.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PHENOLOGY, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "phenology_earlier_onset" in rule_ids

    def test_phenology_later_not_earlier(self) -> None:
        bundle = _phenology_bundle(timing=12.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PHENOLOGY, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "phenology_earlier_onset" not in rule_ids

    def test_phenology_statement_mentions_vegetation_season(self) -> None:
        bundle = _phenology_bundle(timing=12.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PHENOLOGY, bundle)
        stmt = result.statements[0]
        assert "vegetation season" in stmt.statement.lower() or "growing" in stmt.statement.lower()


# ---------------------------------------------------------------------------
# 10. Productivity rules
# ---------------------------------------------------------------------------


class TestProductivityRules:
    def test_productivity_below_fires(self) -> None:
        bundle = _productivity_bundle(pvpi=-0.3)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PRODUCTIVITY, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "productivity_below_baseline" in rule_ids

    def test_productivity_above_not_fire(self) -> None:
        bundle = _productivity_bundle(pvpi=0.3)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PRODUCTIVITY, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "productivity_below_baseline" not in rule_ids

    def test_productivity_statement_mentions_vegetation_productivity(self) -> None:
        bundle = _productivity_bundle(pvpi=-0.3)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PRODUCTIVITY, bundle)
        stmt = result.statements[0]
        assert "vegetation-productivity" in stmt.statement.lower() or "vegetation productivity" in stmt.statement.lower()


# ---------------------------------------------------------------------------
# 11. Historical rules
# ---------------------------------------------------------------------------


class TestHistoricalRules:
    def test_historical_low_percentile_fires(self) -> None:
        bundle = _historical_bundle(pct=15.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.HISTORICAL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "historical_low_percentile" in rule_ids

    def test_historical_high_percentile_not_fire(self) -> None:
        bundle = _historical_bundle(pct=75.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.HISTORICAL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "historical_low_percentile" not in rule_ids


# ---------------------------------------------------------------------------
# 12. Cross-domain rules
# ---------------------------------------------------------------------------


class TestCrossDomainRules:
    def test_cross_water_veg_coherent(self) -> None:
        items = [
            _make_item("precipitation_anomaly", -0.8, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", -0.6, source="smap_l4"),
            _make_item("evapotranspiration_anomaly", -0.4, source="modis_et"),
            _make_item("ndvi_anomaly_absolute", -0.15, source="modis_ndvi"),
        ]
        bundle = _make_bundle("cross", items)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.CROSS_DOMAIN, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "cross_water_vegetation_below" in rule_ids

    def test_cross_water_thermal_coherent(self) -> None:
        items = [
            _make_item("precipitation_anomaly", -0.8, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", -0.6, source="smap_l4"),
            _make_item("lst_day_anomaly", 2.5, source="modis_lst"),
        ]
        bundle = _make_bundle("cross", items)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.CROSS_DOMAIN, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "cross_water_thermal_opposite" in rule_ids

    def test_cross_water_veg_not_when_water_positive(self) -> None:
        items = [
            _make_item("precipitation_anomaly", 0.8, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", 0.6, source="smap_l4"),
            _make_item("evapotranspiration_anomaly", 0.4, source="modis_et"),
            _make_item("ndvi_anomaly_absolute", -0.15, source="modis_ndvi"),
        ]
        bundle = _make_bundle("cross", items)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.CROSS_DOMAIN, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "cross_water_vegetation_below" not in rule_ids


# ---------------------------------------------------------------------------
# 13. Domain summaries
# ---------------------------------------------------------------------------


class TestDomainSummary:
    def test_empty_summary(self) -> None:
        summary = DomainSummary(domain=SynthesisDomain.WATER)
        assert summary.statement_count == 0
        assert not summary.has_statements
        assert summary.to_dict()["domain"] == "water"

    def test_summary_with_statements(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert summary.has_statements
        assert summary.statement_count >= 1
        assert summary.sufficiency == SufficiencyLevel.SUFFICIENT

    def test_summary_to_dict(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        d = summary.to_dict()
        assert d["domain"] == "water"
        assert "statement_count" in d
        assert d["statement_count"] >= 1
        assert isinstance(d["statements"], list)

    def test_summary_limitations_on_insufficient(self) -> None:
        items = [
            _make_item("precipitation_anomaly", -0.8, source="era5_land"),
        ]
        bundle = _make_bundle("water_incomplete", items)
        engine = SynthesisEngine()
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        if summary.sufficiency != SufficiencyLevel.SUFFICIENT:
            assert any("sufficiency" in lim.lower() for lim in summary.limitations)


# ---------------------------------------------------------------------------
# 14. Agricultural synthesis
# ---------------------------------------------------------------------------


class TestAgriculturalSynthesis:
    def test_synthesis_structure(self) -> None:
        synthesis = AgriculturalSynthesis(
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
            spatial_context="test field",
        )
        assert synthesis.time_start == date(2024, 7, 1)
        assert synthesis.time_end == date(2024, 7, 31)
        assert synthesis.spatial_context == "test field"
        assert len(synthesis.available_domains) == 0

    def test_synthesis_to_dict(self) -> None:
        synthesis = AgriculturalSynthesis(
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
            spatial_context="test field",
        )
        d = synthesis.to_dict()
        assert d["time_start"] == "2024-07-01"
        assert d["time_end"] == "2024-07-31"
        assert d["spatial_context"] == "test field"
        assert d["available_domains"] == []
        assert isinstance(d["domain_summaries"], dict)

    def test_synthesis_with_domains(self) -> None:
        synthesis = AgriculturalSynthesis(
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
            spatial_context="test field",
        )
        synthesis.domain_summaries = {
            SynthesisDomain.WATER: DomainSummary(
                domain=SynthesisDomain.WATER,
                statements=[],
            ),
            SynthesisDomain.VEGETATION: DomainSummary(
                domain=SynthesisDomain.VEGETATION,
                statements=[
                    SynthesisStatement(
                        rule_id="test",
                        domain=SynthesisDomain.VEGETATION,
                        pattern=PatternState.BELOW_CONTEXT,
                        statement="Below.",
                        evidence_keys=("ndvi",),
                        evidence_values={"ndvi": -0.1},
                        scientific_basis="Test basis.",
                        limitations=("Test limitation.",),
                    )
                ],
            ),
        }
        assert SynthesisDomain.WATER in synthesis.unavailable_domains
        assert SynthesisDomain.VEGETATION in synthesis.available_domains

    def test_synthesis_domain_summary_method(self) -> None:
        synthesis = AgriculturalSynthesis(
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
        )
        synthesis.domain_summaries = {
            SynthesisDomain.WATER: DomainSummary(
                domain=SynthesisDomain.WATER,
            ),
        }
        assert synthesis.domain_summary(SynthesisDomain.WATER) is not None
        assert synthesis.domain_summary(SynthesisDomain.VEGETATION) is None


# ---------------------------------------------------------------------------
# 15. SynthesisEngine
# ---------------------------------------------------------------------------


class TestSynthesisEngine:
    def test_engine_default_rules(self) -> None:
        engine = SynthesisEngine()
        assert len(engine.rules) == len(DEFAULT_RULES)

    def test_engine_custom_rules(self) -> None:
        custom = [WATER_RULES[0]]
        engine = SynthesisEngine(rules=custom)
        assert len(engine.rules) == 1

    def test_engine_evaluate_domain_empty(self) -> None:
        engine = SynthesisEngine()
        items = [
            _make_item("precipitation_anomaly", 0.0),
        ]
        bundle = _make_bundle("empty", items)
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert not summary.has_statements

    def test_engine_synthesise(self) -> None:
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_bundle(precip=-0.8, soil=-0.6, et=-0.4),
            SynthesisDomain.VEGETATION: _veg_bundle(ndvi_abs=-0.15, ndvi_rel=-0.25),
        }
        synthesis = engine.synthesise(
            bundles,
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
            spatial_context="test field",
        )
        assert synthesis.time_start == date(2024, 7, 1)
        assert synthesis.time_end == date(2024, 7, 31)
        assert SynthesisDomain.WATER in synthesis.available_domains
        assert SynthesisDomain.VEGETATION in synthesis.available_domains

    def test_engine_synthesise_cross_domain(self) -> None:
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_bundle(precip=-0.8, soil=-0.6, et=-0.4),
            SynthesisDomain.VEGETATION: _veg_bundle(ndvi_abs=-0.15, ndvi_rel=-0.25),
            SynthesisDomain.THERMAL: _thermal_bundle(lst=2.5),
        }
        synthesis = engine.synthesise(
            bundles,
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
        )
        cross_ids = [cs.rule_id for cs in synthesis.cross_domain_statements]
        assert "cross_water_vegetation_below" in cross_ids
        assert "cross_water_thermal_opposite" in cross_ids

    def test_engine_synthesise_empty_bundles(self) -> None:
        engine = SynthesisEngine()
        synthesis = engine.synthesise({})
        assert len(synthesis.available_domains) == 0

    def test_engine_synthesise_metadata(self) -> None:
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_bundle(),
        }
        synthesis = engine.synthesise(bundles)
        assert synthesis.metadata["rule_count"] == str(len(DEFAULT_RULES))
        assert synthesis.metadata["domains_evaluated"] == "1"


# ---------------------------------------------------------------------------
# 16. Evidence values preserved
# ---------------------------------------------------------------------------


class TestEvidencePreservation:
    def test_values_in_statement(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        stmt = next(s for s in result.statements if s.rule_id == "water_below_baseline")
        assert "precipitation_anomaly" in stmt.evidence_values
        assert stmt.evidence_values["precipitation_anomaly"] == pytest.approx(-0.8)

    def test_evidence_keys_sorted(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        stmt = next(s for s in result.statements if s.rule_id == "water_below_baseline")
        keys = list(stmt.evidence_keys)
        assert keys == sorted(keys)

    def test_conflicts_preserved(self) -> None:
        conflict = EvidenceConflict(
            metric_a="precipitation_anomaly",
            metric_b="soil_moisture_rootzone_anomaly",
            status=ConsistencyStatus.CONFLICTING,
            explanation="Precipitation is negative but soil moisture is positive.",
        )
        items = [
            _make_item("precipitation_anomaly", -0.8, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", 0.5, source="smap_l4"),
            _make_item("evapotranspiration_anomaly", -0.4, source="modis_et"),
        ]
        bundle = _make_bundle("water_conflict", items, conflicts=[conflict])
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        has_conflict_stmt = any(
            len(s.conflicts) > 0 for s in result.statements
        )
        assert has_conflict_stmt


# ---------------------------------------------------------------------------
# 17. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_inputs_identical_output(self) -> None:
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_bundle(precip=-0.8, soil=-0.6, et=-0.4),
            SynthesisDomain.VEGETATION: _veg_bundle(ndvi_abs=-0.15, ndvi_rel=-0.25),
        }
        s1 = engine.synthesise(bundles, time_start=date(2024, 7, 1))
        s2 = engine.synthesise(bundles, time_start=date(2024, 7, 1))
        assert s1.to_dict() == s2.to_dict()

    def test_rule_determinism(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine1 = SynthesisEngine()
        engine2 = SynthesisEngine()
        r1 = engine1.evaluate_domain(SynthesisDomain.WATER, bundle)
        r2 = engine2.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert [s.rule_id for s in r1.statements] == [
            s.rule_id for s in r2.statements
        ]


# ---------------------------------------------------------------------------
# 18. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_water_source_not_below(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=0.0, et=0.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_below_baseline" not in rule_ids

    def test_zero_values_not_below(self) -> None:
        bundle = _water_bundle(precip=0.0, soil=0.0, et=0.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "water_below_baseline" not in rule_ids
        assert "water_above_baseline" not in rule_ids

    def test_unavailable_evidence_excluded(self) -> None:
        items = [
            _make_item("precipitation_anomaly", None, status=EvidenceStatus.UNAVAILABLE, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", -0.6, source="smap_l4"),
            _make_item("evapotranspiration_anomaly", -0.4, source="modis_et"),
        ]
        bundle = _make_bundle("partial", items)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert result.unavailable_evidence == ["precipitation_anomaly"]

    def test_missing_inputs_no_fire(self) -> None:
        items = [
            _make_item("precipitation_anomaly", -0.8, source="era5_land"),
        ]
        bundle = _make_bundle("sparse", items)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert len(result.statements) == 0

    def test_phenology_zero_timing_no_rule(self) -> None:
        bundle = _phenology_bundle(timing=0.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PHENOLOGY, bundle)
        assert len(result.statements) == 0

    def test_productivity_zero_no_rule(self) -> None:
        bundle = _productivity_bundle(pvpi=0.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.PRODUCTIVITY, bundle)
        assert len(result.statements) == 0

    def test_historical_threshold_boundary(self) -> None:
        bundle = _historical_bundle(pct=25.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.HISTORICAL, bundle)
        rule_ids = [s.rule_id for s in result.statements]
        assert "historical_low_percentile" not in rule_ids

    def test_thermal_zero_no_rule(self) -> None:
        bundle = _thermal_bundle(lst=0.0)
        engine = SynthesisEngine()
        result = engine.evaluate_domain(SynthesisDomain.THERMAL, bundle)
        assert len(result.statements) == 0


# ---------------------------------------------------------------------------
# 19. Overall sufficiency
# ---------------------------------------------------------------------------


class TestOverallSufficiency:
    def test_sufficient_when_all_sufficient(self) -> None:
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_bundle(),
            SynthesisDomain.VEGETATION: _veg_bundle(),
        }
        synthesis = engine.synthesise(bundles)
        assert synthesis.overall_sufficiency == SufficiencyLevel.SUFFICIENT

    def test_insufficient_when_any_insufficient(self) -> None:
        items_incomplete = [
            _make_item("precipitation_anomaly", -0.8, source="era5_land"),
        ]
        incomplete = _make_bundle("incomplete", items_incomplete)
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: incomplete,
            SynthesisDomain.VEGETATION: _veg_bundle(),
        }
        synthesis = engine.synthesise(bundles)
        assert synthesis.overall_sufficiency == SufficiencyLevel.INSUFFICIENT


# ---------------------------------------------------------------------------
# 20. JSON serialisation
# ---------------------------------------------------------------------------


class TestJSONSerialisation:
    def test_synthesis_to_json(self) -> None:
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_bundle(precip=-0.8, soil=-0.6, et=-0.4),
        }
        synthesis = engine.synthesise(
            bundles,
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
            spatial_context="test field",
        )
        d = synthesis.to_dict()
        json_str = json.dumps(d, default=str)
        assert "water_below_baseline" in json_str
        assert "test field" in json_str

    def test_domain_summary_json(self) -> None:
        bundle = _water_bundle(precip=-0.8, soil=-0.6, et=-0.4)
        engine = SynthesisEngine()
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        d = summary.to_dict()
        json_str = json.dumps(d, default=str)
        assert "water" in json_str


# ---------------------------------------------------------------------------
# 21. Synthesis rule scientific basis
# ---------------------------------------------------------------------------


class TestScientificBasis:
    def test_water_rule_no_causation(self) -> None:
        for rule in WATER_RULES:
            assert "cause" not in rule.scientific_basis.lower() or "not" in rule.scientific_basis.lower()

    def test_veg_rule_mentions_anomaly(self) -> None:
        for rule in VEGETATION_RULES:
            assert "anomaly" in rule.scientific_basis.lower() or "baseline" in rule.scientific_basis.lower()

    def test_phenology_rule_not_crop_calendar(self) -> None:
        for rule in PHENOLOGY_RULES:
            assert "crop calendar" in rule.limitations[0].lower() or "crop" in rule.limitations[0].lower()

    def test_productivity_rule_not_yield(self) -> None:
        for rule in PRODUCTIVITY_RULES:
            assert "yield" in rule.limitations[0].lower() or "not a yield" in rule.statement.lower()


# ---------------------------------------------------------------------------
# 22. Sufficiency propagation
# ---------------------------------------------------------------------------


class TestSufficiencyPropagation:
    def test_unavailable_items_count(self) -> None:
        items = [
            _make_item("precipitation_anomaly", None, status=EvidenceStatus.UNAVAILABLE, source="era5_land"),
            _make_item("soil_moisture_rootzone_anomaly", -0.6, source="smap_l4"),
            _make_item("evapotranspiration_anomaly", -0.4, source="modis_et"),
        ]
        bundle = _make_bundle("partial", items)
        engine = SynthesisEngine()
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert len(summary.unavailable_evidence) == 1
        assert "precipitation_anomaly" in summary.unavailable_evidence
