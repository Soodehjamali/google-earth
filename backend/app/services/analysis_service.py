"""Analysis orchestration service."""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import ee
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.exceptions import AppException, EarthEngineError, AnalysisNotFoundError
from app.services.earth_engine.statistics import compute_vegetation_analysis
from app.utils.geometry import create_ee_geometry

logger = get_logger(__name__)


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
