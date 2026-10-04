"""Agricultural Intelligence API endpoints (Phase Q).

Exposes the existing Agricultural Intelligence stack through a clean,
stable, read-only FastAPI API contract.

Architecture:
    Metrics -> Historical -> Evidence -> Synthesis -> API -> Frontend

This module is an orchestration/serialization boundary.  It does NOT:
- implement scientific calculations
- duplicate synthesis rules
- duplicate evidence logic
- calculate NDVI/EVI/etc inside routers
- invent confidence scores
- produce recommendations
- produce a global crop-health score
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.core.exceptions import (
    AppException,
    DateRangeError,
    GeometryError,
    ValidationError,
)
from app.core.logging import get_logger
from app.schemas.agriculture import (
    AgriculturalAnalysisResponse,
    AgricultureAnalysisRequest,
    AgricultureHealthResponse,
    DomainSummaryResponse,
    EvidenceBundleResponse,
    EvidenceConflictResponse,
    EvidenceItemResponse,
    EvidenceSufficiencyResponse,
    ProvenanceResponse,
    SynthesisOnlyRequest,
    SynthesisStatementResponse,
    SpatialSectionModel,
    TemporalSectionModel,
    ValidationSectionModel,
)
from app.services.cache_service import cache_service
from app.services.agriculture.evidence import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceStatus,
    SufficiencyLevel,
)
from app.services.agriculture.synthesis import (
    AgriculturalSynthesis,
    DomainSummary,
    SynthesisDomain,
    SynthesisEngine,
    SynthesisStatement,
)
from app.services.agriculture.types import (
    MetricResult,
    Provenance,
    QualityLevel,
)

logger = get_logger(__name__)

router = APIRouter()

# Valid domain identifiers
VALID_DOMAINS = {
    "vegetation",
    "water",
    "thermal",
    "soil",
    "climate",
    "crop",
    "phenology",
    "productivity",
    "historical",
    "terrain",
    "landcover",
    "stress",
    "irrigation",
}


# ---------------------------------------------------------------------------
# 1. Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_provenance(prov: Optional[Provenance]) -> Optional[ProvenanceResponse]:
    """Convert a Provenance dataclass to a Pydantic response model."""
    if prov is None:
        return None
    return ProvenanceResponse(
        source_dataset_id=prov.source_dataset_id,
        source_dataset_name=prov.source_dataset_name,
        bands=list(prov.bands),
        formula=prov.formula,
        unit=prov.unit,
        spatial_resolution=prov.spatial_resolution,
        temporal_resolution=prov.temporal_resolution,
        aggregation_method=prov.aggregation_method,
        measurement_basis=prov.measurement_basis.value
        if hasattr(prov.measurement_basis, "value")
        else str(prov.measurement_basis),
        quality_level=prov.quality_level.value
        if hasattr(prov.quality_level, "value")
        else str(prov.quality_level),
        temporal_kind=prov.temporal_kind.value
        if hasattr(prov.temporal_kind, "value")
        else str(prov.temporal_kind),
        requested_start=prov.requested_start,
        requested_end=prov.requested_end,
        product_date=prov.product_date,
        date_start=prov.date_start,
        date_end=prov.date_end,
        image_count=prov.image_count,
        fallback_from=prov.fallback_from,
        limitations=list(prov.limitations),
        caveats=list(prov.caveats),
        citation=prov.citation,
        computed_at=prov.computed_at,
    )


def _serialize_evidence_item(item: EvidenceItem) -> EvidenceItemResponse:
    """Convert an EvidenceItem to a Pydantic response model."""
    return EvidenceItemResponse(
        metric_key=item.metric_key,
        value=item.value,
        unit=item.unit,
        status=item.status.value
        if hasattr(item.status, "value")
        else str(item.status),
        quality=item.quality_level.value
        if hasattr(item.quality_level, "value")
        else str(item.quality_level),
        source_dataset=item.source_dataset_id,
        display_name=item.display_name,
        temporal_start=item.temporal_start.isoformat()
        if item.temporal_start
        else None,
        temporal_end=item.temporal_end.isoformat()
        if item.temporal_end
        else None,
        is_usable=item.is_usable,
        is_proxy=item.is_proxy,
        provenance=_serialize_provenance(item.provenance),
        stats=dict(item.stats) if item.stats else None,
        class_histogram=(
            {key: value for key, value in item.class_histogram.items()}
            if item.class_histogram
            else None
        ),
        band_means=dict(item.band_means) if item.band_means else None,
    )


def _serialize_evidence_conflict(
    conflict: Any,
) -> EvidenceConflictResponse:
    """Convert an EvidenceConflict to a Pydantic response model."""
    return EvidenceConflictResponse(
        metric_a=conflict.metric_a,
        metric_b=conflict.metric_b,
        status=conflict.status.value
        if hasattr(conflict.status, "value")
        else str(conflict.status),
        explanation=conflict.explanation,
        possible_explanations=list(conflict.possible_explanations),
    )


def _serialize_evidence_sufficiency(
    suff: Any,
) -> EvidenceSufficiencyResponse:
    """Convert an EvidenceSufficiency to a Pydantic response model."""
    return EvidenceSufficiencyResponse(
        level=suff.level.value
        if hasattr(suff.level, "value")
        else str(suff.level),
        available_count=suff.available_count,
        unavailable_count=suff.unavailable_count,
        distinct_sources=suff.distinct_sources,
        min_quality=suff.min_quality.value
        if hasattr(suff.min_quality, "value")
        else (str(suff.min_quality) if suff.min_quality else None),
        has_conflicts=suff.has_conflicts,
        key_reasons=list(suff.key_reasons),
    )


def _serialize_evidence_bundle(bundle: EvidenceBundle) -> EvidenceBundleResponse:
    """Convert an EvidenceBundle to a Pydantic response model."""
    return EvidenceBundleResponse(
        name=bundle.name,
        items=[_serialize_evidence_item(i) for i in bundle.items],
        available=bundle.available_keys,
        unavailable=[i.metric_key for i in bundle.unavailable_items],
        source_datasets=bundle.source_datasets,
        conflicts=[_serialize_evidence_conflict(c) for c in bundle.conflicts],
        sufficiency=_serialize_evidence_sufficiency(bundle.sufficiency)
        if bundle.sufficiency
        else None,
        limitations=list(bundle.limitations),
    )


def _serialize_synthesis_statement(
    stmt: SynthesisStatement,
) -> SynthesisStatementResponse:
    """Convert a SynthesisStatement to a Pydantic response model."""
    return SynthesisStatementResponse(
        rule_id=stmt.rule_id,
        domain=stmt.domain.value
        if hasattr(stmt.domain, "value")
        else str(stmt.domain),
        pattern=stmt.pattern.value
        if hasattr(stmt.pattern, "value")
        else str(stmt.pattern),
        statement=stmt.statement,
        evidence_keys=list(stmt.evidence_keys),
        evidence_values=dict(stmt.evidence_values),
        scientific_basis=stmt.scientific_basis,
        limitations=list(stmt.limitations),
        sufficiency=stmt.sufficiency.value
        if hasattr(stmt.sufficiency, "value")
        else str(stmt.sufficiency),
        conflicts=list(stmt.conflicts),
    )


def _serialize_domain_summary(summary: DomainSummary) -> DomainSummaryResponse:
    """Convert a DomainSummary to a Pydantic response model."""
    return DomainSummaryResponse(
        domain=summary.domain.value
        if hasattr(summary.domain, "value")
        else str(summary.domain),
        statement_count=summary.statement_count,
        statements=[_serialize_synthesis_statement(s) for s in summary.statements],
        unavailable_evidence=list(summary.unavailable_evidence),
        sufficiency=summary.sufficiency.value
        if hasattr(summary.sufficiency, "value")
        else str(summary.sufficiency),
        limitations=list(summary.limitations),
        has_usable_evidence=bool(summary.has_usable_evidence),
    )


def _serialize_synthesis(
    synthesis: AgriculturalSynthesis,
    evidence_bundles: Optional[Dict[str, EvidenceBundle]] = None,
) -> AgriculturalAnalysisResponse:
    """Convert an AgriculturalSynthesis to the top-level API response."""
    domain_summaries = {
        d.value: _serialize_domain_summary(s)
        for d, s in synthesis.domain_summaries.items()
    }

    evidence_resp: Dict[str, EvidenceBundleResponse] = {}
    if evidence_bundles:
        evidence_resp = {
            d.value: _serialize_evidence_bundle(b)
            for d, b in evidence_bundles.items()
        }

    return AgriculturalAnalysisResponse(
        time_start=synthesis.time_start.isoformat()
        if synthesis.time_start
        else None,
        time_end=synthesis.time_end.isoformat()
        if synthesis.time_end
        else None,
        spatial_context=synthesis.spatial_context,
        generated_at=datetime.utcnow().isoformat(),
        domain_summaries=domain_summaries,
        cross_domain_statements=[
            _serialize_synthesis_statement(cs)
            for cs in synthesis.cross_domain_statements
        ],
        overall_sufficiency=synthesis.overall_sufficiency.value
        if hasattr(synthesis.overall_sufficiency, "value")
        else str(synthesis.overall_sufficiency),
        evidence_bundles=evidence_resp,
        available_domains=[d.value for d in synthesis.available_domains],
        unavailable_domains=[d.value for d in synthesis.unavailable_domains],
        # Explicit domain semantics (F-CONTRACT-FIX-1 §2): the legacy
        # statement-based list above is untouched; the fields below are
        # the unambiguous data/statement split.  unavailable_metric_keys
        # is the de-duplicated canonical aggregate (§4).
        domains_with_data=[d.value for d in synthesis.domains_with_data],
        domains_with_statements=[
            d.value for d in synthesis.domains_with_statements
        ],
        domains_without_data=[d.value for d in synthesis.domains_without_data],
        unavailable_metric_keys=list(synthesis.unavailable_metric_keys()),
        limitations=list(synthesis.limitations),
        metadata=dict(synthesis.metadata),
    )


# ---------------------------------------------------------------------------
# 2. Validation helpers
# ---------------------------------------------------------------------------


def _validate_request(data: AgricultureAnalysisRequest) -> None:
    """Validate the analysis request.

    Raises ValidationError or DateRangeError on invalid input.
    """
    # Validate date format
    try:
        start = date.fromisoformat(data.start_date)
    except (ValueError, TypeError):
        raise ValidationError(
            f"Invalid start_date format: {data.start_date}. Expected YYYY-MM-DD",
        )

    try:
        end = date.fromisoformat(data.end_date)
    except (ValueError, TypeError):
        raise ValidationError(
            f"Invalid end_date format: {data.end_date}. Expected YYYY-MM-DD",
        )

    # Validate date ordering
    if end <= start:
        raise DateRangeError("end_date must be after start_date")

    # Validate domains
    if data.domains is not None:
        invalid = set(data.domains) - VALID_DOMAINS
        if invalid:
            raise ValidationError(
                f"Invalid domain(s): {invalid}. "
                f"Valid domains: {sorted(VALID_DOMAINS)}",
            )

    # Validate ground-truth structure.  Structurally malformed input
    # fails fast per existing API convention; well-formed records
    # that fail P6.1 validity are isolated as rejected references by
    # the P6.2 ingestion boundary while analysis continues.
    if data.ground_truth is not None:
        if not isinstance(data.ground_truth, list):
            raise ValidationError(
                "ground_truth must be a list of reference records",
            )
        for entry in data.ground_truth:
            if not isinstance(entry, dict):
                raise ValidationError(
                    "each ground_truth record must be a mapping",
                )


def _ground_truth_fingerprint(
    records: Optional[List[Any]],
) -> Optional[str]:
    """Deterministic cache fingerprint for supplied reference records.

    Each record is normalized through the frozen P6.1 mapping and
    the normalized forms are sorted, so key order and record order
    never create accidental cache divergence for semantically
    identical input.  Returns None when no records were supplied,
    keeping the cache identity of reference-free requests unchanged.
    """
    if not records:
        return None
    import hashlib
    import json as _json

    from app.services.agriculture.ground_truth import GroundTruthObservation

    blobs = []
    for raw in records:
        try:
            normalized = GroundTruthObservation.from_dict(raw).to_dict()
            blobs.append(_json.dumps(normalized, sort_keys=True, default=str))
        except Exception:
            blobs.append(
                "unreadable:" + _json.dumps(raw, sort_keys=True, default=str)
            )
    blob = _json.dumps(sorted(blobs), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _build_analysis_cache_key(data: AgricultureAnalysisRequest) -> str:
    """Build a deterministic cache key for an agriculture analysis request.

    Incorporates every input that affects the result: geometry, date range,
    requested domains, cloud tolerance, and temporal resolution.  Uses the
    same SHA-256 hashing approach as ``MetricContext.cache_key()``.
    """
    import hashlib
    import json as _json

    geometry_dict = data.geometry.model_dump()
    payload = {
        "geometry": _json.dumps(geometry_dict, sort_keys=True, default=str),
        "start_date": data.start_date,
        "end_date": data.end_date,
        "domains": sorted(data.domains) if data.domains else None,
        "cloud_max_percent": data.cloud_max_percent,
        "ground_truth": _ground_truth_fingerprint(data.ground_truth),
    }
    blob = _json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _enrich_analysis_provenance(
    analysis: Any, provenance: Any
) -> Any:
    """Merge a source provenance record into a normalized analysis.

    The P6.2 adapter's concise keys win on collision; the full
    record only adds provenance the adapter does not carry.
    Matching inputs are untouched, so P6.1 linkage is unaffected.
    """
    if not isinstance(provenance, dict) or not provenance:
        return analysis
    try:
        from dataclasses import replace as _replace

        merged = {**provenance, **analysis.provenance}
        return _replace(analysis, provenance=merged)
    except Exception:
        return analysis


def _collect_validation_analyses(
    response: AgriculturalAnalysisResponse,
) -> List[Any]:
    """Adapt already-produced response data to P6.2 inputs.

    Consumes the serialized analysis response only: scalar
    evidence items, temporal profile points, and spatial cell
    observations.  Nothing is recomputed and no Earth Engine
    builder runs here.  Shapes that cannot be adapted safely are
    recorded as unsupported per P6.2 semantics.
    """
    from app.services.agriculture.validation_engine import (
        NormalizedAnalysis,
        from_cell_observation,
        from_scalar_evidence,
        from_temporal_point,
    )

    analyses: List[Any] = []

    def _unsupported(kind: str, reason: str) -> None:
        analyses.append(
            NormalizedAnalysis(kind=kind, supported=False, reason=reason)
        )

    bundles = response.evidence_bundles or {}
    for domain_key, bundle in bundles.items():
        items = getattr(bundle, "items", None) or []
        for item in items:
            try:
                payload = (
                    item.model_dump()
                    if hasattr(item, "model_dump")
                    else dict(item)
                )
                normalized = from_scalar_evidence(
                    payload, domain=getattr(bundle, "name", domain_key) or domain_key
                )
                analyses.append(
                    _enrich_analysis_provenance(normalized, payload.get("provenance"))
                )
            except Exception as exc:
                _unsupported("scalar_evidence", f"unreadable evidence item ({type(exc).__name__})")

    temporal = getattr(response, "temporal", None)
    if temporal is not None:
        try:
            temporal_payload = (
                temporal.model_dump()
                if hasattr(temporal, "model_dump")
                else dict(temporal)
            )
        except Exception:
            temporal_payload = {}
        for table in ("profiles", "radar_profiles", "thermal_profiles"):
            profiles = temporal_payload.get(table) or {}
            for metric_key, profile in profiles.items():
                points = (profile or {}).get("points", []) or []
                try:
                    domain_hint = _metric_key_to_domain(metric_key) or ""
                except Exception:
                    domain_hint = ""
                for point in points:
                    try:
                        normalized = from_temporal_point(
                            point, metric_key, domain=domain_hint
                        )
                        analyses.append(
                            _enrich_analysis_provenance(
                                normalized,
                                point.get("provenance") if isinstance(point, dict) else None,
                            )
                        )
                    except Exception as exc:
                        _unsupported(
                            "temporal_point",
                            f"unreadable temporal point ({type(exc).__name__})",
                        )

    spatial = getattr(response, "spatial", None)
    if spatial is not None:
        try:
            spatial_payload = (
                spatial.model_dump()
                if hasattr(spatial, "model_dump")
                else dict(spatial)
            )
        except Exception:
            spatial_payload = {}
        for observation in spatial_payload.get("observations", []) or []:
            try:
                normalized = from_cell_observation(observation)
                analyses.append(
                    _enrich_analysis_provenance(
                        normalized,
                        observation.get("provenance")
                        if isinstance(observation, dict)
                        else None,
                    )
                )
            except Exception as exc:
                _unsupported(
                    "cell_observation",
                    f"unreadable cell observation ({type(exc).__name__})",
                )

    return analyses


def _attach_ground_truth_validation(
    response: AgriculturalAnalysisResponse,
    records: List[Any],
    request_id: str,
) -> AgriculturalAnalysisResponse:
    """Run P6.2 validation over an already-built analysis response.

    Executes only when reference records were supplied.  Consumes
    serialized response data through the P6.2 adapters — no metric,
    temporal, or spatial builder runs here and no Earth Engine call
    is made.  A validation failure never destroys the analysis: the
    section stays absent and the reason is recorded as a response
    limitation.
    """
    try:
        from app.services.agriculture.ground_truth import GROUND_TRUTH_VERSION
        from app.services.agriculture.validation_engine import (
            VALIDATION_ENGINE_VERSION,
            ingest_reference_records,
            validate,
        )

        collection = ingest_reference_records(records)
        analyses = _collect_validation_analyses(response)
        report = validate(analyses, collection)
        response.validation = ValidationSectionModel.model_validate(
            {
                "results": [item.to_dict() for item in report.results],
                "rejected_references": [item.to_dict() for item in collection.rejected],
                "duplicates": [item.to_dict() for item in collection.duplicates],
                "limitations": list(collection.limitations) + list(report.limitations),
                "contract_version": GROUND_TRUTH_VERSION,
                "engine_version": VALIDATION_ENGINE_VERSION,
            }
        )
    except Exception as exc:
        logger.warning(
            f"Agriculture analysis {request_id}: ground-truth validation "
            f"skipped ({type(exc).__name__})"
        )
        response.validation = None
        try:
            response.limitations.append(
                f"ground-truth validation unavailable ({type(exc).__name__})"
            )
        except Exception:
            pass
    return response


# ---------------------------------------------------------------------------
# 3. Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=AgricultureHealthResponse,
    tags=["Agriculture"],
)
async def agriculture_health() -> AgricultureHealthResponse:
    """Health check for the agricultural analysis subsystem.

    Reports whether the evidence and synthesis layers are available
    and how many metrics are registered.
    """
    try:
        from app.services.agriculture.catalog import metric_keys

        keys = metric_keys()
        return AgricultureHealthResponse(
            status="ok",
            metrics_registered=len(keys),
            evidence_layer="available",
            synthesis_layer="available",
            message=f"{len(keys)} metrics registered",
        )
    except Exception as e:
        return AgricultureHealthResponse(
            status="degraded",
            message=str(e),
        )


@router.post(
    "/analysis",
    response_model=AgriculturalAnalysisResponse,
    tags=["Agriculture"],
)
async def run_agriculture_analysis(
    data: AgricultureAnalysisRequest,
) -> AgriculturalAnalysisResponse:
    """Run a full agricultural analysis.

    Accepts geometry and date range, executes the metric stack,
    builds evidence, runs synthesis, and returns structured output.

    The response preserves:
