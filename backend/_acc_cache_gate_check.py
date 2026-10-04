"""Phase A1 verification: cache gate against audit response shapes."""

import json

from app.api.v1.agriculture import _response_has_usable_measurement
from app.schemas.agriculture import AgriculturalAnalysisResponse

# 1. Audit outage capture: HTTP 200, 118 metrics all unavailable.
outage = json.load(open("_acc_resp1.json"))
outage.pop("validation", None)
model = AgriculturalAnalysisResponse.model_validate(outage)
print(
    "audit outage response cacheable:",
    _response_has_usable_measurement(model),
)
assert not _response_has_usable_measurement(model)

# 2. Empty response (no bundles/sections) must also be refused.
empty = AgriculturalAnalysisResponse()
print("empty response cacheable:", _response_has_usable_measurement(empty))
assert not _response_has_usable_measurement(empty)

# 3. A response with one usable evidence item is cacheable.
usable = outage | {
    "evidence_bundles": {
        "vegetation": {"name": "vegetation",
            "items": [
                {
                    "metric_key": "evi",
                    "value": 0.2,
                    "unit": "index",
                    "status": "derived",
                    "quality": "good",
                    "is_usable": True,
                }
            ]
        }
    }
}
model_usable = AgriculturalAnalysisResponse.model_validate(usable)
print("usable evidence response cacheable:",
      _response_has_usable_measurement(model_usable))
assert _response_has_usable_measurement(model_usable)

# 4. Usable temporal point without bundles is cacheable.
temporal_only = outage | {
    "evidence_bundles": {},
    "temporal": {
        "window_start": "2024-04-01",
        "window_end": "2024-06-30",
        "profiles": {
            "ndvi": {
                "metric_key": "ndvi",
                "window_start": "2024-04-01",
                "window_end": "2024-06-30",
                "points": [
                    {"window_start": "2024-04-01",
                     "window_end": "2024-04-30",
                     "value": 0.4}
                ],
            }
        },
    },
}
model_temporal = AgriculturalAnalysisResponse.model_validate(temporal_only)
print("temporal-point response cacheable:",
      _response_has_usable_measurement(model_temporal))
assert _response_has_usable_measurement(model_temporal)

# 5. Usable spatial cell observation without bundles is cacheable.
spatial_only = outage | {
    "evidence_bundles": {},
    "spatial": {
        "window_start": "2024-04-01",
        "window_end": "2024-06-30",
        "grid_rows": 1,
        "grid_cols": 1,
        "cells": [],
        "observations": [
            {"cell_id": "r00c00", "metric_key": "ndvi",
             "window_start": "2024-04-01", "window_end": "2024-06-30",
             "value": 0.5}
        ],
    },
}
model_spatial = AgriculturalAnalysisResponse.model_validate(spatial_only)
print("spatial-cell response cacheable:",
      _response_has_usable_measurement(model_spatial))
assert _response_has_usable_measurement(model_spatial)

print("ALL CACHE-GATE CHECKS PASS")
