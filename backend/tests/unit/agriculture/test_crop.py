"""Tests for the crop context and crop area engine (Phase I).

The governing risks here are the ones that would produce a plausible but
invented claim:

1. **A crop identity the dataset does not carry.** The only named species
   any registered product supports is maize, and "cereals" means the
   Triticeae tribe (wheat, barley, rye) which the product deliberately
   does not split. A wheat-only, rice or pistachio claim would be an
   invention, so the tests pin the class names and scan the module's own
   prose for unauthorised species.

2. **A year the dataset does not cover.** The collection is the 2021
   reference year. Any request outside 2020-01-01..2021-12-31 must be
   refused by ``can_attempt`` before any Earth Engine call, and the tests
   verify the gate by installing a fake ``ee`` that records whether it
   was ever touched.

3. **Area from a probability instead of a mask.** Dynamic World carries
   per-pixel posteriors, which are not sub-pixel fractions; only the
   WorldCereal binary mask supports a pixel-count area. A Dynamic World
   area metric would be an invented conversion and is tested to not
   exist.

4. **Area published without its coverage.** A crop-area figure over a
   half-classified geometry is a claim about the missing half too. The
   valid-pixel floor is therefore load-bearing and tested both ways.

The Earth Engine calls run against a strict fake whose collection
resolves ``first()`` only when a fixture for the exact product/season
pair exists, so a filter mix-up fails loudly instead of silently
reducing the wrong image.
"""

from __future__ import annotations

import pytest

from app.services.agriculture.base import MetricContext
from app.services.agriculture.catalog import (
    clear_registry,
    get_metric,
    metric_keys,
)
from app.services.agriculture.crop import (
    ALL_CROP_METRICS,
    CROP_AREA_MIN_VALID_FRACTION,
    CROP_METRICS,
    CerealCropContextMetric,
    FloweringDateMetric,
    FLOWERING_UNAVAILABLE_CODE,
    FLOWERING_UNAVAILABLE_REASON,
    MaizeCropContextMetric,
    PLANTING_UNAVAILABLE_CODE,
    PLANTING_UNAVAILABLE_REASON,
    HARVEST_UNAVAILABLE_CODE,
    HARVEST_UNAVAILABLE_REASON,
    TemporaryCropAreaMetric,
    TemporaryCropContextMetric,
    UNAVAILABLE_CROP_METRICS,
    WORLDCEREAL_ID,
    CropPlantingDateMetric,
    CropHarvestDateMetric,
)
from app.services.agriculture.landcover import DYNAMIC_WORLD
from app.services.agriculture.registry import get_dataset
from app.services.agriculture.registry.datasets import (
    WORLDCEREAL_BINARY_VALUES,
    WORLDCEREAL_PRODUCTS,
    WORLDCEREAL_SEASONS,
)
from app.services.agriculture.types import (
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_UNAVAILABLE,
)

EXPECTED_AVAILABLE_KEYS = {
    "temporary_crop_context",
    "maize_context",
    "cereal_context",
    "temporary_crop_area",
}
EXPECTED_UNAVAILABLE_KEYS = {
    "crop_planting_date",
    "crop_harvest_date",
    "crop_flowering_date",
}

#: The reference window the products were published for.
REFERENCE_START = "2021-01-01"
REFERENCE_END = "2021-12-31"

#: A geometry area of 100 pixels at 10 m.
GEOMETRY_AREA_SQ_M = 100 * 10 * 10


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def make_context(
    start: str = REFERENCE_START,
    end: str = REFERENCE_END,
    area_sq_m: float = GEOMETRY_AREA_SQ_M,
) -> MetricContext:
    return MetricContext(
        geometry={},
        start_date=start,
        end_date=end,
        geometry_key="test-geometry",
        options={"area_sq_m": area_sq_m},
    )


# ==========================================================================
# Fake Earth Engine: one binary image per (product, season) fixture
# ==========================================================================


class _FakeNumber:
    def __init__(self, value):
        self._value = value

    def getInfo(self):
        return self._value


