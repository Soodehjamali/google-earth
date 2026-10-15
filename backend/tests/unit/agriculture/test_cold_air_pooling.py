"""Unit and synthetic tests for topography-derived Cold-Air-Pooling risk proxy.

Verifies:
1. Mathematical behavior on synthetic DEM primitives:
   - Bowl (concavity / depression) -> High pooling risk
   - Ridge / Peak (convexity) -> Low pooling risk
   - Flat plain -> Neutral pooling risk
   - Ranking: Bowl > Flat > Ridge
2. Monotonicity: Deeper topographic bowl yields strictly higher pooling risk.
3. Elevation independence: Absolute elevation shift of the entire DEM (z -> z + C)
   produces identical TPI, slope, height-above-floor, and pooling proxy.
4. Schema contract & naming: Verifies 'pooling_risk_proxy' and heuristic proxy
   disclaimers, strictly forbidding 'microclimate_simulation' claims.
5. Integration test with Earth Engine (auto-skips when GEE credentials absent).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from app.services.agriculture.cold_air_pooling import (
    ColdAirPoolingConfig,
    ColdAirPoolingResult,
    POOLING_DISCLAIMER_FA,
    calculate_cold_air_pooling_ee,
    compute_pooling_index_from_dem_array,
)


def _make_grid_coords(size: int = 51, cell_size_m: float = 30.0):
    """Generate centered coordinate distance arrays in meters."""
    center = size // 2
    y, x = np.ogrid[:size, :size]
    dx = (x - center) * cell_size_m
    dy = (y - center) * cell_size_m
    r = np.hypot(dx, dy)
    return r, dx, dy


def test_synthetic_bowl_vs_ridge_vs_flat():
    """Verify that a bowl (depression) has high pooling risk, ridge has low, and flat is neutral."""
    size = 51
    cell_size = 30.0
    r, _, _ = _make_grid_coords(size, cell_size)
    r_norm = r / (size * cell_size / 2.0)

    # Bowl: center is 50m deeper than rims (parabolic depression)
    dem_bowl = 1000.0 + 50.0 * (r_norm ** 2)

    # Ridge: center is 50m higher than base (parabolic hill)
    dem_ridge = 1050.0 - 50.0 * (r_norm ** 2)

    # Flat: perfectly flat table-land at 1000m
    dem_flat = np.full((size, size), 1000.0)

    res_bowl = compute_pooling_index_from_dem_array(dem_bowl, cell_size_m=cell_size)
    res_ridge = compute_pooling_index_from_dem_array(dem_ridge, cell_size_m=cell_size)
    res_flat = compute_pooling_index_from_dem_array(dem_flat, cell_size_m=cell_size)

    # Center pixel checks
    p_bowl = res_bowl["center_pooling_risk_proxy"]
    p_ridge = res_ridge["center_pooling_risk_proxy"]
    p_flat = res_flat["center_pooling_risk_proxy"]

    # Bowl center is at the bottom of the valley (height above floor = 0, negative TPI, flat bottom)
    assert p_bowl > 0.70, f"Expected bowl pooling risk > 0.70, got {p_bowl:.3f}"
    # Ridge center is high above surroundings (high height above floor, positive TPI)
    assert p_ridge < 0.35, f"Expected ridge pooling risk < 0.35, got {p_ridge:.3f}"
    # Flat terrain is neutral (TPI=0, slope=0)
    assert 0.40 <= p_flat <= 0.60, f"Expected flat pooling risk ~ 0.50, got {p_flat:.3f}"

    # Strict ordering
    assert p_bowl > p_flat > p_ridge, f"Expected Bowl > Flat > Ridge, got {p_bowl} > {p_flat} > {p_ridge}"

    # TPI sign checks
    assert res_bowl["center_tpi_inner"] < 0, "Bowl center inner TPI must be negative"
    assert res_bowl["center_tpi_outer"] < 0, "Bowl center outer TPI must be negative"
    assert res_ridge["center_tpi_inner"] > 0, "Ridge center inner TPI must be positive"
    assert res_ridge["center_tpi_outer"] > 0, "Ridge center outer TPI must be positive"
    assert abs(res_flat["center_tpi_inner"]) < 1e-6, "Flat TPI must be 0"


def test_monotonicity_deeper_bowl():
    """Verify that deeper topographic depressions yield strictly higher pooling risk."""
    size = 51
    cell_size = 30.0
    r, _, _ = _make_grid_coords(size, cell_size)
    r_norm = r / (size * cell_size / 2.0)

    # Depths from 5m to 60m
    depths = [5.0, 15.0, 30.0, 50.0]
    proxies = []

    for depth in depths:
        dem = 1000.0 + depth * (r_norm ** 2)
        res = compute_pooling_index_from_dem_array(dem, cell_size_m=cell_size)
        proxies.append(res["center_pooling_risk_proxy"])

    # Strictly monotonically increasing
    for i in range(len(proxies) - 1):
        assert proxies[i + 1] > proxies[i], (
            f"Monotonicity failed: depth {depths[i+1]}m (proxy={proxies[i+1]:.4f}) "
            f"not greater than depth {depths[i]}m (proxy={proxies[i]:.4f})"
        )


def test_elevation_independence():
    """Verify that adding an arbitrary constant elevation shift changes nothing."""
    size = 45
    cell_size = 30.0
    r, dx, dy = _make_grid_coords(size, cell_size)

    # Complex rolling terrain
    dem_base = (
        1200.0
        + 25.0 * np.sin(dx / 300.0)
        + 15.0 * np.cos(dy / 400.0)
        + 10.0 * (r / 500.0) ** 1.5
    )

    # Elevate whole DEM by +2000 meters (e.g. from 1200m to 3200m)
    dem_shifted = dem_base + 2000.0

    res_base = compute_pooling_index_from_dem_array(dem_base, cell_size_m=cell_size)
    res_shifted = compute_pooling_index_from_dem_array(dem_shifted, cell_size_m=cell_size)

    # 1. Pooling risk proxy grids must match exactly
    np.testing.assert_allclose(
        res_base["pooling_risk_proxy_grid"],
        res_shifted["pooling_risk_proxy_grid"],
        rtol=1e-5,
        atol=1e-5,
        err_msg="Pooling risk proxy grid must be completely invariant to elevation shifts",
    )

    # 2. Key center and aggregated metrics must match
    assert pytest.approx(res_base["center_pooling_risk_proxy"], abs=1e-5) == res_shifted["center_pooling_risk_proxy"]
    assert pytest.approx(res_base["center_tpi_inner"], abs=1e-5) == res_shifted["center_tpi_inner"]
    assert pytest.approx(res_base["center_tpi_outer"], abs=1e-5) == res_shifted["center_tpi_outer"]
    assert pytest.approx(res_base["center_height_above_floor"], abs=1e-5) == res_shifted["center_height_above_floor"]
    assert pytest.approx(res_base["center_slope_deg"], abs=1e-5) == res_shifted["center_slope_deg"]


def test_proxy_labeling_and_disclaimer_contract():
    """Verify that proxy labeling is present and CFD simulation claims are absent."""
    dem = np.full((31, 31), 1400.0)
    res = compute_pooling_index_from_dem_array(dem)

    # Explicit heuristic proxy flags
    assert res["is_heuristic_proxy"] is True
    assert res["quality_state"] == "coarse_proxy"
    assert "pooling_risk_proxy" in res
    assert POOLING_DISCLAIMER_FA == res["disclaimer_fa"]

    # Must NOT claim physical microclimate simulation
    assert "microclimate_simulation" not in res
    assert "cfd_model" not in res


@pytest.mark.requires_gee
def test_cold_air_pooling_live_ee():
    """Integration test with live Earth Engine NASADEM."""
    geom = {
        "type": "Polygon",
        "coordinates": [
            [
                [54.015, 32.310],
                [54.025, 32.310],
                [54.025, 32.320],
                [54.015, 32.320],
                [54.015, 32.310],
            ]
        ],
    }
    result = calculate_cold_air_pooling_ee(geom)
    assert isinstance(result, ColdAirPoolingResult)
    assert 0.0 <= result.mean_pooling_risk_proxy <= 1.0
    assert 0.0 <= result.p90_pooling_risk_proxy <= 1.0
    assert result.min_elevation_m > 0
    assert result.max_elevation_m >= result.min_elevation_m
    assert result.tile_url is not None
    assert "/api/v1/agriculture/tiles/" in result.tile_url
    assert result.is_heuristic_proxy is True
