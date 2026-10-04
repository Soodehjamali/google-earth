/**
 * F2 focused tests — Comprehensive domain views.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/f2.test.ts
 * Covers F2 §23 items 1–14. Static guards read sources; no network.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  DOMAIN_PAGE_CONFIGS,
  allConfiguredMetricKeys,
} from '../domainPages.ts';
import { API_DOMAINS, DOMAIN_ROUTE_PAYLOADS } from '../request.ts';
import {
  findEvidenceItem,
  formatEvidenceValue,
  shouldRenderKpi,
} from '../parse.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));
const domainPagesDir = join(srcDir, 'pages', 'agriculture');

function listFiles(dir: string): string[] {
  const files: string[] = [];
  const walk = (current: string) => {
    for (const entry of readdirSync(current)) {
      const full = join(current, entry);
      if (statSync(full).isDirectory()) {
        if (entry === '__tests__') continue;
        walk(full);
      } else if (/\.(ts|tsx)$/.test(entry)) {
        files.push(full);
      }
    }
  };
  walk(dir);
  return files;
}

const EXPECTED_PAYLOADS: Record<string, string[]> = {
  '/agriculture/vegetation': ['vegetation'],
  '/agriculture/phenology': ['phenology', 'productivity'],
  '/agriculture/climate': ['climate', 'thermal'], // P4: thermal gates the air-temperature profile
  '/agriculture/water': ['water'],
  '/agriculture/soil': ['soil'],
  '/agriculture/thermal': ['thermal'],
  '/agriculture/terrain': ['terrain'],
  '/agriculture/land-crop': ['landcover', 'crop'],
  '/agriculture/stress-irrigation': ['stress', 'irrigation'],
  '/agriculture/history': ['historical'],
};

const EXPECTED_PAGE_KEYS: Record<string, string[]> = {
  vegetation: ['ndvi', 'evi', 'savi', 'msavi', 'ndre', 'lai', 'fapar', 'fcover', 'middle_canopy_dryness_proxy', 'vv', 'vh', 'vh_vv', 'rvi'],
  phenology: [
    'vegetation_season_onset',
    'vegetation_activity_peak',
    'vegetation_season_end',
    'vegetation_season_length',
    'vegetation_season_amplitude',
    'seasonal_vegetation_productivity_indicator',
    'seasonal_evapotranspiration_context',
    'crop_area_normalised_productivity_indicator',
  ],
  climate: [
    'precipitation',
    'temperature_max',
    'temperature_min',
    'temperature_mean',
    'wind_speed',
    'solar_radiation',
    'vpd',
    'relative_humidity',
    'par',
    'gdd',
  ],
  water: [
    'ndwi',
    'ndmi',
    'mndwi',
    'msi',
    'evapotranspiration',
    'potential_evapotranspiration',
    'evapotranspiration_cumulative',
    'era5_evaporation',
  ],
  soil: [
    'soil_moisture_surface',
    'soil_moisture_surface_evening',
    'soil_moisture_rootzone',
    'soil_moisture_rootzone_era5',
    'soil_moisture_wetness',
    'root_zone_soil_moisture_gldas',
    'soil_field_capacity',
    'soil_wilting_point',
    'soil_available_water_capacity',
    'soil_temperature_0_7cm',
    'soil_temperature_7_28cm',
    'soil_organic_carbon',
    'soil_texture_class',
    'soil_ph',
  ],
  thermal: [
    'land_surface_temperature_day',
    'land_surface_temperature_night',
    'land_surface_temperature_mean',
    'surface_temperature_range',
    'landsat_surface_temperature',
  ],
  terrain: ['elevation', 'slope', 'aspect', 'terrain_ruggedness'],
  'land-crop': [
    'land_cover_class',
    'land_cover_quality',
    'land_cover_probability',
    'temporary_crop_context',
    'maize_context',
    'cereal_context',
    'temporary_crop_area',
  ],
  'stress-irrigation': [
    'evaporative_fraction',
    'soil_water_content_ratio',
    'plant_available_water_fraction',
    'vpd_anomaly',
    'vpd_high_duration',
    'lst_day_anomaly',
    'lst_day_percentile',
    'precipitation_cumulative',
    'et_precipitation_deficit',
    'precipitation_anomaly',
    'evapotranspiration_anomaly',
    'soil_moisture_rootzone_anomaly',
  ],
  history: [
    'ndvi_anomaly_absolute',
    'ndvi_anomaly_relative',
    'ndvi_anomaly_standardized',
    'ndvi_percentile_context',
    'ndvi_trend',
    'ndvi_anomaly_persistence',
    'ndvi_change_shift',
    'climate_trend',
    'season_timing_history',
    // P1 consolidation: year-over-year comparison reuses the NDVI
    // temporal profile already transported in the response.
    'ndvi',
  ],
};

function pageSectionKeys(pageKey: string): string[] {
  const config = DOMAIN_PAGE_CONFIGS[pageKey];
  const keys = new Set<string>();
  for (const section of config.sections) {
    for (const key of section.metricKeys) keys.add(key);
  }
  return [...keys].sort();
}

// --- 1. all ten routes render ---------------------------------------------------

describe('1. all ten domain routes render', () => {
  it('App wires ten DomainPage child routes under the shared layout', () => {
    const app = readFileSync(join(srcDir, 'App.tsx'), 'utf-8');
    assert.ok(app.includes('AgricultureLayout'));
    for (const pageKey of Object.keys(EXPECTED_PAGE_KEYS)) {
      assert.ok(
        app.includes(`<DomainPage pageKey="${pageKey}" />`),
        `missing route for ${pageKey}`,
      );
    }
  });

  it('configuration covers exactly the ten locked pages', () => {
    assert.deepEqual(Object.keys(DOMAIN_PAGE_CONFIGS).sort(), Object.keys(EXPECTED_PAGE_KEYS).sort());
  });
});

// --- 2. locked domain mapping -----------------------------------------------------

describe('2. each route uses the correct locked domain mapping', () => {
  it('route payloads match the Phase 0B §13 table', () => {
    for (const [route, domains] of Object.entries(EXPECTED_PAYLOADS)) {
      assert.deepEqual(DOMAIN_ROUTE_PAYLOADS[route], domains, route);
      const pageKey = route.replace('/agriculture/', '');
      assert.deepEqual(DOMAIN_PAGE_CONFIGS[pageKey].apiDomains, domains, pageKey);
    }
  });
});

// --- 3. no Legacy --------------------------------------------------------------------

describe('3. no domain view calls Legacy APIs', () => {
  it('domain pages and shared components stay Comprehensive-only', () => {
    const files = [...listFiles(domainPagesDir), ...listFiles(agricultureDir)];
    const forbidden = [
      'analysesApi.',
      'vegetationApi.',
      'locationsApi.',
      "apiPost('/analyses'",
      'apiPost("/analyses"',
      '/analyses/',
    ];
    for (const file of files) {
      const text = readFileSync(file, 'utf-8');
      for (const token of forbidden) {
        assert.ok(!text.includes(token), `${file} contains Legacy ${token}`);
      }
    }
  });
});

// --- 4. parent owns requests --------------------------------------------------------------

describe('4. child pages never trigger analysis requests directly', () => {
  it('no agricultureApi.analyze / runAnalysis call in domain views', () => {
    const files = listFiles(domainPagesDir);
    assert.ok(files.length > 0);
    for (const file of files) {
      const text = readFileSync(file, 'utf-8');
      assert.ok(!text.includes('agricultureApi.analyze'), file);
      assert.ok(!text.includes('runAnalysis('), file);
      assert.ok(text.includes('useAgricultureContext'), file);
    }
  });
});

// --- 5. missing analysis ----------------------------------------------------------------------

describe('5. missing analysis state is handled with a hub back-link', () => {
  it('empty state links back to /agriculture instead of auto-calling', () => {
    const page = readFileSync(join(domainPagesDir, 'DomainPage.tsx'), 'utf-8');
    assert.ok(page.includes('to="/agriculture"'));
    assert.ok(page.includes('empty-state'));
    assert.ok(!page.includes('agricultureApi.analyze'));
  });

  it('absent evidence resolves to null (safe empty rows)', () => {
    assert.equal(findEvidenceItem({}, 'ndvi'), null);
    assert.equal(findEvidenceItem(null, 'ndvi'), null);
  });
});

// --- 6/7/8. metric scoping ------------------------------------------------------------------------

describe('6/7/8. each domain renders only its relevant metrics', () => {
  it('configured section keys equal the authoritative per-page sets', () => {
    for (const [pageKey, expected] of Object.entries(EXPECTED_PAGE_KEYS)) {
      assert.deepEqual(pageSectionKeys(pageKey), [...expected].sort(), pageKey);
    }
  });

  it('soil includes all 14 moisture + property + composition metrics', () => {
    assert.equal(pageSectionKeys('soil').length, 14);
  });

  it('phenology includes the three productivity proxies', () => {
    const keys = pageSectionKeys('phenology');
    assert.ok(keys.includes('seasonal_vegetation_productivity_indicator'));
    assert.ok(keys.includes('seasonal_evapotranspiration_context'));
    assert.ok(keys.includes('crop_area_normalised_productivity_indicator'));
  });

  it('90 grouped keys plus era5_potential via unavailable text = 91 surfaced', () => {
    // CD-6 adds middle_canopy_dryness_proxy to the vegetation page.
    // P5.2 adds vv, vh, vh_vv, rvi (vegetation page radar section)
    // and msi (water page moisture section): 82 + 5 = 87.
    // P0 consolidation adds soil_organic_carbon, soil_texture_class,
    // soil_ph (soil page composition section): 87 + 3 = 90.
    assert.equal(allConfiguredMetricKeys().length, 90);
    assert.ok(allConfiguredMetricKeys().includes('middle_canopy_dryness_proxy'));
    assert.ok(!allConfiguredMetricKeys().includes('era5_potential_evaporation'));
  });
});

// --- 9. land-crop --------------------------------------------------------------------------

describe('9. land-crop renders scalar summaries, never distributions', () => {
  it('no distribution/chart machinery in domain sources', () => {
    const files = [...listFiles(domainPagesDir), ...listFiles(agricultureDir)];
    // F3-B allow-list: these modules render the backend-supplied
    // category distribution through the explicit histogram semantic
    // map. Chart-library tokens stay forbidden everywhere.
    const F3B_DISTRIBUTION_FILES = new Set([
      'evidenceDetails.ts',
      'ClassHistogramDetail.tsx',
      'EvidenceDetailCard.tsx',
    ]);
    // P5.2 allow-list: the temporal chart renderer plots backend
    // monthly observations with the chart library. Every other
    // domain source stays free of chart tokens.
    // P1 consolidation allow-list: the year-over-year comparison
    // overlays backend monthly NDVI points with the same library.
    const P52_CHART_FILES = new Set(['TemporalLineChart.tsx', 'TemporalChartCard.tsx']);
    const P1_CHART_FILES = new Set(['YearComparisonSection.tsx']);
    const chartTokens = ['recharts', 'BarChart', 'DistributionChart'];
    const distributionTokens = ['Histogram', 'histogram'];
    for (const file of files) {
      const text = readFileSync(file, 'utf-8');
      const base = file.split(/[\\/]/).pop() ?? file;
      for (const token of chartTokens) {
        if (token === 'recharts' && P52_CHART_FILES.has(base)) continue;
        if (token === 'recharts' && P1_CHART_FILES.has(base)) continue;
        assert.ok(!text.includes(token), `${file} contains ${token}`);
      }
      if (!F3B_DISTRIBUTION_FILES.has(base)) {
        for (const token of distributionTokens) {
          assert.ok(!text.includes(token), `${file} contains ${token}`);
        }
      }
    }
  });

  it('land-crop sections are scalar KPI sections with an explicit note', () => {
    // P2A: the class-shares section is a locked, presentation-only
    // branch that renders the response's own class distribution —
    // still no chart machinery, still backend-supplied text only.
    for (const section of DOMAIN_PAGE_CONFIGS['land-crop'].sections) {
      assert.ok(
        section.kind === 'kpi' || section.kind === 'landcover-shares',
        `unexpected land-crop section kind: ${section.kind}`,
      );
      assert.ok(typeof section.note === 'string' && section.note.length > 0);
    }
    assert.ok(
      DOMAIN_PAGE_CONFIGS['land-crop'].sections.some(
        (section) => section.kind === 'landcover-shares',
      ),
    );
  });
});

// --- 10. history ------------------------------------------------------------------------------

describe('10. history renders scalars, never a synthetic series', () => {
  it('no series machinery in domain sources', () => {
    const files = [...listFiles(domainPagesDir), ...listFiles(agricultureDir)];
    // P5.2 allow-list: the temporal chart renderer plots backend
    // monthly series with gaps preserved. Every other domain
    // source stays free of series tokens.
    // P1 consolidation allow-list: the year-over-year comparison
    // overlays backend monthly NDVI points by calendar year, gaps
    // preserved, with no new requests.
    const P52_SERIES_FILES = new Set(['TemporalLineChart.tsx', 'TemporalChartCard.tsx']);
    const P1_SERIES_FILES = new Set(['YearComparisonSection.tsx']);
    const forbidden = ['LineChart', 'connectNulls', 'year-over-year', 'YearOverYear'];
    for (const file of files) {
      const text = readFileSync(file, 'utf-8');
      const base = file.split(/[\\/]/).pop() ?? file;
      if (P52_SERIES_FILES.has(base)) continue;
      if (P1_SERIES_FILES.has(base)) continue;
      for (const token of forbidden) {
        assert.ok(!text.includes(token), `${file} contains ${token}`);
      }
    }
  });

  it('history sections are scalar KPI sections plus the year comparison', () => {
    for (const section of DOMAIN_PAGE_CONFIGS.history.sections) {
      assert.ok(section.kind === 'kpi' || section.kind === 'year-comparison');
    }
    assert.ok(
      DOMAIN_PAGE_CONFIGS.history.sections.some(
        (section) => section.kind === 'year-comparison',
      ),
    );
  });
});

// --- 11. unavailable ------------------------------------------------------------------------------

describe('11. unavailable metrics are not rendered as KPIs', () => {
  it('denylist-shaped evidence never qualifies for KPI rendering', () => {
    const denylisted = [
      { metric_key: 'cwsi', value: null, status: 'unavailable' },
      { metric_key: 'composite_stress', value: 0.8, status: 'unavailable' },
      { metric_key: 'crop_yield_estimate', value: null, status: 'derived' },
      { metric_key: 'topographic_wetness_index', value: undefined, status: 'derived' },
    ];
    for (const item of denylisted) {
      assert.equal(shouldRenderKpi(item), false, item.metric_key);
    }
  });

  it('grouped grids gate every KPI behind shouldRenderKpi', () => {
    const grid = readFileSync(join(agricultureDir, 'MetricKpiGrid.tsx'), 'utf-8');
    assert.ok(grid.includes('shouldRenderKpi'));
  });
});

// --- 12. null safety ----------------------------------------------------------------------------------

describe('12. null values are safe across domain evidence', () => {
  it('null formats to the marker and resolves by exact key only', () => {
    assert.equal(formatEvidenceValue(null), '—');
    const bundles = {
      soil: {
        items: [{ metric_key: 'soil_moisture_surface', value: 0.21 }],
      },
    };
    assert.equal(findEvidenceItem(bundles, 'soil_moisture_surface')?.bundleName, 'soil');
    assert.equal(findEvidenceItem(bundles, 'soil_moisture'), null);
    assert.equal(findEvidenceItem(bundles, 'moisture'), null);
  });
});

// --- 13. historical spelling -------------------------------------------------------------------------------

describe('13. historical spelling remains correct', () => {
  it('history view uses the API spelling; registry spelling never sent', () => {
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.history.apiDomains, ['historical']);
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.history.bundleKeys, ['historical']);
    for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
      for (const domain of config.apiDomains) {
        assert.ok(
          (API_DOMAINS as readonly string[]).includes(domain),
          `unknown api domain ${domain}`,
        );
        assert.ok(domain !== 'history', 'registry spelling must not be sent');
        assert.ok(domain !== 'soil-properties', 'no soil-properties domain');
      }
    }
  });
});

// --- 14. domains=[] ----------------------------------------------------------------------------------------------

describe('14. domains=[] is never introduced', () => {
  it('no empty-domains literal in domain source code (comments excluded)', () => {
    const files = [...listFiles(domainPagesDir), ...listFiles(agricultureDir)];
    for (const file of files) {
      const code = readFileSync(file, 'utf-8')
        .split('\n')
        .filter((line) => {
          const trimmed = line.trim();
          return (
            !trimmed.startsWith('//') &&
            !trimmed.startsWith('*') &&
            !trimmed.startsWith('/*')
          );
        })
        .join('\n');
      assert.ok(!code.includes('domains: []'), file);
      assert.ok(!code.includes('domains:[]'), file);
    }
  });
});
