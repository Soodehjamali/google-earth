"""Agricultural Intelligence Engine.

A modular analytics engine layered on top of the existing Earth Engine
integration. It is organised as a set of independent metric providers
sharing one registry, one quality policy, and one result type.

Layering::

    registry/  declares what datasets exist and how to read them
    types.py   defines the shared vocabulary (results, provenance, quality)
    quality.py pure quality policy, no network
    base.py    the metric provider contract and its shared context
    catalog.py the metric registry, populated by register_all_metrics()
    <domain>.py one module per scientific domain, e.g. vegetation, climate

The public entry point for the API layer is
:func:`app.services.agriculture.catalog.get_metric` and
:func:`app.services.agriculture.catalog.catalog`.

Registration is explicit rather than a side effect of importing a module.
Importing this package does not populate the registry; call
:func:`register_all_metrics` once during application startup. That keeps
imports cheap and lets tests build an isolated registry.
"""

from typing import List

from app.services.agriculture.types import (
    AggregationMethod,
    BandSpec,
    DatasetSpec,
    MeasurementBasis,
    MetricResult,
    Provenance,
    QualityLevel,
    SpatialStats,
)

__all__ = [
    "AggregationMethod",
    "BandSpec",
    "DatasetSpec",
    "MeasurementBasis",
    "MetricResult",
    "Provenance",
    "QualityLevel",
    "SpatialStats",
    "register_all_metrics",
    "ensure_registered",
]


def register_all_metrics() -> List[str]:
    """Register every metric from every domain module.

    Idempotent: registering the same metric twice replaces the earlier
    entry rather than raising, so this is safe to call from both the
    application startup hook and a test fixture.

    Returns the sorted list of registered metric keys, which is useful
    for logging at startup and for asserting coverage in tests.
    """
    from app.services.agriculture.catalog import register_metrics, metric_keys
    from app.services.agriculture.climate import CLIMATE_METRICS
    from app.services.agriculture.crop import (
        UNAVAILABLE_CROP_METRICS,
        CROP_METRICS,
    )
    from app.services.agriculture.landcover import (
        UNAVAILABLE_LANDCOVER_METRICS,
        LANDCOVER_METRICS,
        DYNAMIC_WORLD_METRICS,
    )
    from app.services.agriculture.soil import SOIL_METRICS
    from app.services.agriculture.terrain import (
        UNAVAILABLE_TERRAIN_METRICS,
        TERRAIN_METRICS,
    )
    from app.services.agriculture.thermal import THERMAL_METRICS
    from app.services.agriculture.vegetation import VEGETATION_METRICS
    from app.services.agriculture.phenology import (
        UNAVAILABLE_PHENOLOGY_METRICS,
        PHENOLOGY_METRICS,
    )
    from app.services.agriculture.water import (
        UNAVAILABLE_WATER_METRICS,
        WATER_METRICS,
    )

    register_metrics(VEGETATION_METRICS)
    register_metrics(CLIMATE_METRICS)
    register_metrics(THERMAL_METRICS)
    register_metrics(WATER_METRICS)
    register_metrics(SOIL_METRICS)
    register_metrics(LANDCOVER_METRICS)
    register_metrics(DYNAMIC_WORLD_METRICS)
    register_metrics(TERRAIN_METRICS)
    register_metrics(CROP_METRICS)
    register_metrics(PHENOLOGY_METRICS)
    # These are registered precisely so the catalog can answer "can this
    # system tell me about crop water stress, or which crop is growing
    # here, or how wet the ground is?" with a reasoned no, rather than with
    # silence that could be mistaken for an oversight.
    register_metrics(UNAVAILABLE_WATER_METRICS)
    register_metrics(UNAVAILABLE_LANDCOVER_METRICS)
    register_metrics(UNAVAILABLE_TERRAIN_METRICS)
    register_metrics(UNAVAILABLE_CROP_METRICS)
    register_metrics(UNAVAILABLE_PHENOLOGY_METRICS)

    return metric_keys()


def ensure_registered() -> List[str]:
    """Populate the metric registry if it is still empty.

    The registry is deliberately not populated as an import side effect, so
    that tests can build an isolated one. But an orchestration call must not
    depend on someone else having remembered to run the startup hook: if it
    did, every metric lookup would miss and the analysis would degrade into
    a silent "unknown metric" instead of a computed result.

    This is the guard for that. It is idempotent and cheap after the first
    call, and it never clears anything a caller has registered itself.
    """
    from app.services.agriculture.catalog import metric_keys

    existing = metric_keys()
    if existing:
        return existing
    return register_all_metrics()
