/**
 * F1 focused tests — Comprehensive Agriculture Hub & shared architecture.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/f1.test.ts
 * Covers F1 §23 items 1–12 using pure helpers + static source guards.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  API_DOMAINS,
  DOMAIN_ROUTE_PAYLOADS,
  buildAgricultureRequest,
  clampCloudPercent,
  normalizeSelectedDomains,
  parseGeoJsonInput,
  parseGpsInput,
  validateAnalysisInputs,
} from '../request.ts';
import {
  formatEvidenceValue,
  getProvenanceRows,
  isFiniteNumber,
  normalizeHealth,
  normalizeResponse,
  patternMetaFor,
  qualityToKpiStatus,
  shouldRenderKpi,
  sufficiencyBadgeClass,
} from '../parse.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

function listAgricultureSources(): string[] {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        if (entry === '__tests__') continue;
        walk(full);
      } else if (/\.(ts|tsx)$/.test(entry)) {
        files.push(full);
      }
    }
  };
  walk(agricultureDir);
  return files;
}

const POINT: { type: 'Point'; coordinates: number[] } = {
  type: 'Point',
  coordinates: [53.688, 32.4279],
};

// --- 1. Hub calls the Comprehensive endpoint --------------------------------

describe('1. hub calls POST /api/v1/agriculture/analysis', () => {
  it('AgricultureLayout runs analysis through agricultureApi.analyze', () => {
    const layout = readFileSync(join(agricultureDir, 'AgricultureLayout.tsx'), 'utf-8');
    assert.ok(layout.includes('agricultureApi.analyze'));
    assert.ok(layout.includes('normalizeResponse'));
  });

  it('hub page consumes the parent-owned context', () => {
    const hub = readSource('pages/Agriculture.tsx');
    assert.ok(hub.includes('useAgricultureContext'));
    assert.ok(hub.includes('runAnalysis'));
  });
});

// --- 2. Never Legacy ----------------------------------------------------------

describe('2. hub never calls Legacy analysis creation', () => {
  it('no Legacy client usage in shared agriculture components or hub', () => {
    const files = [...listAgricultureSources(), join(srcDir, 'pages/Agriculture.tsx')];
    const forbidden = [
      'analysesApi.create',
      'analysesApi.getMaps',
      'analysesApi.getTimeSeries',
      'analysesApi.list',
      'analysesApi.get(',
      'vegetationApi.',
      'locationsApi.',
      "apiPost('/analyses'",
      'apiPost("/analyses"',
    ];
    for (const file of files) {
      const text = readFileSync(file, 'utf-8');
      for (const token of forbidden) {
        assert.ok(!text.includes(token), `${file} contains Legacy ${token}`);
      }
    }
  });
});

// --- 3. All-domains omits domains ----------------------------------------------

describe('3. default/all-domain request never sends domains=[]', () => {
  it('all domains selected → domains omitted', () => {
    const req = buildAgricultureRequest({
      geometry: { ...POINT },
      start_date: '2025-06-01',
      end_date: '2025-09-01',
      selectedDomains: [...API_DOMAINS],
      cloud_max_percent: 20,
    });
    assert.ok(!('domains' in req), 'must omit domains when all selected');
  });

  it('empty selection → domains omitted (never [])', () => {
    const req = buildAgricultureRequest({
      geometry: { ...POINT },
      start_date: '2025-06-01',
      end_date: '2025-09-01',
      selectedDomains: [],
      cloud_max_percent: 20,
    });
    assert.ok(!('domains' in req));
    assert.ok(!Array.isArray((req as { domains?: unknown }).domains));
  });
});

// --- 4. Explicit selection sends non-empty domains -------------------------------

describe('4. explicit domain selection sends a non-empty array', () => {
  it('single domain passes through', () => {
    const req = buildAgricultureRequest({
      geometry: { ...POINT },
      start_date: '2025-06-01',
      end_date: '2025-09-01',
      selectedDomains: ['vegetation'],
      cloud_max_percent: 20,
    });
    assert.deepEqual(req.domains, ['vegetation']);
  });

  it('unknown names are dropped; wrong-spelling history is rejected', () => {
    assert.deepEqual(normalizeSelectedDomains(['vegetation', 'nope']), ['vegetation']);
    assert.deepEqual(normalizeSelectedDomains(['history']), []);
  });

  it('history route payload uses the API spelling historical', () => {
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/history'], ['historical']);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/soil'], ['soil']);
  });
});

// --- 5. cloud_max_percent ---------------------------------------------------------

describe('5. cloud_max_percent is sent correctly', () => {
  it('defaults and clamps per backend contract', () => {
    assert.equal(clampCloudPercent(undefined), 20);
    assert.equal(clampCloudPercent('35'), 35);
    assert.equal(clampCloudPercent(150), 100);
    assert.equal(clampCloudPercent(-5), 0);
    assert.equal(clampCloudPercent(Number.NaN), 20);
  });

  it('request carries the clamped value', () => {
    const req = buildAgricultureRequest({
      geometry: { ...POINT },
      start_date: '2025-06-01',
      end_date: '2025-09-01',
      selectedDomains: ['soil'],
      cloud_max_percent: '12.5',
    });
    assert.equal(req.cloud_max_percent, 12.5);
  });
});

// --- geometry + validation helpers --------------------------------------------------

describe('request geometry parsing (existing mechanism, no new format)', () => {
  it('accepts valid GPS and rejects bad coordinates', () => {
    const ok = parseGpsInput('32.4279', '53.6880');
    assert.ok('geometry' in ok);
    assert.equal(parseGpsInput('abc', '53.6') && 'error' in parseGpsInput('abc', '53.6'), true);
    assert.ok('error' in parseGpsInput('200', '10'));
  });

  it('accepts Point/Polygon GeoJSON and rejects the rest', () => {
    assert.ok('geometry' in parseGeoJsonInput('{"type":"Point","coordinates":[1,2]}'));
    assert.ok('geometry' in parseGeoJsonInput('{"type":"Polygon","coordinates":[[[1,2],[3,4],[5,6],[1,2]]]}'));
    assert.ok('error' in parseGeoJsonInput('not json'));
    assert.ok('error' in parseGeoJsonInput('{"type":"LineString","coordinates":[[1,2]]}'));
  });

  it('validates the date range', () => {
    assert.equal(validateAnalysisInputs({ ...POINT }, '2025-06-01', '2025-09-01'), null);
    assert.ok(validateAnalysisInputs(undefined, '2025-06-01', '2025-09-01') !== null);
    assert.ok(validateAnalysisInputs({ ...POINT }, '2025-09-01', '2025-06-01') !== null);
  });
});

// --- 6. Null renders safely ------------------------------------------------------------

describe('6. null metric value renders safely (never zero)', () => {
  it('non-finite values become the unavailable marker', () => {
    for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, 'x']) {
      assert.equal(formatEvidenceValue(bad), '—');
      assert.equal(isFiniteNumber(bad), false);
    }
  });

  it('zero is a real value and renders', () => {
    assert.equal(isFiniteNumber(0), true);
    assert.equal(formatEvidenceValue(0), '0.0000');
    assert.equal(formatEvidenceValue(1.234567), '1.2346');
  });
});

// --- 7. Unavailable never becomes a KPI -----------------------------------------------------

describe('7. unavailable evidence does not render as KPI', () => {
  it('unavailable status or null value → no KPI', () => {
    assert.equal(shouldRenderKpi({ value: 1.2, status: 'unavailable' }), false);
    assert.equal(shouldRenderKpi({ value: null, status: 'derived' }), false);
    assert.equal(shouldRenderKpi({ value: undefined, status: 'observed' }), false);
    assert.equal(shouldRenderKpi(null), false);
  });

  it('finite usable value → KPI allowed', () => {
    assert.equal(shouldRenderKpi({ value: 0.62, status: 'derived' }), true);
    assert.equal(shouldRenderKpi({ value: 0, status: 'observed' }), true);
  });

  it('quality maps to existing tones without inventing scores', () => {
    assert.equal(qualityToKpiStatus('good'), 'good');
    assert.equal(qualityToKpiStatus('moderate'), 'warning');
    assert.equal(qualityToKpiStatus('poor'), 'danger');
    assert.equal(qualityToKpiStatus('mystery'), 'neutral');
    assert.equal(sufficiencyBadgeClass('sufficient'), 'badge-good');
    assert.equal(sufficiencyBadgeClass('limited'), 'badge-warning');
    assert.equal(sufficiencyBadgeClass('whatever'), 'badge-danger');
  });
});

// --- 8. Missing provenance ---------------------------------------------------------------------

describe('8. missing provenance renders safely', () => {
  it('null/undefined provenance yields no rows', () => {
    assert.deepEqual(getProvenanceRows(null), []);
    assert.deepEqual(getProvenanceRows(undefined), []);
  });

  it('only present fields become rows', () => {
    const rows = getProvenanceRows({
      source_dataset_id: 'COPERNICUS/S2_SR_HARMONIZED',
      source_dataset_name: '',
      bands: [],
      formula: '',
      unit: 'index',
      spatial_resolution: '10m',
      temporal_resolution: '',
      aggregation_method: '',
      measurement_basis: 'derived',
      quality_level: 'good',
      temporal_kind: 'observation',
      limitations: [],
      caveats: [],
      citation: '',
    });
    const keys = rows.map((row) => row.key);
    assert.ok(keys.includes('source_dataset_id'));
    assert.ok(!keys.includes('formula'));
    assert.ok(!keys.includes('citation'));
  });
});

// --- 9. Missing synthesis ----------------------------------------------------------------------------

describe('9. missing synthesis renders safely', () => {
  it('non-object payloads normalize to null', () => {
    assert.equal(normalizeResponse(null), null);
    assert.equal(normalizeResponse('oops'), null);
    assert.equal(normalizeResponse([1, 2]), null);
  });

  it('missing collections default to safe empties', () => {
    const normalized = normalizeResponse({ overall_sufficiency: 'limited' });
    assert.ok(normalized !== null);
    assert.deepEqual(normalized?.domain_summaries, {});
    assert.deepEqual(normalized?.evidence_bundles, {});
    assert.deepEqual(normalized?.available_domains, []);
    assert.deepEqual(normalized?.cross_domain_statements, []);
    assert.deepEqual(normalized?.limitations, []);
  });
});

// --- 10. Unknown pattern -------------------------------------------------------------------------------

describe('10. unknown pattern falls back safely', () => {
  it('falls back instead of crashing or redesigning metadata', () => {
    const meta = patternMetaFor('some_future_state');
    assert.ok(typeof meta.color === 'string' && meta.color.length > 0);
    assert.ok(typeof meta.labelFa === 'string');
  });
});

// --- 11. Health ----------------------------------------------------------------------------------------------

describe('11. health response renders safely', () => {
  it('null payload → null; partial payload → defaults', () => {
    assert.equal(normalizeHealth(null), null);
    const partial = normalizeHealth({ status: 'degraded' });
    assert.equal(partial?.metrics_registered, 0);
    assert.equal(partial?.evidence_layer, 'unknown');
    assert.equal(partial?.message, '');
  });

  it('full payload passes through', () => {
    const full = normalizeHealth({
      status: 'ok',
      metrics_registered: 109,
      evidence_layer: 'available',
      synthesis_layer: 'available',
      message: 'all good',
    });
    assert.equal(full?.metrics_registered, 109);
    assert.equal(full?.status, 'ok');
  });
});

// --- 12. No fabricated visualizations --------------------------------------------------------------------------

describe('12. no fake time-series/histogram data is generated', () => {
  it('shared agriculture sources contain no series/distribution fabrication', () => {
    const files = listAgricultureSources();
    assert.ok(files.length > 0);
    // F3-B allow-list: these modules truthfully consume the F3-A
    // structured fields through the explicit semantic maps in
    // evidenceDetails.ts. Every other agriculture source must stay
    // free of distribution tokens.
    const F3B_STRUCTURED_FILES = new Set([
      'evidenceDetails.ts',
      'StructuredDetails.tsx',
      'ClassHistogramDetail.tsx',
      'DynamicWorldBands.tsx',
      'EvidenceDetailCard.tsx',
    ]);
    // P5.2 allow-list: the temporal chart renderer imports the
    // chart library to plot backend monthly observations. Every
    // other agriculture source stays free of chart tokens.
    // P1 consolidation allow-list: the year-over-year comparison
    // overlays backend monthly NDVI points with the same library.
    const P52_CHART_FILES = new Set(['TemporalLineChart.tsx']);
    const P1_CHART_FILES = new Set(['YearComparisonSection.tsx']);
    const STRUCTURAL_TOKENS = ['class_histogram', 'ClassHistogram'];
    const forbiddenEverywhere = [
      'recharts',
      'TimeSeries',
      'time_series',
      'new Array(',
      'as any',
      'as unknown as',
    ];
    for (const file of files) {
      const text = readFileSync(file, 'utf-8');
      const base = file.split(/[\\/]/).pop() ?? file;
      for (const token of forbiddenEverywhere) {
        if (token === 'recharts' && P52_CHART_FILES.has(base)) continue;
        if (token === 'recharts' && P1_CHART_FILES.has(base)) continue;
        assert.ok(!text.includes(token), `${file} contains forbidden ${token}`);
      }
      if (!F3B_STRUCTURED_FILES.has(base)) {
        for (const token of STRUCTURAL_TOKENS) {
          assert.ok(!text.includes(token), `${file} contains forbidden ${token}`);
        }
      }
    }
  });

  it('the F3-B allow-list stays minimal and exact', () => {
    const files = listAgricultureSources();
    const bases = new Set(files.map((file) => file.split(/[\\/]/).pop() ?? file));
    for (const expected of [
      'evidenceDetails.ts',
      'StructuredDetails.tsx',
      'ClassHistogramDetail.tsx',
      'DynamicWorldBands.tsx',
      'EvidenceDetailCard.tsx',
    ]) {
      assert.ok(bases.has(expected), `F3-B module missing: ${expected}`);
    }
  });

  it('the guard still catches structural tokens outside the allow-list', () => {
    const STRUCTURAL_TOKENS = ['class_histogram', 'ClassHistogram'];
    const F3B_STRUCTURED_FILES = new Set([
      'evidenceDetails.ts',
      'StructuredDetails.tsx',
      'ClassHistogramDetail.tsx',
      'DynamicWorldBands.tsx',
      'EvidenceDetailCard.tsx',
    ]);
    const violates = (base: string, text: string): boolean =>
      !F3B_STRUCTURED_FILES.has(base) &&
      STRUCTURAL_TOKENS.some((token) => text.includes(token));
    assert.equal(violates('MetricKpiGrid.tsx', 'item.class_histogram'), true);
    assert.equal(violates('StructuredDetails.tsx', 'item.class_histogram'), false);
    assert.equal(violates('parse.ts', 'recharts'), false);
  });
});
