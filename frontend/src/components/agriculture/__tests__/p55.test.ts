/**
 * P5.5 focused tests — Evidence visualization over the real /analysis payload.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p55.test.ts
 * Covers pure evidence mapping (bundles, items, provenance, synthesis
 * links, temporal/spatial presence, defensive pattern passthrough),
 * domain identity (NDMI, radar, thermal separation), and static guards
 * proving the visualization layer adds no science, endpoints, or grades.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  bundleItems,
  bundleLimitations,
  bundleSourceDatasets,
  bundleSufficiencyLevel,
  bundleUnavailableKeys,
  concordanceMonthsOf,
  evidenceDisplayValue,
  evidenceWindowText,
  hasObservedValue,
  orderedBundleEntries,
  patternsInResponse,
  spatialReferenceFor,
  synthesisLinksFor,
  temporalReferenceFor,
  thermalConcordanceMonthsOf,
  validationsInResponse,
} from '../evidence.ts';
import { coverageRows, spatialStatRows } from '../evidenceDetails.ts';
import { formatEvidenceValue, getProvenanceRows } from '../parse.ts';
import { thermalSourceMetaFor } from '../thermal.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readAgricultureSource(name: string): string {
  return readFileSync(join(agricultureDir, name), 'utf-8');
}

function listNewSources(): string[] {
  const files: string[] = [];
  for (const name of ['evidence.ts', 'EvidenceSection.tsx']) {
    files.push(join(agricultureDir, name));
  }
  return files;
}

function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '$1');
}

function readNewSources(): string[] {
  return listNewSources().map((file) => readFileSync(file, 'utf-8'));
}

function readStrippedNewSources(): string[] {
  return readNewSources().map(stripComments);
}

function makeItem(overrides: Record<string, unknown> = {}) {
  return {
    metric_key: 'ndvi',
    value: 0.62,
    unit: 'index',
    status: 'observed',
    quality: 'good',
    source_dataset: 'COPERNICUS/S2_SR_HARMONIZED',
    display_name: 'NDVI',
    temporal_start: '2024-01-01',
    temporal_end: '2024-04-30',
    is_usable: true,
    is_proxy: false,
    provenance: null,
    stats: null,
    class_histogram: null,
    band_means: null,
    ...overrides,
  } as never;
}

function makeBundle(domain: string, items: unknown[] = [makeItem()]) {
  return {
    name: domain,
    items,
    available: ['ndvi'],
    unavailable: [],
    source_datasets: ['COPERNICUS/S2_SR_HARMONIZED'],
    conflicts: [],
    sufficiency: { level: 'sufficient' },
    limitations: [],
  } as never;
}

// --- 1-9. Evidence payload --------------------------------------------------------

describe('1-9. evidence payload renders verbatim', () => {
  it('1. real evidence bundle renders', () => {
    const bundles = { vegetation: makeBundle('vegetation') };
    const entries = orderedBundleEntries(bundles as never);
    assert.equal(entries.length, 1);
    assert.equal(entries[0]?.domain, 'vegetation');
    assert.equal(bundleItems(entries[0]?.bundle).length, 1);
  });

  it('2. multiple evidence bundles render in response order', () => {
    const bundles = {
      vegetation: makeBundle('vegetation'),
      water: makeBundle('water', [makeItem({ metric_key: 'ndmi', value: 0.1 })]),
      thermal: makeBundle('thermal', [makeItem({ metric_key: 'land_surface_temperature_day', value: 26.5, unit: 'degC' })]),
    };
    const entries = orderedBundleEntries(bundles as never);
    assert.deepEqual(entries.map((e) => e.domain), ['vegetation', 'water', 'thermal']);
  });

  it('3. domain identity preserved', () => {
    const entries = orderedBundleEntries({ water: makeBundle('water') } as never);
    assert.equal(entries[0]?.bundle.name, 'water');
    assert.equal(entries[0]?.domain, 'water');
  });

  it('4. metric identity preserved', () => {
    const items = bundleItems(makeBundle('water', [makeItem({ metric_key: 'ndmi' })]));
    assert.equal(items[0]?.metric_key, 'ndmi');
  });

  it('5. observed value preserved', () => {
    const item = makeItem({ value: 0.623456 });
    assert.equal((item as { value: number }).value, 0.623456);
    assert.equal(evidenceDisplayValue(item), formatEvidenceValue(0.623456));
    assert.equal(hasObservedValue(item), true);
  });

  it('6. unit preserved', () => {
    const items = bundleItems(makeBundle('thermal', [makeItem({ metric_key: 'vv', value: -8.2, unit: 'dB' })]));
    assert.equal(items[0]?.unit, 'dB');
    const ratio = bundleItems(makeBundle('vegetation', [makeItem({ metric_key: 'rvi', value: 0.5, unit: 'ratio' })]));
    assert.equal(ratio[0]?.unit, 'ratio');
  });

  it('7. null handling', () => {
    const item = makeItem({ value: null, status: 'observed' });
    assert.equal(evidenceDisplayValue(item), '—');
    assert.equal(hasObservedValue(item), false);
    assert.notEqual(evidenceDisplayValue(item), '0.0000');
  });

  it('8. insufficient handling', () => {
    const item = makeItem({ value: null, status: 'insufficient', quality: 'insufficient' });
    assert.equal(evidenceDisplayValue(item), '—');
    assert.equal(item.status, 'insufficient');
    assert.equal(item.quality, 'insufficient');
    assert.equal(hasObservedValue(item), false);
  });

  it('9. unavailable handling', () => {
    const item = makeItem({ value: 0.5, status: 'unavailable' });
    assert.equal(hasObservedValue(item), false);
    const missing = makeItem({ value: null, status: 'unavailable' });
    assert.equal(evidenceDisplayValue(missing), '—');
  });
});

// --- 10-16. Provenance ------------------------------------------------------------

describe('10-16. provenance preserves backend identity', () => {
  const provenance = {
    source_dataset_id: 'MODIS/061/MOD11A2',
    source_dataset_name: 'MODIS LST',
    bands: ['LST_Day_1km'],
    formula: 'scale * 0.02 - 273.15',
    unit: 'degC',
    spatial_resolution: '1 km',
    temporal_resolution: '8-day',
    aggregation_method: 'time mean, then spatial mean',
    measurement_basis: 'observed',
    quality_level: 'good',
    temporal_kind: 'observation',
    requested_start: '2024-01-01',
    requested_end: '2024-04-30',
    product_date: null,
    date_start: '2024-01-01',
    date_end: '2024-04-30',
    image_count: 6,
    fallback_from: null,
    limitations: ['Skin temperature, not air temperature.'],
    caveats: [],
    citation: '',
    computed_at: '2024-05-01',
  } as never;

  it('10. dataset preserved', () => {
    const rows = getProvenanceRows(provenance);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    assert.equal(byKey.source_dataset_id, 'MODIS/061/MOD11A2');
  });

  it('11. bands preserved', () => {
    const rows = getProvenanceRows(provenance);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    assert.ok((byKey.bands ?? '').includes('LST_Day_1km'));
  });

  it('12. window preserved', () => {
    const rows = getProvenanceRows(provenance);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    assert.equal(byKey.requested_start, '2024-01-01');
    assert.equal(byKey.requested_end, '2024-04-30');
    assert.equal(byKey.date_start, '2024-01-01');
    assert.equal(byKey.date_end, '2024-04-30');
  });

  it('13. quality preserved', () => {
    const rows = getProvenanceRows(provenance);
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    assert.equal(byKey.quality_level, 'good');
  });

  it('14. coverage preserved without invention', () => {
    const stats = { coverage_percent: 98.5, valid_pixel_count: 120, total_pixel_count: 122 };
    const rows = coverageRows(stats as never);
    assert.ok(rows.some((r) => r.key === 'coverage_percent' && r.value === 98.5));
    assert.deepEqual(coverageRows(null), []);
    assert.deepEqual(spatialStatRows(null), []);
  });

  it('15. physical quantity preserved distinctly', () => {
    const lst = thermalSourceMetaFor('LST_PROFILE');
    const air = thermalSourceMetaFor('AIR_TEMPERATURE_PROFILE');
    assert.equal(lst.physicalQuantity, 'land_surface_temperature');
    assert.equal(air.physicalQuantity, 'air_temperature_2m');
    assert.notEqual(lst.physicalQuantity, air.physicalQuantity);
  });

  it('16. limitations preserved', () => {
    const bundle = makeBundle('thermal') as unknown as Record<string, unknown>;
    (bundle as { limitations: string[] }).limitations = ['Skin temperature, not air temperature.'];
    assert.deepEqual(bundleLimitations(bundle as never), ['Skin temperature, not air temperature.']);
    assert.deepEqual(bundleLimitations(null), []);
    assert.equal(bundleSufficiencyLevel(bundle as never), 'sufficient');
    assert.deepEqual(bundleSourceDatasets(bundle as never), ['COPERNICUS/S2_SR_HARMONIZED']);
    assert.deepEqual(bundleUnavailableKeys(bundle as never), []);
  });
});

// --- 17-20. Patterns ---------------------------------------------------------------

describe('17-20. patterns render only when the backend sent them', () => {
  it('17. generic pattern renders when present', () => {
    const response = {
      patterns: [
        { pattern_id: 'p1', pattern_type: 'PERSISTENT_ANOMALY', window_start: '2024-01-01', window_end: '2024-01-31', status: 'OBSERVED' },
      ],
    };
    const rows = patternsInResponse(response);
    assert.equal(rows.length, 1);
    assert.equal(rows[0]?.pattern_type, 'PERSISTENT_ANOMALY');
  });

  it('18. named pattern renders when present', () => {
    const response = {
      patterns: [
        { pattern_id: 'n1', pattern_type: 'RAPID_CANOPY_SIGNAL_DECLINE', window_start: '2024-01-01', window_end: '2024-01-31', status: 'OBSERVED' },
      ],
    };
    const rows = patternsInResponse(response);
    assert.equal(rows[0]?.pattern_type, 'RAPID_CANOPY_SIGNAL_DECLINE');
  });

  it('19. cross-pattern validation renders when present', () => {
    const response = {
      cross_pattern_validations: [
        { validation_id: 'v1', window_start: '2024-01-01', window_end: '2024-01-31', status: 'CONSISTENT', contributing_pattern_ids: ['p1'] },
      ],
    };
    const rows = validationsInResponse(response);
    assert.equal(rows.length, 1);
    assert.equal(rows[0]?.status, 'CONSISTENT');
    assert.deepEqual(rows[0]?.contributing_pattern_ids, ['p1']);
  });

  it('20. no pattern is generated in frontend', () => {
    assert.deepEqual(patternsInResponse({}), []);
    assert.deepEqual(patternsInResponse(null), []);
    assert.deepEqual(patternsInResponse({ patterns: [{ pattern_id: 1 }] }), []);
    assert.deepEqual(validationsInResponse({}), []);
    assert.deepEqual(validationsInResponse(null), []);
    const first = patternsInResponse({ patterns: [] });
    const second = patternsInResponse({ patterns: [] });
    assert.deepEqual(first, second);
  });
});

// --- 21-23. Synthesis ----------------------------------------------------------------

describe('21-23. synthesis relationship stays traceable', () => {
  const summaries = {
    vegetation: {
      domain: 'vegetation',
      statement_count: 1,
      statements: [
        { rule_id: 'R1', domain: 'vegetation', pattern: 'below_context', statement: ' backend wording ', evidence_keys: ['ndvi'], evidence_values: { ndvi: 0.6 }, scientific_basis: 'basis', limitations: [], sufficiency: 'sufficient', conflicts: [] },
      ],
      unavailable_evidence: [],
      sufficiency: 'sufficient',
      limitations: [],
    },
  } as never;
  const cross = [
    { rule_id: 'C1', domain: 'cross_domain', pattern: 'mixed_evidence', statement: ' cross wording ', evidence_keys: ['ndvi', 'ndmi'], evidence_values: {}, scientific_basis: '', limitations: [], sufficiency: 'limited', conflicts: [] },
  ] as never;

  it('21. existing synthesis renders', () => {
    const links = synthesisLinksFor('ndvi', summaries, cross);
    assert.equal(links.length, 2);
    assert.deepEqual(links.map((l) => l.rule_id).sort(), ['C1', 'R1']);
  });

  it('22. evidence relationship preserved when supplied', () => {
    const links = synthesisLinksFor('ndvi', summaries, cross);
    const r1 = links.find((l) => l.rule_id === 'R1');
    assert.equal(r1?.domain, 'vegetation');
    assert.equal(r1?.pattern, 'below_context');
    assert.deepEqual(synthesisLinksFor('ndvi_anomaly', summaries, cross), []);
  });

  it('23. no synthesis generated in frontend', () => {
    assert.deepEqual(synthesisLinksFor('evi', summaries, cross), []);
    assert.deepEqual(synthesisLinksFor('', summaries, cross), []);
    assert.deepEqual(synthesisLinksFor('ndvi', null, null), []);
  });
});

// --- 24-28. Domain-specific identity ---------------------------------------------------

describe('24-28. metric identity is never renamed', () => {
  it('24. NDMI remains NDMI', () => {
    const items = bundleItems(makeBundle('water', [makeItem({ metric_key: 'ndmi', value: 0.1 })]));
    assert.equal(items[0]?.metric_key, 'ndmi');
    assert.notEqual(items[0]?.metric_key, 'ndwi');
    for (const source of readNewSources()) {
      assert.ok(!/NDWI/.test(source));
    }
  });

  it('25. VV/VH/VH-VV/RVI remain distinct', () => {
    const keys = ['vv', 'vh', 'vh_vv', 'rvi'];
    const items = bundleItems({
      name: 'vegetation',
      items: keys.map((k) => makeItem({ metric_key: k })),
    } as never);
    assert.deepEqual(items.map((i) => i.metric_key), keys);
    assert.equal(new Set(items.map((i) => i.metric_key)).size, 4);
  });

  it('26. MODIS LST remains land-surface temperature', () => {
    const meta = thermalSourceMetaFor('LST_PROFILE');
    assert.equal(meta.physicalQuantity, 'land_surface_temperature');
    assert.equal(meta.datasetId, 'MODIS/061/MOD11A2');
    assert.ok(meta.displayLabel.includes('Land Surface'));
  });

  it('27. ERA5 remains modelled 2m air temperature', () => {
    const meta = thermalSourceMetaFor('AIR_TEMPERATURE_PROFILE');
    assert.equal(meta.physicalQuantity, 'air_temperature_2m');
    assert.ok(meta.displayLabel.includes('Air Temperature'));
  });

  it('28. no LST-ERA5 combination', () => {
    for (const source of readStrippedNewSources()) {
      assert.ok(!/\blst\s*[-+*/]\s*\S/i.test(source));
      assert.ok(!/temperature_2m\s*[-+*/]/i.test(source));
      assert.ok(!/LST_Day_1km\s*[-+*/]/i.test(source));
    }
    const section = readAgricultureSource('EvidenceSection.tsx');
    assert.ok(section.includes('stay'));
    assert.ok(section.includes('separate'));
  });
});

