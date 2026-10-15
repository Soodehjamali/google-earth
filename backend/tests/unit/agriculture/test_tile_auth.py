"""Unit tests for Tile Authentication, HMAC signing, and Slippy bounds checking (P-CLOSEOUT)."""

import time
import pytest
from app.services.agriculture.tile_auth import (
    generate_signed_layer_token,
    verify_layer_token,
    tile_to_wgs84_bbox,
    check_tile_intersects_bbox,
)


def test_tile_math_wgs84_conversion():
    # Ardakan area: lon=53.688, lat=32.4279 -> tile at z=14 is x=10635, y=6630
    bbox = tile_to_wgs84_bbox(14, 10635, 6630)
    lon_min, lat_min, lon_max, lat_max = bbox
    assert lon_min <= 53.688 <= lon_max
    assert lat_min <= 32.4279 <= lat_max


def test_check_tile_intersects_bbox():
    ardakan_bbox = [53.65, 32.40, 53.72, 32.45]
    # In-bounds tile (Ardakan center)
    assert check_tile_intersects_bbox(14, 10635, 6630, ardakan_bbox) is True
    # Out-of-bounds tile (Paris, France: lon ~2.3, lat ~48.8 -> z=14, x=8298, y=5634)
    assert check_tile_intersects_bbox(14, 8298, 5634, ardakan_bbox) is False


def test_verify_layer_token_valid():
    bbox = [53.65, 32.40, 53.72, 32.45]
    token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id="valid_tid_001",
        ttl_seconds=3600,
    )
    is_valid, status, err_code, reason, token_id, payload = verify_layer_token(
        token, 14, 10635, 6630
    )
    assert is_valid is True
    assert status == 200
    assert token_id == "valid_tid_001"
    assert payload["m"] == "ndvi"


def test_verify_layer_token_forged():
    bbox = [53.65, 32.40, 53.72, 32.45]
    token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id="valid_tid_001",
    )
    # Alter payload or signature
    parts = token.split(".")
    forged_token = parts[0] + ".badsignature12345"
    is_valid, status, err_code, reason, token_id, payload = verify_layer_token(
        forged_token, 14, 10635, 6630
    )
    assert is_valid is False
    assert status == 403
    assert err_code == "ERR_TILE_FORBIDDEN"


def test_verify_layer_token_expired():
    bbox = [53.65, 32.40, 53.72, 32.45]
    expired_token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id="exp_tid",
        ttl_seconds=-50,
    )
    is_valid, status, err_code, reason, token_id, payload = verify_layer_token(
        expired_token, 14, 10635, 6630
    )
    assert is_valid is False
    assert status == 403
    assert err_code == "ERR_TILE_EXPIRED"


def test_verify_layer_token_zoom_bounds():
    bbox = [53.65, 32.40, 53.72, 32.45]
    token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id="zoom_tid",
    )
    # Zoom 7 (too low)
    valid_low, status_low, err_low, _, _, _ = verify_layer_token(token, 7, 80, 50)
    assert valid_low is False
    assert status_low == 404
    assert err_low == "ERR_TILE_OUT_OF_BOUNDS"

    # Zoom 21 (too high)
    valid_high, status_high, err_high, _, _, _ = verify_layer_token(token, 21, 1000, 1000)
    assert valid_high is False
    assert status_high == 404
    assert err_high == "ERR_TILE_OUT_OF_BOUNDS"


def test_verify_layer_token_spatial_bounds():
    bbox = [53.65, 32.40, 53.72, 32.45]
    token = generate_signed_layer_token(
        metric="ndvi",
        start_date="2025-06-01",
        end_date="2025-09-01",
        bbox=bbox,
        token_id="spatial_tid",
    )
    # Tile in Paris at z=14 (8298, 5634)
    valid_oob, status_oob, err_oob, _, _, _ = verify_layer_token(token, 14, 8298, 5634)
    assert valid_oob is False
    assert status_oob == 404
    assert err_oob == "ERR_TILE_OUT_OF_BOUNDS"
