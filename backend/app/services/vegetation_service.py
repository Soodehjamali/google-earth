"""Vegetation analysis service."""

from typing import Any, Dict, Optional

import ee

from app.core.logging import get_logger
from app.core.exceptions import EarthEngineError, EmptyDatasetError
from app.services.earth_engine.statistics import compute_vegetation_analysis
from app.services.earth_engine.indices import get_all_index_definitions

logger = get_logger(__name__)


class VegetationService:
    """Service for vegetation analysis operations."""
    
    def analyze(
        self,
        geometry: Any,
        start_date: str,
        end_date: str,
        cloud_max_percent: int = 20,
        scale: int = 10,
    ) -> Dict[str, Any]:
        """Perform vegetation analysis.
        
        Args:
            geometry: Earth Engine geometry.
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            cloud_max_percent: Max cloud coverage.
            scale: Analysis resolution.
        
        Returns:
            Vegetation analysis results.
        """
        logger.info(f"Vegetation analysis: {start_date} to {end_date}")
        
        try:
            result = compute_vegetation_analysis(
                geometry=geometry,
                start_date=start_date,
                end_date=end_date,
                cloud_max_percent=cloud_max_percent,
                scale=scale,
            )
            
            if result["status"] == "no_data":
                raise EmptyDatasetError(
                    message="No cloud-free Sentinel-2 imagery available",
                    detail={"start_date": start_date, "end_date": end_date},
                )
            
            return result
            
        except EmptyDatasetError:
            raise
        except Exception as e:
            logger.error(f"Vegetation analysis failed: {e}")
            raise EarthEngineError(
                message=f"Vegetation analysis failed: {str(e)}",
                detail={"error": str(e)},
            )
    
    def get_index_definitions(self) -> Dict[str, Any]:
        """Get documentation for all vegetation indices."""
        return get_all_index_definitions()
