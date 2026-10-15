"""Unit tests for Pest & Disease Risk Screening and Inspection (Phase P1).

Verifies:
1. Multi-sensor screening (Optical, Radar, Thermal).
2. Evidence hierarchy levels (Level 0 through Level 4).
3. Biotic vs abiotic stress compatibility screening.
4. Ground truth corroboration and linkage.
5. Strict scientific safety invariants:
   - Mandatory disclaimers always present.
   - NO pathogen diagnosis (no specific disease named).
   - NO chemical spray/pesticide recommendation.
"""

from __future__ import annotations

import pytest

from app.schemas.agriculture import (
    EvidenceHierarchyLevel,
    PestDiseasePatternType,
    PestDiseaseRiskLevel,
)
from app.services.agriculture.ground_truth import GroundTruthObservation
from app.services.agriculture.pest_disease_inspection import (
    DISCLAIMER_EN,
    DISCLAIMER_FA,
    inspect_pest_disease_risk,
)


class MockEvidenceItem:
    def __init__(self, metric_key: str, value: float | None, status: str = "available"):
        self.metric_key = metric_key
        self.value = value
        self.status = status
        self.quality = "good"


class MockEvidenceBundle:
    def __init__(self, name: str, items: list[MockEvidenceItem]):
        self.name = name
        self.items = items


class MockPersistence:
    def __init__(self, longest_run_below: int = 0, n_anomalous: int = 0):
        self.longest_run_below = longest_run_below
        self.n_anomalous = n_anomalous


class MockChange:
    def __init__(self, persistence: MockPersistence):
        self.persistence = persistence


class MockTemporalSection:
    def __init__(self, ndvi_persistence: MockPersistence | None = None):
        self.changes = {}
        if ndvi_persistence:
            self.changes["ndvi"] = MockChange(ndvi_persistence)


def test_level_0_no_sensors_available():
    """When no sensor metrics are usable, returns Level 0 and insufficient evidence."""
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", None, status="unavailable"),
        ]),
    }
    result = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles)
    assert result.evidence_hierarchy_level == 0
    assert result.overall_risk_level == PestDiseaseRiskLevel.INSUFFICIENT
    assert result.pattern_type == PestDiseasePatternType.INSUFFICIENT_EVIDENCE
    assert DISCLAIMER_FA in result.scientific_disclaimer_fa
    assert DISCLAIMER_EN in result.scientific_disclaimer_en


def test_level_1_single_sensor_indication():
    """When only optical shows stress without radar or temporal backup, returns Level 1."""
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.22),  # Stressed
        ]),
    }
    result = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles)
    assert result.evidence_hierarchy_level == 1
    assert result.overall_risk_level in (PestDiseaseRiskLevel.MODERATE, PestDiseaseRiskLevel.ELEVATED)
    assert len(result.optical_evidence) > 0
    # Mandatory disclaimers
    assert "سنجش از دور" in result.scientific_disclaimer_fa
    assert "Definitive pathogen" in result.scientific_disclaimer_en


def test_level_2_multi_temporal_persistence():
    """When stress persists across multiple consecutive sub-windows, returns Level 2."""
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.28),
        ]),
    }
    temporal = MockTemporalSection(MockPersistence(longest_run_below=3, n_anomalous=3))
    result = inspect_pest_disease_risk(
        "2024-05-01", "2024-05-31", bundles, temporal_section=temporal
    )
    assert result.evidence_hierarchy_level == 2
    assert result.temporal_persistence["multi_temporal_verified"] is True
    assert result.overall_risk_level == PestDiseaseRiskLevel.ELEVATED
    assert result.pattern_type == PestDiseasePatternType.PERSISTENT_DECLINE


def test_level_3_multi_sensor_concordance():
    """When Optical + Radar + Thermal all indicate stress, returns Level 3."""
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.22),
            MockEvidenceItem("ndre", 0.16),
        ]),
        "radar": MockEvidenceBundle("radar", [
            MockEvidenceItem("sar_vh", -22.5),  # Structural loss
            MockEvidenceItem("sar_vv", -12.0),
        ]),
        "thermal": MockEvidenceBundle("thermal", [
            MockEvidenceItem("lst_celsius", 43.5),  # Thermal elevation
        ]),
    }
    result = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles)
    assert result.evidence_hierarchy_level == 3
    assert result.overall_risk_level in (PestDiseaseRiskLevel.HIGH, PestDiseaseRiskLevel.ELEVATED)
    assert result.biotic_abiotic_assessment.canopy_structural_decay == "detected"


