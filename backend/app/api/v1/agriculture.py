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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AnalysisNotFoundError,
    AppException,
    DateRangeError,
    GeometryError,
    ValidationError,
)
from app.core.logging import get_logger
from app.db.session import get_db
from app.schemas.agriculture import (
    AgriculturalAnalysisResponse,
    AgricultureAnalysisRequest,
    AgricultureHealthResponse,
    AgricultureHistoryItemSummary,
    AgricultureHistoryListResponse,
    DomainSummaryResponse,
    EvidenceBundleResponse,
    EvidenceConflictResponse,
    EvidenceItemResponse,
    EvidenceSufficiencyResponse,
    ProvenanceResponse,
    SynthesisOnlyRequest,
    SynthesisStatementResponse,
    SpatialLayerRequest,
    SpatialLayerResponse,
    SpatialSectionModel,
    TemporalSectionModel,
    ValidationSectionModel,
    HistoricalComparisonRequest,
    HistoricalComparisonResponse,
    SoilIntelligenceRequest,
    SoilIntelligenceResponse,
    PestDiseaseInspectionRequest,
    PestDiseaseInspectionResponse,
)
from app.services.cache_service import cache_service
from app.services.agriculture.history_store import (
    record_analysis_start,
    record_analysis_completion,
    record_analysis_failure,
    get_analysis_history_list,
    get_analysis_history_item,
    delete_analysis_history_item,
)

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
        quality_state=prov.quality_state.value if hasattr(prov.quality_state, "value") else str(prov.quality_state) if prov.quality_state else None,
        native_resolution_m=prov.native_resolution_m,
        support_description=prov.support_description,
        cell_elevation_m=prov.cell_elevation_m,
        site_elevation_m=prov.site_elevation_m,
        raw_value=prov.raw_value,
        corrected_value=prov.corrected_value,
        delta_c=prov.delta_c,
        uncertainty_c=prov.uncertainty_c,
        geometry_type=prov.geometry_type,
        support_radius_m=prov.support_radius_m,
        support_area_sq_m=prov.support_area_sq_m,
        support_family=prov.support_family,
        support_policy=prov.support_policy,
        support_native_resolution_m=prov.support_native_resolution_m,
        original_geometry=prov.original_geometry,
        support_inputs=prov.support_inputs,
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
        quality_state=item.provenance.quality_state.value if item.provenance and hasattr(item.provenance.quality_state, "value") else str(item.provenance.quality_state) if item.provenance and item.provenance.quality_state else None,
        native_resolution_m=item.provenance.native_resolution_m if item.provenance else None,
        raw_value=item.provenance.raw_value if item.provenance else None,
        corrected_value=item.provenance.corrected_value if item.provenance else None,
        delta_c=item.provenance.delta_c if item.provenance else None,
        uncertainty_c=item.provenance.uncertainty_c if item.provenance else None,
        provenance=_serialize_provenance(item.provenance),
        stats=dict(item.stats) if item.stats else None,
        class_histogram=(
            {key: value for key, value in item.class_histogram.items()}
            if item.class_histogram
            else None
        ),
        band_means=dict(item.band_means) if item.band_means else None,
        unavailable_reason=item.unavailable_reason,
        unavailable_message=item.unavailable_message,
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
        vegetation_regime=summary.vegetation_regime,
    )


