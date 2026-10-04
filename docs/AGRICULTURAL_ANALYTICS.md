# Agricultural Intelligence Engine

## Status

| Phase | Scope | State |
|---|---|---|
| A | Foundation: registry, types, quality | ✅ Complete |
| B | Core engine primitives | ✅ Complete |
| C | Vegetation engine | ✅ Complete |
| D | Climate and meteorology engine | ✅ Complete |
| E | Thermal engine | ✅ Complete |
| F | Water and soil moisture engine | ✅ Complete (deferred GLDAS item closed) |
| G | Land cover engine | ✅ Complete |
| H | Terrain engine | ✅ Complete |
| I | Crop type, land cover, crop area & phenology foundation | ✅ Complete |
| J | Soil properties engine | Pending |
| K | Quality, fallback, provenance layer | Pending |
| L | Unified API v1 | Pending |

Test suite: **1320 passing**, 63 integration tests collected, skipped by
default. No network, no credentials and no database are required for the
default run. The `agri_intelligence` database is untouched by the test
suite.

Frontend work is deferred pending review of the backend. See
[Land cover](#phase-g-land-cover-engine) for one known frontend defect.

---

## Design principles

These are enforced in code, not left to discipline.

1. **A number is never published without provenance.** `MetricResult`
   raises at construction time if a value arrives without a source
   record.
2. **Missing data is never reported as zero.** A field we could not
   observe is `insufficient_data`, which is categorically different from
   a field measured at zero.
3. **Proxies are named as proxies.** `CWSI_proxy` can never appear as
   `CWSI`.
4. **Reanalysis is never presented as measurement.** `MeasurementBasis`
   distinguishes direct measurement, agency product, derived value,
   modelled value, proxy, and inference. Modelled, proxy and inference
   all require an explicit disclaimer.
5. **Unverified parameters are marked, not guessed.** A parameter that
   could not be confirmed against an official source carries the
   `PENDING_VERIFICATION` sentinel and forces a dataset to report itself
   as unverified.
6. **No disease, pest or nutrient diagnosis.** Satellite data supports
   statements about vegetation stress, water stress and anomalies. It
   does not support a diagnosis, and the engine will not make one.

---

## Package layout

```
app/services/agriculture/
├── __init__.py          public exports
├── types.py             BandSpec, DatasetSpec, SpatialStats, ClassHistogram,
│                        Provenance, MetricResult, enums
├── quality.py           pure quality policy, no network
├── base.py              Metric contract + MetricContext (cache keys,
│                        coverage-window capability checks)
├── aggregation.py       reducer construction, reduction parsing,
│                        coverage arithmetic, stats merging
├── indices.py           pure index formulas (no Earth Engine)
├── units.py             unit conversions and meteorological formulas
├── catalog.py           metric registry + public catalog payload
├── executor.py          concurrent execution, per-metric error isolation
├── vegetation.py        vegetation metrics, Earth Engine expressions
├── climate.py           climate metrics, ERA5-Land driven
├── thermal.py           land surface temperature, MODIS and Landsat
├── water.py             water indices, evapotranspiration, ERA5
│                        evaporation, the CWSI/WDI omissions
├── soil.py              soil moisture: SMAP L3 retrieval, SMAP L4 and
│                        ERA5-Land root zone, the GLDAS-2.1 root zone
│                        mass per unit area
├── landcover.py         MCD12Q1 categorical metrics + Dynamic World
│                        probability metric (Phase I)
├── crop.py              WorldCereal crop context and crop area,
│                        the planting/harvest/flowering refusals (Phase I)
├── phenology.py         vegetation season onset/peak/end/length/amplitude
│                        on a monthly Sentinel-2 NDVI series, and the
│                        declined seasonal integral (Phase I)
└── registry/
    ├── datasets.py      Earth Engine datasets (19 registered)
    └── external.py      non-GEE sources (ISRIC SoilGrids)
```

## Vegetation metrics

Eight metrics, each an independent provider:

| Key | Bands | Working scale | Basis | Source |
|---|---|---|---|---|
| `ndvi` | B4, B8 | 10 m | derived | Sentinel-2 |
| `evi` | B2, B4, B8 | 10 m | derived | Sentinel-2 |
| `savi` | B4, B8 | 10 m | derived | Sentinel-2 |
| `msavi` | B4, B8 | 10 m | derived | Sentinel-2 |
| `ndre` | B5, B8 | **20 m** | derived | Sentinel-2 |
| `lai` | Lai | 500 m | product | MODIS MCD15A3H |
| `fapar` | Fpar | 500 m | product | MODIS MCD15A3H |
| `fcover` | Fcov | 500 m | product | MODIS MCD15A3H |

The working scale is fixed by the bands being read, not by a caller
preference. `NDRE` reads the 20 m red edge band and therefore reduces at
20 m; allowing a default of 10 m would resample the band and then report
10 m resolution in the provenance, which would be false.

Each index formula is written once as a pure function in `indices.py`
and once as an Earth Engine expression in `vegetation.py`. The pure
version is what the tests pin.

### Composition

Sentinel-2 metrics share one composition step: filter by date, bounds and
cloud cover, apply the SCL mask, convert to reflectance, then take a
median composite. A median is used rather than a mean because one
undetected thin-cloud pixel distorts a mean far more than a median.

SCL classes 0, 1, 3, 8, 9 and 10 are masked. Class 7, cloud with low
probability, is deliberately retained: masking it discards a large amount
of usable data, and it is the quality assessment rather than a blanket
mask that should decide trust.

### Non-diagnostic guarantee

No vegetation metric may claim to identify a cause. Vegetation indices
support statements about greenness, stress and anomalies. They do not
distinguish drought from waterlogging, nutrient shortage from disease,
pest damage from a management effect, and the engine will not pretend
otherwise.

This is enforced two ways: every metric declares an explicit limitation
stating what it cannot determine, and a test scans each metric's
description and limitations for diagnostic vocabulary. A metric may name
a condition it is unable to diagnose, but the sentence must carry a
negation, so "does not distinguish disease" passes while "detects
disease" fails.

## Metric contract

Every metric is a `Metric` subclass declaring its key, bilingual display
name, domain, unit, dataset dependencies (primary first, then fallbacks),
and measurement basis. It implements one method, `compute(context)`,
which returns a `MetricResult`.

The context carries the geometry, date range, serialised geometry key,
scene filters, and dataset versions. It produces deterministic cache keys
by hashing all of those, so a dataset revision automatically invalidates
cached results.

Metrics also answer `can_attempt(context)` before computing, which
compares the requested period against the primary dataset's declared
coverage window. A request for 2010 against Sentinel-2 returns
`unavailable` with reason `outside_temporal_coverage` instead of running
an expensive query that can never return data.

### Temporal semantics: OBSERVATION vs STATIC

The registry stores two dates for every dataset, but those dates do not
mean the same thing for every product. `DatasetSpec.temporal_kind`
makes the meaning explicit:

* `OBSERVATION` (the default) — the dates bound **when observations
  exist**. A request outside them cannot be answered and is rejected as
  `outside_temporal_coverage`. This is the meaning for every time
  series: Sentinel-2, ERA5-Land, MODIS, SMAP.
* `STATIC` — the dates record **when the product was made** (an
  acquisition window or a model reference period). The product is not a
  time series and that date does not restrict which analysis dates it
  can inform, so `can_attempt` does not use the window to reject the
  request. A 2024 terrain analysis against a DEM acquired in February
  2000 is a valid request, not an out-of-coverage one.

Why the acquisition date is not a validity period: a static surface is
a description of the ground as it was when it was surveyed. It remains
the best available answer for questions about any later date, and the
alternative — refusing every realistic request — would make the dataset
useless. What static classification does **not** do is remove request
validation: malformed or inverted date ranges are still rejected, and
all other capability checks still apply.

Provenance keeps the two dates separate for a static product:
`requested_start`/`requested_end` carry the period the caller asked
about, `product_date` carries when the source product was actually made,
and `temporal_kind` states which semantics apply. A result computed from
a year-2000 elevation model for a 2024 request therefore never reads as
though the DEM had been observed in 2024.

The classification lives in the registry, per dataset, and is validated
two ways in `DatasetSpec.__post_init__`: a dataset declared STATIC must
describe itself as static in `temporal_resolution`, and one declared
OBSERVATION must not. A registration can never disagree with the
semantics the engine will actually apply.

## Error isolation

`execute_metrics` runs metrics concurrently in a bounded thread pool
(default 4 workers, because Earth Engine enforces per-user quotas) and
guarantees that a failure in one metric cannot affect any other. An
exception becomes an `error` result with a sanitised message; the
remaining metrics return normally.

Error messages are filtered before reaching a client, because the Earth
Engine client embeds filesystem paths, service account addresses and
credential material in its error strings. Paths, email addresses and PEM
blocks are replaced with a redacted marker, and long messages are
truncated. The full detail is written to the server log.

---

## Corrections made during dataset verification

An initial audit produced a proposed dataset table. Systematic
verification against the Earth Engine Data Catalog and agency
documentation found six errors in it. All six are corrected in the
registry, and each is covered by a regression test.

| # | Initially stated | Verified reality |
|---|---|---|
| 1 | MOD16 ET bands `PF_ET`, `PF_PET` | These bands do not exist. Real bands are `ET`, `PET`, `LE`, `PLE` |
| 2 | `MOD16A2GF` ends around 2023 | It runs 2000 to present and is the recommended historical product. Plain `MOD16A2` starts only in 2021 |
| 3 | `NASA/SMAP/SPL4SMGP/007` | Deprecated. The registry uses `/008` |
| 4 | `NASA/SMAP/SPL2SMAP_S/001` | Does not resolve in the catalog. Removed entirely |
| 5 | `ESA/WorldCereal/2021/MODELS/...` | Incomplete. Correct ID is `ESA/WorldCereal/2021/MODELS/v100` |
| 6 | ERA5 evaporation sign convention | `total_evaporation_sum` negative-for-upward is verified. `potential_evaporation_sum` follows the same convention but is inferred, not documented, and is flagged as such |

Two further defects were found and fixed while building this phase:

* Sentinel-2 reflectance bands were declared with a nodata sentinel of
  `0.0`. This is wrong: Sentinel-2 L2A uses `SCL == 0` as its no-data
  marker, while a raw reflectance of zero is a legitimate dark pixel.
  The sentinel would have silently deleted every dark pixel from every
  vegetation index. All 16 reflectance bands were corrected.
* `MetricResult` guarded against a value carrying `UNAVAILABLE` quality
  but not `INSUFFICIENT`. Both levels mean "no value exists", so both
  are now rejected.

Defects found and fixed while building Phase B:

* `SpatialStats` could be constructed in a self-contradictory state, for
  example valid 50 of a total 100 but missing 0, because the missing
  fields were only populated by the reduction parser. Coverage fields are
  now derived on construction, so an inconsistent instance cannot exist.
  A total smaller than the valid count is also corrected upward.
* The executor logged with keyword arguments, for example
  `logger.info("msg", metric=key)`, following structlog convention. The
  project's `get_logger` returns a standard library logger, whose
  `_log` rejects unexpected keyword arguments. This raised `TypeError`
  at runtime, but only on paths where a record was actually emitted,
  which made it easy to miss during development and fatal in production.
  All call sites now use positional `%s` formatting, and two tests guard
  against recurrence.

Defects found and fixed while building Phase C:

* `NDRE` declared a 20 m working scale in an attribute that nothing read,
  so `effective_scale` returned the 10 m default. Earth Engine would have
  resampled the red edge band to 10 m and the provenance would have
  reported 10 m resolution. `_SpectralIndexMetric` now overrides
  `effective_scale` to use the band scale, so a caller-supplied scale
  cannot override the resolution that the bands actually support.
* Vegetation metrics stated their index behaviour as limitations but did
  not state what they cannot determine. Every spectral index now carries
  an explicit non-diagnostic limitation.

Two test expectations were also corrected after checking the arithmetic:
SAVI at L=0.5 sits *below* NDVI for the same reflectances, since the
soil-adjustment term attenuates rather than amplifies; and the MSAVI
radicand is provably non-negative across the entire physical reflectance
domain, so the guard there is defensive and only reachable with
non-physical input.

---

## Phase D: Climate and meteorology engine

Ten metrics, all driven by ERA5-Land daily aggregated reanalysis
(`ECMWF/ERA5_LAND/DAILY_AGGR`). Every one is `MODELLED`, `DERIVED` or
`PROXY` — nothing read from a reanalysis is presented as a measurement.

| Metric | Unit | Basis | Source band |
|---|---|---|---|
| `precipitation` | mm | modelled | `total_precipitation_sum` |
| `temperature_max` | degC | modelled | `temperature_2m_max` |
| `temperature_min` | degC | modelled | `temperature_2m_min` |
| `temperature_mean` | degC | modelled | `temperature_2m` |
| `solar_radiation` | MJ/m2 | modelled | `surface_solar_radiation_downwards_sum` |
| `vpd` | kPa | derived | `temperature_2m` + `dewpoint_temperature_2m` |
| `relative_humidity` | percent | derived | `temperature_2m` + `dewpoint_temperature_2m` |
| `wind_speed` | m/s | derived | `u_component_of_wind_10m` + `v_component_of_wind_10m` |
| `gdd` | degC-day | derived | `temperature_2m_min` + `temperature_2m_max` |
| `par` | MJ/m2 | **proxy** | `surface_solar_radiation_downwards_sum` |

### Unit conventions established and verified

ERA5 stores each quantity in a unit that is wrong for agronomic
reporting, and each of these is a silent error if forgotten:

| Quantity | ERA5 unit | Reported unit | Conversion |
|---|---|---|---|
| Temperature | K | °C | `− 273.15` (offset, not a factor) |
| Water flux | m | mm | `× 1000` |
| Radiation | J/m² | MJ/m² | `÷ 1e6` |
| Wind | m/s per component | m/s | `√(u² + v²)` |

The Magnus saturation vapour pressure form was checked against published
values and agrees to within 0.11 percent:

| Temperature | Computed | Reference |
|---|---|---|
| 0 °C | 0.6108 kPa | 0.611 kPa |
| 20 °C | 2.3383 kPa | 2.339 kPa |
| 40 °C | 7.3756 kPa | 7.384 kPa |

### The ERA5 sign convention

The ECMWF convention treats downward fluxes as positive, so
`total_evaporation_sum` is stored as a **negative** number. Presenting it
directly would report negative evaporation, which is physically
meaningless. The water-balance module (Phase F) must negate it.

This is verified for `total_evaporation_sum`. The sign of
`potential_evaporation_sum` is *inferred* by analogy, not documented, and
is flagged as such in the registry rather than assumed.

### Per-day pairing

Four of these metrics are derived from **two** bands. For all four, the
two series are combined **per day** and only then averaged or summed:

* `vpd` — temperature and dewpoint must come from the same day.
* `relative_humidity` — same pairing.
* `wind_speed` — the two components must come from the same day.
* `gdd` — the day's minimum and maximum must come from the same day.

Averaging each series independently first and combining the averages
produces a value describing no actual day. For VPD the error is
substantial: a hot dry day and a mild humid day average out to a small
deficit that neither day actually had. Tests feed deliberately
mismatched series and assert the per-day result; an injected unpaired
implementation was confirmed to fail them.

### Qualities and disclosures enforced

* `par` is a fixed-coefficient estimate (45 percent of shortwave) and is
  therefore `PROXY`, named with a proxy suffix, capped at `MODERATE`
  quality regardless of coverage, and always carries a warning.
* `relative_humidity` carries an explicit note that humidity rises as air
  cools, making it a poor measure of atmospheric demand compared with VPD.
* `hdd` is not offered: no heating-degree-day metric is implemented,
  because no consumer has asked for one and the base temperature would
  have to be invented.
* Every metric states the 11 km reanalysis resolution and that the value
  describes a region, not a field.
* `gdd` reports the base temperature actually used, and the upper cap
  when one is supplied, in its provenance limitations.

### Defects found and fixed while building Phase D

* `_reduce_era5_band` initially reduced the period-mean image and read the
  per-day values from a separate computation, so the two could disagree
  about which days were used. Both now derive from one collection.
* The per-day read used `map(...).getInfo()` on what is really an
  `ImageCollection`. The real client returns per-feature properties, so
  the flattened list would have been empty. Rewritten to the documented
  idiom: attach the value as a property with `image.set(...)` and read it
  back with `aggregateArray(property).getInfo()`. The test fake raises on
  the wrong call rather than silently returning nothing.
* `WindSpeedMetric` originally reduced the eastward component alone and
  documented that as a limitation. A single component is not a speed:
  a 10 m/s wind from the north would have reported 0. Rewritten to
  combine both components per day.
* `_ERA5Metric` applied unit conversion to `std_dev`, which is wrong:
  standard deviation is a spread measure and does not take an offset.
  It is now dropped whenever the conversion is not the identity, rather
  than reported as a meaningless converted number.
* Wind direction is deliberately not reported. It would require a
  meteorological convention choice (from-direction versus to-direction)
  to be stated explicitly, and reporting one silently would be a
  fifty-fifty chance of being backwards.

---

## Phase E: Thermal engine

Five metrics from MODIS LST, plus a Landsat 8 surface temperature metric
for sub-field detail.

| Metric | Unit | Basis | Source |
|---|---|---|---|
| `land_surface_temperature_day` | degC | product | `MOD11A2.LST_Day_1km` |
| `land_surface_temperature_night` | degC | product | `MOD11A2.LST_Night_1km` |
| `land_surface_temperature_mean` | degC | product | `MOD11A2.LST_Day_1km` |
| `surface_temperature_range` | K | derived | `MOD11A2.LST_Day_1km` minus `LST_Night_1km` |
| `landsat_surface_temperature` | degC | product | `LC08/C02/T1_L2.ST_B10` |

### The canopy temperature prohibition

**Land surface temperature is not canopy temperature, and this engine
will never publish a `canopy_temperature` metric.**

The radiometric skin temperature a satellite measures is an area-weighted
mixture of sunlit leaves, shaded leaves, soil and the spaces between
rows. Canopy temperature — the temperature of the plant tissue, which is
the quantity that relates to transpiration and water stress — requires a
close-range thermal camera or a surface-energy-balance inversion. It is
not obtainable from a 1 km satellite pixel over a partly vegetated field.

Presenting the first as the second would give a number that looks
scientifically grounded and is wrong by several degrees, in a direction
that depends on crop, row geometry and time of day. The prohibition is
enforced at two levels:

1. **Each metric states it.** The disclaimer is part of every thermal
   metric's class-level `limitations`, which `build_provenance` copies
   into every provenance record, so it reaches the catalog, the API
   response and the result object without being restated at any of them.
2. **A source scan asserts it.** `test_the_engine_never_declares_a_canopy_temperature_key`
   walks every `*.py` file in the package looking for a `key = "...canopy..."`
   assignment, so a later domain module cannot introduce the key by
   accident.

### The scale factor defect

This phase exposed the most consequential defect found so far.
`parse_reduction_result` returned **raw stored values** and never applied
the band's `scale_factor` or `offset`. The registry had declared
`LST_Day_1km` with `scale_factor = 0.02` since Phase A, but nothing read
it on the reduction path.

The failure mode was subtle rather than obvious. A MODIS LST reduction
returns counts around 15000; the temperature is 15000 × 0.02 = 300 K.
Nothing crashed. The number was merely wrong by a factor of fifty, in a
unit where 350 K is a plausible summertime surface temperature — so a
raw count of 300 would have read as a cold winter night, and a raw count
of 15000 would have been rejected as obvious nonsense. Only one of those
two errors is self-announcing.

Fixed at the boundary, not at each call site:

* `parse_reduction_result` takes an optional `band_spec`. When supplied,
  every statistic is converted through `BandSpec.to_physical`, raw nodata
  sentinels are dropped, and the spread is converted only when the
  conversion has no offset (a standard deviation does not take one).
* `climate.py` and `thermal.py` now pass the spec. The vegetation
  module deliberately does not: it applies the reflectance scale factor
  inside the image expression before computing the index, so the
  reduction already returns a dimensionless value in [−1, 1]. Passing a
  spec there would apply the factor a second time.
* The integration suite asserts that Earth Engine really does return raw
  counts for `LST_Day_1km`, so a future change to the dataset cannot
  silently double-apply the conversion.

Seven regression tests cover the conversion directly, including the
no-offset spread case, the offset spread case, the nodata sentinel and
the boolean guard.

### MODIS quality control

The `QC_Day` and `QC_Night` bands are decoded rather than ignored. The
documented eight-bit layout is:

| Bits | Meaning |
|---|---|
| 0-1 | Mandatory QA: 0 produced/good, 1 produced/unreliable, 2 cloud, 3 other |
| 2-3 | Data quality: 0 good, 1 other |
| 4-5 | Emissivity error: ≤0.01, ≤0.02, ≤0.04, >0.04 |
| 6-7 | LST error: ≤1 K, ≤2 K, ≤3 K, >3 K |

The two flags are decoded independently because they genuinely disagree:
a pixel can be flagged "produced, good quality" (bits 0-1 and 2-3 both
zero) while carrying a 2 K error in bits 6-7. Trusting the mandatory flag
alone would accept it. `ModisLstQuality.is_reliable` therefore requires
`lst_error_kelvin <= 1.0`, which is the documented meaning of bits 6-7
being zero rather than an arbitrary threshold.

### Other decisions

* **8-day composite is the primary source.** `MOD11A2` composites eight
  days, so coverage under persistent cloud is far better than the daily
  `MOD11A1`, which is declared as the fallback.
* **Day-night range is in Kelvin.** A temperature difference has no
  meaningful Celsius reading when it is zero, and labelling "30 degC" for
  an interval invites reading it as an absolute temperature.
* **`surface_temperature_range` subtracts the means**, not the per-pixel
  differences. That is cheaper and exact only when the valid pixel sets
  coincide, which they usually do not; the provenance says so.
* **Landsat reduces at 100 m, not 30 m.** The thermal band is acquired at
  100 m and delivered resampled to 30 m. `default_scale` wins over any
  caller-supplied scale, so the provenance cannot overstate the detail.
* **A single Landsat scene is capped at `moderate`.** One scene cannot
  support a confident multi-date claim, even if it covers the whole field.
* **`LANDSAT_THRESHOLDS` is a new preset.** The MODIS floor of five valid
  pixels would call a smallholder field at 100 m insufficient, which is
  wrong: a few hectares legitimately contains only a handful of pixels.

A useful side effect of the `MetricResult` guard: this phase's Landsat
metric initially computed a value while its quality assessment returned
`insufficient`, and construction raised rather than publishing the
contradiction. The guard caught it before any test did.

### Registration

`app/services/agriculture/__init__.py` exposes `register_all_metrics()`,
which populates the catalog from every domain module. It is idempotent,
returns the sorted key list, and is **not** an import side effect — so a
test or a build step can start from an empty registry.

---

## Phase F: Water and soil moisture engine

Two modules, fourteen metrics, and a deliberate refusal to produce two
more.

### Water metrics

| Key | Bands | Scale | Unit | Basis | Source |
|---|---|---|---|---|---|
| `ndwi` | B3, B8 | 10 m | index | derived | Sentinel-2 |
| `ndmi` | B8, B11 | **20 m** | index | derived | Sentinel-2 |
| `mndwi` | B3, B11 | **20 m** | index | derived | Sentinel-2 |
| `evapotranspiration` | ET | 500 m | mm/period | product | MOD16A2GF |
| `potential_evapotranspiration` | PET | 500 m | mm/period | product | MOD16A2GF |
| `evapotranspiration_cumulative` | ET | 500 m | mm | product | MOD16A2GF |
| `era5_evaporation` | total_evaporation_sum | 11132 m | mm | modelled | ERA5-Land |
| `era5_potential_evaporation` | potential_evaporation_sum | 11132 m | — | modelled | ERA5-Land |

### Soil moisture metrics

| Key | Bands | Scale | Unit | Basis | Source |
|---|---|---|---|---|---|
| `soil_moisture_surface` | soil_moisture_am, retrieval_qual_flag_am | 9000 m | m3/m3 | product | SMAP L3 |
| `soil_moisture_surface_evening` | soil_moisture_pm, retrieval_qual_flag_pm | 9000 m | m3/m3 | product | SMAP L3 |
| `soil_moisture_rootzone` | sm_rootzone | 11000 m | m3/m3 | modelled | SMAP L4 |
| `soil_moisture_rootzone_era5` | volumetric_soil_water_layer_1..3 | 11132 m | m3/m3 | modelled | ERA5-Land |
| `soil_moisture_wetness` | sm_rootzone_wetness | 11000 m | **fraction** | modelled | SMAP L4 |
| `root_zone_soil_moisture_gldas` | RootMoist_inst | 27830 m | **kg/m2** | modelled | GLDAS-2.1 |

### A mass per unit area is published as a mass per unit area

`root_zone_soil_moisture_gldas` reports GLDAS-2.1's `RootMoist_inst` band
in **kg/m2**, the unit the product itself publishes, and it is the one
soil moisture figure in this engine that is not a volume fraction.

This was the last item deliberately deferred from this phase's original
audit. The two defensible ways of handling a mass-per-unit-area product
are to convert it to `m3/m3`, which requires the thickness of the root
zone layer and the density of water, or to publish it under its own unit
and never merge it with the volume-fraction metrics. The first option was
evaluated and rejected: the catalogue documents the profile layers
individually (0-10, 10-40, 40-100, 100-200 cm) but does not document the
depth interval that `RootMoist_inst` covers, so the divisor would be an
assumption wearing the costume of a conversion. A conversion made from an
unpublished thickness is exactly the kind of plausible-looking number
this engine exists to avoid.

The second option is therefore used, and it is enforced:

* the metric's unit, its provenance and its warnings all state `kg/m2`;
* the module's cross-quantity-family guard admits `kg/m2` for **this one
  metric only** and pins the count, so a second mass metric cannot
  appear quietly;
* depth units (`mm`, `cm`, `m`) remain forbidden for every soil metric,
  so nothing here can silently adopt TerraClimate's convention;
* a test feeds a 200 kg/m2 root zone through the metric and asserts the
  result is 200.0 and **not** 0.2 — the value a one-metre conversion
  would have produced.

The dataset registration states the same facts as caveats: GLDAS-2.1 is
**open-loop** (it assimilates no soil moisture observations at all), the
catalogue's range for the band is flagged *estimated* so it is not used
  as a validity filter, and the value is not comparable with the SMAP or
ERA5-Land volume fractions without an explicit, stated conversion.

### Water indices: three names, three different questions

NDWI, NDMI and MNDWI are all "a water index" and all start with `ND`.
They are not interchangeable:

* **NDWI** (McFeeters) is a green/NIR contrast, `(B3 - B8) / (B3 + B8)`.
  It responds to open water and to surface moisture. It is *not* an
  indicator of crop water status.
* **NDMI** (Gao) is an NIR/SWIR1 contrast, `(B8 - B11) / (B8 + B11)`. It
  responds to canopy water content. It is *not* a soil moisture
  measurement.
* **MNDWI** (Xu) is a green/SWIR1 contrast, `(B3 - B11) / (B3 + B11)`,
  which suppresses built-up surfaces and is the better open-water index
  over mixed land cover.

The formula for each lives once, as a pure function in `indices.py`. The
wrapper in `water.py` only wires it to Earth Engine, so the two cannot
drift apart. A test asserts that each metric's `required_bands` equals
`indices.BAND_ROLES`, and that the band order matches the sign of the
published formula.

The SWIR indices reduce at 20 m because B11 is acquired at 20 m.
Reducing at 10 m would resample the band and then report 10 m resolution
in the provenance, which would be false.

### MOD16 evapotranspiration

Three metrics read MOD16: `ET`, `PET`, and a cumulative total.

* **The values are 8-day sums, not daily rates.** The registry band unit
  is `kg/m2/8day` and the scale factor is 0.1, so a stored 300 is 30 mm
  over the composite period. The unit is reported as `mm/period` rather
  than `mm/day` for exactly this reason. Forget the 0.1 and the crop
  appears to use ten times the water it uses; report an 8-day sum as a
  daily rate and the same error appears by a factor of eight.
* **Per-composite period lengths are read from the image, not assumed.**
  The final composite of each year spans five or six days rather than
  eight. The metric attaches a `period_days` property to each composite
  and reads it back with `aggregate_array`, so a rate derived from a sum
  is never divided by a nominal eight.
* **The cumulative metric sums the per-composite spatial means**, and
  the provenance states that each composite contributes exactly once, so
  a boundary-straddling composite cannot be double counted.
* **`MOD16A2GF` is primary and `MOD16A2` is the fallback.** The
  gap-filled product is preferred; the near-real-time product was used
  only when explicitly requested, and its provenance records
  `fallback_from`.
* **The fill values cannot enter as data.** The catalogue records that
  MOD16's 32761-32767 fill sentinels are removed from the Earth Engine
  assets entirely. The band spec rejects them anyway, so a value that
  slipped through would still not be published as a measurement.

MOD16 `PET` is **not** reference evapotranspiration `ET0`. It is derived
from a Penman-Monteith formulation with the product's own assumptions,
and it must not be substituted for `ET0`. TerraClimate's `pet` is a
*different* quantity again, computed by ASCE Penman-Monteith. The
limitations of each say so.

### The ERA5 sign convention

This is the single most error-prone conversion in the module, because
both a wrong sign and an `abs()` produce a number of the right magnitude.

ERA5-Land stores `total_evaporation_sum` as **negative when water is
leaving the surface**. The catalogue states this directly: "negative
values indicate evaporation and positive values indicate condensation".
The value is in metres of water equivalent.

The conversion is therefore a **negation**, and nothing else:

```
evaporation_mm = -stored_value * 1000
```

* **`abs()` is forbidden.** A stored `+0.001` m is 1 mm of condensation —
  dew forming. `abs()` would report it as 1 mm of evaporation, which is
  the opposite of what happened. The metric counts condensation days and
  reports them in a warning.
* **Clamping to zero is forbidden.** Clamping a negative stored value to
  zero deletes every evaporation event.
* **Every statistic is flipped, not just the mean.** Negating a
  distribution maps its minimum onto the negative of its maximum, and
  p10 onto the negative of p90. The metric mirrors `min`/`max`,
  `p10`/`p90` and `p25`/`p75` rather than reusing the stored percentiles.
* **The component bands are never read.** ERA5-Land's three component
  evaporation bands (`..._evaporation_from_bare_soil`, `..._from_open_
  water`, `..._from_vegetation_transpiration`) carry swapped values in
  the Earth Engine asset. Their sum disagrees with the total, which
  moves between revisions, so the total is the only defensible input.
  This is recorded as a limitation.

`era5_potential_evaporation` reads `potential_evaporation_sum`, whose
**sign convention is not documented** in the catalogue or in the ECMWF
parameter database. The band is present and a caller will ask for it, so
the metric is registered — but it always returns `unavailable` with the
reason recorded rather than assuming a sign. `potential_evaporation_sum`
in this asset also appears to be in metres while the ECMWF parameter
database documents it in metres of water equivalent per day, which is a
second unresolved ambiguity. MOD16 `PET` is the supported alternative.

### Soil moisture: five incompatible quantities

The governing rule of `soil.py` is that these are **not**
interchangeable, and the module never converts between them:

| Quantity | Unit | What it is |
|---|---|---|
| SMAP L3 soil moisture | m3/m3 | Radiometer retrieval, top 0-5 cm |
| SMAP L4 soil moisture | m3/m3 | Assimilated land model, 0-100 cm |
| ERA5 soil water | m3/m3 | Reanalysis land model |
| GLDAS soil moisture | kg/m2 | Water mass per unit area |
| TerraClimate soil | mm | Depth-integrated water |
| SoilGrids retention | cm3/cm3 | Static soil property |

`m3/m3` is a volume fraction, independent of layer thickness. `kg/m2` is
a mass per unit area, so converting it to a volume fraction needs the
layer depth and the water density. `mm` is a depth of water. Dividing
one by the other without stating the thickness produces a number with no
physical meaning, so this module never does it, and every soil metric
here reports `m3/m3`.

**The SMAP L3 collection split.** The product spans two Earth Engine
collections: `/006` covers 2023-12-04 onward and `/005` covers 2015-03-31
to 2023-12-03. Requesting `/006` for an earlier date returns an *empty*
collection rather than an error, which is indistinguishable from a
cloud-cover problem. The collection is therefore selected from the
requested start date.

**Morning and evening are separate metrics.** Surface soil moisture has
a strong diurnal cycle, so the descending ~06:00 and ascending ~18:00
overpasses are published as `soil_moisture_surface` and
`soil_moisture_surface_evening`. Averaging them would produce a value
describing no actual time of day. The corresponding quality flags are
never interchanged: a test asserts that a good morning flag does not
rescue a skipped evening flag.

**The retrieval quality flag is not a good/bad integer.** Verified
against the NSIDC help centre:

| Bit 0 | Bit 1 | Meaning |
|---|---|---|
| 0 | 0 | Recommended quality |
| 1 | 0 | Uncertain quality — still a real retrieval |
| x | 1 | The retrieval was **SKIPPED** — not a retrieval at all |

So flag value 2 means "no retrieval", not "worse than 1". Reading the
flag as "0 is fine, anything else is worse" would treat a pixel that was
never retrieved — and which therefore holds a fill value — as an
uncertain but real observation. The mask removes any pixel where bit 1
is set; uncertain retrievals (flag 1) are kept, because they are real
observations and the quality assessment handles their trustworthiness.

**The L3 retrieval and the L4 root zone are different quantities.** L3
covers the top 0-5 cm from a radiometer retrieval. L4 covers 0-100 cm
from a model that assimilates SMAP brightness temperatures. Their
limitations state that they are not comparable and are not expected to
agree.

**The ERA5 root zone is a thickness-weighted mean across three layers.**
Layers 1, 2 and 3 span 0-7, 7-28 and 28-100 cm, so the weights are 7, 21
and 72 centimetres:

```
root_zone = (7 * layer_1 + 21 * layer_2 + 72 * layer_3) / 100
```

A flat mean across the three layers would give a different and wrong
answer whenever the profile is stratified — which it usually is. Layer 4
(100-289 cm) is excluded because a root zone deeper than 100 cm is not a
crop root zone. The weights are published in the provenance, because the
result depends on them, and a test pins the arithmetic to 0.135 for
layers of 0.30, 0.20 and 0.10 — against a flat mean of 0.20.

### Relative saturation is not volumetric water content

`soil_moisture_wetness` is the one soil metric whose unit is `fraction`
rather than `m3/m3`, and the distinction matters.

The metric reads SMAP L4's `sm_rootzone_wetness` band. The catalogue
defines it as dimensionless, ranging from 0 to 1, and states verbatim
that it describes "relative saturation between completely dry conditions
and completely saturated conditions". It is a *normalised position on the
retention curve*, not a volume of water per volume of soil:

* A wetness of 0.5 does **not** mean half the soil volume is water. It
  means the soil sits halfway between its driest and its wettest state.
* Two soils with the same wetness can hold very different amounts of
  water, because their porosity and retention differ. A sand and a clay
  at wetness 0.5 are not at the same volumetric water content, and are
  not equally available to a crop.
* Wetness therefore speaks to *how full* the bucket is; `m3/m3` speaks to
  *how much water is in it*. Both are useful and they answer different
  questions, so they are published as two metrics and never merged.

Because the band is published in this form, no conversion is applied. The
metric is labelled RELATIVE SATURATION everywhere it surfaces, including
its warnings, so that a downstream reader cannot mistake it for a
volumetric measurement.

**A SoilGrids-derived wetness was evaluated and declined.** SoilGrids
publishes water retention at 10, 33 and 1500 kPa, so the textbook
definition

```
wetness = (theta - wilting_point) / (field_capacity - wilting_point)
```

could in principle be computed from `/wv0033` and `/wv1500`. It was not,
for three reasons:

1. **Depth support does not line up.** The SMAP L4 band is an average
   over 0-100 cm. SoilGrids is delivered at six discrete intervals
   (0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm), so a comparable
   0-100 cm figure requires a thickness weighting that is itself an
   assumption — and the intervals do not tile the root zone evenly.
2. **The two are not the same kind of quantity in time or space.** The
   SMAP band is a 3-hourly, 11 km, dynamically assimilated field. The
   SoilGrids layers are a static 250 m soil property map (1905-2016).
   Dividing one by the other produces a wetness field whose temporal
   variation comes entirely from SMAP and whose spatial texture comes
   partly from a century-scale map.
3. **The suctions are approximations.** 33 kPa is "approximately field
   capacity" and 1500 kPa is "approximately permanent wilting point", and
   neither holds for every soil texture. A derived wetness would inherit
   that approximation silently and present it as a measured saturation.

Using the product's own published wetness band is both more accurate and
more honest, so the derivation was declined and the refusal is recorded
in the metric's provenance.

### CWSI and WDI are not produced

`cwsi` and `wdi` are registered as metrics with `available: false`. They
return `unavailable` with a machine-readable code and a recorded
scientific reason, and they are **structurally incapable of carrying a
value**: both subclass a base whose `compute()` cannot return anything
other than an unavailable result.

The reason is that both indices are defined relative to baselines built
from canopy temperature observations at known water status:

* **CWSI** needs a non-water-stressed baseline and a maximum-stressed
  upper limit. Neither can be observed from satellite data, and the
  empirical baselines published for other crops and climates are not
  transferable without local field data to validate them.
* **WDI** needs the wet and dry edges of a surface-temperature /
  vegetation-index trapezoid. Those edges are not observable from the
  satellite record alone.

No numerical `CWSI_proxy` or `WDI_proxy` is produced. A number derived
from an unvalidated baseline would be a fabricated agricultural
indicator, and it would be acted upon. A scientifically defensible
`unavailable` is worth more than a misleading number, so the engine
reports the omission instead of filling the slot.

---

## Phase G: Land cover engine

Land cover answers "what is on the ground here, and how much of it?" It
is the first domain in this engine whose product is **categorical**, and
that changes the arithmetic rather than merely the dataset.

### The rule that governs the module

**A land-cover class code is a label, not a number.**

Class 4 (Deciduous Broadleaf Forests) is not "twice" class 2 (Evergreen
Broadleaf Forests), and the difference between class 12 and class 13 is
not a distance. The mean of a field that is half water (17) and half
cropland (12) is 14.5 — a value that describes neither and happens to
collide with a real class, Cropland/Natural Vegetation Mosaics. A
downstream reader would act on it.

Every other module in this engine reduces a continuous field and reports
a mean, a median and percentiles. This module never touches
`SpatialStats`. Categorical results travel in a `ClassHistogram`, and
`MetricResult` enforces at construction that a result carries either a
histogram or a numeric value, **never both**.

### Dataset

| Property | Value |
|---|---|
| Dataset ID | `MODIS/061/MCD12Q1` |
| Product | MODIS Land Cover Type Yearly L3 Global 500 m (IGBP scheme) |
| Band read | `LC_Type1` (class distribution), `QC` (quality flags) |
| Spatial resolution | 500 m |
| Temporal resolution | Annual — one classification image per calendar year |
| Catalogue coverage | 2001-01-01 to 2024-01-01 |
| Measurement basis | `product` |

The product is a supervised classification, not an observation of the
ground. It is reported under `MeasurementBasis.PRODUCT`, never `DIRECT`.

### The IGBP class system, and the class-0 problem

`LC_Type1` uses the IGBP scheme: **17 classes numbered 1 to 17, with no
class 0.** Water Bodies is class 17. This matters because the bundled
frontend disagrees.

Class codes are reproduced exactly as the product publishes them. Nothing
is renumbered, re-based or offset.

| Code | Class | Note |
|---|---|---|
| 1 | Evergreen Needleleaf Forests | |
| 2 | Evergreen Broadleaf Forests | |
| 3 | Deciduous Needleleaf Forests | |
| 4 | Deciduous Broadleaf Forests | |
| 5 | Mixed Forests | |
| 6 | Closed Shrublands | |
| 7 | Open Shrublands | |
| 8 | Woody Savannas | |
| 9 | Savannas | |
| 10 | Grasslands | |
| 11 | Permanent Wetlands | |
| 12 | **Croplands** | over 60% cultivated |
| 13 | Urban and Built-up Lands | |
| 14 | **Cropland/Natural Vegetation Mosaics** | 40–60% cultivated, mixed |
| 15 | Permanent Snow and Ice | |
| 16 | Barren | |
| 17 | **Water Bodies** | **not 0** |

> **Note on the sibling bands.** `LC_Type2` (UMD), `LC_Type3` (LAI),
> `LC_Type4` (BGC) and `LC_Type5` (PFT) use *different* legends in which
> class 0 does mean Water Bodies. That is why class 0 is not universally
> invalid across this product, and why the engine reads only `LC_Type1`
> for the land cover metric. A class 0 must never be emitted for
> `LC_Type1`, and it must not be generalised into a claim that "0 is
> always wrong" either.

#### Known frontend defect: the class-0 mismatch

`frontend/src/pages/LandCover.tsx` defines a `LANDCOVER_CLASSES` legend
that maps `'0'` to Water and contains **no entry for `'17'`**.

Consequences, all of which are the consumer's to fix:

* Water is never labelled or coloured by its own legend entry.
* The dominant-class caption falls back to the raw code when water
  dominates.
* Nothing in the legend is *wrong* about the classes it does list
  (12, 14, 10, 9, 13, 16, 1, 2, 5, 7, 8 are all correct), but the map is
  incomplete in the one place that matters most.

The backend does **not** compensate. Emitting a class 0 would invent water
where there is none and misattribute real water to a class the consumer
does not render. Instead:

* the API transmits class 17;
* the service adds an explicit warning to the payload when water is the
  dominant class, naming both the emitted code and the consumer's
  expectation;
* the `/{analysis_id}/landcover` handler documents the mismatch in its
  docstring and echoes `water_bodies_class: 17`.

**Frontend correction remains outstanding.** `frontend/` was not modified
in this phase.

### Cropland reporting: 12 and 14 are never merged

Class 12 is Croplands (over 60% cultivated). Class 14 is
Cropland/Natural Vegetation Mosaics (40–60% cultivated, mixed with
natural vegetation). They answer different questions and are reported
separately, under their own codes.

There is deliberately **no `cropland_fraction`**. Summing 12 and 14 would
overstate cultivated extent by an amount this product does not let us
correct, because the mosaic class gives no figure for how much of it is
actually cultivated. A caller who wants a total adds the two extents
knowing what the sum does and does not mean.

### Metrics

| Key | Unit | Basis | Status |
|---|---|---|---|
| `land_cover_class` | `class` | product | available |
| `land_cover_quality` | `class` | product | available |
| `crop_type` | `class` | inference | unavailable |
| `irrigation` | `class` | inference | unavailable |

`land_cover_class` reports the class histogram, the percentage of the
classified area per class, the percentage of the requested geometry, the
dominant class, and the total classified area. It reports no mean, no
median and no percentile, and the provenance states why.

### QC is not a confidence score

The `QC` band looks like a quality score and is not one. Its ten values
(0–9) are **unordered post-processing event codes**:

| Code | Meaning |
|---|---|
| 0 | Classified land |
| 1 | Unclassified land |
| 2 | Classified water |
| 3 | Unclassified water |
| 4 | Classified sea ice |
| 5 | Misclassified water |
| 6 | Omitted snow/ice |
| 7 | Misclassified snow/ice |
| 8 | Backfilled label |
| 9 | Forest type changed |

There is no ordering. A pixel with QC 8 is not "twice as uncertain" as
one with QC 4, and QC 1 (unclassified land) is not "worse" than QC 2
(successfully classified water) in any monotonic sense.

Therefore `land_cover_quality` reports **the raw flag distribution** and
nothing else. It does not compute `1 − QC/9`, it does not produce a
0–100 score, and it does not treat higher as worse. Its one derived
figure is arithmetic on *extents*, not on codes: the share of classified
pixels whose flag is 0 or 2 (a direct classification), reported as a
count-based statement in a warning.

### Annual behaviour: no interpolation, no substitution

The product publishes one image per calendar year. A request does not
describe a period the way a daily product does; it names one or more
product years, and the honest answer says which year each image belongs
to.

`resolve_product_year()` maps a requested range onto product years:

* every product year the request **overlaps at all** is included, because
  dropping a year the user asked about would silently narrow the answer;
* a request that resolves to exactly one year is reported as that year;
* a request spanning several years returns each year, reported per year
  rather than averaged into a fiction of a single "period"
  classification;
* a request entirely outside coverage returns no years and a reason
  (`outside_product_coverage`), and **no substitute year is ever used**.

A mid-year request maps to its containing product year. The reduction
uses `collection.first()` — the single annual classification — never a
mean over the year, because averaging annual classifications would
interpolate between labels.

The product lags roughly a year behind the present, so the most recent
calendar year is often not yet published. A request for a year past
2024-01-01 is reported unavailable. This is a real behaviour with a real
consequence: the frontend's default date range is 2025, which is outside
coverage, so a default-range request correctly returns unavailability
rather than a map.

Note that when the metric is run through the shared executor, the
capability check rejects an out-of-coverage range *before* `compute()`
runs, so the reason code that reaches a client is the generic
`outside_temporal_coverage` rather than the metric's own more specific
`outside_product_coverage`. Both are correct; the generic one avoids an
expensive empty query.

### Categorical aggregation

Two helpers were added to the existing aggregation module, not a parallel
reduction system:

* `build_class_reducer(ee_module)` returns `Reducer.frequencyHistogram()`.
* `parse_class_histogram(...)` converts the reduction into a
  `ClassHistogram`.

`parse_class_histogram` resolves the payload's **shape** in one place.
A reduction over a single selected band yields a flat dictionary
(`{"12": 300}`); a payload nested under the band name yields
(`{"LC_Type1": {"12": 300}}`). Passing a nested payload through as though
it were flat has no parseable keys and yields an *empty* histogram —
indistinguishable from a field with no land cover at all. That failure
mode was reachable and is now impossible to reach by forgetting an unwrap
in a caller.

Other parsing rules, all of them tested:

* histogram keys arrive as strings and are parsed back to integers;
* a key that will not parse is dropped, not coerced — a mangled class
  code would be attributed to the wrong class;
* `True` is rejected before numeric parsing, because `bool` is an `int`
  subclass and would otherwise become class 1;
* a fractional code (`"12.5"`) is rejected rather than rounded, because a
  fractional key means the band was not categorical;
* a code absent from the legend is **kept** under a placeholder name,
  because dropping it would hide area that genuinely exists and make the
  percentages disagree with the coverage figures;
* zero and negative counts are dropped, since a class with no pixels
  carries no information and would pad the histogram;
* entries sort by descending extent then by code, so equal extents give a
  deterministic order;
* percentages are computed against the **classified** total, while
  `percent_of_geometry` is computed against the **geometry** — two
  different statements, neither allowed to stand in for the other.

### Small geometries and the 500 m limit

The reduction runs at 500 m, the product's own grid. Reducing finer would
resample a 500 m classification and then report the finer figure as the
result's resolution, which is false precision about a product that cannot
resolve it.

At 500 m a pixel covers **25 hectares**. A field smaller than that may
contain no pixel centred on it at all, and a class genuinely present in
the field may therefore be absent from the result. A geometry that
returns no classified pixels produces `insufficient_data` — explicitly
**not** a zero-filled distribution, which would read as "bare ground".

For a **point** geometry the area is undefined. The classification is
still reported (the point's containing pixel is classified), but no area
figure is invented and the geometry-relative percentage has no
denominator. `calculate_area_sq_meters()` returns `None` for a point and
that `None` is propagated rather than replaced with a guess.

The existing MODIS quality thresholds are applied on coverage and image
count as for any other MODIS metric, but no continuous-metric threshold
is applied to the histogram itself, because a distribution is not a
measurement with a tolerable error bar.

### Not produced: crop type

`crop_type` is registered with `available: false`. `LC_Type1` offers one
generic *Croplands* class; it cannot distinguish wheat from maize from
rice from pistachio, and a metric that named one would be inventing it.

The only product in the registry that addresses crop type is ESA
WorldCereal, and it is not a crop-type classifier either. Turning it into
one would require presenting a 2021 binary mask for one product as a
present-day multi-class crop map. No crop-type metric is produced.

The metric is structurally incapable of carrying a value: it subclasses a
base whose `compute()` has no path that returns anything but
`unavailable`.

### Not produced: irrigation

`irrigation` is registered with `available: false`, for four independent
reasons:

1. The WorldCereal irrigation product is a **binary mask for one specific
   product**, not a classification of the landscape's irrigation status.
2. It covers the **single reference year 2021** and cannot describe any
   other season.
3. It is stratified into up to **106 agro-ecological zones** whose images
   must be filtered by `aez_id`, `product` and `season` and are
   independent of one another.
4. Coverage is **incomplete**: zones without a product were not processed
   because thermal Landsat data was unavailable there.

Irrigation status is also not derivable from `MCD12Q1`, which contains no
irrigation information at all. **No irrigation proxy is produced from
either dataset.**

### Dynamic World: deliberately excluded from this phase

`GOOGLE/DYNAMICWORLD/V1` was **not** implemented as a metric in this
phase, and its dataset registration was **not** removed. It remains
registered and verified, available for a future phase.

> **Phase I note.** The deferral ended in Phase I, which implements it as
> `land_cover_probability` — a probabilistic context metric, not a hard
> classification — with every design decision listed here made
> explicitly. See [Phase I](#phase-i-crop-context-crop-area-and-phenology)
> for the reasoning and the scientific guards.

The reasons for excluding it here are substantive, not scheduling:

* **A different class vocabulary.** Nine classes (water, trees, grass,
  flooded vegetation, crops, shrub and scrub, built, bare, snow and ice)
  labelled 0–8. These do not map onto IGBP's 17 classes; presenting one
  under the other's codes would be a category error.
* **Different temporal character.** Near-daily (2–5 day revisit) from
  2015-06-27, rather than one image per year. Reducing it to an annual
  classification is a real modelling choice with a real method, not a
  drop-in.
* **Different spatial character.** 10 m rather than 500 m — a 50× linear
  resolution difference, and 2500× in area per pixel.
* **A different output shape.** It publishes per-class *probabilities*
  that sum to 1, and the catalogue recommends thresholding the top-1
  probability rather than trusting the `label` argmax. That is a
  probabilistic product, not a hard classification.

Implementing it properly means deciding all of the above explicitly. That
is a phase of its own, so it is deferred rather than approximated.

### Registry corrections applied

Verification against the Earth Engine catalogue corrected three defects.

**1. `MODIS/061/MCD12Q1` declared two bands; the product publishes 13.**
All 13 are now declared with verified ranges: `LC_Type1`, `LC_Type2`,
`LC_Type3`, `LC_Type4`, `LC_Type5`, `LC_Prop1`, `LC_Prop2`, `LC_Prop3`,
`LC_Prop1_Assessment`, `LC_Prop2_Assessment`, `LC_Prop3_Assessment`, `LW`,
`QC`. Caveats now record that `LC_Type1` has no class 0, that `LC_Type2`
and `LC_Type3` *do* have one, that each yearly image is a single
classification rather than a composite, and that QC is not a confidence
score.

**2. `ESA/WorldCereal/2021/MODELS/v100` was described as a multi-class
classification.** It is a **binary mask**: `classification` takes the
values **0 or 100**, and `confidence` is a 0–100 percentage. Each image
covers one product and one season for one agro-ecological zone, and images
must be filtered by `aez_id`, `product` and `season`. The description and
caveats now say so, and the products and seasons are enumerated as
constants. **No crop-type metric is built from it.**

**3. The registry invented a nodata value of `255` for WorldCereal.** The
catalogue documents **no fill or nodata value** for this collection, so
declaring one was a fabrication. It has been removed from both bands,
leaving `nodata_values = ()`. A made-up sentinel would have caused
masking logic to discard valid data, or worse, to accept an undocumented
fill as a measurement.

### API and service wiring

No new service or endpoint was created. The existing pieces were wired:

* `analysis_service._run_landcover_analysis()` builds a `MetricContext`,
  runs the land cover metrics through the **existing** `execute_metrics`
  executor, and serialises the results into the standard analysis
  envelope under `result_data["landcover"]` — the key the existing
  endpoint already reads.
* `GET /api/v1/analyses/{analysis_id}/landcover` returns that stored
  block unchanged. Its former `not_implemented` placeholder is gone.

The metric layer owns computation; the service orchestrates and
serialises; the endpoint reads. The handler contains no Earth Engine
code and no metric imports, and a test asserts that, because a second
computation path in the API layer is exactly the duplication this
architecture exists to prevent.

One defect was found and fixed during wiring:
**`register_all_metrics()` was never called anywhere in `app/`** — only
in tests. At runtime the metric registry was empty, so every lookup
missed and a land cover analysis would have degraded into a silent
"unknown metric" rather than a computed result. `ensure_registered()` now
populates the registry on first use, without clearing anything a caller
registered itself.

The frontend-facing shape is preserved: `classes` (code → percentage),
`dominant_class`, `total_area_sq_meters`. Beyond it, the payload adds
`class_details`, `dominant_class_name`, pixel counts, the QC flag
distribution and the metric provenance. When no classification exists,
`total_area_sq_meters` and the pixel counts are **absent** rather than
zero, because a zero area is a measurement and an unavailable analysis is
not.

An unavailable result is reported as an operational `completed` analysis
whose land cover block says `unavailable`. "We do not know" is a correct
answer, not a failure; mapping it to `failed` would present a scientific
limitation as an infrastructure error.

### Limitations carried into every result

1. This is a generic land-cover classification, not a crop type.
2. Classes 12 and 14 are reported separately and never merged.
3. The product is annual and cannot show within-year change such as
   planting, harvest or a mid-season shift.
4. At 500 m a pixel is 25 ha, so a smaller field may have no pixel centred
   on it and a class present on the ground may be absent from the result.
5. Class boundaries are not precise at the pixel level; an edge pixel is
   assigned to one class, so extents carry unquantified classification
   error.
6. The product lags roughly a year behind the present.

---

## Phase H: Terrain engine

Five keys registered: four drivable metrics plus one explicitly
unavailable one, all over NASADEM with SRTM as fallback.

### The temporal contradiction that produced the shared fix

Phase H began with a real architectural contradiction, not a terrain
annoyance. NASADEM and SRTM are static DEM surfaces: each is a bare
`ee.Image` with no time dimension, and their registry dates describe the
February 2000 acquisition. The shared `can_attempt()` contract, written
for time series, read those dates as an observation validity window and
therefore rejected every realistic request — a 2024 terrain analysis was
refused as `outside_temporal_coverage` because the radar flew in 2000.

The fix is the shared `TemporalKind` semantic described under
[Metric contract](#metric-contract), not a terrain workaround. NASADEM,
SRTM and both SoilGrids registrations are explicitly STATIC; every time
series keeps OBSERVATION semantics and unchanged behaviour.

### Datasets

* **NASADEM** (`NASA/NASADEM_HGT/001`) — primary. 30 m, referenced to
  the EGM96 geoid. Registered STATIC with its real acquisition window
  (2000-02-11 to 2000-02-22); no widened dates.
* **SRTM** (`USGS/SRTMGL1_003`) — fallback only. Registered STATIC with
  the same acquisition window. Retained because NASADEM is reprocessed
  SRTM with better void filling; the fallback triggers only when NASADEM
  returns nothing at all.
* **SoilGrids** — both registrations (`ISRIC/SoilGrids250m/v2_0` and the
  external `ISRIC/SOILGRIDS/V2`) are STATIC. A soil map is a modelled
  surface; its temporal extent reflects the underlying soil profiles,
  not a validity window.

### Metrics

| Key | Unit | Notes |
|---|---|---|
| `elevation` | m | Mean elevation above the EGM96 geoid, not the WGS84 ellipsoid |
| `slope` | degrees | Earth Engine terrain routine over four connected neighbours |
| `aspect` | degrees | Circular mean over pixels above a stated slope threshold |
| `terrain_ruggedness` | m | Standard deviation of elevation within the area |
| `topographic_wetness_index` | — | **Not produced**; see below |

### Aspect: 0 degrees does not mean flat

`ee.Terrain.aspect` returns the downslope direction in degrees clockwise
from north. Verified empirically against live Earth Engine during the
Phase H audit with synthetic planes:

    plane descending eastward  -> aspect 90
    plane descending northward -> aspect  0
    genuinely flat terrain     -> aspect  0

The value 0 therefore carries two incompatible meanings, and an
arithmetic mean of compass bearings is wrong anyway (the mean of 350 and
10 degrees taken arithmetically is 180 — due south). The module
accordingly:

* masks aspect to pixels at or above `TERRAIN_ASPECT_MIN_SLOPE_DEG`
  (1.0 degree) **before** the trigonometry, not after;
* computes the mean through `atan2(mean(sin), mean(cos))` — a circular
  mean, never an arithmetic one;
* reports the excluded flat fraction in the result warnings, as a
  first-class part of the answer;
* reports directional concentration R alongside the mean, so a reader
  can tell a prevailing aspect from an average of noise;
* never returns a bearing outside `[0, 360)` — a floating-point residue
  of 359.99999994 is folded to 0.

### Request-date semantics for terrain

For a static DEM the requested date range is **context for which the
user is requesting analysis**, not an observation window the product
must have been observed in. Terrain metrics still validate the request
itself: malformed or inverted date ranges are rejected, and the date
range is folded into the cache key as usual. What they do not do is
reject a 2024 request because the acquisition was in 2000.

### Not produced: topographic wetness index

TWI = ln(a / tan β) requires upstream contributing area, which is a
*globally serial* quantity: the value at one pixel depends on routing
decisions across the entire upstream catchment. Earth Engine exposes no
flow accumulation, flow direction or watershed primitive.
`ee.Terrain.fillMinima` is a depression-filling routine, not flow
routing, and was found unsuitable for the float DEM path tested.

A one-pass focal operation (e.g. `focal_max`) approximates neighbourhood
maxima, not flow accumulation. Presenting it as TWI would publish a
wetness map that looks plausible and answers no hydrological question —
the one failure mode this engine exists to prevent. TWI is registered as
unavailable with code `no_flow_accumulation_primitive`, stating exactly
which primitive is missing. Reopening this requires new infrastructure,
not a clever expression.

### Defects found and fixed while completing Phase H

1. **Circular-mean wrap residue.** `circular_mean_degrees` canonicalised
   exactly-360 results but a `% 360` of a tiny negative angle can also
   leave a value a hair *under* 360 (359.99999994… for atan2 of −1e-9),
   which passed the `>= 360` guard and reported due north as ~360 —
   outside the documented `[0, 360)` contract.
2. **Integration suites could never run live.** All three integration
   test files imported `initialise_earth_engine` (British spelling);
   the app exposes `initialize_earth_engine`. The `ImportError` was
   swallowed into a `pytest.skip`, so even with `RUN_GEE_INTEGRATION_TESTS=1`
   the suites silently skipped instead of running. Fixed in all three.
3. **Aspect disclaimer failed its own contract.** The always-present
   disclaimer said "at or above a slope of", but the contract test
   requires the literal phrase "slope threshold"; the wording was
   aligned.
4. **Test-fixture fidelity defects** (in the fake Earth Engine, not the
   engine): the fake `ee.Terrain.slope/aspect` returned constants for a
   fully masked DEM — real Earth Engine propagates masks through
   derivatives — and the fake `sin()/cos()` interpreted degrees while
   real Earth Engine takes radians. The metric's π/180 conversion was
   correct; the fake disagreed with it, proving only that two wrongs
   had not yet met. Both fixed so the fixture fails loudly on a real
   convention error.

---

## Phase I: Crop context, crop area and phenology

Phase I adds three things: a **crop domain** (crop context and crop area
from ESA WorldCereal), a **phenology domain** (vegetation season events
from a monthly Sentinel-2 NDVI series), and the **first Dynamic World
metric** (per-class land-cover probabilities). Alongside them, four
deliberately unavailable metrics record why planting date, harvest date,
flowering date and the seasonal integral are not produced.

### The audit that preceded the code

Phase I began with a repository audit, as required. Findings:

* The `crop` and `phenology` domains existed in `MetricDomain` but carried
  **zero** registered metrics; `WORLDCEREAL` and `DYNAMIC_WORLD` were
  registered and verified but used by **no** metric.
* Phase G's MCD12Q1 categorical metrics, their service wiring and their
  pinned payload contract were intact and are preserved untouched.
* Phase H's STATIC/OBSERVATION contract is preserved: no dataset was
  reclassified, no date window widened, and every new metric routes
  through `Metric.can_attempt()` unchanged.

### Dataset verification (all against official sources)

| Dataset | Verified against | Key verified facts |
|---|---|---|
| `ESA/WorldCereal/2021/MODELS/v100` | Van Tricht et al. 2023, ESSD 15, 5491 (the product's own paper) | binary `classification` 0/100 + `confidence` 0–100; products `temporarycrops`, `maize`, `wintercereals`, `springcereals`, `irrigation`; image properties `aez_id`, `product`, `season` (incl. `tc-annual`, `tc-maize-main`, `tc-maize-second`); 10 m; single 2021 reference year; cereals = Triticeae (wheat, barley, rye); temporary crops **exclude perennials and pastures**; validation UA 88.5 / PA 92.1 for temporary crops |
| `GOOGLE/DYNAMICWORLD/V1` | Brown et al. 2022, Scientific Data 9:251 (the product's own paper) | 9 probability bands (water, trees, grass, flooded_vegetation, crops, shrub_and_scrub, built, bare, snow_and_ice) + `label` argmax 0–8; probabilities sum to 1; 10 m; 2015-06-27→present; produced only for S2 L1C scenes with `CLOUDY_PIXEL_PERCENTAGE ≤ 35`; validation: crops ≈ 88.9% user's accuracy but ≈ 60% producer's accuracy vs expert consensus |
| `COPERNICUS/S2_SR_HARMONIZED` | registry entry from earlier phases, unchanged | 10 m B4/B8 for NDVI; SCL masking as documented |
| `MODIS/061/MCD12Q1` | registry entry from Phase G, unchanged | 500 m annual IGBP; used by the existing metrics only |

No dataset was used on the strength of its name alone, and no new
band, resolution or coverage claim was invented: the two newly-used
datasets were re-verified against their primary publications before any
code was written.

### Metrics added

| Key | Domain | Value | Unit | Basis | Status |
|---|---|---|---|---|---|
| `temporary_crop_context` | crop | share of classified area under temporary crops (2021, `tc-annual`) | fraction | product | available |
| `maize_context` | crop | share under maize (2021, `tc-maize-main`) | fraction | product | available |
| `cereal_context` | crop | share under winter cereals / Triticeae (2021) | fraction | product | available |
| `temporary_crop_area` | crop | crop-area estimate + total/crop area separation | fraction (+ area in stats/warnings) | product | available |
| `land_cover_probability` | landcover | top class mean probability + all nine | probability | product | available |
| `vegetation_season_onset` | phenology | first upward threshold crossing | decimal_year | derived | available |
| `vegetation_activity_peak` | phenology | smoothed NDVI maximum (interior only) | decimal_year | derived | available |
| `vegetation_season_end` | phenology | last downward threshold crossing | decimal_year | derived | available |
| `vegetation_season_length` | phenology | EOS − SOS | days | derived | available |
| `vegetation_season_amplitude` | phenology | max − min of the smoothed series | index | derived | available |
| `crop_planting_date` | crop | — | — | inference | **not produced** |
| `crop_harvest_date` | crop | — | — | inference | **not produced** |
| `crop_flowering_date` | crop | — | — | inference | **not produced** |
| `vegetation_seasonal_integral` | phenology | — | — | inference | **not produced** |

The three available crop metrics read exactly one product and one season
each, filtered by the verified `product` and `season` image properties;
no two images are ever mixed. The Dynamic World metric lives in its own
collection (`DYNAMIC_WORLD_METRICS`) so the `landcover` analysis type's
pinned MCD12Q1 contract is unchanged.

### Crop context: what the terms mean here

* **Temporary crops** — crops with a less-than-one-year cycle that must
  be re-sown after harvest. Perennial crops and pastures are excluded by
  the product's own definition, which every result states: a low share
  is not evidence that the land is not farmed.
* **Cereals** — the Triticeae tribe: wheat, barley and rye, deliberately
  grouped by the product because their signatures and seasons cannot be
  separated globally. There is no wheat-only map here and none may be
  inferred from it.
* **Maize** — the only named species any registered dataset supports,
  and only for the 2021 main season.
* No crop species is ever derived from MCD12Q1 classes, from Dynamic
  World probabilities, or from any vegetation index.

### Crop area: quality-aware by construction

`temporary_crop_area` distinguishes three areas that a careless
implementation would collapse into one:

1. **Total geometry area** — the requested polygon's area, reported in
   the result warnings.
2. **Classified area** — valid pixels × 100 m² (the 10 m grid).
3. **Estimated crop-covered area** — crop pixels × 100 m², where crop
   pixels = share × valid pixels.

Rules enforced:

* **The valid-pixel floor (`CROP_AREA_MIN_VALID_FRACTION` = 0.5) is
  load-bearing.** Below 50% classified coverage the result is
  `insufficient_data`: the missing part could be crop or not crop, and
  the product gives no way to tell.
* **The reduction runs at the product's own 10 m grid.**
* **The share is published as the numeric value; the areas travel in
  the statistics and the warnings**, so a fraction is never read as an
  area.
* **Every result carries the ESA validation accuracies** (UA 88.5 / PA
  92.1), the mixed-pixel boundary limitation, and the statement that a
  pixel-derived area is **not a survey-grade field boundary
  measurement**.
* An unprocessed AEZ is `insufficient_data`, never zero crop.
* No area metric is built from Dynamic World: a per-pixel posterior is
  not a cover fraction, and converting one to the other would be an
  invented area.

### The phenology algorithm, stated in full

Every rule is implemented once in `phenology.py` and tested against
hand-computed series:

| Element | Definition |
|---|---|
| Input index | NDVI = (B8 − B4)/(B8 + B4) per scene, Sentinel-2 L2A, after the engine's SCL mask (0, 1, 3, 8, 9, 10 removed; 7 retained) |
| Compositing | per-scene spatial mean at 10 m → calendar-month mean; a month with no usable scene is absent, never zero |
| Smoothing | 3-point moving average, only where all three months are consecutive; edges never smoothed; **no interpolation anywhere** |
| Baseline | the per-window minimum of the (smoothed ∪ edge) series; no external climatology |
| Amplitude | max − min over the window |
| Threshold | min + 0.5 × amplitude (the midpoint) — a reporting convention of this engine, stated in every result, not a calibrated agronomic rule |
| SOS | first crossing from below to at/above the threshold |
| EOS | last crossing from at/above to below the threshold |
| PEAK | month of the smoothed maximum, ties to the earliest month; refused when the maximum sits on a window edge **or** a raw edge value bleeds into the smoother |
| LOS | EOS − SOS in days, only when both crossings occur in a sane order; an inverted arrangement is refused, never published as negative |
| Min observations | ≥ 6 distinct months (`MIN_MONTHS`) and a window ≥ 180 days (`MIN_WINDOW_DAYS`); the window rule is enforced in `can_attempt`, so a short window is refused before any query |
| Gaps | up to 2 consecutive missing months tolerated; 3+ yields `insufficient_data` (`MAX_TOLERATED_GAP_MONTHS`) |
| Date resolution | events are dated to the first day of their month; the decimal-year encoding preserves month resolution and is tested for it |
| Quality | the spatial verdict (`SENTINEL2_THRESHOLDS`) is enforced **before** any value is published, so the series arithmetic cannot release a number the coverage does not support |

**The seasonal integral was evaluated and declined**
(`vegetation_seasonal_integral`, code `integral_requires_gap_filling`):
an integral sums every month between the crossings, so an unfilled gap of
even one month biases the total, and every fill is an invention in
exactly the cloudy periods where the integral would be used. The
proposal to fill gaps locally was rejected for that reason rather than
implemented.

### Phenology scientific safety

The metrics describe the **vegetation signal**, and every result carries
the denial in its warnings:

* the onset is **not the planting date** — canopy development follows
  sowing by an interval no registered dataset observes;
* the peak is **not flowering** — it is peak green canopy, and no
  registered dataset observes anthesis;
* the end is **not the harvest date** — green-canopy loss has many
  causes (senescence, drought, disease, hail, forage cutting) and the
  signal does not distinguish them;
* no phenology anomaly is attributed to any agronomic cause.

The corresponding event-date metrics are registered as unavailable with
full reasons: `crop_planting_date` (`no_planting_date_product`),
`crop_harvest_date` (`no_harvest_date_product`),
`crop_flowering_date` (`no_flowering_signal_product`).

The Dynamic World metric carries the same discipline: the value is the
candidate dominant class's mean probability, the argmax `label` band is
**never read** (the fake raises if a metric selects it), no area is
derived from a probability, and the ~60% producer's accuracy of the
crops class is quoted in the limitations.

### Quality rules introduced in this phase

| Rule | Where |
|---|---|
| valid-pixel floor 0.5 for all crop metrics | `CROP_AREA_MIN_VALID_FRACTION` |
| binary-domain assertion (mean ∈ [0, 100]) before share derivation | `crop.py::_crop_share` |
| ≥ 6 months, ≥ 180-day window, ≤ 2-month gap for phenology | `phenology.py` constants, enforced in compute + `can_attempt` |
| spatial quality enforced before publishing any phenology value | `phenology.py::compute` |
| Dynamic World reporting floor: a top mean probability below 0.4 is flagged as insufficient for any dominant-context claim | `DYNAMIC_WORLD_DOMINANT_MIN_PROBABILITY` |
| argmax band structurally unreadable in tests | `test_landcover.py` fake |

### Provenance additions

Every new provenance carries the product identity (dataset ID, bands,
`temporal_kind`), the requested period, the aggregation method and the
formula — plus, for phenology, the **complete monthly series** and the
longest gap as caveats, so any event can be recomputed from the
published record. The phenology formula string states the index, the
compositing, the smoothing, the threshold share and each event rule in
one line. The crop provenance names the exact `product` and `season`
filter values and the 2021 reference year.

### Defects found and fixed while building Phase I

1. **`SeasonEvents` was frozen but mutated** by its own detector —
   caught by the first test run. Made a mutable detector record.
2. **The peak rule had an edge-bleed hole**: a raw maximum on the
   window's first or last month bleeds into the smoother, producing an
   interior smoothed maximum that is still a window artefact. The rule
   now refuses a peak whenever the raw edge maximum is at or above the
   smoothed maximum. Found by the edge-peak test; a regression test pins
   it.
3. **The phenology metrics published a value while the *spatial*
   quality verdict was INSUFFICIENT** — the `MetricResult` guard caught
   the contradiction. The refusal is now explicit in `compute`.
4. **The EE idiom was corrected during development**: the per-scene
   pass now sets both properties in one `map` and reads them with two
   `aggregate_array` calls (the first draft used a nested `map` that is
   both awkward server-side and un-fakeable faithfully). The fake
   refuses unknown property names, so a property mix-up fails loudly.
5. **The categorical source-scan test was scoped** to the MCD12Q1
   section of `landcover.py`: the Dynamic World probability section
   legitimately uses the continuous reducer because probabilities are
   quantities, not labels. The scan's intent (no averaging of *class
   codes*) is unchanged.

### Tests added (128)

* `test_crop.py` (51): the 2021 gate never touches EE when refused; the
  product/season filters are recorded by the fake; binary-share
  arithmetic including a classified zero and an out-of-domain refusal;
  the valid-pixel floor from both sides; the area prose separating total
  geometry area, classified area and crop area at 10 m; the survey-grade
  disclaimer; the ESA validation accuracies; the Triticeae grouping;
  species-denial prose scans; the unavailable metrics' codes and
  structural inability to carry a value.
* `test_phenology.py` (61): the moving average against hand-computed
  values; gap-stopping; every event rule including tie-breaking,
  inverted-order refusal, flat series, edge peaks, unsorted refusal;
  min-months, min-window and max-gap rules from both sides; the
  decimal-year encoding including leap years; provenance carrying the
  full series and the full algorithm; the agronomic-denial prose scans;
  the declined integral.
* `test_landcover.py` (+16): the probability metric's own collection;
  nine-band-only selection (argmax structurally unreadable); top-mean
  value; candidate-dominant wording; the reporting floor; the
  no-area-from-probability guard; recall limitation; provenance rule;
  registration sharing.

### Live GEE verification

The opt-in live suite (`RUN_GEE_INTEGRATION_TESTS=1`) was executed.
35 tests collected; the run passes or skips with the precise
infrastructure reason — the service account lacks
`roles/earthengine.viewer`, so live compute checks skip with that exact
message rather than a bare `pytest.skip`. No Phase I integration suite
was added: the new metrics' Earth Engine paths are exercised through
contract fakes, and adding live checks against an archive the service
account cannot read yet would produce skips, not verification. The
remaining live-verification gap is the IAM grant, unchanged from
Phase H.

### Remaining limitations (all stated in results)

* Every crop figure is the **2021 reference year** and cannot describe
  any other season.
* Unprocessed AEZs are missing data, never zero crop.
* Phenology events carry **month resolution** and are computed over the
  requested window; a season straddling the window can be truncated.
* The threshold is the amplitude midpoint — a defensible, conventional
  rule, not an agronomic constant.

---

## Registry contents

### Earth Engine datasets

| Dataset ID | Role | Basis | Resolution | Temporal kind | From |
|---|---|---|---|---|---|
| `COPERNICUS/S2_SR_HARMONIZED` | primary | direct | 10/20/60 m | observation | 2017-03-28 |
| `LANDSAT/LC08/C02/T1_L2` | primary | direct | 30 m | observation | 2013-03-18 |
| `MODIS/061/MCD15A3H` | primary | product | 500 m | observation | 2002-07-04 |
| `MODIS/061/MCD12Q1` | primary | product | 500 m | observation | 2001-01-01 |
| `GOOGLE/DYNAMICWORLD/V1` | primary | product | 10 m | observation | 2015-06-27 |
| `ESA/WorldCereal/2021/MODELS/v100` | primary | product | 10 m | observation | 2020-01-01 |
| `ECMWF/ERA5_LAND/DAILY_AGGR` | primary | modelled | 0.1° | observation | 1950-01-02 |
| `IDAHO_EPSCOR/TERRACLIMATE` | primary | modelled | 1/24° | observation | 1958-01-01 |
| `MODIS/061/MOD16A2GF` | primary | product | 500 m | observation | 2000-01-01 |
| `MODIS/061/MOD16A2` | fallback | product | 500 m | observation | 2021-01-01 |
| `MODIS/061/MOD11A2` | primary | direct | 1 km | observation | 2000-02-18 |
| `MODIS/061/MOD11A1` | fallback | direct | 1 km | observation | 2000-02-18 |
| `NASA/SMAP/SPL3SMP_E/006` | primary | product | 9 km | observation | 2023-12-04 |
| `NASA/SMAP/SPL3SMP_E/005` | fallback | product | 9 km | observation | 2015-03-31 |
| `NASA/SMAP/SPL4SMGP/008` | primary | modelled | 11 km | observation | 2015-03-31 |
| `NASA/GLDAS/V021/NOAH/G025/T3H` | primary | modelled | 0.25° (27 830 m) | observation | 2000-01-01 |
| `ISRIC/SoilGrids250m/v2_0` | primary | modelled | 250 m | **static** | — |
| `NASA/NASADEM_HGT/001` | primary | product | 30 m | **static** | 2000-02-11 (acquisition) |
| `USGS/SRTMGL1_003` | fallback | product | 30 m | **static** | 2000-02-11 (acquisition) |

Notes on the Phase F additions:

* SMAP L3 is split across `/006` (2023-12-04 onward) and `/005`
  (2015-03-31 to 2023-12-03). Both are declared by the surface metrics
  and the collection is chosen from the requested start date.
* `NASA/SMAP/SPL4SMGP/008` is delivered on an 11 km pixel even though
  the underlying grid is 9 km EASE-Grid 2.0. Its catalogue maximum is
  0.9, not 1.0.
* `ISRIC/SoilGrids250m/v2_0` is available **natively in Earth Engine**,
  which supersedes the paused REST client for these properties. The
  water-retention assets are `/wv0010`, `/wv0033` and `/wv1500`, at 250 m
  with six depth intervals and unit `cm^3/cm^3` (scale factor 0.001).
* `NASA/GLDAS/V021/NOAH/G025/T3H` was added when the deferred Phase F
  metric was closed. Cadence 3 hourly, pixel size 27 830 m, availability
  from 2000-01-01, band `RootMoist_inst` with units `kg/m^2` — all
  verified against the catalogue entry and its STAC record. Only that one
  band is declared; the profile layers exist in the same asset and are
  recorded in the caveats rather than registered, because no metric reads
  them.

Notes on the Phase G corrections:

* `MODIS/061/MCD12Q1` now declares all **13** published bands rather than
  the two it declared before. Only `LC_Type1` and `QC` are read by the
  land cover metrics; the rest are declared so the registry reflects the
  product. Its availability ends at **2024-01-01**.
* `ESA/WorldCereal/2021/MODELS/v100` had its band semantics corrected:
  `classification` is a **binary mask taking the values 0 or 100**, not a
  multi-class map, and `confidence` is a 0–100 percentage. An invented
  `255` nodata value was removed from both bands, because the catalogue
  documents **no** fill value for this collection.
* `GOOGLE/DYNAMICWORLD/V1` remains registered but is **not** used by any
  metric this phase. See
  [Dynamic World: deliberately excluded](#dynamic-world-deliberately-excluded-from-this-phase).

Notes on the Phase H temporal classification:

* `NASA/NASADEM_HGT/001`, `USGS/SRTMGL1_003`, `ISRIC/SoilGrids250m/v2_0`
  and the external `ISRIC/SOILGRIDS/V2` are declared
  `temporal_kind=STATIC`. Their dates are acquisition/reference metadata:
  they are recorded in provenance as `product_date` and are **not** used
  to gate requests. Every other dataset keeps the default OBSERVATION
  semantics, under which the dates remain a hard coverage gate.
* A dataset's declared kind must agree with its own description: the
  registry rejects a STATIC dataset whose `temporal_resolution` does not
  say "static", and an OBSERVATION one whose does.
* The ESA WorldCereal entry was audited and deliberately left
  OBSERVATION: it is a 2021 reference-year map, but a request outside
  its 2020–2021 window genuinely cannot be served from it (there is no
  2019 or 2023 product in this asset), so its dates remain a real
  coverage bound.

### External sources

| Dataset ID | Role | Basis | Resolution |
|---|---|---|---|
| `ISRIC/SOILGRIDS/V2` | primary, external | modelled | 250 m |

---

## Known constraints

### SoilGrids REST API is paused

ISRIC states the SoilGrids REST API is temporarily paused with no
restoration timeline, and labels it beta with no uptime guarantee. The
conversion factors and depth interval strings could not be verified
against live documentation during this outage, so they carry the
`PENDING_VERIFICATION` sentinel and SoilGrids reports itself as
unverified. The client will return `unavailable` while the service is
down. This is correct behaviour, not a failure.

### Topographic Wetness Index

Not produced, and the earlier plan to implement a documented
flow-accumulation algorithm was **reversed** during the Phase H audit
(see [Phase H](#phase-h-terrain-engine) for the full reasoning): TWI
needs true flow accumulation, which is a globally serial quantity, and
Earth Engine exposes no primitive for it. `ee.Terrain` offers only local
per-pixel derivatives: `slope`, `aspect`, `hillshade`, `products`,
`fillMinima` — the last of which is a depression-filling routine, not
flow routing, and proved unsuitable for the float DEM path tested.
TWI is registered as unavailable with the specific reason
`no_flow_accumulation_primitive` rather than presented as a focal
approximation.

---

## Testing

```
backend/
├── pytest.ini
└── tests/
    ├── conftest.py        auto-skips integration tests by default
    ├── unit/agriculture/  test_types.py, test_quality.py, test_registry.py,
    │                      test_aggregation.py, test_base.py, test_executor.py,
    │                      test_indices.py, test_vegetation.py,
    │                      test_climate.py, test_thermal.py, test_bootstrap.py,
    │                      test_water.py, test_soil.py, test_landcover.py,
    │                      test_terrain.py, test_crop.py, test_phenology.py
    └── integration/       requires RUN_GEE_INTEGRATION_TESTS=1
                           (climate, thermal, terrain, water, soil)
```

### Coverage by area

| Area | Tests | What they guarantee |
|---|---|---|
| `test_types.py` | 35 | No value without provenance; proxy labelling; no value at insufficient quality |
| `test_quality.py` | 63 | Missing data never becomes zero; coverage only downgrades; SMAP flag decoding |
| `test_registry.py` | 195 | Every scale factor, band name and availability date is correct; the GLDAS entry's unit, cadence, coverage and open-loop caveats |
| `test_aggregation.py` | 47 | Empty reductions yield no values; coverage arithmetic is consistent |
| `test_base.py` | 38 | Cache keys are deterministic and complete; coverage windows respected |
| `test_executor.py` | 30 | Per-metric error isolation; error sanitisation; concurrency |
| `test_indices.py` | 55 | Index arithmetic matches the published formulas |
| `test_vegetation.py` | 63 | Required bands exist; band scale matches resolution; no diagnostic claims |
| `test_climate.py` | 82 | Unit conversions; no unpaired two-band derivations |
| `test_thermal.py` | 58 | QC bit decoding; Kelvin discipline; thermal scale factors |
| `test_water.py` | 118 | ERA5 sign is a negation, not `abs()` and not clamped; MOD16 ×0.1 scale factor; no double counting; NDWI/NDMI/MNDWI band wiring; CWSI/WDI carry no value |
| `test_soil.py` | 140 | Volume-fraction units preserved across quantity families, with exactly one pinned kg/m2 exception (GLDAS root zone) that is never converted to m3/m3; relative saturation kept distinct from volumetric water content; the SMAP skip-bit mask is load-bearing; morning and evening flags are never interchanged; thickness-weighted root zone arithmetic; missing data never becomes zero |
| `test_landcover.py` | 172 | Class codes are counted, never averaged; there is no IGBP class 0 and water is 17; class 12 and 14 are never merged; no crop species is asserted; QC never becomes a confidence score; no year is substituted outside coverage; histogram shape resolution; service and endpoint wiring; **Dynamic World probability handling: the argmax band is structurally unreadable, no area from a probability, candidate-dominant wording, the recall limitation (Phase I)** |
| `test_terrain.py` | 62 | A 2024 request against a 2000 acquisition computes; the circular mean wraps through north correctly; flat terrain is excluded before the trigonometry; TWI refuses with the specific missing primitive; provenance separates `product_date` from the requested period |

`test_bootstrap.py` contributes a further 18 tests covering whole-registry
invariants, including that every metric entry carries its provenance
vocabulary and that every unavailable metric explains itself.

The two Phase F test files use a strict fake Earth Engine module rather
than monkeypatching assertions. The fakes raise when a metric asks for a
band the fixture did not provide, so a band-mix-up fails loudly instead
of returning a plausible wrong number. Two guarantees are asserted
directly rather than by inspection:

* the SMAP skip mask is **load-bearing** — with one good day at 0.30 and
  two skipped days holding a 0.02 fill value, the result is 0.30; if the
  mask were removed the median would be 0.02 and the field would look
  falsely dry;
* the ERA5 negation is **not** an `abs()` — a stored `+0.005` must yield
  `-5.0`, and the test asserts the result is strictly negative rather
  than merely the right magnitude.

`test_landcover.py` extends that convention. Its fake rejects any reducer
other than a histogram, so a metric that reduced a categorical band with
a mean would fail rather than return a plausible average class code. The
scientific guards are asserted in the direction that matters — a
*denial*, not merely a missing feature — including:

* no class-code averaging anywhere in the module (checked against the
  module source, so a later edit cannot quietly reintroduce it);
* no class 0 in any result, for a water-only, a cropland-only and a mixed
  area alike;
* class 12 and class 14 present as separate entries with no merged
  fraction;
* QC reported as raw flags with no derived index, and the metric's own
  prose checked for the forbidden `1 − QC/9` form;
* an out-of-range year reported as unavailable with an empty class table
  and no area figure, never a substituted year.

Service- and endpoint-level tests live in the same file. They pin the
serialised contract (`classes`, `dominant_class`, `total_area_sq_meters`),
assert that a point geometry produces no invented area, and assert that
the API handler imports no metric-layer symbol — because a second
computation path in the API layer is the duplication this architecture
exists to prevent.

Run the unit suite:

```bash
cd backend
./.venv/Scripts/python.exe -m pytest tests/unit -q
```

Focused Phase F regression (the files this closure touches):

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/agriculture/test_soil.py tests/unit/agriculture/test_registry.py -q
```

Unit tests require no network, no Earth Engine credentials and no
database. This is enforced, not merely intended: the registry, quality
and types modules import cleanly without pulling in `ee`.

The full suite leaves **no database residue**. No test opens a session,
and no module under `app/services/agriculture/` imports the ORM or
issues a write. After a complete run the `agri_intelligence` database
still reports zero relations, which is the expected state: the schema is
applied by `alembic upgrade head`, not by the tests.

Integration tests are skipped unless explicitly enabled:

```bash
RUN_GEE_INTEGRATION_TESTS=1 ./.venv/Scripts/python.exe -m pytest tests/integration -q
```

The water and soil integration files were added when the deferred Phase F
items were closed. They check the two things the fake Earth Engine cannot
confirm: that the ERA5-Land evaporation band really is negative for
upward flux in the archive, and that the SMAP, MOD16, ERA5-Land and
GLDAS-2.1 band names and units match what Earth Engine publishes. The
GLDAS check also confirms the live pixel size is 27 830 m, so the
declared resolution cannot drift away from the asset unnoticed.

The terrain integration file additionally asserts the static contract
against the live archive — that a 2024 terrain request computes against
the February 2000 acquisition and that provenance keeps `product_date`
separate from the requested period. During this phase's run the service
account lacked `roles/earthengine.viewer`, so the live-compute checks
skipped with that exact reason; they will run unchanged once the IAM
role is granted.

---

## Dependencies added

| Package | Version | Reason |
|---|---|---|
| `numpy` | `>=2.0,<3.0` (2.4.6 verified) | VPD, GDD, evapotranspiration and aggregation maths |

No other dependencies were required. `httpx` was already present for the
SoilGrids client.

The numpy pin is a range rather than an exact version because the
project venv already carried numpy 2.4.6 and a 1.x pin would not resolve
against it. The exact patch version should be frozen once the
environment's dependency set is confirmed against a reachable index.