class _FakeRegionResult:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeImage:
    """One binary image with a pre-reduced payload."""

    def __init__(self, band, payload):
        self._band = band
        self._payload = payload

    def select(self, bands):
        if isinstance(bands, str):
            bands = [bands]
        if bands and bands[0] != self._band:
            raise KeyError(f"fake image holds {self._band!r}, not {bands!r}")
        return self

    def reduceRegion(self, **kwargs):
        reducer = kwargs.get("reducer")
        assert reducer is not None
        # The shared continuous reducer chain leads with count().
        assert getattr(reducer, "name", "") == "count", reducer.name
        return _FakeRegionResult(self._payload)


class _FakeCollection:
    def __init__(self, fixture, requested=None, touched=None):
        self._fixture = fixture  # dict: (product, season) -> payload
        self._requested = requested or {}
        self._touched = touched if touched is not None else set()

    def filterDate(self, start, end):
        self._touched.add(f"dates:{start}:{end}")
        return self

    def filterBounds(self, *_args):
        return self

    def filterMetadata(self, name, operator, value):
        key = (self._requested.get("product"), self._requested.get("season"))
        # Record the filter so the fixture-miss test can see it happened.
        self._touched.add(f"filter:{name}={value}")
        if name == "product":
            self._requested["product"] = value
        elif name == "season":
            self._requested["season"] = value
        return self

    def size(self):
        key = (self._requested.get("product"), self._requested.get("season"))
        if key not in self._fixture:
            return _FakeNumber(0)
        return _FakeNumber(1)

    def first(self):
        key = (self._requested.get("product"), self._requested.get("season"))
        if key not in self._fixture:
            raise KeyError(
                f"fixture has no image for {key!r}; the metric filtered "
                "for a product/season the test did not provide"
            )
        band, payload = self._fixture[key]
        return _FakeImage(band, payload)


class FakeEE:
    def __init__(self, fixture):
        self._fixture = fixture
        self.touched = set()
        self.Reducer = _ReducerNamespace()

    def ImageCollection(self, dataset_id):  # noqa: N802 - mirrors ee API
        assert dataset_id == WORLDCEREAL_ID, dataset_id
        return _FakeCollection(self._fixture, touched=self.touched)


class _FakeReducer:
    def __init__(self, name):
        self.name = name

    def combine(self, other, sharedInputs=False):  # noqa: N803
        return self


class _ReducerNamespace:
    @staticmethod
    def count():
        return _FakeReducer("count")

    @staticmethod
    def mean():
        return _FakeReducer("mean")

    @staticmethod
    def median():
        return _FakeReducer("median")

    @staticmethod
    def stdDev():
        return _FakeReducer("stdDev")

    @staticmethod
    def min():
        return _FakeReducer("min")

    @staticmethod
    def max():
        return _FakeReducer("max")

    @staticmethod
    def percentile(values):
        return _FakeReducer(f"p{values}")


def install_fake_ee(monkeypatch, fixture):
    fake = FakeEE(fixture)
    monkeypatch.setattr("ee.ImageCollection", fake.ImageCollection)
    monkeypatch.setattr("ee.Reducer", fake.Reducer)
    return fake


def full_payload(mean_value):
    """A reduction payload for a 100-pixel geometry at a given mean."""
    return {
        "classification_count": 100,
        "classification_mean": mean_value,
        "classification_median": mean_value,
        "classification_min": 0.0 if mean_value < 100 else 100.0,
        "classification_max": 100.0 if mean_value > 0 else 0.0,
        "classification_stdDev": 0.0,
        "classification_p10": mean_value,
        "classification_p25": mean_value,
        "classification_p75": mean_value,
        "classification_p90": mean_value,
    }


# ==========================================================================
# Collection integrity and registry wiring
# ==========================================================================


def test_all_expected_crop_metrics_present():
    assert {m.key for m in CROP_METRICS} == EXPECTED_AVAILABLE_KEYS


def test_all_expected_unavailable_crop_metrics_present():
    assert {m.key for m in UNAVAILABLE_CROP_METRICS} == EXPECTED_UNAVAILABLE_KEYS


def test_no_duplicate_crop_metric_keys():
    keys = [m.key for m in ALL_CROP_METRICS]
    assert len(keys) == len(set(keys))


def test_every_crop_metric_is_in_the_crop_domain():
    for metric in ALL_CROP_METRICS:
        assert metric.domain == "crop", metric.key


