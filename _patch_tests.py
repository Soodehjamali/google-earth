"""One-off patcher for test_terrain.py fixtures and expectations."""
from pathlib import Path
import re

p = Path("tests/unit/agriculture/test_terrain.py")
text = p.read_text(encoding="utf-8")

R = []

R.append((
    '''def test_elevation_computes_over_a_2024_request(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_elevation_computes_over_a_2024_request(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_elevation_provenance_separates_request_from_acquisition(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_elevation_provenance_separates_request_from_acquisition(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_elevation_reports_insufficient_when_no_pixels_return(monkeypatch):
    _east_facing_plane(monkeypatch)
    # A region result of all-None means the DEM masked everything.
    module = sys.modules["ee"]
    module.Image = lambda dataset_id: _FakeImage(
        None, {"elevation": None}
    )
    result = ElevationMetric().compute(_make_context())''',
    '''def test_elevation_reports_insufficient_when_no_pixels_return(monkeypatch):
    # A fully masked band means the DEM returned nothing for this area.
    _install_dem(monkeypatch, elevation=None)
    result = ElevationMetric().compute(_make_context())''',
))

R.append((
    '''def test_elevation_insufficient_never_carries_a_value(monkeypatch):
    """The contradiction guard: insufficient must not ride under a value."""
    _east_facing_plane(monkeypatch)
    module = sys.modules["ee"]
    module.Image = lambda dataset_id: _FakeImage(None, {"elevation": None})
    result = ElevationMetric().compute(_make_context())''',
    '''def test_elevation_insufficient_never_carries_a_value(monkeypatch):
    """The contradiction guard: insufficient must not ride under a value."""
    _install_dem(monkeypatch, elevation=None)
    result = ElevationMetric().compute(_make_context())''',
))

R.append((
    '''def test_slope_computes_over_a_2024_request(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_slope_computes_over_a_2024_request(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_slope_provenance_carries_the_static_kind(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_slope_provenance_carries_the_static_kind(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_slope_insufficient_when_no_pixels(monkeypatch):
    _east_facing_plane(monkeypatch)
    module = sys.modules["ee"]
    module.Image = lambda dataset_id: _FakeImage(None, {"elevation": None})
    result = SlopeMetric().compute(_make_context())''',
    '''def test_slope_insufficient_when_no_pixels(monkeypatch):
    _install_dem(monkeypatch, elevation=None)
    result = SlopeMetric().compute(_make_context())''',
))

R.append((
    '''def test_aspect_of_an_east_facing_plane_is_ninety(monkeypatch):
    """Verified empirically against live Earth Engine: east = 90."""
    _east_facing_plane(monkeypatch)''',
    '''def test_aspect_of_an_east_facing_plane_is_ninety(monkeypatch):
    """Verified empirically against live Earth Engine: east = 90."""
    _install_dem(monkeypatch)''',
))

R.append((
    '''    The fake slope sits just above the threshold, so the mask keeps it.
    Asserting the mask exists in the formula string pins the order.
    """
    _east_facing_plane(monkeypatch)''',
    '''    The fake slope sits above the threshold, so the mask keeps it.
    Asserting the mask exists in the formula string pins the order.
    """
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_aspect_states_the_flat_exclusion_in_warnings(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_aspect_states_the_flat_exclusion_in_warnings(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_aspect_is_a_circular_mean_not_an_arithmetic_one(monkeypatch):
    """The formula must compute direction through sine and cosine."""
    _east_facing_plane(monkeypatch)''',
    '''def test_aspect_is_a_circular_mean_not_an_arithmetic_one(monkeypatch):
    """The formula must compute direction through sine and cosine."""
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_aspect_insufficient_when_no_direction_exists(monkeypatch):
    """All-flat terrain must refuse, not report 0 as due north."""
    _east_facing_plane(monkeypatch)
    module = sys.modules["ee"]
    module.Image = lambda dataset_id: _FakeImage(None, {"elevation": None})
    result = AspectMetric().compute(_make_context())''',
    '''def test_aspect_insufficient_when_no_direction_exists(monkeypatch):
    """All-flat terrain must refuse, not report 0 as due north."""
    _install_dem(monkeypatch, elevation=None)
    result = AspectMetric().compute(_make_context())''',
))

