"""Tests for the P6.2 deterministic ground-truth validation engine.

Covers ingestion (valid/invalid/malformed records, sources,
deduplication, empty and multiple collections), linkage reuse
(metric, temporal, spatial), validation outcomes (matched,
mismatched, insufficient, unavailable, not validated,
one-to-many, semantic compatibility, nulls, unsupported
outputs, error isolation), provenance preservation, safety
guards, and serialization round-trips.

Pure unit tests over the real validation_engine module with
hand-supplied records only.  No Earth Engine calls, no
network, no database, no credentials required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from app.schemas.agriculture import (
    ReferenceCollectionModel,
    ValidationResultModel,
)
from app.services.agriculture.ground_truth import (
    STATUS_INSUFFICIENT_ANALYSIS,
    STATUS_INSUFFICIENT_REFERENCE,
    STATUS_MATCHED,
    STATUS_MISMATCHED,
    STATUS_NOT_VALIDATED,
    STATUS_UNAVAILABLE,
)
from app.services.agriculture.validation_engine import (
    NO_CANDIDATE_REFERENCE,
    SEMANTICALLY_INCOMPATIBLE,
    UNSUPPORTED_ANALYSIS_OUTPUT,
    NormalizedAnalysis,
    ReferenceCollection,
    ValidationReport,
    ValidationResult,
    assess_semantics,
    deduplicate,
    duplicate_key,
    from_cell_observation,
    from_scalar_evidence,
    from_temporal_point,
    ingest_reference_records,
    make_result,
    normalize_analysis,
    validate,
)
from app.services.agriculture.ground_truth import (
    GroundTruthObservation,
    link,
)

JAN = ("2024-01-01", "2024-01-31")


def _raw(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "observation_id": "obs-1",
        "variable": "observed_stress",
        "value": 2.0,
        "unit": "index",
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
        "limitations": ["single visit"],
    }
    base.update(overrides)
    return base


def _scalar(**overrides: Any) -> NormalizedAnalysis:
    item: Dict[str, Any] = {
        "metric_key": "ndvi",
        "value": 0.62,
        "unit": "index",
        "status": "observed",
        "temporal_start": "2024-01-01",
        "temporal_end": "2024-01-31",
        "source_dataset": "COPERNICUS/S2_SR_HARMONIZED",
        "quality": "good",
    }
    item.update(overrides)
    return from_scalar_evidence(item, domain="vegetation")


def _collection(*records: Dict[str, Any]) -> ReferenceCollection:
    return ingest_reference_records(list(records))


def _cell(**overrides: Any) -> NormalizedAnalysis:
    observation: Dict[str, Any] = {
        "cell_id": "r1c1",
        "metric_key": "ndvi",
        "window_start": "2024-01-01",
        "window_end": "2024-01-31",
        "value": 0.62,
        "unit": "index",
        "quality": "good",
    }
    observation.update(overrides)
    return from_cell_observation(observation)


# ---------------------------------------------------------------------------
# 1. Ingestion
# ---------------------------------------------------------------------------


class TestIngestion:
    def test_valid_observation_ingested(self):
        collection = _collection(_raw())
        assert len(collection.observations) == 1
        assert collection.rejected == ()
        assert collection.observations[0].observation_id == "obs-1"

    def test_invalid_observation_rejected_explicitly(self):
        collection = _collection(_raw(variable="canopy_health"))
        assert collection.observations == ()
        assert len(collection.rejected) == 1
        assert "unknown_variable" in collection.rejected[0].reasons

    def test_malformed_record_rejected_without_abort(self):
        collection = _collection(_raw(), "not-a-mapping", _raw(observation_id="obs-2"))
        assert [o.observation_id for o in collection.observations] == ["obs-1", "obs-2"]
        assert any(r.reasons == ("malformed_record",) for r in collection.rejected)

    def test_recognized_source_accepted(self):
        collection = _collection(_raw(source="agronomist_observation"))
        assert len(collection.observations) == 1

    def test_unknown_source_preserved_verbatim(self):
        collection = _collection(_raw(source="clipboard_note", observation_id="obs-9"))
        assert len(collection.observations) == 1
        assert collection.observations[0].source == "clipboard_note"
        report = validate([_scalar()], collection)
        assert report.results[0].provenance["reference_source"] == "clipboard_note"
        assert "source_vocabulary" in report.results[0].provenance

    def test_deterministic_duplicate(self):
        collection = _collection(_raw(), _raw(), _raw(observation_id="obs-2"))
        assert [o.observation_id for o in collection.observations] == ["obs-1", "obs-2"]
        assert len(collection.duplicates) == 1
        assert collection.duplicates[0].observation_id == "obs-1"
        assert collection.duplicates[0].kept_index == 0

    def test_distinct_observations_retained(self):
        first = _raw(observation_id="a", observed_on="2024-01-10")
        second = _raw(observation_id="b", observed_on="2024-01-20")
        collection = _collection(first, second)
        assert len(collection.observations) == 2
        assert collection.duplicates == ()
        assert duplicate_key(GroundTruthObservation.from_dict(first)) == "a"

    def test_empty_collection(self):
        collection = _collection()
        assert collection == ReferenceCollection.empty()
        report = validate([_scalar()], collection)
        assert len(report.results) == 1
        assert report.results[0].status == STATUS_NOT_VALIDATED

    def test_multiple_observations(self):
        collection = _collection(
            _raw(observation_id="o1"),
            _raw(observation_id="o2", metric_key="ndmi"),
            _raw(observation_id="o3", metric_key=None),
        )
        assert len(collection.observations) == 3
        assert len(collection.for_metric("ndvi")) == 1
        assert len(collection.for_cell("r1c1")) == 3


# ---------------------------------------------------------------------------
# 2. Linkage reuse
# ---------------------------------------------------------------------------


class TestLinkage:
    def test_exact_metric_links(self):
        report = validate([_scalar()], _collection(_raw()))
        assert report.results[0].metric_relationship == "METRIC_MATCH"

    def test_metric_mismatch(self):
        # A metric-mismatched reference is not a candidate, so the
        # engine books the analysis as not validated; the P6.1
        # linkage itself still reports the mismatch when reused.
        report = validate([_scalar()], _collection(_raw(metric_key="ndmi")))
        assert report.results[0].status == STATUS_NOT_VALIDATED
        assert report.results[0].temporal_relationship == NO_CANDIDATE_REFERENCE
        target = link(_scalar().to_mapping(),
                      GroundTruthObservation.from_dict(_raw(metric_key="ndmi")))
        assert target.status == STATUS_MISMATCHED
        assert target.relationship == "METRIC_MISMATCH"

    def test_exact_temporal(self):
        report = validate([_scalar()], _collection(_raw()))
        assert report.results[0].temporal_relationship == "EXACT_TEMPORAL_MATCH"

    def test_compatible_temporal(self):
        analysis = from_temporal_point(
            {"window_start": "2024-01-15", "window_end": "2024-02-15",
             "value": 0.6, "unit": "index"},
            metric_key="ndvi",
            domain="vegetation",
        )
        report = validate([analysis], _collection(_raw()))
        assert report.results[0].temporal_relationship == "COMPATIBLE_TEMPORAL_WINDOW"

    def test_incompatible_temporal(self):
        analysis = from_temporal_point(
            {"window_start": "2024-03-01", "window_end": "2024-03-31",
             "value": 0.6, "unit": "index"},
            metric_key="ndvi",
        )
        report = validate([analysis], _collection(_raw()))
        assert report.results[0].status == STATUS_MISMATCHED
        assert report.results[0].temporal_relationship == "INCOMPATIBLE_TEMPORAL_WINDOW"

    def test_exact_spatial_cell(self):
        observation = {
            "cell_id": "r1c1", "metric_key": "ndvi",
            "window_start": "2024-01-01", "window_end": "2024-01-31",
            "value": 0.5, "unit": "index", "quality": "good",
        }
        report = validate([from_cell_observation(observation)], _collection(_raw()))
        assert report.results[0].spatial_relationship == "EXACT_SPATIAL_CELL_MATCH"

    def test_spatial_mismatch(self):
        report = validate([_scalar()], _collection(_raw(cell_id="r9c9")))
        assert report.results[0].spatial_relationship == "SPATIAL_MISMATCH"

    def test_missing_spatial_linkage(self):
        ref = _raw(cell_id=None, latitude=None, longitude=None)
        report = validate([_scalar()], _collection(ref))
        assert report.results[0].status == STATUS_INSUFFICIENT_REFERENCE
        assert report.results[0].spatial_relationship == "MISSING_SPATIAL_LINKAGE"


# ---------------------------------------------------------------------------
# 3. Validation outcomes
# ---------------------------------------------------------------------------


class TestValidation:
    def test_matched_reference(self):
        report = validate([_cell()], _collection(_raw()))
        result = report.results[0]
        assert result.status == STATUS_MATCHED
        assert result.values_comparable is True
        assert result.analysis_value == 0.62
        assert result.reference_value == 2.0

    def test_mismatched_reference(self):
        report = validate([_cell()], _collection(_raw(cell_id="r9c9")))
        assert report.results[0].status == STATUS_MISMATCHED
        assert report.results[0].spatial_relationship == "SPATIAL_MISMATCH"

    def test_insufficient_reference(self):
        ref = _raw(cell_id=None, latitude=None, longitude=None)
        report = validate([_scalar()], _collection(ref))
        assert report.results[0].status == STATUS_INSUFFICIENT_REFERENCE

    def test_insufficient_analysis(self):
        analysis = from_scalar_evidence({
            "metric_key": "ndvi", "value": None, "unit": "index",
            "status": "observed", "temporal_start": "2024-01-01",
            "temporal_end": "2024-01-31",
        })
        report = validate([analysis], _collection(_raw()))
        assert report.results[0].status == STATUS_INSUFFICIENT_ANALYSIS

    def test_unavailable_analysis(self):
        analysis = from_scalar_evidence({
            "metric_key": "ndvi", "value": 0.6, "unit": "index",
            "status": "unavailable", "temporal_start": "2024-01-01",
            "temporal_end": "2024-01-31",
        })
        report = validate([analysis], _collection(_raw()))
        assert report.results[0].status == STATUS_UNAVAILABLE

    def test_not_validated_without_candidate(self):
        report = validate([_scalar()], _collection(_raw(metric_key="ndmi",
                                                        observation_id="o2")))
        assert len(report.results) == 1
        assert report.results[0].status == STATUS_NOT_VALIDATED
        assert report.results[0].temporal_relationship == NO_CANDIDATE_REFERENCE

    def test_multiple_compatible_references_stay_separate(self):
        collection = _collection(
            _raw(observation_id="o1"),
            _raw(observation_id="o2", source="farmer_observation"),
            _raw(observation_id="o3", source="clipboard_note"),
        )
        report = validate([_cell()], collection)
        assert len(report.results) == 3
        assert sorted(r.observation_id for r in report.results) == ["o1", "o2", "o3"]
        assert all(r.status == STATUS_MATCHED for r in report.results)

    def test_incompatible_variable_semantics(self):
        ref = _raw(variable="observed_pest_presence", state="present",
                   value=None, metric_key="ndvi", unit="index")
        report = validate([_cell()], _collection(ref))
        result = report.results[0]
        assert result.status == STATUS_INSUFFICIENT_REFERENCE
        assert SEMANTICALLY_INCOMPATIBLE in result.limitations

    def test_null_values_stay_null(self):
        ref = _raw(value=None, state="present")
        report = validate([_scalar()], _collection(ref))
        assert report.results[0].reference_value is None
        assert report.results[0].reference_state == "present"

    def test_state_compatibility(self):
        assert assess_semantics(
            _scalar(), GroundTruthObservation.from_dict(_raw())
        ).states_agree is False
        same = _raw(state="observed")
        analysis = from_scalar_evidence({
            "metric_key": "ndvi", "value": 0.6, "unit": "other-unit",
            "status": "observed",
        })
        assert assess_semantics(
            analysis, GroundTruthObservation.from_dict(same)
        ).states_agree is True

    def test_unsupported_output_isolated(self):
        bad = normalize_analysis(" award", {})
        good = _cell()
        report = validate([bad, good], _collection(_raw()))
        assert len(report.results) == 2
        weak = report.results_with_status(STATUS_INSUFFICIENT_ANALYSIS)
        assert len(weak) == 1
        assert "unsupported analysis output" in weak[0].limitations[0]
        assert report.results_with_status(STATUS_MATCHED)

    def test_error_isolation_for_malformed_references(self):
        collection = _collection(_raw(), {"observation_id": "broken"}, _raw(observation_id="o3"))
        assert len(collection.observations) == 2
        report = validate([_scalar()], collection)
        assert len(report.results) == 2


# ---------------------------------------------------------------------------
# 4. Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_reference_provenance_retained(self):
        report = validate([_scalar()], _collection(_raw()))
        prov = report.results[0].provenance
        assert prov["reference_source"] == "field_observation"
        assert prov["reference_method"] == "visual inspection"
        assert prov["reference_time"] == "2024-01-15"
        assert prov["reference_variable"] == "observed_stress"
        assert prov["plot"] == "A"

    def test_analysis_provenance_retained(self):
        report = validate([_scalar()], _collection(_raw()))
        prov = report.results[0].provenance
        assert prov["analysis_metric_key"] == "ndvi"
        assert prov["source_dataset"] == "COPERNICUS/S2_SR_HARMONIZED"

    def test_linkage_reason_retained(self):
        report = validate([_scalar()], _collection(_raw()), analysis_id="a-1")
        assert report.results[0].linkage_reason
        assert report.results[0].target_id in report.results[0].validation_id

    def test_limitations_retained(self):
        report = validate([_scalar()], _collection(_raw()))
        assert "single visit" in report.results[0].limitations


# ---------------------------------------------------------------------------
# 5. Safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_no_interpolation(self):
        analysis = from_temporal_point(
            {"window_start": "2024-02-01", "window_end": "2024-02-29",
             "value": 0.6, "unit": "index"},
            metric_key="ndvi",
        )
        report = validate([analysis], _collection(_raw()))
        assert report.results[0].temporal_relationship == "INCOMPATIBLE_TEMPORAL_WINDOW"

    def test_no_nearest_matching(self):
        near = _raw(observation_id="near", observed_on="2024-02-10",
                    window_start="2024-02-01", window_end="2024-02-29")
        report = validate([_scalar()], _collection(near))
        assert report.results[0].status == STATUS_MISMATCHED

    def test_no_zero_fill(self):
        analysis = from_scalar_evidence({"metric_key": "ndvi", "value": None})
        assert analysis.to_mapping()["value"] is None
        assert analysis.to_dict()["value"] is None

    def test_no_synthetic_observation(self):
        collection = _collection(_raw(), _raw())
        assert len(collection.observations) == 1
        assert collection.rejected == ()


MODULE_PATH = Path(__file__).resolve().parents[3] / "app" / "services" / "agriculture" / "validation_engine.py"


def _module_source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


class TestStaticSafeguards:
    def test_no_scoring_or_inference_machinery(self):
        source = _module_source()
        lowered = source.lower()
        for token in ("accuracy", "precision", "recall", "confusion",
                      "correlation", "confidence", "probability",
                      "roc", "auc", "severity"):
            assert re.search(rf"\b{token}\b", lowered) is None, token
        assert re.search(r"\bscore\b", lowered) is None
        assert re.search(r"\brank", lowered) is None
        for name in ("def detect", "def diagnos", "def predict",
                     "def classify", "def grade"):
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


# ---------------------------------------------------------------------------
# 6. Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_round_trips(self):
        report = validate([_scalar()], _collection(_raw()))
        result = report.results[0]
        assert ValidationResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
        collection = _collection(_raw())
        assert ReferenceCollection.from_dict(collection.to_dict()).to_dict() == (
            collection.to_dict()
        )
        analysis = _scalar()
        assert NormalizedAnalysis.from_dict(analysis.to_dict()).to_dict() == (
            analysis.to_dict()
        )
        assert ValidationReport.from_dict(report.to_dict()).to_dict() == report.to_dict()

    def test_schema_round_trip(self):
        report = validate([_cell()], _collection(_raw()))
        model = ValidationResultModel.model_validate(report.results[0].to_dict())
        assert model.status == STATUS_MATCHED
        assert model.values_comparable is True
        collection_model = ReferenceCollectionModel.model_validate(
            _collection(_raw(), _raw()).to_dict()
        )
        assert len(collection_model.observations) == 1
        assert len(collection_model.duplicates) == 1

    def test_deterministic_report(self):
        first = validate([_cell()], _collection(_raw()))
        second = validate([_cell()], _collection(_raw()))
        assert first.to_dict() == second.to_dict()
        assert first.results_for_metric("ndvi") == first.results
        assert first.results_with_status(STATUS_MATCHED) == first.results

    def test_make_result_reuses_linkage(self):
        analysis = _scalar()
        observation = GroundTruthObservation.from_dict(_raw())
        target = link(analysis.to_mapping(), observation, "a-1")
        result = make_result(analysis, observation, target, "a-1")
        assert result.target_id == target.target_id
        assert result.status == target.status
        assert result.linkage_reason == target.linkage_reason
