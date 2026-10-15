"""Agricultural Intelligence Synthesis Layer (Phase P).

This module synthesises structured descriptive agricultural context from
evidence assembled by the Phase O evidence layer.

**What this module is:**

A deterministic, rule-based synthesis layer that answers:

"What structured descriptive agricultural context can be synthesised
from the available evidence?"

**What this module is NOT:**

* A diagnosis engine
* A prediction system
* A recommendation engine
* A scoring system (no 0--100 confidence, no health score)

**Architecture:**

Existing Metrics
       |
Historical Analytics (Phase N)
       |
Evidence Layer (Phase O)
       |
Agricultural Synthesis (Phase P)
       |
Future API / UI

**Design principles:**

* Every statement is traceable to explicit rules and evidence
* Every statement carries its scientific basis and limitations
* Mixed and conflicting evidence is a valid result
* No causal claims unless explicitly supported by a validated model
* No crop health scores, risk scores, or confidence percentages
* Deterministic: identical inputs produce identical output
* No LLM, no random scoring

**Scientific boundary:**

Multiple observations consistent with a condition do not automatically
prove that condition.  The system reports what is observably consistent,
not what is causally happening.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import (
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

from app.services.agriculture.evidence import (
    ConsistencyStatus,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceItem,
    EvidenceStatus,
    SufficiencyLevel,
)
from app.services.agriculture.types import QualityLevel
from app.services.agriculture.quality_gating import QualityState
from app.services.agriculture.regime import (
    RegimeAssessment,
    VegetationRegime,
    classify_vegetation_regime,
)

# Minimum absolute anomaly threshold to distinguish meaningful canopy departure
# from sensor noise floor and surface reflectance fluctuation (Copernicus / MODIS
# change-detection standards: |ΔNDVI| >= 0.02).
NDVI_ANOMALY_SIGNIFICANCE_THRESHOLD: float = 0.02

# Minimum soil moisture rootzone anomaly threshold (volumetric fraction) to distinguish
# meaningful hydrological departure from retrieval uncertainty (error ~±0.04 m3/m3).
SOIL_MOISTURE_ANOMALY_SIGNIFICANCE_THRESHOLD: float = 0.01


# ---------------------------------------------------------------------------
# 1. Synthesis enums
# ---------------------------------------------------------------------------


class SynthesisDomain(str, Enum):
    """Agricultural synthesis domain."""

    VEGETATION = "vegetation"
    WATER = "water"
    THERMAL = "thermal"
    SOIL = "soil"
    CLIMATE = "climate"
    CROP = "crop"
    PHENOLOGY = "phenology"
    PRODUCTIVITY = "productivity"
    HISTORICAL = "historical"
    CROSS_DOMAIN = "cross_domain"
    TERRAIN = "terrain"
    LANDCOVER = "landcover"
    STRESS = "stress"
    IRRIGATION = "irrigation"


class PatternState(str, Enum):
    """A descriptive pattern in the evidence.

    These describe observations.  They are NOT diagnoses, predictions,
    or recommendations.
    """

    BELOW_CONTEXT = "below_context"
    NEAR_CONTEXT = "near_context"
    ABOVE_CONTEXT = "above_context"
    MIXED_EVIDENCE = "mixed_evidence"
    SUFFICIENT = "sufficient"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"
    COHERENT = "coherent"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# 2. Synthesis rule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SynthesisRule:
    """An explicit, deterministic interpretation rule.

    Every rule defines:

    * ``rule_id``: unique identifier
    * ``domain``: which domain this rule applies to
    * ``inputs``: which metric keys are required (or legacy input tuple)
    * ``conditions``: a callable that evaluates whether the rule fires
    * ``output_pattern``: the pattern state when the rule fires
    * ``statement``: the human-readable output when the rule fires
    * ``scientific_basis``: why this rule is scientifically justified
    * ``limitations``: when this rule may not hold
    * ``min_sources``: minimum independent sources for sufficiency
    * ``required_inputs``: inputs that strictly must be present
    * ``optional_inputs``: inputs evaluated when available
    * ``min_inputs``: minimum count of available inputs required
    * ``applicable_regimes``: which vegetation regimes this rule applies to

    Rules are evaluated deterministically.  Given identical inputs, they
    produce identical outputs.  No randomness, no LLM.
    """

    rule_id: str
    domain: SynthesisDomain
    inputs: Tuple[str, ...]
    conditions: Callable[..., bool]
    output_pattern: PatternState
    statement: str
    scientific_basis: str
    limitations: Tuple[str, ...] = ()
    min_sources: int = 2
    required_inputs: Tuple[str, ...] = ()
    optional_inputs: Tuple[str, ...] = ()
    min_inputs: int = 1
    applicable_regimes: Tuple[VegetationRegime, ...] = (
        VegetationRegime.VEGETATED,
        VegetationRegime.NON_VEGETATED,
        VegetationRegime.UNCERTAIN,
    )


# ---------------------------------------------------------------------------
# 3. Synthesis statement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SynthesisStatement:
    """A single synthesised statement with its evidence and provenance.

    Every statement is:

    * traceable to a rule and evidence
    * carrying its scientific basis and limitations
    * describing an observation, not a cause
    """

    rule_id: str
    domain: SynthesisDomain
    pattern: PatternState
    statement: str
    evidence_keys: Tuple[str, ...]
    evidence_values: Dict[str, Optional[float]]
    scientific_basis: str
    limitations: Tuple[str, ...]
    sufficiency: SufficiencyLevel = SufficiencyLevel.SUFFICIENT
    conflicts: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 4. Domain summary
# ---------------------------------------------------------------------------


@dataclass
class DomainSummary:
    """A per-domain collection of synthesis statements.

    Preserves each metric independently.  Does not collapse into one
    number.  Reports available evidence, unavailable evidence,
    sufficiency, conflicts, and limitations.

    ``has_usable_evidence`` (F-CONTRACT-FIX-1 §3) records whether the
    evaluated bundle held at least one usable evidence item — finite
    value, non-unavailable status, usable quality.  It is set by the
    engine from the bundle's own ``available_items`` and is the
    data-presence signal that statement generation must never
    substitute for.  Defaults to ``False`` so hand-constructed
    summaries stay honest until real evidence state is attached.
    """

    domain: SynthesisDomain
    statements: List[SynthesisStatement] = field(default_factory=list)
    unavailable_evidence: List[str] = field(default_factory=list)
    sufficiency: SufficiencyLevel = SufficiencyLevel.INSUFFICIENT
    conflicts: List[EvidenceConflict] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    has_usable_evidence: bool = False
    vegetation_regime: Optional[str] = None

    @property
    def has_statements(self) -> bool:
        return len(self.statements) > 0

    @property
    def statement_count(self) -> int:
        return len(self.statements)

    def to_dict(self) -> Dict[str, object]:
        return {
            "domain": self.domain.value,
            "statement_count": self.statement_count,
            "statements": [
                {
                    "rule_id": s.rule_id,
                    "pattern": s.pattern.value,
                    "statement": s.statement,
                    "evidence_keys": list(s.evidence_keys),
                    "sufficiency": s.sufficiency.value,
                }
                for s in self.statements
            ],
            "unavailable_evidence": list(self.unavailable_evidence),
            "sufficiency": self.sufficiency.value,
            "conflict_count": len(self.conflicts),
            "has_usable_evidence": self.has_usable_evidence,
            "vegetation_regime": self.vegetation_regime,
            "limitations": list(self.limitations),
        }


# ---------------------------------------------------------------------------
# 5. Agricultural synthesis (top-level)
# ---------------------------------------------------------------------------


@dataclass
class AgriculturalSynthesis:
    """Top-level synthesis result.

    Contains domain-level summaries, overall sufficiency, cross-domain
    consistency, and provenance.  Answers "what is currently observable
    about this field?" without pretending to answer "what should the
    farmer do?"
    """

    time_start: Optional[date]
    time_end: Optional[date]
    spatial_context: Optional[str] = None
    domain_summaries: Dict[SynthesisDomain, DomainSummary] = field(
        default_factory=dict
    )
    overall_sufficiency: SufficiencyLevel = SufficiencyLevel.INSUFFICIENT
    cross_domain_statements: List[SynthesisStatement] = field(
        default_factory=list
    )
    limitations: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    vegetation_regime: Optional[str] = None

    # NOTE (F-CONTRACT-FIX-1): ``available_domains`` keeps its historical
    # statement-based meaning so existing consumers and cached payloads
    # are unaffected.  The explicit data/statement split below is the
    # unambiguous replacement surface for new consumers.
    @property
    def available_domains(self) -> List[SynthesisDomain]:
        """Domains with at least one fired synthesis statement.

        Historical semantics, deliberately preserved: a domain appears
        here only when a synthesis rule actually fired, not merely
        because usable evidence exists.  See ``domains_with_data`` and
        ``domains_with_statements`` for the explicit split.
        """
        return [
            d
            for d, s in self.domain_summaries.items()
            if s.has_statements
        ]

    @property
    def unavailable_domains(self) -> List[SynthesisDomain]:
        return [
            d
            for d, s in self.domain_summaries.items()
            if not s.has_statements
        ]

    @property
    def domains_with_data(self) -> List[SynthesisDomain]:
        """Domains carrying at least one usable evidence item.

        Data presence only: a domain qualifies when its bundle holds
        at least one item that ``EvidenceItem.is_usable`` accepts
        (finite value, not unavailable status, usable quality).
        Statement generation is irrelevant here.
        """
        return [
            d
            for d, s in self.domain_summaries.items()
            if s.has_usable_evidence
        ]

    @property
    def domains_with_statements(self) -> List[SynthesisDomain]:
        """Domains with one or more fired synthesis statements.

        Identical in content to ``available_domains`` (the historical
        property), but named for its exact meaning so new consumers
        never have to guess what "available" meant.
        """
        return [
            d
            for d, s in self.domain_summaries.items()
            if s.has_statements
        ]

    @property
    def domains_without_data(self) -> List[SynthesisDomain]:
        """Domains whose bundles hold no usable evidence item.

        A domain whose every item is unavailable (or whose bundle is
        empty) lands here, whether or not a statement happened to
        fire.  This is the honest complement of ``domains_with_data``.
        """
        return [
            d
            for d, s in self.domain_summaries.items()
            if not s.has_usable_evidence
        ]

    def domain_summary(
        self, domain: SynthesisDomain
    ) -> Optional[DomainSummary]:
        return self.domain_summaries.get(domain)

    def unavailable_metric_keys(self) -> List[str]:
        """De-duplicated unavailable metric keys across all domain bundles.

        Canonical aggregate unavailability (F-CONTRACT-FIX-1 §4):
        ``DomainSummary.unavailable_evidence`` lists the same keys as
        each bundle's own unavailable list, so a naive concatenation
        double-counts every missing metric.  This property returns each
        key exactly once, in first-seen bundle order.  It is the one
        semantic source for "how many metrics are unavailable"; the
        per-bundle and per-summary lists remain the detailed views.
        """
        seen: Dict[str, None] = {}
        for summary in self.domain_summaries.values():
            for key in summary.unavailable_evidence:
                if key not in seen:
                    seen[key] = None
        return list(seen)

    def to_dict(self) -> Dict[str, object]:
        return {
            "time_start": self.time_start.isoformat()
            if self.time_start
            else None,
            "time_end": self.time_end.isoformat()
            if self.time_end
            else None,
            "spatial_context": self.spatial_context,
            "available_domains": [d.value for d in self.available_domains],
            "unavailable_domains": [
                d.value for d in self.unavailable_domains
            ],
            "domains_with_data": [d.value for d in self.domains_with_data],
            "domains_with_statements": [
                d.value for d in self.domains_with_statements
            ],
            "domains_without_data": [
                d.value for d in self.domains_without_data
            ],
            "unavailable_metric_keys": self.unavailable_metric_keys(),
            "overall_sufficiency": self.overall_sufficiency.value,
            "domain_summaries": {
                d.value: s.to_dict()
                for d, s in self.domain_summaries.items()
            },
            "cross_domain_statements": [
                {
                    "rule_id": cs.rule_id,
                    "pattern": cs.pattern.value,
                    "statement": cs.statement,
                    "evidence_keys": list(cs.evidence_keys),
                }
                for cs in self.cross_domain_statements
            ],
            "limitations": list(self.limitations),
            "metadata": dict(self.metadata),
            "vegetation_regime": self.vegetation_regime,
        }


# ---------------------------------------------------------------------------
# 6. Helper: evaluate a domain rule
# ---------------------------------------------------------------------------


def _evaluate_rule(
    rule: SynthesisRule,
    evidence: EvidenceBundle,
    regime: VegetationRegime = VegetationRegime.UNCERTAIN,
) -> Optional[SynthesisStatement]:
    """Evaluate a single rule against an evidence bundle.

    Returns a ``SynthesisStatement`` if the rule fires, ``None``
    otherwise.  Deterministic: identical inputs produce identical output.
    """
    # 1. Regime gate (Phase P-AGRI-1.1 & P-AGRI-1.2)
    if regime not in rule.applicable_regimes:
        return None

    # 2. Check input requirements (Phase P-AGRI-1.4 fault tolerance)
    available_keys = set(evidence.available_keys)
    if rule.optional_inputs:
        required_keys = set(rule.required_inputs)
        if not required_keys.issubset(available_keys):
            return None
        allowed_keys = set(rule.required_inputs) | set(rule.optional_inputs)
        matched_keys = allowed_keys & available_keys
        if len(matched_keys) < rule.min_inputs:
            return None
    else:
        required_keys = (
            set(rule.required_inputs)
            if rule.required_inputs
            else set(rule.inputs)
        )
        if not required_keys.issubset(available_keys):
            return None
        matched_keys = required_keys

    # Collect evidence items for this rule
    items = [
        i for i in evidence.available_items
        if i.metric_key in matched_keys
    ]
    if not items:
        return None

    # Check conditions
    evidence_dict = {i.metric_key: i for i in items}
    values = {k: i.value for k, i in evidence_dict.items()}
    try:
        if not rule.conditions(evidence_dict, values):
            return None
    except Exception:
        return None

    # Determine sufficiency
    sufficiency = SufficiencyLevel.INSUFFICIENT
    if evidence.sufficiency is not None:
        sufficiency = evidence.sufficiency.level

    # Hard invariant (Phase 2): coarse_context cannot raise sufficiency to
    # SUFFICIENT (Level A) for field-level statements (rules outside CLIMATE).
    if rule.domain != SynthesisDomain.CLIMATE:
        all_coarse = all(getattr(i, "is_coarse_context", False) for i in items)
        if all_coarse and sufficiency == SufficiencyLevel.SUFFICIENT:
            sufficiency = SufficiencyLevel.LIMITED

    # Collect conflicts involving this rule's evidence
    relevant_conflicts = [
        c.explanation
        for c in evidence.conflicts
        if c.metric_a in matched_keys or c.metric_b in matched_keys
    ]

    limitations = list(rule.limitations)
    # Fault-tolerant missing evidence disclosure
    if rule.optional_inputs:
        missing_optional = set(rule.optional_inputs) - available_keys
        if (
            "evapotranspiration_anomaly" in missing_optional
            or "evapotranspiration" in missing_optional
        ):
            limitations.append(
                "Direct ET-based water-balance confirmation was unavailable at this location due to quality masking."
            )

    return SynthesisStatement(
        rule_id=rule.rule_id,
        domain=rule.domain,
        pattern=rule.output_pattern,
        statement=rule.statement,
        evidence_keys=tuple(sorted(matched_keys)),
        evidence_values=values,
        scientific_basis=rule.scientific_basis,
        limitations=tuple(limitations),
        sufficiency=sufficiency,
        conflicts=tuple(relevant_conflicts),
    )


# ---------------------------------------------------------------------------
# 7. Default interpretation rules
# ---------------------------------------------------------------------------


# -- Water rules -----------------------------------------------------------

def _water_below_baseline(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Multiple water indicators show below-baseline values."""
    negative_count = sum(
        1 for v in values.values()
        if v is not None and v < 0
    )
    return negative_count >= 2