def _serialize_synthesis(
    synthesis: AgriculturalSynthesis,
    evidence_bundles: Optional[Dict[str, EvidenceBundle]] = None,
    requested_domains: Optional[List[str]] = None,
    outcomes: Optional[Dict[str, Any]] = None,
) -> AgriculturalAnalysisResponse:
    """Convert an AgriculturalSynthesis to the top-level API response."""
    from app.services.agriculture.quality_gating import compute_coverage_summary

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

    coverage_summary = compute_coverage_summary(
        outcomes=outcomes,
        evidence_bundles=evidence_bundles,
        requested_domains=requested_domains,
    )

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
        vegetation_regime=synthesis.vegetation_regime,
        vegetation_regime_explanation=synthesis.metadata.get("regime_explanation"),
        coverage=coverage_summary,
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
    requested domains, cloud tolerance, temporal resolution, and the Point
    support policy version — so a response cached under one meaning of a
    Point request can never be replayed under another.  Uses the same
    SHA-256 hashing approach as ``MetricContext.cache_key()``.
    """
    import hashlib
    import json as _json

    from app.services.agriculture.support import POINT_SUPPORT_POLICY_VERSION

    geometry_dict = data.geometry.model_dump()
    payload = {
        "geometry": _json.dumps(geometry_dict, sort_keys=True, default=str),
        "start_date": data.start_date,
        "end_date": data.end_date,
        "domains": sorted(data.domains) if data.domains else None,
        "cloud_max_percent": data.cloud_max_percent,
        "ground_truth": _ground_truth_fingerprint(data.ground_truth),
        "point_support_policy": POINT_SUPPORT_POLICY_VERSION,
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
                    item.model_dump(mode="json")
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
    db: Optional[AsyncSession] = Depends(get_db),
) -> AgriculturalAnalysisResponse:
    """Run a full agricultural analysis.

    Accepts geometry and date range, executes the metric stack,
    builds evidence, runs synthesis, and returns structured output.
    Persists full result permanently in PostgreSQL for instant retrieval.
    """
    _validate_request(data)

    target_uuid: uuid.UUID
    if data.request_id:
        try:
            target_uuid = uuid.UUID(data.request_id)
        except (ValueError, TypeError):
            target_uuid = uuid.uuid4()
    else:
        target_uuid = uuid.uuid4()

    request_id = str(target_uuid)
    total_start = time.perf_counter()
    logger.info(f"Agriculture analysis {request_id}: {data.start_date} to {data.end_date}")

    session: Optional[AsyncSession] = db if isinstance(db, AsyncSession) else None
    if session:
        try:
            existing_rec, is_completed = await record_analysis_start(
                session, data, target_uuid
            )
            if is_completed and existing_rec.result_data:
                logger.info(
                    f"Agriculture analysis {request_id}: retrieved completed result from DB (idempotent replay)"
                )
                return AgriculturalAnalysisResponse(**existing_rec.result_data)
        except Exception as db_init_err:
            logger.warning(
                f"Agriculture analysis {request_id}: DB start record failed ({type(db_init_err).__name__}), proceeding"
            )

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
        if response.coverage is None or (data.domains and response.coverage.total > 0):
            from app.services.agriculture.quality_gating import compute_coverage_summary
            from app.schemas.agriculture import CoverageSummaryResponse
            response.coverage = CoverageSummaryResponse(
                **compute_coverage_summary(
                    evidence_bundles=response.evidence_bundles,
                    requested_domains=data.domains,
                )
            )
        if (not data.domains or any(d in ("pest_disease", "inspection") for d in data.domains)) and response.pest_disease_inspection is None:
            try:
                from app.services.agriculture.pest_disease_inspection import inspect_pest_disease_risk

                response.pest_disease_inspection = inspect_pest_disease_risk(
                    data.start_date,
                    data.end_date,
                    response.evidence_bundles or {},
                    response.temporal,
                    data.ground_truth,
                    request_id,
                )
            except Exception as pe:
                logger.warning(f"Pest/disease inspection on cache failed ({type(pe).__name__})")
        if session:
            try:
                await record_analysis_completion(session, target_uuid, response)
            except Exception as db_comp_err:
                logger.error(f"Could not persist cache-hit completion for {request_id}: {db_comp_err}")
                response.limitations.append("Database persistence degraded: analysis was not saved to permanent history")
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
            # Declared so the Point support policy can engage. Nothing
            # else in the request changes: the policy reads only this
            # field, and only when it holds a Point.
            requested_geometry=geometry_dict,
            original_geometry=ee_geometry,
            support_plan={},
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
        response = _serialize_synthesis(
            synthesis,
            evidence_bundles,
            requested_domains=data.domains,
            outcomes=outcomes,
        )
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

        # Soil intelligence (Phase P-AGRI-SOIL)
        # Additive computation of real soil moisture and SoilGrids 2.0 properties.
        # Computed when domains is None/empty (all domains) or explicitly includes "soil".
        if not data.domains or "soil" in data.domains:
            try:
                from app.services.agriculture.soil_intelligence import (
                    compute_soil_intelligence,
                )

                soil_payload = await asyncio.to_thread(
                    compute_soil_intelligence,
                    geometry_dict,
                    data.start_date,
                    data.end_date,
                    False,  # Parent analysis endpoint handles its own caching
                )
                if soil_payload:
                    response.soil_intelligence = SoilIntelligenceResponse.model_validate(soil_payload)
            except Exception as soil_exc:
                logger.warning(
                    f"Agriculture analysis {request_id}: soil intelligence "
                    f"skipped ({type(soil_exc).__name__}: {soil_exc})"
                )
                response.soil_intelligence = None

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

        if not data.domains or any(d in ("pest_disease", "inspection") for d in data.domains):
            try:
                from app.services.agriculture.pest_disease_inspection import inspect_pest_disease_risk

                response.pest_disease_inspection = inspect_pest_disease_risk(
                    data.start_date,
                    data.end_date,
                    response.evidence_bundles or {},
                    response.temporal,
                    data.ground_truth,
                    request_id,
                )
            except Exception as pe:
                logger.warning(f"Pest/disease inspection failed ({type(pe).__name__})")

        geom_dict = (
            data.geometry.model_dump()
            if hasattr(data.geometry, "model_dump")
            else dict(data.geometry)
        )
        response.geometry = geom_dict
        if getattr(data, "name", None):
            response.location_name = data.name

        if session:
            try:
                await record_analysis_completion(session, target_uuid, response)
            except Exception as db_comp_err:
                logger.error(f"Could not persist completion to DB for {request_id}: {db_comp_err}")
                response.limitations.append("Database persistence degraded: analysis was not saved to permanent history")

        elapsed_ms = (time.perf_counter() - total_start) * 1000.0
        logger.info(
            f"Agriculture analysis {request_id}: completed "
            f"(metrics={len(outcomes)}, unknown={len(unknown)}, "
            f"cache_lookup={cache_lookup_ms:.1f}ms, total={elapsed_ms:.1f}ms)"
        )
        return response

    except AppException as ae:
        if session:
            try:
                await record_analysis_failure(session, target_uuid, ae.reason or ae.message)
            except Exception:
                pass
        raise
    except Exception as e:
        elapsed_ms = (time.perf_counter() - total_start) * 1000.0
        logger.error(f"Agriculture analysis {request_id} failed ({elapsed_ms:.1f}ms): {e}", exc_info=True)
        err_str = str(e)
        if "Earth Engine" in err_str or "ee." in getattr(type(e), "__module__", "") or "EEException" in type(e).__name__:
            code = "ERR_GEE_UNAVAILABLE"
            reason = "Earth Engine service failed to process satellite imagery"
        elif isinstance(e, (asyncio.TimeoutError, TimeoutError)):
            code = "ERR_GEE_TIMEOUT"
            reason = "Satellite data processing timed out"
        else:
            code = "ERR_INTERNAL_SERVER_ERROR"
            reason = "An unexpected error occurred during agricultural analysis"

        if session:
            try:
                await record_analysis_failure(session, target_uuid, reason)
            except Exception:
                pass

        raise AppException(
            message=reason,
            code=code,
            reason=reason,
            status_code=500,
            detail={
                "request_id": request_id,
            },
        )


# ---------------------------------------------------------------------------
# History persistence endpoints (Phase P0-HISTORY)
# ---------------------------------------------------------------------------


@router.get(
    "/history",
    response_model=AgricultureHistoryListResponse,
    tags=["Agriculture"],
)
async def list_agriculture_history(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    location_id: Optional[uuid.UUID] = Query(None, description="Filter by location ID"),
    db: AsyncSession = Depends(get_db),
) -> AgricultureHistoryListResponse:
    """Retrieve paginated list of saved agricultural analysis history."""
    return await get_analysis_history_list(
        db=db,
        skip=skip,
        limit=limit,
        location_id=location_id,
    )


@router.get(
    "/history/{analysis_id}",
    response_model=AgriculturalAnalysisResponse,
    tags=["Agriculture"],
)
async def get_agriculture_history_detail(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AgriculturalAnalysisResponse:
    """Retrieve full saved agricultural analysis report by persistent ID.

    DECISION RULE: Decoupled from Google Earth Engine. Reads directly from
    persisted database records with zero GEE re-execution.
    """
    record = await get_analysis_history_item(db=db, analysis_id=analysis_id)
    if not record:
        raise AnalysisNotFoundError(str(analysis_id))

    if record.status == "failed":
        raise AppException(
            message="Analysis failed",
            code="ERR_ANALYSIS_FAILED",
            reason="This analysis run was recorded as failed in history",
            status_code=400,
            detail={
                "status": "failed",
                "error_message": record.error_message,
                "analysis_id": str(record.id),
            },
        )

    if record.status != "completed" or not record.result_data:
        raise AppException(
            message="Analysis is not yet completed",
            code="ERR_ANALYSIS_IN_PROGRESS",
            reason="Analysis processing is not yet completed",
            status_code=409,
            detail={
                "status": record.status,
                "analysis_id": str(record.id),
            },
        )

    # Deserialize directly from JSONB - pure offline retrieval
    try:
        data = dict(record.result_data)
        if record.location:
            data["geometry"] = record.location.geometry
            if record.location.name:
                data["location_name"] = record.location.name
            if record.location.area_sq_meters is not None:
                data["area_sq_meters"] = record.location.area_sq_meters
        return AgriculturalAnalysisResponse.model_validate(data)
    except Exception as exc:
        logger.error(f"Failed to parse stored result_data for analysis {analysis_id}: {exc}")
        raise AppException(
            message="Stored analysis data schema is incompatible",
            code="ERR_SCHEMA_INCOMPATIBLE",
            reason="Stored analysis record format could not be deserialized",
            status_code=500,
            detail={"technical_message": str(exc)},
        )


@router.delete(
    "/history/{analysis_id}",
    tags=["Agriculture"],
)
async def delete_agriculture_history_entry(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Manually delete a single agricultural analysis record from history."""
    deleted = await delete_analysis_history_item(db=db, analysis_id=analysis_id)
    if not deleted:
        raise AnalysisNotFoundError(str(analysis_id))

    return {"deleted": True, "id": str(analysis_id)}



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


