"""Sentinel-2 multispectral spectral-profile foundation (P2.1).

A reusable spectral observation layer over the production Sentinel-2
surface-reflectance path.  A spectral profile records the
reflectance response across the available optical bands for a
requested observation window, preserving the relationship between
bands and observation time.  This layer performs no diagnosis, no
scoring, and no visualisation: it only observes and reports.

Sentinel-2 provides discrete multispectral observations, not
continuous hyperspectral measurements.  Each band is an independent
sample at its own centre wavelength; nothing here interpolates
between bands or implies continuity of the spectrum.

A change in reflectance may be associated with many possible
factors, including phenology, water status, canopy structure,
chlorophyll changes, soil and background effects, management,
atmospheric or residual processing effects, pests, or disease.
This phase does not identify the cause of a spectral change.

Reused production path (nothing re-derived):

* dataset ``COPERNICUS/S2_SR_HARMONIZED`` from the central registry
  (:mod:`app.services.agriculture.registry.datasets`), including its
  band table, scale factor, and caveats;
* cloud masking via the Scene Classification Layer
  (``app.services.agriculture.vegetation._mask_sentinel2`` semantics:
  classes 0, 1, 3, 8, 9, 10 removed, class 7 retained);
* compositing via
  :func:`app.services.agriculture.vegetation.build_sentinel2_composite`
  (cloud-filtered median composite, rescaled once by 0.0001);
* reflectance scaling ``raw * 0.0001`` (registry ``BandSpec``
  ``scale_factor``), unit ``"reflectance"``, valid range 0-1;
* spatial reduction via :mod:`app.services.agriculture.aggregation`
  (combined reducer with pixel counts, honest coverage);
* quality verdicts via :mod:`app.services.agriculture.quality`
  (``SENTINEL2_THRESHOLDS``);
* calendar-month iteration via
  :func:`app.utils.dates.get_monthly_periods` and window validation
  via :func:`app.utils.dates.validate_date_range` (the P1.1
  temporal-profile pattern);
* geometry via :class:`app.services.agriculture.base.MetricContext`
  (the agriculture geometry contract: GeoJSON validated at the API
  boundary by ``app.utils.geometry``, threaded here as an opaque
  geometry plus a serialisable ``geometry_key`` — no second geometry
  representation is introduced);
* provenance shape following
  :class:`app.services.agriculture.types.Provenance`.

Temporal / composite behaviour:

* :func:`build_spectral_observation` answers ONE requested window
  with ONE median composite over that window — the existing
  Sentinel-2 composite contract.  Sub-window variation inside the
  window is not resolved by a single observation.
* :func:`build_spectral_profile` preserves temporal identity across
  a longer request by emitting one observation per intersecting
  calendar month (each month is its own composite), in
  chronological order.  Missing months stay missing.

Band scope: only the ten optical reflectance bands registered for
the production dataset are supported (B2, B3, B4, B5, B6, B7, B8,
B8A, B11, B12).  The 60 m aerosol / water-vapour / cirrus bands
(B1, B9, B10), the QA60 bitmask, and the SCL classification layer
are not reflectance observations and are refused explicitly rather
than served through a parallel implementation.  Red-edge bands
B5/B6/B7 are always represented independently and are never reduced
to a single index.

Historical comparison hook: a profile is band-aligned and
chronologically ordered, so a future phase can compare a current
profile against a historical one band by band and window by window.
No baseline arithmetic and no change classification is implemented
here.

Missing data: every requested band is always present in the
observation, in wavelength order.  A band with no usable pixels
carries ``value=None`` with status ``"insufficient"``; a band in a
window that could not be attempted at all carries ``value=None``
with status ``"unavailable"``.  Missing is never zero, never
interpolated, and never silently dropped.

Future cache dimensions (the cache implementation itself is
untouched): geometry key, observation window, cloud tolerance,
band set, per-band resolution, dataset revision.  See
:func:`spectral_cache_dimensions`.

Non-goals of this phase: cause attribution, spectral-shape
thresholds, statistical baselines, probabilistic or risk scoring,
model inference, thermal bands, new external datasets, endpoints,
and charts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.aggregation import (
    build_reducer,
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import MetricContext, coverage_overlap_days
from app.services.agriculture.quality import (
    SENTINEL2_THRESHOLDS,
    assess_quality,
)
from app.services.agriculture.types import QualityLevel
from app.utils.dates import get_monthly_periods, validate_date_range

logger = get_logger(__name__)

__all__ = [
    "S2_DATASET_ID",
    "SUPPORTED_SPECTRAL_BANDS",
    "S2_BAND_WAVELENGTH_NM",
    "S2_BAND_RESOLUTION_M",
    "WAVELENGTH_SOURCE",
    "SPECTRAL_UNIT",
    "SPECTRAL_SCALE_FACTOR",
    "SPECTRAL_VALID_RANGE",
    "COMPOSITE_METHOD",
    "STEP_CALENDAR_MONTH",
    "STATUS_AVAILABLE",
    "STATUS_INSUFFICIENT",
    "STATUS_UNAVAILABLE",
    "BAND_STATUSES",
    "VISIBLE_BANDS",
    "RED_EDGE_BANDS",
    "NIR_BANDS",
    "SWIR_BANDS",
    "EXPLICITLY_UNSUPPORTED_BANDS",
    "SPECTRAL_CHANGE_POSSIBLE_CAUSES",
    "SpectralBandSample",
    "SpectralSlope",
    "SpectralObservation",
    "SpectralProfile",
    "is_supported_band",
    "require_supported_band",
    "normalize_band_set",
    "band_wavelength_nm",
    "band_resolution_m",
    "reflectance_scale_factor",
    "describe_processing",
    "make_spectral_observation",
    "spectral_slopes",
    "visible_samples",
    "red_edge_samples",
    "nir_samples",
    "swir_samples",
    "band_series",
    "observation_for_window",
    "spectral_cache_dimensions",
    "build_spectral_observation",
    "build_spectral_profile",
]

#: Production Sentinel-2 dataset.  The single source of reflectance
#: observations for this module.
S2_DATASET_ID = "COPERNICUS/S2_SR_HARMONIZED"

#: The ten optical reflectance bands registered for the production
#: dataset, in wavelength order.  This order is the canonical
#: deterministic order used for samples, slopes, and serialisation.
SUPPORTED_SPECTRAL_BANDS: Tuple[str, ...] = (
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B11",
    "B12",
)

#: Band centre wavelengths in nanometres.  Source: the ESA
#: Sentinel-2 MSI spectral response as published in the Google Earth
#: Engine catalogue entry for COPERNICUS/S2_SR_HARMONIZED, mirrored
#: in docs/DATASETS.md ("Central Wavelength (nm)" column) and in the
#: central registry band descriptions
#: (app/services/agriculture/registry/datasets.py).  These are nominal
#: centre wavelengths used to order bands and to express per-nanometre
#: slopes between adjacent discrete samples; they are not a claim of
#: continuous spectral coverage.
S2_BAND_WAVELENGTH_NM: Dict[str, float] = {
    "B2": 490.0,
    "B3": 560.0,
    "B4": 665.0,
    "B5": 705.0,
    "B6": 740.0,
    "B7": 783.0,
    "B8": 842.0,
    "B8A": 865.0,
    "B11": 1610.0,
    "B12": 2190.0,
}

#: Native acquisition resolution per band in metres, from the same
#: catalogue source.  Reductions run at the band's own resolution so
#: that no band is silently resampled and the provenance resolution
#: statement stays honest.
S2_BAND_RESOLUTION_M: Dict[str, int] = {
    "B2": 10,
    "B3": 10,
    "B4": 10,
    "B5": 20,
    "B6": 20,
    "B7": 20,
    "B8": 10,
    "B8A": 20,
    "B11": 20,
    "B12": 20,
}

#: Human-readable statement of where the wavelength numbers come from.
WAVELENGTH_SOURCE = (
    "ESA Sentinel-2 MSI nominal band centre wavelengths as published "
    "in the Google Earth Engine catalogue for "
    "COPERNICUS/S2_SR_HARMONIZED, mirrored in docs/DATASETS.md and in "
    "the central registry band descriptions. The profile stores these "
    "as discrete sample positions; adjacent bands are not interpolated."
)

#: Output unit.  Identical to the registry ``BandSpec`` unit for every
#: supported band.
SPECTRAL_UNIT = "reflectance"

#: Raw stored integers are multiplied by this factor exactly once, in
#: the shared composite builder.  This module never rescales and never
#: reads raw digital numbers.
SPECTRAL_SCALE_FACTOR = 0.0001

#: Physically plausible range for surface reflectance.
SPECTRAL_VALID_RANGE: Tuple[float, float] = (0.0, 1.0)

#: Processing convention published on every observation.  Names the
#: existing composite contract so a reader knows sub-window variation
#: is resolved by the monthly series, not by a single observation.
COMPOSITE_METHOD = "median composite, then spatial mean"

#: Temporal step identifier published on every profile.
STEP_CALENDAR_MONTH = "calendar_month"

#: Per-band availability states.  ``"available"`` means a finite
#: reflectance was observed.  ``"insufficient"`` means the window was
#: attempted but the band yielded no usable pixels.  ``"unavailable"``
#: means the window could not be attempted at all.
STATUS_AVAILABLE = "available"
STATUS_INSUFFICIENT = "insufficient"
STATUS_UNAVAILABLE = "unavailable"
BAND_STATUSES: Tuple[str, ...] = (
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT,
    STATUS_UNAVAILABLE,
)

#: Spectral regions, as band groups.  Selectors only; the underlying
#: samples always keep the individual bands.
VISIBLE_BANDS: Tuple[str, ...] = ("B2", "B3", "B4")
RED_EDGE_BANDS: Tuple[str, ...] = ("B5", "B6", "B7")
NIR_BANDS: Tuple[str, ...] = ("B8", "B8A")
SWIR_BANDS: Tuple[str, ...] = ("B11", "B12")

#: Bands a caller might expect that this module deliberately refuses.
#: B1/B9/B10 are 60 m atmosphere-oriented bands with no reflectance
#: registration in the production registry; QA60 is a bitmask whose
#: cloud polygons are unpopulated for part of the archive; SCL is a
#: classification layer, not a reflectance observation.
EXPLICITLY_UNSUPPORTED_BANDS: Tuple[str, ...] = (
    "B1",
    "B9",
    "B10",
    "QA60",
    "SCL",
)

#: Neutral list of factors that may be associated with a reflectance
#: change.  Informational context only: this layer never selects a
#: cause and never classifies a shape.
SPECTRAL_CHANGE_POSSIBLE_CAUSES: Tuple[str, ...] = (
    "phenology",
    "water status",
    "canopy structure",
    "chlorophyll changes",
    "soil/background effects",
    "management",
    "atmospheric/residual processing effects",
    "pests",
    "disease",
)


# --------------------------------------------------------------------------
# Representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SpectralBandSample:
    """One band's reflectance observation within a window.

    A missing band is ``value=None`` with status ``"insufficient"``
    (attempted, nothing usable) or ``"unavailable"`` (not attempted).
    Missing is structural: consumers must render gaps, never fill.
    """

    band: str
    wavelength_nm: float
    value: Optional[float]
    unit: str = SPECTRAL_UNIT
    status: str = STATUS_UNAVAILABLE
    quality: str = "unavailable"
    coverage_percent: Optional[float] = None

    @property
    def is_available(self) -> bool:
        """Whether this sample carries a finite observed reflectance."""
        return (
            self.status == STATUS_AVAILABLE
            and self.value is not None
            and math.isfinite(self.value)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.1 API contract models."""
        return {
            "band": self.band,
            "wavelength_nm": self.wavelength_nm,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "quality": self.quality,
            "coverage_percent": self.coverage_percent,
        }


