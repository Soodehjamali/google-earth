/**
 * P0 legacy-consolidation tests — soil config completeness and legacy
 * deprecation links.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p0-consolidation.test.ts
 * Covers: the three registered soil metric keys in the Soil domain
 * config, safe numeric/categorical rendering paths, correct
 * deprecation targets with no redirects, intact legacy API calls,
 * a fully functional Historical page, and no verdict language.
 * Static guards read sources; no network.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import { findEvidenceItem, formatEvidenceValue, shouldRenderKpi } from '../parse.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const SOIL_KEYS = ['soil_organic_carbon', 'soil_texture_class', 'soil_ph'];

function soilMetricKeys(): string[] {
  const config = DOMAIN_PAGE_CONFIGS.soil;
  assert.ok(config, 'soil page config exists');
  return config.sections.flatMap((section) => section.metricKeys);
}

function makeItem(overrides: Record<string, unknown> = {}) {
  return {
    metric_key: 'soil_ph',
    value: null,
    unit: 'pH',
    status: 'unavailable',
    quality: 'unavailable',
    source_dataset: null,
    display_name: 'Soil pH (not produced)',
    ...overrides,
  } as never;
}

function makeBundles(items: unknown[]) {
  return { soil: { name: 'soil', items } } as never;
}

// --- 1. Soil config contains all three metric keys ----------------------------------

describe('1. soil config completeness', () => {
  it('soil config contains all three registered keys exactly', () => {
    const keys = soilMetricKeys();
    for (const key of SOIL_KEYS) {
      assert.ok(keys.includes(key), `soil config missing ${key}`);
    }
  });

  it('keys use existing conventions (no aliases, kpi sections)', () => {
    const config = DOMAIN_PAGE_CONFIGS.soil;
    const sections = config.sections.filter((section) =>
      section.metricKeys.some((key) => (SOIL_KEYS as string[]).includes(key)),
    );
    assert.ok(sections.length > 0);
    for (const section of sections) {
      assert.equal(section.kind, 'kpi');
    }
  });
});

// --- 2-3. Rendering paths -------------------------------------------------------------

describe('2-3. numeric and categorical soil metrics render safely', () => {
  it('soil page can render numeric soil metrics via the KPI path', () => {
    const bundles = makeBundles([
      makeItem({ metric_key: 'soil_ph', value: 7.0, status: 'observed', quality: 'good' }),
    ]);
    const found = findEvidenceItem(bundles, 'soil_ph');
    assert.ok(found);
    assert.equal(shouldRenderKpi(found.item), true);
  });

  it('unavailable soil metrics render textually, never as zero', () => {
    const bundles = makeBundles([makeItem()]);
    const found = findEvidenceItem(bundles, 'soil_ph');
    assert.ok(found);
    assert.equal(shouldRenderKpi(found.item), false);
    assert.equal(formatEvidenceValue(found.item.value), '—');
  });

  it('categorical texture values are handled safely by the neutral renderer', () => {
    // Backend fixtures may carry a string class label; the numeric
    // guards must refuse it without crashing or fabricating a KPI.
    const bundles = makeBundles([
      makeItem({ metric_key: 'soil_texture_class', value: 'loam', status: 'observed' }),
    ]);
    const found = findEvidenceItem(bundles, 'soil_texture_class');
    assert.ok(found);
    assert.equal(shouldRenderKpi(found.item), false);
    assert.equal(formatEvidenceValue(found.item.value), '—');
    const card = readSource('components/agriculture/EvidenceDetailCard.tsx');
    assert.ok(card.includes('unavailable'));
  });

  it('no threshold coloring was added for the new metrics', () => {
    const config = readSource('components/agriculture/domainPages.ts');
    const notice = readSource('components/ComprehensiveNotice.tsx');
    for (const source of [config, notice]) {
      assert.ok(!/healthy|unhealthy/i.test(source));
      assert.ok(!/\bsafe\b|\bunsafe\b/i.test(source));
      assert.ok(!/good\/bad|bad\/good/i.test(source));
    }
  });
});

// --- 4-7. Deprecation links --------------------------------------------------------------

const LEGACY_TARGETS: Array<[string, string]> = [
  ['pages/Vegetation.tsx', '/agriculture/vegetation'],
  ['pages/Climate.tsx', '/agriculture/climate'],
  ['pages/Water.tsx', '/agriculture/water'],
  ['pages/Soil.tsx', '/agriculture/soil'],
  ['pages/LandCover.tsx', '/agriculture/land-crop'],
];

describe('4-7. legacy deprecation links without redirects', () => {
  it('comprehensive routes in deprecation links are correct', () => {
    const app = readSource('App.tsx');
    for (const [, target] of LEGACY_TARGETS) {
      const short = target.replace('/agriculture/', '');
      assert.ok(app.includes(`path="${short}"`), `route missing for ${target}`);
    }
    for (const [page, target] of LEGACY_TARGETS) {
      const source = readSource(page);
      assert.ok(source.includes('ComprehensiveNotice'), `${page} missing notice`);
      assert.ok(source.includes(`to="${target}"`), `${page} wrong target`);
    }
  });

  it('historical page remains fully functional with a neutral link', () => {
    const source = readSource('pages/Historical.tsx');
    assert.ok(source.includes('ComprehensiveNotice'));
    assert.ok(source.includes('to="/agriculture/history"'));
    assert.ok(source.includes('analysesApi.create'));
    assert.ok(source.includes('analysesApi.getTimeSeries'));
    assert.ok(source.includes('selectedYears'));
    assert.ok(!/منسوخ|deprecat/i.test(source));
  });

  it('no redirect was introduced on any touched legacy page', () => {
    for (const [page] of [...LEGACY_TARGETS, ['pages/Historical.tsx', '']]) {
      const source = readSource(page);
      assert.ok(!source.includes('<Navigate'), page);
      assert.ok(!/window\.location\s*=/.test(source), page);
      assert.ok(!/navigate\(['"`]\/agriculture/.test(source), page);
    }
  });

  it('no legacy API call was removed', () => {
    const expectations: Array<[string, string[]]> = [
      ['pages/Vegetation.tsx', ['analysesApi.create', 'analysesApi.getMaps', 'analysesApi.getTimeSeries']],
      ['pages/Climate.tsx', ['analysesApi.create', 'analysesApi.getMaps', 'analysesApi.getTimeSeries']],
      ['pages/Water.tsx', ['analysesApi.create', 'analysesApi.getMaps']],
      ['pages/Soil.tsx', ['analysesApi.create', 'analysesApi.getMaps']],
      ['pages/LandCover.tsx', ['analysesApi.create', 'analysesApi.getMaps']],
      ['pages/Historical.tsx', ['analysesApi.create', 'analysesApi.getTimeSeries']],
    ];
    for (const [page, calls] of expectations) {
      const source = readSource(page);
      for (const call of calls) {
        assert.ok(source.includes(call), `${page} missing ${call}`);
      }
    }
  });
});

// --- 8. Verdict fields stay legacy-only -------------------------------------------------------

describe('8. verdict fields remain intentionally absent', () => {
  it('no comprehensive diagnostic verdict was added', () => {
    const domainPages = readSource('components/agriculture/domainPages.ts');
    assert.ok(!domainPages.includes('vegetation_health'));
    assert.ok(!domainPages.includes('stress_level'));
    const notice = readSource('components/ComprehensiveNotice.tsx');
    assert.ok(!/health|diagnos|verdict|risk|score/i.test(notice));
  });
});
