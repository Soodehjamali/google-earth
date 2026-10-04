"""Tests for the P2.5 multi-sensor concordance foundation.

Covers exact monthly alignment, the six concordance states,
sensor-family independence (same-family metrics and red-edge
never count as separate sensors), state-driven orientation
without raw-sign heuristics, missing months, temporal ordering
and runs, quality/coverage/provenance preservation, the
deterministic rule, unknown-source refusal, and the terminology
guards (no cause attribution, no scores, no ML).

Evidence items are built directly (earlier phases prove they
come out of the production paths); this layer performs no Earth
Engine calls itself.  No network and no credentials are required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

import pytest

from app.services.agriculture.concordance import (
    CONCORDANCE_RULE_ID,
    CONCORDANCE_STATES,
    EVIDENCE_FAMILIES,
    FAMILY_METRICS,
    FAMILY_RADAR,
    analyze_concordance,
    make_evidence,
    month_orientation,
)

JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")
MAR = ("2024-03-01", "2024-03-31")
APR = ("2024-04-01", "2024-04-30")


def ev(
    family: str,
    metric_id: str,
    window,
    value: Optional[float],
    state: Optional[str] = None,
    state_kind: str = "anomaly",
    quality: str = "good",
    unit: str = "",
    provenance: Optional[dict] = None,
):
    return make_evidence(
        family,
        metric_id,
        window[0],
        window[1],
        value,
        unit=unit,
        quality=quality,
        coverage_percent=90.0 if value is not None else None,
        image_count=3 if value is not None else None,
        state_kind=state_kind,
        state=state,
        provenance=provenance or {"source_dataset": metric_id},
    )


def states(series) -> List[str]:
    return [month.state for month in series.months]


# ==========================================================================
# Temporal alignment
# ==========================================================================


def test_exact_monthly_alignment_no_merging():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", ("2024-01-01", "2024-01-30"), -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert len(series.months) == 2
    assert series.months[0].window_end == "2024-01-30"
    assert series.months[1].window_end == "2024-01-31"


def test_matching_windows_align_across_families():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert len(series.months) == 1
    assert series.months[0].window_start == "2024-01-01"
    assert series.months[0].window_end == "2024-01-31"


def test_temporal_ordering_regardless_of_input_order():
    items = [
        ev("optical", "ndvi", MAR, 0.5, "BELOW_BASELINE"),
        ev("optical", "ndvi", JAN, 0.4, "BELOW_BASELINE"),
        ev("radar", "vh", FEB, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert [m.window_start for m in series.months] == [
        "2024-01-01",
        "2024-02-01",
        "2024-03-01",
    ]
    assert series.window_start == "2024-01-01"
    assert series.window_end == "2024-03-31"


# ==========================================================================
# Concordance states
# ==========================================================================


def test_optical_only_state():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("optical", "ndmi", JAN, 0.2, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["OPTICAL_ONLY"]


def test_radar_only_state():
    items = [
        ev("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["RADAR_ONLY"]


def test_both_usable_without_states_is_insufficient():
    items = [
        ev("optical", "ndvi", JAN, 0.5, None, state_kind="observation"),
        ev("radar", "vh", JAN, -19.0, None, state_kind="observation"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["INSUFFICIENT_EVIDENCE"]


def test_concordant_directional_evidence():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["MULTI_SENSOR_CONCORDANT"]


def test_concordant_change_directions():
    items = [
        ev("optical", "ndre", JAN, 0.3, "DECREASE", state_kind="change"),
        ev("radar", "vh_vv", JAN, -7.0, "DECREASE", state_kind="change"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["MULTI_SENSOR_CONCORDANT"]


def test_neutral_stability_is_concordant():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "NORMAL"),
        ev("radar", "vv", JAN, -12.0, "NORMAL"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["MULTI_SENSOR_CONCORDANT"]


def test_divergent_directional_evidence():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "ABOVE_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["DIVERGENT"]


def test_mixed_evidence_within_family_conflict():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ev("radar", "rvi", JAN, 0.7, "ABOVE_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["MIXED_EVIDENCE"]


def test_mixed_evidence_across_unclear_directions():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vv", JAN, -12.0, "NORMAL"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["MIXED_EVIDENCE"]


def test_insufficient_evidence_when_nothing_usable():
    items = [
        ev("optical", "ndvi", JAN, None, None),
        ev("radar", "vh", JAN, None, None),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["INSUFFICIENT_EVIDENCE"]
    assert series.months[0].families[0].usable_count == 0


def test_partially_missing_month_keeps_working_sensor():
    items = [
        ev("optical", "ndvi", JAN, None, None),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["RADAR_ONLY"]


# ==========================================================================
# Sensor independence
# ==========================================================================


def test_same_family_metrics_are_not_separate_sensors():
    items = [
        ev("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ev("radar", "vh_vv", JAN, -7.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["RADAR_ONLY"]


def test_optical_indices_are_not_separate_sensors():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("optical", "ndmi", JAN, 0.2, "BELOW_BASELINE"),
        ev("optical", "ndre", JAN, 0.3, "BELOW_BASELINE"),
        ev("optical", "msi", JAN, 1.2, "ABOVE_BASELINE"),
    ]
    series = analyze_concordance(items)
    # MSI ABOVE inverts to DOWN per documented polarity: the whole
    # optical family shares DOWN, yet remains one sensor alone.
    assert states(series) == ["OPTICAL_ONLY"]


def test_red_edge_is_not_an_independent_sensor():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev(
            "red_edge",
            "re_slope_b4_b5",
            JAN,
            0.002,
            "DECREASE",
            state_kind="change",
        ),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["OPTICAL_ONLY"]


def test_red_edge_contributes_to_sensor_concordance():
    items = [
        ev(
            "red_edge",
            "re_nd_b8a_b5",
            JAN,
            0.3,
            "DECREASE",
            state_kind="change",
        ),
        ev("radar", "vv", JAN, -12.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert states(series) == ["MULTI_SENSOR_CONCORDANT"]


# ==========================================================================
# Orientation semantics (no raw-sign heuristics)
# ==========================================================================


def test_orientation_follows_state_not_raw_value():
    item = ev("optical", "ndvi", JAN, 0.85, "BELOW_BASELINE")
    assert month_orientation(item) == "DOWN"
    item = ev("radar", "vh", JAN, -25.0, "ABOVE_BASELINE")
    assert month_orientation(item) == "UP"
    items = [
        ev("optical", "ndvi", JAN, 0.85, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -25.0, "BELOW_BASELINE"),
    ]
    assert states(analyze_concordance(items)) == ["MULTI_SENSOR_CONCORDANT"]


def test_msi_polarity_is_explicit_and_documented():
    assert month_orientation(ev("optical", "msi", JAN, 1.2, "INCREASE")) == "DOWN"
    assert month_orientation(ev("optical", "ndmi", JAN, 0.1, "DECREASE")) == "DOWN"
    items = [
        ev("optical", "msi", JAN, 1.2, "INCREASE"),
        ev("optical", "ndmi", JAN, 0.1, "DECREASE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    assert states(analyze_concordance(items)) == ["MULTI_SENSOR_CONCORDANT"]


def test_unknown_states_are_insufficient_not_guessed():
    assert month_orientation(ev("optical", "ndvi", JAN, 0.5, "WEIRD")) == (
        "INSUFFICIENT"
    )
    assert month_orientation(ev("optical", "ndvi", JAN, 0.5, None)) == (
        "INSUFFICIENT"
    )
    assert month_orientation(ev("optical", "ndvi", JAN, None, "BELOW_BASELINE")) == (
        "INSUFFICIENT"
    )


# ==========================================================================
# Runs and summary
# ==========================================================================


def test_temporal_summary_and_runs():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ev("optical", "ndvi", FEB, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", FEB, -19.0, "BELOW_BASELINE"),
        ev("optical", "ndvi", MAR, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", MAR, -19.0, "ABOVE_BASELINE"),
        ev("optical", "ndvi", APR, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", APR, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    summary = series.summary
    assert summary is not None
    assert summary.n_months == 4
    assert summary.n_concordant == 3
    assert summary.n_divergent == 1
    assert summary.concordant_months == ("2024-01-01", "2024-02-01", "2024-04-01")
    assert summary.divergent_months == ("2024-03-01",)
    assert summary.longest_concordant_run == 2
    assert summary.longest_concordant_run_start == "2024-01-01"
    assert summary.longest_concordant_run_end == "2024-02-29"
    assert summary.longest_divergent_run == 1


def test_absent_months_break_runs():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ev("optical", "ndvi", FEB, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", FEB, -19.0, "BELOW_BASELINE"),
        ev("optical", "ndvi", APR, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", APR, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    assert series.summary is not None
    assert series.summary.longest_concordant_run == 2
    assert series.summary.n_months == 3


# ==========================================================================
# Quality, coverage, provenance, rule traceability
# ==========================================================================


def test_source_quality_coverage_provenance_preserved():
    items = [
        ev(
            "optical",
            "ndvi",
            JAN,
            0.5,
            "BELOW_BASELINE",
            quality="moderate",
            provenance={"source_dataset_id": "COPERNICUS/S2_SR_HARMONIZED"},
        ),
        ev(
            "radar",
            "vh",
            JAN,
            -19.0,
            "BELOW_BASELINE",
            quality="good",
            provenance={"source_dataset_id": "COPERNICUS/S1_GRD"},
        ),
    ]
    series = analyze_concordance(items)
    body = series.to_dict()
    month = body["months"][0]
    optical = next(f for f in month["families"] if f["family"] == "optical")
    radar = next(f for f in month["families"] if f["family"] == "radar")
    assert optical["items"][0]["quality"] == "moderate"
    assert optical["items"][0]["coverage_percent"] == pytest.approx(90.0)
    assert optical["items"][0]["image_count"] == 3
    assert optical["items"][0]["provenance"] == {
        "source_dataset_id": "COPERNICUS/S2_SR_HARMONIZED"
    }
    assert radar["items"][0]["provenance"]["source_dataset_id"] == (
        "COPERNICUS/S1_GRD"
    )


def test_deterministic_rule_and_reasons():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    month = series.months[0]
    assert month.rule_id == CONCORDANCE_RULE_ID == "P25_CONCORDANCE_V1"
    assert month.reasons
    joined = " ".join(month.reasons)
    assert "ndvi" in joined and "vh" in joined
    assert "MULTI_SENSOR_CONCORDANT" in joined or "share" in joined
    body = series.to_dict()
    assert body["rule_id"] == CONCORDANCE_RULE_ID
    assert body["rule"]
    assert body["methods"]["concordance"]
    assert body["limitations"]
    again = analyze_concordance(list(reversed(items))).to_dict()
    assert again == body


def test_exact_contributing_metric_lists():
    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("optical", "ndmi", JAN, None, None),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    families = {f.family: f for f in series.months[0].families}
    assert families["optical"].metric_ids == ("ndvi",)
    assert families["optical"].usable_count == 2
    assert families["radar"].metric_ids == ("vh",)


def test_unknown_metric_and_family_refusal():
    with pytest.raises(ValueError, match="not registered for family"):
        make_evidence("optical", "vv", JAN[0], JAN[1], 0.5)
    with pytest.raises(ValueError, match="not registered for family"):
        make_evidence("radar", "ndvi", JAN[0], JAN[1], -12.0)
    with pytest.raises(ValueError, match="Unknown evidence family"):
        make_evidence("thermal", "lst", JAN[0], JAN[1], 300.0)
    with pytest.raises(ValueError, match="Unknown state kind"):
        make_evidence("optical", "ndvi", JAN[0], JAN[1], 0.5, state_kind="risk")


# ==========================================================================
# Pydantic round-trip
# ==========================================================================


def test_pydantic_round_trip():
    from app.schemas.agriculture import ConcordanceSeriesModel

    items = [
        ev("optical", "ndvi", JAN, 0.5, "BELOW_BASELINE"),
        ev("radar", "vh", JAN, -19.0, "BELOW_BASELINE"),
        ev("optical", "ndvi", FEB, 0.5, "BELOW_BASELINE"),
    ]
    series = analyze_concordance(items)
    model = ConcordanceSeriesModel.model_validate(series.to_dict())
    assert model.rule_id == CONCORDANCE_RULE_ID
    assert len(model.months) == 2
    assert model.months[0].state == "MULTI_SENSOR_CONCORDANT"
    assert model.months[1].state == "OPTICAL_ONLY"
    assert model.months[0].families[0].orientation == "DOWN"
    assert model.summary is not None
    assert model.summary.n_concordant == 1
    dumped = model.model_dump()
    assert ConcordanceSeriesModel.model_validate(dumped) == model


# ==========================================================================
# Guards: no database, no cause attribution, no scores, no ML
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.concordance as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def _code_without_user_text() -> str:
    """Stripped code minus the user-facing methods/limitations blocks.

    Those blocks are required scientific documentation (they state
    what concordance is not); everything else must carry no
    loaded terminology.
    """
    code = _code_without_docstrings()
    code = re.sub(
        r"_SERIES_METHODS.*?\n\}",
        "",
        code,
        flags=re.DOTALL,
    )
    code = re.sub(
        r"_SERIES_LIMITATIONS.*?\n\)",
        "",
        code,
        flags=re.DOTALL,
    )
    return code


def test_required_scientific_statements_are_documented():
    import app.services.agriculture.concordance as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    assert "cannot by itself" in source and "pest" in source
    assert "ground truth" in source or "ground-truth" in source
    assert "evidence aggregation, not biological" in source
    assert "derived sentinel-2 evidence" in source


def test_no_database_access():
    code = _code_without_docstrings()
    assert "app.db" not in code
    assert "sqlalchemy" not in code
    assert "alembic" not in code


def test_concordance_states_are_neutral():
    assert set(CONCORDANCE_STATES) == {
        "MULTI_SENSOR_CONCORDANT",
        "OPTICAL_ONLY",
        "RADAR_ONLY",
        "DIVERGENT",
        "MIXED_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
    }
    assert set(EVIDENCE_FAMILIES) == {"optical", "red_edge", "radar"}


def test_no_pest_disease_terminology():
    code = _code_without_user_text().lower().replace("_classify_month", "")
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
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"


def test_no_probability_risk_ml_or_correlation():
    code = _code_without_docstrings().lower()
    for stem in (
        "probab",
        "risk",
        "sklearn",
        "torch",
        "tensorflow",
        "predict",
        "neural",
        "classifier",
        "correlat",
        "regress",
        "threshold",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"
    import app.services.agriculture.concordance as module

    names = " ".join(dir(module)).lower()
    assert "risk" not in names
    assert "probab" not in names


def test_no_interpolation_or_zero_fill_in_implementation():
    code = _code_without_user_text().lower()
    assert "interpolat" not in code
    assert "fillna" not in code
    assert "resample" not in code
    import app.services.agriculture.concordance as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for match in re.finditer(r"interpolat", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "never" in window or "no " in window


def test_module_registers_no_metrics_and_touches_no_cache_or_db():
    code = _code_without_docstrings()
    assert "register_metric" not in code
    assert "cache_service" not in code


def test_family_registries_cover_required_metrics():
    assert set(FAMILY_METRICS["optical"]) == {"ndvi", "ndmi", "ndre", "msi"}
    assert set(FAMILY_METRICS["radar"]) == {"vv", "vh", "vh_vv", "rvi"}
    assert "re_slope_b4_b5" in FAMILY_METRICS["red_edge"]
    assert "re_nd_b8a_b5" in FAMILY_METRICS["red_edge"]
