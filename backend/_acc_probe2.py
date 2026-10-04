"""Temporary acceptance probe: reproduce endpoint behavior in-process."""

import json

from app.services.earth_engine.authentication import initialize_earth_engine

try:
    initialize_earth_engine()
    print("EE INIT: OK")
except Exception as e:  # noqa: BLE001
    print("EE INIT FAILED:", type(e).__name__, "|", str(e)[:150])
    raise SystemExit(2)

from app.services.agriculture import ensure_registered
from app.services.agriculture.base import MetricContext
from app.services.agriculture.catalog import metric_keys
from app.services.agriculture.executor import execute_metrics
from app.utils.geometry import create_ee_geometry

ensure_registered()
keys = metric_keys()
print("metrics:", len(keys))

geom = create_ee_geometry(json.load(open("_acc_req1.json"))["geometry"])
ctx = MetricContext(
    geometry=geom,
    start_date="2024-04-01",
    end_date="2024-06-30",
    geometry_key="diag2",
    cloud_max_percent=20.0,
)

outcomes, unknown = execute_metrics(keys[:6], ctx)
for k, o in outcomes.items():
    r = o.result
    print(
        k,
        "->",
        r.status if r is not None else None,
        "| value:",
        getattr(r, "value", None),
        "| err:",
        o.error_type,
        "| msg:",
        (getattr(r, "message", "") or "")[:110],
    )