@dataclass(frozen=True)
class SpectralSlope:
    """Observed slope between two adjacent available bands.

    ``slope_per_nm`` is ``(value_to - value_from) /
    (wavelength_to_nm - wavelength_from_nm)`` when both ends carry
    finite values, else ``None``.  A descriptor of the sampled shape
    only; no threshold or classification is attached.
    """

    from_band: str
    to_band: str
    wavelength_from_nm: float
    wavelength_to_nm: float
    value_from: Optional[float]
    value_to: Optional[float]
    slope_per_nm: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_band": self.from_band,
            "to_band": self.to_band,
            "wavelength_from_nm": self.wavelength_from_nm,
            "wavelength_to_nm": self.wavelength_to_nm,
            "value_from": self.value_from,
            "value_to": self.value_to,
            "slope_per_nm": self.slope_per_nm,
        }


@dataclass(frozen=True)
class SpectralObservation:
    """The multispectral reflectance observed for one window.

    Exactly one sample per requested band, always in wavelength
    order.  A single observation answers a single window with a
    single median composite (see :data:`COMPOSITE_METHOD`); temporal
    identity across windows lives on :class:`SpectralProfile`.
    """

    window_start: str
    window_end: str
    dataset_id: str
    unit: str
    composite_method: str
    image_count: Optional[int]
    coverage_percent: Optional[float]
    quality: str
    samples: Tuple[SpectralBandSample, ...] = field(default_factory=tuple)

    @property
    def band_order(self) -> Tuple[str, ...]:
        """Requested bands, in wavelength order."""
        return tuple(sample.band for sample in self.samples)

    @property
    def n_available(self) -> int:
        """Samples carrying a finite reflectance."""
        return sum(1 for sample in self.samples if sample.is_available)

    def sample(self, band: str) -> SpectralBandSample:
        """Return one band's sample, raising a clear error if absent."""
        for item in self.samples:
            if item.band == band:
                return item
        available = ", ".join(self.band_order) or "(none)"
        raise KeyError(
            f"Band {band!r} is not part of this observation. "
            f"Observed bands: {available}."
        )

    def values_in_order(self) -> Tuple[Optional[float], ...]:
        """Reflectances in wavelength order, gaps as ``None``."""
        return tuple(sample.value for sample in self.samples)

    def provenance_payload(self) -> Dict[str, Any]:
        """Derivation record for every value in this observation."""
        dataset_name = ""
        spatial_resolution = (
            "10 m (B2,B3,B4,B8) / 20 m (B5,B6,B7,B8A,B11,B12)"
        )
        temporal_resolution = "5 days (combined S2A + S2B revisit)"
        citation = "Copernicus Sentinel-2 MSI Level-2A, ESA"
        caveats: List[str] = []
        try:
            from app.services.agriculture.registry import get_dataset

            spec = get_dataset(self.dataset_id)
            dataset_name = spec.name
            spatial_resolution = spec.spatial_resolution
            temporal_resolution = spec.temporal_resolution
            citation = spec.citation
            caveats = list(spec.caveats)
        except Exception:  # noqa: BLE001 - provenance must never raise
            dataset_name = self.dataset_id
        return {
            "source_dataset_id": self.dataset_id,
            "source_dataset_name": dataset_name,
            "bands": list(self.band_order),
            "formula": (
                "median composite band-mean reflectance; no index formula"
            ),
            "unit": self.unit,
            "spatial_resolution": spatial_resolution,
            "temporal_resolution": temporal_resolution,
            "aggregation_method": self.composite_method,
            "measurement_basis": "direct",
            "quality_level": self.quality,
            "requested_start": self.window_start,
            "requested_end": self.window_end,
            "date_start": self.window_start,
            "date_end": self.window_end,
            "image_count": self.image_count,
            "scale_factor": SPECTRAL_SCALE_FACTOR,
            "cloud_mask_method": "scl",
            "wavelength_source": WAVELENGTH_SOURCE,
            "limitations": [
                (
                    "One median composite per window; sub-window variation "
                    "is not resolved inside a single observation."
                ),
                (
                    "Discrete multispectral samples; adjacent bands are "
                    "not interpolated and carry no continuity claim."
                ),
                (
                    "A reflectance change has many possible explanations; "
                    "this layer records the observation and selects none."
                ),
            ],
            "caveats": caveats,
            "citation": citation,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.1 API contract models."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "dataset_id": self.dataset_id,
            "unit": self.unit,
            "composite_method": self.composite_method,
            "image_count": self.image_count,
            "coverage_percent": self.coverage_percent,
            "quality": self.quality,
            "samples": [sample.to_dict() for sample in self.samples],
            "provenance": self.provenance_payload(),
        }


