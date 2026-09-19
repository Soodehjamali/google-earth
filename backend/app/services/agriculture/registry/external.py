"""Registry entries for data sources outside the Google Earth Engine catalog.

These datasets cannot be reached through the Earth Engine Python API and
require a separate client. They are kept apart from the GEE registry so it
is always obvious which metrics depend on an external service.

STATUS OF THE SOILGRIDS REST API
--------------------------------
As of the verification pass for this engine, ISRIC's SoilGrids REST API
(``https://rest.isric.org/soilgrids/v2.0/``) is **paused**. ISRIC states
that they are experiencing service issues, have temporarily paused the
endpoint, and cannot give a restoration timeline. They also label the API
as beta with no uptime guarantee.

Consequences for this module:

* The client is built and correct, but will legitimately return
  ``unavailable`` while the service is paused. That is honest behaviour,
  not a bug.
* The exact conversion factors ('d-factors') and the literal depth
  interval strings could not be confirmed against the live Swagger
  documentation during the outage. They are therefore declared as
  :data:`PENDING_VERIFICATION` with the values recorded as reported by
  ISRIC's published specification, and flagged in ``caveats``.
* Nothing here invents a number. Where a factor is unverified, the
  registry says so and the metric reports lower confidence.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.services.agriculture.types import (
    PENDING_VERIFICATION,
    BandSpec,
    DatasetSpec,
    MeasurementBasis,
    TemporalKind,
)

__all__ = [
    "EXTERNAL_REGISTRY",
    "SOILGRIDS_PROPERTIES",
    "SOILGRIDS_DEPTHS",
    "SOILGRIDS_BASE_URL",
    "get_external_dataset",
    "get_external_datasets",
]

SOILGRIDS_BASE_URL = "https://rest.isric.org/soilgrids/v2.0/"

#: Standard GlobalSoilMap depth intervals, in centimetres.
#: These six intervals are the documented standard set. The literal
#: ``depth=`` query strings used by the v2.0 API are marked unverified
#: because the documentation was unreachable during the outage; the
#: client builds them from these tuples in the documented ``"0-5cm"`` form.
SOILGRIDS_DEPTHS: Tuple[str, ...] = (
    "0-5cm",
    "5-15cm",
    "15-30cm",
    "30-60cm",
    "60-100cm",
    "100-200cm",
)


class SoilGridsProperty:
    """Description of one SoilGrids property and its raw-to-physical scaling.

    ``d_factor`` is the divisor applied to the raw API value to reach the
    physical unit, per the ISRIC specification.
    """

    __slots__ = (
        "key", "description", "unit", "d_factor", "d_factor_verified",
        "valid_range", "notes",
    )

    def __init__(
        self,
        key: str,
        description: str,
        unit: str,
        d_factor: object,
        d_factor_verified: bool,
        valid_range: Optional[Tuple[float, float]] = None,
        notes: str = "",
    ) -> None:
        self.key = key
        self.description = description
        self.unit = unit
        self.d_factor = d_factor
        self.d_factor_verified = d_factor_verified
        self.valid_range = valid_range
        self.notes = notes

    def to_physical(self, raw_value: Optional[float]) -> Optional[float]:
        """Convert a raw SoilGrids value to its physical unit.

        Returns ``None`` when the conversion factor is unverified, so an
        unverified factor can never silently produce a number that looks
        authoritative.
        """
        if raw_value is None:
            return None
        if self.d_factor is PENDING_VERIFICATION or not self.d_factor_verified:
            return None
        return float(raw_value) / float(self.d_factor)  # type: ignore[arg-type]


#: SoilGrids properties used by this engine.
#:
#: The d-factor values below are those published by ISRIC for SoilGrids
#: v2.0. They are marked ``d_factor_verified=False`` because the live
#: documentation could not be reached during the verification pass while
#: the API was paused. They must be confirmed against
#: ``rest.isric.org/soilgrids/v2.0/docs`` before being promoted to
#: verified, at which point the client begins returning numeric values.
SOILGRIDS_PROPERTIES: Dict[str, SoilGridsProperty] = {
    "clay": SoilGridsProperty(
        "clay", "Clay content", "g/kg", 10, False, (0.0, 1000.0),
        "Reported as g/kg after dividing the raw value by 10.",
    ),
    "sand": SoilGridsProperty(
        "sand", "Sand content", "g/kg", 10, False, (0.0, 1000.0),
        "Reported as g/kg after dividing the raw value by 10.",
    ),
    "silt": SoilGridsProperty(
        "silt", "Silt content", "g/kg", 10, False, (0.0, 1000.0),
        "Reported as g/kg after dividing the raw value by 10.",
    ),
    "soc": SoilGridsProperty(
        "soc", "Soil organic carbon", "dg/kg", 10, False, (0.0, 1000.0),
        "Reported as dg/kg after dividing the raw value by 10.",
    ),
    "bdod": SoilGridsProperty(
        "bdod", "Bulk density of the fine earth fraction", "cg/cm3", 100, False, (0.0, 300.0),
        "Reported as cg/cm3 after dividing the raw value by 100.",
    ),
    "phh2o": SoilGridsProperty(
        "phh2o", "Soil pH in water", "pH", 10, False, (0.0, 14.0),
        "Reported as pH after dividing the raw value by 10.",
    ),
    "nitrogen": SoilGridsProperty(
        "nitrogen", "Total nitrogen", "cg/kg", 100, False, (0.0, 100.0),
        "Reported as cg/kg after dividing the raw value by 100.",
    ),
    "cec": SoilGridsProperty(
        "cec", "Cation exchange capacity", "mmol(c)/kg", 10, False, (0.0, 1000.0),
        "Reported as mmol(c)/kg after dividing the raw value by 10.",
    ),
}


EXTERNAL_REGISTRY: Dict[str, DatasetSpec] = {}

EXTERNAL_REGISTRY["ISRIC/SOILGRIDS/V2"] = DatasetSpec(
    id="ISRIC/SOILGRIDS/V2",
    name="ISRIC SoilGrids 250 m",
    name_fa="خاک‌های جهانی ISRIC",
    provider="ISRIC World Soil Information",
    description=(
        "Global gridded soil property predictions at 250 m, for six "
        "standard depth intervals, served over a REST API rather than "
        "through Earth Engine."
    ),
    spatial_resolution="250 m",
    temporal_resolution="static (predictions, not time series)",
    available_from="2017-01-01",
    available_to=None,
    temporal_kind=TemporalKind.STATIC,
    measurement_basis=MeasurementBasis.MODELLED,
    roles=("primary", "external"),
    bands={
        "clay": BandSpec(
            "clay", "Clay content", "g/kg",
            0.1, 0.0, (0.0, 1000.0), (PENDING_VERIFICATION,)),
        "sand": BandSpec(
            "sand", "Sand content", "g/kg",
            0.1, 0.0, (0.0, 1000.0), (PENDING_VERIFICATION,)),
        "silt": BandSpec(
            "silt", "Silt content", "g/kg",
            0.1, 0.0, (0.0, 1000.0), (PENDING_VERIFICATION,)),
        "soc": BandSpec(
            "soc", "Soil organic carbon", "dg/kg",
            0.1, 0.0, (0.0, 1000.0), (PENDING_VERIFICATION,)),
        "bdod": BandSpec(
            "bdod", "Bulk density", "cg/cm3",
            0.01, 0.0, (0.0, 300.0), (PENDING_VERIFICATION,)),
        "phh2o": BandSpec(
            "phh2o", "Soil pH in water", "pH",
            0.1, 0.0, (0.0, 14.0), (PENDING_VERIFICATION,)),
        "nitrogen": BandSpec(
            "nitrogen", "Total nitrogen", "cg/kg",
            0.01, 0.0, (0.0, 100.0), (PENDING_VERIFICATION,)),
        "cec": BandSpec(
            "cec", "Cation exchange capacity", "mmol(c)/kg",
            0.1, 0.0, (0.0, 1000.0), (PENDING_VERIFICATION,)),
    },
    caveats=(
        "This source is a spatial prediction product produced by machine learning on sparse soil profile observations. It is not a measurement of the soil at your location.",
        "Effective predictive resolution is materially coarser than the nominal 250 m grid cell.",
        "Reported uncertainty is large for most properties, and especially so for organic carbon.",
        "The REST API is documented by ISRIC as beta with no uptime guarantee. It was observed to be paused during development.",
        "Conversion factors and depth interval strings could not be verified against live documentation during the outage and are marked pending; metrics sourced here report reduced confidence until that is resolved.",
    ),
    citation="SoilGrids 250m v2.0, Poggio et al. 2021, ISRIC",
    docs_url="https://www.isric.org/explore/soilgrids",
)


def get_external_dataset(dataset_id: str) -> DatasetSpec:
    try:
        return EXTERNAL_REGISTRY[dataset_id]
    except KeyError:
        raise KeyError(
            f"External dataset {dataset_id!r} is not registered."
        ) from None


def get_external_datasets() -> List[DatasetSpec]:
    return [EXTERNAL_REGISTRY[k] for k in sorted(EXTERNAL_REGISTRY)]
