"""Analysis orchestration service."""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import ee
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.exceptions import AppException, EarthEngineError, AnalysisNotFoundError
from app.services.agriculture import ensure_registered
from app.services.agriculture.base import MetricContext
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.landcover import (
    IGBP_WATER_BODIES,
    LANDCOVER_METRICS,
    LANDCOVER_WORKING_SCALE,
    MCD12Q1,
)

from app.services.earth_engine.statistics import compute_vegetation_analysis
from app.utils.geometry import calculate_area_sq_meters, create_ee_geometry

logger = get_logger(__name__)

#: The land cover metrics that make up the ``landcover`` analysis type.
#: Ordered so the class distribution is computed first; the executor runs
#: them concurrently, but the ordering keeps the serialised payload stable.
LANDCOVER_METRIC_KEYS = tuple(metric.key for metric in LANDCOVER_METRICS)

#: Analysis types that route through the agriculture engine, mapped to the
#: metric registry domains they draw from. ``vegetation`` and ``landcover``
#: keep their dedicated handlers above; everything here is served by
#: :meth:`AnalysisService._run_domain_analysis`.
_ANALYSIS_TYPE_DOMAINS: Dict[str, List[str]] = {
    "climate": ["climate"],
    "water": ["water"],
    "soil": ["soil"],
    "stress": ["stress"],
    "irrigation": ["irrigation"],
}