@dataclass(frozen=True)
class SpectralProfile:
    """Chronological spectral observations sharing one band set.

    The container for future current-vs-historical comparison: two
    profiles with the same ``band_set`` are directly comparable band
    by band and window by window.  No comparison arithmetic lives
    here.
    """

    band_set: Tuple[str, ...]
    dataset_id: str
    unit: str
    composite_method: str
    window_start: str
    window_end: str
    step: str = STEP_CALENDAR_MONTH
    observations: Tuple[SpectralObservation, ...] = field(
        default_factory=tuple
    )

    @property
    def n_observations(self) -> int:
        """Total windows emitted, including missing ones."""
        return len(self.observations)

    @property
    def n_usable(self) -> int:
        """Windows with at least one finite band value."""
        return sum(
            1
            for observation in self.observations
            if observation.n_available > 0
        )

    def to_dict(self) -> Dict[str, Any]:
        """Plain-data form matching the P2.1 API contract models."""
        return {
            "band_set": list(self.band_set),
            "dataset_id": self.dataset_id,
            "unit": self.unit,
            "composite_method": self.composite_method,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "step": self.step,
            "observations": [
                observation.to_dict()
                for observation in self.observations
            ],
        }


# --------------------------------------------------------------------------
# Band set, wavelength, and reflectance contracts
# --------------------------------------------------------------------------


