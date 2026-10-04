"""Tests for the P3.3 cross-pattern validation layer.

Covers validation over already-established P3.1/P3.2 pattern
outputs only: compatible same-window patterns, opposing and
explicitly divergent patterns, insufficient and unavailable
sources, exact temporal identity (no merging, no shifting, gaps
break, multi-month spans preserved), duplicate evidence
protection with S1/S2 independence, descriptive
moisture/greenness handling, provenance preservation, ordering
determinism, and the wording guards (no scores, no confidence or
probability, no biological interpretation, no raw-value
reinterpretation).

Patterns are built with the real P3.1/P3.2 evaluators over real
P1/P2 states wherever possible; this layer performs no Earth
Engine calls itself.  No network and no credentials are required.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import List, Optional

from app.services.agriculture.baseline_anomaly import score_profile
from app.services.agriculture.change_profile import analyze_changes
from app.services.agriculture.concordance import analyze_concordance
from app.services.agriculture.concordance import (
    make_evidence as make_concordance_evidence,
)
from app.services.agriculture.cross_pattern_validation import (
    RULE_COMPATIBLE,
    RULE_DIVERGENCE,
    RULE_MISSING,
    RULE_MOISTURE_DESCRIPTIVE,
    RULE_SENSOR_AGREEMENT,
    STATUS_CONSISTENT,
    STATUS_INSUFFICIENT,
    STATUS_MIXED,
    VALIDATION_RULES,
    VALIDATION_STATUSES,
    VALIDATION_VERSION,
    CrossPatternValidation,
    get_validation_rule,
    sort_validations,
    validate_all,
    validate_window,
)
from app.services.agriculture.joint_profile import analyze_joint
from app.services.agriculture.named_patterns import (
    evaluate_moisture_greenness_divergence,
    evaluate_multi_modal_change,
    evaluate_rapid_canopy_decline,
    evaluate_red_edge_decline,
    evaluate_sustained_radar_deviation,
)
from app.services.agriculture.pattern_engine import (
    PATTERN_INSUFFICIENT,
    PatternEvidence,
    evaluate_concordance_month,
    evaluate_rapid_changes,
)
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


JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")
MAR = ("2024-03-01", "2024-03-31")
AUG = ("2024-08-01", "2024-08-31")


def _temporal(
    metric_key: str,
    values: List[Optional[float]],
    unit: str = "index",
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
        dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        unit=unit,
        window_start=start,
        window_end=windows[-1][1],
        points=points,
    )


def _ndvi_rapid_decline():
    profile = _temporal(
        "ndvi", [0.60, 0.62, 0.60, 0.61, 0.60, 0.62, 0.61, 0.30]
    )
    anomalies = score_profile(profile)
    changes = tuple(
        change
        for change in analyze_changes(profile, anomalies).changes
        if change.rapid == "RAPID_DECREASE"
    )
    assert changes, "expected a real P1.3 rapid NDVI decline in the fixture"
    return evaluate_rapid_canopy_decline("ndvi", changes)


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


def _concordance_series(specs):
    items = [
        make_concordance_evidence(
            family,
            metric_id,
            window[0],
            window[1],
            value,
            quality="good" if value is not None else "insufficient",
            coverage_percent=90.0 if value is not None else None,
            image_count=3 if value is not None else None,
            state_kind="anomaly",
            state=state,
        )
        for family, metric_id, window, value, state in specs
    ]
    return analyze_concordance(items)


def _single_concordance_month(specs):
    months = _concordance_series(specs).months
    assert len(months) == 1
    return months[0]


def _divergent_joint():
    ndvi = _temporal("ndvi", [0.50, 0.50, 0.50, 0.50])
    moisture = _temporal("ndmi", [0.40, 0.35, 0.30, 0.25])
    return analyze_joint(
        ndvi,
        moisture,
        ndvi_changes=analyze_changes(ndvi, None),
        moisture_changes=analyze_changes(moisture, None),
    )


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
    pols = {"vv": ("VV",), "vh": ("VH",)}[metric_key]
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


def _up_rapid_pattern(window):
    item = PatternEvidence(
        evidence_id=f"vv:{window[0]}:change",
        source_module="radar_anomaly",
        metric_id="vv",
        sensor="S1",
        family="radar",
        window_start=window[0],
        window_end=window[1],
        value=-9.0,
        unit="dB",
        anomaly_state=None,
        change_direction="INCREASE",
        rapid="RAPID_INCREASE",
        quality="good",
        coverage_percent=90.0,
        image_count=3,
        provenance={},
        limitations=(),
    )
    (pattern,) = evaluate_rapid_changes([item])
    return pattern


def _august_trio():
    (rapid,) = _ndvi_rapid_decline()
    window = (rapid.window_start, rapid.window_end)
    assert window == AUG
    (red_edge,) = evaluate_red_edge_decline(
        _red_edge_items(
            [
                ("re_slope_b5_b6", window[0], window[1], 0.001, "DECREASE", "good"),
                ("re_nd_b6_b5", window[0], window[1], 0.05, "DECREASE", "good"),
            ]
        )
    )
    month = _single_concordance_month(
        [
            ("optical", "ndvi", window, 0.3, "BELOW_BASELINE"),
            ("radar", "vh", window, -19.5, "BELOW_BASELINE"),
        ]
    )
    (multi_modal,) = evaluate_multi_modal_change(month)
    return rapid, red_edge, multi_modal, window


# ==========================================================================
# Statuses: compatible, mixed, insufficient
# ==========================================================================


def test_compatible_same_month_patterns():
    (rapid,) = _ndvi_rapid_decline()
    window = (rapid.window_start, rapid.window_end)
    (red_edge,) = evaluate_red_edge_decline(
        _red_edge_items(
            [("re_slope_b5_b6", window[0], window[1], 0.001, "DECREASE", "good")]
        )
    )
    result = validate_window([rapid, red_edge], window[0], window[1])
    assert result.status == STATUS_CONSISTENT == "CONSISTENT"
    assert result.rule_id == RULE_COMPATIBLE
    assert set(result.compatible_pattern_ids) == {
        rapid.pattern_id,
        red_edge.pattern_id,
    }
    assert result.conflicting_pattern_ids == ()
    assert result.window_start == window[0]
    assert result.window_end == window[1]
    assert "compatible observed" in result.explanation.lower()


def test_opposing_directions_yield_mixed_evidence():
    (rapid,) = _ndvi_rapid_decline()
    window = (rapid.window_start, rapid.window_end)
    up_pattern = _up_rapid_pattern(window)
    result = validate_window([rapid, up_pattern], window[0], window[1])
    assert result.status == STATUS_MIXED == "MIXED_EVIDENCE"
    assert result.rule_id == RULE_DIVERGENCE
    assert set(result.conflicting_pattern_ids) == {
        rapid.pattern_id,
        up_pattern.pattern_id,
    }
    assert "mixed evidence" in result.explanation.lower()


def test_insufficient_source_pattern_preserved():
    (month,) = _concordance_series(
        [
            ("optical", "ndvi", JAN, None, None),
            ("radar", "vh", JAN, None, None),
        ]
    ).months
    (insufficient,) = evaluate_concordance_month(month)
    assert insufficient.pattern_type == PATTERN_INSUFFICIENT
    result = validate_window([insufficient], JAN[0], JAN[1])
    assert result.status == STATUS_INSUFFICIENT == "INSUFFICIENT_EVIDENCE"
    assert result.rule_id == RULE_MISSING
    assert result.contributing_pattern_ids == (insufficient.pattern_id,)
    assert result.compatible_pattern_ids == ()
    assert result.conflicting_pattern_ids == ()


def test_unavailable_source_pattern_preserved():
    (rapid,) = _ndvi_rapid_decline()
    unavailable = dataclasses.replace(
        rapid,
        quality_by_evidence={
            evidence_id: "unavailable"
            for evidence_id in rapid.contributing_evidence_ids
        },
    )
    result = validate_window(
        [unavailable], rapid.window_start, rapid.window_end
    )
    assert result.status == STATUS_INSUFFICIENT
    assert result.rule_id == RULE_MISSING
    assert result.compatible_pattern_ids == ()
    assert result.conflicting_pattern_ids == ()


def test_missing_pattern_yields_insufficient():
    result = validate_window([], JAN[0], JAN[1])
    assert result.status == STATUS_INSUFFICIENT
    assert result.rule_id == RULE_MISSING
    assert result.contributing_pattern_ids == ()
    assert validate_all(()) == ()


# ==========================================================================
# Exact temporal semantics
# ==========================================================================


def test_exact_month_matching():
    rapid, red_edge, _, window = _august_trio()
    result = validate_window([rapid, red_edge], window[0], window[1])
    assert set(result.contributing_pattern_ids) == {
        rapid.pattern_id,
        red_edge.pattern_id,
    }
    assert result.provenance["rejected_pattern_ids"] == []
    assert result.provenance["evaluated_window"] == {
        "window_start": window[0],
        "window_end": window[1],
    }


def test_nonmatching_month_rejection():
    (rapid,) = _ndvi_rapid_decline()
    result = validate_window([rapid], JAN[0], JAN[1])
    assert result.status == STATUS_INSUFFICIENT
    assert result.contributing_pattern_ids == ()
    assert result.provenance["rejected_pattern_ids"] == [rapid.pattern_id]


def test_temporal_gap_behavior():
    january = _single_concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ]
    )
    march = _single_concordance_month(
        [
            ("optical", "ndvi", MAR, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", MAR, -19.0, "BELOW_BASELINE"),
        ]
    )
    (january_modal,) = evaluate_multi_modal_change(january)
    (march_modal,) = evaluate_multi_modal_change(march)
    results = validate_all([january_modal, march_modal])
    assert len(results) == 2
    assert (results[0].window_start, results[0].window_end) == JAN
    assert (results[1].window_start, results[1].window_end) == MAR
    assert all(item.status == STATUS_CONSISTENT for item in results)


def test_multi_month_span_preservation():
    analysis = _radar_analysis("vv", [-12.0, -12.0, -12.0, -16.0, -16.0], "dB")
    assert analysis.persistence.state == "PERSISTENT"
    (sustained,) = evaluate_sustained_radar_deviation(analysis)
    assert sustained.window_start == "2024-01-01"
    assert sustained.window_end == "2024-05-31"
    (result,) = validate_all([sustained])
    assert result.status == STATUS_CONSISTENT
    assert result.window_start == "2024-01-01"
    assert result.window_end == "2024-05-31"
    assert result.contributing_pattern_ids == (sustained.pattern_id,)


# ==========================================================================
# Overlap and sensor independence
# ==========================================================================


def test_duplicate_evidence_detection():
    rapid, _, multi_modal, window = _august_trio()
    result = validate_window([rapid, multi_modal], window[0], window[1])
    assert result.overlapping_evidence is True
    assert "ndvi" in result.overlapping_metric_ids
    assert "audit" in result.overlap_explanation.lower()
    assert "strength" in result.overlap_explanation.lower()


def test_s1_s2_independence():
    rapid, _, multi_modal, window = _august_trio()
    result = validate_window([rapid, multi_modal], window[0], window[1])
    assert result.contributing_sensors == ("S1", "S2")
    assert result.independent_sensor_count == 2
    assert result.pattern_count == 2
    # Two S2-only patterns still count one independent sensor.
    (red_edge,) = evaluate_red_edge_decline(
        _red_edge_items(
            [("re_slope_b5_b6", window[0], window[1], 0.001, "DECREASE", "good")]
        )
    )
    same_sensor = validate_window([rapid, red_edge], window[0], window[1])
    assert same_sensor.contributing_sensors == ("S2",)
    assert same_sensor.independent_sensor_count == 1
    assert same_sensor.pattern_count == 2


def test_p25_concordance_not_double_counted():
    rapid, _, multi_modal, window = _august_trio()
    month = _single_concordance_month(
        [
            ("optical", "ndvi", window, 0.3, "BELOW_BASELINE"),
            ("radar", "vh", window, -19.5, "BELOW_BASELINE"),
        ]
    )
    (generic_concordance,) = evaluate_concordance_month(month)
    result = validate_window(
        [generic_concordance, multi_modal, rapid], window[0], window[1]
    )
    assert result.status == STATUS_CONSISTENT
    assert result.rule_id == RULE_SENSOR_AGREEMENT
    assert result.contributing_sensors == ("S1", "S2")
    assert result.independent_sensor_count == 2
    assert result.overlapping_evidence is True
    assert "counted once" in result.overlap_explanation.lower()


def test_moisture_greenness_divergence_remains_descriptive():
    joint = _divergent_joint()
    patterns = evaluate_moisture_greenness_divergence(joint)
    assert patterns
    window = (patterns[0].window_start, patterns[0].window_end)
    window_patterns = [
        pattern
        for pattern in patterns
        if (pattern.window_start, pattern.window_end) == window
    ]
    assert window_patterns
    result = validate_window(list(window_patterns), window[0], window[1])
    assert result.status == STATUS_MIXED
    assert result.rule_id == RULE_MOISTURE_DESCRIPTIVE
    lowered = result.explanation.lower()
    assert "descriptive divergence" in lowered
    assert "causal order" in lowered
    assert set(result.conflicting_pattern_ids) == {
        pattern.pattern_id for pattern in window_patterns
    }
    # Every divergence window validates the same way; windows never merge.
    grouped = validate_all(list(patterns))
    assert {item.window_start for item in grouped} == {
        pattern.window_start for pattern in patterns
    }
    assert all(item.status == STATUS_MIXED for item in grouped)


# ==========================================================================
# Provenance and identity
# ==========================================================================


def test_named_pattern_provenance_preserved():
    rapid, _, _, window = _august_trio()
    joint = _divergent_joint()
    moisture = evaluate_moisture_greenness_divergence(joint)
    moisture_window = (moisture[0].window_start, moisture[0].window_end)
    rapid_result = validate_window([rapid], window[0], window[1])
    provenance = rapid_result.provenance["source_provenance"][
        rapid.pattern_id
    ]
    change_payload = provenance[rapid.contributing_evidence_ids[0]]["change"]
    assert change_payload["rapid"] == "RAPID_DECREASE"
    moisture_result = validate_window(
        list(moisture), moisture_window[0], moisture_window[1]
    )
    moisture_provenance = moisture_result.provenance["source_provenance"][
        moisture[0].pattern_id
    ]
    assert "lags" in moisture_provenance[
        moisture[0].contributing_evidence_ids[0]
    ]
    assert rapid_result.rule_version == VALIDATION_VERSION
    assert moisture_result.rule_version == VALIDATION_VERSION


def test_source_metric_identity_preserved():
    rapid, red_edge, multi_modal, window = _august_trio()
    result = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    assert set(result.contributing_metric_ids) == (
        set(rapid.contributing_metric_ids)
        | set(red_edge.contributing_metric_ids)
        | set(multi_modal.contributing_metric_ids)
    )
    assert "ndvi" in result.contributing_metric_ids
    assert "red_edge" in result.contributing_families
    assert "optical" in result.contributing_families
    assert "radar" in result.contributing_families
    assert result.source_pattern_types[rapid.pattern_id] == (
        "RAPID_CANOPY_SIGNAL_DECLINE"
    )
    assert result.source_pattern_states[rapid.pattern_id] == "OBSERVED"


# ==========================================================================
# Determinism and ordering
# ==========================================================================


def test_deterministic_ordering():
    rapid, red_edge, multi_modal, window = _august_trio()
    forward = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    backward = validate_window(
        [multi_modal, red_edge, rapid], window[0], window[1]
    )
    assert forward.to_dict() == backward.to_dict()
    january = _single_concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ]
    )
    (january_modal,) = evaluate_multi_modal_change(january)
    ordered = validate_all([multi_modal, january_modal])
    assert [item.window_start for item in ordered] == [JAN[0], window[0]]
    assert sort_validations(list(reversed(ordered))) == ordered


def test_repeated_evaluation_deterministic():
    rapid, red_edge, _, window = _august_trio()
    first = validate_window([rapid, red_edge], window[0], window[1])
    second = validate_window([rapid, red_edge], window[0], window[1])
    assert first.to_dict() == second.to_dict()
    assert first.validation_id.startswith(f"{RULE_COMPATIBLE}:")
    assert validate_all([rapid, red_edge]) == validate_all([rapid, red_edge])


# ==========================================================================
# Coexistence without reinterpretation
# ==========================================================================


def test_compatible_triple_coexistence():
    rapid, red_edge, multi_modal, window = _august_trio()
    result = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    assert result.status == STATUS_CONSISTENT
    assert result.rule_id == RULE_SENSOR_AGREEMENT
    assert set(result.compatible_pattern_ids) == {
        rapid.pattern_id,
        red_edge.pattern_id,
        multi_modal.pattern_id,
    }
    assert result.conflicting_pattern_ids == ()
    assert "common biological cause" in result.explanation


def test_divergent_sensor_evidence_preserved_as_mixed():
    month = _single_concordance_month(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "ABOVE_BASELINE"),
        ]
    )
    (divergent,) = evaluate_concordance_month(month)
    assert divergent.pattern_type == "DIVERGENT_SENSOR_EVIDENCE"
    result = validate_window([divergent], JAN[0], JAN[1])
    assert result.status == STATUS_MIXED
    assert result.rule_id == RULE_DIVERGENCE
    assert result.conflicting_pattern_ids == (divergent.pattern_id,)


def test_insufficient_evidence_never_becomes_negative_evidence():
    (month,) = _concordance_series(
        [
            ("optical", "ndvi", FEB, None, None),
            ("radar", "vh", FEB, None, None),
        ]
    ).months
    (insufficient,) = evaluate_concordance_month(month)
    result = validate_window([insufficient], FEB[0], FEB[1])
    assert result.status == STATUS_INSUFFICIENT
    lowered = result.explanation.lower()
    assert "no negative finding" in lowered
    assert "no change occurred" not in lowered
    assert "unchanged" not in lowered
    assert result.source_pattern_states[insufficient.pattern_id] == (
        "INSUFFICIENT_EVIDENCE"
    )


def test_mixed_evidence_does_not_select_a_winner():
    (rapid,) = _ndvi_rapid_decline()
    window = (rapid.window_start, rapid.window_end)
    up_pattern = _up_rapid_pattern(window)
    forward = validate_window([rapid, up_pattern], window[0], window[1])
    backward = validate_window([up_pattern, rapid], window[0], window[1])
    assert forward.to_dict() == backward.to_dict()
    assert set(forward.conflicting_pattern_ids) == {
        rapid.pattern_id,
        up_pattern.pattern_id,
    }
    lowered = forward.explanation.lower()
    assert "no winner" in lowered or "none preferred" in lowered
    assert "correct pattern" not in lowered
    assert "prevails" not in lowered


def test_no_raw_value_reinterpretation():
    from app.services.agriculture.change_profile import MonthChange

    def _decline(absolute: float, relative: float, rate: float):
        return MonthChange(
            window_start=AUG[0],
            window_end=AUG[1],
            value=0.30,
            previous_value=0.61,
            absolute_change=absolute,
            relative_change=relative,
            days_elapsed=31,
            rate_per_day=rate,
            direction="DECREASE",
            rapid="RAPID_DECREASE",
            unit="index",
            quality="good",
        )

    first = evaluate_rapid_canopy_decline("ndvi", (_decline(-0.31, -0.5, -0.01),))
    second = evaluate_rapid_canopy_decline("ndvi", (_decline(-0.10, -0.2, -0.003),))
    first_result = validate_window(list(first), AUG[0], AUG[1])
    second_result = validate_window(list(second), AUG[0], AUG[1])
    assert first_result.status == second_result.status == STATUS_CONSISTENT
    assert first_result.rule_id == second_result.rule_id
    assert first_result.compatible_pattern_ids == (
        second_result.compatible_pattern_ids
    )
    assert first_result.conflicting_pattern_ids == (
        second_result.conflicting_pattern_ids
    )


def test_provenance_survives_serialization_round_trip():
    from app.schemas.agriculture import (
        CrossPatternValidationModel,
        ValidationRuleModel,
    )

    rapid, red_edge, multi_modal, window = _august_trio()
    result = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    payload = result.to_dict()
    assert CrossPatternValidation.from_dict(payload).to_dict() == payload
    model = CrossPatternValidationModel.model_validate(payload)
    assert model.status == STATUS_CONSISTENT
    assert model.validation_id == result.validation_id
    assert CrossPatternValidationModel.model_validate(model.model_dump()) == model
    rule = ValidationRuleModel.model_validate(
        get_validation_rule(result.rule_id).to_dict()
    )
    assert rule.rule_version == VALIDATION_VERSION


# ==========================================================================
# Registry and guards: no scores, no biology, no storage
# ==========================================================================


def test_rule_registry_is_deterministic():
    assert [rule.rule_id for rule in VALIDATION_RULES] == [
        RULE_COMPATIBLE,
        RULE_DIVERGENCE,
        RULE_SENSOR_AGREEMENT,
        RULE_MOISTURE_DESCRIPTIVE,
        RULE_MISSING,
    ]
    assert set(VALIDATION_STATUSES) == {
        "CONSISTENT",
        "MIXED_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
    }
    assert all(rule.rule_version == VALIDATION_VERSION for rule in VALIDATION_RULES)
    assert get_validation_rule(RULE_SENSOR_AGREEMENT).pattern_type == (
        "CONSISTENT"
    )
    try:
        get_validation_rule("P33_PEST_V1")
    except KeyError as exc:
        assert "not registered" in str(exc)
    else:  # pragma: no cover - registry must refuse unknown rules
        raise AssertionError("unknown validation rule was accepted")


def test_no_numeric_score_generated():
    rapid, red_edge, multi_modal, window = _august_trio()
    result = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    payload = result.to_dict()
    for key in payload:
        lowered = key.lower()
        assert "score" not in lowered, f"score-like field {key!r}"
        assert "grade" not in lowered, f"grade-like field {key!r}"
        assert "strength" not in lowered, f"strength-like field {key!r}"
        assert "weight" not in lowered, f"weight-like field {key!r}"
    assert isinstance(payload["pattern_count"], int)
    assert isinstance(payload["independent_sensor_count"], int)
    assert isinstance(payload["overlapping_evidence"], bool)
    top_floats = [
        key for key, value in payload.items() if isinstance(value, float)
    ]
    assert top_floats == []


def test_no_confidence_probability_generated():
    rapid, red_edge, multi_modal, window = _august_trio()
    result = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    payload = result.to_dict()
    for key in payload:
        lowered = key.lower()
        assert "confiden" not in lowered
        assert "probab" not in lowered
        assert "risk" not in lowered
    text = " ".join(
        [
            result.explanation,
            result.overlap_explanation,
            result.rule_description,
            *result.limitations,
        ]
    ).lower()
    assert "confidence" not in text
    assert "probability" not in text
    assert "risk" not in text


def test_no_biological_interpretation_generated():
    rapid, red_edge, multi_modal, window = _august_trio()
    result = validate_window(
        [rapid, red_edge, multi_modal], window[0], window[1]
    )
    texts = [
        result.explanation,
        result.overlap_explanation,
        result.rule_description,
        *result.limitations,
    ]
    for text in texts:
        lowered = text.lower()
        for stem in (
            "pest",
            "disease",
            "pathogen",
            "infest",
            "defoliat",
            "vascular",
            "fungal",
            "chlorosis",
            "nutrient",
            "borer",
            "diagnosi",
            "diagnose",
            "severity",
            "damage",
            "health",
            "stress",
        ):
            assert stem not in lowered, f"forbidden stem {stem!r} in {text!r}"
    assert "compatible observed" in result.explanation.lower()
    # "cause" may only appear inside an explicit negation.
    for text in texts:
        for match in re.finditer(r"cause", text.lower()):
            context = text.lower()[max(0, match.start() - 40): match.end()]
            assert (
                "does not" in context
                or "never" in context
                or "not " in context
                or "no " in context
            ), f"non-negated 'cause' in {text!r}"


def _code_without_docstrings() -> str:
    import app.services.agriculture.cross_pattern_validation as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def test_no_raw_value_access_in_implementation():
    code = _code_without_docstrings()
    # ".value" attribute reads are forbidden; the ".values()"
    # mapping method is unrelated and is excluded precisely.
    assert not re.search(r"\.value(?!s\()", code), "raw-value read in code"
    for snippet in (
        '["value"]',
        "['value']",
        "absolute_change",
        "relative_change",
        "rate_per_day",
        "z_score",
        "z-score",
        "previous_value",
    ):
        assert snippet not in code, f"raw-value access {snippet!r} in code"


def test_no_biological_or_statistical_machinery_in_implementation():
    code = _code_without_docstrings()
    lowered = code.lower()
    for stem in (
        "pest",
        "disease",
        "pathogen",
        "infest",
        "defoliat",
        "vascular",
        "fungal",
        "chlorosis",
        "nutrient",
        "borer",
        "diagnosi",
        "diagnose",
        "severity",
        "damage",
        "health",
        "stress",
        "probab",
        "risk",
        "confiden",
        "threshold",
        "correlat",
        "regress",
        "sklearn",
        "torch",
        "tensorflow",
        "predict",
        "neural",
        "classifier",
        "statistics",
        "stdev",
        "polyfit",
        "score",
    ):
        assert stem not in lowered, f"forbidden stem {stem!r} in code"
    import app.services.agriculture.cross_pattern_validation as module

    names = " ".join(dir(module)).lower()
    assert "risk" not in names
    assert "probab" not in names
    assert "score" not in names


def test_no_interpolation_or_zero_fill_in_implementation():
    code = _code_without_docstrings().lower()
    assert "fillna" not in code
    assert "resample" not in code
    import app.services.agriculture.cross_pattern_validation as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for match in re.finditer(r"interpolat", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "never" in window or "no " in window


def test_module_touches_no_database_cache_or_endpoints():
    code = _code_without_docstrings()
    for snippet in (
        "app.db",
        "sqlalchemy",
        "alembic",
        "cache_service",
        "register_metric",
        "APIRouter",
        "app.get",
        "app.post",
    ):
        assert snippet not in code, f"storage/endpoint snippet {snippet!r} in code"
