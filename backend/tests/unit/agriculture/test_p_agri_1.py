"""Unit tests for Phase P-AGRI-1 (Agronomic Intelligence & Synthesis Realignment).

Covers:
TEST 1: Vegetation regime classification correctly resolves to NON_VEGETATED for F-A12.
TEST 2: Vegetation regime classification correctly resolves to VEGETATED for active crop canopy.
TEST 3: Suppress invalid canopy interpretations on NON_VEGETATED ground.
TEST 4: Significance / noise gating on small NDVI anomalies (|ΔNDVI| < 0.02).
TEST 5: Fault-tolerant water rules when evapotranspiration is masked/missing.
TEST 6: Model conflict detection between SMAP L4 and ERA5-Land root-zone moisture.
TEST 7: Regime-aware synthesis statements (surface condition, desiccation, thermal load).
"""

import pytest
from datetime import date
from typing import Dict, List, Optional

from app.services.agriculture.evidence import (
    ConsistencyStatus,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceItem,
    EvidenceStatus,
    detect_conflict,
)
from app.services.agriculture.regime import (
    VegetationRegime,
    classify_vegetation_regime,
)
from app.services.agriculture.synthesis import (
    NDVI_ANOMALY_SIGNIFICANCE_THRESHOLD,
    PatternState,
    SynthesisDomain,
    SynthesisEngine,
    SynthesisRule,
    _evaluate_rule,
)
from app.services.agriculture.types import QualityLevel


def _make_item(
    metric_key: str,
    value: Optional[float],
    quality: QualityLevel = QualityLevel.GOOD,
    source: str = "test_source",
    unit: str = "",
) -> EvidenceItem:
    return EvidenceItem(
        metric_key=metric_key,
        value=value,
        unit=unit,
        status=EvidenceStatus.DERIVED if value is not None else EvidenceStatus.UNAVAILABLE,
        temporal_start=date(2025, 6, 1),
        temporal_end=date(2025, 9, 1),
        quality_level=quality,
        provenance=None,
        source_dataset_id=source,
    )


# ===========================================================================
# TEST 1: Regime classification for F-A12 bare ground
# ===========================================================================

def test_regime_classification_non_vegetated():
    """F-A12 point: NDVI 0.0528, DW bare prob 0.54, VH -17.11 dB -> NON_VEGETATED."""
    evidence = {
        "ndvi": 0.0528,
        "land_cover_probability": 0.541,
        "vh": -17.11,
        "vh_vv": -7.70,
        "rvi": 0.603,
    }
    assessment = classify_vegetation_regime(evidence)
    assert assessment.regime == VegetationRegime.NON_VEGETATED
    assert assessment.confidence == "high"
    assert "NON_VEGETATED" in assessment.explanation


# ===========================================================================
# TEST 2: Regime classification for vegetated canopy
# ===========================================================================

def test_regime_classification_vegetated():
    """Active crop field: NDVI 0.68, DW bare prob 0.02, VH -11.5 dB -> VEGETATED."""
    evidence = {
        "ndvi": 0.68,
        "savi": 0.52,
        "land_cover_probability": 0.02,
        "vh": -11.5,
    }
    assessment = classify_vegetation_regime(evidence)
    assert assessment.regime == VegetationRegime.VEGETATED
    assert assessment.confidence == "high"
    assert "VEGETATED" in assessment.explanation


# ===========================================================================
# TEST 3: Suppression of canopy interpretations on bare ground
# ===========================================================================

def test_suppress_canopy_proxy_and_veg_on_bare_ground():
    """On NON_VEGETATED ground, canopy proxy and veg historical rules must NOT fire."""
    engine = SynthesisEngine()
    
    # Bundle with bare ground metrics plus middle_canopy_dryness_proxy=5.0 and small positive ndvi anomaly
    items = [
        _make_item("ndvi", 0.0528),
        _make_item("land_cover_probability", 0.541),
        _make_item("middle_canopy_dryness_proxy", 5.0),
        _make_item("ndvi_anomaly_absolute", 0.008),
        _make_item("ndvi_anomaly_relative", 0.15),
    ]
    bundle = EvidenceBundle(name="vegetation", items=items)
    bundle.assess_sufficiency()

    # When evaluated with NON_VEGETATED regime
    summary = engine.evaluate_domain(
        SynthesisDomain.VEGETATION,
        bundle,
        regime=VegetationRegime.NON_VEGETATED,
    )
    fired_rule_ids = [s.rule_id for s in summary.statements]

    # Must NOT contain canopy proxy or vegetation_above_historical
    assert "canopy_proxy_no_stress" not in fired_rule_ids
    assert "vegetation_above_historical" not in fired_rule_ids
    # Must contain bare_ground_surface_condition
    assert "bare_ground_surface_condition" in fired_rule_ids


# ===========================================================================
# TEST 4: Significance / noise gating
# ===========================================================================