def is_supported_band(band: str) -> bool:
    """Whether a band is served through the production reflectance path."""
    return band in S2_BAND_WAVELENGTH_NM


def require_supported_band(band: str) -> str:
    """Return the band, or refuse with the supported set listed.

    Raises:
        ValueError: for any band outside the production reflectance
            registration — including the 60 m bands, QA60, and SCL —
            rather than serving it through a parallel implementation.
    """
    if band in S2_BAND_WAVELENGTH_NM:
        return band
    supported = ", ".join(SUPPORTED_SPECTRAL_BANDS)
    raise ValueError(
        f"Spectral profiles are not supported for band {band!r}. "
        f"Supported Sentinel-2 reflectance bands: {supported}."
    )


def normalize_band_set(
    bands: Optional[Sequence[str]] = None,
) -> Tuple[str, ...]:
    """Validate and canonically order a requested band set.

    ``None`` selects the full ten-band production set.  Explicit sets
    are validated band by band (unsupported bands raise), deduplicated,
    and returned in wavelength order so every downstream consumer —
    samples, slopes, serialisation — is deterministic regardless of
    the order the caller asked in.
    """
    if bands is None:
        return SUPPORTED_SPECTRAL_BANDS
    seen: List[str] = []
    for band in bands:
        require_supported_band(band)
        if band not in seen:
            seen.append(band)
    if not seen:
        raise ValueError(
            "Spectral profiles require at least one supported band. "
            f"Supported bands: {', '.join(SUPPORTED_SPECTRAL_BANDS)}."
        )
    return tuple(
        sorted(seen, key=lambda name: S2_BAND_WAVELENGTH_NM[name])
    )