def _water_mixed(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Water indicators show mixed directions."""
    has_positive = any(
        v is not None and v > 0 for v in values.values()
    )
    has_negative = any(
        v is not None and v < 0 for v in values.values()
    )
    return has_positive and has_negative


def _water_above_baseline(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Multiple water indicators show above-baseline values."""
    positive_count = sum(
        1 for v in values.values()
        if v is not None and v > 0
    )
    return positive_count >= 2


WATER_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="water_below_baseline",
        domain=SynthesisDomain.WATER,
        inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "evapotranspiration_anomaly",
        ),
        required_inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
        ),
        optional_inputs=("evapotranspiration_anomaly",),
        min_inputs=2,
        conditions=_water_below_baseline,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "Multiple water-availability indicators show below-baseline "
            "values: precipitation, soil moisture, and/or "
            "evapotranspiration are lower than their historical reference."
        ),
        scientific_basis=(
            "Precipitation, soil moisture, and evapotranspiration are "
            "independently measured or modelled water-balance terms.  "
            "When multiple terms simultaneously run below their "
            "historical baseline, the pattern is coherent."
        ),
        limitations=(
            "Different temporal response lags may cause short-term "
            "divergence.  Soil moisture responds faster than "
            "precipitation accumulates.  ET depends on atmospheric "
            "demand as well as water supply.",
            "ERA5-Land precipitation is modelled at roughly 11 km, "
            "not measured at the field.  SMAP soil moisture is a "
            "retrieval at roughly 9 km.  MODIS ET is a modelled "
            "product at 500 m.",
        ),
        min_sources=2,
    ),
    SynthesisRule(
        rule_id="water_mixed_evidence",
        domain=SynthesisDomain.WATER,
        inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "evapotranspiration_anomaly",
        ),
        required_inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
        ),
        optional_inputs=("evapotranspiration_anomaly",),
        min_inputs=2,
        conditions=_water_mixed,
        output_pattern=PatternState.MIXED_EVIDENCE,
        statement=(
            "Water-availability indicators show mixed evidence: some "
            "terms are above baseline while others are below."
        ),
        scientific_basis=(
            "Mixed water-balance signals are a valid observation.  "
            "They may reflect temporal lags, spatial resolution "
            "differences, or different response dynamics."
        ),
        limitations=(
            "Mixed evidence does not mean either metric is wrong.  "
            "Possible causes include temporal mismatch, spatial "
            "mismatch, lagged response, or source differences.",
        ),
        min_sources=2,
    ),
    SynthesisRule(
        rule_id="water_above_baseline",
        domain=SynthesisDomain.WATER,
        inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "evapotranspiration_anomaly",
        ),
        required_inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
        ),
        optional_inputs=("evapotranspiration_anomaly",),
        min_inputs=2,
        conditions=_water_above_baseline,
        output_pattern=PatternState.ABOVE_CONTEXT,
        statement=(
            "Multiple water-availability indicators show above-baseline "
            "values: precipitation, soil moisture, and/or "
            "evapotranspiration are higher than their historical reference."
        ),
        scientific_basis=(
            "When multiple water-balance terms simultaneously run above "
            "their historical baseline, the pattern indicates wetter "
            "than normal conditions."
        ),
        limitations=(
            "Above-baseline precipitation does not guarantee adequate "
            "soil moisture at the root zone.  Runoff and drainage may "
            "carry excess water away.",
        ),
        min_sources=2,
    ),
]