@router.post(
    "/spatial-layer",
    response_model=SpatialLayerResponse,
    tags=["Agriculture"],
)
async def get_spatial_layer(
    data: SpatialLayerRequest,
) -> SpatialLayerResponse:
    """Generate a real Earth Engine raster map tile layer for spatial MVP visualization.

    Supports 'ndvi', 'lst_day', 'soil_moisture', and 'sar_vh'.
    Returns real XYZ tile URL template from Google Earth Engine.
    """
    from app.services.agriculture.spatial_layer import generate_spatial_layer

    if asyncio.get_running_loop() is not None:
        return await asyncio.to_thread(generate_spatial_layer, data)
    return generate_spatial_layer(data)


# Concurrency cap & rate-limiting state for hardened tile proxy (P-CLOSEOUT)
_tile_concurrency_semaphore = asyncio.Semaphore(10)
_tile_ip_requests: Dict[str, List[float]] = {}
_MAX_TILE_REQUESTS_PER_MINUTE = 180


@router.get(
    "/tiles/{layer_token}/{z}/{x}/{y}.png",
    tags=["Agriculture"],
)
async def get_proxied_tile(
    layer_token: str,
    z: int,
    x: int,
    y: int,
    request: Request,
):
    """Proxy and cache Earth Engine map tiles with cryptographic integrity and security hardening.

    Ensures the client browser never contacts Google/Earth Engine directly.
    - Validates cryptographic HMAC signature, date range, layer, and polygon bbox binding.
    - Enforces zoom restrictions [8, 20] and spatial bounds (returns 404 outside).
    - Caps concurrent upstream GEE fetches via Semaphore(10).
    - Enforces per-client IP rate limiting.
    - Emits Cache-Control: private headers.
    - Never logs tokens or sensitive parameters.
    """
    from fastapi.responses import Response
    import httpx
    from app.services.agriculture.tile_auth import verify_layer_token
    from app.services.cache_service import cache_service

    # 1. Rate limiting per client IP
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    now = time.time()
    history = [t for t in _tile_ip_requests.get(client_ip, []) if now - t < 60.0]
    if len(history) >= _MAX_TILE_REQUESTS_PER_MINUTE:
        raise AppException(
            message="Tile request rate limit exceeded",
            code="ERR_TILE_RATE_LIMIT",
            reason="Too many tile requests per minute from this IP address.",
            status_code=429,
        )
    history.append(now)
    _tile_ip_requests[client_ip] = history

    # 2. Cryptographic token verification & slippy bounds check
    is_valid, status_code, err_code, reason, token_id, payload = verify_layer_token(
        layer_token, z, x, y
    )
    if not is_valid:
        raise AppException(
            message=reason,
            code=err_code,
            reason=reason,
            status_code=status_code,
        )

    # 3. Check pre-cached tile by token_id and tile coordinates
    tile_cache_key = f"tile_img:{token_id}:{z}:{x}:{y}"
    cached_bytes = cache_service.get(tile_cache_key)
    if cached_bytes and isinstance(cached_bytes, (bytes, bytearray)):
        return Response(
            content=bytes(cached_bytes),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    # 4. Lookup upstream tile template
    url_template = cache_service.get(f"tile_template:{token_id}")
    if not url_template or not isinstance(url_template, str):
        raise AppException(
            message="Map tile layer session expired or not found",
            code="ERR_TILE_LAYER_EXPIRED",
            reason="The map tile layer token has expired or is invalid. Please refresh the map layer.",
            status_code=404,
        )

    target_url = url_template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))

    # 5. Fetch from upstream with concurrency cap (Semaphore 10) & 10s timeout
    try:
        async with _tile_concurrency_semaphore:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(target_url)
                if resp.status_code == 200:
                    cache_service.set(tile_cache_key, resp.content, ttl=86400)
                    return Response(
                        content=resp.content,
                        media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"},
                    )
                elif resp.status_code == 404:
                    return Response(status_code=404, content=b"")
                else:
                    logger.warning(
                        "Tile proxy upstream error %s for z=%s x=%s y=%s",
                        resp.status_code,
                        z,
                        x,
                        y,
                    )
                    return Response(status_code=resp.status_code, content=resp.content)
    except Exception as exc:
        logger.warning(
            "Tile proxy fetch failed for z=%s x=%s y=%s: %s",
            z,
            x,
            y,
            type(exc).__name__,
        )
        return Response(status_code=502, content=b"")