def test_noise_gating_suppresses_sub_threshold_ndvi_anomaly():
    """An NDVI anomaly of +0.008 is < 0.02 and must not trigger vegetation_above_historical."""
    engine = SynthesisEngine()
    items = [
        _make_item("ndvi_anomaly_absolute", 0.008),
        _make_item("ndvi_anomaly_relative", 0.15),
    ]
    bundle = EvidenceBundle(name="vegetation", items=items)
    bundle.assess_sufficiency()

    # Even under VEGETATED or UNCERTAIN regime, noise anomaly must be suppressed
    summary = engine.evaluate_domain(
        SynthesisDomain.VEGETATION,
        bundle,
        regime=VegetationRegime.VEGETATED,
    )
    fired_rule_ids = [s.rule_id for s in summary.statements]
    assert "vegetation_above_historical" not in fired_rule_ids

    # But an anomaly >= 0.02 MUST fire
    items_valid = [
        _make_item("ndvi_anomaly_absolute", 0.05),
        _make_item("ndvi_anomaly_relative", 0.15),
    ]
    bundle_valid = EvidenceBundle(name="vegetation", items=items_valid)
    bundle_valid.assess_sufficiency()
    summary_valid = engine.evaluate_domain(
        SynthesisDomain.VEGETATION,
        bundle_valid,
        regime=VegetationRegime.VEGETATED,
    )
    fired_valid = [s.rule_id for s in summary_valid.statements]
    assert "vegetation_above_historical" in fired_valid


# ===========================================================================
# TEST 5: Fault-tolerant water rules
# ===========================================================================

def test_water_rules_fault_tolerant_missing_et():
    """Missing evapotranspiration must not suppress water rules when precip & soil moisture exist."""
    engine = SynthesisEngine()
    items = [
        _make_item("precipitation_anomaly", -0.05),
        _make_item("soil_moisture_rootzone_anomaly", -0.02),
        # ET is missing / unavailable
    ]
    bundle = EvidenceBundle(name="water", items=items)
    bundle.assess_sufficiency()

    summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
    fired_rule_ids = [s.rule_id for s in summary.statements]

    assert "water_below_baseline" in fired_rule_ids
    stmt = next(s for s in summary.statements if s.rule_id == "water_below_baseline")
    assert any("ET-based" in lim for lim in stmt.limitations)


# ===========================================================================
# TEST 6: Model conflict detection (SMAP L4 vs ERA5)
# ===========================================================================

def test_model_conflict_smap_vs_era5():
    """Divergence between SMAP L4 (0.207) and ERA5 (0.037) must be flagged as CONFLICTING."""
    item_smap = _make_item("soil_moisture_rootzone", 0.207, unit="m3/m3")
    item_era5 = _make_item("soil_moisture_rootzone_era5", 0.037, unit="m3/m3")

    bundle = EvidenceBundle(
        name="soil",
        items=[item_smap, item_era5],
    )
    conflicts = bundle.run_consistency_checks()
    assert any(c.status == ConsistencyStatus.CONFLICTING for c in conflicts)
    conflict = next(c for c in conflicts if c.status == ConsistencyStatus.CONFLICTING)
    assert "Model discrepancy" in conflict.explanation
    assert "5.6×" in conflict.explanation or "5.5×" in conflict.explanation or "5.6" in conflict.explanation

    # Rule evaluation must also fire soil_rootzone_model_conflict
    engine = SynthesisEngine()
    summary = engine.evaluate_domain(SynthesisDomain.SOIL, bundle)
    fired_rule_ids = [s.rule_id for s in summary.statements]
    assert "soil_rootzone_model_conflict" in fired_rule_ids


# ===========================================================================
# TEST 7: Regime-aware synthesis statements
# ===========================================================================

def test_regime_aware_synthesis_statements():
    """Surface desiccation, thermal load, and atmospheric aridity fire appropriately."""
    engine = SynthesisEngine()

    # Soil bundle with surface desiccation
    soil_items = [
        _make_item("soil_moisture_surface", 0.0535),
        _make_item("soil_wilting_point", 0.0999),
    ]
    soil_bundle = EvidenceBundle(name="soil", items=soil_items)
    soil_bundle.assess_sufficiency()
    soil_summary = engine.evaluate_domain(SynthesisDomain.SOIL, soil_bundle)
    assert "soil_surface_desiccation" in [s.rule_id for s in soil_summary.statements]

    # Thermal bundle with severe solar heating
    thermal_items = [
        _make_item("land_surface_temperature_day", 48.98),
        _make_item("lst_day_anomaly", 3.28),
    ]
    thermal_bundle = EvidenceBundle(name="thermal", items=thermal_items)
    thermal_bundle.assess_sufficiency()
    thermal_summary = engine.evaluate_domain(SynthesisDomain.THERMAL, thermal_bundle)
    assert "surface_thermal_load_high" in [s.rule_id for s in thermal_summary.statements]

    # Cross-domain with thermal + aridity + surface desiccation
    cross_items = [
        _make_item("land_surface_temperature_day", 48.98),
        _make_item("vpd", 3.45),
        _make_item("soil_moisture_surface", 0.0535),
        _make_item("precipitation_anomaly", -0.05),
        _make_item("soil_moisture_rootzone_anomaly", -0.02),
        _make_item("lst_day_anomaly", 3.28),
    ]
    cross_bundle = EvidenceBundle(name="cross_domain", items=cross_items)
    cross_bundle.assess_sufficiency()
    cross_summary = engine.evaluate_domain(SynthesisDomain.CROSS_DOMAIN, cross_bundle)
    cross_rule_ids = [s.rule_id for s in cross_summary.statements]
    assert "cross_water_thermal_opposite" in cross_rule_ids
    assert "cross_aridity_thermal_surface" in cross_rule_ids
    assert "atmospheric_aridity_severe" in cross_rule_ids
