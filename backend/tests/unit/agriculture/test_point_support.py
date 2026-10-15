"""Tests for the Point support policy (F-A12).

The risks pinned here:

1. A Point must never again yield a zero coverage denominator that is
   clamped into a confident 100 % coverage.
2. A Polygon request, and any hand-built context that never declared a
   request geometry, must be byte-for-byte unaffected.
3. Point-queryable products (ERA5, GLDAS, SMAP L4) must keep their
   containing-pixel semantics and never be buffered.
4. The support region must reach the cache identity, so a value cached
   under the old zero-area meaning cannot be replayed.
5. Every buffered value discloses what it describes and keeps the
   original coordinate.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from app.services.agriculture.aggregation import (
    estimate_pixel_count,
    parse_reduction_result,
    pixel_area_sq_m,
)
from app.services.agriculture.base import MetricContext
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.support import (
    DISCLOSURE_PREFIX,
    INPUT_DISCLOSURE_PREFIX,
    open_support_scope,
    scope_context_for_dataset,
    FIELD_RADIUS_M,
    LOCAL_RADIUS_M,
    POINT_QUERYABLE_DATASET_IDS,
    POINT_SUPPORT_POLICY_VERSION,
    apply_support_disclosure,
    family_for_native_resolution_m,
    parse_native_resolution_m,
    resolve_support_context,
    support_identity,
    support_radius_m,
)
from app.services.agriculture.types import Provenance

POINT = {"type": "Point", "coordinates": [53.688, 32.4279]}
POLYGON = {
    "type": "Polygon",
    "coordinates": [[[53.0, 32.0], [53.1, 32.0], [53.1, 32.1], [53.0, 32.0]]],
}

S2 = "COPERNICUS/S2_SR_HARMONIZED"
S1 = "COPERNICUS/S1_GRD"
DW = "GOOGLE/DYNAMICWORLD/V1"
SOILGRIDS = "ISRIC/SoilGrids250m/v2_0"
MOD11 = "MODIS/061/MOD11A2"
MOD16 = "MODIS/061/MOD16A2GF"
NASADEM = "NASA/NASADEM_HGT/001"
LANDSAT = "LANDSAT/LC08/C02/T1_L2"
ERA5 = "ECMWF/ERA5_LAND/DAILY_AGGR"
GLDAS = "NASA/GLDAS/V021/NOAH/G025/T3H"
SMAP_L4 = "NASA/SMAP/SPL4SMGP/008"


class _FakeGeometry:
    """Stands in for ``ee.Geometry``: records the buffer radius."""

    def __init__(self, radius_m: float = 0.0) -> None:
        self.radius_m = radius_m

    def buffer(self, radius_m: float) -> "_FakeGeometry":
        return _FakeGeometry(radius_m)


class _FakeMetric:
    key = "fake"

    def __init__(self, dataset_id: str) -> None:
        self._dataset = get_dataset(dataset_id)

    def primary_dataset(self):
        return self._dataset


def _point_context(**overrides) -> MetricContext:
    point = _FakeGeometry()
    base = dict(
        geometry=point,
        start_date="2025-06-01",
        end_date="2025-09-01",
        geometry_key=str(POINT),
        requested_geometry=POINT,
        original_geometry=point,
        support_plan={},
    )
    base.update(overrides)
    return MetricContext(**base)


# -- family policy ----------------------------------------------------------


@pytest.mark.parametrize(
    "dataset_id, family, radius",
    [
        (S2, "field", FIELD_RADIUS_M),
        (S1, "field", FIELD_RADIUS_M),
        (DW, "field", FIELD_RADIUS_M),
        (LANDSAT, "local", LOCAL_RADIUS_M),
        (NASADEM, "local", LOCAL_RADIUS_M),
        (SOILGRIDS, "soil", 500.0),
        (MOD16, "soil", 750.0),
        (MOD11, "regional", 1500.0),
    ],
)
def test_family_and_radius_follow_native_resolution(dataset_id, family, radius):
    native = parse_native_resolution_m(get_dataset(dataset_id).spatial_resolution)
    assert family_for_native_resolution_m(native) == family
    assert support_radius_m(native) == pytest.approx(radius)


def test_no_single_universal_radius():
    radii = {
        support_radius_m(
            parse_native_resolution_m(get_dataset(d).spatial_resolution)
        )
        for d in (S2, LANDSAT, SOILGRIDS, MOD16, MOD11)
    }
    assert len(radii) == 5


def test_unreadable_resolution_is_not_guessed():
    assert parse_native_resolution_m(None) is None
    assert parse_native_resolution_m("varies") is None
    assert support_radius_m(None) == 0.0


# -- denominator ------------------------------------------------------------


@pytest.mark.parametrize("dataset_id", [S2, S1, DW, LANDSAT, NASADEM, SOILGRIDS, MOD16, MOD11])
def test_point_gets_a_real_denominator(dataset_id):
    scoped = resolve_support_context(_point_context(), _FakeMetric(dataset_id))
    area = scoped.option("area_sq_m")
    assert area and area > 0
    assert area == pytest.approx(math.pi * scoped.support_spec.radius_m ** 2)
    native = scoped.support_spec.native_resolution_m
    assert estimate_pixel_count(area, native) >= 1


def test_zero_area_clamp_is_gone_for_a_point():
    """The audited failure: total 0 clamped to valid -> 100 % coverage."""
    scoped = resolve_support_context(_point_context(), _FakeMetric(S2))
    total = estimate_pixel_count(scoped.option("area_sq_m"), 10)
    assert total > 1  # 60 m disc holds ~113 ten-metre pixels
    stats = parse_reduction_result(
        {"NDVI_count": 2, "NDVI_mean": 0.4},
        band="NDVI",
        total_pixel_count=total,
        pixel_area_sq_m=pixel_area_sq_m(10),
    )
    assert stats.total_pixel_count == total
    assert stats.coverage_percent < 5.0  # 2 of ~113, not a fake 100 %


def test_buffer_is_built_from_the_original_point():
    scoped = resolve_support_context(_point_context(), _FakeMetric(S2))
    assert scoped.geometry.radius_m == FIELD_RADIUS_M
    assert scoped.original_geometry is not scoped.geometry
    assert scoped.requested_geometry == POINT


def test_same_radius_is_built_once_per_request():
    ctx = _point_context()
    a = resolve_support_context(ctx, _FakeMetric(S2))
    b = resolve_support_context(ctx, _FakeMetric(S1))
    assert a.geometry is b.geometry


# -- untouched paths --------------------------------------------------------


def test_polygon_request_is_untouched():
    ctx = _point_context(requested_geometry=POLYGON)
    assert resolve_support_context(ctx, _FakeMetric(S2)) is ctx


def test_hand_built_context_is_untouched():
    ctx = MetricContext(
        geometry=_FakeGeometry(), start_date="2025-06-01", end_date="2025-09-01"
    )
    assert resolve_support_context(ctx, _FakeMetric(S2)) is ctx
    assert ctx.option("area_sq_m") is None


def test_metric_without_dataset_is_untouched():
    class _NoDataset:
        key = "none"

        def primary_dataset(self):
            raise KeyError("none")

    ctx = _point_context()
    assert resolve_support_context(ctx, _NoDataset()) is ctx


# -- point-queryable products ----------------------------------------------


@pytest.mark.parametrize("dataset_id", [ERA5, GLDAS, SMAP_L4])
def test_point_queryable_products_are_never_buffered(dataset_id):
    assert dataset_id in POINT_QUERYABLE_DATASET_IDS
    ctx = _point_context()
    scoped = resolve_support_context(ctx, _FakeMetric(dataset_id))
    assert scoped.geometry is ctx.geometry
    assert scoped.option("area_sq_m") is None
    assert scoped.support_spec.point_queryable is True
    assert scoped.support_spec.radius_m == 0.0


def test_queryable_metric_after_buffered_one_drops_the_area():
    """A nested ERA5 read inside a buffered context must go back to a Point."""
    ctx = _point_context()
    buffered = resolve_support_context(ctx, _FakeMetric(S2))
    back = resolve_support_context(buffered, _FakeMetric(ERA5))
    assert back.geometry is ctx.original_geometry
    assert back.option("area_sq_m") is None
    assert back.support_spec.point_queryable is True


def test_resolution_is_idempotent():
    ctx = _point_context()
    once = resolve_support_context(ctx, _FakeMetric(S2))
    assert resolve_support_context(once, _FakeMetric(S2)) is once


# -- derived metrics that read a second dataset -----------------------------


def test_second_dataset_is_scoped_by_its_own_grid_not_the_primary():
    """SMAP L4 (queryable) primary must not leave SoilGrids on a bare Point."""
    ctx = open_support_scope(_point_context(), _FakeMetric(SMAP_L4))
    assert ctx.support_spec.point_queryable is True
    assert ctx.option("area_sq_m") is None

    soil = scope_context_for_dataset(ctx, SOILGRIDS)
    assert soil.option("area_sq_m") == pytest.approx(math.pi * 500.0 ** 2)
    assert soil.geometry.radius_m == 500.0
    assert soil.support_spec.family == "soil"


def test_queryable_second_dataset_returns_to_the_point():
    ctx = open_support_scope(_point_context(), _FakeMetric(MOD16))
    assert ctx.geometry.radius_m == 750.0
    era5 = scope_context_for_dataset(ctx, ERA5)
    assert era5.geometry is ctx.original_geometry
    assert era5.option("area_sq_m") is None


def test_scope_for_dataset_is_a_no_op_for_a_polygon():
    ctx = _point_context(requested_geometry=POLYGON)
    assert scope_context_for_dataset(ctx, SOILGRIDS) is ctx


def test_scope_for_unknown_dataset_leaves_context_alone():
    ctx = _point_context()
    assert scope_context_for_dataset(ctx, "NO/SUCH/DATASET") is ctx


def test_every_support_used_is_logged_and_disclosed():
    ctx = open_support_scope(_point_context(), _FakeMetric(SMAP_L4))
    scope_context_for_dataset(ctx, SOILGRIDS)
    scope_context_for_dataset(ctx, SOILGRIDS)  # repeat reads log once
    assert [s.dataset_id for s in ctx.support_log] == [SMAP_L4, SOILGRIDS]

    prov = apply_support_disclosure(_Result(), ctx).provenance
    assert [i["dataset_id"] for i in prov.support_inputs] == [SMAP_L4, SOILGRIDS]
    assert prov.support_inputs[1]["radius_m"] == 500.0
    # primary scalar fields describe the primary (point-queryable) input
    assert prov.support_radius_m == 0.0
    assert sum(i.startswith(INPUT_DISCLOSURE_PREFIX) for i in prov.limitations) == 1


def test_log_is_fresh_per_metric_and_not_shared_between_metrics():
    base = _point_context()
    a = open_support_scope(base, _FakeMetric(SMAP_L4))
    b = open_support_scope(base, _FakeMetric(SMAP_L4))
    scope_context_for_dataset(a, SOILGRIDS)
    assert len(a.support_log) == 2
    assert len(b.support_log) == 1


def test_open_scope_leaves_polygon_and_hand_built_contexts_alone():
    poly = _point_context(requested_geometry=POLYGON)
    assert open_support_scope(poly, _FakeMetric(S2)) is poly
    plain = MetricContext(geometry=_FakeGeometry(), start_date="a", end_date="b")
    assert open_support_scope(plain, _FakeMetric(S2)) is plain


def test_redisclosure_replaces_instead_of_stacking():
    ctx = open_support_scope(_point_context(), _FakeMetric(SMAP_L4))
    result = apply_support_disclosure(_Result(), ctx)
    scope_context_for_dataset(ctx, SOILGRIDS)
    again = apply_support_disclosure(result, ctx)
    lims = again.provenance.limitations
    assert sum(i.startswith(DISCLOSURE_PREFIX) for i in lims) == 1
    assert sum(i.startswith(INPUT_DISCLOSURE_PREFIX) for i in lims) == 1


# -- consistency across month sub-windows ----------------------------------


def test_profile_month_windows_share_the_scalar_geometry():
    """A scalar and its monthly profile must reduce over one geometry."""
    ctx = _point_context()
    scalar = resolve_support_context(ctx, _FakeMetric(S2))
    month = resolve_support_context(
        replace(ctx, start_date="2025-07-01", end_date="2025-08-01"),
        _FakeMetric(S2),
    )
    assert month.geometry is scalar.geometry
    assert month.option("area_sq_m") == scalar.option("area_sq_m")
    assert support_identity(month.support_spec) == support_identity(scalar.support_spec)


# -- cache identity ---------------------------------------------------------


def test_cache_key_differs_between_zero_area_and_support_region():
    ctx = _point_context()
    legacy = ctx.cache_key("ndvi")
    scoped = resolve_support_context(ctx, _FakeMetric(S2)).cache_key("ndvi")
    assert legacy != scoped


def test_cache_key_differs_between_families():
    ctx = _point_context()
    a = resolve_support_context(ctx, _FakeMetric(S2)).cache_key("m")
    b = resolve_support_context(ctx, _FakeMetric(SOILGRIDS)).cache_key("m")
    assert a != b


def test_polygon_cache_key_carries_no_support_term():
    ctx = MetricContext(
        geometry=_FakeGeometry(), start_date="a", end_date="b", geometry_key="g"
    )
    assert ctx.support_identity() == "none"


def test_support_identity_embeds_policy_version():
    scoped = resolve_support_context(_point_context(), _FakeMetric(S2))
    assert POINT_SUPPORT_POLICY_VERSION in support_identity(scoped.support_spec)


def test_api_cache_key_changes_with_policy_version(monkeypatch):
    from app.api.v1 import agriculture as api
    from app.schemas.agriculture import AgricultureAnalysisRequest

    request = AgricultureAnalysisRequest(
        geometry=POINT,
        start_date="2025-06-01",
        end_date="2025-09-01",
        cloud_max_percent=20,
    )
    current = api._build_analysis_cache_key(request)
    import app.services.agriculture.support as support_module

    monkeypatch.setattr(support_module, "POINT_SUPPORT_POLICY_VERSION", "point-support-v0")
    assert api._build_analysis_cache_key(request) != current


# -- disclosure -------------------------------------------------------------


def _provenance() -> Provenance:
    return Provenance(
        source_dataset_id=S2,
        source_dataset_name="Sentinel-2",
        spatial_resolution="10 m",
    )


class _Result:
    def __init__(self) -> None:
        self.provenance = _provenance()


def test_buffered_result_discloses_support_and_original_point():
    scoped = resolve_support_context(_point_context(), _FakeMetric(S2))
    result = apply_support_disclosure(_Result(), scoped)
    prov = result.provenance
    assert prov.geometry_type == "Point"
    assert prov.support_radius_m == FIELD_RADIUS_M
    assert prov.support_area_sq_m == pytest.approx(math.pi * FIELD_RADIUS_M ** 2)
    assert prov.support_family == "field"
    assert prov.support_policy == POINT_SUPPORT_POLICY_VERSION
    assert prov.support_native_resolution_m == 10.0
    assert prov.original_geometry == POINT
    assert any(
        item.startswith(DISCLOSURE_PREFIX) and "around the selected location" in item
        for item in prov.limitations
    )


def test_coarse_buffer_is_labelled_regional_context():
    scoped = resolve_support_context(_point_context(), _FakeMetric(MOD11))
    prov = apply_support_disclosure(_Result(), scoped).provenance
    assert any("regional/district-scale" in item for item in prov.limitations)


def test_field_scale_buffer_is_not_labelled_regional():
    scoped = resolve_support_context(_point_context(), _FakeMetric(S2))
    prov = apply_support_disclosure(_Result(), scoped).provenance
    assert not any("regional/district-scale" in item for item in prov.limitations)


def test_queryable_result_discloses_single_pixel_not_a_buffer():
    scoped = resolve_support_context(_point_context(), _FakeMetric(ERA5))
    prov = apply_support_disclosure(_Result(), scoped).provenance
    assert prov.support_radius_m == 0.0
    assert prov.original_geometry == POINT
    assert any("single native pixel" in item for item in prov.limitations)


def test_disclosure_is_idempotent():
    scoped = resolve_support_context(_point_context(), _FakeMetric(S2))
    result = apply_support_disclosure(_Result(), scoped)
    again = apply_support_disclosure(result, scoped)
    assert sum(i.startswith(DISCLOSURE_PREFIX) for i in again.provenance.limitations) == 1


def test_unscoped_result_gets_no_disclosure():
    ctx = MetricContext(
        geometry=_FakeGeometry(), start_date="a", end_date="b"
    )
    result = apply_support_disclosure(_Result(), ctx)
    assert result.provenance.geometry_type is None
    assert result.provenance.support_radius_m is None
    assert result.provenance.original_geometry is None
    assert result.provenance.limitations == []
