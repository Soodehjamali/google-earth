"""Acceptance diagnosis: run one metric in-process through the production path."""

import json, traceback

import ee
from app.services.earth_engine.authentication import initialize_earth_engine
initialize_earth_engine()


from app.utils.geometry import create_ee_geometry
from app.services.agriculture import ensure_registered
from app.services.agriculture.base import MetricContext
from app.services.agriculture.executor import execute_metrics
from app.services.agriculture.catalog import get_metric, metric_keys

ensure_registered()
keys = metric_keys()
print(f"{len(keys)} metrics registered")

geom = create_ee_geometry({
    "type": "Polygon",
    "coordinates": [[[51.80, 32.45],[51.842, 32.45],[51.842, 32.482],[51.80, 32.482],[51.80, 32.45]]],
})
ctx = MetricContext(
    geometry=geom,
    start_date="2024-04-01",
    end_date="2024-06-30",
    geometry_key="diag",
    cloud_max_percent=20.0,
)

# 1. can_attempt probes
for k in ("precipitation", "ndvi", "temperature_mean", "soil_moisture_surface"):
    m = get_metric(k)
    try:
        ok, reason = m.can_attempt(ctx)
        print(f"can_attempt {k}: {ok} reason={reason}")
    except Exception as e:
        print(f"can_attempt {k}: RAISED {type(e).__name__}: {e}")

# 2. Execute a small subset
outcomes, unknown = execute_metrics(["precipitation", "ndvi"], ctx)
for k, o in outcomes.items():
    r = o.result
    if r is None:
        print(f"{k}: result=None error={o.error}")
    else:
        print(f"{k}: status={r.status} quality={r.quality} value={r.value}")
        if r.status != "observed" and r.status != "derived":
            try:
                print(f"   reason={getattr(r, 'reason', None)} message={getattr(r, 'message', None)}")
            except Exception:
                pass