// --- Temporal / spatial relationships ---------------------------------------------------

describe('temporal and spatial references are presence only', () => {
  it('observation window travels verbatim', () => {
    assert.equal(
      evidenceWindowText(makeItem({ temporal_start: '2024-01-01', temporal_end: '2024-01-31' })),
      '2024-01-01 → 2024-01-31',
    );
    assert.equal(evidenceWindowText(makeItem({ temporal_start: null, temporal_end: null })), null);
  });

  it('monthly presence is boolean only', () => {
    const temporal = {
      profiles: { ndvi: { metric_key: 'ndvi' } },
      anomalies: { ndvi: { metric_key: 'ndvi' } },
      changes: {},
      radar_profiles: {},
      radar_analyses: {},
      thermal_profiles: {},
      thermal_analyses: {},
    } as never;
    const ref = temporalReferenceFor('ndvi', temporal);
    assert.equal(ref.hasProfile, true);
    assert.equal(ref.hasAnomaly, true);
    assert.equal(ref.hasChange, false);
    assert.deepEqual(temporalReferenceFor('evi', temporal), {
      hasProfile: false, hasAnomaly: false, hasChange: false, hasRadar: false, hasThermal: false,
    });
  });

  it('spatial presence counts exact-key observations', () => {
    const spatial = {
      observations: [
        { cell_id: 'c1', metric_key: 'ndvi' },
        { cell_id: 'c2', metric_key: 'ndvi' },
        { cell_id: 'c1', metric_key: 'ndmi' },
      ],
      summaries: { ndvi: { state: 'NORMAL_AREA', n_usable: 2, n_missing: 0 } },
      concordance: [{ cell_id: 'c1', metrics: ['ndvi', 'ndmi'] }],
      persistence: [{ cell_id: 'c1' }],
    } as never;
    const ref = spatialReferenceFor('ndvi', spatial);
    assert.equal(ref.observationCount, 2);
    assert.equal(ref.summaryState, 'NORMAL_AREA');
    assert.equal(ref.hasConcordance, true);
    const missing = spatialReferenceFor('evi', spatial);
    assert.equal(missing.observationCount, 0);
    assert.equal(missing.summaryState, null);
  });

  it('concordance months pass through verbatim', () => {
    const temporal = {
      concordance: { months: [{ window_start: '2024-01-01', window_end: '2024-01-31', state: 'MULTI_SENSOR_CONCORDANT' }] },
      thermal_concordance: { months: [{ window_start: '2024-01-01', window_end: '2024-01-31', lst_relationship: 'THERMAL_CONCORDANT', air_relationship: 'THERMAL_CONTEXT_CONCORDANT' }] },
    } as never;
    assert.equal(concordanceMonthsOf(temporal)[0]?.state, 'MULTI_SENSOR_CONCORDANT');
    assert.equal(thermalConcordanceMonthsOf(temporal)[0]?.lst_relationship, 'THERMAL_CONCORDANT');
    assert.deepEqual(concordanceMonthsOf(null), []);
  });
});

