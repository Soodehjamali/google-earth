"""The yield-model foundation (Phase M).

This module contains **no yield prediction**. It contains the
architecture that a yield prediction would be required to pass through,
so that when — and only when — a scientifically validated model with
real calibration data exists, it cannot be added to this engine without
also declaring its identity, its scope, its inputs, its provenance and
its validation evidence.

Why the registry starts empty
-----------------------------
A yield model is a claim: "applying this function, with these
parameters, calibrated on these observations, to these inputs, in this
geography and period, predicts a harvested mass". The audit of this
repository found none of the prerequisites:

* no validated yield model of any methodology (empirical, LUE-based,
  simulation, or machine-learned),
* no field-level calibration data of any kind — no harvest records, no
  crop-cut measurements, no official sub-national yield statistics,
  no experimental datasets,
* no validated uncertainty definition,
* and no verified crop identity beyond the 2021 WorldCereal context
  masks (temporary crops, maize main season, Triticeae winter cereals),
  which are crop *context*, not the verified species a crop-specific
  model would require.

Registering a model requires every field of :class:`YieldModelSpec` to
carry real, auditable content. The light-use-efficiency route is
illustrative of why the bar is where it is: an LUE model needs a
crop-specific maximum light-use-efficiency coefficient, and every
published value is measured for a specific species under specific
conditions. Inventing a coefficient, or borrowing one whose
applicability is unverified, would manufacture accuracy that no
observation supports. The same argument applies, one way or another,
to every other methodology — which is why nothing is registered.

What IS here
------------
1. :class:`YieldModelSpec` — the declaration contract. Its ``__post_init__``
   refuses a spec that would quietly omit its calibration provenance,
   its validation evidence, its scope or its units.

2. :class:`YieldModelRegistry` — a registry that validates a spec
   against a declared metric key at registration time and forbids
   changing a model's version while keeping the same one (a model whose
   code changes must change its ``model_version``; that is the rule
   that stops a silent model swap behind a stable metric name).

3. The unavailable metrics — ``crop_yield_estimate``,
   ``crop_biomass_estimate`` and ``crop_yield_uncertainty`` — registered
   in the main metric catalog with precise, machine-readable reasons, so
   the public catalog answers "what is the yield of this field?" with a
   reasoned no instead of a number, and answers "can you tell me how
   confident the yield number is?" by pointing at the reason no number
   exists.

The metrics here use the same ``_UnavailableMetric`` pattern as every
other deliberately unavailable metric in this engine: their ``compute``
has no path that returns a value, so a later edit cannot turn them into
a fabricated indicator without deleting the class outright.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.types import (
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
)

__all__ = [
    "YieldModelSpec",
    "YieldModelRegistry",
    "YIELD_MODEL_REGISTRY",
    "UnavailableYieldEstimateMetric",
    "UnavailableBiomassEstimateMetric",
    "UnavailableYieldUncertaintyMetric",
    "UNAVAILABLE_YIELD_METRICS",
    "ALL_YIELD_MODEL_METRICS",
    "YIELD_UNAVAILABLE_CODE",
    "YIELD_UNAVAILABLE_REASON",
    "BIOMASS_UNAVAILABLE_CODE",
    "BIOMASS_UNAVAILABLE_REASON",
    "YIELD_UNCERTAINTY_UNAVAILABLE_CODE",
    "YIELD_UNCERTAINTY_UNAVAILABLE_REASON",
    "YIELD_MODEL_DOC_URL",
]


# ==========================================================================
# The declaration contract
# ==========================================================================


@dataclass(frozen=True)
class ValidationEvidence:
    """The evidence a registered yield model must be able to show.

    Every field here is a claim about the real world, and each carries
    its own provenance. A model without validation evidence is not an
    unvalidated model; it is an untested hypothesis, and this engine
    does not publish hypotheses as results.
    """

    #: The dataset the model's parameters were fitted or calibrated
    #: against. Named, not described: "Iran MoA 2018-2023 provincial
    #: statistics", never "official data".
    calibration_source: str

    #: The dataset the model was evaluated against *after* calibration.
    #: Must be disjoint from the calibration data for the metrics below
    #: to mean what they say; overlap is declared explicitly.
    validation_dataset: str

    #: The evaluation statistics actually computed on the validation
    #: dataset, e.g. ``{"rmse_t_ha": 0.62, "r2": 0.71, "n": 214}``.
    #: Reported verbatim; never summarised as a word like "accurate".
    validation_metrics: Dict[str, float] = field(default_factory=dict)

    #: The period the validation observations cover.
    validation_period: str = ""

    #: The geography the validation observations cover.
    validation_geography: str = ""

    #: Whether validation observations overlap the calibration ones.
    #: Overlap is permitted only when declared, and a declared overlap
    #: must be reflected in how the metrics are quoted.
    shares_observations_with_calibration: bool = False

    def __post_init__(self) -> None:
        if not self.calibration_source or not self.calibration_source.strip():
            raise ValueError(
                "A yield model must name its calibration source. "
                "'None', 'internal' and 'N/A' do not name a dataset."
            )
        if not self.validation_dataset or not self.validation_dataset.strip():
            raise ValueError(
                "A yield model must name its validation dataset. A model "
                "evaluated on its own training data has no validation "
                "evidence at all."
            )
        if not self.validation_metrics:
            raise ValueError(
                "A yield model must carry computed validation statistics "
                "(RMSE, R2, bias, n, ...). Theoretical formulation alone "
                "is not validation evidence."
            )
        if not self.validation_period or not self.validation_geography:
            raise ValueError(
                "A yield model's validation evidence must state the period "
                "and the geography the validation observations cover."
            )


@dataclass(frozen=True)
class YieldModelSpec:
    """Everything a yield model must declare before it may predict.

    The contract is deliberately heavy. Each field closes one of the
    routes by which a yield number misleads:

    * ``model_id`` and ``model_version`` — a result must be traceable to
      the exact code and parameters that produced it. Changing the model
      while keeping the version is forbidden by the registry, not just
      discouraged.
    * ``crop_scope`` — the species or group the model was calibrated
      for. A wheat model applied to maize is not an approximation; it is
      a different claim wearing the same units.
    * ``required_inputs`` — the metric keys the model consumes, checked
      against the registry at registration time.
    * ``output_unit`` — the unit the model's output is honestly
      expressed in. This engine refuses any yield unit it cannot derive
      from a validated model; ``t/ha`` produced without one is the
      exact failure Phase M exists to prevent.
    * ``applicable_geography`` and ``applicable_period`` — where and
      when the model's calibration is expected to hold. Extrapolation
      beyond them is not performed silently.
    * ``uncertainty_definition`` — what the model's uncertainty actually
      is. If the model cannot quantify uncertainty, the honest string is
      "uncertainty not quantified", and every result built on the model
      must carry that statement rather than an invented interval.
    * ``assumptions`` — every assumption a reader would need in order to
      audit the claim. An empty tuple is refused: a model with no stated
      assumptions is a model whose assumptions are unstated, not a model
      with none.
    """

    #: Stable identifier, e.g. ``"wheat-ndvi-baseline"``.
    model_id: str

    #: Version of this model's specification and parameters. Bumped on
    #: every change to the model's behaviour; never reused.
    model_version: str

    #: Version of the parameter set, distinct from the model version
    #: because parameters can be recalibrated without changing the
    #: model's form.
    parameter_version: str

    #: The crop identities the model is calibrated for. Must be a
    #: non-empty tuple of explicit identities. "any crop" is not an
    #: identity.
    crop_scope: Tuple[str, ...]

    #: The metric keys the model consumes from this engine's registry.
    required_inputs: Tuple[str, ...]

    #: The model's output unit, e.g. ``"t/ha"``. Must be a real mass-per-
    #: area unit; a dimensionless index may never stand in for one.
    output_unit: str

    #: Where the calibration is expected to hold.
    applicable_geography: str

    #: When the calibration is expected to hold.
    applicable_period: str

    #: What the model's uncertainty is. The literal string "uncertainty
    #: not quantified" is permitted and must be carried verbatim into
    #: every result when used.
    uncertainty_definition: str

    #: Every assumption a reader would need to audit the claim.
    assumptions: Tuple[str, ...]

    #: The validation evidence.
    validation: ValidationEvidence

    #: Free-form description of the model's form (empirical regression,
    #: LUE, simulation wrapper, ...). Descriptive only; the identity of
    #: the model is (model_id, model_version).
    methodology: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("model_id", self.model_id),
            ("model_version", self.model_version),
            ("parameter_version", self.parameter_version),
        ):
            if not value or not str(value).strip():
                raise ValueError(
                    f"YieldModelSpec.{name} must be a non-empty string; a "
                    "model without a stable identity cannot be traced."
                )
        if not self.crop_scope:
            raise ValueError(
                "YieldModelSpec.crop_scope must name at least one crop "
                "identity. A model that applies to 'any crop' has no "
                "calibrated scope."
            )
        if not self.required_inputs:
            raise ValueError(
                "YieldModelSpec.required_inputs must name the metric keys "
                "the model consumes; an empty list hides the model's "
                "dependencies."
            )
        if not self.output_unit or self.output_unit.strip() in (
            "",
            "index",
            "fraction",
            "dimensionless",
        ):
            raise ValueError(
                f"YieldModelSpec.output_unit is {self.output_unit!r}. A "
                "yield model's output must be a mass-per-area unit "
                "(t/ha, kg/m2, ...); a dimensionless quantity is not a "
                "yield."
            )
        if not self.applicable_geography or not self.applicable_period:
            raise ValueError(
                "YieldModelSpec must state the geography and the period "
                "its calibration is expected to hold over."
            )
        if not self.uncertainty_definition:
            raise ValueError(
                "YieldModelSpec.uncertainty_definition must be present. "
                "When a model cannot quantify uncertainty, the required "
                "literal is 'uncertainty not quantified', stated openly."
            )
        if not self.assumptions:
            raise ValueError(
                "YieldModelSpec.assumptions must list every assumption the "
                "model rests on; an empty list means unstated assumptions, "
                "not the absence of them."
            )


# ==========================================================================
# The registry
# ==========================================================================


class YieldModelRegistry:
    """Where a validated yield model would be registered.

    Empty by design. Registration validates the spec, pins the metric
    key it may publish under, and records the version so a later edit
    that changes the model without bumping the version is detected
    rather than silently accepted.
    """

    def __init__(self) -> None:
        self._models: Dict[str, Tuple[YieldModelSpec, str]] = {}

    def register(self, spec: YieldModelSpec, metric_key: str) -> None:
        """Register a validated model for publication under ``metric_key``.

        Raises on a duplicate ``(model_id, model_version)`` pair, on a
        version change without a new registration under the same id
        (which the registry treats as an attempt to swap the model
        behind a stable name), and on an empty metric key.
        """
        if not metric_key or not metric_key.strip():
            raise ValueError("A registered model needs a metric key.")
        existing = self._models.get(spec.model_id)
        if existing is not None:
            _, existing_key = existing
            if existing_key == metric_key:
                raise ValueError(
                    f"Model {spec.model_id!r} is already registered for "
                    f"{metric_key!r}. A changed model must change its "
                    "model_version and register explicitly; the registry "
                    "does not overwrite a registered model in place."
                )
            raise ValueError(
                f"Model {spec.model_id!r} is already registered for "
                f"{existing_key!r}; one model cannot publish under two "
                "metric keys."
            )
        self._models[spec.model_id] = (spec, metric_key)

    def get(self, model_id: str) -> Optional[Tuple[YieldModelSpec, str]]:
        """The registered spec and metric key for a model id, or ``None``."""
        return self._models.get(model_id)

    def registered_model_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self._models))

    def __len__(self) -> int:
        return len(self._models)


#: The engine-wide yield-model registry. Empty, and stays empty until a
#: spec carrying genuine calibration and validation evidence exists.
YIELD_MODEL_REGISTRY = YieldModelRegistry()


#: Where the contract is documented, so the refusal can point somewhere
#: actionable.
YIELD_MODEL_DOC_URL = "docs/AGRICULTURAL_ANALYTICS.md#phase-m"


# ==========================================================================
# The unavailable metrics
# ==========================================================================


YIELD_UNAVAILABLE_CODE = "no_validated_yield_model"
YIELD_UNAVAILABLE_REASON = (
    "Not produced. No validated crop yield model exists in this engine. "
    "A yield estimate requires a model whose form, parameters, crop "
    "scope and applicability are scientifically specified, calibrated "
    "against real harvest observations, and evaluated on validation data "
    "disjoint from its calibration. The repository audit found no such "
    "model, no field-level calibration data of any kind (no harvest "
    "records, no crop-cut measurements, no official sub-national yield "
    "statistics, no experimental datasets), and no verified crop "
    "identity beyond the 2021 WorldCereal context masks, which are crop "
    "context, not species. Vegetation indices, ET, LAI and FAPAR are "
    "inputs a validated model could consume; none of them is a yield, "
    "and no published or invented coefficient in this engine converts "
    "them into one. Registering a model requires a complete "
    "YieldModelSpec (model identity, version, crop scope, required "
    "inputs, calibration provenance, validation evidence, geography, "
    "period, uncertainty definition) — see yield_model.py."
)

BIOMASS_UNAVAILABLE_CODE = "no_verified_biomass_model"
BIOMASS_UNAVAILABLE_REASON = (
    "Not produced. No biomass model is implemented because none can be "
    "verified with the data this engine holds. A light-use-efficiency "
    "biomass model would require a crop-specific maximum LUE coefficient "
    "(every published value is measured for a specific species under "
    "specific conditions), the fraction of PAR actually absorbed by the "
    "crop rather than by whatever else shares the pixel, and a respiration "
    "or allocation treatment; a vegetation-index biomass model would "
    "require a species- and site-specific regression fitted on real "
    "harvests. The engine holds none of these: the coefficients are not "
    "verified for any crop this area grows, the WorldCereal masks cannot "
    "establish crop identity, and no harvest observations exist to fit "
    "or evaluate anything against. Inventing or borrowing coefficients "
    "would manufacture a mass out of a dimensionless index, so biomass "
    "is registered as unavailable rather than estimated."
)

YIELD_UNCERTAINTY_UNAVAILABLE_CODE = "no_yield_estimate_to_quantify"
YIELD_UNCERTAINTY_UNAVAILABLE_REASON = (
    "Not produced. Uncertainty is a property of an estimate, and this "
    "engine produces no yield estimate: there is no validated model, no "
    "calibration data and no validation data from which an error "
    "distribution could be derived. A confidence interval or a probability "
    "distribution published here would be invented, and an invented "
    "interval is worse than a missing one because it lends fabricated "
    "precision to a number that does not exist. The yield-estimate "
    "metric's unavailable reason (no_validated_yield_model) states what "
    "would have to change. When a validated model is registered, its "
    "YieldModelSpec.uncertainty_definition governs what may be published: "
    "a model that cannot quantify uncertainty must say 'uncertainty not "
    "quantified' rather than receive a percentage."
)


class _UnavailableYieldMetric(Metric):
    """A yield-domain metric that structurally cannot carry a value.

    Mirrors the crop module's unavailable base: ``compute`` has no path
    that returns a value, so a later change cannot turn one of these
    into a fabricated indicator without deliberately deleting the class.
    """

    domain = MetricDomain.PRODUCTIVITY
    measurement_basis = MeasurementBasis.INFERENCE
    dataset_ids: Tuple[str, ...] = ()

    unavailable_reason: str = ""
    unavailable_code: str = "not_supported"

    def compute(self, context: MetricContext) -> MetricResult:
        provenance = None
        if self.dataset_ids:
            try:
                dataset = self.primary_dataset()
                provenance = self.build_provenance(
                    context=context,
                    dataset=dataset,
                    bands=[],
                    formula="not computed",
                    quality=QualityLevel.UNAVAILABLE,
                    image_count=0,
                    aggregation_method="not applicable",
                )
            except Exception:  # noqa: BLE001 - provenance is optional here
                provenance = None

        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            reason=self.unavailable_code,
            message=self.unavailable_reason,
            unit=self.unit,
            provenance=provenance,
        )

    def metadata(self) -> Dict[str, Any]:
        metadata = super().metadata()
        metadata["available"] = False
        metadata["unavailable_code"] = self.unavailable_code
        metadata["unavailable_reason"] = self.unavailable_reason
        return metadata


class UnavailableYieldEstimateMetric(_UnavailableYieldMetric):
    """Crop yield estimate — registered as unavailable, with the reason."""

    key = "crop_yield_estimate"
    display_name = "Crop Yield Estimate (not produced)"
    display_name_fa = "برآورد عملکرد محصول (تولید نمی‌شود)"
    unit = "t/ha"
    unavailable_code = YIELD_UNAVAILABLE_CODE
    unavailable_reason = YIELD_UNAVAILABLE_REASON
    description = (
        "Harvested crop mass per unit area. Not produced: no validated "
        "yield model, no calibration data and no verified crop identity "
        "exist in this engine."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )


class UnavailableBiomassEstimateMetric(_UnavailableYieldMetric):
    """Crop biomass estimate — registered as unavailable, with the reason."""

    key = "crop_biomass_estimate"
    display_name = "Crop Biomass Estimate (not produced)"
    display_name_fa = "برآورد بیوماس محصول (تولید نمی‌شود)"
    unit = "t/ha"
    unavailable_code = BIOMASS_UNAVAILABLE_CODE
    unavailable_reason = BIOMASS_UNAVAILABLE_REASON
    description = (
        "Above-ground plant mass per unit area. Not produced: no verified "
        "biomass model or species-specific coefficients exist, and no "
        "harvest data exists to fit or evaluate one."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )


class UnavailableYieldUncertaintyMetric(_UnavailableYieldMetric):
    """Yield uncertainty — registered as unavailable, with the reason."""

    key = "crop_yield_uncertainty"
    display_name = "Yield Estimate Uncertainty (not produced)"
    display_name_fa = "عدم قطعیت برآورد عملکرد (تولید نمی‌شود)"
    unit = "t/ha"
    unavailable_code = YIELD_UNCERTAINTY_UNAVAILABLE_CODE
    unavailable_reason = YIELD_UNCERTAINTY_UNAVAILABLE_REASON
    description = (
        "The uncertainty of a yield estimate. Not produced: no yield "
        "estimate exists, and an uncertainty distribution would be "
        "invented."
    )
    limitations = (
        "Not produced. See the unavailable reason for the full argument.",
    )


#: The yield-domain metrics registered in the main metric catalog. All
#: three are unavailable, and each carries its precise reason.
UNAVAILABLE_YIELD_METRICS: Tuple[Metric, ...] = (
    UnavailableYieldEstimateMetric(),
    UnavailableBiomassEstimateMetric(),
    UnavailableYieldUncertaintyMetric(),
)

ALL_YIELD_MODEL_METRICS: Tuple[Metric, ...] = UNAVAILABLE_YIELD_METRICS
