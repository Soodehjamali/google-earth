"""Vegetation Regime Gate (Phase P-AGRI-1.1).

Classifies the dominant surface state into:
1. VEGETATED: Active photosynthetically active crop or canopy presence.
2. NON_VEGETATED: Bare mineral soil, rock, sand, fallow, or built surface.
3. UNCERTAIN: Insufficient, conflicting, or borderline evidence.

Design principles:
- Reusable, deterministic, seed-independent.
- Does not rely on a single hardcoded threshold; integrates optical indices
  (NDVI, SAVI, EVI), Dynamic World land-cover probabilities, and radar
  depolarization context.
- Explicitly handles missing or masked inputs gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.services.agriculture.evidence import EvidenceBundle, EvidenceItem


class VegetationRegime(str, Enum):
    """Classified vegetation regime."""

    VEGETATED = "vegetated"
    NON_VEGETATED = "non_vegetated"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class RegimeAssessment:
    """Detailed assessment of the vegetation regime."""

    regime: VegetationRegime
    confidence: str  # "high", "moderate", "low"
    basis_metrics: Tuple[str, ...]
    basis_values: Dict[str, Optional[float]]
    explanation: str
    limitations: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Scientific Thresholds (Documented agronomic and remote-sensing standards)
# ---------------------------------------------------------------------------

# In optical remote sensing (Copernicus / Sentinel-2 / Landsat):
# NDVI < 0.10 represents bare soil, rock, sand, and non-vegetated terrain.
# NDVI >= 0.20 represents unambiguous active photosynthetic canopy.
# 0.10 <= NDVI < 0.20 represents sparse rangeland, early emergence, or mixed soil.
NDVI_BARE_UPPER_BOUND: float = 0.10
NDVI_VEG_LOWER_BOUND: float = 0.20

# Soil-adjusted indices (SAVI, EVI) account for soil brightness:
SAVI_BARE_UPPER_BOUND: float = 0.08
SAVI_VEG_LOWER_BOUND: float = 0.15

# Dynamic World (10 m global land cover near-real-time model):
# Bare ground probability >= 0.40 with crops/trees < 0.10 strongly corroborates bare soil.
DW_BARE_DOMINANT_PROB: float = 0.40
DW_CROP_PRESENCE_PROB: float = 0.15

# Sentinel-1 C-band SAR:
# Cross-polarization VH is driven by volume scattering from canopy structure.
# VH < -15.0 dB and VH/VV < -6.5 dB characterize smooth/bare surface scattering.
RADAR_VH_BARE_MAX_DB: float = -15.0
RADAR_VH_VEG_MIN_DB: float = -14.0


def _extract_values_from_bundles(
    bundles: Mapping[Any, EvidenceBundle],
) -> Dict[str, float]:
    """Extract finite usable numeric values across all domain bundles."""
    values: Dict[str, float] = {}
    for bundle in bundles.values():
        if not bundle or not hasattr(bundle, "available_items"):
            continue
        for item in bundle.available_items:
            if (
                item
                and item.metric_key
                and item.value is not None
                and isinstance(item.value, (int, float))
            ):
                values[item.metric_key] = float(item.value)
    return values


def _extract_values_from_items(
    items: Sequence[EvidenceItem],
) -> Dict[str, float]:
    """Extract finite usable numeric values from an items sequence."""
    values: Dict[str, float] = {}
    for item in items:
        if (
            item
            and item.metric_key
            and item.value is not None
            and isinstance(item.value, (int, float))
        ):
            values[item.metric_key] = float(item.value)
    return values


def classify_vegetation_regime(
    evidence: Any,
) -> RegimeAssessment:
    """Classify the vegetation regime from available evidence.

    Accepts:
    - Mapping[SynthesisDomain, EvidenceBundle]
    - Sequence[EvidenceItem]
    - Dict[str, float]
    """
    if isinstance(evidence, Mapping) and all(
        isinstance(v, (int, float)) for v in evidence.values()
    ):
        values = {k: float(v) for k, v in evidence.items()}
    elif isinstance(evidence, Mapping):
        values = _extract_values_from_bundles(evidence)
    elif isinstance(evidence, Sequence):
        values = _extract_values_from_items(evidence)
    else:
        values = {}

    basis_metrics: List[str] = []
    basis_values: Dict[str, Optional[float]] = {}

    ndvi = values.get("ndvi")
    savi = values.get("savi")
    evi = values.get("evi")
    msavi = values.get("msavi")
    dw_prob = values.get("land_cover_probability")
    vh = values.get("vh")
    vh_vv = values.get("vh_vv")
    rvi = values.get("rvi")

    for k in ("ndvi", "savi", "evi", "msavi", "land_cover_probability", "vh", "vh_vv", "rvi"):
        if k in values:
            basis_metrics.append(k)
            basis_values[k] = values[k]

    # Case 0: No vegetation indicators present at all
    if ndvi is None and savi is None and evi is None and msavi is None and dw_prob is None:
        return RegimeAssessment(
            regime=VegetationRegime.UNCERTAIN,
            confidence="low",
            basis_metrics=tuple(basis_metrics),
            basis_values=basis_values,
            explanation=(
                "No optical or land-cover vegetation metrics are available in the "
                "evidence; vegetation regime cannot be determined."
            ),
            limitations=("Assessment deferred due to missing vegetation inputs.",),
        )

    # 1. Evidence of NON_VEGETATED / BARE_GROUND
    bare_signals: List[str] = []
    veg_signals: List[str] = []

    if ndvi is not None:
        if ndvi < NDVI_BARE_UPPER_BOUND:
            bare_signals.append(f"NDVI {ndvi:.4f} < {NDVI_BARE_UPPER_BOUND}")
        elif ndvi >= NDVI_VEG_LOWER_BOUND:
            veg_signals.append(f"NDVI {ndvi:.4f} >= {NDVI_VEG_LOWER_BOUND}")

    if savi is not None:
        if savi < SAVI_BARE_UPPER_BOUND:
            bare_signals.append(f"SAVI {savi:.4f} < {SAVI_BARE_UPPER_BOUND}")
        elif savi >= SAVI_VEG_LOWER_BOUND:
            veg_signals.append(f"SAVI {savi:.4f} >= {SAVI_VEG_LOWER_BOUND}")

    if evi is not None:
        if evi < SAVI_BARE_UPPER_BOUND:
            bare_signals.append(f"EVI {evi:.4f} < {SAVI_BARE_UPPER_BOUND}")
        elif evi >= SAVI_VEG_LOWER_BOUND:
            veg_signals.append(f"EVI {evi:.4f} >= {SAVI_VEG_LOWER_BOUND}")

    if dw_prob is not None:
        # If land_cover_probability is available, it reflects the highest mean class
        # (in our pipeline bare probability when dominant class is bare).
        if dw_prob >= DW_BARE_DOMINANT_PROB:
            bare_signals.append(f"Dynamic World bare class probability {dw_prob:.2f}")

    if vh is not None and vh < RADAR_VH_BARE_MAX_DB:
        bare_signals.append(f"Sentinel-1 VH backscatter {vh:.2f} dB (surface scattering)")
    elif vh is not None and vh >= RADAR_VH_VEG_MIN_DB:
        veg_signals.append(f"Sentinel-1 VH backscatter {vh:.2f} dB (canopy volume scattering)")

    # Decision tree:
    # A. Decisive Non-Vegetated
    if len(bare_signals) >= 1 and len(veg_signals) == 0:
        conf = "high" if len(bare_signals) >= 2 else "moderate"
        signals_text = ", ".join(bare_signals)
        return RegimeAssessment(
            regime=VegetationRegime.NON_VEGETATED,
            confidence=conf,
            basis_metrics=tuple(basis_metrics),
            basis_values=basis_values,
            explanation=(
                f"Surface is classified as NON_VEGETATED / BARE_GROUND based on: {signals_text}. "
                "No active photosynthetically active crop canopy is present."
            ),
            limitations=(
                "Sparse vegetation (< 10% ground cover) or non-photosynthetic crop residue "
                "may share bare soil spectral signatures.",
            ),
        )

    # B. Decisive Vegetated
    if len(veg_signals) >= 1 and len(bare_signals) == 0:
        conf = "high" if len(veg_signals) >= 2 else "moderate"
        signals_text = ", ".join(veg_signals)
        return RegimeAssessment(
            regime=VegetationRegime.VEGETATED,
            confidence=conf,
            basis_metrics=tuple(basis_metrics),
            basis_values=basis_values,
            explanation=(
                f"Surface is classified as VEGETATED based on: {signals_text}. "
                "Active canopy presence is established."
            ),
            limitations=(
                "Vegetation signal reflects all green canopy in the footprint (weeds, cover crops, "
                "perennials, trees) and does not identify a specific commercial crop species.",
            ),
        )

    # C. Mixed or Transition
    if len(bare_signals) > 0 and len(veg_signals) > 0:
        return RegimeAssessment(
            regime=VegetationRegime.UNCERTAIN,
            confidence="low",
            basis_metrics=tuple(basis_metrics),
            basis_values=basis_values,
            explanation=(
                f"Mixed signals observed between bare ground ({', '.join(bare_signals)}) "
                f"and vegetation ({', '.join(veg_signals)}). Regime is UNCERTAIN."
            ),
            limitations=(
                "Surface may feature heterogeneous patchwork, emerging crop rows, or mixed vegetation.",
            ),
        )

    # D. Intermediate with no decisive threshold crossings
    return RegimeAssessment(
        regime=VegetationRegime.UNCERTAIN,
        confidence="low",
        basis_metrics=tuple(basis_metrics),
        basis_values=basis_values,
        explanation=(
            "Vegetation indices sit in the intermediate sparse/transitional range "
            f"(NDVI={ndvi} if present); canopy presence cannot be established with confidence."
        ),
        limitations=("Conservative gating applied to suppress unverified canopy conclusions.",),
    )