- domain summaries with synthesis statements
- underlying evidence bundles
- provenance for every metric
- unavailable metrics with reasons
- quality and status information
- limitations and scientific basis
    """
    _validate_request(data)

    request_id = str(uuid.uuid4())
    total_start = time.perf_counter()
    logger.info(f"Agriculture analysis {request_id}: {data.start_date} to {data.end_date}")

    # Check cache before executing any metrics
    cache_key = _build_analysis_cache_key(data)
    cache_lookup_start = time.perf_counter()
    try:
        cached = cache_service.get(cache_key)
    except Exception as cache_exc:
        logger.warning(f"Agriculture analysis {request_id}: cache lookup failed ({type(cache_exc).__name__}), proceeding without cache")
        cached = None
    cache_lookup_ms = (time.perf_counter() - cache_lookup_start) * 1000.0

    if cached is not None:
        elapsed_ms = (time.perf_counter() - total_start) * 1000.0
        logger.info(
            f"Agriculture analysis {request_id}: cache hit "
            f"(lookup={cache_lookup_ms:.1f}ms, total={elapsed_ms:.1f}ms)"
        )
        cached["request_id"] = request_id
        response = AgriculturalAnalysisResponse(**cached)
        if data.ground_truth:
            response = _attach_ground_truth_validation(
                response, data.ground_truth, request_id
            )
        return response

    try:
        # Build EE geometry
        from app.utils.geometry import create_ee_geometry

        geometry_dict = data.geometry.model_dump()
        ee_geometry = create_ee_geometry(geometry_dict)

        # Execute metrics through the existing stack
        from app.services.agriculture import ensure_registered
        from app.services.agriculture.catalog import metric_keys as get_metric_keys
        from app.services.agriculture.base import MetricContext
        from app.services.agriculture.executor import execute_metrics

        ensure_registered()
        keys = get_metric_keys()

        # Filter to requested domains if specified
        if data.domains:
            # Map domains to metric keys (approximate mapping)
            domain_metric_map = _domain_to_metric_keys(data.domains)
            keys = [k for k in keys if k in domain_metric_map]

        context = MetricContext(
            geometry=ee_geometry,
            start_date=data.start_date,
            end_date=data.end_date,
            geometry_key=f"{geometry_dict}",
            cloud_max_percent=data.cloud_max_percent,
        )

        # The metric stack and the temporal/spatial builders make blocking
        # Earth Engine network calls. Running them directly here would pin
        # the event loop for the whole duration — a slow or retrying EE
        # request once wedged every endpoint, including /health. The
        # default executor thread pool is bounded and shared, so this is
        # offload, not a per-request thread factory. Synchronous callers
        # (threadpool worker threads) fall back to a direct call because
        # there is no running loop to protect there.
        if asyncio.get_running_loop() is not None:
            outcomes, unknown = await asyncio.to_thread(
                execute_metrics, keys, context
            )
        else:  # pragma: no cover - synchronous-only deployment path
            outcomes, unknown = execute_metrics(keys, context)

        # Build evidence from metric results
        evidence_bundles = _build_evidence_bundles(outcomes)

        # Run synthesis
        engine = SynthesisEngine()
        synthesis = engine.synthesise(
            evidence_bundles,
            time_start=date.fromisoformat(data.start_date),
            time_end=date.fromisoformat(data.end_date),
            spatial_context=f"Analysis {request_id}",
        )

        # Serialize
        response = _serialize_synthesis(synthesis, evidence_bundles)
        response.request_id = request_id
        response.metadata["metrics_executed"] = str(len(outcomes))
        response.metadata["unknown_metrics"] = str(len(unknown))

        # Temporal intelligence (P5.3): monthly profiles and derived
        # analyses for the requested domains, attached additively.
        # Orchestration only — every payload is produced by an
        # existing P1-P4 builder. Failures here never fail the
        # analysis; the section simply carries the limitation.
        try:
            from app.services.agriculture.temporal_section import (
                build_temporal_section,
            )

            # Same event-loop protection as the metric execution above.
            temporal_payload = await asyncio.to_thread(
                build_temporal_section, context, keys, data.domains
            )
            response.temporal = TemporalSectionModel.model_validate(
                temporal_payload
            )
        except Exception as temporal_exc:
            logger.warning(
                f"Agriculture analysis {request_id}: temporal section "
                f"skipped ({type(temporal_exc).__name__})"
            )
            response.temporal = None

        # Spatial intelligence (P5.3-S): deterministic grid cells and
        # area summaries for the requested metrics, attached
        # additively. Orchestration only — every payload is produced
        # by an existing P1.5 builder. Failures here never fail the
        # analysis; the section simply stays absent.
        try:
            from app.services.agriculture.spatial_section import (
                build_spatial_section,
            )

            # Same event-loop protection as the metric execution above.
            spatial_payload = await asyncio.to_thread(
                build_spatial_section, context, geometry_dict, keys
            )
            response.spatial = (
                SpatialSectionModel.model_validate(spatial_payload)
                if spatial_payload is not None
                else None
            )
        except Exception as spatial_exc:
            logger.warning(
                f"Agriculture analysis {request_id}: spatial section "
                f"skipped ({type(spatial_exc).__name__})"
            )
            response.spatial = None

        # Cache only successful analysis results that carry real provider
        # evidence (Phase A1): an EE outage surfaces as HTTP 200 with every
        # metric unavailable, and caching that would serve the outage shape
        # for CACHE_TTL after recovery. Error statuses never reach this
        # point (they raise), so the usable-measurement check below is the
        # remaining outage signature. The cached payload stays analysis-
        # only: validation is never stored, so reference observations
        # cannot leak across requests. It is attached after this write on
        # every path that needs it.
        try:
            if _response_has_usable_measurement(response):
                cache_service.set(cache_key, response.model_dump())
            else:
                logger.warning(
                    f"Agriculture analysis {request_id}: result carries no "
                    f"usable provider measurement; not cached"
                )
                response.metadata["cache_gate"] = "no_usable_measurement"
        except Exception as cache_exc:
            logger.warning(f"Agriculture analysis {request_id}: cache write failed ({type(cache_exc).__name__})")

        if data.ground_truth:
            response = _attach_ground_truth_validation(
                response, data.ground_truth, request_id
            )

        elapsed_ms = (time.perf_counter() - total_start) * 1000.0
        logger.info(
            f"Agriculture analysis {request_id}: completed "
            f"(metrics={len(outcomes)}, unknown={len(unknown)}, "
            f"cache_lookup={cache_lookup_ms:.1f}ms, total={elapsed_ms:.1f}ms)"
        )
        return response

    except AppException:
        raise
    except Exception as e:
        elapsed_ms = (time.perf_counter() - total_start) * 1000.0
        logger.error(f"Agriculture analysis {request_id} failed ({elapsed_ms:.1f}ms): {e}")
        raise AppException(
            message=f"Analysis failed: {type(e).__name__}",
            status_code=500,
            detail={"request_id": request_id, "error_type": type(e).__name__},
        )


@router.post(
    "/analysis/synthesis-only",
    response_model=AgriculturalAnalysisResponse,
    tags=["Agriculture"],
)
async def run_synthesis_from_evidence(
    data: SynthesisOnlyRequest,
) -> AgriculturalAnalysisResponse:
    """Run synthesis from pre-built evidence bundles.

    Allows the frontend or other services to submit evidence
    directly and receive synthesis output.  Useful for testing
    and for cases where evidence is built externally.
    """
    request_id = str(uuid.uuid4())

    try:
        # Parse evidence bundles
        bundles = _parse_evidence_bundles(data.evidence_bundles)

        # Parse dates
        start = date.fromisoformat(data.time_start) if data.time_start else None
        end = date.fromisoformat(data.time_end) if data.time_end else None

        # Run synthesis
        engine = SynthesisEngine()
        synthesis = engine.synthesise(
            bundles,
            time_start=start,
            time_end=end,
            spatial_context=data.spatial_context,
        )

        # Serialize
        response = _serialize_synthesis(synthesis, bundles)
        response.request_id = request_id
        return response

    except AppException:
        raise
    except Exception as e:
        logger.error(f"Synthesis-only analysis {request_id} failed: {e}")
        raise AppException(
            message=f"Synthesis failed: {type(e).__name__}",
            status_code=500,
            detail={"request_id": request_id, "error_type": type(e).__name__},
        )


# ---------------------------------------------------------------------------
# 4. Internal helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. Cache-safety gate
# ---------------------------------------------------------------------------


def _response_has_usable_measurement(
    response: AgriculturalAnalysisResponse,
) -> bool:
    """Whether the provider produced at least one usable measurement.

    A result is cache-safe only when real provider evidence reached this
    response: at least one evidence item that is usable (observed or
    derived value), a usable temporal-profile point, or a usable spatial
    cell observation. Everything else — an all-unavailable evidence
    layer, a wholly empty analysis — is treated as an infrastructure
    outage footprint and refused, because caching it would serve an
    outage shape for CACHE_TTL after the provider has recovered.

    Legitimate "the provider answered but this metric is honestly
    unavailable" results are unaffected as long as any sibling metric
    produced a real measurement (partial analyses stay cacheable).
    """
    for bundle in (response.evidence_bundles or {}).values():
        for item in getattr(bundle, "items", None) or []:
            if getattr(item, "is_usable", False):
                return True

    temporal = response.temporal
    if temporal is not None:
        for table in (
            "profiles",
            "radar_profiles",
            "thermal_profiles",
        ):
            for profile in (getattr(temporal, table, None) or {}).values():
                for point in getattr(profile, "points", None) or []:
                    if getattr(point, "value", None) is not None:
                        return True

    spatial = response.spatial
    if spatial is not None:
        for observation in getattr(spatial, "observations", None) or []:
            if getattr(observation, "value", None) is not None:
                return True

    return False


def _domain_to_metric_keys(domains: List[str]) -> List[str]:
    """Map domain names to metric keys using the metric registry.

    The metric registry is the source of truth for which metrics
    belong to which domain.
    """
    from app.services.agriculture.catalog import metrics_in_domain

    keys: List[str] = []
    for domain in domains:
        # Normalise "historical" to "history" for registry compatibility
        registry_domain = "history" if domain == "historical" else domain
        try:
            keys.extend(m.key for m in metrics_in_domain(registry_domain))
        except ValueError:
            # Unknown domain: no metrics to add
            continue
    return keys


def _build_evidence_bundles(
    outcomes: Dict[str, Any],
) -> Dict[SynthesisDomain, EvidenceBundle]:
    """Build evidence bundles from metric outcomes.

    Groups metric results by domain and wraps them as EvidenceItems.
    Uses the metric registry's authoritative domain for each metric.

    Synthesis bundles intentionally contain cross-domain evidence: a
    rule belongs to the domain it *describes* (its output domain) but
    may read evidence computed under other registry domains. Each
    output domain's bundle is therefore enriched with the union of the
    ``inputs`` declared by the synthesis rules registered for it. Only
    evidence that actually exists and is usable is added; nothing is
    fabricated and no item is duplicated.
    """
    from app.services.agriculture.synthesis import DEFAULT_RULES

    domain_groups: Dict[str, List[EvidenceItem]] = {}
    by_key: Dict[str, EvidenceItem] = {}

    for key, outcome in outcomes.items():
        if outcome is None or outcome.result is None:
            continue

        result: MetricResult = outcome.result
        item = EvidenceItem.from_result(result)

        # Determine domain from metric registry (authoritative source)
        domain = _metric_key_to_domain(key)
        if domain is None:
            # Unregistered metric: skip rather than silently misclassify
            continue

        # Normalise "history" to "historical" for SynthesisDomain compatibility
        if domain == "history":
            domain = "historical"

        domain_groups.setdefault(domain, []).append(item)
        by_key.setdefault(key, item)

    # Union of rule-declared inputs per output domain, in rule
    # declaration order. Derived from the rules themselves, never
    # hardcoded, so a rule edit automatically updates its bundle.
    rule_inputs: Dict[str, List[str]] = {}
    for rule in DEFAULT_RULES:
        wanted = rule_inputs.setdefault(rule.domain.value, [])
        for needed in rule.inputs:
            if needed not in wanted:
                wanted.append(needed)

    # Seed evaluation bundles for output domains that hold no native
    # registry evidence but whose rule inputs exist and are usable.
    # Without this, a domain described only through other domains'
    # metrics would never be evaluated at all. CROSS_DOMAIN is
    # excluded: its rules run on the merged bundle in ``synthesise``,
    # and a second bundle here would duplicate their statements.
    for domain_str, needed_keys in rule_inputs.items():
        if (
            domain_str in domain_groups
            or domain_str == SynthesisDomain.CROSS_DOMAIN.value
        ):
            continue
        seeded = [
            by_key[key]
            for key in needed_keys
            if by_key.get(key) is not None and by_key[key].is_usable
        ]
        if seeded:
            domain_groups[domain_str] = seeded

    bundles: Dict[SynthesisDomain, EvidenceBundle] = {}
    for domain_str, items in domain_groups.items():
        present = {i.metric_key for i in items}
        for needed_key in rule_inputs.get(domain_str, []):
            if needed_key in present:
                continue
            source = by_key.get(needed_key)
            if source is None or not source.is_usable:
                # Genuinely missing or unusable evidence stays missing;
                # synthesis rules require their inputs to be available.
                continue
            items.append(source)
            present.add(needed_key)

        try:
            domain = SynthesisDomain(domain_str)
        except ValueError:
            continue

        bundle = EvidenceBundle(
            name=domain_str,
            items=items,
        )
        bundle.run_consistency_checks()
        bundle.assess_sufficiency()
        bundles[domain] = bundle

    return bundles


def _metric_key_to_domain(key: str) -> Optional[str]:
    """Map a metric key to its authoritative domain from the metric registry.

    Uses ``get_metric(key).domain`` as the single source of truth.
    Returns ``None`` for unregistered metrics rather than silently
    misclassifying them.
    """
    from app.services.agriculture.catalog import get_metric, has_metric

    if not has_metric(key):
        return None
    metric = get_metric(key)
    return metric.domain


def _parse_evidence_bundles(
    raw: Dict[str, Any],
) -> Dict[SynthesisDomain, EvidenceBundle]:
    """Parse raw evidence bundle dicts into EvidenceBundle objects.

    This allows the synthesis-only endpoint to accept pre-built
    evidence from external sources.  Accepts both ``Dict[str, Any]``
    (raw dicts) and ``Dict[str, DomainEvidenceInput]`` (typed models).
    """
    bundles: Dict[SynthesisDomain, EvidenceBundle] = {}

    for domain_str, bundle_dict in raw.items():
        try:
            domain = SynthesisDomain(domain_str)
        except ValueError:
            continue

        # Handle both Pydantic model and raw dict
        if hasattr(bundle_dict, "model_dump"):
            # Pydantic model: access .items as a field
            item_dicts = [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in bundle_dict.items
            ]
        elif isinstance(bundle_dict, dict):
            item_dicts = bundle_dict.get("items", [])
        else:
            item_dicts = []

        items = []
        for item_dict in item_dicts:
            items.append(
                EvidenceItem(
                    metric_key=item_dict.get("metric_key", ""),
                    value=item_dict.get("value"),
                    unit=item_dict.get("unit", ""),
                    status=EvidenceStatus(
                        item_dict.get("status", "derived")
                    ),
                    temporal_start=None,
                    temporal_end=None,
                    quality_level=QualityLevel(
                        item_dict.get("quality", "good")
                    ),
                    provenance=None,
                    source_dataset_id=item_dict.get("source_dataset"),
                    display_name=item_dict.get("display_name", ""),
                )
            )

        bundle = EvidenceBundle(
            name=domain_str,
            items=items,
        )
        bundle.assess_sufficiency()
        bundles[domain] = bundle

    return bundles
