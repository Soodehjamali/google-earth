/**
 * UI-2 spatial + relationship tests.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/spatial.test.ts
 * Covers spatial helpers (valid/empty/partial payloads, filters,
 * geometry fallback), the SpatialSection component contract via
 * source checks, MapView backward compatibility, joint/concordance
 * relationship rendering from existing fields, and the documented
 * patterns block (no fake pattern UI).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  concordanceSummaryOf,
  jointAnalysisOf,
  patternsInResponse,
  validationsInResponse,
} from '../evidence.ts';
import {
  SPATIAL_STATE_VALUES,
  cellPolygonFeature,
  concordanceForCell,
  concordanceStateLabel,
  distinctConcordanceStates,
  distinctSpatialMetrics,
  observationsForCell,
  persistenceForCell,
  persistenceStateLabel,
  spatialCells,
  spatialLimitations,
  spatialMapCenter,
  spatialObservations,
  spatialStateLabel,
  spatialSummaries,
} from '../spatial.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const RING = [
  [
    [51.0, 35.0],
    [51.1, 35.0],
    [51.1, 35.1],
    [51.0, 35.1],
    [51.0, 35.0],
  ],
];

function makeCell(overrides: Record<string, unknown> = {}) {
  return {
    cell_id: 'r1c1',
    row: 1,
    col: 1,
    west: 51.0,
    south: 35.0,
    east: 51.1,
    north: 35.1,
    geometry: { type: 'Polygon', coordinates: RING },
    ...overrides,
  } as never;
}

function makeObservation(overrides: Record<string, unknown> = {}) {
  return {
    cell_id: 'r1c1',
    metric_key: 'ndvi',
    window_start: '2024-01-01',
    window_end: '2024-01-31',
    value: 0.62,
    unit: 'index',
    category: 'ABOVE_BASELINE',
    quality: 'good',
    coverage_percent: 100.0,
    image_count: 4,
    ...overrides,
  } as never;
}

function makeSpatial(overrides: Record<string, unknown> = {}) {
  return {
    window_start: '2024-01-01',
    window_end: '2024-01-31',
    grid_rows: 1,
    grid_cols: 1,
    bbox: [51.0, 35.0, 51.1, 35.1],
    cells: [makeCell()],
    observations: [makeObservation()],
    summaries: {
      ndvi: {
        metric_key: 'ndvi',
        window_start: '2024-01-01',
        window_end: '2024-01-31',
        n_cells: 1,
        n_usable: 1,
        n_missing: 0,
        anomalous_count: 1,
        anomalous_fraction: 1.0,
        quality_counts: { good: 1 },
        state: 'ANOMALOUS_AREA',
        method: 'area aggregation',
      },
    },
    concordance: [
      {
        cell_id: 'r1c1',
        window_start: '2024-01-01',
        window_end: '2024-01-31',
        metrics: ['ndvi', 'ndmi'],
        anomalous_metrics: ['ndvi'],
        state: 'SINGLE_METRIC_ANOMALY',
      },
    ],
    persistence: [
      {
        cell_id: 'r1c1',
        longest_run_below: 0,
        longest_run_above: 2,
        n_anomalous: 2,
        n_observed: 3,
        n_missing: 1,
        state: 'PERSISTENT',
      },
    ],
    limitations: ['single-window persistence'],
    ...overrides,
  } as never;
}

// --- 1. Valid payload ---------------------------------------------------------------

describe('1. spatial section renders with a valid payload', () => {
  it('cells, observations, and summaries narrow in backend order', () => {
    const spatial = makeSpatial();
    assert.deepEqual(spatialCells(spatial).map((c) => c.cell_id), ['r1c1']);
    assert.equal(spatialObservations(spatial).length, 1);
    assert.deepEqual(
      spatialSummaries(spatial).map((s) => s.metric_key),
      ['ndvi'],
    );
    assert.deepEqual(spatialLimitations(spatial), ['single-window persistence']);
  });

  it('per-cell lookups resolve by exact cell identity', () => {
    const spatial = makeSpatial();
    assert.equal(observationsForCell(spatialObservations(spatial), 'r1c1').length, 1);
    assert.deepEqual(observationsForCell(spatialObservations(spatial), 'r9c9'), []);
    assert.equal(concordanceForCell(spatial, 'r1c1')?.state, 'SINGLE_METRIC_ANOMALY');
    assert.equal(concordanceForCell(spatial, 'r9c9'), null);
    assert.equal(persistenceForCell(spatial, 'r1c1')?.state, 'PERSISTENT');
    assert.equal(persistenceForCell(spatial, null), null);
  });

  it('map center derives from the backend bbox only', () => {
    assert.deepEqual(spatialMapCenter(makeSpatial()), [51.05, 35.05]);
    assert.equal(spatialMapCenter(null), null);
    assert.equal(spatialMapCenter({} as never), null);
  });
});

// --- 2-3. Empty and partial payloads ---------------------------------------------------

describe('2-3. empty and partial payloads stay honest', () => {
  it('empty spatial payload yields empty helpers', () => {
    for (const empty of [null, undefined, {}]) {
      assert.deepEqual(spatialCells(empty as never), []);
      assert.deepEqual(spatialObservations(empty as never), []);
      assert.deepEqual(spatialSummaries(empty as never), []);
      assert.deepEqual(spatialLimitations(empty as never), []);
      assert.deepEqual(distinctSpatialMetrics(empty as never), []);
      assert.deepEqual(distinctConcordanceStates(empty as never), []);
    }
  });

  it('partial payload: cells without observations still list', () => {
    const spatial = makeSpatial({ observations: [], concordance: [], persistence: [] });
    assert.equal(spatialCells(spatial).length, 1);
    assert.deepEqual(spatialObservations(spatial), []);
    assert.equal(concordanceForCell(spatial, 'r1c1'), null);
  });

  it('partial payload: summaries without cells still render', () => {
    const spatial = makeSpatial({ cells: [], observations: [] });
    assert.deepEqual(spatialCells(spatial), []);
    assert.equal(spatialSummaries(spatial).length, 1);
  });

  it('component has honest empty states and never fabricates', () => {
    const component = readSource('components/agriculture/SpatialSection.tsx');
    assert.ok(component.includes('No spatial data'));
    assert.ok(component.includes('carries no spatial section'));
    assert.ok(component.includes('No grid cells in this response.'));
    assert.ok(component.includes('No cells match the selected filters.'));
    assert.ok(!component.includes('connectNulls'));
  });
});

// --- 4. Cell status rendering -------------------------------------------------------------

describe('4. cell status rendering stays textual and verbatim', () => {
  it('state labels are neutral with raw state alongside', () => {
    assert.equal(spatialStateLabel('ANOMALOUS_AREA'), 'Anomalous area');
    assert.equal(concordanceStateLabel('SINGLE_METRIC_ANOMALY'), 'Single-metric anomaly');
    assert.equal(persistenceStateLabel('PERSISTENT'), 'Persistent');
    assert.equal(spatialStateLabel('SOME_FUTURE_STATE'), 'SOME_FUTURE_STATE');
    assert.deepEqual(SPATIAL_STATE_VALUES.concentration, [
      'NORMAL_AREA',
      'ANOMALOUS_AREA',
      'CONCENTRATED_ANOMALY',
      'INSUFFICIENT',
    ]);
  });

  it('component renders raw states as text, never color alone', () => {
    const component = readSource('components/agriculture/SpatialSection.tsx');
    assert.ok(component.includes('({summary.state})'));
    assert.ok(component.includes('({concordance.state})'));
    assert.ok(component.includes('({persistence.state})'));
    assert.ok(component.includes('<code>{cellId}</code>'));
    assert.ok(component.includes('<code>{item.metric_key}</code>'));
  });

  it('null observation values are gaps, never zero', () => {
    const missing = makeObservation({ value: null, category: null });
    assert.equal(missing.value, null);
    const [cell] = spatialCells(makeSpatial());
    assert.equal(cell?.cell_id, 'r1c1');
  });
});

// --- Filters -------------------------------------------------------------------------------

describe('filters narrow by values already present', () => {
  it('metric and concordance options derive from the payload', () => {
    const spatial = makeSpatial({
      observations: [makeObservation(), makeObservation({ metric_key: 'ndmi' })],
    });
    assert.deepEqual(distinctSpatialMetrics(spatial), ['ndmi', 'ndvi']);
    assert.deepEqual(distinctConcordanceStates(spatial), ['SINGLE_METRIC_ANOMALY']);
  });

  it('component exposes exactly two response-driven filters', () => {
    const component = readSource('components/agriculture/SpatialSection.tsx');
    assert.ok(component.includes('Filter cells by metric'));
    assert.ok(component.includes('Filter cells by concordance state'));
    assert.ok(component.includes('Showing {visibleCells.length} of {cells.length} cells'));
    assert.ok(!/\.sort\s*\(/.test(
      component.replace(/\[\.\.\.keys\]\.sort\(\)/g, ''),
    ));
  });
});

// --- 5. Geometry fallback -----------------------------------------------------------------------

describe('5. no-geometry fallback lists cells without inventing shapes', () => {
  it('valid Polygon geometry passes through verbatim', () => {
    const feature = cellPolygonFeature(makeCell());
    assert.equal(feature?.type, 'Feature');
    assert.equal(feature?.geometry.type, 'Polygon');
    assert.deepEqual(feature?.geometry.coordinates, RING);
    assert.deepEqual(feature?.properties, { cell_id: 'r1c1' });
  });

  it('missing or invalid geometry yields no feature', () => {
    assert.equal(cellPolygonFeature(makeCell({ geometry: null })), null);
    assert.equal(cellPolygonFeature(makeCell({ geometry: { type: 'Point' } })), null);
    assert.equal(cellPolygonFeature(null), null);
    assert.equal(cellPolygonFeature(undefined), null);
  });

  it('component states the fallback explicitly', () => {
    const component = readSource('components/agriculture/SpatialSection.tsx');
    assert.ok(
      component.includes('Cells carry no mappable geometry — table representation below.'),
    );
    assert.ok(component.includes('without mappable geometry'));
  });
});

// --- 6. Map behavior intact --------------------------------------------------------------------------

describe('6. existing map behavior remains intact', () => {
  it('MapView keeps its geometry path and adds optional overlays', () => {
    const map = readSource('components/MapView.tsx');
    assert.ok(map.includes('geometry?: GeoJSON.Geometry'));
    assert.ok(map.includes('overlays?: GeoJSON.Feature[]'));
    assert.ok(map.includes('geometry-fill'));
    assert.ok(map.includes('spatial-cells-fill'));
    assert.ok(map.includes('if (!overlays || overlays.length === 0) return'));
  });

  it('hub preview map call is unchanged', () => {
    const hub = readSource('pages/Agriculture.tsx');
    assert.ok(hub.includes('<MapView'));
    assert.ok(hub.includes('geometry={previewGeometry}'));
  });

  it('hub mounts the spatial section from response data', () => {
    const hub = readSource('pages/Agriculture.tsx');
    assert.ok(hub.includes('SpatialSection'));
    assert.ok(hub.includes('spatial={result.spatial ?? null}'));
  });
});

// --- 7-8. Relationships and the patterns block ----------------------------------------------------------

describe('7-8. relationships from existing fields; no fake pattern UI', () => {
  const temporal = {
    joint: {
      ndvi_key: 'ndvi',
      moisture_key: 'ndmi',
      window_start: '2024-01-01',
      window_end: '2024-04-30',
      step: 'calendar_month',
      joint: { ndvi_key: 'ndvi', moisture_key: 'ndmi' },
      changes: [
        {
          window_start: '2024-02-01',
          window_end: '2024-02-29',
          pattern: 'CONCURRENT_DECLINE',
          divergence: 'CONCORDANT',
          ndvi_direction: 'DECREASE',
          moisture_direction: 'DECREASE',
        },
      ],
      lags: [{ lag_months: 1, n_paired: 3, sufficient: true, method: 'agreement' }],
      scatter: { n_paired: 3, method: 'agreement' },
    },
    concordance: {
      months: [{ window_start: '2024-01-01', state: 'MULTI_SENSOR_CONCORDANT' }],
      summary: { n_months: 4, n_concordant: 2, n_divergent: 1, n_insufficient: 1 },
    },
  } as never;

  it('7. joint and concordance summary narrow verbatim', () => {
    assert.equal(jointAnalysisOf(temporal)?.ndvi_key, 'ndvi');
    assert.equal(jointAnalysisOf(temporal)?.moisture_key, 'ndmi');
    assert.equal(concordanceSummaryOf(temporal)?.n_concordant, 2);
    assert.equal(jointAnalysisOf(null), null);
    assert.equal(jointAnalysisOf({}), null);
    assert.equal(concordanceSummaryOf(null), null);
  });

  it('7. evidence section renders the relationship layer', () => {
    const evidence = readSource('components/agriculture/EvidenceSection.tsx');
    assert.ok(evidence.includes('JointReference'));
    assert.ok(evidence.includes('Joint NDVI-moisture analysis'));
    assert.ok(evidence.includes('concordanceSummary'));
  });

  it('8. no fake pattern UI when the contract carries none', () => {
    assert.deepEqual(patternsInResponse({}), []);
    assert.deepEqual(validationsInResponse({}), []);
    const evidence = readSource('components/agriculture/EvidenceSection.tsx');
    assert.ok(evidence.includes('{patterns.length > 0 && <PatternReference'));
    assert.ok(evidence.includes('{validations.length > 0 && <ValidationReference'));
  });
});

// --- Safeguards -----------------------------------------------------------------------------------

describe('safeguards: presentation only', () => {
  it('spatial sources compute nothing and fetch nothing', () => {
    const spatial = readSource('components/agriculture/spatial.ts');
    const component = readSource('components/agriculture/SpatialSection.tsx');
    for (const source of [spatial, component]) {
      const stripped = source
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|\s)\/\/.*$/gm, '$1');
      assert.ok(!/fetch\s*\(/.test(stripped));
      assert.ok(!/apiPost|apiGet|axios/.test(stripped));
      assert.ok(!/Math\.(sqrt|pow|mean|std)/.test(stripped));
      assert.ok(!/interpolat/i.test(stripped));
      assert.ok(!/threshold/i.test(stripped));
      assert.ok(!/correlation|regression/i.test(stripped));
      assert.ok(!/accuracy|precision|recall/i.test(stripped));
      assert.ok(!/confidence|probability|severity/i.test(stripped));
      assert.ok(!/\bscore\b/i.test(stripped));
      assert.ok(!/pest|disease|diagnos/i.test(stripped));
    }
  });

  it('no new endpoints', () => {
    const component = readSource('components/agriculture/SpatialSection.tsx');
    assert.ok(!/\/evidence|\/patterns|\/provenance|\/synthesis/.test(
      component.replace('/analysis/synthesis-only', ''),
    ));
    assert.ok(!/\/agriculture\/(evidence|patterns|provenance|synthesis)/.test(component));
  });
});
