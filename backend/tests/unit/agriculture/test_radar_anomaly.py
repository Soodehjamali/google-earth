"""Tests for the P2.4 radar anomaly and change foundation.

Covers all four radar metrics, metric identity and units,
baseline statistics through the reused P1.2 machinery, neutral
anomaly categories, z-score signs, P1.3 change/rapid/persistence
semantics, gaps and missing months, window preservation,
provenance, determinism, and the terminology guards (no cause
attribution, no biological logic).

Analyses consume P2.3 RadarProfile objects built directly (P2.3
proves they come out of the production composite path); this
layer performs no Earth Engine calls itself.  No network and no
credentials are required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.services.agriculture.radar_anomaly import (
    SUPPORTED_RADAR_ANOMALY_METRICS,
    RadarMetricAnalysis,
    analyze_radar_metric,
    analyze_radar_set,
)
from app.services.agriculture.radar_profile import (
    RadarProfile,
    RadarProfilePoint,
)
from app.utils.dates import get_monthly_periods

UNITS = {"vv": "dB", "vh": "dB", "vh_vv": "dB", "rvi": "ratio"}
POLS = {
    "vv": ("VV",),
    "vh": ("VH",),
    "vh_vv": ("VV", "VH"),
    "rvi": ("VV", "VH"),
}
DATASET = "COPERNICUS/S1_GRD"


def make_profile(
    metric_key: str,
    values: List[Optional[float]],
    start: str = "2024-01-01",
    quality: str = "good",
) -> RadarProfile:
    windows = get_monthly_periods(start, "2030-01-01")[: len(values)]
    points = tuple(
        RadarProfilePoint(
            window_start=window_start,
            window_end=window_end,
            value=value,
            unit=UNITS[metric_key],
            quality=quality if value is not None else "insufficient",
            coverage_percent=90.0 if value is not None else None,
            image_count=3 if value is not None else None,
            provenance=(
                {
                    "source_dataset_id": DATASET,
                    "bands": list(POLS[metric_key]),
                    "quality_level": quality,
                }
                if value is not None
                else {}
            ),
        )
        for (window_start, window_end), value in zip(windows, values)
    )
    end = windows[-1][1] if windows else start
    return RadarProfile(
        metric_key=metric_key,
        dataset_id=DATASET,
        unit=UNITS[metric_key],
        polarizations=POLS[metric_key],
        mode="IW",
        orbit_pass="DESCENDING",
        scale_m=10,
        window_start=start,
        window_end=end,
        points=points,
    )


# ==========================================================================
# Metrics, identity, units
# ==========================================================================


def test_all_four_radar_metrics_supported():
    assert SUPPORTED_RADAR_ANOMALY_METRICS == ("vv", "vh", "vh_vv", "rvi")


@pytest.mark.parametrize("metric_key", ["vv", "vh", "vh_vv", "rvi"])
def test_each_metric_keeps_identity_and_unit(metric_key: str):
    base = {"vv": -12.0, "vh": -19.0, "vh_vv": -7.0, "rvi": 0.6}[metric_key]
    values = [base, base + 0.5, base - 0.5, base + 0.25]
    analysis = analyze_radar_metric(make_profile(metric_key, values))
    assert analysis.metric_key == metric_key
    assert analysis.unit == UNITS[metric_key]
    assert analysis.anomalies.unit == UNITS[metric_key]
    assert analysis.dataset_id == DATASET
    assert tuple(analysis.polarizations) == POLS[metric_key]


def test_unknown_metric_is_refused_without_substitution():
    profile = make_profile("vv", [-12.0, -11.0, -10.0])
    impostor = RadarProfile(
        metric_key="ndvi",
        dataset_id=profile.dataset_id,
        unit=profile.unit,
        polarizations=profile.polarizations,
        mode=profile.mode,
        orbit_pass=profile.orbit_pass,
        scale_m=profile.scale_m,
        window_start=profile.window_start,
        window_end=profile.window_end,
        points=profile.points,
    )
    with pytest.raises(ValueError, match="Supported radar metrics"):
        analyze_radar_metric(impostor)
    with pytest.raises(ValueError, match="Supported radar metrics"):
        analyze_radar_set([make_profile("vv", [-12.0, -11.0, -10.0]), impostor])


def test_no_metric_mixing_between_populations():
    vv = analyze_radar_metric(
        make_profile("vv", [-12.0, -11.0, -10.0, -11.5])
    )
    vh = analyze_radar_metric(
        make_profile("vh", [-20.0, -19.0, -18.0, -19.5])
    )
    assert vv.baseline is not None and vh.baseline is not None
    assert vv.baseline.mean == pytest.approx((-12.0 - 11.0 - 10.0 - 11.5) / 4)
    assert vh.baseline.mean == pytest.approx((-20.0 - 19.0 - 18.0 - 19.5) / 4)
    assert vv.baseline.mean != pytest.approx(vh.baseline.mean)


def test_set_analysis_preserves_order_and_independence():
    profiles = [
        make_profile("vv", [-12.0, -11.0, -10.0]),
        make_profile("rvi", [0.5, 0.6, 0.55]),
    ]
    analyses = analyze_radar_set(profiles)
    assert [a.metric_key for a in analyses] == ["vv", "rvi"]
    assert analyses[0].unit == "dB"
    assert analyses[1].unit == "ratio"


# ==========================================================================
# Baseline semantics (reused P1.2)
# ==========================================================================


def test_baseline_mean_min_max_median():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -10.0, -11.0, -11.5])
    )
    baseline = analysis.baseline
    assert baseline is not None
    assert baseline.mean == pytest.approx((-12.0 - 10.0 - 11.0 - 11.5) / 4)
    assert baseline.minimum == pytest.approx(-12.0)
    assert baseline.maximum == pytest.approx(-10.0)
    assert baseline.median == pytest.approx((-11.5 + -11.0) / 2)
    assert baseline.n_usable == 4
    assert baseline.n_observations == 4
    assert baseline.reference_start == "2024-01-01"
    assert baseline.strategy == "full_period"


def test_baseline_sample_standard_deviation():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -10.0, -11.0])
    )
    baseline = analysis.baseline
    assert baseline is not None
    # Sample spread (ddof=1): deviations -1, +1, 0 -> variance 1.0.
    assert baseline.std == pytest.approx(1.0)


def test_minimum_baseline_sample_behavior():
    two = analyze_radar_metric(make_profile("vh", [-19.0, -18.0]))
    assert two.baseline is None
    assert all(
        point.category == "INSUFFICIENT_BASELINE"
        for point in two.anomalies.points
    )
    assert all(point.z_score is None for point in two.anomalies.points)
    three = analyze_radar_metric(make_profile("vh", [-19.0, -18.0, -18.5]))
    assert three.baseline is not None
    assert three.baseline.n_usable == 3


def test_leave_one_out_percentile_exposure():
    # Nine usable months: each leave-one-out population holds eight
    # members, meeting the eight-sample percentile floor.
    values = [-14.0 + i * 0.5 for i in range(9)]
    analysis = analyze_radar_metric(make_profile("vv", values))
    scored = [p for p in analysis.anomalies.points if p.percentile is not None]
    assert len(scored) == 9
    ordered = sorted(scored, key=lambda p: p.value or 0.0)
    percentiles = [p.percentile for p in ordered]
    assert percentiles == sorted(percentiles)
    assert all(0.0 <= p <= 100.0 for p in percentiles if p is not None)
    few = analyze_radar_metric(make_profile("vv", [-12.0, -11.0, -10.0]))
    assert all(p.percentile is None for p in few.anomalies.points)


def test_zero_spread_baseline_refusal_inherited():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -12.0, -12.0, -12.0])
    )
    assert analysis.baseline is None
    assert all(
        point.category == "INSUFFICIENT_BASELINE"
        for point in analysis.anomalies.points
    )
    assert all(point.z_score is None for point in analysis.anomalies.points)
    # Observed values still pass through untouched, never zeroed.
    assert [p.value for p in analysis.anomalies.points] == [
        -12.0,
        -12.0,
        -12.0,
        -12.0,
    ]


# ==========================================================================
# Anomaly categories and z-signs (reused P1.2)
# ==========================================================================


def test_below_above_normal_classification():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -10.0, -11.0])
    )
    by_value = {p.value: p for p in analysis.anomalies.points}
    assert by_value[-12.0].category == "BELOW_BASELINE"
    assert by_value[-10.0].category == "ABOVE_BASELINE"
    assert by_value[-11.0].category == "NORMAL"


def test_z_score_sign_preserved():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -10.0, -11.0])
    )
    by_value = {p.value: p for p in analysis.anomalies.points}
    assert by_value[-12.0].z_score == pytest.approx(-1.0)
    assert by_value[-10.0].z_score == pytest.approx(1.0)
    assert by_value[-11.0].z_score == pytest.approx(0.0)


def test_insufficient_baseline_points_carry_no_score():
    analysis = analyze_radar_metric(make_profile("rvi", [0.6, 0.65]))
    assert analysis.baseline is None
    for point in analysis.anomalies.points:
        assert point.category == "INSUFFICIENT_BASELINE"
        assert point.z_score is None
        assert point.percentile is None


# ==========================================================================
# Change semantics (reused P1.3)
# ==========================================================================


def test_consecutive_change_values():
    analysis = analyze_radar_metric(make_profile("vv", [-12.0, -11.0, -10.5]))
    changes = analysis.changes
    assert len(changes) == 3
    assert changes[0].direction == "INSUFFICIENT"
    assert changes[0].absolute_change is None
    second = changes[1]
    assert second.previous_value == pytest.approx(-12.0)
    assert second.value == pytest.approx(-11.0)
    assert second.absolute_change == pytest.approx(1.0)
    assert second.relative_change == pytest.approx(1.0 / 12.0)
    assert second.days_elapsed == 31
    assert second.rate_per_day == pytest.approx(1.0 / 31)
    assert second.direction == "INCREASE"


def test_relative_change_none_on_zero_previous():
    analysis = analyze_radar_metric(make_profile("rvi", [0.0, 0.5, 0.5]))
    assert analysis.changes[1].relative_change is None
    assert analysis.changes[1].direction == "INCREASE"
    assert analysis.changes[2].direction == "STABLE"
    assert analysis.changes[2].absolute_change == pytest.approx(0.0)


def test_direction_vocabulary_is_p13_only():
    analysis = analyze_radar_metric(
        make_profile("vh", [-19.0, -20.0, -20.0, -18.0])
    )
    directions = [change.direction for change in analysis.changes]
    assert directions[1] == "DECREASE"
    assert directions[2] == "STABLE"
    assert directions[3] == "INCREASE"
    assert set(directions) <= {"INCREASE", "DECREASE", "STABLE", "INSUFFICIENT"}


def test_rapid_change_uses_baseline_spread():
    values = [-12.1, -11.9, -12.0, -12.1, -11.9, -12.0, -12.05, -9.0]
    analysis = analyze_radar_metric(make_profile("vv", values))
    assert analysis.baseline is not None
    rapids = [change.rapid for change in analysis.changes]
    assert rapids[-1] == "RAPID_INCREASE"
    assert "NOT_RAPID" in rapids[1:-1]


def test_rapid_insufficient_without_baseline():
    analysis = analyze_radar_metric(make_profile("vv", [-12.0, -9.0]))
    assert analysis.baseline is None
    assert all(change.rapid == "INSUFFICIENT" for change in analysis.changes)


def test_persistence_uses_existing_semantics():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -12.0, -12.0, -16.0, -16.0])
    )
    persistence = analysis.persistence
    assert persistence.longest_run_above == 3
    assert persistence.longest_run_below == 2
    assert persistence.n_anomalous == 5
    assert persistence.n_observed == 5
    assert persistence.n_missing == 0
    assert persistence.state == "PERSISTENT"


def test_gaps_break_persistence_runs():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -16.0, None, -16.0, -16.0])
    )
    persistence = analysis.persistence
    assert persistence.longest_run_below == 2
    assert persistence.n_missing == 1
    assert persistence.state == "NO_PERSISTENCE"


def test_persistence_insufficient_without_baseline():
    analysis = analyze_radar_metric(make_profile("vh", [-19.0, -18.0]))
    assert analysis.persistence.state == "INSUFFICIENT"
    assert analysis.persistence.n_observed == 2


# ==========================================================================
# Gaps, windows, no fabrication
# ==========================================================================


def test_missing_months_stay_missing_everywhere():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, None, -11.0])
    )
    assert analysis.anomalies.points[1].value is None
    assert analysis.anomalies.points[1].category == "INSUFFICIENT_BASELINE"
    assert analysis.anomalies.points[1].z_score is None
    assert analysis.changes[1].direction == "INSUFFICIENT"
    assert analysis.changes[1].value is None


def test_one_month_gap_bridging_follows_p13_allowance():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, None, -11.0, -10.5])
    )
    bridged = analysis.changes[2]
    assert bridged.previous_value == pytest.approx(-12.0)
    assert bridged.absolute_change == pytest.approx(1.0)


def test_two_month_gap_refuses_the_step():
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, None, None, -11.0])
    )
    assert analysis.baseline is None  # only two usable months
    last = analysis.changes[3]
    assert last.direction == "INSUFFICIENT"
    assert last.absolute_change is None
    assert last.previous_value is None


def test_exact_monthly_windows_preserved():
    analysis = analyze_radar_metric(
        make_profile("vh", [-19.0, -18.5, -18.0])
    )
    observed_starts = [
        point["window_start"] for point in analysis.to_dict()["observed"]["points"]
    ]
    assert observed_starts == ["2024-01-01", "2024-02-01", "2024-03-01"]
    assert [p.window_start for p in analysis.anomalies.points] == observed_starts
    assert [c.window_start for c in analysis.changes] == observed_starts


# ==========================================================================
# Provenance and units
# ==========================================================================


def test_provenance_sections_and_derivation_labels():
    analysis = analyze_radar_metric(
        make_profile("vh_vv", [-7.0, -6.5, -7.5, -6.8])
    )
    body = analysis.to_dict()
    assert body["metric_key"] == "vh_vv"
    assert body["dataset_id"] == DATASET
    assert body["unit"] == "dB"
    assert body["polarizations"] == ["VV", "VH"]
    assert body["mode"] == "IW"
    assert body["orbit_pass"] == "DESCENDING"
    assert body["scale_m"] == 10
    assert body["observed"]["derivation"] == "observed"
    assert body["baseline"] is not None
    assert body["baseline"]["derivation"] == "baseline-derived"
    assert body["baseline"]["n_usable"] == 4
    assert body["baseline"]["reference_start"] == "2024-01-01"
    assert "quality_counts" in body["baseline"]
    assert all(
        entry["derivation"] == "anomaly-derived" for entry in body["anomalies"]
    )
    assert all(
        entry["derivation"] == "change-derived" for entry in body["changes"]
    )
    first = body["anomalies"][0]
    assert first["quality"] == "good"
    assert first["coverage_percent"] == pytest.approx(90.0)
    assert first["image_count"] == 3
    assert first["radar_provenance"]["source_dataset_id"] == DATASET
    assert first["radar_provenance"]["bands"] == ["VV", "VH"]
    assert "P1.2" in body["methods"]["baseline"]
    assert "P1.3" in body["methods"]["change"]
    assert body["limitations"]


def test_unit_preserved_in_ratio_metric():
    analysis = analyze_radar_metric(make_profile("rvi", [0.5, 0.6, 0.55, 0.65]))
    assert analysis.unit == "ratio"
    assert all(p.unit == "ratio" for p in analysis.anomalies.points)
    assert all(c.unit == "ratio" for c in analysis.changes)


def test_deterministic_output():
    first = analyze_radar_metric(
        make_profile("vv", [-12.0, -11.0, -10.0, -11.5])
    ).to_dict()
    second = analyze_radar_metric(
        make_profile("vv", [-12.0, -11.0, -10.0, -11.5])
    ).to_dict()
    assert first == second


def test_usable_months_hook():
    analysis = analyze_radar_metric(make_profile("vv", [-12.0, None, -11.0]))
    from app.services.agriculture.radar_anomaly import usable_months

    assert usable_months(analysis) == [-12.0, -11.0]


# ==========================================================================
# Pydantic round-trip
# ==========================================================================


def test_pydantic_round_trip():
    from app.schemas.agriculture import RadarAnomalyAnalysisModel

    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -11.0, -10.0, -11.5])
    )
    model = RadarAnomalyAnalysisModel.model_validate(analysis.to_dict())
    assert model.metric_key == "vv"
    assert model.unit == "dB"
    assert model.polarizations == ["VV"]
    assert model.mode == "IW"
    assert model.orbit_pass == "DESCENDING"
    assert model.baseline is not None
    assert model.baseline.n_usable == 4
    assert len(model.anomalies) == 4
    assert len(model.changes) == 4
    assert model.anomalies[0].category == "BELOW_BASELINE"
    dumped = model.model_dump()
    assert RadarAnomalyAnalysisModel.model_validate(dumped) == model


# ==========================================================================
# Guards: no database, no cause attribution, no biological logic
# ==========================================================================


def _code_without_docstrings() -> str:
    import app.services.agriculture.radar_anomaly as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    stripped = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
    return stripped


def test_no_database_access():
    code = _code_without_docstrings()
    assert "app.db" not in code
    assert "sqlalchemy" not in code
    assert "alembic" not in code


def test_no_pest_disease_terminology():
    import app.services.agriculture.radar_anomaly as module

    code = _code_without_docstrings().lower()
    for stem in (
        "pest",
        "disease",
        "pathogen",
        "infest",
        "defoliat",
        "vascular",
        "fungal",
        "chlorosis",
        "diagnos",
        "severity",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"
    assert set(module.SUPPORTED_RADAR_ANOMALY_METRICS) == {
        "vv",
        "vh",
        "vh_vv",
        "rvi",
    }


def test_no_biological_classification_logic():
    code = _code_without_docstrings().lower()
    for stem in (
        "stress",
        "damage",
        "risk",
        "probab",
        "sklearn",
        "torch",
        "tensorflow",
        "predict",
        "threshold",
    ):
        assert stem not in code, f"forbidden stem {stem!r} in code"
    analysis = analyze_radar_metric(
        make_profile("vv", [-12.0, -10.0, -11.0, -16.0])
    )
    assert {
        point.category for point in analysis.anomalies.points
    } <= {"NORMAL", "BELOW_BASELINE", "ABOVE_BASELINE", "INSUFFICIENT_BASELINE"}
    assert {change.direction for change in analysis.changes} <= {
        "INCREASE",
        "DECREASE",
        "STABLE",
        "INSUFFICIENT",
    }
    assert analysis.persistence.state in {
        "PERSISTENT",
        "NO_PERSISTENCE",
        "INSUFFICIENT",
    }


def test_no_interpolation_or_zero_fill_in_implementation():
    code = _code_without_docstrings().lower()
    assert "interpolat" not in code
    assert "fillna" not in code
    assert "resample" not in code
    import app.services.agriculture.radar_anomaly as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    for match in re.finditer(r"interpolat", source):
        window = source[max(0, match.start() - 60): match.end() + 20]
        assert "never" in window or "no " in window


def test_module_registers_no_metrics_and_touches_no_cache_or_db():
    code = _code_without_docstrings()
    assert "register_metric" not in code
    assert "cache_service" not in code
