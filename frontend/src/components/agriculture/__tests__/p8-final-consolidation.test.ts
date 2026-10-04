/**
 * P8 focused tests — final legacy consolidation (all four approved routes).
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p8-final-consolidation.test.ts
 * Locks the P7-authorized migration: /vegetation, /climate, /water and
 * /landcover redirect (replace) to their Comprehensive destinations, the
 * sidebar points directly at Comprehensive routes with no legacy links,
 * all six legacy page files and analysesApi remain, /historical is HOLD
 * and unchanged, destination routes stay registered, and no forbidden
 * product-contract capability was recreated. Static guards read sources;
 * no network. Backend is read-only here (one constant guard).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = dirname(dirname(dirname(here)));
const repoDir = dirname(dirname(srcDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const MIGRATIONS: Array<[string, string]> = [
  ['/vegetation', '/agriculture/vegetation'],
  ['/climate', '/agriculture/climate'],
  ['/water', '/agriculture/water'],
  ['/landcover', '/agriculture/land-crop'],
  ['/soil', '/agriculture/soil'],
];

const LEGACY_PAGES = [
  'Vegetation',
  'Climate',
  'Water',
  'Soil',
  'LandCover',
  'Historical',
];

// --- 1. routing -----------------------------------------------------------------

describe('1. approved legacy URLs redirect to Comprehensive destinations', () => {
  for (const [legacy, target] of MIGRATIONS) {
    it(`${legacy} → ${target} (replace)`, () => {
      const app = readSource('App.tsx');
      const route =
        app.match(new RegExp(`<Route\\s+path="${legacy}"[\\s\\S]*?/>`))?.[0] ?? '';
      assert.ok(route, `route for ${legacy} is missing`);
      assert.ok(route.includes('<Navigate'), route);
      assert.ok(route.includes(`to="${target}"`), route);
      assert.ok(route.includes('replace'), route);
    });
  }

  it('no legacy page component is rendered directly anymore', () => {
    const app = readSource('App.tsx');
    for (const page of ['Vegetation', 'Climate', 'Water', 'LandCover']) {
      assert.ok(!app.includes(`<${page} />`), `${page} still rendered`);
      assert.ok(
        !app.includes(`from './pages/${page}'`),
        `stale ${page} import`,
      );
    }
  });

  it('all ten comprehensive destination routes stay registered', () => {
    const app = readSource('App.tsx');
    for (const pageKey of [
      'vegetation',
      'phenology',
      'climate',
      'water',
      'soil',
      'thermal',
      'terrain',
      'land-crop',
      'stress-irrigation',
      'history',
    ]) {
      assert.ok(
        app.includes(`<DomainPage pageKey="${pageKey}" />`),
        `missing destination for ${pageKey}`,
      );
    }
  });
});

// --- 2. navigation ---------------------------------------------------------------

describe('2. sidebar points directly at Comprehensive routes', () => {
  it('the five domain entries target comprehensive routes', () => {
    const layout = readSource('components/Layout.tsx');
    for (const target of [
      '/agriculture/vegetation',
      '/agriculture/climate',
      '/agriculture/water',
      '/agriculture/soil',
      '/agriculture/land-crop',
    ]) {
      assert.ok(layout.includes(`path: '${target}'`), `nav missing ${target}`);
    }
  });

  it('no primary-navigation link targets a legacy URL', () => {
    const layout = readSource('components/Layout.tsx');
    for (const legacy of [
      '/vegetation',
      '/climate',
      '/water',
      '/soil',
      '/landcover',
    ]) {
      assert.ok(
        !layout.includes(`path: '${legacy}'`),
        `legacy nav link still present: ${legacy}`,
      );
    }
  });

  it('unrelated navigation entries are unchanged', () => {
    const layout = readSource('components/Layout.tsx');
    for (const entry of [
      `{ path: '/', label: 'داشبورد'`,
      `{ path: '/location'`,
      `{ path: '/agriculture', label: 'تحلیل کشاورزی'`,
      `{ path: '/historical'`,
      `{ path: '/reports'`,
      `{ path: '/settings'`,
    ]) {
      assert.ok(layout.includes(entry), `nav entry changed: ${entry}`);
    }
  });
});

// --- 3. preservation -------------------------------------------------------------

describe('3. legacy sources and APIs are preserved', () => {
  it('all six legacy page files remain', () => {
    for (const page of LEGACY_PAGES) {
      const full = join(srcDir, `pages/${page}.tsx`);
      assert.ok(existsSync(full), `${page}.tsx deleted`);
    }
  });

  it('legacy pages keep their analysesApi calls and no redirect', () => {
    const expectations: Array<[string, string[]]> = [
      ['Vegetation', ['analysesApi.create', 'analysesApi.getMaps', 'analysesApi.getTimeSeries']],
      ['Climate', ['analysesApi.create', 'analysesApi.getMaps', 'analysesApi.getTimeSeries']],
      ['Water', ['analysesApi.create', 'analysesApi.getMaps']],
      ['LandCover', ['analysesApi.create', 'analysesApi.getMaps']],
      ['Historical', ['analysesApi.create', 'analysesApi.getTimeSeries']],
    ];
    for (const [page, calls] of expectations) {
      const source = readSource(`pages/${page}.tsx`);
      for (const call of calls) {
        assert.ok(source.includes(call), `${page} missing ${call}`);
      }
      assert.ok(!source.includes('<Navigate'), `${page} gained a redirect`);
    }
  });

  it('analysesApi remains exported with the legacy surface', () => {
    const api = readSource('api/analyses.ts');
    assert.ok(api.includes('export const analysesApi'));
    assert.ok(api.includes("'/analyses'"));
  });

  it('backend legacy routers remain (read-only guard)', () => {
    const router = readFileSync(
      join(repoDir, 'backend', 'app', 'api', 'router.py'),
      'utf-8',
    );
    for (const include of [
      'analyses.router',
      'maps.router',
      'timeseries.router',
    ]) {
      assert.ok(router.includes(include), `backend router lost ${include}`);
    }
  });
});

// --- 4. historical HOLD ----------------------------------------------------------

describe('4. /historical is HOLD and untouched', () => {
  it('/historical still renders its page with no redirect', () => {
    const app = readSource('App.tsx');
    assert.ok(app.includes('<Historical />'), 'historical no longer rendered');
    assert.ok(
      !app.includes('path="/historical" element={<Navigate'),
      'historical was redirected',
    );
  });

  it('the Historical page keeps year chips, comparison, and summary', () => {
    const source = readSource('pages/Historical.tsx');
    assert.ok(source.includes('selectedYears'));
    assert.ok(source.includes('analysesApi.getTimeSeries'));
    assert.ok(source.includes('to="/agriculture/history"'));
  });

  it('the 36-month temporal bound is unchanged (read-only guard)', () => {
    const temporal = readFileSync(
      join(
        repoDir,
        'backend',
        'app',
        'services',
        'agriculture',
        'temporal_section.py',
      ),
      'utf-8',
    );
    assert.ok(temporal.includes('MAX_TEMPORAL_MONTHS = 36'));
  });
});

// --- 5. product contract ---------------------------------------------------------

describe('5. no forbidden capability was recreated by the migration', () => {
  it('the migration touches only routing and navigation files', () => {
    for (const file of ['App.tsx', 'components/Layout.tsx']) {
      const source = readSource(file);
      assert.ok(!source.includes('vegetation_health'), file);
      assert.ok(!source.includes('stress_level'), file);
      assert.ok(!source.includes('composite_stress'), file);
      assert.ok(!source.includes('interpretation'), file);
      assert.ok(!source.includes('valid_area_sq_m'), file);
    }
  });

  it('no precipitation temporal series was introduced', () => {
    const app = readSource('App.tsx');
    assert.ok(!app.toLowerCase().includes('precipitation'));
    const layout = readSource('components/Layout.tsx');
    assert.ok(!layout.toLowerCase().includes('precipitation'));
  });

  it('the P4 climate + thermal routing fix is intact', () => {
    const request = readSource('components/agriculture/request.ts');
    assert.ok(request.includes("'/agriculture/climate': ['climate', 'thermal']"));
    const domainPages = readSource('components/agriculture/domainPages.ts');
    assert.ok(domainPages.includes("apiDomains: ['climate', 'thermal']"));
  });
});
