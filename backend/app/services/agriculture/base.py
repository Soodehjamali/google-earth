"""The metric provider contract.

Every scientific metric in this engine is a :class:`Metric` subclass. The
contract is small on purpose: a metric declares its identity, declares the
datasets it depends on, and knows how to compute itself given a context.

The context carries everything that would otherwise become a global or a
parameter threaded through twenty call sites: the geometry, the date
range, the Earth Engine objects, and the cache key inputs.

Why a class rather than a function
----------------------------------
Metrics need to report metadata even when they cannot compute a value.
A class lets a metric answer "what are your bands and limitations?" and
"can you even attempt this date range?" without running the computation.
That is what makes the fallback chain and the catalog possible.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.agriculture.types import (
    NOT_AVAILABLE_REASON_OUT_OF_COVERAGE,
    NOT_AVAILABLE_REASON_UNSUPPORTED,
    DatasetSpec,
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    TemporalKind,
)

__all__ = [
    "MetricContext",
    "Metric",
    "MetricDomain",
    "coverage_overlap_days",
]


class MetricDomain:
    """Canonical domain names, used for grouping and for API routing."""

    VEGETATION = "vegetation"
    WATER = "water"
    SOIL = "soil"
    CLIMATE = "climate"
    THERMAL = "thermal"
    TERRAIN = "terrain"
    CROP = "crop"
    PHENOLOGY = "phenology"
    LANDCOVER = "landcover"
    STRESS = "stress"
    IRRIGATION = "irrigation"
    PRODUCTIVITY = "productivity"
    HISTORY = "history"

    ALL: Tuple[str, ...] = (
        VEGETATION, WATER, SOIL, CLIMATE, THERMAL, TERRAIN, CROP, PHENOLOGY,
        LANDCOVER, STRESS, IRRIGATION, PRODUCTIVITY, HISTORY,
    )


def _parse_date(value: Any) -> Optional[date]:
    """Parse an ISO date or datetime string into a date, or None."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Accept both 'YYYY-MM-DD' and full ISO timestamps.
        candidate = text[:10]
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            return None
    return None


def coverage_overlap_days(
    start: Optional[date],
    end: Optional[date],
    available_from: Optional[str],
    available_to: Optional[str],
) -> int:
    """Return the number of days of overlap between a request and coverage.

    Returns 0 when the request lies entirely outside the dataset's
    lifetime, which callers use to distinguish "no data for this period"
    from "this dataset never covered this period".
    """
    if start is None or end is None:
        return 0
    if start > end:
        return 0

    ds_start = _parse_date(available_from)
    ds_end = _parse_date(available_to) or date(2200, 1, 1)

    overlap_start = max(start, ds_start) if ds_start else start
    overlap_end = min(end, ds_end)

    if overlap_start > overlap_end:
        return 0
    return (overlap_end - overlap_start).days + 1


