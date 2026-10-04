/**
 * Navigation + ground-truth request integration tests.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/nav-groundtruth.test.ts
 * Covers: all 10 domain routes registered and linked from the hub,
 * no dangling links, shared-analysis intact (no new API calls),
 * optional ground_truth request shaping, and draft validation.
 * Static guards read sources; no network.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  DOMAIN_PAGE_CONFIGS,
  routePathForDomain,
} from '../domainPages.ts';
import {
  blankGroundTruthDraft,
  buildAgricultureRequest,
  toGroundTruthRecord,
  validateGroundTruthDraft,
} from '../request.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const EXPECTED_ROUTES = [
  '/agriculture/vegetation',
  '/agriculture/phenology',
  '/agriculture/climate',
  '/agriculture/water',
  '/agriculture/soil',
  '/agriculture/thermal',
  '/agriculture/terrain',
  '/agriculture/land-crop',
  '/agriculture/stress-irrigation',
  '/agriculture/history',
];

const BASE_GEOMETRY = { type: 'Point', coordinates: [53.688, 32.4279] } as const;

function baseInputs(overrides: Record<string, unknown> = {}) {
  return {
    geometry: BASE_GEOMETRY,
    start_date: '2025-06-01',
    end_date: '2025-09-01',
    selectedDomains: [],
    cloud_max_percent: 20,
    ...overrides,
  } as Parameters<typeof buildAgricultureRequest>[0];
}

function validDraft(overrides: Record<string, unknown> = {}) {
  return {
    ...blankGroundTruthDraft(),
    variable: 'observed_stress',
    value: 2.0,
    observed_on: '2025-07-15',
    source: 'field_observation',
    method: 'visual inspection',
    ...overrides,
  };
}

// --- Navigation --------------------------------------------------------------

describe('domain navigation', () => {
  it('all 10 domain routes are registered in App', () => {
    const app = readSource('App.tsx');
    for (const route of EXPECTED_ROUTES) {
      const short = route.replace('/agriculture/', '');
      assert.ok(
        app.includes(`path="${short}"`),
        `App.tsx missing route path="${short}"`,
      );
    }
  });

  it('every config routePath matches a registered route', () => {
    const app = readSource('App.tsx');
    for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
      const short = config.routePath.replace('/agriculture/', '');
      assert.ok(app.includes(`path="${short}"`), config.routePath);
    }
    assert.equal(Object.keys(DOMAIN_PAGE_CONFIGS).length, 10);
  });

  it('hub renders domain navigation cards', () => {
    const hub = readSource('pages/Agriculture.tsx');
    assert.ok(hub.includes('DomainNavCards'));
    assert.ok(hub.includes('<DomainNavCards'));
  });

  it('nav cards link to all configured routes', () => {
    const nav = readSource('components/agriculture/DomainNavCards.tsx');
    assert.ok(nav.includes('DOMAIN_PAGE_CONFIGS'));
    assert.ok(nav.includes('to={config.routePath}'));
    assert.ok(nav.includes('<Link'));
    // Every configured routePath must be a registered route.
    const app = readSource('App.tsx');
    for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
      const short = config.routePath.replace('/agriculture/', '');
      assert.ok(app.includes(`path="${short}"`), config.routePath);
    }
  });

  it('no link points to a nonexistent route', () => {
    const app = readSource('App.tsx');
    const known = new Set([...EXPECTED_ROUTES, '/agriculture']);
    for (const file of [
      'components/agriculture/DomainNavCards.tsx',
      'components/agriculture/DomainSummaryBlock.tsx',
    ]) {
      const source = readSource(file);
      for (const match of source.matchAll(/to=\{?["'`]([^"'`}]+)["'`]/g)) {
        const target = match[1];
        if (target.startsWith('/agriculture')) {
          assert.ok(known.has(target), `${file} links to unknown ${target}`);
        }
      }
    }
  });

  it('routePathForDomain resolves every configured bundle key', () => {
    const bundleKeys = new Set<string>();
    for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
      for (const key of config.bundleKeys) bundleKeys.add(key);
    }
    assert.ok(bundleKeys.size > 0);
    for (const key of bundleKeys) {
      const route = routePathForDomain(key);
      assert.ok(route, `no route for bundle ${key}`);
      assert.ok((EXPECTED_ROUTES as string[]).includes(route as string));
    }
    assert.equal(routePathForDomain('no_such_domain'), null);
  });

  it('summary blocks link to details only where a page exists', () => {
    const block = readSource('components/agriculture/DomainSummaryBlock.tsx');
    assert.ok(block.includes('routePathForDomain'));
    assert.ok(block.includes('View details'));
  });

  it('navigation adds no separate API calls (shared analysis intact)', () => {
    for (const file of [
      'components/agriculture/DomainNavCards.tsx',
      'components/agriculture/DomainSummaryBlock.tsx',
      'pages/Agriculture.tsx',
    ]) {
      const source = readSource(file);
      assert.ok(!source.includes('agricultureApi.analyze'), file);
      assert.ok(!source.includes('apiPost('), file);
      assert.ok(!source.includes('fetch('), file);
    }
  });
});

// --- Ground-truth request shaping ---------------------------------------------

describe('ground_truth request shaping', () => {
  it('omitted when absent (existing behavior unchanged)', () => {
    const request = buildAgricultureRequest(baseInputs());
    assert.ok(!('ground_truth' in request));
    assert.deepEqual(Object.keys(request).sort(), [
      'cloud_max_percent',
      'end_date',
      'geometry',
      'start_date',
    ]);
  });

  it('omitted when empty list supplied', () => {
    const request = buildAgricultureRequest(baseInputs({ groundTruth: [] }));
    assert.ok(!('ground_truth' in request));
  });

  it('included when records supplied', () => {
    const record = toGroundTruthRecord(validDraft(), 'ref-1');
    const request = buildAgricultureRequest(baseInputs({ groundTruth: [record] }));
    assert.deepEqual(request.ground_truth, [record]);
  });

  it('draft validation accepts a complete draft', () => {
    assert.equal(validateGroundTruthDraft(validDraft()), null);
  });

  it('draft validation accepts state-only drafts', () => {
    assert.equal(
      validateGroundTruthDraft(validDraft({ value: null, state: 'present' })),
      null,
    );
  });

  it('draft validation rejects incomplete drafts', () => {
    assert.ok(validateGroundTruthDraft(validDraft({ variable: 'nope' })));
    assert.ok(validateGroundTruthDraft(validDraft({ value: null, state: null })));
    assert.ok(
      validateGroundTruthDraft(validDraft({ value: null, state: 'severe' })),
    );
    assert.ok(validateGroundTruthDraft(validDraft({ observed_on: '' })));
    assert.ok(validateGroundTruthDraft(validDraft({ observed_on: '15-07-2025' })));
    assert.ok(validateGroundTruthDraft(validDraft({ source: 'word_of_mouth' })));
    assert.ok(validateGroundTruthDraft(validDraft({ method: '  ' })));
  });

  it('record normalization uses fallback id and drops empties', () => {
    const record = toGroundTruthRecord(
      validDraft({ observation_id: '', metric_key: '', cell_id: '' }),
      'ref-3',
    );
    assert.equal(record.observation_id, 'ref-3');
    assert.ok(!('metric_key' in record));
    assert.ok(!('cell_id' in record));
    assert.equal(record.value, 2.0);
  });

  it('form wires the optional section into the request', () => {
    const form = readSource('components/agriculture/AnalysisRequestForm.tsx');
    assert.ok(form.includes('Ground Truth'));
    assert.ok(form.includes('groundTruth: gtRecords'));
    assert.ok(form.includes('validateGroundTruthDraft'));
    assert.ok(form.includes('toGroundTruthRecord'));
    assert.ok(form.includes('Only needed for reference validation'));
  });

  it('request type mirrors the backend ground_truth field', () => {
    const types = readSource('types/index.ts');
    assert.ok(types.includes('ground_truth?: GroundTruthObservationInput[] | null'));
    for (const field of [
      'observation_id', 'variable', 'observed_on', 'source', 'method',
      'metric_key', 'cell_id', 'window_start', 'window_end',
    ]) {
      assert.ok(types.includes(field), field);
    }
  });

  it('validation section still receives the real response', () => {
    const hub = readSource('pages/Agriculture.tsx');
    assert.ok(hub.includes('result.validation'));
    assert.ok(hub.includes('<ValidationSection'));
  });
});