def _extract_value(outcome: Any, field: Optional[str] = None) -> Optional[Any]:
    """Pull a usable value out of an executor outcome.

    ``None`` outcome → ``None``. A dict-valued metric result exposes its
    ``mean`` (or the requested ``field``). A numeric scalar is returned as
    a float. A string scalar — e.g. a USDA texture class — is returned as
    itself, because a classification is the metric's real answer and
    dropping it would report ``None`` for a metric that did answer.
    Anything else is ``None`` rather than a guessed number.
    """
    if outcome is None or getattr(outcome, "result", None) is None:
        return None
    value = outcome.result.value
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(field or "mean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return value
    return None


def _extract_min_max(outcome: Any) -> Dict[str, Optional[float]]:
    """Normalise an outcome into a ``{"mean", "min", "max"}`` block.

    A scalar result is reported as the same value for all three, because
    that is what a single number means; a dict result carries its own
    spread. ``None`` propagates rather than becoming zero.
    """
    if outcome is None or getattr(outcome, "result", None) is None:
        return {"min": None, "max": None, "mean": None}
    value = outcome.result.value
    if value is None:
        return {"min": None, "max": None, "mean": None}
    if isinstance(value, dict):
        return {
            "mean": value.get("mean"),
            "min": value.get("min"),
            "max": value.get("max"),
        }
    if isinstance(value, (int, float)):
        return {"mean": float(value), "min": float(value), "max": float(value)}
    return {"min": None, "max": None, "mean": None}


def _map_climate(outcomes: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise the climate metrics into the analysis contract."""
    result = dict(base)
    result["climate"] = {
        "temperature": _extract_min_max(outcomes.get("temperature_mean")),
        "precipitation": {"total": _extract_value(outcomes.get("precipitation"))},
        "evapotranspiration": {
            "total": _extract_value(outcomes.get("evapotranspiration")),
        },
    }
    return result


def _map_water(outcomes: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise the water metrics, deriving a descriptive stress level.

    The stress level is a descriptive band over the NDWI mean, never a
    diagnosis: high NDWI (more surface water) is described as low stress.
    """
    ndwi_stats = _extract_min_max(outcomes.get("ndwi"))
    ndwi_mean = ndwi_stats.get("mean")
    if ndwi_mean is None:
        stress_level: Optional[str] = None
    elif ndwi_mean > 0.2:
        stress_level = "low"
    elif ndwi_mean >= 0.0:
        stress_level = "moderate"
    else:
        stress_level = "high"

    result = dict(base)
    result["water"] = {
        "ndwi": ndwi_stats,
        "soil_moisture": _extract_min_max(outcomes.get("soil_moisture_surface")),
        "precipitation": {"total": _extract_value(outcomes.get("precipitation"))},
        "stress_level": stress_level,
    }
    return result


def _map_soil(outcomes: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise soil moisture and soil property metrics."""
    texture_value = _extract_value(outcomes.get("soil_texture_class"))
    result = dict(base)
    result["soil"] = {
        "soil_moisture": _extract_min_max(outcomes.get("soil_moisture_surface")),
        "organic_carbon": _extract_min_max(outcomes.get("soil_organic_carbon")),
        "ph": _extract_min_max(outcomes.get("soil_ph")),
        "sand": _extract_value(outcomes.get("soil_sand_content")),
        "clay": _extract_value(outcomes.get("soil_clay_content")),
        "silt": _extract_value(outcomes.get("soil_silt_content")),
        "texture": {"class": texture_value},
    }
    return result


def _map_stress(outcomes: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise the stress metrics into the analysis contract."""
    result = dict(base)
    result["stress"] = {
        "evaporative_fraction": _extract_min_max(
            outcomes.get("evaporative_fraction")
        ),
        "vpd_anomaly": _extract_min_max(outcomes.get("vpd_anomaly")),
        "lst_day_anomaly": _extract_min_max(outcomes.get("lst_day_anomaly")),
    }
    return result


def _map_irrigation(outcomes: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise the irrigation metrics into the analysis contract."""
    result = dict(base)
    result["irrigation"] = {
        "precipitation_cumulative": _extract_min_max(
            outcomes.get("precipitation_cumulative")
        ),
        "et_precipitation_deficit": _extract_min_max(
            outcomes.get("et_precipitation_deficit")
        ),
        "precipitation_anomaly": _extract_min_max(
            outcomes.get("precipitation_anomaly")
        ),
    }
    return result


_DOMAIN_MAPPERS = {
    "climate": _map_climate,
    "water": _map_water,
    "soil": _map_soil,
    "stress": _map_stress,
    "irrigation": _map_irrigation,
}


def _geometry_area_sq_m(geometry: Dict[str, Any]) -> Optional[float]:
    """Area of the requested geometry in square metres, when it has one.

    A point geometry has no area. That is not an error and must not be
    papered over with a guessed value: the reduction still returns the class
    of the pixel the point falls in, and the coverage percentages simply
    lose their denominator. Reporting a fabricated area would turn a
    location query into a false land-cover-extent claim.
    """
    return calculate_area_sq_meters(geometry)


class AnalysisService:
    """Orchestrates analysis operations."""
    
    async def create_analysis(
        self,
        db: AsyncSession,
        geometry: Dict[str, Any],
        start_date: str,
        end_date: str,
        analysis_type: str = "complete",
        temporal_resolution: str = "monthly",
        location_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Create and run an analysis.
        
        Args:
            db: Database session.
            geometry: GeoJSON geometry.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            analysis_type: Type of analysis.
            temporal_resolution: Temporal aggregation.
            location_id: Optional existing location ID.
        
        Returns:
            Analysis results.
        """
        analysis_id = str(uuid.uuid4())
        logger.info(f"Creating analysis {analysis_id}: {analysis_type}")

        # Cache is checked at this service boundary, before any Earth Engine
        # work: an equivalent repeated request must not rebuild the geometry
        # or re-execute a single metric (Phase S.4 contract). The cached
        # object is the full result envelope, so a cache-hit response is
        # field-for-field identical to a fresh one. Cache failures are
        # logged and never fatal (Phase S.4 failure-non-fatal behaviour).
        from app.services.cache_service import cache_service

        cache_key = cache_service._make_key(
            kind="create_analysis",
            geometry=geometry,
            start_date=start_date,
            end_date=end_date,
            analysis_type=analysis_type,
        )
        try:
            cached = cache_service.get(cache_key)
        except Exception as cache_exc:  # noqa: BLE001 - cache is never fatal
            logger.warning(
                "Analysis %s: cache lookup failed (%s), proceeding",
                analysis_id,
                type(cache_exc).__name__,
            )
            cached = None

        if cached is not None:
            logger.info("Analysis %s: cache hit", analysis_id)
            return dict(cached)

        try:
            # Create EE geometry
            ee_geometry = create_ee_geometry(geometry)
            
            # Run analysis based on type
            if analysis_type in ("complete", "vegetation"):
                result = await self._run_vegetation_analysis(
                    ee_geometry, start_date, end_date
                )
            elif analysis_type == "landcover":
                result = await self._run_landcover_analysis(
                    ee_geometry, geometry, start_date, end_date
                )
            elif analysis_type in _ANALYSIS_TYPE_DOMAINS:
                result = self._run_domain_analysis(
                    ee_geometry, geometry, start_date, end_date, analysis_type
                )
            else:
                result = {
                    "status": "not_implemented",
                    "message": f"Analysis type '{analysis_type}' not yet implemented",
                }
            
            envelope = {
                "id": analysis_id,
                "analysis_type": analysis_type,
                "status": "completed" if result.get("status") == "completed" else "failed",
                "start_date": start_date,
                "end_date": end_date,
                "temporal_resolution": temporal_resolution,
                "result_data": result,
                "completed_at": datetime.utcnow().isoformat(),
            }

            # Only a completed analysis is worth caching; a failed or
            # not_implemented outcome must never be served as a hit later
            # (Phase S.4/S.5: failed analyses are not cached).
            if envelope["status"] == "completed":
                try:
                    cache_service.set(cache_key, envelope)
                except Exception as cache_exc:  # noqa: BLE001 - cache is never fatal
                    logger.warning(
                        "Analysis %s: cache write failed (%s)",
                        analysis_id,
                        type(cache_exc).__name__,
                    )

            return envelope
            
        except Exception as e:
            logger.error(f"Analysis {analysis_id} failed: {e}")
            return {
                "id": analysis_id,
                "analysis_type": analysis_type,
                "status": "failed",
                "error_message": str(e),
                "completed_at": datetime.utcnow().isoformat(),
            }
    
    async def _run_vegetation_analysis(
        self,
        geometry: Any,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """Run vegetation analysis."""
        return compute_vegetation_analysis(
            geometry=geometry,
            start_date=start_date,
            end_date=end_date,
        )

    async def _run_landcover_analysis(
        self,
        ee_geometry: Any,
        geometry: Dict[str, Any],
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """Run the land cover analysis.

        The computation lives entirely in the agriculture metric layer; this
        method only builds the context, runs the metrics through the shared
        executor, and serialises their results into the payload the API and
        the frontend consume.

        Two properties matter here and are enforced rather than assumed:

        * **Class codes are reported as the product publishes them.** There
          is no IGBP class 0, and Water Bodies is class 17. Nothing is
          renumbered to match a consumer's legend.
        * **An out-of-coverage request is reported as unavailable.** The
          product stops at 2024-01-01, so a request for a later year yields
          an explicit "not available" payload, never a substituted year.

        The metrics are run through the shared executor so a failure in one
        cannot discard the other, and so error messages are sanitised before
        they can reach a client.

        Returns:
            The standard analysis envelope, whose ``result_data`` nests the
            land cover block under ``"landcover"``. That nesting is what the
            existing ``/{analysis_id}/landcover`` endpoint reads, and it is
            preserved here rather than reshaped.
        """
        # A metric lookup against an empty registry would report "unknown
        # metric" for every key and degrade the analysis to nothing, so the
        # registry is guaranteed populated here rather than assumed.
        ensure_registered()

        context = MetricContext(
            geometry=ee_geometry,
            start_date=start_date,
            end_date=end_date,
            geometry_key=json.dumps(geometry, sort_keys=True, default=str),
            scale=LANDCOVER_WORKING_SCALE,
            options={
                # Used to derive total_pixel_count, so coverage percentages
                # are measured against the geometry rather than against the
                # classes that happen to be present.
                "area_sq_m": _geometry_area_sq_m(geometry),
            },
        )

        outcomes, unknown = execute_metrics(
            LANDCOVER_METRIC_KEYS, context, max_workers=2
        )

        class_outcome = outcomes.get("land_cover_class")
        quality_outcome = outcomes.get("land_cover_quality")

        class_result = class_outcome.result if class_outcome else None

        landcover: Dict[str, Any] = {
            "dataset": MCD12Q1,
            "product": "MODIS Land Cover Type (MCD12Q1)",
            "spatial_resolution_m": LANDCOVER_WORKING_SCALE,
            "temporal_resolution": "annual",
            "class_scheme": "IGBP (LC_Type1)",
            "classes": {},
            "dominant_class": None,
        }

        if unknown:
            landcover["unknown_metrics"] = unknown

        if class_result is None:
            landcover["status"] = "error"
            landcover["message"] = "Land cover metric was not executed."
            return {"status": "failed", "landcover": landcover}

        landcover["status"] = class_result.status
        landcover["reason"] = class_result.reason
        landcover["message"] = class_result.message
        landcover["provenance"] = (
            class_result.provenance.to_dict()
            if class_result.provenance is not None
            else None
        )
        landcover["warnings"] = list(class_result.warnings)

        if class_result.class_histogram is not None:
            histogram = class_result.class_histogram

            # ``classes`` maps class code to percentage, which is the shape
            # the existing consumer reads. The codes are the IGBP codes the
            # product publishes: 12, 14 and 17 are what they are.
            landcover["classes"] = {
                str(entry.code): entry.percent for entry in histogram.entries
            }
            landcover["class_details"] = [
                entry.to_dict() for entry in histogram.entries
            ]
            landcover["dominant_class"] = (
                str(histogram.dominant_code)
                if histogram.dominant_code is not None
                else None
            )
            landcover["dominant_class_name"] = histogram.dominant_name

            # Area is derived from the pixel count at the product's own grid,
            # so the figure and the resolution it rests on travel together.
            pixel_area = float(LANDCOVER_WORKING_SCALE) ** 2
            landcover["total_area_sq_meters"] = (
                histogram.valid_pixel_count * pixel_area
            )
            landcover["total_pixel_count"] = histogram.total_pixel_count
            landcover["valid_pixel_count"] = histogram.valid_pixel_count

            # State the mismatch rather than hiding it: an IGBP map has no
            # class 0, so a consumer whose legend keys water at "0" will not
            # find it. The backend report is the correct channel for this.
            if histogram.dominant_code == IGBP_WATER_BODIES:
                landcover.setdefault("warnings", []).append(
                    "Water is reported as IGBP class 17. A consumer that "
                    "maps water to class 0 will not render this correctly; "
                    "the IGBP legend has no class 0."
                )
        else:
            # No fiction: no zero-filled class table standing in for a real
            # distribution, and no dominant class invented.
            landcover["classes"] = {}
            landcover["dominant_class"] = None

        if quality_outcome is not None:
            quality_result = quality_outcome.result
            landcover["quality"] = {
                "status": quality_result.status,
                "product": "MCD12Q1 QC flags",
                "note": (
                    "QC values are unordered post-processing event codes, "
                    "not a confidence score. No aggregate quality index is "
                    "derived from them."
                ),
                "flags": (
                    {
                        str(entry.code): entry.pixel_count
                        for entry in quality_result.class_histogram.entries
                    }
                    if quality_result.class_histogram is not None
                    else {}
                ),
                "warnings": list(quality_result.warnings),
            }

        # The analysis itself ran to completion. "No data for this period"
        # is a correct answer, not a failure, so the outer status is
        # ``completed`` and the outcome — ok, insufficient or unavailable —
        # is carried by the land cover block's own status. Mapping an
        # unavailable result to ``failed`` here would present a scientific
        # "we do not know" as an operational error.
        return {
            "status": "completed",
            "landcover": landcover,
        }

    def _run_domain_analysis(
        self,
        ee_geometry: Any,
        geometry: Dict[str, Any],
        start_date: str,
        end_date: str,
        analysis_type: str,
    ) -> Dict[str, Any]:
        """Run one agriculture-engine domain and map it to the contract.

        Executes every registered metric of the domain through the shared
        executor (per-metric error isolation included), then serialises the
        outcomes with the domain's mapper. A successful result is cached
        under the same SHA-256 key discipline as the agriculture API;
        cache failures are logged and never fatal.
        """
        import time as _time

        from app.services.agriculture.types import STATUS_OK
        from app.services.cache_service import cache_service

        started = _time.perf_counter()
        domains = _ANALYSIS_TYPE_DOMAINS[analysis_type]

        from app.services.agriculture.catalog import metrics_in_domain

        metric_keys: List[str] = []
        for domain in domains:
            metric_keys.extend(m.key for m in metrics_in_domain(domain))

        cache_key = cache_service._make_key(
            kind="domain_analysis",
            analysis_type=analysis_type,
            geometry=geometry,
            start_date=start_date,
            end_date=end_date,
            domains=sorted(domains),
        )
        try:
            cached = cache_service.get(cache_key)
        except Exception as cache_exc:  # noqa: BLE001 - cache is never fatal
            logger.warning(
                "Domain analysis %s: cache lookup failed (%s), proceeding",
                analysis_type,
                type(cache_exc).__name__,
            )
            cached = None

        if cached is not None:
            logger.info("Domain analysis %s: cache hit", analysis_type)
            return cached

        mapper = _DOMAIN_MAPPERS[analysis_type]

        # A point geometry has no area; the coverage denominators then work
        # from the reduction itself rather than a fabricated area figure.
        area_sq_m = _geometry_area_sq_m(geometry)

        context = MetricContext(
            geometry=ee_geometry,
            start_date=start_date,
            end_date=end_date,
            geometry_key=json.dumps(geometry, sort_keys=True, default=str),
            cloud_max_percent=20.0,
            options={"area_sq_m": area_sq_m} if area_sq_m else {},
        )

        outcomes, unknown = execute_metrics(metric_keys, context)

        usable = {
            key: outcome
            for key, outcome in outcomes.items()
            if outcome.result is not None and outcome.result.status == STATUS_OK
        }
        base = {
            "status": "completed",
            "analysis_type": analysis_type,
            "domains": domains,
            "data_quality": "acceptable" if usable else "insufficient",
            "image_count": sum(
                (o.result.provenance.image_count or 0) if o.result.provenance else 0
                for o in outcomes.values()
                if o.result is not None
            ),
            "metadata": {
                "metrics_executed": str(len(outcomes)),
                "metrics_usable": str(len(usable)),
                "unknown_metrics": str(len(unknown)),
            },
        }
        result = mapper(outcomes, base)

        try:
            cache_service.set(cache_key, result)
        except Exception as cache_exc:  # noqa: BLE001 - cache is never fatal
            logger.warning(
                "Domain analysis %s: cache write failed (%s)",
                analysis_type,
                type(cache_exc).__name__,
            )

        logger.info(
            "Domain analysis %s completed in %.1f ms "
            "(metrics=%d, unknown=%d)",
            analysis_type,
            (_time.perf_counter() - started) * 1000.0,
            len(outcomes),
            len(unknown),
        )
        return result

    def get_analysis_summary(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract summary from analysis result."""
        stats = result_data.get("statistics", {})
        ndvi = stats.get("NDVI", {})
        
        return {
            "vegetation_health": result_data.get("vegetation_health", "unknown"),
            "ndvi_mean": ndvi.get("mean"),
            "data_quality": result_data.get("data_quality", "unknown"),
            "image_count": result_data.get("image_count", 0),
            "interpretation": result_data.get("interpretation", ""),
        }


analysis_service = AnalysisService()
