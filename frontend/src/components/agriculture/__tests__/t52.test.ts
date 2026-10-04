/**
 * P5.2 focused tests — Temporal intelligence visualizations.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/t52.test.ts
 * Covers pure chart mapping (values, dates, units, gaps, backend
 * passthrough), metric identity (NDMI, radar units, thermal
 * separation), and static guards proving the visualization layer
 * computes no science of its own.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import {
  attachAnomalies,
  attachChanges,
  baselineLevels,
  findTemporalPayloads,
  formatShortDate,
  hasUsableData,
  mapProfilePoints,
  orientationFor,
  persistenceSummary,
  relationshipFor,
  stateTone,
  toGapValue,
} from '../temporalChart.ts';
import { thermalSourceMetaFor } from '../thermal.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readNewSource(name: string): string {
  return readFileSync(join(agricultureDir, name), 'utf-8');
}

const MAPPER_SOURCES = [
  readNewSource('temporalChart.ts'),
  readNewSource('TemporalLineChart.tsx'),
  readNewSource('TemporalChartCard.tsx'),
];
const ALL_NEW_SOURCES = [
  ...MAPPER_SOURCES,
  readNewSource('TemporalSection.tsx'),
];

/** Strip comments so prose about absent computation cannot trip guards. */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '$1');
}

const STRIPPED_MAPPER_SOURCES = MAPPER_SOURCES.map(stripComments);
const STRIPPED_ALL_NEW_SOURCES = ALL_NEW_SOURCES.map(stripComments);

const NDVI_POINTS = [
  { window_start: '2024-01-01', window_end: '2024-01-31', value: 0.62, unit: 'index', quality: 'good', coverage_percent: 100 },
  { window_start: '2024-02-01', window_end: '2024-02-29', value: null, unit: 'index', quality: 'insufficient', coverage_percent: 0 },
  { window_start: '2024-03-01', window_end: '2024-03-31', value: 0.71, unit: 'index', quality: 'good', coverage_percent: 98.5 },
];

// --- 1-4. Values, dates, units, nulls -----------------------------------------

describe('1-4. mapping preserves backend observations', () => {
  it('temporal mapping preserves values in backend order', () => {
    const data = mapProfilePoints(NDVI_POINTS, 'index');
    assert.deepEqual(
      data.map((d) => d.value),
      [0.62, null, 0.71],
    );
    assert.deepEqual(
      data.map((d) => d.window_start),
      ['2024-01-01', '2024-02-01', '2024-03-01'],
    );
  });

  it('dates remain exact with display labels derived only', () => {
    const data = mapProfilePoints(NDVI_POINTS, 'index');
    assert.equal(data[0]?.period, '2024-01-01 → 2024-01-31');
    assert.ok((data[0]?.label ?? '').length > 0);
    assert.equal(formatShortDate('not-a-date'), 'not-a-date');
  });

  it('units remain exact from backend records', () => {
    const data = mapProfilePoints(NDVI_POINTS, 'fallback');
    assert.equal(data[0]?.unit, 'index');
    const radar = mapProfilePoints(
      [{ window_start: '2024-01-01', window_end: '2024-01-31', value: -8.2 }],
      'dB',
    );
    assert.equal(radar[0]?.unit, 'dB');
  });

  it('null values remain null, never zero', () => {
    const data = mapProfilePoints(NDVI_POINTS, 'index');
    assert.equal(data[1]?.value, null);
    assert.notEqual(data[1]?.value, 0);
    assert.equal(data[1]?.quality, 'insufficient');
  });
});

// --- 5-7. Gaps without fill or interpolation -----------------------------------

describe('5-7. missing months are chart gaps', () => {
  it('non-finite values become gaps', () => {
    assert.equal(toGapValue(Number.NaN), null);
    assert.equal(toGapValue(Number.POSITIVE_INFINITY), null);
    assert.equal(toGapValue(undefined), null);
    assert.equal(toGapValue('0.6'), null);
    assert.equal(toGapValue(0), 0);
  });

  it('line never connects across gaps and never fills', () => {
    const chart = readNewSource('TemporalLineChart.tsx');
    assert.ok(chart.includes('connectNulls={false}'));
    assert.ok(!chart.includes('connectNulls={true}'));
    for (const source of STRIPPED_ALL_NEW_SOURCES) {
      assert.ok(!source.includes('interpolate('));
      assert.ok(!/connectNulls=\{(true|1)\}/.test(source));
    }
  });

  it('no zero-fill patterns in new visualization code', () => {
    for (const source of ALL_NEW_SOURCES) {
      assert.ok(!/\?\?\s*0\b/.test(source));
      assert.ok(!/\|\|\s*0\b/.test(source));
    }
  });

  it('usability detection counts finite values only', () => {
    assert.equal(hasUsableData(mapProfilePoints(NDVI_POINTS, 'index')), true);
    assert.equal(
      hasUsableData(
        mapProfilePoints(
          NDVI_POINTS.map((p) => ({ ...p, value: null })),
          'index',
        ),
      ),
      false,
    );
  });
});

