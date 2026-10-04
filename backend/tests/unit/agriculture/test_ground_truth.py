"""Tests for the P6.1 ground-truth validation contract and foundation.

Covers reference-observation validity, temporal/spatial/metric
matching with no interpolation or fabrication, deterministic
linkage states, provenance preservation, additive schema
round-trips, and the wording guards (no grading, no biological
inference from remote sensing, no causal language in linkage
reasons).

Pure unit tests over the real ground_truth module.  No Earth
Engine calls, no network, no database, no credentials required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from app.schemas.agriculture import (
    GroundTruthObservationModel,
    ValidationTargetModel,
)
from app.services.agriculture.ground_truth import (
    KNOWN_SOURCES,
    REFERENCE_VARIABLES,
    STATUS_INSUFFICIENT_ANALYSIS,
    STATUS_INSUFFICIENT_REFERENCE,
    STATUS_MATCHED,
    STATUS_MISMATCHED,
    STATUS_NOT_VALIDATED,
    STATUS_UNAVAILABLE,
    GroundTruthObservation,
    ValidationTarget,
    build_target_id,
    declare_not_validated,
    link,
    link_all,
    match_metric,
    match_spatial,
    match_temporal,
    reference_window,
    sort_targets,
    source_is_recognized,
)

JAN = ("2024-01-01", "2024-01-31")
FEB = ("2024-02-01", "2024-02-29")


def _observation(**overrides: Any) -> GroundTruthObservation:
    base: Dict[str, Any] = {
        "observation_id": "obs-1",
        "variable": "observed_stress",
        "value": 2.0,
        "unit": "class",
        "state": "present",
        "latitude": 32.42,
        "longitude": 53.68,
        "observed_on": "2024-01-15",
        "window_start": "2024-01-01",
        "window_end": "2024-01-31",
        "source": "field_observation",
        "method": "visual inspection",
        "quality": "good",
        "status": "available",
        "metric_key": "ndvi",
        "domain": "vegetation",
        "cell_id": "r1c1",
        "provenance": {"plot": "A"},
        "limitations": ("single visit",),
    }
    base.update(overrides)
    return GroundTruthObservation(**base)


def _analysis(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "metric_key": "ndvi",
        "domain": "vegetation",
        "window_start": "2024-01-01",
        "window_end": "2024-01-31",
        "cell_id": "r1c1",
        "value": 0.62,
        "unit": "index",
        "status": "observed",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Observation validity
# ---------------------------------------------------------------------------


class TestObservationValidity:
    def test_valid_observation_is_usable(self):
        obs = _observation()
        assert obs.refusal_reasons() == ()
        assert obs.is_usable
        # Quality travels verbatim; nothing upgrades a supplied record.
        assert _observation(quality="uncertain").to_dict()["quality"] == "uncertain"

    def test_missing_value_with_present_state_is_usable(self):
        obs = _observation(value=None, state="absent")
        assert obs.refusal_reasons() == ()
        assert obs.is_usable

    def test_missing_value_and_state_is_refused(self):
        obs = _observation(value=None, state=None)
        assert "missing_value_and_state" in obs.refusal_reasons()
        assert not obs.is_usable

    def test_non_finite_value_is_refused(self):
        assert "non_finite_value" in _observation(value=float("nan")).refusal_reasons()

    def test_missing_and_partial_location(self):
        assert not _observation(latitude=None, longitude=None).has_location()
        assert not _observation(latitude=None).has_location()
        assert not _observation(longitude=None).has_location()
        missing = _observation(latitude=None, longitude=None)
        assert missing.refusal_reasons() == ()
        assert missing.is_usable
        assert _observation().has_location()

    def test_missing_and_invalid_time(self):
        assert "missing_observation_time" in (
            _observation(observed_on=None).refusal_reasons()
        )
        assert "invalid_observation_time" in (
            _observation(observed_on="15-01-2024").refusal_reasons()
        )

    def test_unknown_variable_is_refused(self):
        assert "unknown_variable" in _observation(variable="canopy_health").refusal_reasons()

    def test_unknown_state_string_is_refused(self):
        assert "unknown_state" in _observation(state="severe").refusal_reasons()

    def test_missing_source_method_and_unavailable_status(self):
        reasons = _observation(source="", method="").refusal_reasons()
        assert "missing_source" in reasons
        assert "missing_method" in reasons
        assert not _observation(status="unavailable").is_usable


# ---------------------------------------------------------------------------
# 2. Temporal matching
# ---------------------------------------------------------------------------


class TestTemporalMatching:
    def test_exact_temporal_match(self):
        assert match_temporal(*JAN, *JAN) == "EXACT_TEMPORAL_MATCH"

    def test_compatible_temporal_overlap(self):
        assert (
            match_temporal("2024-01-01", "2024-01-31", "2024-01-15", "2024-02-15")
            == "COMPATIBLE_TEMPORAL_WINDOW"
        )

    def test_incompatible_temporal_disjoint(self):
        assert match_temporal(*JAN, *FEB) == "INCOMPATIBLE_TEMPORAL_WINDOW"

    def test_missing_window_is_incompatible_not_fabricated(self):
        assert match_temporal("2024-01-01", "2024-01-31", None, None) == (
            "INCOMPATIBLE_TEMPORAL_WINDOW"
        )
        assert match_temporal(None, None, *JAN) == "INCOMPATIBLE_TEMPORAL_WINDOW"

    def test_adjacent_and_inverted_windows_do_not_bridge(self):
        assert (
            match_temporal("2024-01-01", "2024-01-31", "2024-02-01", "2024-02-29")
            == "INCOMPATIBLE_TEMPORAL_WINDOW"
        )
        assert (
            match_temporal("2024-01-31", "2024-01-01", *JAN)
            == "INCOMPATIBLE_TEMPORAL_WINDOW"
        )

    def test_reference_window_rule(self):
        assert reference_window(_observation()) == JAN
        day_only = _observation(window_start=None, window_end=None)
        assert reference_window(day_only) == ("2024-01-15", "2024-01-15")


# ---------------------------------------------------------------------------
# 3. Spatial and metric matching
# ---------------------------------------------------------------------------


class TestSpatialAndMetricMatching:
    def test_exact_spatial_cell_match(self):
        assert match_spatial("r1c1", "r1c1", True) == "EXACT_SPATIAL_CELL_MATCH"

    def test_spatial_mismatch(self):
        assert match_spatial("r1c1", "r1c2", True) == "SPATIAL_MISMATCH"

    def test_missing_spatial_linkage(self):
        assert match_spatial("r1c1", None, False) == "MISSING_SPATIAL_LINKAGE"

    def test_coordinates_never_stand_in_for_a_cell(self):
        assert match_spatial("r1c1", None, True) == "SPATIAL_MISMATCH"

    def test_metric_identity(self):
        assert match_metric("ndvi", "ndmi") == "METRIC_MISMATCH"
        assert match_metric("ndvi", "ndvi") == "METRIC_MATCH"
        # A reference that declares no metric linkage makes no metric claim.
        assert match_metric("ndvi", None) == "METRIC_MATCH"


# ---------------------------------------------------------------------------
# 4. Linkage
# ---------------------------------------------------------------------------


class TestLinkage:
    def test_full_match_links_reference(self):
        target = link(_analysis(), _observation())
        assert target.status == STATUS_MATCHED
        assert target.relationship == "EXACT_TEMPORAL_MATCH"
        assert target.observation_id == "obs-1"

    def test_compatible_window_links_as_compatible_without_causal_verbs(self):
        target = link(_analysis(), _observation(observed_on="2024-01-20",
                                                window_start=None, window_end=None))
        assert target.status == STATUS_MATCHED
        assert target.relationship == "COMPATIBLE_TEMPORAL_WINDOW"
        text = target.linkage_reason.lower()
        for verb in ("cause", "due to", "indicates", "proves", "confirms"):
            assert verb not in text

    def test_incompatible_temporal_mismatches(self):
        target = link(_analysis(), _observation(window_start="2024-03-01",
                                                window_end="2024-03-31",
                                                observed_on="2024-03-15"))
        assert target.status == STATUS_MISMATCHED
        assert target.relationship == "INCOMPATIBLE_TEMPORAL_WINDOW"

    def test_metric_mismatch_takes_priority(self):
        target = link(_analysis(), _observation(metric_key="ndmi"))
        assert target.status == STATUS_MISMATCHED
        assert target.relationship == "METRIC_MISMATCH"

    def test_insufficient_reference_for_unusable_record(self):
        target = link(_analysis(), _observation(variable="canopy_health"))
        assert target.status == STATUS_INSUFFICIENT_REFERENCE

    def test_unavailable_and_missing_analysis_values(self):
        assert link(
            _analysis(status="unavailable", value=None), _observation()
        ).status == STATUS_UNAVAILABLE
        assert link(
            _analysis(value=None), _observation()
        ).status == STATUS_INSUFFICIENT_ANALYSIS

    def test_analysis_side_missing_cell_is_insufficient_analysis(self):
        analysis = _analysis()
        del analysis["cell_id"]
        target = link(analysis, _observation())
        assert target.status == STATUS_INSUFFICIENT_ANALYSIS
        assert target.relationship == "MISSING_SPATIAL_LINKAGE"

    def test_not_validated_default_and_deterministic_linkage(self):
        assert declare_not_validated("t-1").status == STATUS_NOT_VALIDATED
        assert declare_not_validated("t-1").relationship == "NOT_EVALUATED"
        pairs = [
            (_analysis(metric_key="ndmi"), _observation(observation_id="o2",
                                                       variable="observed_damage",
                                                       metric_key="ndmi")),
            (_analysis(), _observation()),
        ]
        first = link_all(pairs)
        assert [t.target_id for t in first] == (
            [t.target_id for t in link_all(list(reversed(pairs)))]
        )
        assert sort_targets(first) == first
        assert link(_analysis(), _observation()).to_dict() == (
            link(_analysis(), _observation()).to_dict()
        )


# ---------------------------------------------------------------------------
# 5. Provenance and serialization
# ---------------------------------------------------------------------------


class TestProvenanceAndSerialization:
    def test_provenance_preservation(self):
        target = link(_analysis(), _observation(), analysis_id="a-1")
        prov = target.provenance
        assert prov["reference_source"] == "field_observation"
        assert prov["reference_method"] == "visual inspection"
        assert prov["reference_time"] == "2024-01-15"
        assert prov["reference_variable"] == "observed_stress"
        assert prov["reference_quality"] == "good"
        assert prov["plot"] == "A"
        assert "single visit" in target.limitations

    def test_no_zero_fill_and_stable_round_trips(self):
        obs = _observation(value=None, state="present")
        assert obs.to_dict()["value"] is None
        assert GroundTruthObservation.from_dict(obs.to_dict()).value is None
        assert GroundTruthObservation.from_dict(_observation().to_dict()).to_dict() == (
            _observation().to_dict()
        )
        target = link(_analysis(), _observation())
        assert ValidationTarget.from_dict(target.to_dict()).to_dict() == target.to_dict()

    def test_target_identity_and_verbatim_foreign_source(self):
        assert build_target_id("ndvi", *JAN, "r1c1", "obs-1") == (
            "ndvi:2024-01-01:2024-01-31:r1c1:obs-1"
        )
        assert not source_is_recognized("clipboard_note")
        assert all(source_is_recognized(s) for s in KNOWN_SOURCES)
        target = link(_analysis(), _observation(source="clipboard_note"))
        assert target.provenance["reference_source"] == "clipboard_note"
        assert "source_vocabulary" in target.provenance
        assert target.status == STATUS_MATCHED

    def test_schema_models_and_reference_vocabulary(self):
        obs_model = GroundTruthObservationModel.model_validate(_observation().to_dict())
        assert obs_model.observation_id == "obs-1"
        assert obs_model.variable == "observed_stress"
        target_model = ValidationTargetModel.model_validate(
            link(_analysis(), _observation()).to_dict()
        )
        assert target_model.status == STATUS_MATCHED
        # Biological labels exist only as externally supplied reference vocabulary.
        for variable in (
            "observed_disease",
            "observed_pest_presence",
            "observed_pest_absence",
            "observed_management_event",
            "unknown",
            "not_assessed",
        ):
            assert variable in REFERENCE_VARIABLES
            assert _observation(variable=variable).is_usable


# ---------------------------------------------------------------------------
# 6. Static safeguards
# ---------------------------------------------------------------------------


MODULE_PATH = Path(__file__).resolve().parents[3] / "app" / "services" / "agriculture" / "ground_truth.py"


def _module_source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


class TestStaticSafeguards:
    def test_no_grading_or_inference_machinery(self):
        source = _module_source()
        lowered = source.lower()
        for token in ("accuracy", "precision", "recall", "confusion",
                      "correlation", "roc", "auc"):
            assert re.search(rf"\b{token}\b", lowered) is None, token
        for name in ("def detect", "def diagnos", "def predict",
                     "def classify", "def score", "def rank", "def grade"):
            assert name not in source, name

    def test_no_remote_sensing_to_biology_mapping(self):
        source = _module_source()
        for metric in ("ndvi", "ndmi", "ndre", "msi", "vv", "vh", "rvi",
                       "lst", "thermal"):
            for label in ("pest", "disease"):
                pattern = re.compile(
                    rf"{metric}[^\n]{{0,80}}{label}|{label}[^\n]{{0,80}}{metric}"
                )
                assert pattern.search(source) is None, (metric, label)

    def test_no_external_calls(self):
        source = _module_source()
        assert "earthengine" not in source.lower()
        assert "ee." not in source
        assert "import requests" not in source
        assert "sqlite" not in source.lower()
