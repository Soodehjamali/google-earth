"""Tests for the P1.5 spatial anomaly and hotspot foundation.

The pure spatial layer (grid, aggregation, concentration,
concordance, persistence) runs over hand-built cell observations.
Only the thin per-cell evaluator needs Earth Engine, exercised
through a strict queue-based fake serving one outcome per cell in
order.  No network and no credentials are required.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional

import pytest

from app.core.exceptions import GeometryError
from app.services.agriculture.base import MetricContext
from app.services.agriculture.spatial_profile import (
    CONCENTRATION_MIN_FRACTION,
    CONCORDANCE_INSUFFICIENT,
    CONCORDANCE_MIXED,
    CONCORDANCE_MULTI_METRIC,
    CONCORDANCE_NONE,
    CONCORDANCE_SINGLE_METRIC,
    MIN_VALID_CELLS,
    STATE_ANOMALOUS_AREA,
    STATE_CONCENTRATED_ANOMALY,
    STATE_INSUFFICIENT,
    STATE_NORMAL_AREA,
    CellObservation,
    aggregate_cells,
    area_state,
    bbox_of_geojson,
    cell_cache_key,
    cell_concordance,
    evaluate_cell,
    evaluate_grid,
    grid_cells,
    track_cell_persistence,
)

AREA_SQ_M = 10000.0
BBOX = (51.0, 32.0, 52.0, 33.0)  # west, south, east, north
WINDOW = ("2024-07-01", "2024-07-31")


@pytest.fixture(autouse=True)
def _clean_registry():
    from app.services.agriculture.catalog import clear_registry

    clear_registry()
    yield
    clear_registry()


def make_context(**overrides) -> MetricContext:
    fields = {
        "geometry": {},
        "start_date": WINDOW[0],
        "end_date": WINDOW[1],
        "geometry_key": "test-geometry",
        "options": {"area_sq_m": AREA_SQ_M},
    }
    fields.update(overrides)
    return MetricContext(**fields)


def _obs(
    cell_id: str,
    value: Optional[float],
    category: Optional[str] = None,
    quality: str = "good",
    coverage: Optional[float] = 100.0,
    image: Optional[int] = 6,
    metric_key: str = "ndvi",
    unit: str = "index",
) -> CellObservation:
    return CellObservation(
        cell_id=cell_id,
        metric_key=metric_key,
        window_start=WINDOW[0],
        window_end=WINDOW[1],
        value=value,
        unit=unit,
        quality=quality if value is not None else "insufficient",
        coverage_percent=coverage if value is not None else None,
        image_count=image if value is not None else None,
        category=category,
    )


# ==========================================================================
# Spatial unit: grid creation and validation
# ==========================================================================


def test_grid_cells_cover_the_bbox_deterministically():
    first = grid_cells(BBOX, 2, 3)
    second = grid_cells(BBOX, 2, 3)
    assert first == second
    assert len(first) == 6
    assert [cell.cell_id for cell in first] == [
        "r00c00",
        "r00c01",
        "r00c02",
        "r01c00",
        "r01c01",
        "r01c02",
    ]
    top_left = first[0]
    assert top_left.row == 0 and top_left.col == 0
    assert (top_left.west, top_left.south, top_left.east, top_left.north) == (
        pytest.approx(51.0),
        pytest.approx(32.5),
        pytest.approx(51.0 + 1.0 / 3.0),
        pytest.approx(33.0),
    )
    assert top_left.geometry["type"] == "Polygon"
    ring = top_left.geometry["coordinates"][0]
    assert ring[0] == ring[-1]  # closed ring
    assert len(ring) == 5
    # Full coverage without overlap: widths sum to the bbox width.
    assert sum(cell.east - cell.west for cell in first[:3]) == pytest.approx(1.0)


def test_grid_dimensions_are_validated():
    with pytest.raises(ValueError):
        grid_cells(BBOX, 0, 3)
    with pytest.raises(ValueError):
        grid_cells(BBOX, 2, -1)
    with pytest.raises(ValueError):
        grid_cells(BBOX, True, 3)


def test_zero_extent_and_non_finite_boxes_refused():
    with pytest.raises(ValueError, match="positive extent"):
        grid_cells((51.0, 32.0, 51.0, 33.0), 2, 2)
    with pytest.raises(ValueError, match="positive extent"):
        grid_cells((51.0, 32.0, 52.0, 32.0), 2, 2)
    with pytest.raises(ValueError, match="finite"):
        grid_cells((51.0, 32.0, float("nan"), 33.0), 2, 2)


def test_bbox_of_geojson_reuses_the_repository_contract():
    polygon = {
        "type": "Polygon",
        "coordinates": [[[51.0, 32.0], [52.0, 32.0], [52.0, 33.0], [51.0, 33.0], [51.0, 32.0]]],
    }
    assert bbox_of_geojson(polygon) == (51.0, 32.0, 52.0, 33.0)
    assert bbox_of_geojson({"type": "Point", "coordinates": [51.5, 32.5]}) == (
        51.5,
        32.5,
        51.5,
        32.5,
    )


def test_empty_and_invalid_geometry_raise_geometry_errors():
    with pytest.raises(GeometryError):
        bbox_of_geojson({})
    with pytest.raises(GeometryError):
        bbox_of_geojson({"type": "LineString", "coordinates": []})
    with pytest.raises(GeometryError):
        bbox_of_geojson(
            {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 1.0]]]}
        )


def test_point_bbox_cannot_form_a_grid():
    with pytest.raises(ValueError, match="positive extent"):
        grid_cells(bbox_of_geojson({"type": "Point", "coordinates": [51.5, 32.5]}), 2, 2)


def test_geometry_axis_order_is_wgs84_lng_lat():
    (cell,) = grid_cells((10.0, 20.0, 11.0, 21.0), 1, 1)
    ring = cell.geometry["coordinates"][0]
    assert ring[0] == [cell.west, cell.south]
    assert ring[2] == [cell.east, cell.north]


# ==========================================================================
# Aggregation and concentration
# ==========================================================================


def _grid_obs(
    values: List[Optional[float]],
    categories: Optional[List[Optional[str]]] = None,
    coverages: Optional[List[Optional[float]]] = None,
) -> List[CellObservation]:
    cells = grid_cells(BBOX, 3, 3)
    observations = []
    for index, cell in enumerate(cells):
        value = values[index]
        observations.append(
            _obs(
                cell.cell_id,
                value,
                category=categories[index] if categories else None,
                coverage=coverages[index] if coverages else 100.0,
            )
        )
    return observations


def test_single_cell_anomaly_reports_insufficient_not_concentration():
    summary = aggregate_cells(
        _grid_obs([0.20] + [None] * 8, ["BELOW_BASELINE"] + [None] * 8)[:1]
    )
    assert summary.n_cells == 1
    assert summary.n_usable == 1
    assert summary.state == STATE_INSUFFICIENT


def test_fully_anomalous_grid_is_concentrated():
    summary = aggregate_cells(
        _grid_obs([0.20] * 9, ["BELOW_BASELINE"] * 9)
    )
    assert summary.state == STATE_CONCENTRATED_ANOMALY
    assert summary.anomalous_count == 9
    assert summary.anomalous_fraction == pytest.approx(1.0)
    assert summary.mean == pytest.approx(0.20)
    assert summary.median == pytest.approx(0.20)
    assert area_state(_grid_obs([0.20] * 9, ["BELOW_BASELINE"] * 9)) == (
        STATE_CONCENTRATED_ANOMALY
    )


def test_normal_cells_report_normal_area():
    summary = aggregate_cells(_grid_obs([0.60] * 9, ["NORMAL"] * 9))
    assert summary.state == STATE_NORMAL_AREA
    assert summary.anomalous_count == 0
    assert summary.anomalous_fraction == pytest.approx(0.0)


def test_dispersed_anomalies_are_anomalous_not_concentrated():
    categories = ["BELOW_BASELINE", "BELOW_BASELINE"] + ["NORMAL"] * 7
    summary = aggregate_cells(_grid_obs([0.20, 0.25] + [0.60] * 7, categories))
    assert summary.state == STATE_ANOMALOUS_AREA
    assert summary.anomalous_fraction == pytest.approx(2.0 / 9.0)


def test_missing_cells_lower_counts_but_never_enter_means():
    values: List[Optional[float]] = [0.20, None, 0.30, None, 0.25, None, 0.22, None, 0.28]
    categories = [
        "BELOW_BASELINE",
        None,
        "BELOW_BASELINE",
        None,
        "BELOW_BASELINE",
        None,
        "BELOW_BASELINE",
        None,
        "BELOW_BASELINE",
    ]
    summary = aggregate_cells(_grid_obs(values, categories))
    assert summary.n_cells == 9
    assert summary.n_usable == 5
    assert summary.n_missing == 4
    assert summary.mean == pytest.approx((0.20 + 0.30 + 0.25 + 0.22 + 0.28) / 5)
    assert summary.state == STATE_CONCENTRATED_ANOMALY


def test_all_missing_grid_reports_insufficient():
    summary = aggregate_cells(_grid_obs([None] * 9))
    assert summary.state == STATE_INSUFFICIENT
    assert summary.mean is None
    assert summary.median is None
    assert summary.anomalous_fraction is None


def test_insufficient_usable_cells_despite_anomalies():
    observations = _grid_obs(
        [0.20, 0.22] + [None] * 7, ["BELOW_BASELINE"] * 2 + [None] * 7
    )[:2]
    summary = aggregate_cells(observations)
    assert summary.n_usable == 2
    assert summary.state == STATE_INSUFFICIENT


def test_coverage_summary_keeps_poor_support_visible():
    summary = aggregate_cells(
        _grid_obs(
            [0.20, 0.22, 0.25, 0.30, 0.60, 0.62, 0.58, 0.61, 0.59],
            ["BELOW_BASELINE"] * 4 + ["NORMAL"] * 5,
            coverages=[12.0, 25.0, 90.0, 95.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
    )
    assert summary.min_coverage_percent == pytest.approx(12.0)
    assert summary.mean_coverage_percent == pytest.approx(
        (12.0 + 25.0 + 90.0 + 95.0 + 100.0 * 5) / 9.0
    )
    assert summary.quality_counts == {"good": 9}


def test_aggregation_rejects_mixed_metrics_windows_and_empties():
    observations = _grid_obs([0.20] * 9, ["BELOW_BASELINE"] * 9)
    other = _obs("r00c00", 0.20, "BELOW_BASELINE", metric_key="ndmi")
    with pytest.raises(ValueError, match="one metric"):
        aggregate_cells(observations + [other])
    shifted = [
        CellObservation(
            cell_id="r00c00",
            metric_key="ndvi",
            window_start="2024-06-01",
            window_end="2024-06-30",
            value=0.20,
        )
    ]
    with pytest.raises(ValueError, match="one window"):
        aggregate_cells(observations[:2] + shifted)
    with pytest.raises(ValueError, match="at least one"):
        aggregate_cells([])


def test_concentration_policy_constants():
    assert MIN_VALID_CELLS == 3
    assert CONCENTRATION_MIN_FRACTION == 0.5


# ==========================================================================
# Multi-metric concordance
# ==========================================================================


def _layer(
    metric_key: str, value: Optional[float], category: Optional[str]
) -> CellObservation:
    return _obs("r00c00", value, category, metric_key=metric_key)


def test_two_below_layers_are_multi_metric():
    result = cell_concordance(
        {
            "ndvi": _layer("ndvi", 0.30, "BELOW_BASELINE"),
            "ndmi": _layer("ndmi", 0.15, "BELOW_BASELINE"),
        }
    )
    assert result.state == CONCORDANCE_MULTI_METRIC
    assert result.anomalous_metrics == ("ndmi", "ndvi")
    assert result.cell_id == "r00c00"


def test_single_anomalous_layer_is_single_metric():
    result = cell_concordance(
        {
            "ndvi": _layer("ndvi", 0.30, "BELOW_BASELINE"),
            "ndmi": _layer("ndmi", 0.45, "NORMAL"),
        }
    )
    assert result.state == CONCORDANCE_SINGLE_METRIC
    assert result.anomalous_metrics == ("ndvi",)


def test_opposite_anomalies_are_mixed():
    result = cell_concordance(
        {
            "ndvi": _layer("ndvi", 0.30, "BELOW_BASELINE"),
            "ndmi": _layer("ndmi", 0.75, "ABOVE_BASELINE"),
        }
    )
    assert result.state == CONCORDANCE_MIXED


def test_no_anomaly_is_no_concordance():
    result = cell_concordance(
        {
            "ndvi": _layer("ndvi", 0.60, "NORMAL"),
            "ndmi": _layer("ndmi", 0.45, "NORMAL"),
        }
    )
    assert result.state == CONCORDANCE_NONE


def test_missing_layers_are_excluded_not_negative():
    result = cell_concordance(
        {
            "ndvi": _layer("ndvi", 0.30, "BELOW_BASELINE"),
            "ndmi": _layer("ndmi", None, None),
        }
    )
    assert result.state == CONCORDANCE_SINGLE_METRIC
    result = cell_concordance(
        {
            "ndvi": _layer("ndvi", None, None),
            "ndmi": _layer("ndmi", None, None),
        }
    )
    assert result.state == CONCORDANCE_INSUFFICIENT


def test_concordance_rejects_mixed_cells_windows_and_empties():
    layers = {
        "ndvi": _layer("ndvi", 0.30, "BELOW_BASELINE"),
        "ndmi": _layer("ndmi", 0.15, "BELOW_BASELINE"),
    }
    other_cell = _obs("r00c01", 0.30, "BELOW_BASELINE")
    with pytest.raises(ValueError, match="one cell"):
        cell_concordance({**layers, "vv": other_cell})
    other_window = CellObservation(
        cell_id="r00c00",
        metric_key="vv",
        window_start="2024-06-01",
        window_end="2024-06-30",
        value=-10.0,
    )
    with pytest.raises(ValueError, match="one window"):
        cell_concordance({**layers, "vv": other_window})
    with pytest.raises(ValueError, match="at least one"):
        cell_concordance({})


# ==========================================================================
# Temporal persistence per cell
# ==========================================================================


def test_repeated_below_deviation_is_persistent():
    result = track_cell_persistence("r00c00", [-1.5, -2.0, -1.2, 0.5, 1.1])
    assert result.state == "PERSISTENT"
    assert result.longest_run_below == 3
    assert result.n_observed == 5
    assert result.n_missing == 0


def test_interrupted_runs_do_not_persist():
    result = track_cell_persistence("r00c00", [-1.5, -2.0, None, -1.2, -0.8, 0.5])
    assert result.state == "NO_PERSISTENCE"
    assert result.longest_run_below == 2
    assert result.n_missing == 1


def test_empty_series_is_insufficient():
    result = track_cell_persistence("r00c00", [None, None])
    assert result.state == "INSUFFICIENT"
    assert result.n_observed == 0


# ==========================================================================
# Per-cell evaluation through the production path
# ==========================================================================


class _FakeNumber:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def getInfo(self):
        return self._value

    def Or(self, _other):  # noqa: N802 - mirrors ee
        return self

    def Not(self):  # noqa: N802 - mirrors ee
        return self

    def eq(self, _other):
        return self


class _FakeReducer:
    def combine(self, _other, sharedInputs=False):  # noqa: N803 - mirrors ee
        return self


class _FakeReducerNamespace:
    @staticmethod
    def count():
        return _FakeReducer()

    @staticmethod
    def mean():
        return _FakeReducer()

    @staticmethod
    def median():
        return _FakeReducer()

    @staticmethod
    def stdDev():  # noqa: N802 - mirrors ee
        return _FakeReducer()

    @staticmethod
    def min():
        return _FakeReducer()

    @staticmethod
    def max():
        return _FakeReducer()

    @staticmethod
    def percentile(_values):
        return _FakeReducer()


class _FakeFilterNamespace:
    @staticmethod
    def eq(_key, _value):
        return ("eq",)

    @staticmethod
    def lte(_key, _value):  # noqa: N802 - mirrors ee
        return ("lte",)

    @staticmethod
    def listContains(_key, _value):  # noqa: N802 - mirrors ee
        return ("listContains",)


class _FakeImageNamespace:
    @staticmethod
    def constant(_value):
        return _FakeNumber(0)


_ALLOWED_BANDS = {"SCL", "B4", "B8"}


class _FakeRegion:
    def __init__(self, fake: "FakeSpatialEE", scale: int = 10) -> None:
        self._fake = fake
        self._scale = scale

    def getInfo(self):
        return self._fake._pop_stats(self._scale)


class _FakeImage:
    def __init__(self, fake: "FakeSpatialEE") -> None:
        self._fake = fake
        self._bands = set(_ALLOWED_BANDS)

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in self._bands:
                raise KeyError(f"fake spatial image holds {sorted(self._bands)}")
        return self

    def rename(self, name):
        self._bands.add(name)
        return self

    def updateMask(self, _mask):  # noqa: N802 - mirrors ee
        return self

    def multiply(self, _factor):
        return self

    def normalizedDifference(self, _bands):  # noqa: N802 - mirrors ee
        return self

    def expression(self, _formula, _variables):
        return self

    def eq(self, _other):
        return _FakeNumber(0)

    def reduceRegion(self, **kwargs):
        return _FakeRegion(self._fake, int(kwargs.get("scale", 10)))


class _FakeMapped:
    def __init__(self, fake: "FakeSpatialEE") -> None:
        self._fake = fake

    def median(self):
        return _FakeImage(self._fake)


class _FakeCollection:
    def __init__(self, fake: "FakeSpatialEE") -> None:
        self._fake = fake

    def filterDate(self, *_args):
        return self

    def filterBounds(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        for band in bands:
            if band not in _ALLOWED_BANDS:
                raise KeyError(f"fake spatial collection holds {_ALLOWED_BANDS}")
        return self

    def size(self):
        return _FakeNumber(self._fake._peek_scenes())

    def map(self, func):
        func(_FakeImage(self._fake))
        return _FakeMapped(self._fake)

    def mean(self):
        return _FakeImage(self._fake)


class FakeSpatialEE:
    """One queued outcome per evaluated cell, in call order."""

    def __init__(self, outcomes: List[Dict[str, Any]]) -> None:
        self._queue: Deque[Dict[str, Any]] = deque(outcomes)
        self.Reducer = _FakeReducerNamespace()
        self.Filter = _FakeFilterNamespace()
        self.Image = _FakeImageNamespace()

    def ImageCollection(self, _dataset_id):  # noqa: N802 - mirrors ee
        return _FakeCollection(self)

    def _peek_scenes(self) -> int:
        if not self._queue:
            raise AssertionError("fake spatial queue exhausted on size()")
        return int(self._queue[0]["scenes"])

    def _pop_stats(self, scale: int) -> Dict[str, Any]:
        if not self._queue:
            raise AssertionError("fake spatial queue exhausted on reduceRegion()")
        outcome = self._queue.popleft()
        mean = outcome["mean"]
        if mean is None or not isinstance(mean, (int, float)):
            return {}
        value = float(mean)
        total = int(AREA_SQ_M / (scale * scale))
        return {
            "mean": value,
            "median": value,
            "min": value,
            "max": value,
            "stdDev": 0.0,
            "p10": value,
            "p25": value,
            "p75": value,
            "p90": value,
            "count": total,
        }


@pytest.fixture
def fake_spatial(monkeypatch):
    def install(outcomes: List[Dict[str, Any]]) -> FakeSpatialEE:
        fake = FakeSpatialEE(outcomes)
        import ee

        for name in ("ImageCollection", "Reducer", "Filter", "Image"):
            monkeypatch.setattr(ee, name, getattr(fake, name))
        return fake

    return install


def _cell_outcome(mean: Optional[float], scenes: int = 6) -> Dict[str, Any]:
    return {"mean": mean, "scenes": scenes}


def test_cell_evaluation_uses_the_metric_production_path(fake_spatial):
    fake_spatial([_cell_outcome(0.62)])
    cells = grid_cells(BBOX, 1, 1)
    observation = evaluate_cell("ndvi", make_context(), cells[0].cell_id, cells[0].geometry)
    assert observation.cell_id == "r00c00"
    assert observation.metric_key == "ndvi"
    assert observation.value == pytest.approx(0.62)
    assert observation.unit == "index"
    assert observation.quality in ("excellent", "good", "moderate")
    assert observation.coverage_percent == pytest.approx(100.0)
    assert observation.image_count == 6


def test_empty_cell_collection_is_missing_not_zero(fake_spatial):
    fake_spatial([_cell_outcome(None, scenes=0)])
    cells = grid_cells(BBOX, 1, 1)
    observation = evaluate_cell("ndvi", make_context(), cells[0].cell_id, cells[0].geometry)
    assert observation.value is None
    assert observation.quality == "unavailable"


def test_unsupported_metric_key_is_refused(fake_spatial):
    fake_spatial([])
    cells = grid_cells(BBOX, 1, 1)
    with pytest.raises(ValueError, match="Supported metrics"):
        evaluate_cell("soil_field_capacity", make_context(), cells[0].cell_id, cells[0].geometry)


def test_cache_keys_are_namespaced_per_cell():
    context = make_context()
    assert cell_cache_key(context, "r00c00") != cell_cache_key(context, "r00c01")
    assert cell_cache_key(context, "r00c00") == cell_cache_key(context, "r00c00")


def test_evaluate_grid_preserves_cell_order(fake_spatial):
    fake_spatial([_cell_outcome(0.60), _cell_outcome(0.62)])
    cells = grid_cells(BBOX, 1, 2)
    observations = evaluate_grid("ndvi", make_context(), cells)
    assert [obs.cell_id for obs in observations] == ["r00c00", "r00c01"]
    assert [obs.value for obs in observations] == [pytest.approx(0.60), pytest.approx(0.62)]


# ==========================================================================
# Multiple metrics, determinism, round-trips, guards
# ==========================================================================


def test_ndvi_and_vh_grids_stay_independent():
    ndvi_summary = aggregate_cells(
        _grid_obs([0.60] * 9, ["NORMAL"] * 9)[:4]
    )
    vh_obs = [
        _obs(
            cell.cell_id,
            -12.0,
            "BELOW_BASELINE",
            metric_key="vh",
            unit="dB",
        )
        for cell in grid_cells(BBOX, 2, 2)
    ]
    vh_summary = aggregate_cells(vh_obs)
    assert ndvi_summary.mean == pytest.approx(0.60)
    assert vh_summary.mean == pytest.approx(-12.0)
    assert ndvi_summary.state == STATE_NORMAL_AREA
    assert vh_summary.state == STATE_CONCENTRATED_ANOMALY


def test_deterministic_output():
    first = aggregate_cells(_grid_obs([0.20] * 9, ["BELOW_BASELINE"] * 9))
    second = aggregate_cells(_grid_obs([0.20] * 9, ["BELOW_BASELINE"] * 9))
    assert first == second
    assert grid_cells(BBOX, 2, 2) == grid_cells(BBOX, 2, 2)


def test_pydantic_round_trip():
    from app.schemas.agriculture import (
        CellConcordanceModel,
        CellObservationModel,
        CellPersistenceModel,
        SpatialCellModel,
        SpatialSummaryModel,
    )

    (cell,) = grid_cells(BBOX, 1, 1)
    assert SpatialCellModel(**cell.to_dict()).cell_id == "r00c00"
    observation = _obs("r00c00", 0.30, "BELOW_BASELINE")
    assert CellObservationModel(**observation.to_dict()).value == pytest.approx(0.30)
    summary = aggregate_cells(_grid_obs([0.20] * 9, ["BELOW_BASELINE"] * 9))
    summary_model = SpatialSummaryModel(**summary.to_dict())
    assert summary_model.state == STATE_CONCENTRATED_ANOMALY
    assert summary_model.anomalous_fraction == pytest.approx(1.0)
    concordance = cell_concordance(
        {
            "ndvi": _layer("ndvi", 0.30, "BELOW_BASELINE"),
            "ndmi": _layer("ndmi", 0.15, "BELOW_BASELINE"),
        }
    )
    assert CellConcordanceModel(**concordance.to_dict()).state == (
        CONCORDANCE_MULTI_METRIC
    )
    persistence = track_cell_persistence("r00c00", [-1.5, -2.0, -1.2, 0.5])
    assert CellPersistenceModel(**persistence.to_dict()).state == "PERSISTENT"


def test_no_pest_disease_language_in_production_states():
    import app.services.agriculture.spatial_profile as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "must not choose among these causes" in source
    for token in (
        "pest_risk",
        "pest-risk",
        "severity_level",
        "probability_of",
        "machine learning",
        "sklearn",
        "torch",
        "tensorflow",
        "training data",
        "defoliation",
        "outbreak",
        "infestation",
        "infection",
    ):
        assert token not in source.lower(), token
    states = {
        STATE_NORMAL_AREA,
        STATE_ANOMALOUS_AREA,
        STATE_CONCENTRATED_ANOMALY,
        STATE_INSUFFICIENT,
        CONCORDANCE_SINGLE_METRIC,
        CONCORDANCE_MULTI_METRIC,
        CONCORDANCE_MIXED,
        CONCORDANCE_NONE,
        CONCORDANCE_INSUFFICIENT,
    }
    for state in states:
        lowered = state.lower()
        assert "pest" not in lowered and "disease" not in lowered


def test_concentration_policy_constants():
    assert MIN_VALID_CELLS == 3
    assert CONCENTRATION_MIN_FRACTION == 0.5


def test_module_touches_no_database_or_network():
    import app.services.agriculture.spatial_profile as module

    source = open(module.__file__, encoding="utf-8").read().lower()
    for token in ("sqlite", "postgres", "sqlalchemy", "requests.get", "urllib"):
        assert token not in source, token
