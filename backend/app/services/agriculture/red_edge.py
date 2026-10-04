"""Red-edge diagnostics foundation (P2.2).

A small, reusable diagnostics layer on top of the P2.1 spectral
observations.  It describes red-edge spectral behavior only: how
reflectance changes across the red / red-edge / narrow-NIR bands
within one window, and how those descriptors move between
consecutive monthly windows.  This layer performs no cause
attribution of any kind.

Sentinel-2 MSI records discrete multispectral samples, not
hyperspectral measurements.  Every diagnostic below is computed
directly from the stated discrete bands at their documented centre
wavelengths.  No intermediate wavelengths are invented and no
inflection fitting is performed.

A red-edge response may be associated with many possible factors,
including chlorophyll variation, phenology, water stress, canopy
structure, soil and background effects, management,
atmospheric or residual processing effects, or biological stress.
Red-edge diagnostics therefore describe spectral and vegetation
response, never cause.  This phase must not identify pests or
diseases, and no single red-edge metric here may be read as a
diagnosis.

Reused machinery (nothing re-derived):

* P2.1 observation types, band tables, wavelength and resolution
  metadata, status vocabulary, and reflectance convention
  (:mod:`app.services.agriculture.spectral_profile`);
* the production Sentinel-2 masking/composite/scaling path is NOT
  repeated here: diagnostics consume finished
  :class:`SpectralObservation` / :class:`SpectralProfile` objects,
  however they were built;
* normalized differences via
  :func:`app.services.agriculture.indices.safe_normalized_difference`
  (missing, non-finite, and zero-denominator inputs yield ``None``);
* month-to-month direction labels via
  :func:`app.services.agriculture.change_profile.classify_direction`
  with no reference spread (exact-zero steps read STABLE, signed
  steps read INCREASE/DECREASE, missing steps read INSUFFICIENT) —
  the P1.3 change semantics, not a second change system.  The
  spread-relative STABLE band and rapid flags are deliberately not
  reused: no reference spread exists at this layer, so there is
  nothing to compare a step against;
* the P1.2 historical hook is structural: per-diagnostic series keep
  ``(window, value, quality, coverage, image_count)`` order, and
  :func:`to_temporal_profile` adapts one diagnostic series to a
  :class:`TemporalProfile` the generic P1.2 baseline machinery can
  consume later.  No baseline arithmetic is implemented here.

Diagnostics implemented (deterministic order):

* ``re_slope_b4_b5``, ``re_slope_b5_b6``, ``re_slope_b6_b7``,
  ``re_slope_b7_b8a`` — wavelength-aware slopes
  ``(r2 - r1) / (wl2 - wl1)`` in reflectance per nanometre.
* ``re_nd_b6_b5``, ``re_nd_b7_b5`` — normalized differences
  between red-edge bands (dimensionless).
* ``re_nd_b8a_b5`` — red-edge-to-NIR contrast against the narrow
  NIR band (dimensionless).  B8A is used rather than B8 because it
  shares the 20 m grid of the red-edge bands, so no resampling
  choice is hidden; the registered NDRE metric already covers the
  B8/B5 pair and is not duplicated here.

Deliberately not implemented: a red-edge position proxy.  Locating
an inflection between the discrete 705/740/783 nm samples would
require interpolation or curve fitting that the samples do not
support, so it is refused rather than invented.

Missing data: every diagnostic identifier is present for every
month.  Unusable inputs yield ``value=None`` with an explicit
status — ``"unavailable"`` when the window was never attempted,
``"insufficient"`` when inputs were attempted but missing or the
computation is undefined.  Nothing is zero-filled, nothing is
interpolated, and no input band is silently dropped.

Temporal behavior: one diagnostic set per month in chronological
order; change is exposed only against the exact preceding monthly
observation when both months carry finite values for that
diagnostic, otherwise the change reads INSUFFICIENT.  This is
stricter than the P1.3 gap allowance on purpose: diagnostic steps
never bridge an unobserved month.

Non-goals of this phase: cause attribution, cut-off values of any
kind, probabilistic or risk scoring, model inference, thermal or
radar inputs, new datasets, endpoints, charts, and cache changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.logging import get_logger
from app.services.agriculture.change_profile import (
    DIRECTION_DECREASE,
    DIRECTION_INCREASE,
    DIRECTION_INSUFFICIENT,
    DIRECTION_STABLE,
    classify_direction,
)
from app.services.agriculture.indices import safe_normalized_difference
from app.services.agriculture.spectral_profile import (
    COMPOSITE_METHOD,
    S2_BAND_WAVELENGTH_NM,
    S2_DATASET_ID,
    SPECTRAL_UNIT,
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT,
    STATUS_UNAVAILABLE,
    STEP_CALENDAR_MONTH,
    SpectralObservation,
    SpectralProfile,
)
from app.services.agriculture.temporal_profile import (
    TemporalProfile,
    TemporalProfilePoint,
)

logger = get_logger(__name__)

__all__ = [
    "RED_EDGE_INPUT_BANDS",
    "RED_EDGE_DIAGNOSTIC_IDS",
    "RED_EDGE_DIAGNOSTIC_SPECS",
    "SLOPE_UNIT",
    "INDEX_UNIT",
    "RED_EDGE_SLOPE_PAIRS",
    "RED_EDGE_NORMALIZED_IDS",
    "RedEdgeDiagnostic",
    "RedEdgeObservationDiagnostics",
    "RedEdgeChange",
    "RedEdgeSeries",
    "red_edge_slope",
    "compute_red_edge_diagnostics",
    "analyze_red_edge_series",
    "diagnostic_series",
    "to_temporal_profile",
]

#: Bands this layer reads, in wavelength order.  B8 (broad NIR,
#: 842 nm, 10 m) is intentionally absent: the narrow NIR band B8A
#: shares the 20 m grid of the red-edge bands, and the B8/B5 pair is
#: already served by the registered NDRE metric.
RED_EDGE_INPUT_BANDS: Tuple[str, ...] = ("B4", "B5", "B6", "B7", "B8A")

#: Slope pairs in wavelength order.  B7 to B8A spans B8 without
#: using it: the slope is a direct two-point descriptor, not a
#: fitted curve, so no intermediate band is implied.
RED_EDGE_SLOPE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("B4", "B5"),
    ("B5", "B6"),
    ("B6", "B7"),
    ("B7", "B8A"),
)

#: Unit for wavelength-aware slopes.
SLOPE_UNIT = "reflectance/nm"

#: Unit for normalized differences.  Matches the repository's index
#: unit convention for dimensionless spectral contrasts.
INDEX_UNIT = "index"


def _slope_id(first: str, second: str) -> str:
    return f"re_slope_{first.lower()}_{second.lower()}"


def _slope_formula(first: str, second: str) -> str:
    wl_first = S2_BAND_WAVELENGTH_NM[first]
    wl_second = S2_BAND_WAVELENGTH_NM[second]
    return f"({second} - {first}) / ({wl_second:g} - {wl_first:g})"


def _nd_id(high: str, low: str) -> str:
    return f"re_nd_{high.lower()}_{low.lower()}"


def _nd_formula(high: str, low: str) -> str:
    return f"({high} - {low}) / ({high} + {low})"


#: Canonical diagnostic registry, in emission order.  Each entry
#: states the computation kind, the exact input bands, the explicit
#: formula, the unit, and neutral limitations.  Directions and
#: states defined anywhere else in this module are limited to the
#: P1.3 direction labels.
RED_EDGE_DIAGNOSTIC_SPECS: Dict[str, Dict[str, Any]] = {
    _slope_id("B4", "B5"): {
        "kind": "slope",
        "inputs": ("B4", "B5"),
        "formula": _slope_formula("B4", "B5"),
        "unit": SLOPE_UNIT,
        "description": (
            "Reflectance change per nanometre from red (665 nm) to "
            "red edge 1 (705 nm)."
        ),
        "limitations": (
            "B4 is acquired at 10 m while B5 is acquired at 20 m; "
            "this slope combines different native resolutions.",
            "Discrete two-point descriptor; no values between the "
            "stated wavelengths are implied.",
        ),
    },
    _slope_id("B5", "B6"): {
        "kind": "slope",
        "inputs": ("B5", "B6"),
        "formula": _slope_formula("B5", "B6"),
        "unit": SLOPE_UNIT,
        "description": (
            "Reflectance change per nanometre from red edge 1 "
            "(705 nm) to red edge 2 (740 nm)."
        ),
        "limitations": (
            "Discrete two-point descriptor; no values between the "
            "stated wavelengths are implied.",
        ),
    },
    _slope_id("B6", "B7"): {
        "kind": "slope",
        "inputs": ("B6", "B7"),
        "formula": _slope_formula("B6", "B7"),
        "unit": SLOPE_UNIT,
        "description": (
            "Reflectance change per nanometre from red edge 2 "
            "(740 nm) to red edge 3 (783 nm)."
        ),
        "limitations": (
            "Discrete two-point descriptor; no values between the "
            "stated wavelengths are implied.",
        ),
    },
    _slope_id("B7", "B8A"): {
        "kind": "slope",
        "inputs": ("B7", "B8A"),
        "formula": _slope_formula("B7", "B8A"),
        "unit": SLOPE_UNIT,
        "description": (
            "Reflectance change per nanometre from red edge 3 "
            "(783 nm) to narrow NIR (865 nm)."
        ),
        "limitations": (
            "Direct two-point descriptor across the B8 position; "
            "B8 itself is not an input and nothing about it is "
            "implied.",
            "Discrete two-point descriptor; no values between the "
            "stated wavelengths are implied.",
        ),
    },
    _nd_id("B6", "B5"): {
        "kind": "normalized_difference",
        "inputs": ("B6", "B5"),
        "formula": _nd_formula("B6", "B5"),
        "unit": INDEX_UNIT,
        "description": (
            "Normalized difference between red edge 2 and red edge 1."
        ),
        "limitations": (
            "Both inputs share the 20 m grid.",
            "Undefined when the two reflectances sum to zero; "
            "reported as missing, never as zero.",
        ),
    },
    _nd_id("B7", "B5"): {
        "kind": "normalized_difference",
        "inputs": ("B7", "B5"),
        "formula": _nd_formula("B7", "B5"),
        "unit": INDEX_UNIT,
        "description": (
            "Normalized difference spanning the red edge, red edge 3 "
            "against red edge 1."
        ),
        "limitations": (
            "Both inputs share the 20 m grid.",
            "Undefined when the two reflectances sum to zero; "
            "reported as missing, never as zero.",
        ),
    },
    _nd_id("B8A", "B5"): {
        "kind": "normalized_difference",
        "inputs": ("B8A", "B5"),
        "formula": _nd_formula("B8A", "B5"),
        "unit": INDEX_UNIT,
        "description": (
            "Red-edge-to-NIR contrast: narrow NIR against red edge 1."
        ),
        "limitations": (
            "Both inputs share the 20 m grid.",
            "Distinct from the registered NDRE metric, which pairs "
            "B8 (broad NIR, 10 m) with B5.",
            "Undefined when the two reflectances sum to zero; "
            "reported as missing, never as zero.",
        ),
    },
}

#: Emission order for every monthly diagnostic set.
RED_EDGE_DIAGNOSTIC_IDS: Tuple[str, ...] = tuple(
    RED_EDGE_DIAGNOSTIC_SPECS
)

#: Identifiers of the normalized-difference diagnostics.
RED_EDGE_NORMALIZED_IDS: Tuple[str, ...] = tuple(
    identifier
    for identifier, spec in RED_EDGE_DIAGNOSTIC_SPECS.items()
    if spec["kind"] == "normalized_difference"
)


# --------------------------------------------------------------------------
# Representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RedEdgeDiagnostic:
    """One red-edge diagnostic value for one window.

    A missing diagnostic is ``value=None`` with status
    ``"insufficient"`` (inputs attempted but unusable or the
    computation undefined) or ``"unavailable"`` (the window was
    never attempted).  Missing is structural.
    """

    diagnostic_id: str
    formula: str
    input_bands: Tuple[str, ...]
    wavelengths_nm: Tuple[float, ...]
    value: Optional[float]
    unit: str
    window_start: str
    window_end: str
    quality: str
    coverage_percent: Optional[float]
    image_count: Optional[int]
    dataset_id: str
    status: str = STATUS_UNAVAILABLE
    limitations: Tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        """Whether this diagnostic carries a finite value."""
        return (
            self.status == STATUS_AVAILABLE
            and self.value is not None
            and math.isfinite(self.value)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.2 API contract models."""
        return {
            "diagnostic_id": self.diagnostic_id,
            "formula": self.formula,
            "input_bands": list(self.input_bands),
            "wavelengths_nm": list(self.wavelengths_nm),
            "value": self.value,
            "unit": self.unit,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "dataset_id": self.dataset_id,
            "status": self.status,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class RedEdgeObservationDiagnostics:
    """One month's full red-edge diagnostic set.

    Exactly one entry per registered diagnostic identifier, always
    in registry order, each naming the window it belongs to so the
    band-to-time relationship of the source observation survives.
    """

    window_start: str
    window_end: str
    dataset_id: str
    quality: str
    coverage_percent: Optional[float]
    image_count: Optional[int]
    diagnostics: Tuple[RedEdgeDiagnostic, ...] = field(
        default_factory=tuple
    )
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def diagnostic_order(self) -> Tuple[str, ...]:
        """Registered identifiers, in emission order."""
        return tuple(item.diagnostic_id for item in self.diagnostics)

    @property
    def n_available(self) -> int:
        """Diagnostics carrying a finite value."""
        return sum(1 for item in self.diagnostics if item.is_available)

    def diagnostic(self, diagnostic_id: str) -> RedEdgeDiagnostic:
        """Return one diagnostic, raising a clear error if absent."""
        for item in self.diagnostics:
            if item.diagnostic_id == diagnostic_id:
                return item
        available = ", ".join(self.diagnostic_order) or "(none)"
        raise KeyError(
            f"Diagnostic {diagnostic_id!r} is not part of this "
            f"observation. Available diagnostics: {available}."
        )

    def diagnostic_provenance(
        self, diagnostic_id: str
    ) -> Dict[str, Any]:
        """Derivation record for one diagnostic value."""
        item = self.diagnostic(diagnostic_id)
        payload = dict(self.provenance)
        payload.update(
            {
                "diagnostic_id": item.diagnostic_id,
                "formula": item.formula,
                "input_bands": list(item.input_bands),
                "wavelengths_nm": list(item.wavelengths_nm),
                "unit": item.unit,
                "status": item.status,
                "limitations": list(item.limitations),
            }
        )
        return payload

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.2 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "dataset_id": self.dataset_id,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
            "image_count": self.image_count,
            "diagnostics": [
                {
                    **item.to_dict(),
                    "provenance": self.diagnostic_provenance(
                        item.diagnostic_id
                    ),
                }
                for item in self.diagnostics
            ],
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RedEdgeChange:
    """One diagnostic's step between consecutive monthly windows.

    Directions reuse the P1.3 labels (INCREASE / DECREASE / STABLE /
    INSUFFICIENT) with the no-spread convention: only an exact zero
    step reads STABLE.  A step is exposed only against the exact
    preceding monthly observation when both months carry finite
    values; otherwise every numeric field is ``None`` and the
    direction reads INSUFFICIENT.
    """

    diagnostic_id: str
    unit: str
    window_start: str
    window_end: str
    previous_window_start: Optional[str]
    previous_window_end: Optional[str]
    value: Optional[float]
    previous_value: Optional[float]
    absolute_change: Optional[float]
    relative_change: Optional[float]
    days_elapsed: Optional[int]
    rate_per_day: Optional[float]
    direction: str = DIRECTION_INSUFFICIENT

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.2 API contract models."""
        return {
            "diagnostic_id": self.diagnostic_id,
            "unit": self.unit,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "previous_window_start": self.previous_window_start,
            "previous_window_end": self.previous_window_end,
            "value": self.value,
            "previous_value": self.previous_value,
            "absolute_change": self.absolute_change,
            "relative_change": self.relative_change,
            "days_elapsed": self.days_elapsed,
            "rate_per_day": self.rate_per_day,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class RedEdgeSeries:
    """Monthly red-edge diagnostics with consecutive-month steps.

    The container a later historical comparison can consume:
    ``diagnostic_series`` yields band-agnostic ``(window, value,
    quality, coverage, image_count)`` rows per diagnostic, and
    :func:`to_temporal_profile` adapts one diagnostic to the generic
    P1.2 profile shape.  No baseline arithmetic lives here.
    """

    diagnostic_ids: Tuple[str, ...]
    dataset_id: str
    window_start: str
    window_end: str
    step: str = STEP_CALENDAR_MONTH
    monthly: Tuple[RedEdgeObservationDiagnostics, ...] = field(
        default_factory=tuple
    )
    changes: Tuple[RedEdgeChange, ...] = field(default_factory=tuple)

    @property
    def n_months(self) -> int:
        """Total months emitted, including missing ones."""
        return len(self.monthly)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.2 API contract models."""
        return {
            "diagnostic_ids": list(self.diagnostic_ids),
            "dataset_id": self.dataset_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "monthly": [entry.to_dict() for entry in self.monthly],
            "changes": [change.to_dict() for change in self.changes],
        }


# --------------------------------------------------------------------------
# Pure computation (no Earth Engine)
# --------------------------------------------------------------------------


def _is_usable_number(value: Any) -> bool:
    """Finite numbers only: None, NaN, infinities, and bools are gaps."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _clean_coverage(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def red_edge_slope(
    first_value: Optional[float],
    second_value: Optional[float],
    first_band: str,
    second_band: str,
) -> Optional[float]:
    """Wavelength-aware slope between two discrete band samples.

    ``(second - first) / (wavelength_2 - wavelength_1)`` using the
    documented centre wavelengths.  Returns ``None`` for missing
    ends; the wavelength run is a positive constant by registry
    construction, so no division guard beyond input validity is
    needed.  No intermediate wavelengths are invented.
    """
    if not _is_usable_number(first_value):
        return None
    if not _is_usable_number(second_value):
        return None
    run = (
        S2_BAND_WAVELENGTH_NM[second_band]
        - S2_BAND_WAVELENGTH_NM[first_band]
    )
    if run == 0:
        return None
    assert first_value is not None and second_value is not None
    return (float(second_value) - float(first_value)) / run


def _sample_value(
    observation: SpectralObservation, band: str
) -> Optional[float]:
    try:
        sample = observation.sample(band)
    except KeyError:
        return None
    return float(sample.value) if _is_usable_number(sample.value) else None


def _build_diagnostic(
    observation: SpectralObservation,
    diagnostic_id: str,
    values: Mapping[str, Optional[float]],
) -> RedEdgeDiagnostic:
    spec = RED_EDGE_DIAGNOSTIC_SPECS[diagnostic_id]
    inputs = spec["inputs"]
    wavelengths = tuple(S2_BAND_WAVELENGTH_NM[band] for band in inputs)

    if observation.quality == STATUS_UNAVAILABLE:
        status = STATUS_UNAVAILABLE
        computed: Optional[float] = None
    elif any(values.get(band) is None for band in inputs):
        status = STATUS_INSUFFICIENT
        computed = None
    else:
        first, second = inputs[0], inputs[1]
        first_value = values[first]
        second_value = values[second]
        assert first_value is not None and second_value is not None
        if spec["kind"] == "slope":
            computed = red_edge_slope(
                first_value, second_value, first, second
            )
        else:
            # Inputs are stored in formula order (high, low), so
            # (first - second) / (first + second) reproduces the
            # stated normalized difference exactly.
            computed = safe_normalized_difference(
                first_value, second_value
            )
        if computed is None or not _is_usable_number(computed):
            status = STATUS_INSUFFICIENT
            computed = None
        else:
            status = STATUS_AVAILABLE
            computed = float(computed)

    return RedEdgeDiagnostic(
        diagnostic_id=diagnostic_id,
        formula=spec["formula"],
        input_bands=tuple(inputs),
        wavelengths_nm=wavelengths,
        value=computed,
        unit=spec["unit"],
        window_start=observation.window_start,
        window_end=observation.window_end,
        quality=observation.quality,
        coverage_percent=_clean_coverage(observation.coverage_percent),
        image_count=observation.image_count,
        dataset_id=observation.dataset_id,
        status=status,
        limitations=tuple(spec["limitations"]),
    )


def compute_red_edge_diagnostics(
    observation: SpectralObservation,
) -> RedEdgeObservationDiagnostics:
    """Describe one window's red-edge behavior.

    Reads the finished P2.1 observation — its band values, quality,
    coverage, image count, and dataset — and emits every registered
    diagnostic in registry order, each carrying the window it
    belongs to.  Invalid or missing inputs become explicit missing
    diagnostics; the identifier set is never reduced.
    """
    values = {
        band: _sample_value(observation, band)
        for band in RED_EDGE_INPUT_BANDS
    }
    diagnostics = tuple(
        _build_diagnostic(observation, diagnostic_id, values)
        for diagnostic_id in RED_EDGE_DIAGNOSTIC_IDS
    )
    provenance = dict(observation.provenance_payload())
    provenance["diagnostic_ids"] = list(RED_EDGE_DIAGNOSTIC_IDS)
    provenance["processing"] = COMPOSITE_METHOD
    return RedEdgeObservationDiagnostics(
        window_start=observation.window_start,
        window_end=observation.window_end,
        dataset_id=observation.dataset_id,
        quality=observation.quality,
        coverage_percent=_clean_coverage(observation.coverage_percent),
        image_count=observation.image_count,
        diagnostics=diagnostics,
        provenance=provenance,
    )


def _days_between(earlier: str, later: str) -> Optional[int]:
    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except (ValueError, TypeError):
        return None


def _change_for(
    diagnostic_id: str,
    unit: str,
    current: RedEdgeObservationDiagnostics,
    previous: Optional[RedEdgeObservationDiagnostics],
) -> RedEdgeChange:
    """Step of one diagnostic against its exact predecessor.

    ``previous`` is the chronologically adjacent monthly entry, or
    ``None`` for the first month.  A step is exposed only when both
    months carry finite values; anything else reads INSUFFICIENT
    with null numeric fields, so no step ever bridges an unobserved
    month.
    """
    value = current.diagnostic(diagnostic_id).value
    previous_value = (
        previous.diagnostic(diagnostic_id).value
        if previous is not None
        else None
    )
    if not _is_usable_number(value) or not _is_usable_number(
        previous_value
    ):
        return RedEdgeChange(
            diagnostic_id=diagnostic_id,
            unit=unit,
            window_start=current.window_start,
            window_end=current.window_end,
            previous_window_start=(
                previous.window_start if previous is not None else None
            ),
            previous_window_end=(
                previous.window_end if previous is not None else None
            ),
            value=float(value) if _is_usable_number(value) else None,
            previous_value=(
                float(previous_value)
                if _is_usable_number(previous_value)
                else None
            ),
            absolute_change=None,
            relative_change=None,
            days_elapsed=None,
            rate_per_day=None,
            direction=DIRECTION_INSUFFICIENT,
        )
    assert value is not None and previous_value is not None
    absolute = float(value) - float(previous_value)
    relative: Optional[float] = None
    if float(previous_value) != 0.0:
        relative = absolute / abs(float(previous_value))
    days: Optional[int] = None
    rate: Optional[float] = None
    if previous is not None:
        days = _days_between(
            previous.window_start, current.window_start
        )
        if days is not None and days > 0:
            rate = absolute / days
    return RedEdgeChange(
        diagnostic_id=diagnostic_id,
        unit=unit,
        window_start=current.window_start,
        window_end=current.window_end,
        previous_window_start=(
            previous.window_start if previous is not None else None
        ),
        previous_window_end=(
            previous.window_end if previous is not None else None
        ),
        value=float(value),
        previous_value=float(previous_value),
        absolute_change=absolute,
        relative_change=relative,
        days_elapsed=days,
        rate_per_day=rate,
        direction=classify_direction(absolute),
    )


#: Band set a spectral profile is expected to carry for red-edge
#: work.  Used only as a debug aid below: a profile with a subset
#: still yields explicit per-diagnostic missing states, never an
#: error, so this is documentation, not a gate.
SUPPORTED_PROFILE_BANDS_GUARD: Tuple[str, ...] = RED_EDGE_INPUT_BANDS


def analyze_red_edge_series(
    profile: SpectralProfile,
) -> RedEdgeSeries:
    """Describe every month of a spectral profile in red-edge terms.

    Each monthly observation keeps its own diagnostic set in
    chronological order; each month's steps compare only against
    the exact preceding monthly entry.  Missing months stay
    missing, and their neighbours' steps read INSUFFICIENT rather
    than reaching across them.
    """
    if set(profile.band_set) != set(SUPPORTED_PROFILE_BANDS_GUARD):
        logger.debug(
            "Red-edge series over band set %s; diagnostics name "
            "only the bands they read.",
            sorted(profile.band_set),
        )
    monthly = tuple(
        compute_red_edge_diagnostics(observation)
        for observation in profile.observations
    )
    units = {
        identifier: RED_EDGE_DIAGNOSTIC_SPECS[identifier]["unit"]
        for identifier in RED_EDGE_DIAGNOSTIC_IDS
    }
    changes: List[RedEdgeChange] = []
    for index, current in enumerate(monthly):
        previous = monthly[index - 1] if index > 0 else None
        for diagnostic_id in RED_EDGE_DIAGNOSTIC_IDS:
            changes.append(
                _change_for(
                    diagnostic_id, units[diagnostic_id], current, previous
                )
            )
    return RedEdgeSeries(
        diagnostic_ids=RED_EDGE_DIAGNOSTIC_IDS,
        dataset_id=profile.dataset_id or S2_DATASET_ID,
        window_start=profile.window_start,
        window_end=profile.window_end,
        step=profile.step,
        monthly=monthly,
        changes=tuple(changes),
    )


# --------------------------------------------------------------------------
# Historical comparison hook (alignment helpers, no arithmetic)
# --------------------------------------------------------------------------


def diagnostic_series(
    series: RedEdgeSeries, diagnostic_id: str
) -> List[Dict[str, Any]]:
    """One diagnostic's values across the series, in order.

    Rows keep ``(window, value, quality, coverage, image_count)``
    with gaps as ``None``.  A later current-vs-historical comparison
    joins two series' rows on ``(window_start, diagnostic_id)``; the
    helper exists so that join needs no new derivation.
    """
    if diagnostic_id not in RED_EDGE_DIAGNOSTIC_SPECS:
        supported = ", ".join(RED_EDGE_DIAGNOSTIC_IDS)
        raise ValueError(
            f"Unknown red-edge diagnostic {diagnostic_id!r}. "
            f"Supported diagnostics: {supported}."
        )
    rows: List[Dict[str, Any]] = []
    for entry in series.monthly:
        rows.append(
            {
                "window_start": entry.window_start,
                "window_end": entry.window_end,
                "diagnostic_id": diagnostic_id,
                "value": entry.diagnostic(diagnostic_id).value,
                "quality": entry.quality,
                "coverage_percent": entry.coverage_percent,
                "image_count": entry.image_count,
            }
        )
    return rows


def to_temporal_profile(
    series: RedEdgeSeries, diagnostic_id: str
) -> TemporalProfile:
    """Adapt one diagnostic series to the generic P1.2 profile shape.

    The returned :class:`TemporalProfile` carries the diagnostic
    values as monthly points with their quality, coverage, and image
    counts, so the generic P1.2 baseline machinery
    (``build_baseline`` / ``score_profile``) can consume it in a
    later phase without any new anomaly engine.  Nothing is scored
    here; adaptation is not analysis.
    """
    if diagnostic_id not in RED_EDGE_DIAGNOSTIC_SPECS:
        supported = ", ".join(RED_EDGE_DIAGNOSTIC_IDS)
        raise ValueError(
            f"Unknown red-edge diagnostic {diagnostic_id!r}. "
            f"Supported diagnostics: {supported}."
        )
    spec = RED_EDGE_DIAGNOSTIC_SPECS[diagnostic_id]
    points = tuple(
        TemporalProfilePoint(
            window_start=row["window_start"],
            window_end=row["window_end"],
            value=row["value"],
            unit=spec["unit"],
            quality=row["quality"],
            coverage_percent=row["coverage_percent"],
            image_count=row["image_count"],
        )
        for row in diagnostic_series(series, diagnostic_id)
    )
    return TemporalProfile(
        metric_key=diagnostic_id,
        dataset_id=series.dataset_id,
        unit=spec["unit"],
        window_start=series.window_start,
        window_end=series.window_end,
        step=series.step,
        points=points,
    )


# Re-export the reused direction labels next to the change type so
# readers of a serialized change need no second import to interpret
# it.  The labels themselves remain owned by P1.3.
DIRECTION_LABELS: Tuple[str, ...] = (
    DIRECTION_INCREASE,
    DIRECTION_DECREASE,
    DIRECTION_STABLE,
    DIRECTION_INSUFFICIENT,
)
