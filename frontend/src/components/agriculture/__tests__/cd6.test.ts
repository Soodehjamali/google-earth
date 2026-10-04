/**
 * CD-6 focused tests — middle-canopy dryness proxy frontend integration.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/cd6.test.ts
 * Covers the CD-6 brief items 1–15 through pure helpers plus static
 * source guards, following the f1/f2/f3b conventions.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import { API_DOMAINS, normalizeSelectedDomains } from '../request.ts';
import {
  DOMAIN_META,
  PATTERN_META,
} from '../../../types/index.ts';
import type { EvidenceItemResponse } from '../../../types/index.ts';
import type { ProvenanceResponse } from '../../../types/index.ts';
import {
  PROXY_METRIC_KEY,
  PROXY_RULE_IDS,
  PROXY_STATE_META,
  isProxyRuleId,
  isStateProxyItem,
  proxyStateFor,
} from '../proxyState.ts';
import {
  domainMetaFor,
  formatEvidenceValue,
  getProvenanceRows,
  qualityToKpiStatus,
  shouldRenderKpi,
} from '../parse.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

function proxyItem(overrides: Partial<EvidenceItemResponse> = {}): EvidenceItemResponse {
  return {
    metric_key: PROXY_METRIC_KEY,
    value: 3,
    unit: 'state',
    status: 'proxy',
    quality: 'good',
    source_dataset: 'COPERNICUS/S2_SR_HARMONIZED',
    display_name: 'Middle-Canopy Dryness Proxy',
    temporal_start: '2024-07-01',
    temporal_end: '2024-07-31',
    is_usable: true,
    is_proxy: true,
    provenance: null,
    stats: null,
    class_histogram: null,
    band_means: null,
    ...overrides,
  };
}

// --- 1/2. metadata registration + vegetation placement ------------------------

describe('1/2. proxy metadata lives under the vegetation domain', () => {
  it('vegetation page has a proxy section with the exact proxy key', () => {
    const config = DOMAIN_PAGE_CONFIGS.vegetation;
    assert.ok(config);
    assert.equal(config.metaKey, 'vegetation');
    assert.deepEqual(config.apiDomains, ['vegetation']);
    assert.deepEqual(config.bundleKeys, ['vegetation']);
    const section = config.sections.find((entry) =>
      entry.metricKeys.includes(PROXY_METRIC_KEY),
    );
    assert.ok(section, 'proxy section missing from vegetation page');
    assert.ok(section.title.toLowerCase().includes('proxy'));
    assert.ok((section.note ?? '').toLowerCase().includes('proxy'));
  });

  it('domain selection semantics are unchanged (domains only, no proxy entry)', () => {
    assert.ok(!(API_DOMAINS as readonly string[]).includes(PROXY_METRIC_KEY));
    assert.deepEqual(normalizeSelectedDomains(['vegetation', PROXY_METRIC_KEY]), [
      'vegetation',
    ]);
    assert.deepEqual(DOMAIN_PAGE_CONFIGS.vegetation.apiDomains, ['vegetation']);
  });

  it('cross-domain synthesis metadata exists for the contract test', () => {
    assert.ok(DOMAIN_META.cross_domain);
    assert.equal(DOMAIN_META.cross_domain.key, 'cross_domain');
    assert.ok(DOMAIN_META.cross_domain.label.length > 0);
    assert.ok(DOMAIN_META.cross_domain.labelFa.length > 0);
    assert.ok(DOMAIN_META.cross_domain.icon.length > 0);
    assert.equal(domainMetaFor('cross_domain').key, 'cross_domain');
  });
});

// --- 3-7. state legend ----------------------------------------------------------

describe('3-7. backend state codes resolve to the backend legend', () => {
  it('codes 1-5 map to the exact backend state names', () => {
    assert.equal(proxyStateFor(1)?.name, 'OPTICAL_STRESS_ONLY');
    assert.equal(proxyStateFor(2)?.name, 'RADAR_STRUCTURAL_CONTEXT_ONLY');
    assert.equal(proxyStateFor(3)?.name, 'CONCORDANT_STRESS');
    assert.equal(proxyStateFor(4)?.name, 'MIXED_OR_CONTRADICTORY');
    assert.equal(proxyStateFor(5)?.name, 'NO_STRESS_EVIDENCE');
  });

  it('every state carries bilingual labels', () => {
    for (const code of [1, 2, 3, 4, 5]) {
      const meta = PROXY_STATE_META[code];
      assert.ok(meta.label.length > 0);
      assert.ok(meta.labelFa.length > 0);
      assert.equal(meta.code, code);
    }
  });

  it('state table covers exactly the five backend codes', () => {
    assert.deepEqual(
      Object.keys(PROXY_STATE_META).map(Number).sort(),
      [1, 2, 3, 4, 5],
    );
  });
});

// --- 8. missing / insufficient ----------------------------------------------------

describe('8. missing and insufficient evidence stay unrendered as states', () => {
  it('non-codes resolve to null, never a guessed label', () => {
    for (const bad of [null, undefined, NaN, '3', 0, 6, 3.5, -1, Infinity]) {
      assert.equal(proxyStateFor(bad), null);
    }
  });

  it('null/unavailable proxy values never qualify for KPI rendering', () => {
    assert.equal(shouldRenderKpi({ value: null, status: 'proxy' }), false);
    assert.equal(shouldRenderKpi({ value: undefined, status: 'proxy' }), false);
    assert.equal(shouldRenderKpi({ value: 3, status: 'unavailable' }), false);
    assert.equal(formatEvidenceValue(null), '—');
  });
});

// --- 9. confidence / quality -------------------------------------------------------

describe('9. categorical confidence and quality render through existing paths', () => {
  it('backend qualities map to the existing KPI tones', () => {
    assert.equal(qualityToKpiStatus('good'), 'good');
    assert.equal(qualityToKpiStatus('moderate'), 'warning');
    assert.equal(qualityToKpiStatus('poor'), 'danger');
  });

  it('provenance drawer passes caveats (confidence ledger) through generically', () => {
    const drawer = readSource('components/agriculture/ProvenanceDrawer.tsx');
    assert.ok(drawer.includes('provenance.caveats'));
    assert.ok(drawer.includes('provenance.limitations'));
  });
});

// --- 10. proxy identification --------------------------------------------------------

describe('10. state proxies are identified without touching scalar metrics', () => {
  it('only is_proxy + unit state qualifies', () => {
    assert.equal(isStateProxyItem(proxyItem()), true);
    assert.equal(isStateProxyItem(proxyItem({ unit: 'index' })), false);
    assert.equal(isStateProxyItem(proxyItem({ is_proxy: false })), false);
    assert.equal(
      isStateProxyItem({ metric_key: 'ndvi', value: 0.6, unit: 'index', status: 'derived' }),
      false,
    );
    assert.equal(isStateProxyItem(null), false);
    assert.equal(isStateProxyItem(undefined), false);
  });
});

// --- 11. synthesis statements ----------------------------------------------------------

describe('11. the five proxy rules render through the existing statement UI', () => {
  it('exact rule-id set, no substring matching', () => {
    assert.equal(PROXY_RULE_IDS.size, 5);
    for (const id of [
      'canopy_proxy_concordant_stress',
      'canopy_proxy_optical_stress_only',
      'canopy_proxy_radar_context_only',
      'canopy_proxy_mixed',
      'canopy_proxy_no_stress',
    ]) {
      assert.equal(isProxyRuleId(id), true, id);
    }
    assert.equal(isProxyRuleId('canopy_proxy_concordant_stress_extra'), false);
    assert.equal(isProxyRuleId('vegetation_below_historical'), false);
    assert.equal(isProxyRuleId(null), false);
  });

  it('every pattern used by proxy rules exists in PATTERN_META', () => {
    for (const pattern of ['coherent', 'below_context', 'near_context', 'mixed_evidence']) {
      assert.ok(PATTERN_META[pattern], pattern);
    }
  });

  it('statement card marks proxy rules and labels proxy evidence values', () => {
    const card = readSource('components/agriculture/SynthesisStatementCard.tsx');
    assert.ok(card.includes('isProxyRuleId'));
    assert.ok(card.includes('proxyStateFor'));
    assert.ok(card.includes('PROXY_METRIC_KEY'));
  });
});

// --- 12. limitations / provenance ----------------------------------------------------------

describe('12. proxy limitations and provenance survive generically', () => {
  it('provenance rows expose formula, basis, quality and window', () => {
    const provenance: ProvenanceResponse = {
      source_dataset_id: 'COPERNICUS/S2_SR_HARMONIZED',
      source_dataset_name: 'Sentinel-2',
      bands: ['B8', 'B11'],
      formula: 'concordance of signs',
      unit: 'state',
      spatial_resolution: '10 m',
      temporal_resolution: 'mixed',
      aggregation_method: 'votes counted',
      measurement_basis: 'proxy',
      quality_level: 'good',
      temporal_kind: 'observation',
      requested_start: '2024-07-01',
      requested_end: '2024-07-31',
      limitations: ['does not directly measure'],
      caveats: ['confidence: HIGH'],
      citation: 'CD-4',
    };
    const rows = getProvenanceRows(provenance);
    const byKey = new Map(rows.map((row) => [row.key, row.value]));
    assert.equal(byKey.get('formula'), 'concordance of signs');
    assert.equal(byKey.get('measurement_basis'), 'proxy');
    assert.equal(byKey.get('quality_level'), 'good');
    assert.equal(byKey.get('requested_start'), '2024-07-01');
  });
});

// --- 13. no physical quantities -----------------------------------------------------------------

describe('13. no percentages, probabilities, or physical quantities', () => {
  it('proxy sources contain no quantitative fabrication tokens', () => {
    const files = [
      'components/agriculture/proxyState.ts',
      'components/agriculture/ProxyStateCard.tsx',
    ];
    const forbidden = ['%', 'percent', 'probability', 'toFixed', 'confidence_score'];
    for (const relative of files) {
      const text = readSource(relative);
      for (const token of forbidden) {
        assert.ok(!text.includes(token), `${relative} contains ${token}`);
      }
    }
    // domainPages.ts legitimately names pre-existing backend keys such
    // as lst_day_percentile, so only the added proxy section is scanned.
    const pages = readSource('components/agriculture/domainPages.ts');
    const start = pages.indexOf("id: 'dryness-proxy'");
    assert.ok(start >= 0, 'proxy section missing');
    const section = pages.slice(start, pages.indexOf('},', start) + 2);
    for (const token of forbidden) {
      assert.ok(!section.includes(token), `proxy section contains ${token}`);
    }
  });

  it('edited renderers add no quantitative tokens either', () => {
    for (const relative of [
      'components/agriculture/MetricKpiGrid.tsx',
      'components/agriculture/EvidenceDetailCard.tsx',
      'components/agriculture/SynthesisStatementCard.tsx',
    ]) {
      const text = readSource(relative);
      assert.ok(!text.includes('percent'), `${relative} contains percent`);
      assert.ok(!text.includes('probability'), `${relative} contains probability`);
    }
  });
});

// --- 14. NO_STRESS_EVIDENCE vs NO_EVIDENCE -----------------------------------------------------------------

describe('14. state 5 and missing evidence stay visually and semantically distinct', () => {
  it('code 5 resolves; missing resolves to null', () => {
    assert.equal(proxyStateFor(5)?.name, 'NO_STRESS_EVIDENCE');
    assert.equal(proxyStateFor(null), null);
    assert.equal(proxyStateFor(undefined), null);
  });

  it('grids keep both the state branch and the unavailable branch', () => {
    const grid = readSource('components/agriculture/MetricKpiGrid.tsx');
    assert.ok(grid.includes('ProxyStateCard'));
    assert.ok(grid.includes('kpi-no-data'));
    assert.ok(grid.includes('unavailable'));
    const detail = readSource('components/agriculture/EvidenceDetailCard.tsx');
    assert.ok(detail.includes('ProxyStateCard'));
    assert.ok(detail.includes('unavailable'));
  });
});

// --- 15. existing vegetation metrics unaffected -----------------------------------------------------------------

describe('15. established vegetation sections keep their exact keys', () => {
  it('overview and canopy sections are byte-identical in membership', () => {
    const sections = DOMAIN_PAGE_CONFIGS.vegetation.sections;
    const overview = sections.find((entry) => entry.id === 'overview');
    const canopy = sections.find((entry) => entry.id === 'canopy');
    assert.deepEqual(overview?.metricKeys, ['ndvi', 'evi', 'savi', 'msavi', 'ndre']);
    assert.deepEqual(canopy?.metricKeys, ['lai', 'fapar', 'fcover']);
  });
});
