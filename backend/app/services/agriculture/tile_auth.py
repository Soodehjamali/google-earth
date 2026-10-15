"""Tile Authentication, Cryptographic HMAC Signing, and Slippy-Tile Bounding Verification.

Provides defense-in-depth for the backend tile proxy:
1. HMAC-SHA256 signature binding metric, date range, bounding box [W, S, E, N], expiry, and token ID.
2. Coordinate and zoom level restriction: z in [8, 20], tile bbox intersects polygon bounds.
3. Anti-forgery and expiry validation returning 403 on tampering or expiry.
4. Out-of-bounds validation returning 404.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings


def _get_signing_secret() -> bytes:
    """Obtain HMAC secret key from application settings or fallback."""
    sec = (
        getattr(settings, "TILE_SIGNING_SECRET", None)
        or getattr(settings, "SECRET_KEY", None)
        or "agri_tile_secret_default_key_change_in_production"
    )
    return sec.encode("utf-8")


def tile_to_wgs84_bbox(z: int, x: int, y: int) -> Tuple[float, float, float, float]:
    """Calculate the WGS84 bounding box [lon_min, lat_min, lon_max, lat_max] of a slippy map tile (z, x, y)."""
    n = 2.0 ** z
    lon_min = (x / n) * 360.0 - 180.0
    lon_max = ((x + 1) / n) * 360.0 - 180.0

    # Spherical Mercator inverse projection
    lat_rad_max = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat_max = math.degrees(lat_rad_max)

    lat_rad_min = math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n)))
    lat_min = math.degrees(lat_rad_min)

    return lon_min, lat_min, lon_max, lat_max


def check_tile_intersects_bbox(
    z: int,
    x: int,
    y: int,
    bbox: List[float],
    buffer_deg: float = 0.05,
) -> bool:
    """Check if slippy map tile (z, x, y) intersects the polygon bounding box [W, S, E, N].
    
    A safety buffer (default 0.05 degrees ~ 5.5 km) is applied to ensure edge tiles covering
    the polygon boundary are not clipped.
    """
    if len(bbox) < 4:
        return True
    
    tile_w, tile_s, tile_e, tile_n = tile_to_wgs84_bbox(z, x, y)
    poly_w = bbox[0] - buffer_deg
    poly_s = bbox[1] - buffer_deg
    poly_e = bbox[2] + buffer_deg
    poly_n = bbox[3] + buffer_deg

    # No intersection if completely disjoint
    if tile_e < poly_w or tile_w > poly_e or tile_n < poly_s or tile_s > poly_n:
        return False
    return True


def generate_signed_layer_token(
    metric: str,
    start_date: str,
    end_date: str,
    bbox: List[float],
    token_id: Optional[str] = None,
    ttl_seconds: int = 7200,
) -> str:
    """Generate a tamper-evident HMAC-SHA256 signed layer token."""
    if not token_id:
        import uuid
        token_id = uuid.uuid4().hex[:16]

    now = int(time.time())
    payload = {
        "tid": token_id,
        "m": metric,
        "s": start_date,
        "e": end_date,
        "b": [round(float(c), 6) for c in bbox],
        "exp": now + ttl_seconds,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
    sig = hmac.new(_get_signing_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_layer_token(
    token: str,
    z: int,
    x: int,
    y: int,
) -> Tuple[bool, int, str, str, Optional[str], Optional[Dict[str, Any]]]:
    """Verify layer token authenticity, expiration, zoom bounds, and spatial intersection.

    Returns:
        (is_valid, http_status_code, error_code, reason_or_message, token_id, payload_dict)
    """
    if not token or "." not in token:
        return (
            False,
            403,
            "ERR_TILE_FORBIDDEN",
            "Invalid tile layer token structure.",
            None,
            None,
        )

    parts = token.split(".", 1)
    if len(parts) != 2:
        return (
            False,
            403,
            "ERR_TILE_FORBIDDEN",
            "Malformed tile layer token.",
            None,
            None,
        )

    payload_b64, signature = parts
    expected_sig = hmac.new(
        _get_signing_secret(), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return (
            False,
            403,
            "ERR_TILE_FORBIDDEN",
            "Tile layer token signature verification failed (forged or altered token).",
            None,
            None,
        )

    # Decode payload
    rem = len(payload_b64) % 4
    if rem:
        payload_b64 += "=" * (4 - rem)

    try:
        raw_json = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        payload = json.loads(raw_json)
    except Exception:
        return (
            False,
            403,
            "ERR_TILE_FORBIDDEN",
            "Unreadable tile layer token payload.",
            None,
            None,
        )

    # 1. Check expiration (403 Forbidden)
    exp = payload.get("exp", 0)
    if exp < time.time():
        return (
            False,
            403,
            "ERR_TILE_EXPIRED",
            "Tile layer session token has expired. Please refresh the map layer.",
            None,
            payload,
        )

    # 2. Check zoom level restriction [8, 20] (404 Not Found outside bounds)
    if z < 8 or z > 20:
        return (
            False,
            404,
            "ERR_TILE_OUT_OF_BOUNDS",
            f"Zoom level {z} outside supported range [8, 20].",
            payload.get("tid"),
            payload,
        )

    # 3. Check spatial bounding box intersection (404 Not Found outside polygon bounds)
    bbox = payload.get("b", [])
    if bbox and len(bbox) == 4:
        if not check_tile_intersects_bbox(z, x, y, bbox):
            return (
                False,
                404,
                "ERR_TILE_OUT_OF_BOUNDS",
                f"Requested tile ({z}, {x}, {y}) is outside analysis polygon bounds.",
                payload.get("tid"),
                payload,
            )

    token_id = payload.get("tid")
    return True, 200, "OK", "", token_id, payload