def band_wavelength_nm(band: str) -> float:
    """Centre wavelength of a supported band in nanometres."""
    require_supported_band(band)
    return S2_BAND_WAVELENGTH_NM[band]


def band_resolution_m(band: str) -> int:
    """Native acquisition resolution of a supported band in metres."""
    require_supported_band(band)
    return S2_BAND_RESOLUTION_M[band]


def reflectance_scale_factor() -> float:
    """The single reflectance scale factor (0.0001).

    This is the registry ``BandSpec`` scale factor for every
    supported band, applied exactly once inside the shared composite
    builder.  No second scaling exists anywhere in this module.
    """
    return SPECTRAL_SCALE_FACTOR


def describe_processing() -> Dict[str, Any]:
    """Processing convention shared by every spectral observation."""
    return {
        "dataset_id": S2_DATASET_ID,
        "unit": SPECTRAL_UNIT,
        "scale_factor": SPECTRAL_SCALE_FACTOR,
        "valid_range": list(SPECTRAL_VALID_RANGE),
        "composite_method": COMPOSITE_METHOD,
        "cloud_mask_method": "scl",
        "cloud_mask_retained_class": 7,
        "band_scales_m": dict(S2_BAND_RESOLUTION_M),
        "wavelength_source": WAVELENGTH_SOURCE,
    }


# --------------------------------------------------------------------------
# Pure construction (no Earth Engine)
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


def _validate_quality(quality: str) -> str:
    valid = {level.value for level in QualityLevel}
    if quality not in valid:
        raise ValueError(
            f"Unknown quality level {quality!r}. "
            f"Expected one of {sorted(valid)}."
        )
    return quality