def test_level_4_logic_with_genuine_field_observation_unit_test_representation():
    """Unit-test representation demonstrating that genuine, verified field observations can produce Level 4."""
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.24),
            MockEvidenceItem("ndre", 0.17),
        ]),
        "radar": MockEvidenceBundle("radar", [
            MockEvidenceItem("sar_vh", -21.8),
        ]),
    }
    # Note: This is an explicit unit-test representation of an external agronomist field visit
    genuine_gt = [
        GroundTruthObservation(
            observation_id="gt-unit-test-rep-01",
            observed_on="2024-05-15",
            source="agronomist_observation",
            method="field_inspection",
            variable="observed_stress",
            state="present",
            quality="good",
            is_test_fixture=False,
            observed_stress="زردی حاشیه برگ و پژمردگی شاخه‌های آفتاب‌رو",
            pest_observation="مشاهده پوره پسیل در سطح زیرین برگ",
        )
    ]
    result = inspect_pest_disease_risk(
        "2024-05-01", "2024-05-31", bundles, ground_truth_records=genuine_gt
    )
    assert result.evidence_hierarchy_level == 4
    assert result.evidence_hierarchy_title_fa == "سطح ۴: اعتبارسنجی تلفیقی با داده‌های میدانی (Ground Truth Validated)"
    assert result.overall_risk_level == PestDiseaseRiskLevel.HIGH
    assert result.ground_truth_corroboration["has_ground_truth"] is True
    assert result.ground_truth_corroboration["has_real_ground_truth"] is True
    assert result.ground_truth_corroboration["is_test_fixture"] is False
    assert result.ground_truth_corroboration["confirms_stress"] is True
    assert result.pattern_type == PestDiseasePatternType.POSSIBLE_BIOTIC_STRESS


def test_synthetic_test_fixture_ground_truth_never_produces_level_4():
    """REGRESSION TEST: Synthetic/test fixture ground truth must NEVER elevate evidence to Level 4.
    
    The system must retain the actual sensor/temporal evidence level (Level 1, 2, or 3)
    and explicitly flag the record as a Test Fixture.
    """
    # Optical only (baseline sensor evidence = Level 1)
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.22),
            MockEvidenceItem("ndre", 0.16),
        ]),
    }

    # Case A: Explicit is_test_fixture=True flag
    gt_fixture_flag = [
        GroundTruthObservation(
            observation_id="gt-fixture-01",
            observed_on="2024-05-15",
            source="agronomist_observation",
            method="field_inspection",
            variable="observed_stress",
            state="present",
            is_test_fixture=True,
            observed_stress="زردی برگ",
            pest_observation="پوره پسیل",
        )
    ]
    res_a = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles, ground_truth_records=gt_fixture_flag)
    assert res_a.evidence_hierarchy_level != 4, "Test fixture must NEVER produce Level 4"
    assert res_a.evidence_hierarchy_level == 1, "Should fall back to real sensor evidence (Level 1)"
    assert res_a.ground_truth_corroboration["is_test_fixture"] is True
    assert res_a.ground_truth_corroboration["has_real_ground_truth"] is False
    assert "Test Fixture — not real ground truth" in res_a.ground_truth_corroboration["summary_fa"]
    assert any("Test Fixture — not real ground truth" in lim for lim in res_a.limitations)

    # Case B: source="test_fixture"
    gt_source_fixture = [
        GroundTruthObservation(
            observation_id="gt-sample-ardakan-01",
            observed_on="2024-05-15",
            source="test_fixture",
            method="field_inspection",
            variable="observed_stress",
            state="present",
            observed_stress="زردی برگ",
        )
    ]
    res_b = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles, ground_truth_records=gt_source_fixture)
    assert res_b.evidence_hierarchy_level != 4
    assert res_b.evidence_hierarchy_level == 1
    assert res_b.ground_truth_corroboration["is_test_fixture"] is True

    # Case C: notes indicates synthetic/test fixture
    gt_notes_fixture = [
        {
            "observation_id": "gt-02",
            "observed_on": "2024-05-15",
            "source": "field_observation",
            "method": "field_inspection",
            "variable": "observed_stress",
            "state": "present",
            "notes": "داده آزمایشی شبیه‌سازی‌شده (synthetic/test fixture — not real ground truth)",
            "observed_stress": "تنش آبی",
            "is_derived": False,
        }
    ]
    res_c = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles, ground_truth_records=gt_notes_fixture)
    assert res_c.evidence_hierarchy_level != 4
    assert res_c.evidence_hierarchy_level == 1
    assert res_c.ground_truth_corroboration["is_test_fixture"] is True

    # Case D: Multi-temporal persistence exists (Sensor Level 2) with test fixture GT
    temporal = MockTemporalSection(MockPersistence(longest_run_below=3, n_anomalous=3))
    res_d = inspect_pest_disease_risk(
        "2024-05-01", "2024-05-31", bundles, temporal_section=temporal, ground_truth_records=gt_fixture_flag
    )
    assert res_d.evidence_hierarchy_level == 2, "Should preserve Level 2 temporal persistence without inflating to Level 4"
    assert res_d.evidence_hierarchy_title_fa == "سطح ۲: پایداری چندزمانه (Multi-Temporal Persistence)"
    assert res_d.ground_truth_corroboration["is_test_fixture"] is True