# -- Vegetation rules ------------------------------------------------------

def _veg_below_baseline(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Vegetation indices show below-historical values."""
    abs_anom = values.get("ndvi_anomaly_absolute")
    if abs_anom is not None and abs(abs_anom) < NDVI_ANOMALY_SIGNIFICANCE_THRESHOLD:
        return False
    negative_count = sum(
        1 for v in values.values()
        if v is not None and v < 0
    )
    return negative_count >= 2


def _veg_above_baseline(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Vegetation indices show above-historical values."""
    abs_anom = values.get("ndvi_anomaly_absolute")
    if abs_anom is not None and abs(abs_anom) < NDVI_ANOMALY_SIGNIFICANCE_THRESHOLD:
        return False
    positive_count = sum(
        1 for v in values.values()
        if v is not None and v > 0
    )
    return positive_count >= 2


def _is_bare_ground_surface(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Surface condition indicates bare ground / absence of canopy."""
    ndvi = values.get("ndvi")
    dw_prob = values.get("land_cover_probability")
    if ndvi is not None and ndvi < 0.12:
        return True
    if dw_prob is not None and dw_prob >= 0.40:
        return True
    return False


VEGETATION_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="vegetation_below_historical",
        domain=SynthesisDomain.VEGETATION,
        inputs=(
            "ndvi_anomaly_absolute",
            "ndvi_anomaly_relative",
        ),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_veg_below_baseline,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "Vegetation indices show below-historical values: NDVI is "
            "lower than its month-of-year baseline."
        ),
        scientific_basis=(
            "NDVI anomaly measures the difference between the current "
            "observation and the historical month-of-year baseline.  A "
            "negative anomaly indicates lower greenness than the "
            "reference period."
        ),
        limitations=(
            "NDVI saturates over dense canopies.  Cloud gaps at the "
            "seasonal peak may bias the mean downward.  The anomaly is "
            "a descriptive statistic, not a diagnosis of crop health.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="vegetation_above_historical",
        domain=SynthesisDomain.VEGETATION,
        inputs=(
            "ndvi_anomaly_absolute",
            "ndvi_anomaly_relative",
        ),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_veg_above_baseline,
        output_pattern=PatternState.ABOVE_CONTEXT,
        statement=(
            "Vegetation indices show above-historical values: NDVI is "
            "higher than its month-of-year baseline."
        ),
        scientific_basis=(
            "A positive NDVI anomaly indicates higher greenness than "
            "the reference period."
        ),
        limitations=(
            "Above-baseline NDVI may reflect favourable growing "
            "conditions, but the anomaly does not identify the cause.",
        ),
        min_sources=1,
    ),
]

# -- Canopy-proxy rules (Phase CD-5 production wiring) -------------------
#
# Each rule consumes exactly one input — the middle-canopy dryness
# proxy state code — and fires only for its own state.  The conditions
# compare against the exact integer codes the proxy publishes (1.0 to
# 5.0, exactly representable, never averaged), so the rules restate
# proxy evidence deterministically instead of reinterpreting it.
# Every statement is explicitly proxy-labelled, carries the proxy's
# limitations, and converts the state into no physical quantity.

def _proxy_is_optical_stress_only(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Proxy reports optical-only stress (state 1)."""
    value = values.get("middle_canopy_dryness_proxy")
    return value is not None and value == 1.0


def _proxy_is_radar_context_only(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Proxy reports radar-only structural context (state 2)."""
    value = values.get("middle_canopy_dryness_proxy")
    return value is not None and value == 2.0


def _proxy_is_concordant_stress(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Proxy reports concordant stress (state 3)."""
    value = values.get("middle_canopy_dryness_proxy")
    return value is not None and value == 3.0


def _proxy_is_mixed(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Proxy reports mixed or contradictory evidence (state 4)."""
    value = values.get("middle_canopy_dryness_proxy")
    return value is not None and value == 4.0


def _proxy_is_no_stress(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Proxy reports no stress evidence (state 5)."""
    value = values.get("middle_canopy_dryness_proxy")
    return value is not None and value == 5.0


CANOPY_PROXY_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="canopy_proxy_concordant_stress",
        domain=SynthesisDomain.VEGETATION,
        inputs=("middle_canopy_dryness_proxy",),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_proxy_is_concordant_stress,
        output_pattern=PatternState.COHERENT,
        statement=(
            "Middle-canopy dryness proxy reports CONCORDANT_STRESS "
            "(state 3 of 5): optical seasonal moisture/stress anomalies "
            "show deterioration with compatible radar structural "
            "context in the same analysis window.  This is an evidence "
            "proxy, not a measurement of middle-canopy leaves."
        ),
        scientific_basis=(
            "The proxy combines the deterministic sign classification "
            "of the NDMI, MSI and NDRE seasonal anomalies with "
            "Sentinel-1 VV/VH/VH-VV/RVI contextual availability on the "
            "same requested window.  Coexistence of optical "
            "deterioration with usable radar context is reported as "
            "concordance.  This describes evidence agreement, not a "
            "physical process."
        ),
        limitations=(
            "Optical data observe the canopy top-down and isolate no "
            "leaf layer.  Radar signals are contextual only and carry "
            "no stress direction.  The state code is an identifier, "
            "not a magnitude, percentage, or moisture content.  No "
            "cause is diagnosed.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="canopy_proxy_optical_stress_only",
        domain=SynthesisDomain.VEGETATION,
        inputs=("middle_canopy_dryness_proxy",),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_proxy_is_optical_stress_only,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "Middle-canopy dryness proxy reports OPTICAL_STRESS_ONLY "
            "(state 1 of 5): optical seasonal anomalies show "
            "deterioration without usable radar corroboration in the "
            "same window.  This is an evidence proxy, not a "
            "measurement of middle-canopy leaves."
        ),
        scientific_basis=(
            "Optical-only deterioration is reported without radar "
            "corroboration because the radar leg contributed no usable "
            "evidence.  Absence of corroboration is recorded as "
            "missing, not as contradiction."
        ),
        limitations=(
            "Optical data observe the canopy top-down and isolate no "
            "leaf layer.  Without radar context this reading is "
            "weaker.  The state code is an identifier, not a "
            "magnitude, percentage, or moisture content.  No cause is "
            "diagnosed.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="canopy_proxy_radar_context_only",
        domain=SynthesisDomain.VEGETATION,
        inputs=("middle_canopy_dryness_proxy",),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_proxy_is_radar_context_only,
        output_pattern=PatternState.NEAR_CONTEXT,
        statement=(
            "Middle-canopy dryness proxy reports "
            "RADAR_STRUCTURAL_CONTEXT_ONLY (state 2 of 5): radar "
            "structural context is available while optical "
            "moisture/stress evidence is unavailable.  No stress "
            "direction is implied.  This is an evidence proxy, not a "
            "measurement of middle-canopy leaves."
        ),
        scientific_basis=(
            "Radar structural context coexists with unavailable optical "
            "evidence on the same requested window.  Radar carries no "
            "stress direction, so no deterioration reading follows."
        ),
        limitations=(
            "Radar signals mix canopy structure, biomass, soil, "
            "roughness and acquisition geometry.  Optical evidence is "
            "unavailable, so no moisture/stress reading exists.  The "
            "state code is an identifier, not a magnitude, percentage, "
            "or moisture content.  No cause is diagnosed.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="canopy_proxy_mixed",
        domain=SynthesisDomain.VEGETATION,
        inputs=("middle_canopy_dryness_proxy",),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_proxy_is_mixed,
        output_pattern=PatternState.MIXED_EVIDENCE,
        statement=(
            "Middle-canopy dryness proxy reports MIXED_OR_CONTRADICTORY "
            "(state 4 of 5): available optical signals materially "
            "disagree, so no deterioration reading is supported.  This "
            "is an evidence proxy, not a measurement of "
            "middle-canopy leaves."
        ),
        scientific_basis=(
            "Stress-direction and anti-stress-direction optical "
            "anomalies coexist for the same window.  Disagreement is "
            "reported as mixed evidence rather than resolved toward "
            "either side."
        ),
        limitations=(
            "Mixed evidence may reflect real spatial heterogeneity, "
            "phenology, or sensor confounding rather than error.  The "
            "state code is an identifier, not a magnitude, percentage, "
            "or moisture content.  No cause is diagnosed.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="canopy_proxy_no_stress",
        domain=SynthesisDomain.VEGETATION,
        inputs=("middle_canopy_dryness_proxy",),
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_proxy_is_no_stress,
        output_pattern=PatternState.NEAR_CONTEXT,
        statement=(
            "Middle-canopy dryness proxy reports NO_STRESS_EVIDENCE "
            "(state 5 of 5): available evidence shows "
            "reference-or-better conditions with no deterioration "
            "signal.  This is an evidence proxy, not a measurement of "
            "middle-canopy leaves."
        ),
        scientific_basis=(
            "All usable optical seasonal anomalies read neutral or "
            "favourable against their baselines on the same requested "
            "window.  Absence of a deterioration signal is reported "
            "explicitly rather than as missing evidence."
        ),
        limitations=(
            "Reference-or-better conditions in one window do not "
            "preclude stress in another.  The state code is an "
            "identifier, not a magnitude, percentage, or moisture "
            "content.  No cause is diagnosed.",
        ),
        min_sources=1,
    ),
]

# -- Thermal rules ---------------------------------------------------------

def _thermal_high_lst(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """LST anomaly is positive (warmer than baseline)."""
    return values.get("lst_day_anomaly") is not None and values["lst_day_anomaly"] > 0


def _thermal_high_surface_temp(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Daytime land surface temperature is severely elevated."""
    lst = values.get("land_surface_temperature_day")
    return lst is not None and lst >= 45.0


THERMAL_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="thermal_above_baseline",
        domain=SynthesisDomain.THERMAL,
        inputs=("lst_day_anomaly",),
        conditions=_thermal_high_lst,
        output_pattern=PatternState.ABOVE_CONTEXT,
        statement=(
            "Land surface temperature is above its historical baseline.  "
            "The surface is warmer than the reference period."
        ),
        scientific_basis=(
            "LST anomaly measures the difference between the current "
            "observation and the historical same-calendar-window "
            "baseline.  A positive anomaly indicates warmer conditions."
        ),
        limitations=(
            "LST is surface temperature, not canopy temperature.  The "
            "thermal signal combines soil, vegetation, and atmospheric "
            "components.  Spatial resolution is approximately 1 km for "
            "MODIS, which may not resolve field-scale variability.",
        ),
        min_sources=1,
    ),
]

# -- Soil rules ------------------------------------------------------------

def _soil_moisture_below(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Soil moisture anomaly is negative."""
    return (
        values.get("soil_moisture_rootzone_anomaly") is not None
        and values["soil_moisture_rootzone_anomaly"] < 0
    )


def _soil_surface_desiccation(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Surface soil moisture is below permanent wilting point."""
    sm = values.get("soil_moisture_surface")
    wp = values.get("soil_wilting_point")
    if sm is not None and wp is not None:
        return sm < wp
    if sm is not None and sm < 0.08:
        return True
    return False


def _soil_rootzone_model_conflict(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """SMAP L4 and ERA5-Land root-zone moisture diverge significantly."""
    smap = values.get("soil_moisture_rootzone")
    era5 = values.get("soil_moisture_rootzone_era5")
    if smap is not None and era5 is not None:
        diff = abs(smap - era5)
        ratio = max(smap, era5) / max(min(smap, era5), 1e-4)
        return diff > 0.05 or ratio > 2.0
    return False


SOIL_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="soil_moisture_below_baseline",
        domain=SynthesisDomain.SOIL,
        inputs=("soil_moisture_rootzone_anomaly",),
        conditions=_soil_moisture_below,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "Root-zone soil moisture is below its historical baseline."
        ),
        scientific_basis=(
            "SMAP L4 root-zone soil moisture is an assimilated model "
            "product.  A negative anomaly indicates drier than normal "
            "root-zone conditions."
        ),
        limitations=(
            "SMAP L4 is a modelled product at roughly 9 km, not a "
            "direct measurement at the field.  The root-zone estimate "
            "is an assimilation, not a retrieval.",
        ),
        min_sources=1,
    ),
]

# -- Climate / atmospheric aridity helpers ---------------------------------

def _climate_atmospheric_aridity(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Vapor pressure deficit indicates extreme atmospheric evaporative demand."""
    vpd = values.get("vpd")
    if vpd is not None and vpd >= 3.0:
        return True
    rh = values.get("rh")
    if rh is not None and rh < 25.0:
        return True
    return False


def _climate_near_freezing_minimum(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Forecasted or observed minimum temperature is at or below freezing threshold."""
    t_min = values.get("temperature_min")
    return t_min is not None and t_min <= 2.0


def _cross_cold_air_pooling_frost_risk(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Cold air pooling potential coincides with low minimum temperature."""
    t_min = values.get("temperature_min")
    if t_min is None or t_min > 3.0:
        return False
    cap_val = values.get("cold_air_pooling_index")
    if cap_val is not None and cap_val > 0.0:
        return True
    cap_item = evidence.get("cold_air_pooling_risk")
    if cap_item and str(cap_item.value).lower() in ("moderate", "high", "critical", "warning", "watch"):
        return True
    return False


# -- Phenology rules -------------------------------------------------------

def _phenology_delayed_onset(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Season onset is later than historical context."""
    v = values.get("season_timing_history")
    return v is not None and v > 0


def _phenology_early_onset(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Season onset is earlier than historical context."""
    v = values.get("season_timing_history")
    return v is not None and v < 0


PHENOLOGY_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="phenology_later_onset",
        domain=SynthesisDomain.PHENOLOGY,
        inputs=("season_timing_history",),
        conditions=_phenology_delayed_onset,
        output_pattern=PatternState.ABOVE_CONTEXT,
        statement=(
            "The vegetation season onset is later than the historical "
            "context.  The growing signal started after the reference "
            "period's average."
        ),
        scientific_basis=(
            "Season timing history compares the analysis year's "
            "vegetation season onset against preceding years' detected "
            "seasons.  A positive value means later onset."
        ),
        limitations=(
            "The vegetation season is not the crop calendar.  Onset "
            "describes the NDVI threshold crossing, not planting date.  "
            "Canopy development follows sowing by an interval that "
            "depends on species, cultivar, and conditions.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="phenology_earlier_onset",
        domain=SynthesisDomain.PHENOLOGY,
        inputs=("season_timing_history",),
        conditions=_phenology_early_onset,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "The vegetation season onset is earlier than the historical "
            "context.  The growing signal started before the reference "
            "period's average."
        ),
        scientific_basis=(
            "Season timing history compares the analysis year's "
            "vegetation season onset against preceding years' detected "
            "seasons.  A negative value means earlier onset."
        ),
        limitations=(
            "The vegetation season is not the crop calendar.  Earlier "
            "onset does not necessarily mean earlier planting.",
        ),
        min_sources=1,
    ),
]

# -- Productivity rules ----------------------------------------------------

def _productivity_below(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Productivity indicator is below zero (below baseline)."""
    v = values.get("seasonal_vegetation_productivity_indicator")
    return v is not None and v < 0


PRODUCTIVITY_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="productivity_below_baseline",
        domain=SynthesisDomain.PRODUCTIVITY,
        inputs=("seasonal_vegetation_productivity_indicator",),
        conditions=_productivity_below,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "The seasonal vegetation productivity indicator is below "
            "its historical baseline.  The mean greenness over the "
            "detected season is lower than the reference period."
        ),
        scientific_basis=(
            "The seasonal vegetation productivity indicator is the mean "
            "NDVI over the detected vegetation season, compared against "
            "the historical baseline.  It is a vegetation-productivity "
            "proxy, not a yield estimate."
        ),
        limitations=(
            "This is a vegetation-productivity proxy.  It describes the "
            "strength of the vegetation signal, not the mass of any "
            "crop.  It carries no units of mass and cannot be converted "
            "into yield without a validated model this engine does not "
            "have.",
        ),
        min_sources=1,
    ),
]

# -- Historical rules ------------------------------------------------------

def _historical_low_percentile(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """NDVI is at a low percentile of the reference period."""
    v = values.get("ndvi_percentile_context")
    return v is not None and v < 25


HISTORICAL_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="historical_low_percentile",
        domain=SynthesisDomain.HISTORICAL,
        inputs=("ndvi_percentile_context",),
        conditions=_historical_low_percentile,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "NDVI is at a low percentile of the reference period.  The "
            "current value ranks in the bottom quarter of the "
            "historical distribution."
        ),
        scientific_basis=(
            "The percentile context reports where the current NDVI "
            "ranks within the historical month-of-year reference "
            "population.  A percentile below 25 means the value is "
            "lower than at least 75 percent of the reference."
        ),
        limitations=(
            "A percentile is a rank within a stated reference "
            "population, not a probability.  The reference population "
            "is the historical month-of-year distribution, which may "
            "be small.",
        ),
        min_sources=1,
    ),
]

# -- Cross-domain rules ----------------------------------------------------

def _cross_water_vegetation_coherent(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Water and vegetation indicators both show below-baseline."""
    water_below = sum(
        1 for k in (
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "evapotranspiration_anomaly",
        )
        if values.get(k) is not None and values[k] < 0
    )
    veg_below = sum(
        1 for k in ("ndvi_anomaly_absolute",)
        if values.get(k) is not None and values[k] < 0
    )
    return water_below >= 2 and veg_below >= 1


def _cross_water_thermal_coherent(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """Water below baseline and thermal above baseline."""
    water_below = sum(
        1 for k in (
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
        )
        if values.get(k) is not None and values[k] < 0
    )
    thermal_above = (
        values.get("lst_day_anomaly") is not None
        and values["lst_day_anomaly"] > 0
    )
    return water_below >= 1 and thermal_above


def _cross_aridity_thermal_surface(
    evidence: Dict[str, EvidenceItem],
    values: Dict[str, Optional[float]],
) -> bool:
    """High thermal load coincides with high atmospheric aridity or low soil moisture."""
    lst_high = (
        values.get("land_surface_temperature_day") is not None
        and values["land_surface_temperature_day"] >= 40.0
    ) or (
        values.get("lst_day_anomaly") is not None
        and values["lst_day_anomaly"] > 0
    )
    arid = (
        values.get("vpd") is not None and values["vpd"] >= 2.5
    ) or (
        values.get("soil_moisture_surface") is not None
        and values["soil_moisture_surface"] < 0.10
    )
    return bool(lst_high and arid)


CROSS_DOMAIN_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="cross_water_vegetation_below",
        domain=SynthesisDomain.CROSS_DOMAIN,
        inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "evapotranspiration_anomaly",
            "ndvi_anomaly_absolute",
        ),
        required_inputs=(),
        optional_inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "evapotranspiration_anomaly",
            "ndvi_anomaly_absolute",
        ),
        min_inputs=3,
        applicable_regimes=(
            VegetationRegime.VEGETATED,
            VegetationRegime.UNCERTAIN,
        ),
        conditions=_cross_water_vegetation_coherent,
        output_pattern=PatternState.COHERENT,
        statement=(
            "Multiple water-availability and vegetation indicators show "
            "a coherent below-baseline pattern.  Precipitation, soil "
            "moisture, and/or ET are below their historical baselines, "
            "and NDVI is also below its baseline."
        ),
        scientific_basis=(
            "When independently measured water-balance terms and "
            "vegetation indices simultaneously show negative anomalies, "
            "the pattern is consistent across observation systems.  "
            "This is a descriptive observation, not a causal diagnosis."
        ),
        limitations=(
            "Coherence does not imply causation.  The pattern may "
            "reflect temporal lags, spatial resolution differences, or "
            "confounding factors.  Different sensors at different "
            "resolutions contribute to this pattern.",
            "ERA5-Land precipitation is modelled at 11 km.  SMAP soil "
            "moisture is at 9 km.  MODIS ET is at 500 m.  Sentinel-2 "
            "NDVI is at 10 m.  These are not directly comparable at "
            "field scale.",
        ),
        min_sources=2,
    ),
    SynthesisRule(
        rule_id="cross_water_thermal_opposite",
        domain=SynthesisDomain.CROSS_DOMAIN,
        inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "lst_day_anomaly",
        ),
        required_inputs=(),
        optional_inputs=(
            "precipitation_anomaly",
            "soil_moisture_rootzone_anomaly",
            "lst_day_anomaly",
        ),
        min_inputs=2,
        conditions=_cross_water_thermal_coherent,
        output_pattern=PatternState.COHERENT,
        statement=(
            "Water-availability indicators are below baseline while "
            "land surface temperature is above baseline.  Drier "
            "conditions coincide with warmer surface temperatures."
        ),
        scientific_basis=(
            "Reduced soil moisture and precipitation reduce evaporative "
            "cooling, which can increase land surface temperature.  "
            "This is a physically plausible pattern in water-limited "
            "regimes."
        ),
        limitations=(
            "LST is surface temperature, not canopy temperature.  The "
            "relationship between soil moisture and LST depends on "
            "vegetation cover, atmospheric demand, and surface "
            "properties.  In energy-limited regimes the relationship "
            "may reverse.",
        ),
        min_sources=2,
    ),
]


# ---------------------------------------------------------------------------
# 8. Regime-aware synthesis rules (Phase P-AGRI-1.6)
# ---------------------------------------------------------------------------

REGIME_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="bare_ground_surface_condition",
        domain=SynthesisDomain.VEGETATION,
        inputs=("ndvi", "land_cover_probability"),
        required_inputs=(),
        optional_inputs=("ndvi", "land_cover_probability"),
        min_inputs=1,
        applicable_regimes=(VegetationRegime.NON_VEGETATED,),
        conditions=_is_bare_ground_surface,
        output_pattern=PatternState.NEAR_CONTEXT,
        statement=(
            "Surface is classified as non-vegetated / bare ground. "
            "Optical and land cover evidence confirm minimal photosynthetic canopy. "
            "Crop canopy stress and growth interpretations are not applicable."
        ),
        scientific_basis=(
            "When NDVI is in the mineral soil/rock range (< 0.12) and baseline vegetation "
            "is absent, active photosynthetic canopy is absent. "
            "Evaluating vegetative stress without canopy presence is scientifically invalid."
        ),
        limitations=(
            "Sparse opportunistic vegetation (< 10% cover) or dry non-photosynthetic "
            "residue may not register as green canopy.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="surface_thermal_load_high",
        domain=SynthesisDomain.THERMAL,
        inputs=("land_surface_temperature_day",),
        conditions=_thermal_high_surface_temp,
        output_pattern=PatternState.ABOVE_CONTEXT,
        statement=(
            "Daytime land surface temperature is severely elevated (>= 45 °C), "
            "indicating extreme solar heating and high thermal load at the surface."
        ),
        scientific_basis=(
            "MODIS daytime LST reflects the radiometric temperature of the exposed "
            "surface under solar irradiation. Unshaded bare ground in arid climates "
            "readily exceeds 45-50 °C during summer months."
        ),
        limitations=(
            "LST measures radiometric skin temperature at ~1 km resolution, not canopy "
            "or 2-meter air temperature.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="soil_surface_desiccation",
        domain=SynthesisDomain.SOIL,
        inputs=("soil_moisture_surface", "soil_wilting_point"),
        required_inputs=(),
        optional_inputs=("soil_moisture_surface", "soil_wilting_point"),
        min_inputs=1,
        conditions=_soil_surface_desiccation,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "Topsoil moisture is below the soil permanent wilting point "
            "threshold, indicating severe topsoil desiccation."
        ),
        scientific_basis=(
            "When volumetric surface soil moisture drops below the permanent "
            "wilting point derived from soil hydraulic properties (SoilGrids), "
            "matric potential falls below -1500 kPa and moisture is tightly bound."
        ),
        limitations=(
            "SMAP L3 surface moisture retrieval represents top 5 cm at ~9 km. "
            "SoilGrids hydraulic properties are mapped at 250 m.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="soil_rootzone_model_conflict",
        domain=SynthesisDomain.SOIL,
        inputs=("soil_moisture_rootzone", "soil_moisture_rootzone_era5"),
        required_inputs=("soil_moisture_rootzone", "soil_moisture_rootzone_era5"),
        min_inputs=2,
        conditions=_soil_rootzone_model_conflict,
        output_pattern=PatternState.CONFLICTING,
        statement=(
            "Root-zone soil moisture estimates diverge substantially between "
            "assimilated satellite radiometry (SMAP L4) and atmospheric reanalysis (ERA5-Land). "
            "Significant model disagreement indicates structural uncertainty."
        ),
        scientific_basis=(
            "SMAP L4 assimilates satellite L-band brightness temperatures with NASA Catchment LSM; "
            "ERA5-Land is an open-loop model with ECMWF HTESSEL. Divergence reflects differing "
            "hydrological physics, soil layering, and pedotransfer parameterizations."
        ),
        limitations=(
            "Neither model provides in-situ ground truth; disagreement highlights "
            "uncertainty rather than proving which estimate is correct.",
        ),
        min_sources=2,
    ),
    SynthesisRule(
        rule_id="atmospheric_aridity_severe",
        domain=SynthesisDomain.CROSS_DOMAIN,
        inputs=("vpd", "rh"),
        required_inputs=(),
        optional_inputs=("vpd", "rh"),
        min_inputs=1,
        conditions=_climate_atmospheric_aridity,
        output_pattern=PatternState.ABOVE_CONTEXT,
        statement=(
            "Atmospheric evaporative demand is high with elevated vapor pressure deficit "
            "(VPD >= 3.0 kPa), indicating strong atmospheric aridity."
        ),
        scientific_basis=(
            "High vapor pressure deficit (VPD) drives steep atmospheric drying potential, "
            "accelerating evaporation from moist surfaces and increasing evaporative stress."
        ),
        limitations=(
            "ERA5-Land reanalysis is modelled at ~11 km resolution; local microclimatic "
            "boundary conditions may vary.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="cross_aridity_thermal_surface",
        domain=SynthesisDomain.CROSS_DOMAIN,
        inputs=(
            "land_surface_temperature_day",
            "vpd",
            "soil_moisture_surface",
        ),
        required_inputs=(),
        optional_inputs=(
            "land_surface_temperature_day",
            "vpd",
            "soil_moisture_surface",
            "lst_day_anomaly",
        ),
        min_inputs=2,
        conditions=_cross_aridity_thermal_surface,
        output_pattern=PatternState.COHERENT,
        statement=(
            "Elevated land surface temperature coincides with strong atmospheric demand "
            "and desiccated surface soil moisture, indicating coherent arid surface conditions."
        ),
        scientific_basis=(
            "In arid and semi-arid water-limited regimes, lack of surface moisture suppresses "
            "latent heat flux (evaporative cooling), channeling net radiation into sensible heat "
            "flux and driving elevated surface temperatures."
        ),
        limitations=(
            "Combines products at disparate resolutions (MODIS ~1 km, ERA5-Land ~11 km, SMAP ~9 km). "
            "Describes regional environmental state rather than sub-field variability.",
        ),
        min_sources=2,
    ),
]


CLIMATE_RULES: List[SynthesisRule] = [
    SynthesisRule(
        rule_id="climate_near_freezing_minimum",
        domain=SynthesisDomain.CROSS_DOMAIN,
        inputs=("temperature_min",),
        required_inputs=("temperature_min",),
        conditions=_climate_near_freezing_minimum,
        output_pattern=PatternState.BELOW_CONTEXT,
        statement=(
            "Minimum air temperature is near or below freezing, indicating potential "
            "cold-stress or frost exposure for sensitive crop phenological stages."
        ),
        scientific_basis=(
            "Numerical weather predictions (NOAA GFS) and reanalysis provide elevation-corrected 2-meter air temperature. "
            "When nocturnal temperatures drop toward 0 °C, radiation cooling and cold air drainage "
            "increase frost risk depending on crop phenology."
        ),
        limitations=(
            "Coarse-scale NWP/reanalysis requires elevation lapse-rate adjustment "
            "and local microtopography validation. Uncalibrated phenological thresholds require on-site confirmation.",
        ),
        min_sources=1,
    ),
    SynthesisRule(
        rule_id="cross_cold_air_pooling_frost_risk",
        domain=SynthesisDomain.CROSS_DOMAIN,
        inputs=("temperature_min", "cold_air_pooling_risk"),
        required_inputs=(),
        optional_inputs=("temperature_min", "cold_air_pooling_risk", "cold_air_pooling_index"),
        min_inputs=1,
        conditions=_cross_cold_air_pooling_frost_risk,
        output_pattern=PatternState.COHERENT,
        statement=(
            "Topographic cold air drainage potential coincides with near-freezing forecast temperatures, "
            "indicating elevated microclimatic frost vulnerability in lower-lying terrain features."
        ),
        scientific_basis=(
            "Nocturnal radiation cooling generates dense, cold air layers that drain into terrain depressions "
            "(katabatic flow). High cold-air-pooling convergence amplifies freezing severity beyond regional gridded forecasts."
        ),
        limitations=(
            "Topographic index derived from NASADEM (30 m). Micro-scale orchard features (windbreaks, walls, soil tillage) "
            "significantly modify local airflow.",
        ),
        min_sources=1,
    ),
]


# ---------------------------------------------------------------------------
# 9. All default rules
# ---------------------------------------------------------------------------

DEFAULT_RULES: List[SynthesisRule] = (
    WATER_RULES
    + VEGETATION_RULES
    + CANOPY_PROXY_RULES
    + THERMAL_RULES
    + SOIL_RULES
    + PHENOLOGY_RULES
    + PRODUCTIVITY_RULES
    + HISTORICAL_RULES
    + CROSS_DOMAIN_RULES
    + REGIME_RULES
)

ALL_SYNTHESIS_RULES: List[SynthesisRule] = DEFAULT_RULES + CLIMATE_RULES
CLIMATE_SYNTHESIS_RULES: List[SynthesisRule] = CLIMATE_RULES


# ---------------------------------------------------------------------------
# 10. Synthesis engine
# ---------------------------------------------------------------------------


class SynthesisEngine:
    """Deterministic, rule-based synthesis engine.

    Evaluates synthesis rules against evidence bundles and produces
    structured ``AgriculturalSynthesis`` results.  The engine is
    deterministic: identical inputs produce identical output.

    The engine does NOT:

    * Calculate new satellite metrics
    * Make causal claims
    * Produce health scores
    * Recommend actions
    * Use an LLM
    """

    def __init__(
        self,
        rules: Optional[Sequence[SynthesisRule]] = None,
    ) -> None:
        self._rules = list(rules or DEFAULT_RULES)
        self._rules_by_domain: Dict[SynthesisDomain, List[SynthesisRule]] = {}
        for rule in self._rules:
            self._rules_by_domain.setdefault(rule.domain, []).append(rule)

    @property
    def rules(self) -> List[SynthesisRule]:
        return list(self._rules)

    def evaluate_domain(
        self,
        domain: SynthesisDomain,
        evidence: EvidenceBundle,
        regime: Optional[VegetationRegime] = None,
    ) -> DomainSummary:
        """Evaluate all rules for a domain against an evidence bundle.

        Returns a ``DomainSummary`` with statements, unavailable
        evidence, sufficiency, conflicts, and limitations.
        """
        if regime is None:
            regime = classify_vegetation_regime(evidence).regime

        rules = self._rules_by_domain.get(domain, [])
        statements: List[SynthesisStatement] = []

        for rule in rules:
            stmt = _evaluate_rule(rule, evidence, regime=regime)
            if stmt is not None:
                statements.append(stmt)

        unavailable = [i.metric_key for i in evidence.unavailable_items]
        sufficiency = SufficiencyLevel.INSUFFICIENT
        if evidence.sufficiency is not None:
            sufficiency = evidence.sufficiency.level

        # Data presence is read from the bundle's own usable items,
        # never inferred from statements or sufficiency wording
        # (F-CONTRACT-FIX-1 §3).
        has_usable = len(evidence.available_items) > 0

        limitations: List[str] = []
        if sufficiency != SufficiencyLevel.SUFFICIENT:
            limitations.append(
                f"Evidence sufficiency: {sufficiency.value}."
            )
        if evidence.has_conflicts:
            limitations.append(
                f"{sum(1 for c in evidence.conflicts if c.status == ConsistencyStatus.CONFLICTING)} "
                "conflicting pair(s) detected."
            )

        return DomainSummary(
            domain=domain,
            statements=statements,
            unavailable_evidence=unavailable,
            sufficiency=sufficiency,
            conflicts=evidence.conflicts,
            limitations=limitations,
            has_usable_evidence=has_usable,
            vegetation_regime=regime.value if regime else None,
        )

    def synthesise(
        self,
        bundles: Dict[SynthesisDomain, EvidenceBundle],
        time_start: Optional[date] = None,
        time_end: Optional[date] = None,
        spatial_context: Optional[str] = None,
    ) -> AgriculturalSynthesis:
        """Run full synthesis across all domains.

        Takes a mapping of domain to evidence bundle, evaluates all
        rules, and produces a structured ``AgriculturalSynthesis``.
        """
        regime_assessment = classify_vegetation_regime(bundles)
        regime = regime_assessment.regime

        domain_summaries: Dict[SynthesisDomain, DomainSummary] = {}

        for domain, evidence in bundles.items():
            summary = self.evaluate_domain(domain, evidence, regime=regime)
            summary.vegetation_regime = regime.value
            domain_summaries[domain] = summary

        # Cross-domain synthesis
        cross_evidence = self._merge_evidence(bundles)
        cross_summary = self.evaluate_domain(
            SynthesisDomain.CROSS_DOMAIN, cross_evidence, regime=regime
        )

        # Overall sufficiency
        sufficiencies = [
            s.sufficiency for s in domain_summaries.values()
        ]
        if not sufficiencies:
            # No bundles provided: no evidence = insufficient
            overall = SufficiencyLevel.INSUFFICIENT
        elif all(s == SufficiencyLevel.SUFFICIENT for s in sufficiencies):
            overall = SufficiencyLevel.SUFFICIENT
        elif any(s == SufficiencyLevel.INSUFFICIENT for s in sufficiencies):
            overall = SufficiencyLevel.INSUFFICIENT
        else:
            overall = SufficiencyLevel.LIMITED

        limitations: List[str] = []
        for domain, summary in domain_summaries.items():
            # Two distinct structural facts stay machine-readable
            # (F-CONTRACT-FIX-1 §5): "no synthesis rule fired" (a
            # statement gap) and "no usable evidence exists" (a data
            # gap).  A domain with usable data but no statement gets
            # only the statement-gap line; a data-less domain gets the
            # data-gap line instead, which is the more precise
            # diagnosis.  No scientific conclusion is drawn either way.
            if not summary.has_usable_evidence:
                limitations.append(
                    f"No usable evidence for {domain.value}."
                )
            elif not summary.has_statements:
                limitations.append(
                    f"No synthesis rules fired for {domain.value}."
                )

        return AgriculturalSynthesis(
            time_start=time_start,
            time_end=time_end,
            spatial_context=spatial_context,
            domain_summaries=domain_summaries,
            overall_sufficiency=overall,
            cross_domain_statements=cross_summary.statements,
            limitations=limitations,
            metadata={
                "rule_count": str(len(self._rules)),
                "domains_evaluated": str(len(bundles)),
                "vegetation_regime": regime.value,
                "regime_confidence": regime_assessment.confidence,
                "regime_explanation": regime_assessment.explanation,
            },
            vegetation_regime=regime.value,
        )

    def _merge_evidence(
        self,
        bundles: Dict[SynthesisDomain, EvidenceBundle],
    ) -> EvidenceBundle:
        """Merge all domain bundles into one for cross-domain rules."""
        all_items: List[EvidenceItem] = []
        all_conflicts: List[EvidenceConflict] = []
        for evidence in bundles.values():
            all_items.extend(evidence.items)
            all_conflicts.extend(evidence.conflicts)
        merged = EvidenceBundle(
            name="cross_domain",
            items=all_items,
            conflicts=all_conflicts,
        )
        merged.assess_sufficiency()
        return merged
