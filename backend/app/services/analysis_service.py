"""Analysis orchestration service."""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

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
            else:
                result = {
                    "status": "not_implemented",
                    "message": f"Analysis type '{analysis_type}' not yet implemented",
                }
            
            return {
                "id": analysis_id,
                "analysis_type": analysis_type,
                "status": "completed" if result.get("status") == "completed" else "failed",
                "start_date": start_date,
                "end_date": end_date,
                "temporal_resolution": temporal_resolution,
                "result_data": result,
                "completed_at": datetime.utcnow().isoformat(),
            }
            
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