def test_every_crop_metric_declares_limitations_and_names():
    for metric in ALL_CROP_METRICS:
        assert metric.limitations, metric.key
        assert metric.display_name_fa, metric.key


def test_every_available_crop_metric_reads_worldcereal():
    for metric in CROP_METRICS:
        assert metric.dataset_ids == (WORLDCEREAL_ID,), metric.key


def test_registration_reaches_the_catalog():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    for key in EXPECTED_AVAILABLE_KEYS | EXPECTED_UNAVAILABLE_KEYS:
        assert key in metric_keys(), key


def test_the_registered_context_metric_round_trips():
    from app.services.agriculture import register_all_metrics

    register_all_metrics()
    metric = get_metric("temporary_crop_context")
    assert isinstance(metric, TemporaryCropContextMetric)


# ==========================================================================
# Dataset contract
# ==========================================================================


def test_the_worldcereal_dataset_is_verified():
    dataset = get_dataset(WORLDCEREAL_ID)
    assert dataset.is_verified is True


def test_the_worldcereal_classification_band_is_binary():
    values = tuple(WORLDCEREAL_BINARY_VALUES)
    assert values == (0, 100)


def test_the_worldcereal_products_include_the_three_used_here():
    assert {"temporarycrops", "maize", "wintercereals"}.issubset(
        set(WORLDCEREAL_PRODUCTS)
    )


def test_the_worldcereal_seasons_include_the_three_used_here():
    assert {"tc-annual", "tc-maize-main", "tc-wintercereals"}.issubset(
        set(WORLDCEREAL_SEASONS)
    )


# ==========================================================================
# Temporal semantics: the 2021 reference year is a hard gate
# ==========================================================================


def test_a_reference_year_request_can_attempt():
    metric = TemporaryCropContextMetric()
    can, reason = metric.can_attempt(make_context())
    assert can is True
    assert reason is None


def test_a_request_after_2021_is_out_of_coverage():
    metric = TemporaryCropContextMetric()
    can, reason = metric.can_attempt(make_context("2023-01-01", "2023-12-31"))
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_a_request_before_2020_is_out_of_coverage():
    metric = TemporaryCropContextMetric()
    can, reason = metric.can_attempt(make_context("2019-01-01", "2019-12-31"))
    assert can is False
    assert reason == "outside_temporal_coverage"


def test_out_of_coverage_requests_never_touch_earth_engine(monkeypatch):
    """The capability gate must reject before any collection is opened."""
    fake = install_fake_ee(monkeypatch, fixture={})
    metric = TemporaryCropContextMetric()
    result = metric.compute(make_context("2023-01-01", "2023-12-31"))

    assert result.status == STATUS_UNAVAILABLE
    assert fake.touched == set()


def test_reversed_dates_are_rejected():
    metric = TemporaryCropContextMetric()
    can, _reason = metric.can_attempt(make_context("2021-12-31", "2021-01-01"))
    assert can is False


def test_the_area_metric_shares_the_temporal_gate():
    metric = TemporaryCropAreaMetric()
    can, reason = metric.can_attempt(make_context("2022-01-01", "2022-12-31"))
    assert can is False
    assert reason == "outside_temporal_coverage"


# ==========================================================================
# Product and season filters
# ==========================================================================


def test_the_context_metrics_filter_for_their_own_product(monkeypatch):
    fixture = {
        ("temporarycrops", "tc-annual"): (
            "classification",
            full_payload(80.0),
        ),
    }
    install_fake_ee(monkeypatch, fixture)

    result = TemporaryCropContextMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.8)


def test_a_missing_product_yields_insufficient_not_zero(monkeypatch):
    """An unprocessed zone is missing data, not an absence of crop."""
    install_fake_ee(monkeypatch, fixture={})
    result = TemporaryCropContextMetric().compute(make_context())

    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None
    assert result.message and "not processed" in result.message


def test_the_maize_metric_asks_for_its_own_season(monkeypatch):
    class _RecordingEE(FakeEE):
        def ImageCollection(self, dataset_id):  # noqa: N802
            collection = super().ImageCollection(dataset_id)
            collection._touched = self.touched
            return collection

    fixture = {
        ("maize", "tc-maize-main"): ("classification", full_payload(20.0)),
    }
    fake = _RecordingEE(fixture)
    monkeypatch.setattr("ee.ImageCollection", fake.ImageCollection)
    monkeypatch.setattr("ee.Reducer", fake.Reducer)

    result = MaizeCropContextMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert "filter:product=maize" in fake.touched
    assert "filter:season=tc-maize-main" in fake.touched