def test_biotic_vs_abiotic_distinction():
    """When heat and drought dominate, flags abiotic compatibility; when decoupled, flags biotic compatibility."""
    # Abiotic scenario: High LST + low moisture
    abiotic_bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.30),
            MockEvidenceItem("ndmi", 0.05),  # High moisture deficit
        ]),
        "thermal": MockEvidenceBundle("thermal", [
            MockEvidenceItem("lst_celsius", 44.0),  # Extreme surface heat
        ]),
    }
    res_abiotic = inspect_pest_disease_risk("2024-07-01", "2024-07-31", abiotic_bundles)
    assert res_abiotic.biotic_abiotic_assessment.compatible_stress_type == "abiotic"

    # Biotic scenario: Specific chlorophyll drop (NDRE) and pest ground truth without heatwave
    biotic_bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.32),
            MockEvidenceItem("ndre", 0.15),  # Early chlorophyll collapse
            MockEvidenceItem("ndmi", 0.25),  # Adequate moisture
        ]),
        "radar": MockEvidenceBundle("radar", [
            MockEvidenceItem("sar_vh", -22.0),
        ]),
        "thermal": MockEvidenceBundle("thermal", [
            MockEvidenceItem("lst_celsius", 32.0),  # Normal thermal
        ]),
    }
    res_biotic = inspect_pest_disease_risk("2024-07-01", "2024-07-31", biotic_bundles)
    assert res_biotic.biotic_abiotic_assessment.compatible_stress_type == "biotic"


def test_scientific_safety_invariants():
    """Verify that NO specific pathogen diagnosis or chemical spray advice is ever output."""
    bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.20),
            MockEvidenceItem("ndre", 0.14),
        ]),
    }
    result = inspect_pest_disease_risk("2024-05-01", "2024-05-31", bundles)

    all_texts = (
        result.pattern_title_fa
        + " "
        + result.pattern_summary_fa
        + " "
        + result.scientific_disclaimer_fa
        + " "
        + " ".join(result.recommended_field_actions_fa)
        + " "
        + " ".join(result.limitations)
    )

    # Strictly disallowed words in agricultural remote sensing:
    forbidden_terms = [
        "Verticillium",
        "Phytophthora",
        "توصیه سم",
        "تجویز سم برای",
        "قارچ‌کش کاربندازیم",
        "حشره‌کش دیازینون",
        "سم‌پاشی شیمیایی با",
    ]
    for term in forbidden_terms:
        assert term not in all_texts, f"Forbidden term {term!r} found in response"

    # Must include mandatory clinical recommendations:
    assert "بازدید میدانی" in all_texts or "گیاه‌پزشک" in all_texts
    assert "آزمایشگاه" in all_texts


def test_cannot_diagnose_pest_without_ground_truth():
    """P-AGRI-8.1: Verify that spectral anomalies are NEVER labeled as pest or disease diagnosis without ground truth."""
    # Scenario: Acute drop in chlorophyll and radar structure, but NO ground truth
    stressed_bundles = {
        "vegetation": MockEvidenceBundle("vegetation", [
            MockEvidenceItem("ndvi", 0.21),
            MockEvidenceItem("ndre", 0.12),
        ]),
        "radar": MockEvidenceBundle("radar", [
            MockEvidenceItem("sar_vh", -22.5),
        ]),
        "thermal": MockEvidenceBundle("thermal", [
            MockEvidenceItem("lst_celsius", 33.0),
        ]),
    }
    result_no_gt = inspect_pest_disease_risk("2024-06-01", "2024-06-30", stressed_bundles, ground_truth_records=[])
    
    # 1. Pattern title must be neutral remote-sensing anomaly, NOT pest diagnosis
    assert "ناهنجاری سنجش از دور" in result_no_gt.pattern_title_fa
    assert "علت نامشخص" in result_no_gt.pattern_title_fa
    assert "آفت یا بیماری" not in result_no_gt.pattern_title_fa
    assert "خطر آفت" not in result_no_gt.risk_level_fa
    assert "خطر متوسط آفت" not in result_no_gt.risk_level_fa
    assert result_no_gt.evidence_hierarchy_level < 4

    # 2. When certified expert ground truth IS provided with pest diagnosis
    gt_record = GroundTruthObservation(
        observation_id="gt-cert-001",
        observed_on="2024-06-15",
        source="agronomist_observation",
        method="field_inspection",
        variable="observed_pest_presence",
        state="present",
        pest_observation="پسیل پسته",
        notes="Certified agronomist field scouting confirmed psylla infestation.",
    )
    result_with_gt = inspect_pest_disease_risk("2024-06-01", "2024-06-30", stressed_bundles, ground_truth_records=[gt_record])
    assert result_with_gt.evidence_hierarchy_level == 4
    assert "تأییدشده با مشاهدات میدانی" in result_with_gt.pattern_title_fa

