/**
 * P5 focused tests — /soil routing migration to Comprehensive.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p5.test.ts
 * Locks the routing-only migration: /soil redirects to
 * /agriculture/soil, the sidebar Soil entry targets the comprehensive
 * route, the legacy Soil page and analysesApi remain intact, and the
 * comprehensive soil configuration is unchanged. Static guards read
 * sources; no network.
 * NOTE (final consolidation): the sidebar order/content and the set of
 * Navigate targets are now locked by p8-final-consolidation.test.ts,
 * which covers all five migrated routes. The sidebar-paths and
 * Navigate-target assertions below were updated to that contract;
 * nothing else in this file changed meaning.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import { DOMAIN_ROUTE_PAYLOADS } from '../request.ts';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = dirname(dirname(dirname(here)));
const repoDir = dirname(dirname(srcDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const SOIL_TARGET = '/agriculture/soil';

// --- 1. /soil redirects to /agriculture/soil ----------------------------------------

describe('1. /soil navigates to /agriculture/soil', () => {
  it('the /soil route is a Navigate redirect to the comprehensive route', () => {
    const app = readSource('App.tsx');
    const route = app.match(/<Route\s+path="\/soil"[\s\S]*?\/>/)?.[0] ?? '';
    assert.ok(route, 'route for /soil is missing');
    assert.ok(route.includes('<Navigate'), route);
    assert.ok(route.includes(`to="${SOIL_TARGET}"`), route);
    assert.ok(route.includes('replace'), route);
  });

  it('the redirect uses the project router (react-router-dom + BrowserRouter)', () => {
    const app = readSource('App.tsx');
    assert.ok(
      app.includes(`import { Routes, Route, Navigate } from 'react-router-dom'`),
    );
    const main = readSource('main.tsx');
    assert.ok(main.includes('BrowserRouter'));
  });

  it('the legacy Soil page is no longer rendered directly', () => {
    const app = readSource('App.tsx');
    assert.ok(!app.includes('<Soil />'), 'legacy Soil still rendered');
    assert.ok(!app.includes("import Soil from './pages/Soil'"), 'stale Soil import');
  });

  it('the comprehensive soil route stays registered', () => {
    const app = readSource('App.tsx');
    assert.ok(
      app.includes(`<Route path="soil" element={<DomainPage pageKey="soil" />} />`),
    );
    assert.ok(app.includes('<AgricultureLayout />'));
  });
});

// --- 2. sidebar navigation -----------------------------------------------------------

describe('2. sidebar Soil entry targets the comprehensive route', () => {
  it('the Soil nav item points at /agriculture/soil', () => {
    const layout = readSource('components/Layout.tsx');
    assert.ok(layout.includes(`path: '${SOIL_TARGET}'`), 'soil nav path missing');
    assert.ok(layout.includes("labelEn: 'Soil'"));
  });

  it('the deprecated /soil sidebar entry is gone', () => {
    const layout = readSource('components/Layout.tsx');
    assert.ok(!layout.includes(`path: '/soil'`), 'legacy soil link still in sidebar');
  });

  it('every sidebar entry matches the final consolidated contract', () => {
    // Final consolidation (P7 authorized, P8 implemented): the five
    // domain entries point at Comprehensive routes; /historical stays.
    const layout = readSource('components/Layout.tsx');
    const paths = [...layout.matchAll(/path: '([^']+)'/g)].map((match) => match[1]);
    assert.deepEqual(paths, [
      '/',
      '/location',
      '/agriculture/vegetation',
      '/agriculture/climate',
      '/agriculture/water',
      SOIL_TARGET,
      '/agriculture/land-crop',
      '/agriculture',
      '/historical',
      '/reports',
      '/settings',
    ]);
  });

  it('sidebar navigation introduces no redirect or extra call', () => {
    const layout = readSource('components/Layout.tsx');
    assert.ok(!layout.includes('<Navigate'));
    assert.ok(!/window\.location/.test(layout));
    assert.ok(!layout.includes('apiPost'));
    assert.ok(!layout.includes('fetch('));
  });
});

// --- 3. redirect set matches the final consolidated contract -------------------------------
// Final consolidation: /vegetation, /climate, /water and /landcover join
// /soil as compatibility redirects. /historical is HOLD and keeps rendering.

const APPROVED_REDIRECTS: Array<[string, string]> = [
  ['/vegetation', '/agriculture/vegetation'],
  ['/climate', '/agriculture/climate'],
  ['/water', '/agriculture/water'],
  ['/soil', '/agriculture/soil'],
  ['/landcover', '/agriculture/land-crop'],
];

describe('3. redirect set matches the final consolidated contract', () => {
  it('every Navigate in App targets only an approved comprehensive route', () => {
    const app = readSource('App.tsx');
    const targets = [...app.matchAll(/<Navigate\s+to="([^"]+)"/g)].map(
      (match) => match[1],
    );
    assert.deepEqual(
      [...targets].sort(),
      APPROVED_REDIRECTS.map(([, target]) => target).sort(),
    );
  });

  it('all non-migrated routes still render their own pages', () => {
    const app = readSource('App.tsx');
    const expected: Array<[string, string]> = [
      ['/', '<Dashboard />'],
      ['/location', '<Location />'],
      ['/analysis/:id', '<Analysis />'],
      ['/historical', '<Historical />'],
      ['/reports', '<Reports />'],
      ['/settings', '<Settings />'],
    ];
    for (const [path, element] of expected) {
      assert.ok(
        app.includes(`<Route path="${path}" element={${element}} />`),
        `route ${path} no longer renders ${element}`,
      );
    }
  });

  it('each approved legacy path is a replace redirect to its destination', () => {
    const app = readSource('App.tsx');
    for (const [legacy, target] of APPROVED_REDIRECTS) {
      const route = app.match(
        new RegExp(`<Route\\s+path="${legacy}"[\\s\\S]*?/>`),
      )?.[0] ?? '';
      assert.ok(route, `route for ${legacy} is missing`);
      assert.ok(route.includes('<Navigate'), route);
      assert.ok(route.includes(`to="${target}"`), route);
      assert.ok(route.includes('replace'), route);
    }
  });

  it('the registered route set is unchanged', () => {
    const app = readSource('App.tsx');
    const paths = [...app.matchAll(/path="([^"]+)"/g)].map((match) => match[1]);
    assert.deepEqual(paths, [
      '/',
      '/location',
      '/analysis/:id',
      '/vegetation',
      '/climate',
      '/water',
      '/soil',
      '/landcover',
      '/agriculture',
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
      '/historical',
      '/reports',
      '/settings',
    ]);
  });

  it('no page-level redirect was added anywhere else', () => {
    const notice = readSource('components/ComprehensiveNotice.tsx');
    assert.ok(!notice.includes('<Navigate'));
    for (const page of ['Vegetation', 'Climate', 'Water', 'LandCover', 'Historical']) {
      const source = readSource(`pages/${page}.tsx`);
      assert.ok(!source.includes('<Navigate'), page);
      assert.ok(!/window\.location\s*=/.test(source), page);
    }
  });
});

// --- 4. legacy API stays available ---------------------------------------------------------

describe('4. analysesApi remains available to legacy consumers', () => {
  it('analysesApi still exposes the legacy endpoints', () => {
    const api = readSource('api/analyses.ts');
    for (const fragment of [
      'export const analysesApi',
      "'/analyses'",
      '`/analyses/${id}`',
      '`/analyses/${id}/soil`',
      '`/analyses/${id}/timeseries',
      '`/analyses/${id}/maps`',
      "'/analyses', data",
    ]) {
      assert.ok(api.includes(fragment), `analysesApi lost ${fragment}`);
    }
  });

  it('legacy pages still import analysesApi', () => {
    const consumers = [
      'Dashboard',
      'Reports',
      'Location',
      'Analysis',
      'Soil',
      'Vegetation',
      'Climate',
      'Water',
      'LandCover',
      'Historical',
    ];
    for (const page of consumers) {
      const source = readSource(`pages/${page}.tsx`);
      assert.ok(source.includes('analysesApi'), `${page} lost analysesApi`);
    }
  });

  it('backend legacy routers are not removed (read-only guard)', () => {
    const router = readFileSync(
      join(repoDir, 'backend', 'app', 'api', 'router.py'),
      'utf-8',
    );
    for (const include of [
      'analyses.router',
      'soil.router',
      'maps.router',
      'timeseries.router',
      'reports.router',
    ]) {
      assert.ok(router.includes(include), `backend router lost ${include}`);
    }
  });
});

// --- 5. comprehensive soil contract and legacy artifact stay intact --------------------------

describe('5. comprehensive soil contract stays intact', () => {
  it('soil route, domains, and request payload are unchanged', () => {
    const soil = DOMAIN_PAGE_CONFIGS.soil;
    assert.equal(soil.routePath, SOIL_TARGET);
    assert.deepEqual(soil.apiDomains, ['soil']);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS[SOIL_TARGET], ['soil']);
    assert.equal(Object.keys(DOMAIN_ROUTE_PAYLOADS).length, 10);
    assert.equal(Object.keys(DOMAIN_PAGE_CONFIGS).length, 10);
  });

  it('the three audited soil properties remain registered', () => {
    const keys = DOMAIN_PAGE_CONFIGS.soil.sections.flatMap(
      (section) => section.metricKeys,
    );
    for (const key of [
      'soil_organic_carbon',
      'soil_texture_class',
      'soil_ph',
      'soil_moisture_surface',
    ]) {
      assert.ok(keys.includes(key), `soil config missing ${key}`);
    }
  });

  it('legacy Soil.tsx is retained with its notice and API calls', () => {
    const soil = readSource('pages/Soil.tsx');
    assert.ok(soil.includes('ComprehensiveNotice'));
    assert.ok(soil.includes(`to="${SOIL_TARGET}"`));
    assert.ok(soil.includes('analysesApi.create'));
    assert.ok(soil.includes('analysesApi.getMaps'));
    assert.ok(!soil.includes('<Navigate'), 'legacy page gained a redirect');
    assert.ok(!/window\.location\s*=/.test(soil));
  });

  it('the hub still links to the comprehensive soil page', () => {
    const nav = readSource('components/agriculture/DomainNavCards.tsx');
    assert.ok(nav.includes('to={config.routePath}'));
    const block = readSource('components/agriculture/DomainSummaryBlock.tsx');
    assert.ok(block.includes('routePathForDomain'));
  });
});
