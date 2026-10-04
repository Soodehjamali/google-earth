/**
 * P2A focused tests — land-cover class shares presentation parity.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p2a.test.ts
 * Covers taxonomy pass-through, both supplied ratios, dominant class,
 * honest empty states, the absent-area contract, config wiring, the
 * neutral palette, and static guards (no legacy API, no chart tokens,
 * no fabricated data).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import { classShareModel, dominantClassLabel } from '../evidenceDetails.ts';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const COMPONENT = 'components/agriculture/LandCoverSharesSection.tsx';

function entry(code: number, name: string, percent: number, geometryPercent: number) {
  return {
    code,
    name,
    pixel_count: Math.round(percent * 1000),
    percent,
    percent_of_geometry: geometryPercent,
  };
}

function histogram(
  entries: ReturnType<typeof entry>[],
  extra: Record<string, unknown> = {},
) {
  return {
    entries,
    dominant_code: entries.length > 0 ? entries[0].code : null,
    dominant_name: entries.length > 0 ? entries[0].name : '',
    valid_pixel_count: 83700,
    total_pixel_count: 100000,
    ...extra,
  };
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    metric_key: 'land_cover_class',
    unit: 'category',
    status: 'ok',
    quality: 'good',
    display_name: 'Land Cover Class',
    is_usable: false,
    is_proxy: false,
    ...overrides,
  } as NonNullable<Parameters<typeof classShareModel>[0]>;
}

// --- 1. taxonomy --------------------------------------------------------------------------

describe('1. class taxonomy comes from the response, never from a local map', () => {
  it('backend class names and codes pass through unchanged', () => {
    const model = classShareModel(
      item({
        class_histogram: histogram([
          entry(12, 'Croplands', 41.5, 37.4),
          entry(10, 'Grasslands', 30.2, 27.2),
          entry(17, 'Water Bodies', 12.1, 10.9),
        ]),
      }),
    );
    assert.deepEqual(
      model.rows.map((row) => row.name),
      ['Croplands', 'Grasslands', 'Water Bodies'],
    );
    assert.deepEqual(model.rows.map((row) => row.code), [12, 10, 17]);
    // The IGBP water class 17 stays present under its backend name —
    // the legacy palette's '0 → Water' mapping is never reintroduced.
    const water = model.rows.find((row) => row.code === 17);
    assert.ok(water);
    assert.equal(water.name, 'Water Bodies');
  });

  it('rows are ranked by the supplied share, highest first', () => {
    const model = classShareModel(
      item({
        class_histogram: histogram([
          entry(16, 'Barren', 8.4, 7.6),
          entry(12, 'Croplands', 64.9, 58.4),
          entry(1, 'Evergreen Needleleaf Forests', 5.1, 4.6),
        ]),
      }),
    );
    assert.deepEqual(model.rows.map((row) => row.code), [12, 16, 1]);
  });
});

// --- 2/3. ratios and dominant ----------------------------------------------------------

describe('2/3. both supplied ratios and the response dominant class', () => {
  it('percent and percent_of_geometry are preserved as delivered', () => {
    const model = classShareModel(
      item({
        class_histogram: histogram([entry(12, 'Croplands', 41.5, 37.4)]),
      }),
    );
    assert.equal(model.rows[0].percent, 41.5);
    assert.equal(model.rows[0].percent_of_geometry, 37.4);
  });

  it('dominant follows the response dominant_code, not row order alone', () => {
    const model = classShareModel(
      item({
        class_histogram: histogram([entry(1, 'Croplands', 30, 27)], {
          dominant_code: 1,
        }),
      }),
    );
    assert.equal(model.dominant?.code, 1);
    assert.equal(model.dominant?.name, 'Croplands');
    assert.equal(model.dominant?.percent, 30);
  });

  it('dominant falls back to the top ranked class when no code is supplied', () => {
    const model = classShareModel(
      item({
        class_histogram: histogram(
          [entry(10, 'Grasslands', 55, 49.5), entry(12, 'Croplands', 20, 18)],
          { dominant_code: null },
        ),
      }),
    );
    assert.equal(model.dominant?.code, 10);
  });
});

// --- 4/5. honest empty states --------------------------------------------------------------

describe('4/5. absent, empty, and out-of-scope inputs stay honest', () => {
  it('missing item and missing distribution are not reported as carried', () => {
    assert.deepEqual(classShareModel(null).rows, []);
    assert.equal(classShareModel(null).carried, false);
    const withoutDistribution = classShareModel(
      item({ class_histogram: null, metric_key: 'land_cover_class' }),
    );
    assert.equal(withoutDistribution.carried, false);
    assert.deepEqual(withoutDistribution.rows, []);
    assert.equal(withoutDistribution.dominant, null);
  });

  it('an empty distribution is distinguishable from an absent one', () => {
    const carriedEmpty = classShareModel(
      item({
        class_histogram: {
          entries: [],
          dominant_code: null,
          dominant_name: '',
          valid_pixel_count: 0,
          total_pixel_count: 100000,
        },
      }),
    );
    assert.equal(carriedEmpty.carried, true);
    assert.deepEqual(carriedEmpty.rows, []);
    assert.equal(carriedEmpty.dominant, null);
    assert.equal(carriedEmpty.total_pixel_count, 100000);
  });

  it('only the land-cover class key is modelled', () => {
    const quality = classShareModel(
      item({
        metric_key: 'land_cover_quality',
        class_histogram: histogram([entry(0, 'Good', 90, 81)]),
      }),
    );
    assert.deepEqual(quality.rows, []);
    assert.equal(quality.carried, false);
  });
});

// --- 6. no area is derivable --------------------------------------------------------------

describe('6. area in km² is reported as not provided', () => {
  it('the model exposes no area quantity of any kind', () => {
    const model = classShareModel(
      item({
        class_histogram: histogram([entry(12, 'Croplands', 41.5, 37.4)]),
      }),
    );
    assert.deepEqual(
      Object.keys(model).sort(),
      ['carried', 'dominant', 'rows', 'total_pixel_count', 'valid_pixel_count'],
    );
    assert.ok(!('area' in model));
    assert.ok(!('area_sq_km' in model));
  });

  it('the section states the missing area instead of inventing one', () => {
    const component = readSource(COMPONENT);
    assert.ok(component.includes('not provided by this response'));
    assert.ok(component.includes('km'));
    for (const fabrication of ['1e-6', 'sq_km', 'sqKm', 'pixelArea', 'square_km']) {
      assert.ok(!component.includes(fabrication), `component contains ${fabrication}`);
    }
  });
});

// --- 7. pixels are shown as pixels --------------------------------------------------------

describe('7. pixel counts are surfaced as supplied', () => {
  it('valid and total pixel counts reach the section', () => {
    const model = classShareModel(
      item({ class_histogram: histogram([entry(12, 'Croplands', 41.5, 37.4)]) }),
    );
    assert.equal(model.valid_pixel_count, 83700);
    assert.equal(model.total_pixel_count, 100000);
    assert.ok(readSource(COMPONENT).includes('total pixels'));
  });
});

// --- 8. configuration wiring ----------------------------------------------------------------

describe('8. land-crop wires the shares section without changing its key set', () => {
  it('a landcover-shares section exists with the class key and a note', () => {
    const landCrop = DOMAIN_PAGE_CONFIGS['land-crop'];
    const section = landCrop.sections.find((s) => s.kind === 'landcover-shares');
    assert.ok(section, 'landcover-shares section missing');
    assert.deepEqual(section.metricKeys, ['land_cover_class']);
    assert.ok(typeof section.note === 'string' && section.note.length > 0);
    assert.ok(section.title.length > 0);
    assert.ok(section.titleFa.length > 0);
  });

  it('the configured land-crop key set is unchanged', () => {
    const keys = new Set<string>();
    for (const section of DOMAIN_PAGE_CONFIGS['land-crop'].sections) {
      for (const key of section.metricKeys) keys.add(key);
    }
    assert.deepEqual([...keys].sort(), [
      'cereal_context',
      'land_cover_class',
      'land_cover_probability',
      'land_cover_quality',
      'maize_context',
      'temporary_crop_area',
      'temporary_crop_context',
    ]);
  });

  it('DomainPage renders the section from the existing bundles', () => {
    const page = readSource('pages/agriculture/DomainPage.tsx');
    assert.ok(page.includes("section.kind === 'landcover-shares'"));
    assert.ok(page.includes('LandCoverSharesSection'));
    assert.ok(page.includes('findEvidenceItem'));
  });
});

// --- 9. neutral palette ---------------------------------------------------------------------

describe('9. the shares use one neutral accent, never an invented per-class palette', () => {
  it('the component carries no colour literals', () => {
    const component = readSource(COMPONENT);
    assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(component), 'hex colour literal found');
    assert.ok(component.includes('var(--color-primary)'));
    assert.ok(component.includes('var(--color-border)'));
  });
});

// --- 10. static guards ------------------------------------------------------------------------

describe('10. the new section keeps every lock intact', () => {
  it('no chart machinery, legacy API, or fabricated-data tokens', () => {
    const component = readSource(COMPONENT);
    const forbidden = [
      'recharts',
      'BarChart',
      'DistributionChart',
      'Histogram',
      'histogram',
      'class_histogram',
      'ClassHistogram',
      'LineChart',
      'TimeSeries',
      'time_series',
      'new Array(',
      'as any',
      'as unknown as',
      'analysesApi.',
      'vegetationApi.',
      'locationsApi.',
      'agricultureApi.analyze',
      'fetch(',
      'domains: []',
    ];
    for (const token of forbidden) {
      assert.ok(!component.includes(token), `component contains ${token}`);
    }
  });

  it('the legacy land-cover route is a compatibility redirect; the page file remains', () => {
    // Final consolidation: /landcover redirects to /agriculture/land-crop.
    // The route path stays registered; the page file stays in the repo.
    const app = readSource('App.tsx');
    assert.ok(app.includes('path="/landcover"'));
    assert.ok(app.includes('to="/agriculture/land-crop"'));
    assert.ok(!app.includes("./pages/LandCover"), 'stale LandCover import in App');
    assert.ok(!app.includes('<LandCover />'), 'legacy LandCover still rendered');
    const legacy = readSource('pages/LandCover.tsx');
    assert.ok(legacy.includes('ComprehensiveNotice'));
    assert.ok(legacy.includes('analysesApi.create'));
  });
});

// --- 11. scalar grid shows the dominant class ------------------------------------------------

describe('11. the scalar grid shows the dominant class, not an unavailable card', () => {
  it('label is Name (code) taken from the response taxonomy', () => {
    const label = dominantClassLabel(
      item({
        class_histogram: histogram([
          entry(14, 'Cropland/Natural Vegetation Mosaics', 12.1, 10.9),
        ]),
      }),
    );
    assert.equal(label, 'Cropland/Natural Vegetation Mosaics (14)');
  });

  it('absent shares and other keys fall through to the ordinary branches', () => {
    assert.equal(dominantClassLabel(null), null);
    assert.equal(dominantClassLabel(item({ class_histogram: null })), null);
    assert.equal(
      dominantClassLabel(
        item({
          metric_key: 'land_cover_quality',
          class_histogram: histogram([entry(0, 'Good', 90, 81)]),
        }),
      ),
      null,
    );
  });

  it('the grid keeps every existing lock while adding the dominant branch', () => {
    const grid = readSource('components/agriculture/MetricKpiGrid.tsx');
    assert.ok(grid.includes('dominantClassLabel'));
    assert.ok(grid.includes('shouldRenderKpi'));
    assert.ok(grid.includes('ProxyStateCard'));
    assert.ok(grid.includes('kpi-no-data'));
    assert.ok(grid.includes('unavailable'));
    for (const token of ['class_histogram', 'ClassHistogram', 'recharts', 'as any']) {
      assert.ok(!grid.includes(token), `grid contains ${token}`);
    }
  });
});