// --- 29-32. Safeguards --------------------------------------------------------------------

describe('29-32. no frontend science, grades, or endpoints', () => {
  it('29. no grade vocabulary', () => {
    for (const source of readStrippedNewSources()) {
      const masked = source.replace(/z_score/g, 'z');
      assert.ok(!/\brisk\b/i.test(masked));
      assert.ok(!/\bprobability\b/i.test(masked));
      assert.ok(!/\bconfidence\b/i.test(masked));
      assert.ok(!/\bseverity\b/i.test(masked));
      assert.ok(!/\bscore\b/i.test(masked));
      assert.ok(!/risk_score|confidence_score|probability_of|severity_score/i.test(source));
    }
  });

  it('30. no biological interpretation', () => {
    for (const source of readNewSources()) {
      assert.ok(!/pest|disease|heat stress|heat_stress|thermal stress|canopy stress|defoliation|fungal/i.test(source));
      assert.ok(!/canopy temperature|canopyTemperature/i.test(source));
    }
  });

  it('31. no anomaly/persistence/concordance derivation', () => {
    for (const source of readStrippedNewSources()) {
      assert.ok(!/mean\(/.test(source));
      assert.ok(!/median\(/.test(source));
      assert.ok(!/\.reduce\(/.test(source));
      assert.ok(!/Math\.sqrt/.test(source));
      assert.ok(!/Math\.pow/.test(source));
      assert.ok(!/stdev|stddev/i.test(source));
      assert.ok(!/percentile\(/.test(source));
      assert.ok(!/correlation|regression/i.test(source));
      assert.ok(!/threshold/i.test(source));
      assert.ok(!/calculate/i.test(source));
      assert.ok(!/standardizedAnomaly|computeBaseline|calculateZScore|build_baseline|score_profile|zScore/.test(source));
      assert.ok(!/analyze_concordance|evaluate_concordance_month|detect_breakpoint|compute_persistence/.test(source));
      assert.ok(!/interpolate\(/.test(source));
    }
  });

  it('32. no API endpoint added', () => {
    const api = readFileSync(join(srcDir, 'api', 'agriculture.ts'), 'utf-8');
    assert.ok(api.includes('/agriculture/analysis'));
    assert.ok(!/\/evidence|\/patterns|\/provenance|\/synthesis/.test(api.replace('/analysis/synthesis-only', '')));
    for (const source of readStrippedNewSources()) {
      assert.ok(!/fetch\(/.test(source));
      assert.ok(!/axios/i.test(source));
      assert.ok(!/apiPost|apiGet/.test(source));
      assert.ok(!/\/agriculture\/(evidence|patterns|provenance|synthesis)/.test(source));
    }
    const page = readFileSync(join(srcDir, 'pages', 'agriculture', 'DomainPage.tsx'), 'utf-8');
    assert.ok(page.includes('EvidenceSection'));
    assert.ok(!/fetch\(/.test(stripComments(page)));
  });
});

// --- 33-35. Accessibility --------------------------------------------------------------------

describe('33-35. evidence is accessible without color alone', () => {
  it('33. evidence cards use semantic sections', () => {
    const section = readAgricultureSource('EvidenceSection.tsx');
    assert.ok(section.includes('<section'));
    assert.ok(section.includes('<article'));
    assert.ok(section.includes('aria-label'));
  });

  it('34. provenance and details expand accessibly', () => {
    const section = readAgricultureSource('EvidenceSection.tsx');
    assert.ok(section.includes('<details'));
    assert.ok(section.includes('<summary'));
    const drawer = readAgricultureSource('ProvenanceDrawer.tsx');
    assert.ok(drawer.includes('<button'));
  });

  it('35. state available textually', () => {
    const section = readAgricultureSource('EvidenceSection.tsx');
    assert.ok(section.includes('{status}'));
    assert.ok(section.includes('{quality}'));
    assert.ok(section.includes('Insufficient evidence.'));
    assert.ok(section.includes('No evidence is available for this analysis.'));
  });
});
