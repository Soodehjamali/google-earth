"""Pure vegetation index formulas.

These functions take and return plain numbers. They contain no Earth
Engine calls, which means the maths is unit testable without credentials
and is the single place where each formula is written down.

The Earth Engine variants in :mod:`app.services.agriculture.vegetation`
mirror these exactly. If the two ever disagree, the tests here define
which is correct.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

__all__ = [
    "ndvi",
    "evi",
    "savi",
    "msavi",
    "ndre",
    "ndwi",
    "ndmi",
    "mndwi",
    "safe_normalized_difference",
    "FORMULA_TEXT",
]


def safe_normalized_difference(
    a: Optional[float],
    b: Optional[float],
) -> Optional[float]:
    """Compute ``(a - b) / (a + b)`` with all the guards that implies.

    Returns ``None`` whenever the result would be undefined or
    meaningless:

    * either input missing or non-finite
    * denominator zero, which happens when both bands are zero

    Returning ``None`` rather than a substituted zero matters because a
    zero here would be indistinguishable from a genuine mid-range index
    value and would silently enter field statistics.
    """
    if a is None or b is None:
        return None
    if not isinstance(a, (int, float)) or isinstance(a, bool):
        return None
    if not isinstance(b, (int, float)) or isinstance(b, bool):
        return None
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    denominator = a + b
    if denominator == 0:
        return None
    return (a - b) / denominator


def ndvi(nir: Optional[float], red: Optional[float]) -> Optional[float]:
    """Normalized Difference Vegetation Index.

    ``(NIR - RED) / (NIR + RED)``

    The workhorse greenness index. Saturates in dense canopies and is
    sensitive to soil background in sparse ones.
    """
    return safe_normalized_difference(nir, red)


def evi(
    nir: Optional[float],
    red: Optional[float],
    blue: Optional[float],
) -> Optional[float]:
    """Enhanced Vegetation Index.

    ``2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)``

    Resists atmospheric haze and canopy background better than NDVI, at
    the cost of needing the blue band and being noisier over sparse
    vegetation.
    """
    values = (nir, red, blue)
    for value in values:
        if value is None or isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
    assert nir is not None and red is not None and blue is not None
    denominator = nir + 6.0 * red - 7.5 * blue + 1.0
    if denominator == 0:
        return None
    return 2.5 * (nir - red) / denominator


def savi(
    nir: Optional[float],
    red: Optional[float],
    soil_factor: float = 0.5,
) -> Optional[float]:
    """Soil-Adjusted Vegetation Index.

    ``((NIR - RED) / (NIR + RED + L)) * (1 + L)`` with ``L = 0.5``

    The default ``L`` of 0.5 suits intermediate vegetation cover. ``L=1``
    is for sparse canopies, ``L=0.25`` for dense ones. Whatever value a
    caller uses must be reported in the provenance, because the same
    reflectance can yield different SAVI values.
    """
    values = (nir, red)
    for value in values:
        if value is None or isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
    if not math.isfinite(soil_factor):
        return None
    assert nir is not None and red is not None
    denominator = nir + red + soil_factor
    if denominator == 0:
        return None
    return ((nir - red) / denominator) * (1.0 + soil_factor)


def msavi(nir: Optional[float], red: Optional[float]) -> Optional[float]:
    """Modified Soil-Adjusted Vegetation Index.

    ``(2*NIR + 1 - sqrt((2*NIR + 1)^2 - 8*(NIR - RED))) / 2``

    Self-adjusting for soil background, so it needs no ``L`` parameter.
    The term under the square root can go negative for some reflectance
    combinations; that query is undefined and returns ``None`` rather
    than a complex number or a clamped guess.
    """
    values = (nir, red)
    for value in values:
        if value is None or isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
    assert nir is not None and red is not None

    term = (2.0 * nir + 1.0) ** 2 - 8.0 * (nir - red)
    if term < 0:
        return None
    return (2.0 * nir + 1.0 - math.sqrt(term)) / 2.0


def ndre(nir: Optional[float], red_edge: Optional[float]) -> Optional[float]:
    """Normalized Difference Red Edge.

    ``(NIR - REDEDGE) / (NIR + REDEDGE)``

    Uses the 705 nm red edge band. More sensitive to chlorophyll content
    and to early stress than NDVI, and it saturates later in dense
    canopies, which makes it useful for nitrogen and chlorophyll-related
    signals. It is not a nitrogen measurement.
    """
    return safe_normalized_difference(nir, red_edge)


def ndwi(green: Optional[float], nir: Optional[float]) -> Optional[float]:
    """Normalized Difference Water Index (McFeeters).

    ``(GREEN - NIR) / (GREEN + NIR)``

    Targets open water. Positive values indicate water surfaces.
    """
    return safe_normalized_difference(green, nir)


def ndmi(
    nir: Optional[float],
    swir1: Optional[float],
) -> Optional[float]:
    """Normalized Difference Moisture Index (Gao).

    ``(NIR - SWIR1) / (NIR + SWIR1)``

    Sensitive to vegetation water content rather than to open water. This
    is the index to use for crop water status; NDWI will not serve that
    purpose.
    """
    return safe_normalized_difference(nir, swir1)


def mndwi(
    green: Optional[float],
    swir1: Optional[float],
) -> Optional[float]:
    """Modified Normalized Difference Water Index (Xu).

    ``(GREEN - SWIR1) / (GREEN + SWIR1)``

    Generally outperforms NDWI for water delineation in built-up and
    vegetated surroundings, because SWIR1 suppresses vegetation and
    shadow better than NIR.
    """
    return safe_normalized_difference(green, swir1)


#: Human-readable formula text, surfaced in provenance so every value can
#: be traced to the expression that produced it.
FORMULA_TEXT = {
    "ndvi": "(B8 - B4) / (B8 + B4)",
    "evi": "2.5 * (B8 - B4) / (B8 + 6*B4 - 7.5*B2 + 1)",
    "savi": "((B8 - B4) / (B8 + B4 + L)) * (1 + L), L = 0.5",
    "msavi": "(2*B8 + 1 - sqrt((2*B8 + 1)^2 - 8*(B8 - B4))) / 2",
    "ndre": "(B8 - B5) / (B8 + B5)",
    "ndwi": "(B3 - B8) / (B3 + B8)",
    "ndmi": "(B8 - B11) / (B8 + B11)",
    "mndwi": "(B3 - B11) / (B3 + B11)",
}

#: Ordered red, near-infrared, blue, green, red edge, SWIR1 by band name,
#: used to build Earth Engine expressions from the same definitions.
BAND_ROLES = {
    "ndvi": ("B8", "B4"),
    "evi": ("B8", "B4", "B2"),
    "savi": ("B8", "B4"),
    "msavi": ("B8", "B4"),
    "ndre": ("B8", "B5"),
    "ndwi": ("B3", "B8"),
    "ndmi": ("B8", "B11"),
    "mndwi": ("B3", "B11"),
}

#: Expected plausible value range per index, used to flag a result that is
#: mathematically valid but physically implausible.
EXPECTED_RANGE: dict = {
    "ndvi": (-1.0, 1.0),
    "evi": (-1.0, 1.0),
    "savi": (-1.5, 1.5),
    "msavi": (-1.0, 1.0),
    "ndre": (-1.0, 1.0),
    "ndwi": (-1.0, 1.0),
    "ndmi": (-1.0, 1.0),
    "mndwi": (-1.0, 1.0),
}

#: Typical range for vegetated land, used for interpretation only. These
#: are guides for a human reader, never thresholds for a diagnosis.
TYPICAL_VEGETATION_RANGE: dict = {
    "ndvi": (0.2, 0.8),
    "evi": (0.2, 0.6),
    "savi": (0.1, 0.7),
    "msavi": (0.1, 0.7),
    "ndre": (0.1, 0.5),
    "ndwi": (-0.5, 0.1),
    "ndmi": (0.0, 0.5),
    "mndwi": (-0.5, 0.0),
}