// --- 8-15. Backend anomaly/change/persistence passthrough -----------------------

describe('8-15. anomaly, change, and persistence ride along unchanged', () => {
  const anomalies = [
    { window_start: '2024-01-01', window_end: '2024-01-31', value: 0.62, unit: 'index', quality: 'good', coverage_percent: 100, image_count: 4, z_score: 1.2, percentile: 88.5, category: 'ABOVE_BASELINE' },
    { window_start: '2024-03-01', window_end: '2024-03-31', value: 0.71, unit: 'index', quality: 'good', coverage_percent: 98.5, image_count: 4, z_score: 2.1, percentile: 97.0, category: 'ABOVE_BASELINE' },
  ];
  const changes = [
    { window_start: '2024-03-01', window_end: '2024-03-31', value: 0.71, previous_window_start: '2024-01-01', previous_window_end: '2024-01-31', previous_value: 0.62, absolute_change: 0.09, relative_change: 0.145, days_elapsed: 60, rate_per_day: 0.0015, direction: 'INCREASE', rapid: 'NOT_RAPID', z_score: 2.1, percentile: 97.0, unit: 'index', quality: 'good', coverage_percent: 98.5, image_count: 4 },
  ];

  it('baseline levels are read verbatim', () => {
    const levels = baselineLevels({ mean: 0.55, minimum: 0.4, maximum: 0.7 } as never);
    assert.deepEqual(levels, { mean: 0.55, min: 0.4, max: 0.7 });
    assert.equal(baselineLevels(null), null);
    assert.equal(baselineLevels({ mean: Number.NaN } as never), null);
  });

  it('anomaly category, z-score, and percentile attach by window', () => {
    const data = attachAnomalies(mapProfilePoints(NDVI_POINTS, 'index'), anomalies as never);
    assert.equal(data[0]?.state, 'ABOVE_BASELINE');
    assert.equal(data[0]?.z, 1.2);
    assert.equal(data[0]?.percentile, 88.5);
    assert.equal(data[1]?.state, null);
    assert.equal(data[1]?.z, null);
  });

  it('change fields attach by window without recomputation', () => {
    const data = attachChanges(mapProfilePoints(NDVI_POINTS, 'index'), changes as never);
    assert.equal(data[2]?.absoluteChange, 0.09);
    assert.equal(data[2]?.relativeChange, 0.145);
    assert.equal(data[2]?.ratePerDay, 0.0015);
    assert.equal(data[2]?.direction, 'INCREASE');
    assert.equal(data[2]?.rapid, 'NOT_RAPID');
    assert.equal(data[0]?.direction, null);
  });

  it('persistence summary repeats backend state and runs', () => {
    const text = persistenceSummary({
      longest_run_below: 0, longest_run_above: 4, n_anomalous: 4,
      n_observed: 9, n_missing: 1, state: 'PERSISTENT',
    });
    assert.ok(text?.includes('PERSISTENT'));
    assert.ok(text?.includes('4'));
    assert.equal(persistenceSummary(null), null);
  });

  it('insufficient orientation keeps an observed value plottable', () => {
    const data = mapProfilePoints(
      [{ window_start: '2024-01-01', window_end: '2024-01-31', value: 20.0, quality: 'poor' }],
      'degC',
    );
    assert.equal(data[0]?.value, 20.0);
    assert.equal(data[0]?.quality, 'poor');
  });
});

// --- 16-20. Optical and radar identity ------------------------------------------

describe('16-20. metric identity is preserved', () => {
  it('NDMI remains NDMI in page configuration', () => {
    const water = DOMAIN_PAGE_CONFIGS.water;
    const section = water.sections.find((s) => s.id === 'temporal-moisture');
    assert.ok(section);
    assert.deepEqual(
      (section?.temporalSeries ?? []).map((s) => s.metricKey),
      ['ndmi', 'msi'],
    );
    assert.equal(section?.temporalSeries?.[0]?.label, 'NDMI');
  });

  it('NDMI is never labeled NDWI in changed sources', () => {
    const changed = [
      readFileSync(join(agricultureDir, 'domainPages.ts'), 'utf-8'),
      ...ALL_NEW_SOURCES,
    ];
    for (const source of changed) {
      assert.ok(!/NDWI/.test(source));
    }
  });

  it('radar units stay dB/dB/dB/ratio in configuration', () => {
    const vegetation = DOMAIN_PAGE_CONFIGS.vegetation;
    const section = vegetation.sections.find((s) => s.id === 'temporal-radar');
    assert.ok(section);
    const byKey = Object.fromEntries(
      (section?.temporalSeries ?? []).map((s) => [s.metricKey, s.unit]),
    );
    assert.deepEqual(byKey, { vv: 'dB', vh: 'dB', 'vh_vv': 'dB', rvi: 'ratio' });
  });

  it('optical temporal section keeps NDVI and NDRE', () => {
    const vegetation = DOMAIN_PAGE_CONFIGS.vegetation;
    const section = vegetation.sections.find((s) => s.id === 'temporal-optical');
    assert.ok(section);
    assert.deepEqual(
      (section?.temporalSeries ?? []).map((s) => s.metricKey),
      ['ndvi', 'ndre'],
    );
  });
});