def test_the_cereal_metric_names_the_triticeae_scope():
    metric = CerealCropContextMetric()
    joined = " ".join(metric.limitations).lower()
    assert "triticeae" in joined or "wheat, barley" in joined


# ==========================================================================
# Binary mask semantics
# ==========================================================================


def test_the_share_is_the_mask_mean_over_one_hundred(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(55.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.value == pytest.approx(0.55)


def test_a_full_mask_reports_full_share(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(100.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.value == pytest.approx(1.0)


def test_an_empty_mask_reports_zero_share_without_error(monkeypatch):
    """A classified zero is a real measurement, unlike missing data."""
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(0.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.0)


def test_an_out_of_domain_mean_is_refused(monkeypatch):
    """A mean outside 0..100 means the band was not the documented mask."""
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(150.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA


def test_the_provenance_names_the_product_and_season(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(60.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.provenance is not None
    assert "temporarycrops" in result.provenance.formula
    assert "tc-annual" in result.provenance.formula


def test_the_provenance_names_the_reference_year(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(60.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.provenance is not None
    assert "2021" in result.provenance.formula


def test_the_result_carries_a_2021_reference_warning(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(60.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    joined = " ".join(result.warnings)
    assert "2021" in joined


# ==========================================================================
# The valid-pixel floor
# ==========================================================================


def test_a_half_classified_geometry_is_refused(monkeypatch):
    """The floor is load-bearing: missing pixels are not crop."""
    payload = full_payload(50.0)
    payload["classification_count"] = 49  # just under the 50% floor
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): ("classification", payload),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.value is None


def test_a_just_over_floor_geometry_is_published(monkeypatch):
    payload = full_payload(50.0)
    payload["classification_count"] = 51
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): ("classification", payload),
        },
    )
    result = TemporaryCropContextMetric().compute(make_context())
    assert result.status == STATUS_OK


def test_the_floor_is_declared_and_sane():
    assert 0.0 < CROP_AREA_MIN_VALID_FRACTION <= 1.0


def test_a_point_geometry_with_no_area_is_refused(monkeypatch):
    """Without an area denominator no coverage claim can be made."""
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(60.0),
            ),
        },
    )
    result = TemporaryCropContextMetric().compute(
        make_context(area_sq_m=None)
    )
    assert result.status == STATUS_INSUFFICIENT_DATA


# ==========================================================================
# Crop area
# ==========================================================================


def test_the_area_value_is_a_fraction_and_the_areas_travel_in_prose(
    monkeypatch,
):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(40.0),
            ),
        },
    )
    result = TemporaryCropAreaMetric().compute(make_context())

    assert result.status == STATUS_OK
    assert result.value == pytest.approx(0.4)
    joined = " ".join(result.warnings)
    # 40 pixels of 100 valid, each 100 m2 -> 4000 m2.
    assert "4,000" in joined.replace("\u202f", ",")
    assert "10 m" in joined


def test_the_area_prose_distinguishes_total_from_crop_area(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(40.0),
            ),
        },
    )
    result = TemporaryCropAreaMetric().compute(make_context())
    joined = " ".join(result.warnings)
    assert "Total geometry area" in joined
    assert "temporary-crop area" in joined


def test_the_area_prose_flags_a_partially_classified_geometry(monkeypatch):
    payload = full_payload(50.0)
    payload["classification_count"] = 60
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): ("classification", payload),
        },
    )
    result = TemporaryCropAreaMetric().compute(make_context())
    joined = " ".join(result.warnings)
    assert "did not classify the whole geometry" in joined


def test_the_area_prose_states_it_is_not_survey_grade(monkeypatch):
    install_fake_ee(
        monkeypatch,
        fixture={
            ("temporarycrops", "tc-annual"): (
                "classification",
                full_payload(40.0),
            ),
        },
    )
    result = TemporaryCropAreaMetric().compute(make_context())
    joined = " ".join(result.warnings)
    assert "survey-grade" in joined


