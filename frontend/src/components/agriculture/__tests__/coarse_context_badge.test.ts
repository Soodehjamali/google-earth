import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { isCoarseContext, formatCoarseResolutionFa } from '../coarseGating.ts';
import type { EvidenceItemResponse, ProvenanceResponse } from '../../../types/index.ts';

describe('Phase 2 Task 2.1: CoarseContextBadge & Support Quality Gating', () => {
  it('1. identifies coarse context items correctly', () => {
    const coarseItem: EvidenceItemResponse = {
      metric_key: 'temperature_mean',
      value: 23.5,
      unit: '°C',
      status: 'modelled',
      quality: 'moderate',
      quality_state: 'coarse_context',
      display_name: 'دمای هوا',
      is_usable: true,
      is_proxy: false,
    };
    assert.strictEqual(isCoarseContext(coarseItem), true);

    const validItem: EvidenceItemResponse = {
      metric_key: 'ndvi',
      value: 0.45,
      unit: '',
      status: 'observed',
      quality: 'good',
      quality_state: 'valid',
      display_name: 'شاخص پوشش گیاهی',
      is_usable: true,
      is_proxy: false,
    };
    assert.strictEqual(isCoarseContext(validItem), false);

    const provCoarse: ProvenanceResponse = {
      aggregation_method: 'spatial mean',
      measurement_basis: 'modelled',
      quality_level: 'moderate',
      quality_state: 'coarse_context',
      native_resolution_m: 11132,
      temporal_kind: 'observation',
    };
    assert.strictEqual(isCoarseContext(provCoarse), true);
  });

  it('2. formats Persian badge resolution string accurately', () => {
    const text11km = formatCoarseResolutionFa(11132);
    assert.ok(text11km.includes('کیلومتر') || text11km.includes('11'));

    const text9km = formatCoarseResolutionFa(9000);
    assert.ok(text9km.includes('کیلومتر') || text9km.includes('9'));

    const text500m = formatCoarseResolutionFa(500);
    assert.ok(text500m.includes('متر') || text500m.includes('500'));

    const textNull = formatCoarseResolutionFa(null);
    assert.strictEqual(textNull, 'زمینه منطقه‌ای');
  });
});