R.append((
    '''def test_aspect_provenance_names_the_slope_threshold(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_aspect_provenance_names_the_slope_threshold(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_ruggedness_computes_over_a_2024_request(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_ruggedness_computes_over_a_2024_request(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_ruggedness_insufficient_without_a_spread(monkeypatch):
    _east_facing_plane(monkeypatch)
    module = sys.modules["ee"]
    module.Image = lambda dataset_id: _FakeImage(None, {"elevation": None})
    result = TerrainRuggednessMetric().compute(_make_context())''',
    '''def test_ruggedness_insufficient_without_a_spread(monkeypatch):
    _install_dem(monkeypatch, elevation=None)
    result = TerrainRuggednessMetric().compute(_make_context())''',
))

R.append((
    '''def test_srtm_fallback_reports_its_source(monkeypatch):
    """A metric pointed at SRTM must record that NASADEM was preferred."""
    _east_facing_plane(monkeypatch, dataset_id=SRTM)''',
    '''def test_srtm_fallback_reports_its_source(monkeypatch):
    """A metric pointed at SRTM must record that NASADEM was preferred."""
    _install_dem(monkeypatch)''',
))

R.append((
    '''    assert provenance.source_dataset_id == SRTM
    assert provenance.fallback_from == NASADEM
    warnings = " ".join(result.warnings)
    assert "NASADEM" in warnings and "fallback" in warnings.lower()''',
    '''    assert provenance.source_dataset_id == SRTM
    assert provenance.fallback_from == NASADEM
    warnings = " ".join(result.warnings)
    assert "NASADEM" in warnings and "fallback" in warnings.lower()


def test_nasadem_voids_trigger_the_srtm_fallback(monkeypatch):
    """A fully masked NASADEM must retry with SRTM and say so."""
    # Only SRTM carries data; NASADEM is masked out entirely.
    module = types.ModuleType("ee")
    fake = FakeEE({
        NASADEM: _FakeImage(None, {"elevation": None}),
        SRTM: _FakeImage(None, {"elevation": float(RAW_ELEVATION)}),
    })
    module.Image = fake.Image
    module.Reducer = _FakeReducerNamespace()
    module.Terrain = _FakeTerrainNamespace()
    monkeypatch.setitem(sys.modules, "ee", module)

    result = ElevationMetric().compute(_make_context())
    assert result.status == STATUS_OK
    assert result.value == pytest.approx(float(RAW_ELEVATION))
    provenance = result.provenance
    assert provenance.source_dataset_id == SRTM
    assert provenance.fallback_from == NASADEM
    warnings = " ".join(result.warnings)
    assert "fallback" in warnings.lower()''',
))

R.append((
    '''def test_primary_path_reports_no_fallback(monkeypatch):
    _east_facing_plane(monkeypatch, dataset_id=NASADEM)''',
    '''def test_primary_path_reports_no_fallback(monkeypatch):
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_every_terrain_metric_provenance_distinguishes_static(monkeypatch):
    """Elevation and ruggedness are the two the fake can drive fully."""
    _east_facing_plane(monkeypatch)''',
    '''def test_every_terrain_metric_provenance_distinguishes_static(monkeypatch):
    """Elevation and ruggedness are the two the fake can drive fully."""
    _install_dem(monkeypatch)''',
))

R.append((
    '''def test_result_to_dict_serialises_the_temporal_kind(monkeypatch):
    _east_facing_plane(monkeypatch)''',
    '''def test_result_to_dict_serialises_the_temporal_kind(monkeypatch):
    _install_dem(monkeypatch)''',
))

for old, new in R:
    if old in text:
        text = text.replace(old, new, 1)
        print("OK  :", old.strip().splitlines()[0][:70])
    else:
        print("MISS:", old.strip().splitlines()[0][:70])

# Remove the now-unused _east_facing_plane helper.
text = re.sub(
    r"\n\ndef _east_facing_plane\(monkeypatch, dataset_id: str = NASADEM\) -> None:\n(?:    .*\n|\n)*?    \)\n",
    "\n",
    text,
    count=1,
)
assert "_east_facing_plane" not in text, "helper still referenced"

# Circular-mean expectation fixes.
old1 = '''def test_circular_mean_of_opposite_bearings_is_the_first_bearing():'''
new1 = '''def test_circular_mean_across_the_wrap_is_north():'''
assert old1 in text
text = text.replace(old1, new1, 1)

old2 = '''    mean = circular_mean_degrees(mean_sin, mean_cos)
    assert 340.0 <= mean <= 20.0'''
new2 = '''    mean = circular_mean_degrees(mean_sin, mean_cos)
    assert mean is not None
    assert mean <= 20.0 or mean >= 340.0'''
assert old2 in text
text = text.replace(old2, new2, 1)

p.write_text(text, encoding="utf-8")
print("written")