def test_the_area_metric_reports_its_validation_accuracies():
    joined = " ".join(TemporaryCropAreaMetric().limitations).lower()
    assert "88.5" in joined
    assert "92.1" in joined


def test_the_area_metric_reports_mixed_pixel_limitation():
    joined = " ".join(TemporaryCropAreaMetric().limitations).lower()
    assert "mixed pixels" in joined or "boundary error" in joined


def test_the_area_metric_is_not_built_from_dynamic_world():
    """A probability is not an area; the area metric must read the mask."""
    for metric in CROP_METRICS:
        assert DYNAMIC_WORLD not in metric.dataset_ids, metric.key


# ==========================================================================
# Scientific guards: no invented species, no invented years
# ==========================================================================


def test_no_crop_metric_claims_a_species_outside_the_product():
    """Wheat, barley and rye may be named only as the Triticeae grouping."""
    for metric in CROP_METRICS:
        text = (metric.description + " " + " ".join(metric.limitations)).lower()
        for species in ("rice", "pistachio", "cotton", "sugar beet"):
            assert species not in text, (metric.key, species)


def test_no_crop_metric_claims_a_present_day_capability():
    for metric in CROP_METRICS:
        text = " ".join(metric.limitations).lower()
        assert "2021" in text, metric.key
        assert "cannot describe" in text or "single reference year" in text


def test_the_context_metrics_do_not_claim_crop_type():
    for metric in (
        TemporaryCropContextMetric(),
        MaizeCropContextMetric(),
        CerealCropContextMetric(),
    ):
        text = (metric.description + " " + " ".join(metric.limitations)).lower()
        if metric.key != "maize_context":
            assert "not crop type" in text or "crop *context*" in text or (
                "context, not crop type" in text
            ), metric.key


def test_maize_is_the_only_named_species():
    named = {
        metric.key: metric.description.lower() + " ".join(metric.limitations).lower()
        for metric in CROP_METRICS
    }
    assert "maize" in named["maize_context"]
    for key, text in named.items():
        if key == "maize_context":
            continue
        # The cereal metric may name wheat/barley/rye only inside the
        # Triticeae sentence.
        if key == "cereal_context":
            assert "triticeae" in text
        else:
            assert "wheat" not in text, key


# ==========================================================================
# Deliberately unavailable metrics
# ==========================================================================


def test_the_planting_date_metric_is_registered_but_unavailable():
    metric = CropPlantingDateMetric()
    result = metric.compute(make_context())
    assert result.status == STATUS_UNAVAILABLE
    assert result.value is None
    assert metric.metadata()["available"] is False


def test_the_planting_reason_explains_greenup_is_not_sowing():
    lowered = PLANTING_UNAVAILABLE_REASON.lower()
    assert "green" in lowered
    assert "sowing" in lowered or "planting" in lowered
    assert "worldcereal" in lowered


def test_the_harvest_reason_lists_alternative_causes():
    lowered = HARVEST_UNAVAILABLE_REASON.lower()
    for cause in ("senescence", "drought", "disease"):
        assert cause in lowered


def test_the_flowering_reason_refuses_the_ndvi_peak_reading():
    lowered = FLOWERING_UNAVAILABLE_REASON.lower()
    assert "ndvi" in lowered
    assert "anthesis" in lowered or "flowering" in lowered
    assert "not" in lowered


def test_the_unavailable_metrics_carry_codes():
    assert PLANTING_UNAVAILABLE_CODE == "no_planting_date_product"
    assert HARVEST_UNAVAILABLE_CODE == "no_harvest_date_product"
    assert FLOWERING_UNAVAILABLE_CODE == "no_flowering_signal_product"


def test_no_unavailable_crop_metric_can_produce_a_value():
    for metric in UNAVAILABLE_CROP_METRICS:
        result = metric.compute(make_context())
        assert result.value is None, metric.key
        assert result.class_histogram is None, metric.key
        assert result.status == STATUS_UNAVAILABLE, metric.key


def test_the_unavailable_metrics_declare_an_inference_basis():
    from app.services.agriculture.types import MeasurementBasis

    for metric in UNAVAILABLE_CROP_METRICS:
        assert metric.measurement_basis is MeasurementBasis.INFERENCE, metric.key
