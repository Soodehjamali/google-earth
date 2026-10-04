"""Tests for the P3.2 named non-specific evidence patterns.

Covers the five neutral patterns, their exact predicates over
existing P1/P2 states, coexistence without ranking, window
identity, quality and provenance preservation, and the guards
(no biological readings, no scores, no new statistics).

Patterns consume real P1.3 month changes, real P1.4 joint
analyses, real P2.4 radar analyses, and real P2.5 concordance
months; this layer performs no Earth Engine calls itself.  No
network and no credentials are required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import pytest

from app.services.agriculture.change_profile import (
    MonthChange,
    analyze_changes,
)
from app.services.agriculture.concordance import analyze_concordance
from app.services.agriculture.concordance import (
    make_evidence as make_concordance_evidence,
)
from app.services.agriculture.joint_profile import analyze_joint
from app.services.agriculture.named_patterns import (
    FULL_PATTERN_ORDER,
    NAMED_PATTERN_ORDER,
    NAMED_PATTERN_TYPES,
    NAMED_RULES,
    evaluate_moisture_greenness_divergence,
    evaluate_multi_modal_change,
    evaluate_rapid_canopy_decline,
    evaluate_red_edge_decline,
    evaluate_sustained_radar_deviation,
    get_named_rule,
    sort_named_patterns,
)
from app.services.agriculture.pattern_engine import PatternEvidence
from app.services.agriculture.radar_anomaly import analyze_radar_metric
from app.services.agriculture.radar_profile import (
    RadarProfile,
    RadarProfilePoint,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)
from app.utils.dates import get_monthly_periods


def _temporal(
    metric_key: str,
    values: List[Optional[float]],
    unit: str = "index",
    dataset_id: str = "COPERNICUS/S2_SR_HARMONIZED",
    start: str = "2024-01-01",
) -> TemporalProfile:
    windows = get_monthly_periods(start, "2030-01-01")[: len(values)]
    points = tuple(
        TemporalProfilePoint(
            window_start=window_start,
            window_end=window_end,
            value=value,
            unit=unit,
            quality="good" if value is not None else "insufficient",
            coverage_percent=90.0 if value is not None else None,
            image_count=6 if value is not None else None,
        )
        for (window_start, window_end), value in zip(windows, values)
    )
    return TemporalProfile(
        metric_key=metric_key,
        dataset_id=dataset_id,
        unit=unit,
        window_start=start,
        window_end=windows[-1][1],
        points=points,
    )


def _ndvi_jump():
    from app.services.agriculture.baseline_anomaly import score_profile

    profile = _temporal(
        "ndvi", [0.60, 0.62, 0.60, 0.61, 0.60, 0.62, 0.61, 0.30]
    )
    anomalies = score_profile(profile)
    return analyze_changes(profile, anomalies).changes


def _radar_analysis(metric_key: str, values, unit: str):
    windows = get_monthly_periods("2024-01-01", "2030-01-01")[: len(values)]
    points = tuple(
        RadarProfilePoint(
            window_start=window_start,
            window_end=window_end,
            value=value,
            unit=unit,
            quality="good",
            coverage_percent=90.0,
            image_count=3,
            provenance={"source_dataset_id": "COPERNICUS/S1_GRD"},
        )
        for (window_start, window_end), value in zip(windows, values)
    )
    pols = {"vv": ("VV",), "vh": ("VH",), "vh_vv": ("VV", "VH"), "rvi": ("VV", "VH")}[
        metric_key
    ]
    profile = RadarProfile(
        metric_key=metric_key,
        dataset_id="COPERNICUS/S1_GRD",
        unit=unit,
        polarizations=pols,
        mode="IW",
        orbit_pass="DESCENDING",
        scale_m=10,
        window_start="2024-01-01",
        window_end=windows[-1][1],
        points=points,
    )
    return analyze_radar_metric(profile)


def _red_edge_items(specs):
    return [
        PatternEvidence(
            evidence_id=f"{metric}:{window_start}:change",
            source_module="red_edge",
            metric_id=metric,
            sensor="S2",
            family="red_edge",
            window_start=window_start,
            window_end=window_end,
            value=value,
            unit="reflectance/nm",
            anomaly_state=None,
            change_direction=direction,
            rapid=None,
            quality=quality,
            coverage_percent=80.0,
            image_count=4,
            provenance={},
            limitations=(),
        )
        for metric, window_start, window_end, value, direction, quality in specs
    ]


JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")


# ==========================================================================
# Registry: stable IDs, deterministic ordering, exact predicates
# ==========================================================================


def test_named_rule_ids_are_stable():
    assert [rule.rule_id for rule in NAMED_RULES] == [
        "P32_RAPID_CANOPY_DECLINE_V1",
        "P32_MOISTURE_DIVERGENCE_V1",
        "P32_RED_EDGE_DECLINE_V1",
        "P32_RADAR_DEVIATION_V1",
        "P32_MULTI_MODAL_V1",
    ]
    assert [rule.pattern_type for rule in NAMED_RULES] == list(NAMED_PATTERN_ORDER)
    assert get_named_rule("P32_MULTI_MODAL_V1").pattern_type == (
        "MULTI_MODAL_CANOPY_CHANGE"
    )
    with pytest.raises(KeyError, match="not registered"):
        get_named_rule("P32_PEST_V1")


def test_named_pattern_types_are_neutral():
    assert set(NAMED_PATTERN_TYPES) == {
        "RAPID_CANOPY_SIGNAL_DECLINE",
        "MOISTURE_GREENNESS_DIVERGENCE",
        "RED_EDGE_DECLINE_PATTERN",
        "SUSTAINED_RADAR_DEVIATION",
        "MULTI_MODAL_CANOPY_CHANGE",
    }
    assert list(FULL_PATTERN_ORDER)[:6] == [
        "PERSISTENT_ANOMALY",
        "RAPID_CHANGE",
        "MULTI_SENSOR_CONCORDANCE",
        "DIVERGENT_SENSOR_EVIDENCE",
        "SEQUENTIAL_CHANGE",
        "INSUFFICIENT_EVIDENCE",
    ]
    assert list(FULL_PATTERN_ORDER)[6:] == list(NAMED_PATTERN_ORDER)


def test_exact_rule_predicates():
    predicates = {
        rule.rule_id: rule.predicate for rule in NAMED_RULES
    }
    assert "RAPID_DECREASE" in predicates["P32_RAPID_CANOPY_DECLINE_V1"]
    assert "MOISTURE_DOWN_NDVI_STABLE" in predicates["P32_MOISTURE_DIVERGENCE_V1"]
    assert "DECREASE" in predicates["P32_RED_EDGE_DECLINE_V1"]
    assert "PERSISTENT" in predicates["P32_RADAR_DEVIATION_V1"]
    assert "MULTI_SENSOR_CONCORDANT" in predicates["P32_MULTI_MODAL_V1"]


def test_sort_named_patterns_uses_full_order():
    assert sort_named_patterns([]) == ()


# ==========================================================================
# Pattern 1 — rapid canopy signal decline
# ==========================================================================


def test_rapid_ndvi_decline_establishes_pattern():
    changes = [c for c in _ndvi_jump() if c.rapid == "RAPID_DECREASE"]
    assert changes, "expected a real P1.3 rapid decline in the fixture"
    patterns = evaluate_rapid_canopy_decline("ndvi", tuple(changes))
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_type == "RAPID_CANOPY_SIGNAL_DECLINE"
    assert pattern.status == "OBSERVED"
    assert pattern.contributing_metric_ids == ("ndvi",)
    assert pattern.window_start == changes[0].window_start
    assert "rapid decrease" in pattern.explanation
    assert "does not identify its cause" in pattern.explanation
    assert pattern.rule_id == "P32_RAPID_CANOPY_DECLINE_V1"
    change_payload = pattern.provenance_by_evidence[
        pattern.contributing_evidence_ids[0]
    ]["change"]
    assert change_payload["rapid"] == "RAPID_DECREASE"
    assert change_payload["absolute_change"] is not None
    assert change_payload["previous_window_start"] is not None


def test_non_rapid_decline_does_not_establish():
    profile = _temporal("ndvi", [0.60, 0.59, 0.58, 0.57])
    changes = analyze_changes(profile, None).changes
    assert all(change.rapid != "RAPID_DECREASE" for change in changes)
    assert evaluate_rapid_canopy_decline("ndvi", tuple(changes)) == ()


def test_insufficient_quality_does_not_establish():
    change = MonthChange(
        window_start="2024-01-01",
        window_end="2024-01-31",
        value=0.3,
        previous_value=0.6,
        absolute_change=-0.3,
        relative_change=-0.5,
        days_elapsed=31,
        rate_per_day=-0.3 / 31,
        direction="DECREASE",
        rapid="RAPID_DECREASE",
        unit="index",
        quality="insufficient",
    )
    assert evaluate_rapid_canopy_decline("ndvi", (change,)) == ()


def test_rapid_decline_refuses_unsupported_metrics():
    with pytest.raises(ValueError, match="supports"):
        evaluate_rapid_canopy_decline("ndmi", ())


def test_ndre_rapid_decline_where_available():
    from app.services.agriculture.baseline_anomaly import score_profile

    profile = _temporal("ndre", [0.40, 0.42, 0.40, 0.41, 0.40, 0.42, 0.41, 0.10])
    anomalies = score_profile(profile)
    changes = tuple(
        c
        for c in analyze_changes(profile, anomalies).changes
        if c.rapid == "RAPID_DECREASE"
    )
    if not changes:
        pytest.skip("fixture produced no P1.3 rapid NDRE decline")
    patterns = evaluate_rapid_canopy_decline("ndre", changes)
    assert patterns and patterns[0].contributing_metric_ids == ("ndre",)


# ==========================================================================
# Pattern 2 — moisture greenness divergence
# ==========================================================================


def _divergent_joint():
    ndvi = _temporal("ndvi", [0.50, 0.50, 0.50, 0.50])
    moisture = _temporal("ndmi", [0.40, 0.35, 0.30, 0.25])
    ndvi_changes = analyze_changes(ndvi, None)
    moisture_changes = analyze_changes(moisture, None)
    return analyze_joint(
        ndvi,
        moisture,
        ndvi_changes=ndvi_changes,
        moisture_changes=moisture_changes,
    )


def test_moisture_down_ndvi_stable_establishes_pattern():
    joint = _divergent_joint()
    assert joint.moisture_key == "ndmi"
    assert any(
        change.divergence == "MOISTURE_DOWN_NDVI_STABLE"
        for change in joint.changes
    )
    patterns = evaluate_moisture_greenness_divergence(joint)
    assert patterns
    for pattern in patterns:
        assert pattern.pattern_type == "MOISTURE_GREENNESS_DIVERGENCE"
        assert pattern.status == "OBSERVED"
        assert pattern.contributing_metric_ids == ("ndmi",)
        assert pattern.contributing_sensors == ("S2",)
        assert "does not identify its cause" in pattern.explanation


def test_non_divergent_state_does_not_establish():
    ndvi = _temporal("ndvi", [0.50, 0.45, 0.40, 0.35])
    moisture = _temporal("ndmi", [0.40, 0.35, 0.30, 0.25])
    joint = analyze_joint(
        ndvi,
        moisture,
        ndvi_changes=analyze_changes(ndvi, None),
        moisture_changes=analyze_changes(moisture, None),
    )
    assert all(
        change.divergence != "MOISTURE_DOWN_NDVI_STABLE"
        for change in joint.changes
    )
    assert evaluate_moisture_greenness_divergence(joint) == ()


def test_true_ndwi_is_never_substituted():
    joint = _divergent_joint()
    impostor = joint.__class__(
        ndvi_key=joint.ndvi_key,
        moisture_key="ndwi",
        window_start=joint.window_start,
        window_end=joint.window_end,
        step=joint.step,
        joint=joint.joint,
        changes=joint.changes,
        lags=joint.lags,
        scatter=joint.scatter,
    )
    with pytest.raises(ValueError, match="never substituted"):
        evaluate_moisture_greenness_divergence(impostor)


def test_wrong_greenness_key_is_refused():
    joint = _divergent_joint()
    impostor = joint.__class__(
        ndvi_key="evi",
        moisture_key=joint.moisture_key,
        window_start=joint.window_start,
        window_end=joint.window_end,
        step=joint.step,
        joint=joint.joint,
        changes=joint.changes,
        lags=joint.lags,
        scatter=joint.scatter,
    )
    with pytest.raises(ValueError, match="greenness"):
        evaluate_moisture_greenness_divergence(impostor)


def test_lag_information_preserved_without_causal_reading():
    joint = _divergent_joint()
    patterns = evaluate_moisture_greenness_divergence(joint)
    assert patterns
    pattern = patterns[0]
    provenance = pattern.provenance_by_evidence[
        pattern.contributing_evidence_ids[0]
    ]
    assert "lags" in provenance
    assert isinstance(provenance["lags"], list)
    lowered = pattern.explanation.lower()
    if "lag" in lowered:
        assert "no lag is preferred" in lowered
        assert "causal order" in lowered


# ==========================================================================
# Pattern 3 — red-edge decline
# ==========================================================================


def test_red_edge_decrease_establishes_pattern():
    items = _red_edge_items(
        [
            ("re_slope_b5_b6", "2024-01-01", "2024-01-31", 0.001, "DECREASE", "good"),
            ("re_nd_b6_b5", "2024-01-01", "2024-01-31", 0.05, "DECREASE", "good"),
            ("re_slope_b5_b6", "2024-02-01", "2024-02-29", 0.002, "INCREASE", "good"),
        ]
    )
    patterns = evaluate_red_edge_decline(items)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_type == "RED_EDGE_DECLINE_PATTERN"
    assert pattern.window_start == "2024-01-01"
    assert set(pattern.contributing_metric_ids) == {
        "re_slope_b5_b6",
        "re_nd_b6_b5",
    }
    assert pattern.contributing_sensors == ("S2",)
    assert "2 diagnostic(s)" in pattern.explanation
    assert "does not identify its cause" in pattern.explanation


def test_no_magnitude_cutoff_for_red_edge():
    items = _red_edge_items(
        [("re_slope_b6_b7", "2024-01-01", "2024-01-31", -0.00001, "DECREASE", "good")]
    )
    patterns = evaluate_red_edge_decline(items)
    assert len(patterns) == 1


def test_insufficient_red_edge_does_not_establish():
    items = _red_edge_items(
        [
            ("re_slope_b5_b6", "2024-01-01", "2024-01-31", None, "DECREASE", "insufficient"),
            ("re_nd_b6_b5", "2024-01-01", "2024-01-31", 0.05, "STABLE", "good"),
        ]
    )
    assert evaluate_red_edge_decline(items) == ()


# ==========================================================================
# Pattern 4 — sustained radar deviation
# ==========================================================================


@pytest.mark.parametrize(
    "metric_key,unit,values",
    [
        ("vv", "dB", [-12.0, -12.0, -12.0, -16.0, -16.0]),
        ("vh", "dB", [-19.0, -19.0, -19.0, -23.0, -23.0]),
        ("vh_vv", "dB", [-7.0, -7.0, -7.0, -10.0, -10.0]),
        ("rvi", "ratio", [0.50, 0.50, 0.50, 0.80, 0.85]),
    ],
)
def test_sustained_radar_deviation_all_metrics(metric_key, unit, values):
    analysis = _radar_analysis(metric_key, values, unit)
    assert analysis.persistence.state == "PERSISTENT"
    patterns = evaluate_sustained_radar_deviation(analysis)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_type == "SUSTAINED_RADAR_DEVIATION"
    assert pattern.status == "OBSERVED"
    assert pattern.contributing_metric_ids == (metric_key,)
    assert pattern.contributing_sensors == ("S1",)
    assert pattern.window_start == "2024-01-01"
    assert "consecutive months" in pattern.explanation
    assert "does not identify its cause" in pattern.explanation
    assert pattern.rule_id == "P32_RADAR_DEVIATION_V1"


def test_non_persistent_radar_does_not_establish():
    analysis = _radar_analysis("vv", [-12.0, -11.0, -10.0], "dB")
    assert analysis.persistence.state != "PERSISTENT"
    assert evaluate_sustained_radar_deviation(analysis) == ()


# ==========================================================================
# Pattern 5 — multi-modal canopy change
# ==========================================================================


def _concordance_month(specs):
    items = [
        make_concordance_evidence(
            family,
            metric_id,
            window[0],
            window[1],
            value,
            quality="good",
            coverage_percent=90.0,
            image_count=3,
            state_kind="anomaly",
            state=state,
        )
        for family, metric_id, window, value, state in specs
    ]
    months = analyze_concordance(items).months
    assert len(months) == 1
    return months[0]


def test_concordant_month_establishes_multi_modal():
    month = _concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("optical", "ndmi", JAN, 0.2, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
            ("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
        ]
    )
    (pattern,) = evaluate_multi_modal_change(month)
    assert pattern.pattern_type == "MULTI_MODAL_CANOPY_CHANGE"
    assert pattern.status == "OBSERVED"
    # S2 metrics do not count as multiple sensors; S1 neither.
    assert pattern.contributing_sensors == ("S1", "S2")
    assert set(pattern.contributing_metric_ids) == {"ndvi", "ndmi", "vh", "vv"}
    assert "compatible observed change" in pattern.explanation


def test_non_concordant_months_do_not_establish():
    optical_only = _concordance_month(
        [("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE")]
    )
    assert evaluate_multi_modal_change(optical_only) == ()
    radar_only = _concordance_month(
        [("radar", "vh", JAN, -19.0, "BELOW_BASELINE")]
    )
    assert evaluate_multi_modal_change(radar_only) == ()
    divergent = _concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "ABOVE_BASELINE"),
        ]
    )
    assert evaluate_multi_modal_change(divergent) == ()


def test_red_edge_does_not_create_third_sensor():
    month = _concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("red_edge", "re_slope_b4_b5", JAN, 0.002, "DECREASE"),
            ("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
        ]
    )
    (pattern,) = evaluate_multi_modal_change(month)
    assert pattern.contributing_sensors == ("S1", "S2")


def test_same_month_evidence_attaches_without_recomputation():
    from app.services.agriculture.pattern_engine import PatternEvidence

    month = _concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ]
    )
    rapid = PatternEvidence(
        evidence_id="ndvi:2024-01-01:change",
        source_module="change_profile",
        metric_id="ndvi",
        sensor="S2",
        family="optical",
        window_start="2024-01-01",
        window_end="2024-01-31",
        value=0.4,
        unit="index",
        anomaly_state=None,
        change_direction="DECREASE",
        rapid="RAPID_DECREASE",
        quality="good",
        coverage_percent=90.0,
        image_count=6,
        provenance={},
        limitations=(),
    )
    other_month = PatternEvidence(
        evidence_id="ndvi:2024-02-01:change",
        source_module="change_profile",
        metric_id="ndvi",
        sensor="S2",
        family="optical",
        window_start="2024-02-01",
        window_end="2024-02-29",
        value=0.4,
        unit="index",
        anomaly_state=None,
        change_direction="DECREASE",
        rapid="RAPID_DECREASE",
        quality="good",
        coverage_percent=90.0,
        image_count=6,
        provenance={},
        limitations=(),
    )
    (pattern,) = evaluate_multi_modal_change(month, [rapid, other_month])
    assert "ndvi:2024-01-01:change" in pattern.contributing_evidence_ids
    assert "ndvi:2024-02-01:change" not in pattern.contributing_evidence_ids
    assert "attached without recomputation" in pattern.explanation


# ==========================================================================
# Composition, determinism, preservation
# ==========================================================================


def test_multiple_named_patterns_coexist_without_ranking():
    changes = [c for c in _ndvi_jump() if c.rapid == "RAPID_DECREASE"]
    rapid = evaluate_rapid_canopy_decline("ndvi", tuple(changes))
    red_edge = evaluate_red_edge_decline(
        _red_edge_items(
            [("re_slope_b5_b6", "2024-08-01", "2024-08-31", 0.001, "DECREASE", "good")]
        )
    )
    month = _concordance_month(
        [
            ("optical", "ndvi", ("2024-08-01", "2024-08-31"), 0.3, "BELOW_BASELINE"),
            ("radar", "vh", ("2024-08-01", "2024-08-31"), -19.5, "BELOW_BASELINE"),
        ]
    )
    multi_modal = evaluate_multi_modal_change(month)
    combined = sort_named_patterns(list(rapid) + list(red_edge) + list(multi_modal))
    assert [p.pattern_type for p in combined] == [
        "RAPID_CANOPY_SIGNAL_DECLINE",
        "RED_EDGE_DECLINE_PATTERN",
        "MULTI_MODAL_CANOPY_CHANGE",
    ]
    assert not any("RISK" in p.pattern_type for p in combined)


def test_deterministic_repeat_evaluation():
    joint = _divergent_joint()
    first = [p.to_dict() for p in evaluate_moisture_greenness_divergence(joint)]
    second = [p.to_dict() for p in evaluate_moisture_greenness_divergence(joint)]
    assert first == second
    assert first[0]["pattern_id"].startswith("P32_MOISTURE_DIVERGENCE_V1:")


def test_missing_evidence_creates_no_pattern():
    assert evaluate_rapid_canopy_decline("ndvi", ()) == ()
    assert evaluate_red_edge_decline([]) == ()
    assert evaluate_multi_modal_change(
        _concordance_month(
            [
                ("optical", "ndvi", JAN, None, None),
                ("radar", "vh", JAN, None, None),
            ]
        )
    ) == ()


def test_pydantic_round_trip_on_p31_contract():
    from app.schemas.agriculture import EvidencePatternModel

    changes = [c for c in _ndvi_jump() if c.rapid == "RAPID_DECREASE"]
    (pattern,) = evaluate_rapid_canopy_decline("ndvi", tuple(changes))
    model = EvidencePatternModel.model_validate(pattern.to_dict())
    assert model.pattern_type == "RAPID_CANOPY_SIGNAL_DECLINE"
    assert model.status == "OBSERVED"
    assert model.contributing_metric_ids == ["ndvi"]
    dumped = model.model_dump()
    assert EvidencePatternModel.model_validate(dumped) == model


# ==========================================================================
# Guards: no database, no cause attribution, no scores, no new statistics
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.named_patterns as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def test_no_database_access():
    code = _code_without_docstrings()
    assert "app.db" not in code
    assert "sqlalchemy" not in code
    assert "alembic" not in code


def test_no_biological_classification():
    code = _code_without_docstrings().lower()
    for stem in (
        "pest",
        "disease",
        "pathogen",
        "infest",
        "defoliat",
        "vascular",
        "borer",
        "fungal",
        "chlorosis",
        "diagnosi",
        "diagnose",
        "severity",
        "damage",
        "health",
        "nutrient",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"


def test_no_causal_claim_language():
    code = _code_without_docstrings().lower()
    for phrase in (
        "caused by",
        "indicates pest",
        "indicates disease",
        "confirms",
        "diagnostic of",
        "characteristic of",
        "leads to",
    ):
        assert phrase not in code, f"forbidden phrase {phrase!r} in code"


def test_no_probability_risk_or_new_statistics():
    code = _code_without_docstrings()
    lowered = code.lower()
    for stem in (
        "probab",
        "risk",
        "confiden",
        "threshold",
        "correlat",
        "regress",
        "pearson",
        "sklearn",
        "torch",
        "tensorflow",
        "predict",
        "neural",
        "classifier",
        "statistics",
        "np.mean",
        "np.std",
        "stdev",
        "polyfit",
    ):
        assert stem not in lowered, f"forbidden stem {stem!r} in code"
    import app.services.agriculture.named_patterns as module

    names = " ".join(dir(module)).lower()
    assert "risk" not in names
    assert "probab" not in names


def test_no_interpolation_or_zero_fill_in_implementation():
    code = _code_without_docstrings().lower()
    assert "interpolat" not in code
    assert "fillna" not in code
    assert "resample" not in code
    import app.services.agriculture.named_patterns as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for match in re.finditer(r"interpolat", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "never" in window or "no " in window


def test_module_creates_no_second_engine_or_cache_or_db():
    code = _code_without_docstrings()
    assert "register_metric" not in code
    assert "cache_service" not in code
    assert "def compute_baseline" not in code
    assert "def score_profile" not in code
    assert "def month_changes" not in code
