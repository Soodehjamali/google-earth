"""Land cover analysis endpoints.

This endpoint serves the land cover block a completed ``landcover``
analysis stored. It performs no computation of its own: the metric layer
computes, the analysis service orchestrates and serialises, and this
handler reads the stored payload back.

The response is the stored ``landcover`` block, unchanged. Two properties
of it are deliberate and are worth stating at the API boundary:

* **Class codes are the IGBP codes the product publishes.** There is no
  IGBP class 0. Water Bodies is class 17, Croplands is 12, and
  Cropland/Natural Vegetation Mosaics is 14. The ``classes`` mapping is
  keyed by those codes.

  The bundled frontend contains a ``LANDCOVER_CLASSES`` legend that maps
  ``'0'`` to Water and has no entry for ``'17'``, so water will not render
  under its own label and the dominant-class caption will fall back to the
  raw code. That is a defect in the consumer, and it is reported here
  rather than compensated for: emitting a class 0 to satisfy the legend
  would invent water where there is none and misattribute real water.
  See ``docs/AGRICULTURAL_ANALYTICS.md``.

* **An out-of-coverage request carries a reason, not a result.** The
  product is annual and stops at 2024-01-01, so a later request returns an
  unavailable payload with no classes and no area, rather than a
  substituted year.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.db.models.analysis import Analysis

logger = get_logger(__name__)
router = APIRouter()

#: The dataset this endpoint's payload describes, stated once.
LANDCOVER_DATASET = "MODIS/061/MCD12Q1"

#: The class code the product uses for Water Bodies. Named so the
#: frontend's class-0 expectation is visible in code, not only in prose.
IGBP_WATER_BODIES_CLASS = 17


@router.get("/{analysis_id}/landcover")
async def get_landcover_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get land cover analysis results.

    Returns the IGBP class distribution over the analysis geometry for the
    requested product year, as class code to percentage, together with the
    dominant class, the classified area, and the QC flag distribution.

    The payload is whatever the analysis stored. When the analysis has no
    land cover block — because it was a different analysis type, or it
    never ran — the response says so explicitly instead of returning an
    empty class table that could be read as "no land cover here".
    """
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    landcover_data = (
        analysis.result_data.get("landcover")
        if analysis.result_data
        else None
    )
    if landcover_data:
        return landcover_data

    # No block was stored. Distinguish "this analysis is not about land
    # cover" from "land cover ran but found nothing", because the second
    # would be a claim about the ground and the first is not.
    return {
        "status": "unavailable",
        "reason": "no_landcover_result_stored",
        "message": (
            "This analysis has no stored land cover result. Land cover "
            "results are produced by analyses created with "
            "analysis_type='landcover'."
        ),
        "analysis_id": str(analysis_id),
        "analysis_type": analysis.analysis_type,
        "dataset": LANDCOVER_DATASET,
        "class_scheme": "IGBP (LC_Type1)",
        "water_bodies_class": IGBP_WATER_BODIES_CLASS,
        "classes": {},
        "dominant_class": None,
    }
