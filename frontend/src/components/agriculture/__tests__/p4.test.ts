/**
 * P4 focused tests — climate thermal routing fix.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p4.test.ts
 * Locks the narrow routing defect: the climate request carries the
 * existing `thermal` domain so the backend can build
 * `temporal.thermal_profiles.temperature_mean`, the existing climate
 * domains stay, no precipitation temporal field is invented, the
 * existing temporal rendering path is untouched, and no additional
 * API request is introduced. Static guards read sources; no network.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import {
  API_DOMAINS,
  DOMAIN_ROUTE_PAYLOADS,
  buildAgricultureRequest,
} from '../request.ts';
import {
  mapProfilePoints,
  payloadPoints,
  profileFor,
} from '../temporalChart.ts';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

const POINT: { type: 'Point'; coordinates: number[] } = {
  type: 'Point',
  coordinates: [53.688, 32.4279],
};

function climateRequest(selectedDomains: readonly string[]) {
  return buildAgricultureRequest({
    geometry: { type: 'Point', coordinates: [...POINT.coordinates] },
    start_date: '2025-06-01',
    end_date: '2025-09-01',
    selectedDomains,
    cloud_max_percent: 20,
  });
}

// --- 1. climate request includes the required thermal domain ---------------------

describe('1. climate request carries the thermal domain', () => {
  it('locked route payload and page config both request thermal', () => {
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/climate'], [
      'climate',
      'thermal',
    ]);
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.climate.apiDomains, ['climate', 'thermal']);
  });

  it('thermal comes from the locked API vocabulary, never a new name', () => {
    for (const domain of DOMAIN_ROUTE_PAYLOADS['/agriculture/climate']) {
      assert.ok(
        (API_DOMAINS as readonly string[]).includes(domain),
        `${domain} is not a locked API domain`,
      );
    }
    assert.ok((API_DOMAINS as readonly string[]).includes('thermal'));
    assert.ok((API_DOMAINS as readonly string[]).includes('climate'));
  });

  it('built climate requests include climate and thermal', () => {
    assert.deepEqual(climateRequest(['climate']).domains, ['climate', 'thermal']);
    assert.deepEqual(climateRequest(['climate', 'soil']).domains, [
      'climate',
      'soil',
      'thermal',
    ]);
    assert.deepEqual(climateRequest(['climate', 'thermal']).domains, [
      'climate',
      'thermal',
    ]);
  });
});

// --- 2. existing climate domains remain present ----------------------------------

describe('2. existing climate domains and payload contracts stay', () => {
  it('climate remains in every climate request', () => {
    for (const domains of [
      climateRequest(['climate']).domains ?? [],
      climateRequest(['climate', 'soil']).domains ?? [],
      DOMAIN_ROUTE_PAYLOADS['/agriculture/climate'],
      DOMAIN_PAGE_CONFIGS.climate.apiDomains,
    ]) {
      assert.ok(domains.includes('climate'), domains.join(','));
    }
  });

  it('other route payloads are unchanged', () => {
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/vegetation'], ['vegetation']);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/water'], ['water']);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/soil'], ['soil']);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/thermal'], ['thermal']);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/land-crop'], [
      'landcover',
      'crop',
    ]);
    assert.deepEqual(DOMAIN_ROUTE_PAYLOADS['/agriculture/history'], ['historical']);
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.water.apiDomains, ['water']);
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.soil.apiDomains, ['soil']);
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.thermal.apiDomains, ['thermal']);
  });

  it('all-selected and empty selections still omit domains (Phase 0B §4)', () => {
    const all = climateRequest([...API_DOMAINS]);
    assert.ok(!('domains' in all), 'all-selected must omit domains');
    const empty = climateRequest([]);
    assert.ok(!('domains' in empty), 'empty selection must omit domains');
    assert.ok(!('domains' in climateRequest([...API_DOMAINS, 'climate'])));
  });

  it('climate bundle and scalar sections are untouched', () => {
    const climate = DOMAIN_PAGE_CONFIGS.climate;
    assert.deepEqual(climate.bundleKeys, ['climate']);
    const growing = climate.sections.find((section) => section.id === 'growing');
    assert.ok(growing);
    assert.equal(growing?.kind, 'kpi');
    assert.ok(growing?.metricKeys.includes('precipitation'));
  });
});

// --- 3. no precipitation temporal field is invented --------------------------------

describe('3. precipitation stays a scalar, never a temporal series', () => {
  it('no configured temporal series uses a precipitation key', () => {
    for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
      for (const section of config.sections) {
        for (const entry of section.temporalSeries ?? []) {
          assert.notEqual(entry.metricKey, 'precipitation', config.pageKey);
          assert.ok(!entry.metricKey.includes('precip'), config.pageKey);
        }
      }
    }
  });

  it('the climate temporal section profiles temperature only', () => {
    const section = DOMAIN_PAGE_CONFIGS.climate.sections.find(
      (candidate) => candidate.id === 'temporal-air-temperature',
    );
    assert.ok(section);
    assert.deepEqual(section?.metricKeys, ['temperature_mean']);
    assert.deepEqual(
      (section?.temporalSeries ?? []).map((entry) => entry.metricKey),
      ['temperature_mean'],
    );
  });

  it('the built request carries no precipitation or time-series field', () => {
    const request = climateRequest(['climate']);
    const keys = Object.keys(request).sort();
    assert.deepEqual(keys, [
      'cloud_max_percent',
      'domains',
      'end_date',
      'geometry',
      'start_date',
    ]);
    assert.ok(!('precipitation' in request));
    assert.ok(!('timeseries' in request));
  });

  it('the client and page config sources add no precipitation series', () => {
    const request = readSource('components/agriculture/request.ts');
    assert.ok(!request.includes('precipitation'), 'request.ts gained precipitation');
    const sources = [
      'components/agriculture/TemporalSection.tsx',
      'components/agriculture/temporalChart.ts',
      'pages/agriculture/DomainPage.tsx',
    ];
    for (const file of sources) {
      const text = readSource(file);
      assert.ok(!text.includes('precipitation'), `${file} gained precipitation`);
    }
  });

  it('the agriculture client exposes no precipitation endpoint', () => {
    const client = readSource('api/agriculture.ts');
    assert.ok(!client.includes('precipitation'));
    assert.ok(!client.includes('timeseries'));
  });
});

// --- 4. existing climate temporal rendering remains intact ---------------------------

describe('4. temperature profile renders through the existing path', () => {
  const climateTemporal = DOMAIN_PAGE_CONFIGS.climate.sections.find(
    (section) => section.id === 'temporal-air-temperature',
  );
  const entry = climateTemporal?.temporalSeries?.[0];

  it('entry keeps its key, unit and thermal identity', () => {
    assert.ok(entry);
    assert.equal(entry?.metricKey, 'temperature_mean');
    assert.equal(entry?.unit, 'degC');
    assert.equal(entry?.thermalKind, 'AIR_TEMPERATURE_PROFILE');
    assert.equal(entry?.label, 'Mean Air Temperature');
    assert.equal(entry?.labelFa, 'میانگین دمای هوا');
  });

  it('profileFor resolves thermal_profiles.temperature_mean verbatim', () => {
    const temporal = {
      thermal_profiles: {
        temperature_mean: {
          points: [
            {
              window_start: '2025-06-01',
              window_end: '2025-06-30',
              value: 24.5,
              unit: 'degC',
              quality: 'good',
              coverage_percent: 100,
            },
            {
              window_start: '2025-07-01',
              window_end: '2025-07-31',
              value: null,
              quality: 'insufficient',
              coverage_percent: 0,
            },
          ],
        },
      },
    };
    const payload = profileFor(temporal, 'temperature_mean');
    assert.ok(payload, 'thermal profile must resolve');
    const data = mapProfilePoints(payloadPoints(payload), entry?.unit ?? 'degC');
    assert.equal(data.length, 2);
    assert.equal(data[0]?.value, 24.5);
    assert.equal(data[0]?.unit, 'degC');
    assert.equal(data[1]?.value, null, 'null months stay gaps');
    assert.equal(profileFor(temporal, 'precipitation'), null, 'no precipitation profile');
  });

  it('the page still feeds the response temporal section to the chart layer', () => {
    const page = readSource('pages/agriculture/DomainPage.tsx');
    assert.ok(page.includes('temporal={result.temporal'));
    assert.ok(page.includes('TemporalSection'));
    const section = readSource('components/agriculture/TemporalSection.tsx');
    assert.ok(section.includes('profileFor(temporal'));
    assert.ok(section.includes('thermalKind'));
    const charts = readSource('components/agriculture/temporalChart.ts');
    assert.ok(charts.includes("'thermal_profiles'"));
  });

  it('no thresholds or interpretation were added to the chart layer', () => {
    const charts = readSource('components/agriculture/temporalChart.ts');
    for (const token of ['threshold', 'ReferenceLine', 'interpretation', 'stress_level']) {
      assert.ok(!charts.includes(token), token);
    }
  });
});

// --- 5. no additional API request is introduced ---------------------------------------

describe('5. one analysis request, no second call', () => {
  it('the parent layout still owns exactly one analysis call', () => {
    const layout = readSource('components/agriculture/AgricultureLayout.tsx');
    const occurrences = layout.split('agricultureApi.analyze(').length - 1;
    assert.equal(occurrences, 1);
    assert.ok(!layout.includes('agricultureApi.synthesisOnly'));
    assert.ok(!layout.includes('apiPost'));
  });

  it('the agriculture client endpoints are unchanged', () => {
    const client = readSource('api/agriculture.ts');
    assert.equal(client.split('apiPost<').length - 1, 2);
    assert.equal(client.split('apiGet<').length - 1, 1);
    assert.ok(client.includes("'/agriculture/analysis'"));
  });

  it('domain views never issue their own request', () => {
    const page = readSource('pages/agriculture/DomainPage.tsx');
    assert.ok(!page.includes('agricultureApi'));
    assert.ok(!page.includes('runAnalysis('));
    assert.ok(page.includes('useAgricultureContext'));
    const hub = readSource('pages/Agriculture.tsx');
    assert.ok(!hub.includes('apiPost('));
    assert.equal(hub.split('runAnalysis(').length - 1, 1);
  });
});

// --- 6. final consolidated routes ------------------------------------------------
// Final consolidation (P7 authorized): /climate joins /soil, /vegetation,
// /water and /landcover as compatibility redirects to Comprehensive.
// /historical is HOLD and keeps rendering its own page.

describe('6. final consolidated routes', () => {
  it('the legacy /climate route redirects with replace, rendering no page', () => {
    const app = readSource('App.tsx');
    assert.ok(app.includes('path="/climate"'));
    assert.ok(!app.includes('<Climate />'));
    assert.ok(app.includes('path="/climate" element={<Navigate'));
    assert.ok(app.includes('to="/agriculture/climate"'));
  });

  it('the remaining approved legacy routes redirect; HOLD routes still render', () => {
    const app = readSource('App.tsx');
    for (const legacy of ['/vegetation', '/water', '/landcover', '/soil']) {
      assert.ok(app.includes(`path="${legacy}" element={<Navigate`), legacy);
    }
    for (const page of ['/location', '/historical', '/reports', '/settings']) {
      assert.ok(!app.includes(`path="${page}" element={<Navigate`), page);
    }
    assert.ok(app.includes('<Historical />'), 'historical must keep rendering');
  });
});