@router.post(
    "/historical-comparison",
    response_model=HistoricalComparisonResponse,
    tags=["Agriculture"],
)
async def get_historical_comparison(
    data: HistoricalComparisonRequest,
) -> HistoricalComparisonResponse:
    """Generate 10-year same-period historical comparison across real satellite observations.

    Supports exact seasonal same-period comparisons over the preceding 10 years.
    Never fabricates missing years or values.
    """
    from app.services.agriculture.history import generate_historical_comparison

    if asyncio.get_running_loop() is not None:
        return await asyncio.to_thread(generate_historical_comparison, data)
    return generate_historical_comparison(data)


@router.post(
    "/soil-intelligence",
    response_model=SoilIntelligenceResponse,
    tags=["Agriculture"],
)
async def get_soil_intelligence(
    data: SoilIntelligenceRequest,
) -> SoilIntelligenceResponse:
    """Compute real GEE soil moisture and SoilGrids 2.0 multi-depth properties.

    Strictly uses real Earth Engine satellite and gridded datasets.
    Never fabricates, hallucinates, or estimates uncalibrated soil nutrients.
    """
    from app.services.agriculture.soil_intelligence import compute_soil_intelligence

    geom_dict = (
        data.geometry.model_dump()
        if hasattr(data.geometry, "model_dump")
        else dict(data.geometry)
    )
    if asyncio.get_running_loop() is not None:
        payload = await asyncio.to_thread(
            compute_soil_intelligence,
            geom_dict,
            data.start_date,
            data.end_date,
        )
    else:
        payload = compute_soil_intelligence(
            geom_dict,
            data.start_date,
            data.end_date,
        )
    return SoilIntelligenceResponse.model_validate(payload)


