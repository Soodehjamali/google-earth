"""Tests for the P3.1 Evidence Pattern Engine foundation.

Covers the deterministic rule registry, stable pattern IDs and
ordering, the five generic patterns plus insufficient evidence,
exact window identity, source preservation, coexistence without
double counting, red-edge sensor semantics, and the terminology
guards (no cause attribution, no scores, no ML).

Rules consume real P1.2/P1.3 objects (score_profile,
analyze_changes, persistence_of) and real P2.5 concordance
months (analyze_concordance); this layer performs no Earth
Engine calls itself.  No network and no credentials are required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import pytest

from app.services.agriculture.baseline_anomaly import score_profile
from app.services.agriculture.change_profile import (
    analyze_changes,
    persistence_of,
)
from app.services.agriculture.concordance import (
    analyze_concordance,
    make_evidence as make_concordance_evidence,
)
from app.services.agriculture.pattern_engine import (
    ENGINE_VERSION,
    PATTERN_ORDER,
    PATTERN_TYPES,
    RULES,
    MetricEvidenceBundle,
    evaluate_all,
    evaluate_concordance_month,
    evaluate_persistent_anomaly,
    evaluate_rapid_changes,
    evaluate_sequential_changes,
    evidence_from_anomaly_point,
    evidence_from_concordance_item,
    evidence_from_month_change,
    evidence_from_red_edge_change,
    get_rule,
    sort_patterns,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)
from app.utils.dates import get_monthly_periods


def _temporal(
    metric_key: str,
    values: List[Optional[float]],
    unit: str = "dB",
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
            image_count=3 if value is not None else None,
        )
        for (window_start, window_end), value in zip(windows, values)
    )
    return TemporalProfile(
        metric_key=metric_key,
        dataset_id="COPERNICUS/S1_GRD",
        unit=unit,
        window_start=start,
        window_end=windows[-1][1],
        points=points,
    )


def _bundle(
    metric_id: str,
    values: List[Optional[float]],
    sensor: str = "S1",
    family: str = "radar",
    source_module: str = "radar_anomaly",
    unit: str = "dB",
) -> MetricEvidenceBundle:
    profile = _temporal(metric_id, values, unit=unit)
    anomalies = score_profile(profile)
    changes = analyze_changes(profile, anomalies).changes
    return MetricEvidenceBundle(
        metric_id=metric_id,
        sensor=sensor,
        family=family,
        source_module=source_module,
        anomalies=anomalies,
        persistence=persistence_of(anomalies),
        changes=tuple(changes),
        provenance_by_window={},
    )


def _concordance_months(specs):
    items = []
    for family, metric_id, window, value, state in specs:
        items.append(
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
        )
    return analyze_concordance(items).months


JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")
MAR = ("2024-03-01", "2024-03-31")
APR = ("2024-04-01", "2024-04-30")


# ==========================================================================
# Registry, IDs, ordering
# ==========================================================================


def test_rule_registry_is_deterministic():
    assert [rule.rule_id for rule in RULES] == [
        "P31_PERSISTENT_ANOMALY_V1",
        "P31_RAPID_CHANGE_V1",
        "P31_CONCORDANCE_V1",
        "P31_DIVERGENCE_V1",
        "P31_SEQUENTIAL_CHANGE_V1",
        "P31_INSUFFICIENT_V1",
    ]
    assert [rule.pattern_type for rule in RULES] == list(PATTERN_ORDER)
    assert all(rule.rule_version == ENGINE_VERSION for rule in RULES)
    assert get_rule("P31_RAPID_CHANGE_V1").pattern_type == "RAPID_CHANGE"
    with pytest.raises(KeyError, match="not registered"):
        get_rule("P31_PEST_V1")


def test_pattern_types_are_generic_only():
    assert set(PATTERN_TYPES) == {
        "PERSISTENT_ANOMALY",
        "RAPID_CHANGE",
        "MULTI_SENSOR_CONCORDANCE",
        "DIVERGENT_SENSOR_EVIDENCE",
        "SEQUENTIAL_CHANGE",
        "INSUFFICIENT_EVIDENCE",
    }


def test_pattern_ids_are_stable():
    bundle = _bundle("vv", [-12.0, -12.0, -12.0, -16.0, -16.0])
    first = [p.pattern_id for p in evaluate_all([bundle], [])]
    second = [p.pattern_id for p in evaluate_all([bundle], [])]
    assert first == second
    assert len(set(first)) == len(first)


def test_pattern_ordering_is_deterministic():
    bundle = _bundle(
        "vv",
        [-12.1, -11.9, -12.0, -12.1, -11.9, -12.0, -12.05, -9.0],
    )
    months = _concordance_months(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
            ("optical", "ndvi", FEB, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", FEB, -19.0, "ABOVE_BASELINE"),
            ("optical", "ndvi", MAR, None, None),
            ("radar", "vh", MAR, None, None),
        ]
    )
    patterns = evaluate_all([bundle], months)
    types = [p.pattern_type for p in patterns]
    assert types == sorted(types, key=list(PATTERN_ORDER).index)
    assert "PERSISTENT_ANOMALY" in types
    assert "RAPID_CHANGE" in types
    assert "MULTI_SENSOR_CONCORDANCE" in types
    assert "DIVERGENT_SENSOR_EVIDENCE" in types
    assert "INSUFFICIENT_EVIDENCE" in types


# ==========================================================================
# Foundation patterns
# ==========================================================================


def test_persistent_anomaly_pattern():
    bundle = _bundle("vv", [-12.0, -12.0, -12.0, -16.0, -16.0])
    assert bundle.persistence.state == "PERSISTENT"
    pattern = evaluate_persistent_anomaly(
        bundle.metric_id,
        bundle.sensor,
        bundle.family,
        bundle.source_module,
        bundle.anomalies,
        bundle.persistence,
        bundle.provenance_by_window,
    )
    assert pattern is not None
    assert pattern.pattern_type == "PERSISTENT_ANOMALY"
    assert pattern.status == "OBSERVED"
    assert pattern.contributing_metric_ids == ("vv",)
    assert pattern.contributing_sensors == ("S1",)
    assert pattern.window_start == "2024-01-01"
    assert pattern.window_end == "2024-05-31"
    assert "vv" in pattern.explanation and "2024-01-01" in pattern.explanation
    assert "biological cause" in pattern.explanation
    assert pattern.rule_id == "P31_PERSISTENT_ANOMALY_V1"


def test_no_persistent_pattern_without_persistence():
    bundle = _bundle("vv", [-12.0, -11.0, -10.0])
    assert bundle.persistence.state == "NO_PERSISTENCE"
    assert evaluate_persistent_anomaly(
        bundle.metric_id,
        bundle.sensor,
        bundle.family,
        bundle.source_module,
        bundle.anomalies,
        bundle.persistence,
        bundle.provenance_by_window,
    ) is None


def test_rapid_change_pattern():
    bundle = _bundle(
        "vv", [-12.1, -11.9, -12.0, -12.1, -11.9, -12.0, -12.05, -9.0]
    )
    items = [
        evidence_from_month_change(
            bundle.source_module,
            bundle.metric_id,
            bundle.sensor,
            bundle.family,
            change,
        )
        for change in bundle.changes
    ]
    patterns = evaluate_rapid_changes(items)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_type == "RAPID_CHANGE"
    assert pattern.status == "OBSERVED"
    assert pattern.window_start == "2024-08-01"
    assert pattern.source_states[pattern.contributing_evidence_ids[0]] in (
        "RAPID_INCREASE",
        "RAPID_DECREASE",
    )
    assert "biological cause" in pattern.explanation


def test_rapid_rule_ignores_non_rapid_changes():
    bundle = _bundle("vv", [-12.0, -11.9, -11.8])
    items = [
        evidence_from_month_change(
            bundle.source_module,
            bundle.metric_id,
            bundle.sensor,
            bundle.family,
            change,
        )
        for change in bundle.changes
    ]
    assert evaluate_rapid_changes(items) == ()


def test_multi_sensor_concordance_pattern():
    (month,) = _concordance_months(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ]
    )
    (pattern,) = evaluate_concordance_month(month)
    assert pattern.pattern_type == "MULTI_SENSOR_CONCORDANCE"
    assert pattern.status == "OBSERVED"
    assert pattern.window_start == "2024-01-01"
    assert pattern.window_end == "2024-01-31"
    assert pattern.contributing_sensors == ("S1", "S2")
    assert set(pattern.contributing_metric_ids) == {"ndvi", "vh"}
    assert "biological cause" in pattern.explanation


def test_divergent_sensor_pattern():
    (month,) = _concordance_months(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("radar", "vh", JAN, -19.0, "ABOVE_BASELINE"),
        ]
    )
    (pattern,) = evaluate_concordance_month(month)
    assert pattern.pattern_type == "DIVERGENT_SENSOR_EVIDENCE"
    assert pattern.status == "OBSERVED"


def test_insufficient_evidence_pattern():
    (month,) = _concordance_months(
        [
            ("optical", "ndvi", JAN, None, None),
            ("radar", "vh", JAN, None, None),
        ]
    )
    (pattern,) = evaluate_concordance_month(month)
    assert pattern.pattern_type == "INSUFFICIENT_EVIDENCE"
    assert pattern.status == "INSUFFICIENT_EVIDENCE"
    assert pattern.contributing_evidence_ids == ()


def test_single_sensor_month_yields_no_pattern():
    (month,) = _concordance_months(
        [("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE")]
    )
    assert evaluate_concordance_month(month) == ()


def test_sequential_change_pattern():
    bundle = _bundle("vv", [-12.0, -11.5, -11.0, -10.5])
    items = [
        evidence_from_month_change(
            bundle.source_module,
            bundle.metric_id,
            bundle.sensor,
            bundle.family,
            change,
        )
        for change in bundle.changes
    ]
    patterns = evaluate_sequential_changes(items)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_type == "SEQUENTIAL_CHANGE"
    assert pattern.window_start == "2024-02-01"
    assert pattern.window_end == "2024-04-30"
    assert len(pattern.contributing_evidence_ids) == 3
    assert "consecutive months" in pattern.explanation


def test_sequential_run_breaks_on_gap_and_reversal():
    bundle = _bundle("vv", [-12.0, -11.5, None, -11.0, -10.5, -11.5])
    items = [
        evidence_from_month_change(
            bundle.source_module,
            bundle.metric_id,
            bundle.sensor,
            bundle.family,
            change,
        )
        for change in bundle.changes
    ]
    patterns = evaluate_sequential_changes(items)
    # Gap month splits the series; the two-month rise after it
    # still forms exactly one run starting at the first post-gap rise.
    assert len(patterns) == 1
    assert patterns[0].window_start == "2024-04-01"


# ==========================================================================
# Windows, ordering, coexistence
# ==========================================================================


def test_exact_window_identity():
    bundle = _bundle("vv", [-12.0, -11.5, -11.0, -10.5])
    patterns = evaluate_all([bundle], [])
    sequential = next(
        p for p in patterns if p.pattern_type == "SEQUENTIAL_CHANGE"
    )
    assert (sequential.window_start, sequential.window_end) == (
        "2024-02-01",
        "2024-04-30",
    )


def test_multiple_patterns_coexist_for_one_window():
    bundle = _bundle(
        "vv", [-12.1, -11.9, -12.0, -12.1, -11.9, -12.0, -12.05, -9.0]
    )
    months = _concordance_months(
        [
            ("optical", "ndvi", ("2024-08-01", "2024-08-31"), 0.4, "BELOW_BASELINE"),
            ("radar", "vh", ("2024-08-01", "2024-08-31"), -19.5, "BELOW_BASELINE"),
        ]
    )
    patterns = evaluate_all([bundle], months)
    august = [p for p in patterns if p.window_start == "2024-08-01"]
    types = {p.pattern_type for p in august}
    assert "RAPID_CHANGE" in types
    assert "MULTI_SENSOR_CONCORDANCE" in types


def test_no_double_counting_of_sensor_family():
    months = _concordance_months(
        [
            ("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
            ("optical", "ndmi", JAN, 0.2, "BELOW_BASELINE"),
            ("optical", "ndre", JAN, 0.3, "BELOW_BASELINE"),
            ("optical", "msi", JAN, 1.2, "ABOVE_BASELINE"),
            ("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ]
    )
    (pattern,) = evaluate_concordance_month(months[0])
    assert pattern.contributing_sensors == ("S1", "S2")
    assert set(pattern.contributing_metric_ids) == {
        "ndvi",
        "ndmi",
        "ndre",
        "msi",
        "vh",
    }


def test_red_edge_remains_sentinel2_derived():
    from app.services.agriculture.red_edge import RedEdgeChange

    change = RedEdgeChange(
        diagnostic_id="re_slope_b5_b6",
        unit="reflectance/nm",
        window_start="2024-01-01",
        window_end="2024-01-31",
        previous_window_start="2023-12-01",
        previous_window_end="2023-12-31",
        value=0.002,
        previous_value=0.001,
        absolute_change=0.001,
        relative_change=1.0,
        days_elapsed=31,
        rate_per_day=0.001 / 31,
        direction="INCREASE",
    )
    item = evidence_from_red_edge_change("re_slope_b5_b6", change)
    assert item.sensor == "S2"
    assert item.family == "red_edge"
    assert item.change_direction == "INCREASE"


# ==========================================================================
# Preservation and quality
# ==========================================================================


def test_source_preservation_across_patterns():
    bundle = _bundle("vh", [-19.0, -18.5, -18.0, -17.5])
    patterns = evaluate_all([bundle], [])
    for pattern in patterns:
        assert pattern.contributing_metric_ids == ("vh",)
        assert pattern.contributing_sensors == ("S1",)
        assert pattern.rule_id.startswith("P31_")
        assert pattern.rule_version == "P31_V1"
        assert pattern.rule_description
        assert pattern.limitations
        for evidence_id, quality in pattern.quality_by_evidence.items():
            assert quality == "good"
        for evidence_id, coverage in pattern.coverage_by_evidence.items():
            assert coverage == pytest.approx(90.0)


def test_unavailable_quality_refuses_promotion():
    from app.services.agriculture.change_profile import MonthChange

    good_change = MonthChange(
        window_start="2024-01-01",
        window_end="2024-01-31",
        value=-11.0,
        previous_value=-12.0,
        absolute_change=1.0,
        relative_change=1.0 / 12.0,
        days_elapsed=31,
        rate_per_day=1.0 / 31,
        direction="INCREASE",
        rapid="RAPID_INCREASE",
        unit="dB",
        quality="unavailable",
    )
    item = evidence_from_month_change("radar_anomaly", "vv", "S1", "radar", good_change)
    assert evaluate_rapid_changes([item]) == ()


def test_missing_evidence_is_never_negative_evidence():
    bundle = _bundle("vv", [-12.0, None, -11.0])
    patterns = evaluate_all([bundle], [])
    assert all(p.status == "OBSERVED" for p in patterns)
    assert not any(
        p.pattern_type == "SEQUENTIAL_CHANGE" for p in patterns
    )


def test_adapters_preserve_source_information():
    from app.services.agriculture.concordance import make_evidence

    point = TemporalProfilePoint(
        window_start="2024-01-01",
        window_end="2024-01-31",
        value=0.5,
        unit="index",
        quality="good",
        coverage_percent=80.0,
        image_count=4,
    )
    item = evidence_from_anomaly_point(
        "baseline_anomaly",
        "ndvi",
        "S2",
        "optical",
        point,
        category="BELOW_BASELINE",
        provenance={"source_dataset_id": "COPERNICUS/S2_SR_HARMONIZED"},
    )
    assert item.anomaly_state == "BELOW_BASELINE"
    assert item.coverage_percent == pytest.approx(80.0)
    assert item.image_count == 4
    assert item.provenance["source_dataset_id"] == (
        "COPERNICUS/S2_SR_HARMONIZED"
    )
    concordance_item = make_evidence(
        "radar", "vh", JAN[0], JAN[1], -19.0, state_kind="change", state="DECREASE"
    )
    adapted = evidence_from_concordance_item(concordance_item)
    assert adapted.change_direction == "DECREASE"
    assert adapted.anomaly_state is None
    assert adapted.sensor == "S1"


# ==========================================================================
# Pydantic round-trip
# ==========================================================================


def test_pydantic_round_trip():
    from app.schemas.agriculture import EvidencePatternModel, PatternRuleModel

    bundle = _bundle("vv", [-12.0, -12.0, -12.0, -16.0, -16.0])
    patterns = evaluate_all([bundle], [])
    assert patterns
    model = EvidencePatternModel.model_validate(patterns[0].to_dict())
    assert model.pattern_type == "PERSISTENT_ANOMALY"
    assert model.status == "OBSERVED"
    assert model.contributing_metric_ids == ["vv"]
    dumped = model.model_dump()
    assert EvidencePatternModel.model_validate(dumped) == model
    rule = PatternRuleModel.model_validate(get_rule("P31_RAPID_CHANGE_V1").to_dict())
    assert rule.pattern_type == "RAPID_CHANGE"


# ==========================================================================
# Guards: no database, no cause attribution, no scores, no ML
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.pattern_engine as module

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
    code = _code_without_docstrings().lower().replace("_classify_month", "")
    for stem in (
        "pest",
        "disease",
        "pathogen",
        "infest",
        "defoliat",
        "vascular",
        "fungal",
        "chlorosis",
        "diagnosi",
        "diagnose",
        "severity",
        "stress",
        "damage",
        "health",
        "borer",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"
    assert set(PATTERN_TYPES) <= {
        "PERSISTENT_ANOMALY",
        "RAPID_CHANGE",
        "MULTI_SENSOR_CONCORDANCE",
        "DIVERGENT_SENSOR_EVIDENCE",
        "SEQUENTIAL_CHANGE",
        "INSUFFICIENT_EVIDENCE",
    }


def test_no_probability_risk_or_hidden_statistics():
    code = _code_without_docstrings()
    lowered = code.lower()
    for stem in (
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
        "np.mean",
        "np.std",
        "stdev",
    ):
        assert stem not in lowered, f"forbidden stem {stem!r} in code"
    import app.services.agriculture.pattern_engine as module

    names = " ".join(dir(module)).lower()
    assert "risk" not in names
    assert "probab" not in names


def test_no_interpolation_or_zero_fill_in_implementation():
    code = _code_without_docstrings().lower()
    assert "interpolat" not in code
    assert "fillna" not in code
    assert "resample" not in code
    import app.services.agriculture.pattern_engine as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for match in re.finditer(r"interpolat", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "never" in window or "no " in window


def test_module_registers_no_metrics_and_touches_no_cache_or_db():
    code = _code_without_docstrings()
    assert "register_metric" not in code
    assert "cache_service" not in code
