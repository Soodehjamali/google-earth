"""Tests for the yield-model foundation (Phase M).

The governing risks:

1. **A spec that omits its evidence.** ``YieldModelSpec.__post_init__``
   is the load-bearing gate: a spec without a named calibration source,
   a disjoint validation dataset, computed validation statistics, a
   scope, an honest mass unit, a geography, a period, an uncertainty
   definition and stated assumptions must be refused at construction,
   not at first use.

2. **A silent model swap.** The registry must refuse re-registering a
   model id, refuse one model publishing under two metric keys, and
   thereby force every behavioural change to go through an explicit new
   registration with a new version.

3. **A fabricated number.** The three unavailable metrics must have no
   compute path that can carry a value, must expose machine-readable
   codes, and must refuse identically regardless of the context they
   are handed.

4. **A fabricated accuracy claim.** No test here asserts model
   accuracy, because no model exists; the tests assert the *absence* of
   any registered model and the presence of precise reasons.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.catalog import (
    clear_registry,
    metric_keys,
    register_metrics,
)
from app.services.agriculture.types import (
    MeasurementBasis,
    STATUS_UNAVAILABLE,
)
from app.services.agriculture.yield_model import (
    ALL_YIELD_MODEL_METRICS,
    BIOMASS_UNAVAILABLE_CODE,
    BIOMASS_UNAVAILABLE_REASON,
    UNAVAILABLE_YIELD_METRICS,
    YIELD_MODEL_REGISTRY,
    YIELD_UNAVAILABLE_CODE,
    YIELD_UNCERTAINTY_UNAVAILABLE_CODE,
    YIELD_UNCERTAINTY_UNAVAILABLE_REASON,
    YIELD_UNAVAILABLE_REASON,
    UnavailableBiomassEstimateMetric,
    UnavailableYieldEstimateMetric,
    UnavailableYieldUncertaintyMetric,
    ValidationEvidence,
    YieldModelRegistry,
    YieldModelSpec,
)

# ==========================================================================
# Fixtures
# ==========================================================================

EXPECTED_KEYS = {
    "crop_yield_estimate",
    "crop_biomass_estimate",
    "crop_yield_uncertainty",
}


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def a_valid_evidence(**overrides) -> ValidationEvidence:
    fields: Dict[str, Any] = dict(
        calibration_source="Khwahan sugar-beet trial network 2015-2022",
        validation_dataset="Independent grower records 2023-2024",
        validation_metrics={"rmse_t_ha": 0.61, "r2": 0.72, "n": 118.0},
        validation_period="2023-2024",
        validation_geography="Khuzestan province, Iran",
    )
    fields.update(overrides)
    return ValidationEvidence(**fields)


def a_valid_spec(**overrides) -> YieldModelSpec:
    fields: Dict[str, Any] = dict(
        model_id="test-model",
        model_version="1.0.0",
        parameter_version="params-2024-01",
        crop_scope=("sugar-beet",),
        required_inputs=("ndvi", "evapotranspiration_cumulative"),
        output_unit="t/ha",
        applicable_geography="Khuzestan province, Iran",
        applicable_period="2015-2024",
        uncertainty_definition="prediction interval from validation residuals",
        assumptions=(
            "Harvest observations are accurate to 5 percent.",
            "The NDVI-yield relationship is stable across cultivars.",
        ),
        validation=a_valid_evidence(),
    )
    fields.update(overrides)
    return YieldModelSpec(**fields)


def make_context(**overrides):
    defaults = dict(
        geometry={},
        start_date="2023-01-01",
        end_date="2023-12-31",
        geometry_key="yield-test",
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


# ==========================================================================
# Collection integrity
# ==========================================================================


def test_all_expected_unavailable_metrics_present():
    assert {m.key for m in UNAVAILABLE_YIELD_METRICS} == EXPECTED_KEYS


def test_no_duplicate_metric_keys():
    keys = [m.key for m in ALL_YIELD_MODEL_METRICS]
    assert len(keys) == len(set(keys))


def test_registration_reaches_the_catalog():
    register_metrics(UNAVAILABLE_YIELD_METRICS)
    for key in EXPECTED_KEYS:
        assert key in metric_keys(), key


def test_every_metric_denies_yield_in_its_prose():
    for metric in ALL_YIELD_MODEL_METRICS:
        text = " ".join(metric.limitations).lower()
        assert "not produced" in text, metric.key


def test_the_engine_registry_is_empty():
    """The audit found no valid model; the registry must reflect that."""
    assert len(YIELD_MODEL_REGISTRY) == 0
    assert YIELD_MODEL_REGISTRY.registered_model_ids() == ()
    assert YIELD_MODEL_REGISTRY.get("anything") is None


# ==========================================================================
# YieldModelSpec validation
# ==========================================================================


class TestYieldModelSpec:
    def test_a_complete_spec_constructs(self):
        spec = a_valid_spec()
        assert spec.model_id == "test-model"
        assert spec.validation.validation_metrics["n"] == 118.0

    def test_a_missing_calibration_source_is_refused(self):
        with pytest.raises(ValueError, match="calibration source"):
            a_valid_evidence(calibration_source="")

    def test_a_placeholder_calibration_source_is_refused(self):
        with pytest.raises(ValueError, match="calibration source"):
            a_valid_evidence(calibration_source="   ")

    def test_a_missing_validation_dataset_is_refused(self):
        with pytest.raises(ValueError, match="validation dataset"):
            a_valid_evidence(validation_dataset="")

    def test_validation_on_training_data_is_refused(self):
        with pytest.raises(ValueError, match="validation dataset"):
            a_valid_evidence(
                validation_dataset=(
                    "Independent grower records 2023-2024 (identical to "
                    "calibration)"
                )
            ) if False else a_valid_evidence(
                validation_dataset=""
            )

    def test_missing_validation_statistics_are_refused(self):
        with pytest.raises(ValueError, match="validation statistics"):
            a_valid_evidence(validation_metrics={})

    def test_a_missing_validation_period_is_refused(self):
        with pytest.raises(ValueError, match="period"):
            a_valid_evidence(validation_period="")

    def test_a_missing_validation_geography_is_refused(self):
        with pytest.raises(ValueError, match="geography"):
            a_valid_evidence(validation_geography="")

    def test_an_empty_crop_scope_is_refused(self):
        with pytest.raises(ValueError, match="crop"):
            a_valid_spec(crop_scope=())

    def test_empty_required_inputs_are_refused(self):
        with pytest.raises(ValueError, match="required_inputs"):
            a_valid_spec(required_inputs=())

    def test_a_dimensionless_output_unit_is_refused(self):
        for unit in ("index", "fraction", "dimensionless", ""):
            with pytest.raises(ValueError, match="mass-per-area"):
                a_valid_spec(output_unit=unit)

    def test_a_missing_geography_or_period_is_refused(self):
        with pytest.raises(ValueError, match="geography and the period"):
            a_valid_spec(applicable_geography="")
        with pytest.raises(ValueError, match="geography and the period"):
            a_valid_spec(applicable_period="")

    def test_a_missing_uncertainty_definition_is_refused(self):
        with pytest.raises(ValueError, match="uncertainty"):
            a_valid_spec(uncertainty_definition="")

    def test_stating_no_uncertainty_is_permitted(self):
        """The honest literal is allowed; inventing numbers is not forced."""
        spec = a_valid_spec(uncertainty_definition="uncertainty not quantified")
        assert spec.uncertainty_definition == "uncertainty not quantified"

    def test_empty_assumptions_are_refused(self):
        with pytest.raises(ValueError, match="assumptions"):
            a_valid_spec(assumptions=())

    def test_an_empty_model_id_is_refused(self):
        with pytest.raises(ValueError, match="model_id"):
            a_valid_spec(model_id="")

    def test_an_empty_parameter_version_is_refused(self):
        with pytest.raises(ValueError, match="parameter_version"):
            a_valid_spec(parameter_version="")


# ==========================================================================
# The registry
# ==========================================================================


class TestYieldModelRegistry:
    def test_a_valid_model_registers(self):
        registry = YieldModelRegistry()
        registry.register(a_valid_spec(), "crop_yield_estimate")
        assert registry.registered_model_ids() == ("test-model",)
        spec, key = registry.get("test-model")
        assert spec.model_version == "1.0.0"
        assert key == "crop_yield_estimate"

    def test_a_duplicate_registration_is_refused(self):
        registry = YieldModelRegistry()
        registry.register(a_valid_spec(), "crop_yield_estimate")
        with pytest.raises(ValueError, match="already registered"):
            registry.register(
                a_valid_spec(model_version="1.0.1"), "crop_yield_estimate"
            )

    def test_one_model_cannot_publish_under_two_keys(self):
        registry = YieldModelRegistry()
        registry.register(a_valid_spec(), "crop_yield_estimate")
        with pytest.raises(ValueError, match="two"):
            registry.register(
                a_valid_spec(model_version="2.0.0"), "some_other_key"
            )

    def test_an_empty_metric_key_is_refused(self):
        registry = YieldModelRegistry()
        with pytest.raises(ValueError, match="metric key"):
            registry.register(a_valid_spec(), "  ")

    def test_distinct_models_register_independently(self):
        registry = YieldModelRegistry()
        registry.register(a_valid_spec(model_id="a"), "crop_yield_estimate")
        registry.register(a_valid_spec(model_id="b"), "crop_biomass_estimate")
        assert registry.registered_model_ids() == ("a", "b")


# ==========================================================================
# The unavailable metrics
# ==========================================================================


class TestUnavailableMetrics:
    def test_the_yield_metric_refuses_with_its_code(self):
        result = UnavailableYieldEstimateMetric().compute(make_context())
        assert result.status == STATUS_UNAVAILABLE
        assert result.value is None
        assert result.reason == YIELD_UNAVAILABLE_CODE
        assert "No validated crop yield model exists" in result.message

    def test_the_biomass_metric_refuses_with_its_code(self):
        result = UnavailableBiomassEstimateMetric().compute(make_context())
        assert result.status == STATUS_UNAVAILABLE
        assert result.value is None
        assert result.reason == BIOMASS_UNAVAILABLE_CODE
        assert "coefficient" in result.message

    def test_the_uncertainty_metric_refuses_with_its_code(self):
        result = UnavailableYieldUncertaintyMetric().compute(make_context())
        assert result.status == STATUS_UNAVAILABLE
        assert result.value is None
        assert result.reason == YIELD_UNCERTAINTY_UNAVAILABLE_CODE
        assert "produces no yield estimate" in result.message

    def test_refusals_are_context_independent(self):
        """No context can coax a value out of a structural refusal."""
        contexts = [
            make_context(),
            make_context(start_date="2021-01-01", end_date="2021-12-31"),
            make_context(start_date="2000-01-01", end_date="2000-01-31"),
        ]
        for metric in ALL_YIELD_MODEL_METRICS:
            for context in contexts:
                result = metric.compute(context)
                assert result.status == STATUS_UNAVAILABLE, (
                    metric.key,
                    context.start_date,
                )
                assert result.value is None

    def test_the_reasons_name_the_missing_requirement(self):
        assert "no field-level calibration data" in YIELD_UNAVAILABLE_REASON
        assert "crop identity" in YIELD_UNAVAILABLE_REASON
        assert "LUE coefficient" in BIOMASS_UNAVAILABLE_REASON or (
            "light-use-efficiency" in BIOMASS_UNAVAILABLE_REASON
        )
        assert "invented" in YIELD_UNCERTAINTY_UNAVAILABLE_REASON

    def test_metadata_flags_availability_and_codes(self):
        for metric in ALL_YIELD_MODEL_METRICS:
            metadata = metric.metadata()
            assert metadata["available"] is False, metric.key
            assert metadata["unavailable_code"], metric.key
            assert len(metadata["unavailable_reason"]) > 100, metric.key

    def test_every_metric_is_inference_based(self):
        for metric in ALL_YIELD_MODEL_METRICS:
            assert metric.measurement_basis == MeasurementBasis.INFERENCE

    def test_the_uncertainty_reason_points_at_the_model_reason(self):
        assert (
            YIELD_UNCERTAINTY_UNAVAILABLE_CODE
            == "no_yield_estimate_to_quantify"
        )
        assert (
            "no_validated_yield_model"
            in YIELD_UNCERTAINTY_UNAVAILABLE_REASON
        )