def make_spectral_observation(
    window_start: str,
    window_end: str,
    band_values: Mapping[str, Optional[float]],
    *,
    image_count: Optional[int] = None,
    coverage_percent: Optional[float] = None,
    quality: str = QualityLevel.UNAVAILABLE.value,
    dataset_id: str = S2_DATASET_ID,
    composite_method: str = COMPOSITE_METHOD,
    band_set: Optional[Sequence[str]] = None,
    band_statuses: Optional[Mapping[str, str]] = None,
    default_status: Optional[str] = None,
    band_coverages: Optional[Mapping[str, Optional[float]]] = None,
) -> SpectralObservation:
    """Assemble one window's observation from per-band reflectances.

    The pure core shared by the Earth Engine builder and by any
    future historical-baseline constructor: both produce the same
    ordered, provenance-carrying representation from the same inputs.

    Args:
        window_start: Observation window start (YYYY-MM-DD).
        window_end: Observation window end (YYYY-MM-DD).
        band_values: Reflectance per band (0-1).  Missing bands are
            ``None`` — never zero, never interpolated.
        image_count: Scenes contributing to the composite, if known.
        coverage_percent: Observation coverage, if known.
        quality: Observation quality level string.
        dataset_id: Source dataset (production Sentinel-2 by default).
        composite_method: Processing convention label.
        band_set: Bands the observation claims.  Defaults to the keys
            of ``band_values``; every entry is validated and the
            result is wavelength-ordered.  Requested bands absent from
            ``band_values`` become explicit missing samples.
        band_statuses: Explicit per-band status overrides.  When
            omitted, status is derived: finite values are
            ``"available"``, gaps are ``default_status`` (when given)
            or ``"insufficient"``.
        default_status: Status for gaps when no explicit status is
            given — ``"unavailable"`` for windows that were never
            attempted, ``"insufficient"`` otherwise.
        band_coverages: Per-band coverage percentages, when known.

    Raises:
        ValueError: for unsupported bands, unknown quality levels,
            unknown statuses, or an empty band set.
    """
    ordered = normalize_band_set(
        band_set if band_set is not None else tuple(band_values.keys())
    )
    _validate_quality(quality)
    if default_status is not None and default_status not in BAND_STATUSES:
        raise ValueError(
            f"Unknown band status {default_status!r}. "
            f"Expected one of {list(BAND_STATUSES)}."
        )
    if band_statuses:
        for band, status in band_statuses.items():
            require_supported_band(band)
            if status not in BAND_STATUSES:
                raise ValueError(
                    f"Unknown band status {status!r} for band {band!r}. "
                    f"Expected one of {list(BAND_STATUSES)}."
                )

    samples: List[SpectralBandSample] = []
    for band in ordered:
        raw = band_values.get(band)
        value = float(raw) if _is_usable_number(raw) else None
        if band_statuses and band in band_statuses:
            status = band_statuses[band]
        elif value is not None:
            status = STATUS_AVAILABLE
        elif default_status is not None:
            status = default_status
        else:
            status = STATUS_INSUFFICIENT
        per_band_coverage: Optional[float] = None
        if band_coverages is not None:
            per_band_coverage = _clean_coverage(
                band_coverages.get(band)
            )
        if per_band_coverage is None:
            per_band_coverage = _clean_coverage(coverage_percent)
        samples.append(
            SpectralBandSample(
                band=band,
                wavelength_nm=S2_BAND_WAVELENGTH_NM[band],
                value=value,
                unit=SPECTRAL_UNIT,
                status=status,
                quality=quality,
                coverage_percent=per_band_coverage,
            )
        )
    return SpectralObservation(
        window_start=window_start,
        window_end=window_end,
        dataset_id=dataset_id,
        unit=SPECTRAL_UNIT,
        composite_method=composite_method,
        image_count=image_count,
        coverage_percent=_clean_coverage(coverage_percent),
        quality=quality,
        samples=tuple(samples),
    )


def _missing_observation(
    window_start: str,
    window_end: str,
    ordered: Sequence[str],
    quality: str = QualityLevel.UNAVAILABLE.value,
) -> SpectralObservation:
    return make_spectral_observation(
        window_start,
        window_end,
        {},
        image_count=None,
        coverage_percent=None,
        quality=quality,
        band_set=tuple(ordered),
        default_status=STATUS_UNAVAILABLE,
    )


# --------------------------------------------------------------------------
# Spectral shape access (descriptors only — no thresholds)
# --------------------------------------------------------------------------


def _group_samples(
    observation: SpectralObservation, group: Sequence[str]
) -> Tuple[SpectralBandSample, ...]:
    wanted = set(group)
    return tuple(
        sample for sample in observation.samples if sample.band in wanted
    )


def visible_samples(
    observation: SpectralObservation,
) -> Tuple[SpectralBandSample, ...]:
    """Blue/green/red samples (B2/B3/B4), in wavelength order."""
    return _group_samples(observation, VISIBLE_BANDS)


def red_edge_samples(
    observation: SpectralObservation,
) -> Tuple[SpectralBandSample, ...]:
    """Independent red-edge samples (B5/B6/B7), never merged."""
    return _group_samples(observation, RED_EDGE_BANDS)


def nir_samples(
    observation: SpectralObservation,
) -> Tuple[SpectralBandSample, ...]:
    """NIR samples (B8 broad, B8A narrow), independently reported."""
    return _group_samples(observation, NIR_BANDS)


def swir_samples(
    observation: SpectralObservation,
) -> Tuple[SpectralBandSample, ...]:
    """SWIR samples (B11/B12), in wavelength order."""
    return _group_samples(observation, SWIR_BANDS)


