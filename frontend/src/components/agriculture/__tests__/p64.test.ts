/**
 * P6.4 focused tests — Ground-truth validation UI over the P6.3 response.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p64.test.ts
 * Covers pure validation mapping (section narrowing, status labels,
 * tri-state flags, provenance entries, limitations), backend field
 * preservation, and static guards proving the UI layer computes no
 * science, grades nothing, and calls no new endpoints.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  VALIDATION_STATUSES,
  asValidationSection,
  duplicateReferences,
  optionalText,
  rejectedReferences,
  triStateLabel,
  validationLimitations,
  validationProvenanceEntries,
  validationResults,
  validationStatusLabel,
} from '../validation.ts';
import { formatEvidenceValue } from '../parse.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readAgricultureSource(name: string): string {
  return readFileSync(join(agricultureDir, name), 'utf-8');
}

function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|\s)\/\/.*$/gm, '$1');
}

const NEW_SOURCES = ['validation.ts', 'ValidationSection.tsx'].map(readAgricultureSource);
const STRIPPED = NEW_SOURCES.map(stripComments);

function makeResult(overrides: Record<string, unknown> = {}) {
  return {
    validation_id: 'v:ndvi:2024-01-01:2024-01-31:r1c1:obs-1',
    target_id: 'ndvi:2024-01-01:2024-01-31:r1c1:obs-1',
    observation_id: 'obs-1',
    metric_key: 'ndvi',
    domain: 'vegetation',
    analysis_id: null,
    analysis_window_start: '2024-01-01',
    analysis_window_end: '2024-01-31',
    analysis_cell_id: 'r1c1',
    analysis_value: 0.62,
    analysis_unit: 'index',
    analysis_state: 'observed',
    reference_variable: 'observed_stress',
    reference_value: 2.0,
    reference_unit: 'index',
    reference_state: 'present',
    reference_source: 'field_observation',
    reference_method: 'visual inspection',
    reference_time: '2024-01-15',
    temporal_relationship: 'EXACT_TEMPORAL_MATCH',
    spatial_relationship: 'EXACT_SPATIAL_CELL_MATCH',
    metric_relationship: 'METRIC_MATCH',
    states_agree: null,
    values_comparable: true,
    status: 'MATCHED_REFERENCE',
    linkage_reason: 'analysis and reference share metric, overlapping window, and cell',
    contract_version: 'P61_V1',
    engine_version: 'P62_V1',
    provenance: { reference_source: 'field_observation', plot: 'A' },
    limitations: ['single visit'],
    ...overrides,
  } as never;
}

function makeSection(overrides: Record<string, unknown> = {}) {
  return {
    results: [makeResult()],
    rejected_references: [],
    duplicates: [],
    limitations: [],
    contract_version: 'P61_V1',
    engine_version: 'P62_V1',
    ...overrides,
  } as never;
}

// --- 1-2. Section presence ----------------------------------------------------------

describe('1-2. validation absent vs present', () => {
  it('1. validation absent narrows to null', () => {
    assert.equal(asValidationSection(null), null);
    assert.equal(asValidationSection(undefined), null);
    assert.equal(asValidationSection('nope'), null);
    assert.equal(asValidationSection({}), null);
    assert.deepEqual(validationResults(null), []);
    assert.deepEqual(validationResults(undefined), []);
  });

  it('2. validation present narrows and preserves order', () => {
    const section = makeSection({
      results: [makeResult({ validation_id: 'v:a' }), makeResult({ validation_id: 'v:b' })],
    });
    const narrowed = asValidationSection(section);
    assert.ok(narrowed);
    assert.deepEqual(
      validationResults(narrowed).map((r) => r.validation_id),
      ['v:a', 'v:b'],
    );
  });
});

// --- 3-8. Six backend statuses --------------------------------------------------------

describe('3-8. six backend statuses stay descriptive', () => {
  it('3. matched result keeps neutral label', () => {
    assert.equal(validationStatusLabel('MATCHED_REFERENCE'), 'Matched reference');
    const [result] = validationResults(makeSection());
    assert.equal(result?.status, 'MATCHED_REFERENCE');
    assert.equal(result?.metric_key, 'ndvi');
  });

  it('4. mismatched result is never called wrong', () => {
    assert.equal(validationStatusLabel('MISMATCHED_REFERENCE'), 'Mismatched reference');
    for (const source of NEW_SOURCES) {
      assert.ok(!/['"]Wrong['"]/.test(source));
    }
  });

  it('5. insufficient analysis label', () => {
    assert.equal(validationStatusLabel('INSUFFICIENT_ANALYSIS'), 'Insufficient analysis');
  });

  it('6. insufficient reference label', () => {
    assert.equal(validationStatusLabel('INSUFFICIENT_REFERENCE'), 'Insufficient reference');
  });

  it('7. unavailable label', () => {
    assert.equal(validationStatusLabel('UNAVAILABLE'), 'Unavailable');
  });

  it('8. not validated label', () => {
    assert.equal(validationStatusLabel('NOT_VALIDATED'), 'Not validated');
    assert.deepEqual(VALIDATION_STATUSES, [
      'MATCHED_REFERENCE',
      'MISMATCHED_REFERENCE',
      'INSUFFICIENT_REFERENCE',
      'INSUFFICIENT_ANALYSIS',
      'UNAVAILABLE',
      'NOT_VALIDATED',
    ]);
  });

  it('unknown states pass through verbatim, never invented', () => {
    assert.equal(validationStatusLabel('SOMETHING_NEW'), 'SOMETHING_NEW');
    assert.equal(validationStatusLabel(''), '—');
    assert.equal(validationStatusLabel(null), '—');
  });
});

// --- 9-10. Rejected and duplicate references ---------------------------------------------

describe('9-10. rejected and duplicate references', () => {
  it('9. rejected references keep index, id, and reasons', () => {
    const section = makeSection({
      results: [],
      rejected_references: [{ index: 1, observation_id: 'obs-9', reasons: ['unknown_variable'] }],
    });
    const rejected = rejectedReferences(section);
    assert.equal(rejected.length, 1);
    assert.equal(rejected[0]?.index, 1);
    assert.equal(rejected[0]?.observation_id, 'obs-9');
    assert.deepEqual(rejected[0]?.reasons, ['unknown_variable']);
  });

  it('10. duplicate references keep identity fields and reason', () => {
    const section = makeSection({
      duplicates: [{
        observation_id: 'obs-1',
        kept_index: 0,
        dropped_indices: [2],
        reason: 'duplicate observation_id; first occurrence kept',
      }],
    });
    const duplicates = duplicateReferences(section);
    assert.equal(duplicates.length, 1);
    assert.equal(duplicates[0]?.observation_id, 'obs-1');
    assert.equal(duplicates[0]?.kept_index, 0);
    assert.deepEqual(duplicates[0]?.dropped_indices, [2]);
    assert.ok((duplicates[0]?.reason ?? '').length > 0);
  });
});

// --- 11-14. Nulls and tri-state flags ------------------------------------------------------

describe('11-14. nulls stay unavailable, flags stay words', () => {
  it('11. null analysis value renders as unavailable', () => {
    const [result] = validationResults(makeSection({
      results: [makeResult({ analysis_value: null })],
    }));
    assert.equal(result?.analysis_value, null);
    assert.equal(formatEvidenceValue(result?.analysis_value), '—');
  });

  it('12. null reference value renders as unavailable', () => {
    const [result] = validationResults(makeSection({
      results: [makeResult({ reference_value: null })],
    }));
    assert.equal(result?.reference_value, null);
    assert.equal(formatEvidenceValue(result?.reference_value), '—');
  });

  it('13. states_agree null renders as unavailable', () => {
    assert.equal(triStateLabel(null), '—');
    assert.equal(triStateLabel(undefined), '—');
    assert.equal(triStateLabel('yes'), '—');
  });

  it('14. values_comparable renders as words', () => {
    assert.equal(triStateLabel(true), 'yes');
    assert.equal(triStateLabel(false), 'no');
    assert.equal(triStateLabel(null), '—');
  });

  it('optional text renders markers for missing strings', () => {
    assert.equal(optionalText('ndvi'), 'ndvi');
    assert.equal(optionalText(''), '—');
    assert.equal(optionalText(null), '—');
    assert.equal(optionalText(42), '—');
  });
});

// --- 15-16. Provenance and limitations -------------------------------------------------------

describe('15-16. provenance and limitations render verbatim', () => {
  it('15. provenance rendering keeps backend keys and values', () => {
    const entries = validationProvenanceEntries({
      reference_source: 'field_observation',
      plot: 'A',
      count: 3,
      flag: true,
      missing: null,
      nested: { deep: 1 },
    });
    const byKey = Object.fromEntries(entries.map((e) => [e.key, e.value]));
    assert.equal(byKey.reference_source, 'field_observation');
    assert.equal(byKey.plot, 'A');
    assert.equal(byKey.count, '3');
    assert.equal(byKey.flag, 'yes');
    assert.equal(byKey.missing, '—');
    assert.equal(byKey.nested, '—');
    assert.deepEqual(validationProvenanceEntries(null), []);
    assert.deepEqual(validationProvenanceEntries(undefined), []);
  });

  it('16. limitations rendering keeps backend strings', () => {
    const section = makeSection({ limitations: ['single visit', 42, null] });
    assert.deepEqual(validationLimitations(section), ['single visit']);
    assert.deepEqual(validationLimitations(null), []);
  });
});

// --- Relationships, identity, ordering, empty states -------------------------------------------

describe('relationships, identity, ordering, empty states', () => {
  it('relationships render verbatim', () => {
    const [result] = validationResults(makeSection());
    assert.equal(result?.temporal_relationship, 'EXACT_TEMPORAL_MATCH');
    assert.equal(result?.spatial_relationship, 'EXACT_SPATIAL_CELL_MATCH');
    assert.equal(result?.metric_relationship, 'METRIC_MATCH');
    const component = readAgricultureSource('ValidationSection.tsx');
    assert.ok(component.includes('{optionalText(result.temporal_relationship)}'));
    assert.ok(component.includes('{optionalText(result.spatial_relationship)}'));
    assert.ok(component.includes('{optionalText(result.metric_relationship)}'));
  });

  it('reference source, method, and time preserved', () => {
    const [result] = validationResults(makeSection());
    assert.equal(result?.reference_source, 'field_observation');
    assert.equal(result?.reference_method, 'visual inspection');
    assert.equal(result?.reference_time, '2024-01-15');
    assert.equal(result?.observation_id, 'obs-1');
  });

  it('backend order preserved with no reordering', () => {
    for (const source of STRIPPED) {
      assert.ok(!/\.sort\s*\(/.test(source));
    }
    const section = makeSection({
      results: [
        makeResult({ validation_id: 'v:z', status: 'UNAVAILABLE' }),
        makeResult({ validation_id: 'v:a', status: 'MATCHED_REFERENCE' }),
      ],
    });
    assert.deepEqual(
      validationResults(section).map((r) => r.validation_id),
      ['v:z', 'v:a'],
    );
  });

  it('empty results render an honest empty state, never fabricated rows', () => {
    const section = makeSection({ results: [] });
    assert.deepEqual(validationResults(section), []);
    const component = readAgricultureSource('ValidationSection.tsx');
    assert.ok(component.includes('No validation results in this response.'));
  });

  it('null section renders nothing', () => {
    const component = readAgricultureSource('ValidationSection.tsx');
    assert.ok(component.includes('if (!validation'));
    assert.ok(component.includes('return null'));
  });

  it('hub renders the section only from response data', () => {
    const hub = readFileSync(join(srcDir, 'pages', 'Agriculture.tsx'), 'utf-8');
    assert.ok(hub.includes('ValidationSection'));
    assert.ok(hub.includes('result.validation'));
  });

  it('status is text, never color alone', () => {
    const component = readAgricultureSource('ValidationSection.tsx');
    assert.ok(component.includes('<code>{result.status}</code>'));
    assert.ok(component.includes('validationStatusLabel(result.status)'));
  });
});

// --- 17-18 + safeguards --------------------------------------------------------------------------

describe('17-18. safeguards: no grades, no computation, no endpoints', () => {
  it('17. no fabricated score, risk, or confidence', () => {
    for (const source of STRIPPED) {
      assert.ok(!/\bscore\b/i.test(source.replace(/scores or grades/g, '')));
      assert.ok(!/\brisk\b/i.test(source));
      assert.ok(!/\bconfidence\b/i.test(source));
      assert.ok(!/\baccuracy\b/i.test(source));
      assert.ok(!/\bprobability\b/i.test(source));
      assert.ok(!/\bseverity\b/i.test(source));
      assert.ok(!/\bpass\b/i.test(source.replace(/passes through|pass through/g, '')));
      assert.ok(!/\bfail\b/i.test(source));
      assert.ok(!/['"]Correct['"]/.test(source));
    }
  });

  it('18. no frontend recalculation', () => {
    for (const source of STRIPPED) {
      assert.ok(!/accuracy|precision|recall/i.test(source));
      assert.ok(!/correlation|regression/i.test(source));
      assert.ok(!/percentile\s*\(/i.test(source));
      assert.ok(!/\bmean\s*\(/i.test(source));
      assert.ok(!/\bmedian\s*\(/i.test(source));
      assert.ok(!/interpolat/i.test(source));
      assert.ok(!/Math\.(sqrt|pow|mean|std)/.test(source));
      assert.ok(!/\.reduce\s*\(/.test(source));
    }
  });

  it('no new endpoints or data fetching', () => {
    for (const source of NEW_SOURCES) {
      assert.ok(!/['"`]\/(ground-truth|validation|evidence|provenance)\b/.test(source));
      assert.ok(!/fetch\s*\(/.test(source));
      assert.ok(!/apiPost|apiGet|axios/.test(source));
    }
  });

  it('no ranking or biological inference', () => {
    for (const source of STRIPPED) {
      assert.ok(!/\brank/i.test(source));
      assert.ok(!/\bbest\b/i.test(source));
      assert.ok(!/pest|disease/i.test(source));
      assert.ok(!/NDWI/.test(source));
      assert.ok(!/caus/i.test(source));
    }
  });

  it('types mirror backend fields exactly', () => {
    const types = readFileSync(join(srcDir, 'types', 'index.ts'), 'utf-8');
    for (const field of [
      'validation_id', 'target_id', 'observation_id', 'metric_key', 'domain',
      'analysis_window_start', 'analysis_window_end', 'analysis_cell_id',
      'analysis_value', 'analysis_unit', 'analysis_state',
      'reference_variable', 'reference_value', 'reference_unit', 'reference_state',
      'reference_source', 'reference_method', 'reference_time',
      'temporal_relationship', 'spatial_relationship', 'metric_relationship',
      'states_agree', 'values_comparable', 'linkage_reason',
      'contract_version', 'engine_version', 'provenance', 'limitations',
    ]) {
      assert.ok(types.includes(field), field);
    }
    for (const field of [
      'rejected_references', 'duplicates', 'kept_index', 'dropped_indices', 'reasons',
    ]) {
      assert.ok(types.includes(field), field);
    }
    assert.ok(types.includes('validation?: ValidationSection | null'));
    assert.ok(!/ValidationResultModel/.test(types));
  });
});