@router.post(
    "/pest-disease-inspection",
    response_model=PestDiseaseInspectionResponse,
    tags=["Agriculture"],
)
async def get_pest_disease_inspection(
    data: PestDiseaseInspectionRequest,
) -> PestDiseaseInspectionResponse:
    """Run multi-sensor pest & disease risk screening and anomaly inspection.

    Performs optical (NDVI, NDRE, NDMI, MSI), radar (Sentinel-1 SAR), and thermal (LST, Tair)
    anomaly evaluation, temporal persistence checks, and biotic vs abiotic compatibility screening.
    Never fabricates data; never provides uncalibrated pathogen diagnosis or chemical spray prescriptions.
    """
    from app.services.agriculture.pest_disease_inspection import inspect_pest_disease_risk

    analysis_req = AgricultureAnalysisRequest(
        geometry=data.geometry,
        start_date=data.start_date,
        end_date=data.end_date,
        domains=["vegetation", "water", "thermal", "crop", "climate", "soil", "stress"],
        cloud_max_percent=data.cloud_max_percent,
        ground_truth=data.ground_truth,
    )

    analysis_resp = await run_agriculture_analysis(analysis_req)

    bundles = analysis_resp.evidence_bundles or {}
    temporal_sec = analysis_resp.temporal
    ground_truth = data.ground_truth or []

    if asyncio.get_running_loop() is not None:
        result = await asyncio.to_thread(
            inspect_pest_disease_risk,
            data.start_date,
            data.end_date,
            bundles,
            temporal_sec,
            ground_truth,
            analysis_resp.request_id,
        )
    else:
        result = inspect_pest_disease_risk(
            data.start_date,
            data.end_date,
            bundles,
            temporal_sec,
            ground_truth,
            analysis_resp.request_id,
        )
    return result


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
    from app.services.agriculture.synthesis import ALL_SYNTHESIS_RULES

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
    for rule in ALL_SYNTHESIS_RULES:
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
