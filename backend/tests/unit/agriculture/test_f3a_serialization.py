"""F3-A focused tests — serialization-only passthrough of stats,
class_histogram, and band_means.

Frozen F3-A boundary:
  * No new statistical computation.
  * No methodology changes.
  * No availability changes.
  * Unavailable/insufficient/error results never carry the new fields.
  * Dynamic World exposes exactly the nine canonical band means.
  * Warnings are never parsed as a data transport.
  * D4 metrics (stress/irrigation/history/productivity/phenology) receive
    zero new stats attachments.

No GEE. No network. No ``ee`` import.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.agriculture.catalog import clear_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def _good_provenance():
    from app.services.agriculture.types import (
        MeasurementBasis,
        Provenance,
        QualityLevel,
        TemporalKind,
    )

    return Provenance(
        source_dataset_id="COPERNICUS/S2_SR_HARMONIZED",
        source_dataset_name="Sentinel-2 SR Harmonized",
        bands=["B4", "B8"],
        formula="(B8 - B4) / (B8 + B4)",
        unit="index",
        spatial_resolution="10m",
        temporal_resolution="5-day",
        measurement_basis=MeasurementBasis.DERIVED,
        quality_level=QualityLevel.GOOD,
        temporal_kind=TemporalKind.OBSERVATION,
        requested_start="2024-06-01",
        requested_end="2024-09-01",
        image_count=12,
    )


def _serialize_item(item):
    from app.api.v1.agriculture import _serialize_evidence_item

    return _serialize_evidence_item(item)


# --- stats round-trip ------------------------------------------------------


def test_stats_round_trip():
    """An attached SpatialStats survives MetricResult → Evidence → API."""
    from app.services.agriculture.evidence import EvidenceItem
    from app.services.agriculture.types import MetricResult, SpatialStats

    stats = SpatialStats(
        mean=0.62,
        median=0.60,
        min=0.10,
        max=0.90,
        std_dev=0.12,
        p10=0.30,
        p25=0.45,
        p75=0.75,
        p90=0.85,
        valid_pixel_count=100,
        valid_area_sq_m=10000.0,
        total_pixel_count=120,
    )
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="NDVI",
        value=0.62,
        unit="index",
        stats=stats,
        provenance=_good_provenance(),
    )
    item = EvidenceItem.from_result(result)
    assert item.stats is not None
    assert item.stats["mean"] == pytest.approx(0.62)
    assert item.stats["p90"] == pytest.approx(0.85)
    assert item.stats["valid_pixel_count"] == 100
    assert item.stats["coverage_percent"] == pytest.approx(100.0 * 100 / 120)

    response = _serialize_item(item)
    assert response.stats is not None
    assert response.stats["mean"] == pytest.approx(0.62)
    # Scalar value is preserved untouched alongside stats.
    assert response.value == pytest.approx(0.62)


# --- class_histogram round-trip --------------------------------------------


def test_class_histogram_round_trip():
    """A categorical histogram survives MetricResult → Evidence → API."""
    from app.services.agriculture.evidence import EvidenceItem
    from app.services.agriculture.types import (
        ClassHistogram,
        ClassHistogramEntry,
        MetricResult,
    )

    histogram = ClassHistogram(
        entries=[
            ClassHistogramEntry(
                code=12, name="Croplands", pixel_count=300,
                percent=60.0, percent_of_geometry=50.0,
            ),
            ClassHistogramEntry(
                code=10, name="Grasslands", pixel_count=200,
                percent=40.0, percent_of_geometry=33.3,
            ),
        ],
        dominant_code=12,
        dominant_name="Croplands",
        valid_pixel_count=500,
        total_pixel_count=600,
    )
    result = MetricResult(
        metric_key="land_cover_class",
        display_name="Land Cover Class Distribution",
        display_name_fa="توزیع کلاس پوشش زمین",
        unit="class",
        class_histogram=histogram,
        provenance=_good_provenance(),
    )
    item = EvidenceItem.from_result(result)
    assert item.value is None
    assert item.class_histogram is not None
    assert item.class_histogram["dominant_code"] == 12
    assert len(item.class_histogram["entries"]) == 2
    assert item.class_histogram["entries"][0]["code"] == 12

    response = _serialize_item(item)
    assert response.value is None
    assert response.class_histogram is not None
    assert response.class_histogram["dominant_name"] == "Croplands"


# --- band_means round-trip -------------------------------------------------


def test_band_means_round_trip_without_warning_parsing():
    """band_means travel as structured data, independent of warnings text."""
    from app.services.agriculture.evidence import EvidenceItem
    from app.services.agriculture.landcover import (
        DYNAMIC_WORLD_PROBABILITY_BANDS,
    )
    from app.services.agriculture.types import MetricResult

    means = {band: 0.10 for band in DYNAMIC_WORLD_PROBABILITY_BANDS}
    means["crops"] = 0.55
    result = MetricResult(
        metric_key="land_cover_probability",
        display_name="Land Cover Probability",
        display_name_fa="احتمال پوشش زمین",
        value=0.55,
        unit="probability",
        band_means=dict(means),
        provenance=_good_provenance(),
        warnings=[],
    )
    item = EvidenceItem.from_result(result)
    assert item.band_means is not None
    assert set(item.band_means) == set(DYNAMIC_WORLD_PROBABILITY_BANDS)
    assert item.band_means["crops"] == pytest.approx(0.55)

    response = _serialize_item(item)
    assert response.band_means is not None
    assert response.band_means["crops"] == pytest.approx(0.55)
    assert "label" not in response.band_means


def test_band_means_absent_without_structured_source():
    """A warnings-only payload never fabricates band_means."""
    from app.services.agriculture.evidence import EvidenceItem
    from app.services.agriculture.types import MetricResult

    result = MetricResult(
        metric_key="land_cover_probability",
        display_name="Land Cover Probability",
        display_name_fa="احتمال پوشش زمین",
        value=0.55,
        unit="probability",
        provenance=_good_provenance(),
        warnings=["Mean class probabilities over the period: crops 0.55"],
    )
    item = EvidenceItem.from_result(result)
    assert item.band_means is None
    assert _serialize_item(item).band_means is None


# --- null/absent behavior --------------------------------------------------


def test_new_fields_absent_for_unavailable_results():
    """Unavailable/insufficient/error results never carry the new fields."""
    from app.services.agriculture.evidence import EvidenceItem
    from app.services.agriculture.types import MetricResult

    for outcome in (
        MetricResult.unavailable(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="NDVI",
            reason="not_supported",
            message="nope",
            unit="index",
        ),
        MetricResult.insufficient(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="NDVI",
            message="nope",
            unit="index",
            provenance=_good_provenance(),
        ),
        MetricResult.error(
            metric_key="ndvi",
            display_name="NDVI",
            display_name_fa="NDVI",
            message="boom",
            unit="index",
        ),
    ):
        item = EvidenceItem.from_result(outcome)
        assert item.stats is None
        assert item.class_histogram is None
        assert item.band_means is None
        response = _serialize_item(item)
        assert response.stats is None
        assert response.class_histogram is None
        assert response.band_means is None


def test_new_fields_absent_when_metric_did_not_compute_them():
    """Metrics without structure serialize nulls, never empty fabrications."""
    from app.services.agriculture.evidence import EvidenceItem
    from app.services.agriculture.types import MetricResult

    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="NDVI",
        value=0.5,
        unit="index",
        provenance=_good_provenance(),
    )
    response = _serialize_item(EvidenceItem.from_result(result))
    assert response.stats is None
    assert response.class_histogram is None
    assert response.band_means is None


# --- Dynamic World contract -------------------------------------------------


def test_dynamic_world_canonical_bands_and_floor():
    """Exactly nine canonical bands, no label; floor unchanged at 0.4."""
    from app.services.agriculture.landcover import (
        DYNAMIC_WORLD_DOMINANT_MIN_PROBABILITY,
        DYNAMIC_WORLD_PROBABILITY_BANDS,
        LandCoverProbabilityMetric,
    )

    assert tuple(DYNAMIC_WORLD_PROBABILITY_BANDS) == (
        "water",
        "trees",
        "grass",
        "flooded_vegetation",
        "crops",
        "shrub_and_scrub",
        "built",
        "bare",
        "snow_and_ice",
    )
    assert "label" not in DYNAMIC_WORLD_PROBABILITY_BANDS
    assert DYNAMIC_WORLD_DOMINANT_MIN_PROBABILITY == pytest.approx(0.4)
    assert LandCoverProbabilityMetric.key == "land_cover_probability"
    assert LandCoverProbabilityMetric.unit == "probability"
    assert tuple(LandCoverProbabilityMetric.source_bands.fget(None)) == tuple(
        DYNAMIC_WORLD_PROBABILITY_BANDS
    )


def test_metric_result_band_means_defaults_to_none():
    """The new slot is optional and defaults to absent."""
    from app.services.agriculture.types import MetricResult

    assert "band_means" in MetricResult.__dataclass_fields__
    result = MetricResult(
        metric_key="ndvi",
        display_name="NDVI",
        display_name_fa="NDVI",
        value=0.5,
        unit="index",
        provenance=_good_provenance(),
    )
    assert result.band_means is None
    assert result.to_dict()["band_means"] is None


# --- D4: zero new attachments (static source guard) --------------------------


def _module_text(name: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / "app" / "services" / "agriculture" / name).read_text(
        encoding="utf-8"
    )


def test_d4_modules_attach_no_stats():
    """Stress/irrigation/history/productivity/phenology MetricResult sites
    carry no stats= kwarg: D4 remains zero attachments, no new computation."""
    import re

    kwarg = re.compile(r"(?m)^\s*stats=(?![=])")
    for module in (
        "stress.py",
        "irrigation.py",
        "history.py",
        "productivity.py",
        "phenology.py",
    ):
        assert kwarg.search(_module_text(module)) is None, module


def test_band_means_only_from_dynamic_world():
    """No metric module besides landcover populates band_means.

    The evidence/schema/API plumbing files are excluded: they declare
    and forward the field but never originate values.
    """
    import re

    plumbing = {"evidence.py", "types.py", "catalog.py", "__init__.py"}
    kwarg = re.compile(r"(?m)^\s*band_means=(?![=])")
    d = Path(__file__).resolve().parents[3] / "app" / "services" / "agriculture"
    populated = sorted(
        path.name
        for path in d.glob("*.py")
        if path.name not in plumbing
        and kwarg.search(path.read_text(encoding="utf-8")) is not None
    )
    assert populated == ["landcover.py"], populated
