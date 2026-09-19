---
name: agri-metric-unit-tests
description: >
  How to write offline unit tests for a metric in the Agricultural
  Intelligence Engine (backend/app/services/agriculture/) without Earth
  Engine credentials. Use this whenever you add or change a Metric
  subclass and need tests for its band wiring, scale factor, sign/unit
  convention, quality-flag decoding, or insufficient-data behaviour.
  Triggers on "test a metric", "add tests for <metric>", "unit test the
  water/soil/vegetation engine", or any work in
  backend/tests/unit/agriculture/.
agent_created: true
---

# Offline unit tests for agriculture metrics

The default test run must need **no network, no credentials and no
database**. The existing suite (`tests/unit/agriculture/`) achieves this
by injecting a *strict fake* `ee` module, so the real `compute()` path
runs. Copy `test_climate.py`, `test_water.py` or `test_soil.py` rather
than inventing a new harness.

## Run the tests

The project has its own venv. Use it, not the managed Python:

```bash
cd backend
./.venv/Scripts/python.exe -m pytest tests/unit/agriculture/test_<area>.py -q
```

Full suite:

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Integration tests are opt-in via `RUN_GEE_INTEGRATION_TESTS=1` and are
auto-skipped otherwise by `tests/conftest.py`.

## Rule 1 — patch the `ee` ATTRIBUTES, not just `sys.modules`

Every metric does a **function-local** `import ee` inside `compute()`.
Once the real `ee` package is imported anywhere in the process, that
statement binds the real module from `sys.modules`, so replacing
`sys.modules["ee"]` alone does nothing and the test tries to contact
Earth Engine.

Correct fixture:

```python
@pytest.fixture
def fake_ee(monkeypatch):
    def install(bands):
        fake = FakeEE(bands)
        for name in ("ImageCollection", "Reducer", "Filter"):
            monkeypatch.setattr(f"ee.{name}", getattr(fake, name))
        return fake
    return install
```

## Rule 2 — give every reduction a realistic `count`

`parse_reduction_result` reads `count` from the reduction dict, and
`assess_quality` compares it to `thresholds.min_valid_pixels` (MODIS 5,
Sentinel-2 20, reanalysis 1). A fake that returns `count == 1` makes
every MODIS metric report `insufficient_data` — for a reason that has
nothing to do with what the test is checking.

```python
PIXEL_TALLY = 5000  # in the returned reduction dict, not len(values)
```

Also supply all nine stat keys: `mean, median, min, max, stdDev, p10,
p25, p75, p90`.

## Rule 3 — make the fake strict

`select()` must **raise `KeyError`** when asked for a band the fixture
did not provide. A lenient fake returns a plausible number for the wrong
band, and a band mix-up — the most common real defect — passes silently.

```python
def select(self, bands):
    if bands and bands[0] != self._band:
        raise KeyError(f"holds {self._band!r}, not {bands!r}")
    return self
```

Assert the strictness explicitly, e.g. a PET metric against an ET-only
fixture must raise.

## Rule 4 — model what the fake must support per pipeline shape

Different pipelines call different methods. Check which before writing:

| Pipeline | Methods used |
|---|---|
| Spectral index | `ImageCollection.filterDate/filterBounds/filter`, `map`, `median`, `select`, `updateMask`, `normalizedDifference`, `expression` |
| Single-band product | `ImageCollection.select(band)`, `size`, `mean`/`median`, `map` |
| Multi-band masked (**SMAP**) | `size` **before** `select`, then `map` over multi-band images, `select` inside the map, `bitwiseAnd`, `neq`, `Not`, `updateMask`, `rename`, `median` |

For SMAP the fake needs a `_FakeMultiBandImage` that selects either the
soil band or the flag band, plus `_FakeMapped.median()` that composites
after masking. If a fixture supplies a soil band but no flag, auto-add a
permissive all-zero flag — the real product always ships both.

## Rule 5 — test the convention, not just the number

The valuable tests assert the *scientific decision*, because a wrong one
still yields a believable number:

- **Scale factor**: assert the value **and** that a plausible wrong
  factor was *not* applied (`result.value != pytest.approx(0.03)`).
- **Sign**: ERA5 `total_evaporation_sum` is negated, never `abs()`-ed
  and never clamped. Assert a stored `+0.005` returns a **strictly
  negative** result.
- **Mask is load-bearing**: for SMAP, feed one good day (0.30) and two
  skipped days holding a 0.02 fill value. Correct output is 0.30; an
  unmasked implementation returns 0.02.
- **Never averaged**: AM/PM overpasses are separate metrics — assert the
  two compute different values from unequal inputs, and that a good
  morning flag does not rescue a skipped evening flag.
- **Missing ≠ zero**: an empty collection must give
  `STATUS_INSUFFICIENT_DATA` with `value is None`, and the message must
  say why. A genuine `0.0` is real data and must pass through.
- **Unavailable**: `cwsi`/`wdi` must return `STATUS_UNAVAILABLE` with
  `value is None` and a reason > 100 chars, even with every dataset
  faked — they are structurally incapable of a value.

## Rule 6 — assert the registry is the single source of truth

Do not hardcode 0.1 or 500 m in the expected value. Read the band spec:

```python
spec = get_dataset(DATASET_ID).band("ET")
assert spec.scale_factor == pytest.approx(0.1)
assert spec.to_physical(32767) is None   # fill sentinel still rejected
```

`BandSpec.to_physical` rejects `None`, `bool`, non-numeric, non-finite
and declared `nodata_values`, but it does **not** enforce `valid_range`.

## Checklist for a new metric's test file

1. Every key present; no duplicates; correct `domain`; a unit declared.
2. Every metric declares `limitations`.
3. Band names match the pure formula (`indices.BAND_ROLES`) exactly.
4. Working scale matches band resolution (B11 → 20 m, SMAP L3 → 9000 m).
5. The unit / scale-factor conversion is applied once, correctly.
6. The sign or masking convention is asserted directly.
7. Empty input → `insufficient`; never `0`.
8. Provenance carries dataset, bands, formula, and the caveat.
9. No metric claims to diagnose disease, pests or nutrient deficiency.
10. `metric.metadata()` serialises and reports `available` correctly.