def spectral_slopes(
    observation: SpectralObservation,
) -> Tuple[SpectralSlope, ...]:
    """Per-nanometre slopes between adjacent observed bands.

    One entry per consecutive pair in wavelength order.  Pairs with a
    missing end carry ``slope_per_nm=None``.  Slopes describe the
    sampled shape; they classify nothing.
    """
    slopes: List[SpectralSlope] = []
    samples = list(observation.samples)
    for first, second in zip(samples, samples[1:]):
        if _is_usable_number(first.value) and _is_usable_number(
            second.value
        ):
            run = second.wavelength_nm - first.wavelength_nm
            assert first.value is not None and second.value is not None
            slope = (
                (second.value - first.value) / run if run != 0 else None
            )
        else:
            slope = None
        slopes.append(
            SpectralSlope(
                from_band=first.band,
                to_band=second.band,
                wavelength_from_nm=first.wavelength_nm,
                wavelength_to_nm=second.wavelength_nm,
                value_from=first.value,
                value_to=second.value,
                slope_per_nm=slope,
            )
        )
    return tuple(slopes)


# --------------------------------------------------------------------------
# Historical comparison hook (alignment helpers, no arithmetic)
# --------------------------------------------------------------------------


def band_series(
    profile: SpectralProfile, band: str
) -> List[Dict[str, Any]]:
    """One band's values across the profile, in chronological order.

    Gaps stay gaps.  A future current-vs-historical comparison joins
    two profiles' series on ``(window_start, band)``; the helper
    exists so that join needs no new derivation.
    """
    require_supported_band(band)
    series: List[Dict[str, Any]] = []
    for observation in profile.observations:
        try:
            value = observation.sample(band).value
        except KeyError:
            value = None
        series.append(
            {
                "window_start": observation.window_start,
                "window_end": observation.window_end,
                "band": band,
                "value": value,
            }
        )
    return series


def observation_for_window(
    profile: SpectralProfile, window_start: str
) -> Optional[SpectralObservation]:
    """Return the observation for a window start, or ``None``."""
    for observation in profile.observations:
        if observation.window_start == window_start:
            return observation
    return None


def spectral_cache_dimensions(
    context: MetricContext, bands: Optional[Sequence[str]] = None
) -> Dict[str, Any]:
    """Future cache key dimensions for a spectral request.

    Informational only: the cache implementation is untouched and this
    mapping is not stored anywhere.  It documents what a future cache
    entry must vary on so that two different spectral requests can
    never share an entry.
    """
    ordered = normalize_band_set(bands)
    return {
        "geometry": context.geometry_key,
        "window_start": context.start_date,
        "window_end": context.end_date,
        "dataset_id": S2_DATASET_ID,
        "band_set": list(ordered),
        "band_scales_m": {
            band: S2_BAND_RESOLUTION_M[band] for band in ordered
        },
        "cloud_max_percent": context.cloud_max_percent,
        "processing": describe_processing(),
    }


# --------------------------------------------------------------------------
# Earth Engine builders (reuse the production composite path)
# --------------------------------------------------------------------------


def _s2_coverage_days(context: MetricContext) -> int:
    try:
        from app.services.agriculture.registry import get_dataset

        spec = get_dataset(S2_DATASET_ID)
        return coverage_overlap_days(
            context.start,
            context.end,
            spec.available_from,
            spec.available_to,
        )
    except Exception:  # noqa: BLE001 - coverage probe must not fail hard
        return 1