@dataclass
class MetricContext:
    """Everything a metric needs in order to compute itself.

    Deliberately holds Earth Engine objects as ``Any`` so this module can
    be imported without the ``ee`` package being initialised. Modules that
    actually read imagery import ``ee`` themselves.
    """

    geometry: Any
    start_date: str
    end_date: str

    #: Serializable representation of the geometry, used for cache keys and
    #: for logging. Kept separate so we never re-serialise an EE object.
    geometry_key: str = ""

    #: Loaded Earth Engine objects, populated lazily by the executor.
    image_collections: Dict[str, Any] = field(default_factory=dict)
    images: Dict[str, Any] = field(default_factory=dict)

    #: Spatial scale in metres to use for reductions. Metrics may override.
    scale: Optional[int] = None

    #: Maximum acceptable cloud cover percentage when selecting scenes.
    cloud_max_percent: float = 20.0

    #: Dataset version identifiers, folded into the cache key so that a
    #: dataset revision invalidates cached results.
    dataset_versions: Dict[str, str] = field(default_factory=dict)

    #: Free-form options for metric-specific tuning.
    options: Dict[str, Any] = field(default_factory=dict)

    def cache_key(self, metric_key: str, **extra: Any) -> str:
        """Build a deterministic cache key for a metric.

        Folds in everything that could change the answer: geometry,
        dates, metric identity, scale, cloud tolerance, dataset versions,
        and any metric-specific extras.
        """
        payload = {
            "metric": metric_key,
            "geometry": self.geometry_key,
            "start": self.start_date,
            "end": self.end_date,
            "scale": self.scale,
            "cloud_max_percent": self.cloud_max_percent,
            "dataset_versions": dict(sorted(self.dataset_versions.items())),
            "extra": extra,
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @property
    def start(self) -> Optional[date]:
        return _parse_date(self.start_date)

    @property
    def end(self) -> Optional[date]:
        return _parse_date(self.end_date)

    def option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


class Metric(ABC):
    """Base class for every scientific metric.

    Subclasses must declare their identity and their dataset dependencies,
    then implement :meth:`compute`.
    """

    #: Machine-readable key, e.g. ``"ndvi"``. Must be unique across the
    #: registry and stable, because it appears in API paths and cache keys.
    key: str = ""

    #: Human-readable names. Persian is required: the UI is bilingual.
    display_name: str = ""
    display_name_fa: str = ""

    #: Domain this metric belongs to, from :class:`MetricDomain`.
    domain: str = ""

    #: Output unit, e.g. ``"index"``, ``"mm"``, ``"degC"``.
    unit: str = ""

    #: Dataset IDs this metric depends on, most preferred first. The first
    #: entry is the primary source; later entries are fallbacks.
    dataset_ids: Sequence[str] = ()

    #: How the value is obtained. Subclasses override where needed.
    measurement_basis: MeasurementBasis = MeasurementBasis.DERIVED

    #: Spatial scale in metres for reductions. ``None`` means use the
    #: context default.
    default_scale: Optional[int] = None

    #: Short statement of what the metric means, shown to users.
    description: str = ""

    #: Things this metric cannot tell you. Surfaced verbatim.
    limitations: Tuple[str, ...] = ()

    # -- identity ----------------------------------------------------------

    def __init__(self) -> None:
        if not self.key:
            raise ValueError(
                f"{type(self).__name__} must define a non-empty 'key'"
            )
        if not self.display_name or not self.display_name_fa:
            raise ValueError(
                f"Metric {self.key!r} must define display_name and "
                "display_name_fa"
            )
        if self.domain not in MetricDomain.ALL:
            raise ValueError(
                f"Metric {self.key!r} has unknown domain "
                f"{self.domain!r}. Expected one of {MetricDomain.ALL}"
            )

    # -- capability reporting ---------------------------------------------

    @property
    def primary_dataset_id(self) -> Optional[str]:
        return self.dataset_ids[0] if self.dataset_ids else None

    def primary_dataset(self) -> DatasetSpec:
        """Return the primary dataset spec from the registry."""
        from app.services.agriculture.registry import get_dataset

        if not self.dataset_ids:
            raise ValueError(f"Metric {self.key!r} declares no datasets")
        dataset_id = self.dataset_ids[0]
        from app.services.agriculture.registry import has_dataset
        if has_dataset(dataset_id):
            return get_dataset(dataset_id)

        from app.services.agriculture.registry import get_external_dataset

        return get_external_dataset(dataset_id)

    def can_attempt(self, context: MetricContext) -> Tuple[bool, Optional[str]]:
        """Whether this metric can attempt the requested date range.

        Returns a ``(can_attempt, reason)`` pair. A metric that cannot
        attempt a period should say why rather than returning an empty
        result, so the caller can distinguish "out of coverage" from
        "no scenes found".

        Two cases, decided by the primary dataset's declared
        :class:`TemporalKind`:

        * ``OBSERVATION`` — the declared window bounds when observations
          exist, so a request outside it is rejected as out of coverage.
        * ``STATIC`` — the declared window records when the product was
          made. The product is not a time series and that date does not
          restrict which analysis dates it can inform, so the window is
          *not* used to reject the request.

        What is never skipped, for either kind, is validation of the
        request itself. A malformed or inverted date range cannot be
        computed for any dataset, and a static surface is not an excuse to
        attempt one. So the dates are parsed and ordered first, and only
        then does the coverage question arise.
        """
        try:
            dataset = self.primary_dataset()
        except KeyError:
            return False, NOT_AVAILABLE_REASON_UNSUPPORTED

        # Malformed or inverted ranges are rejected for every dataset.
        # ``coverage_overlap_days`` returns 0 for both of these, which is
        # why the static branch cannot simply skip the call: doing so
        # would let a nonsense request through to an expensive query.
        start = context.start
        end = context.end
        if start is None or end is None or start > end:
            return False, NOT_AVAILABLE_REASON_OUT_OF_COVERAGE

        if dataset.temporal_kind is TemporalKind.STATIC:
            # The acquisition date is context, not a validity window.
            return True, None

        days = coverage_overlap_days(
            start,
            end,
            dataset.available_from,
            dataset.available_to,
        )
        if days <= 0:
            return False, NOT_AVAILABLE_REASON_OUT_OF_COVERAGE
        return True, None

    # -- computation -------------------------------------------------------

    @abstractmethod
    def compute(self, context: MetricContext) -> MetricResult:
        """Compute the metric and return a fully-formed result.

        Implementations must never return a bare number, and must never
        report missing data as zero. Use the ``MetricResult`` constructors
        for the unavailable, insufficient and error cases.

        Implementations should let unexpected exceptions propagate: the
        executor catches them per metric so that one failure cannot take
        down a whole analysis.
        """
        raise NotImplementedError

    # -- helpers for subclasses -------------------------------------------

    def build_provenance(
        self,
        context: MetricContext,
        dataset: DatasetSpec,
        bands: Sequence[str],
        formula: str,
        quality: QualityLevel,
        image_count: Optional[int] = None,
        aggregation_method: str = "mean",
        fallback_from: Optional[str] = None,
        extra_limitations: Sequence[str] = (),
        extra_caveats: Sequence[str] = (),
    ) -> Provenance:
        """Assemble a provenance record with the metric's own limitations.

        Keeps the "every output states its source and its weaknesses" rule
        in one place instead of repeated in every metric.

        The temporal kind is carried through from the dataset, and for a
        static product the acquisition date is recorded separately from
        the requested period. Without that separation a result computed
        from a year-2000 elevation model for a 2024 request would show
        2024 in both date fields and read as though the DEM had been
        observed in 2024.
        """
        is_static = dataset.temporal_kind is TemporalKind.STATIC
        product_date: Optional[str] = None
        if is_static:
            # The honest "when is this from?". A closed acquisition window
            # is reported as its start; an open-ended one as the single
            # declared date. Either way it is the product's date, never
            # the user's request.
            product_date = dataset.available_from

        return Provenance(
            source_dataset_id=dataset.id,
            source_dataset_name=dataset.name,
            bands=list(bands),
            formula=formula,
            unit=self.unit,
            spatial_resolution=dataset.spatial_resolution,
            temporal_resolution=dataset.temporal_resolution,
            temporal_kind=dataset.temporal_kind,
            aggregation_method=aggregation_method,
            measurement_basis=self.measurement_basis,
            quality_level=quality,
            requested_start=context.start_date,
            requested_end=context.end_date,
            product_date=product_date,
            date_start=context.start_date,
            date_end=context.end_date,
            image_count=image_count,
            fallback_from=fallback_from,
            limitations=list(self.limitations) + list(extra_limitations),
            caveats=list(dataset.caveats) + list(extra_caveats),
            citation=dataset.citation,
        )

    def effective_scale(self, context: MetricContext) -> int:
        """Resolve the reduction scale for this metric."""
        if self.default_scale is not None:
            return self.default_scale
        if context.scale is not None:
            return context.scale
        return 10

    @property
    def source_bands(self) -> Tuple[str, ...]:
        """All source bands this metric reads.

        The default lists every band of the primary dataset, which is
        correct for metrics that consume the whole dataset. Metrics that
        read only a subset, or that combine bands across datasets,
        override this.

        It exists so that tests and the catalog endpoint can assert a
        metric only reads bands that genuinely exist, a class of bug that
        otherwise surfaces only at runtime inside an Earth Engine call.
        """
        try:
            dataset = self.primary_dataset()
        except Exception:  # noqa: BLE001 - the catalog must never raise
            return ()
        return tuple(dataset.bands.keys())

    @property
    def requires_disclaimer(self) -> bool:
        """Whether this metric's basis always demands an explicit caveat."""
        return self.measurement_basis.requires_disclaimer

    def metadata(self) -> Dict[str, Any]:
        """Describe this metric for the public catalog endpoint."""
        return {
            "key": self.key,
            "display_name": self.display_name,
            "display_name_fa": self.display_name_fa,
            "domain": self.domain,
            "unit": self.unit,
            "description": self.description,
            "measurement_basis": self.measurement_basis.value,
            "dataset_ids": list(self.dataset_ids),
            "limitations": list(self.limitations),
            "is_proxy": self.measurement_basis in (
                MeasurementBasis.PROXY,
                MeasurementBasis.INFERENCE,
            ),
            # Metrics are available unless a subclass says otherwise. An
            # unavailable metric is a deliberate, documented omission, not
            # a failure, so the flag defaults to True and is only ever
            # cleared explicitly.
            "available": True,
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} key={self.key!r} domain={self.domain!r}>"
