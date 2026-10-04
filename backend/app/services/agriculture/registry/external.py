"""Registry entries for data sources outside the Google Earth Engine catalog.

These datasets cannot be reached through the Earth Engine Python API and
require a separate client. They are kept apart from the GEE registry so it
is always obvious which metrics depend on an external service.

STATUS OF THE SOILGRIDS REST API
--------------------------------
The ISRIC SoilGrids REST API (``https://rest.isric.org/soilgrids/v2.0/``)
was **paused** during the original verification pass, so the conversion
factors below were carried as ``PENDING_VERIFICATION``. The official
ISRIC documentation (``docs.isric.org``, "SoilGrids layers" FAQ) has since
been re-consulted and confirms both the mapped units and the conversion
factors: "All maps produced with SoilGrids store data as integer values ...
By dividing the predictions values by the values in the Conversion factor
column, the user can obtain the more familiar units in the Conventional
units column."

Consequences for this module:

* The d-factors and conventional units are now **verified** against the
  official ISRIC table and are flagged accordingly.
* The client is built and correct, but may still legitimately return
  ``unavailable`` while the service itself is paused. That is honest
  behaviour, not a bug.
* Nothing here invents a number. The factors are the ones ISRIC publishes,
  not approximations.
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
#: Mapped units, conversion (d-)factors and conventional units are taken
#: verbatim from ISRIC's official "SoilGrids layers" documentation table
#: (docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html), consulted
#: 2026-09: bdod cg/cm3 ÷100 → kg/dm3; cec mmol(c)/kg ÷10 → cmol(c)/kg;
#: cfvo cm3/dm3 ÷10 → cm3/100cm3; clay/sand/silt g/kg ÷10 → %;
#: nitrogen cg/kg ÷100 → g/kg; soc dg/kg ÷10 → g/kg; phh2o pH×10 ÷10 → pH.
SOILGRIDS_PROPERTIES: Dict[str, SoilGridsProperty] = {
    "clay": SoilGridsProperty(
        "clay", "Clay content", "%", 10, True, (0.0, 1000.0),
        "Conventional unit is % (g/100g) after dividing the raw g/kg value by 10.",
    ),
    "sand": SoilGridsProperty(
        "sand", "Sand content", "%", 10, True, (0.0, 1000.0),
        "Conventional unit is % (g/100g) after dividing the raw g/kg value by 10.",
    ),
    "silt": SoilGridsProperty(
        "silt", "Silt content", "%", 10, True, (0.0, 1000.0),
        "Conventional unit is % (g/100g) after dividing the raw g/kg value by 10.",
    ),
    "soc": SoilGridsProperty(
        "soc", "Soil organic carbon", "g/kg", 10, True, (0.0, 1000.0),
        "Conventional unit is g/kg after dividing the raw dg/kg value by 10.",
    ),
    "bdod": SoilGridsProperty(
        "bdod", "Bulk density of the fine earth fraction", "kg/dm3", 100, True, (0.0, 300.0),
        "Conventional unit is kg/dm3 after dividing the raw cg/cm3 value by 100.",
    ),
    "phh2o": SoilGridsProperty(
        "phh2o", "Soil pH in water", "pH", 10, True, (0.0, 140.0),
        "Mapped unit is pH x 10; dividing by 10 returns pH.",
    ),
    "nitrogen": SoilGridsProperty(
        "nitrogen", "Total nitrogen", "g/kg", 100, True, (0.0, 100.0),
        "Conventional unit is g/kg after dividing the raw cg/kg value by 100.",
    ),
    "cec": SoilGridsProperty(
        "cec", "Cation exchange capacity buffered at pH7", "cmol(c)/kg", 10, True, (0.0, 1000.0),
        "Conventional unit is cmol(c)/kg after dividing the raw mmol(c)/kg value by 10.",
    ),
    "cfvo": SoilGridsProperty(
        "cfvo", "Coarse fragments", "cm3/100cm3", 10, True, (0.0, 1000.0),
        "Mapped unit is cm3/dm3 (vol per mille); dividing by 10 gives cm3/100cm3 (vol%).",
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
            "clay", "Clay content", "%",
            0.1, 0.0, (0.0, 100.0), ()),
        "sand": BandSpec(
            "sand", "Sand content", "%",
            0.1, 0.0, (0.0, 100.0), ()),
        "silt": BandSpec(
            "silt", "Silt content", "%",
            0.1, 0.0, (0.0, 100.0), ()),
        "soc": BandSpec(
            "soc", "Soil organic carbon", "g/kg",
            0.1, 0.0, (0.0, 1000.0), ()),
        "bdod": BandSpec(
            "bdod", "Bulk density", "kg/dm3",
            0.01, 0.0, (0.0, 3.0), ()),
        "phh2o": BandSpec(
            "phh2o", "Soil pH in water", "pH",
            0.1, 0.0, (0.0, 14.0), ()),
        "nitrogen": BandSpec(
            "nitrogen", "Total nitrogen", "g/kg",
            0.01, 0.0, (0.0, 100.0), ()),
        "cec": BandSpec(
            "cec", "Cation exchange capacity", "cmol(c)/kg",
            0.1, 0.0, (0.0, 100.0), ()),
        "cfvo": BandSpec(
            "cfvo", "Coarse fragments", "cm3/100cm3",
            0.1, 0.0, (0.0, 100.0), ()),
    },
    caveats=(
        "This source is a spatial prediction product produced by machine learning on sparse soil profile observations. It is not a measurement of the soil at your location.",
        "Effective predictive resolution is materially coarser than the nominal 250 m grid cell.",
        "Reported uncertainty is large for most properties, and especially so for organic carbon.",
        "The REST API is documented by ISRIC as beta with no uptime guarantee. It was observed to be paused during development.",
        "Conversion factors and conventional units were verified against ISRIC's official SoilGrids documentation (docs.isric.org, 'SoilGrids layers' table) after the earlier API outage; the mapped units and d-factors used here are ISRIC's published values.",
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