// --- 21-25. Thermal separation ----------------------------------------------------

describe('21-25. thermal quantities stay separate', () => {
  it('MODIS LST keeps its land-surface identity', () => {
    const meta = thermalSourceMetaFor('LST_PROFILE');
    assert.equal(meta.displayLabel, 'Land Surface Temperature');
    assert.equal(meta.physicalQuantity, 'land_surface_temperature');
    assert.equal(meta.datasetId, 'MODIS/061/MOD11A2');
    const thermal = DOMAIN_PAGE_CONFIGS.thermal;
    const section = thermal.sections.find((s) => s.id === 'temporal-lst');
    assert.ok(section);
    assert.equal(section?.temporalSeries?.[0]?.metricKey, 'land_surface_temperature_day');
    assert.equal(section?.temporalSeries?.[0]?.thermalKind, 'LST_PROFILE');
  });

  it('ERA5 keeps its modelled air-temperature identity', () => {
    const meta = thermalSourceMetaFor('AIR_TEMPERATURE_PROFILE');
    assert.equal(meta.displayLabel, 'Modelled 2 m Air Temperature');
    assert.equal(meta.physicalQuantity, 'air_temperature_2m');
    const climate = DOMAIN_PAGE_CONFIGS.climate;
    const section = climate.sections.find((s) => s.id === 'temporal-air-temperature');
    assert.ok(section);
    assert.equal(section?.temporalSeries?.[0]?.metricKey, 'temperature_mean');
    assert.equal(section?.temporalSeries?.[0]?.thermalKind, 'AIR_TEMPERATURE_PROFILE');
  });

  it('LST and ERA5 live on separate sections, never one pooled chart', () => {
    const allSeries = Object.values(DOMAIN_PAGE_CONFIGS).flatMap((config) =>
      config.sections.flatMap((section) => section.temporalSeries ?? []),
    );
    const lstEntries = allSeries.filter((s) => s.thermalKind === 'LST_PROFILE');
    const airEntries = allSeries.filter((s) => s.thermalKind === 'AIR_TEMPERATURE_PROFILE');
    assert.equal(lstEntries.length, 1);
    assert.equal(airEntries.length, 1);
    assert.notEqual(lstEntries[0]?.metricKey, airEntries[0]?.metricKey);
  });

  it('relationship and orientation read backend states verbatim', () => {
    const month = {
      window_start: '2024-01-01',
      window_end: '2024-01-31',
      rule_id: 'P44_THERMAL_CONCORDANCE_V1',
      lst: { orientation: 'UP' },
      air: { orientation: 'DOWN' },
      lst_relationship: 'THERMAL_CONCORDANT',
      air_relationship: 'THERMAL_CONTEXT_DIVERGENT',
    } as never;
    assert.equal(relationshipFor(month, 'lst'), 'THERMAL_CONCORDANT');
    assert.equal(relationshipFor(month, 'air'), 'THERMAL_CONTEXT_DIVERGENT');
    assert.equal(orientationFor(month, 'lst'), 'UP');
    assert.equal(orientationFor(month, 'air'), 'DOWN');
    assert.equal(relationshipFor(null, 'lst'), null);
  });

  it('state tones never invent categories', () => {
    assert.equal(stateTone('ABOVE_BASELINE'), '#27ae60');
    assert.equal(stateTone('BELOW_BASELINE'), '#c0392b');
    assert.equal(stateTone('SOMETHING_ELSE'), '#95a5a6');
  });
});

// --- 26-28. Availability, finiteness, provenance access -----------------------------

