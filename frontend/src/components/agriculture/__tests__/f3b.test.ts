/**
 * F3-B focused tests — truthful consumption of the F3-A structured fields.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/f3b.test.ts
 * Covers S1/S2/S3/H/DW semantics via the pure evidenceDetails module
 * plus static source guards for the presentational components.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  DYNAMIC_WORLD_BANDS,
  DYNAMIC_WORLD_DOMINANT_FLOOR,
  DYNAMIC_WORLD_METRIC,
  bandRows,
  cropShare,
  histogramRows,
  isCropShareMetric,
  isDynamicWorldMetric,
  isHistogramMetric,
  isSpatialStatsMetric,
  spatialStatRows,
  coverageRows,
  temporalRange,
  temporalRangeKind,
} from '../evidenceDetails.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readComponent(name: string): string {
  return readFileSync(join(agricultureDir, name), 'utf-8');
}

function statsFixture(overrides: Record<string, number | null> = {}) {
  return {
    mean: 0.62,
    median: 0.6,
    min: 0.1,
    max: 0.9,
    std_dev: 0.12,
    p10: 0.3,
    p25: 0.45,
    p75: 0.75,
    p90: 0.85,
    valid_pixel_count: 100,
    valid_area_sq_m: 10000,
    total_pixel_count: 120,
    missing_pixel_count: 20,
    missing_percent: 16.7,
    coverage_percent: 83.3,
    ...overrides,
  };
}

// --- S1 --------------------------------------------------------------------------------------------

describe('S1 spatial stats detail', () => {
  it('Type-A keys render; Type-B/C keys do not', () => {
    for (const key of ['ndvi', 'lai', 'temperature_mean', 'soil_moisture_surface', 'elevation', 'evapotranspiration', 'par', 'surface_temperature_range']) {
      assert.equal(isSpatialStatsMetric(key), true, key);
    }
    for (const key of [
      'evapotranspiration_cumulative',
      'era5_evaporation',
      'wind_speed',
      'vpd',
      'relative_humidity',
      'gdd',
      'temporary_crop_context',
      'maize_context',
      'cereal_context',
      'temporary_crop_area',
      'aspect',
      'terrain_ruggedness',
      'ndvi_anomaly_absolute',
      'evaporative_fraction',
      'precipitation_cumulative',
    ]) {
      assert.equal(isSpatialStatsMetric(key), false, key);
    }
  });

  it('fields follow the frozen order and nulls are omitted', () => {
    const rows = spatialStatRows(statsFixture({ median: null, p25: null }));
    assert.deepEqual(
      rows.map((row) => row.key),
      ['mean', 'min', 'max', 'std_dev', 'p10', 'p75', 'p90'],
    );
  });

  it('stats-null yields no rows (block absent)', () => {
    assert.deepEqual(spatialStatRows(null), []);
    assert.deepEqual(spatialStatRows(undefined), []);
    assert.deepEqual(coverageRows(null), []);
  });

  it('coverage rows follow the frozen order', () => {
    assert.deepEqual(
      coverageRows(statsFixture()).map((row) => row.key),
      [
        'coverage_percent',
        'valid_pixel_count',
        'total_pixel_count',
        'missing_pixel_count',
        'missing_percent',
        'valid_area_sq_m',
      ],
    );
  });
});

// --- S2 --------------------------------------------------------------------------------------------

describe('S2 temporal/composite range', () => {
  it('only the six source-verified Type-B metrics qualify, with correct labels', () => {
    assert.equal(temporalRangeKind('evapotranspiration_cumulative'), 'composite');
    for (const key of ['era5_evaporation', 'wind_speed', 'vpd', 'relative_humidity', 'gdd']) {
      assert.equal(temporalRangeKind(key), 'daily', key);
    }
    assert.equal(temporalRangeKind('ndvi'), null);
    assert.equal(temporalRangeKind('temperature_mean'), null);
    assert.equal(temporalRangeKind('aspect'), null);
  });

  it('min/max range renders; missing bounds yield null', () => {
    const range = temporalRange('vpd', statsFixture());
    assert.deepEqual(range, { kind: 'daily', min: 0.1, max: 0.9 });
    assert.equal(temporalRange('vpd', statsFixture({ min: null })), null);
    assert.equal(temporalRange('vpd', statsFixture({ max: null })), null);
    assert.equal(temporalRange('ndvi', statsFixture()), null);
  });

  it('range exposes only min/max — no mean, no coverage fields', () => {
    const range = temporalRange('gdd', statsFixture());
    assert.ok(range !== null);
    assert.deepEqual(Object.keys(range).sort(), ['kind', 'max', 'min']);
  });

  it('component never renders coverage or spatial-spread wording', () => {
    const text = readComponent('StructuredDetails.tsx');
    const start = text.indexOf('export function TemporalRangeDetail');
    const end = text.indexOf('export function CropShareDetail');
    assert.ok(start >= 0 && end > start);
    const s2Section = text.slice(start, end);
    assert.ok(!s2Section.includes('coverage'));
    assert.ok(!s2Section.includes('Spatial spread'));
    assert.ok(s2Section.includes('daily range'));
    assert.ok(s2Section.includes('composite range'));
  });
});

// --- S3 --------------------------------------------------------------------------------------------

describe('S3 crop share', () => {
  it('exactly the four WorldCereal context metrics qualify', () => {
    for (const key of ['temporary_crop_context', 'maize_context', 'cereal_context', 'temporary_crop_area']) {
      assert.equal(isCropShareMetric(key), true, key);
    }
    assert.equal(isCropShareMetric('ndvi'), false);
    assert.equal(isCropShareMetric('land_cover_class'), false);
  });

  it('share converts mask-mean units to percent', () => {
    assert.deepEqual(cropShare('maize_context', statsFixture({ mean: 42 })), { percent: 42 / 100 });
  });

  it('non-qualifying keys and null means yield null', () => {
    assert.equal(cropShare('ndvi', statsFixture()), null);
    assert.equal(cropShare('maize_context', null), null);
    assert.equal(cropShare('maize_context', statsFixture({ mean: null })), null);
  });

  it('no area conversion exists in the S3 path', () => {
    const module = readFileSync(join(agricultureDir, 'evidenceDetails.ts'), 'utf-8');
    assert.ok(!module.includes('hectare'));
    const component = readComponent('StructuredDetails.tsx');
    assert.ok(!component.includes('hectare'));
    assert.ok(component.includes('never total agricultural area'));
  });
});

// --- H ---------------------------------------------------------------------------------------------

describe('H class histogram', () => {
  it('exactly the two categorical metrics qualify', () => {
    assert.equal(isHistogramMetric('land_cover_class'), true);
    assert.equal(isHistogramMetric('land_cover_quality'), true);
    assert.equal(isHistogramMetric('ndvi'), false);
    assert.equal(isHistogramMetric('land_cover_probability'), false);
  });

  it('entries sort by percent descending with all columns', () => {
    const rows = histogramRows({
      entries: [
        { code: 10, name: 'Grasslands', pixel_count: 200, percent: 40, percent_of_geometry: 33.3 },
        { code: 12, name: 'Croplands', pixel_count: 300, percent: 60, percent_of_geometry: 50 },
      ],
      dominant_code: 12,
      dominant_name: 'Croplands',
      valid_pixel_count: 500,
      total_pixel_count: 600,
    });
    assert.deepEqual(rows.map((row) => row.code), [12, 10]);
    assert.deepEqual(Object.keys(rows[0]).sort(), [
      'code',
      'name',
      'percent',
      'percent_of_geometry',
      'pixel_count',
    ]);
  });

  it('absent histogram yields no rows', () => {
    assert.deepEqual(histogramRows(null), []);
    assert.deepEqual(histogramRows(undefined), []);
  });

  it('QC codes are not presented as rankings; no area conversion', () => {
    const text = readComponent('ClassHistogramDetail.tsx');
    assert.ok(text.includes('not a quality ranking'));
    assert.ok(!text.includes('hectare'));
    assert.ok(!text.includes('Pie') && !text.includes('Donut') && !text.includes('donut'));
    assert.ok(!text.includes('recharts'));
  });
});

// --- DW --------------------------------------------------------------------------------------------

describe('DW band probabilities', () => {
  it('exactly nine canonical bands; probability metric only', () => {
    assert.deepEqual([...DYNAMIC_WORLD_BANDS], [
      'water',
      'trees',
      'grass',
      'flooded_vegetation',
      'crops',
      'shrub_and_scrub',
      'built',
      'bare',
      'snow_and_ice',
    ]);
    assert.equal(isDynamicWorldMetric('land_cover_probability'), true);
    assert.equal(isDynamicWorldMetric('land_cover_class'), false);
    assert.equal(DYNAMIC_WORLD_DOMINANT_FLOOR, 0.4);
  });

  it('non-null values sort descending; nulls last; unknown keys dropped', () => {
    const rows = bandRows({
      water: 0.05,
      trees: null,
      grass: 0.3,
      flooded_vegetation: 0.01,
      crops: 0.55,
      shrub_and_scrub: 0.02,
      built: 0.01,
      bare: 0.01,
      snow_and_ice: null,
      label: 4,
    });
    assert.equal(rows.length, 9);
    assert.deepEqual(
      rows.map((row) => row.band),
      ['crops', 'grass', 'water', 'shrub_and_scrub', 'flooded_vegetation', 'built', 'bare', 'trees', 'snow_and_ice'],
    );
    assert.ok(!rows.some((row) => (row.band as string) === 'label'));
  });

  it('absent band_means yields no rows', () => {
    assert.deepEqual(bandRows(null), []);
    assert.deepEqual(bandRows(undefined), []);
    assert.deepEqual(bandRows({}), []);
  });

  it('component uses candidate wording, floor convention, 0-1 values', () => {
    const text = readComponent('DynamicWorldBands.tsx');
    assert.ok(text.includes('Candidate dominant context'));
    assert.ok(text.includes('not a hard classification'));
    assert.ok(text.includes('DYNAMIC_WORLD_DOMINANT_FLOOR'));
    assert.ok(!text.includes('hectare'));
    assert.ok(!text.includes('% of land') && !text.includes('percent of the area'));
  });
});

// --- Architecture ----------------------------------------------------------------------------------

describe('F3-B architecture preservation', () => {
  it('child routes still make no API calls', () => {
    const domainPage = readFileSync(join(srcDir, 'pages/agriculture/DomainPage.tsx'), 'utf-8');
    assert.ok(!domainPage.includes('agricultureApi'));
    assert.ok(!domainPage.includes('fetch('));
  });

  it('F3-B components make no API calls and parse no warnings', () => {
    for (const name of [
      'evidenceDetails.ts',
      'StructuredDetails.tsx',
      'ClassHistogramDetail.tsx',
      'DynamicWorldBands.tsx',
      'EvidenceDetailCard.tsx',
    ]) {
      const text = readComponent(name);
      assert.ok(!text.includes('agricultureApi'), `${name} calls API`);
      assert.ok(!text.includes('fetch('), `${name} fetches`);
      assert.ok(!text.includes('warnings'), `${name} reads warnings`);
    }
  });

  it('no generic stats renderer exists that could leak Type-B coverage', () => {
    const module = readFileSync(join(agricultureDir, 'evidenceDetails.ts'), 'utf-8');
    assert.ok(module.includes('never a generic'));
    const card = readComponent('EvidenceDetailCard.tsx');
    for (const tag of ['SpatialStatsDetail', 'TemporalRangeDetail', 'CropShareDetail', 'ClassHistogramDetail', 'DynamicWorldBands']) {
      assert.ok(card.includes(tag), `EvidenceDetailCard missing ${tag}`);
    }
  });
});