def _reduce_band(
    composite: Any,
    context: MetricContext,
    ee_module: Any,
    band: str,
) -> Tuple[Optional[float], Optional[float], int]:
    """Reduce one reflectance band over the geometry.

    Returns ``(mean, coverage_percent, valid_pixel_count)``.  The
    composite already carries reflectance (0-1), so no band
    specification is passed to the parser: applying a scale factor
    here would rescale twice.
    """
    scale = S2_BAND_RESOLUTION_M[band]
    band_image = composite.select([band])
    raw = band_image.reduceRegion(
        reducer=build_reducer(ee_module),
        geometry=context.geometry,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()
    area_sq_m = context.option("area_sq_m")
    stats = parse_reduction_result(
        raw or {},
        band=band,
        total_pixel_count=estimate_pixel_count(area_sq_m, scale),
        pixel_area_sq_m=pixel_area_sq_m(scale),
    )
    mean = (
        float(stats.mean)
        if _is_usable_number(stats.mean)
        else None
    )
    return mean, _clean_coverage(stats.coverage_percent), int(
        stats.valid_pixel_count or 0
    )


def build_spectral_observation(
    context: MetricContext,
    bands: Optional[Sequence[str]] = None,
    ee_module: Any = None,
) -> SpectralObservation:
    """Observe the requested bands for one window (single composite).

    Runs the production Sentinel-2 composite builder once for the
    requested window — a cloud-filtered median composite — then
    reduces each requested band at its own native resolution.  One
    call therefore performs one collection filter and one composite;
    per-band work is reductions of that shared composite, not new
    collections.

    Windows outside the Sentinel-2 coverage are returned as
    explicitly missing (all bands ``"unavailable"``) without running
    any observation.  Exceptions from a single window propagate to
    the caller (:func:`build_spectral_profile` converts them to
    missing observations so one month cannot sink a series).
    """
    from app.services.agriculture.vegetation import (
        build_sentinel2_composite,
    )

    ordered = normalize_band_set(bands)
    validate_date_range(context.start_date, context.end_date)

    if _s2_coverage_days(context) <= 0:
        logger.warning(
            "Spectral observation for %s to %s is outside the "
            "Sentinel-2 coverage; emitting a missing observation "
            "without running.",
            context.start_date,
            context.end_date,
        )
        return _missing_observation(
            context.start_date, context.end_date, ordered
        )

    if ee_module is None:
        import ee as ee_module  # type: ignore[no-redef]

    composite, image_count = build_sentinel2_composite(
        context, ee_module, ordered
    )

    if image_count == 0:
        return make_spectral_observation(
            context.start_date,
            context.end_date,
            {},
            image_count=0,
            coverage_percent=None,
            quality=QualityLevel.INSUFFICIENT.value,
            band_set=ordered,
            default_status=STATUS_INSUFFICIENT,
        )

    means: Dict[str, Optional[float]] = {}
    coverages: Dict[str, Optional[float]] = {}
    valid_counts: List[int] = []
    finite_coverages: List[float] = []
    for band in ordered:
        mean, coverage, valid = _reduce_band(
            composite, context, ee_module, band
        )
        means[band] = mean
        coverages[band] = coverage
        valid_counts.append(valid)
        if coverage is not None:
            finite_coverages.append(coverage)

    observation_coverage = (
        min(finite_coverages) if finite_coverages else 0.0
    )
    quality = assess_quality(
        image_count=image_count,
        coverage_percent=observation_coverage,
        valid_pixel_count=min(valid_counts) if valid_counts else 0,
        thresholds=SENTINEL2_THRESHOLDS,
    )

    return make_spectral_observation(
        context.start_date,
        context.end_date,
        means,
        image_count=image_count,
        coverage_percent=observation_coverage,
        quality=quality.value,
        band_set=ordered,
        band_coverages=coverages,
    )


def build_spectral_profile(
    context: MetricContext,
    bands: Optional[Sequence[str]] = None,
    ee_module: Any = None,
) -> SpectralProfile:
    """Observe the requested bands month by month over a window.

    Every intersecting calendar month is emitted exactly once, in
    chronological order, each with its own composite from
    :func:`build_spectral_observation`.  A month that cannot be
    observed — no scenes, full masking, or a raised exception —
    becomes a missing observation, never a zero and never an
    interpolation of its neighbours.
    """
    ordered = normalize_band_set(bands)
    validate_date_range(context.start_date, context.end_date)

    if ee_module is None:
        try:
            import ee as ee_module  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 - resolved per month instead
            ee_module = None

    windows = [
        (window_start, window_end)
        for window_start, window_end in get_monthly_periods(
            context.start_date, context.end_date
        )
    ]

    observations: List[SpectralObservation] = []
    for window_start, window_end in windows:
        sub_context = replace(
            context, start_date=window_start, end_date=window_end
        )
        try:
            observations.append(
                build_spectral_observation(
                    sub_context, ordered, ee_module
                )
            )
        except Exception as exc:  # noqa: BLE001 - one month cannot sink the profile
            logger.warning(
                "Spectral profile: month %s to %s failed (%s); "
                "recording a missing observation.",
                window_start,
                window_end,
                type(exc).__name__,
            )
            observations.append(
                _missing_observation(window_start, window_end, ordered)
            )

    return SpectralProfile(
        band_set=ordered,
        dataset_id=S2_DATASET_ID,
        unit=SPECTRAL_UNIT,
        composite_method=COMPOSITE_METHOD,
        window_start=context.start_date,
        window_end=context.end_date,
        observations=tuple(observations),
    )