describe('26-28. availability and provenance behavior', () => {
  it('unavailable and insufficient months are not values', () => {
    const data = mapProfilePoints(
      [
        { window_start: '2024-01-01', window_end: '2024-01-31', value: null, quality: 'unavailable' },
        { window_start: '2024-02-01', window_end: '2024-02-29', value: null, quality: 'insufficient' },
      ],
      'degC',
    );
    assert.ok(data.every((d) => d.value === null));
    assert.equal(hasUsableData(data), false);
  });

  it('temporal payloads keep full backend records for provenance', () => {
    const bundles = {
      thermal: {
        items: [
          {
            metric_key: 'land_surface_temperature_day',
            points: [
              {
                window_start: '2024-01-01',
                window_end: '2024-01-31',
                value: 26.85,
                provenance: { source_dataset_id: 'MODIS/061/MOD11A2' },
              },
            ],
          },
        ],
      },
    };
    const found = findTemporalPayloads(bundles);
    assert.ok('land_surface_temperature_day' in found);
    const points = found['land_surface_temperature_day']?.points;
    assert.ok(Array.isArray(points));
  });

  it('non-profile bundle items resolve to no temporal payload', () => {
    const bundles = {
      vegetation: { items: [{ metric_key: 'ndvi', value: 0.6 }] },
    };
    assert.deepEqual(findTemporalPayloads(bundles), {});
    assert.deepEqual(findTemporalPayloads(null), {});
  });
});

// --- 29-31. No science, biology, or scores in new code -------------------------------

describe('29-31. visualization code computes nothing scientific', () => {
  it('no statistical computation tokens in mapper and chart sources', () => {
    for (const source of STRIPPED_MAPPER_SOURCES) {
      assert.ok(!/mean\(/.test(source));
      assert.ok(!/\.reduce\(/.test(source));
      assert.ok(!/Math\.sqrt/.test(source));
      assert.ok(!/Math\.pow/.test(source));
      assert.ok(!/stdev|stddev/i.test(source));
      assert.ok(!/zScore|standardized|calculate/i.test(source));
      assert.ok(!/percentile\(/.test(source));
      assert.ok(!/threshold/i.test(source));
    }
  });

  it('no biological interpretation or canopy claims', () => {
    for (const source of STRIPPED_ALL_NEW_SOURCES) {
      assert.ok(!/pest|disease|defoliation|fungal|nutrient|drought/i.test(source));
      assert.ok(!/canopy temperature/i.test(source));
      assert.ok(!/heat stress|thermal stress|canopy stress/i.test(source));
    }
  });

  it('no score, risk, probability, or severity vocabulary', () => {
    for (const source of STRIPPED_ALL_NEW_SOURCES) {
      assert.ok(!/risk|probability|severity|confidence|winner|ranking/i.test(source));
      // 'Z-score' is the backend field's display label, not a scoring
      // feature; mask it and the P1.2 method reference before scanning.
      const masked = source
        .replace(/score_profile/g, 'method_ref')
        .replace(/Z-score/g, 'Z');
      assert.ok(!/\bscore\b/i.test(masked));
    }
  });

  it('no thermal subtraction patterns', () => {
    for (const source of STRIPPED_ALL_NEW_SOURCES) {
      assert.ok(!/\blst\s*[-−+*/]\s*\S/i.test(source));
      assert.ok(!/temperature_2m\s*[-−+*/]/i.test(source));
      assert.ok(!/LST_Day_1km\s*[-−+*/]/i.test(source));
    }
  });
});

// --- 32-34. Responsive, accessible, deterministic --------------------------------------

describe('32-34. responsive, accessible, deterministic rendering', () => {
  it('chart sizes fluidly without a fixed viewport', () => {
    const chart = readNewSource('TemporalLineChart.tsx');
    assert.ok(chart.includes('ResponsiveContainer'));
    assert.ok(chart.includes('width="100%"'));
    assert.ok(!/width=\{[0-9]{3,}\}/.test(chart));
  });

  it('categorical states stay text-accessible', () => {
    const chart = readNewSource('TemporalLineChart.tsx');
    const card = readNewSource('TemporalChartCard.tsx');
    assert.ok(chart.includes('role="img"'));
    assert.ok(chart.includes('aria-label'));
    assert.ok(chart.includes('State'));
    assert.ok(card.includes('empty-state'));
  });

  it('mapping is deterministic', () => {
    const first = attachChanges(
      attachAnomalies(mapProfilePoints(NDVI_POINTS, 'index'), []),
      [],
    );
    const second = attachChanges(
      attachAnomalies(mapProfilePoints(NDVI_POINTS, 'index'), []),
      [],
    );
    assert.deepEqual(first, second);
    assert.deepEqual(
      mapProfilePoints(NDVI_POINTS, 'index').map((d) => d.label),
      mapProfilePoints(NDVI_POINTS, 'index').map((d) => d.label),
    );
  });

  it('DomainPage renders temporal sections without redesign', () => {
    const page = readFileSync(join(srcDir, 'pages', 'agriculture', 'DomainPage.tsx'), 'utf-8');
    assert.ok(page.includes("section.kind === 'temporal'"));
    assert.ok(page.includes('TemporalSection'));
  });
});
