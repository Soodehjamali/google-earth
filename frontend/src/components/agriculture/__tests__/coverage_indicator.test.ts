import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  toPersianDigits,
  formatCoveragePrimaryFa,
  formatCoverageSecondaryFa,
  formatPercentageFa,
  getCoverageCounts,
  partitionMetricsForInventory,
} from '../coverageUtils.ts';
import type { AgriculturalAnalysisResponse, EvidenceBundleResponse } from '../../../types/index.ts';

describe('Coverage Indicator & Utilities (Phase 2 Task 2.3)', () => {
  it('converts digits to Persian characters accurately', () => {
    assert.equal(toPersianDigits(1234567890), '۱۲۳۴۵۶۷۸۹۰');
    assert.equal(toPersianDigits('35 of 118'), '۳۵ of ۱۱۸');
  });

  it('formats primary and secondary coverage lines with Persian phrasing', () => {
    const primary = formatCoveragePrimaryFa(42, 118);
    assert.equal(primary, '۴۲ از ۱۱۸ شاخص دادهٔ معتبر دارند');

    const secondary = formatCoverageSecondaryFa(15);
    assert.equal(secondary, '+ ۱۵ شاخص زمینه منطقه‌ای');

    const pct = formatPercentageFa(42 / 118);
    assert.equal(pct, '۳۶٪');
  });

  it('preserves strict separation: coarse context (K) is never counted in valid (N)', () => {
    const mockResponse: AgriculturalAnalysisResponse = {
      analysis_id: 'test-123',
      created_at: '2026-10-15T00:00:00Z',
      polygon_area_ha: 12.5,
      coverage: {
        valid: 40,
        coarse_context: 12,
        unavailable: 66,
        total: 118,
        valid_ratio: 0.339,
        by_domain: {
          climate: {
            valid: 10,
            coarse_context: 12,
            unavailable: 2,
            total: 24,
            valid_ratio: 0.4167,
          },
        },
      },
    };

    const counts = getCoverageCounts(mockResponse);
    assert.equal(counts.valid, 40);
    assert.equal(counts.coarse_context, 12);
    assert.equal(counts.total, 118);
    // Ratio must be valid / total, NOT (valid + coarse) / total
    assert.equal(counts.valid_ratio, 0.339);
    assert.notEqual(counts.valid, counts.valid + counts.coarse_context);
  });

  it('correctly derives coverage counts from bundles if coverage field is missing (legacy report)', () => {
    const legacyResponse: AgriculturalAnalysisResponse = {
      analysis_id: 'legacy-123',
      created_at: '2026-10-15T00:00:00Z',
      polygon_area_ha: 10.0,
      evidence_bundles: {
        vegetation: {
          domain: 'vegetation',
          is_sufficient: true,
          evidence_count: 2,
          quality_level: 'A',
          summary: 'Vegetation summary',
          items: [
            {
              metric_key: 'ndvi',
              domain: 'vegetation',
              value: 0.65,
              evidence_level: 'A',
              is_usable: true,
              quality_state: 'valid',
            },
            {
              metric_key: 'evi',
              domain: 'vegetation',
              value: 0.45,
              evidence_level: 'A',
              is_usable: true,
              quality_state: 'valid',
            },
          ],
          unavailable: ['ndre'],
        },
        climate: {
          domain: 'climate',
          is_sufficient: true,
          evidence_count: 2,
          quality_level: 'B',
          summary: 'Climate summary',
          items: [
            {
              metric_key: 'era5_temp',
              domain: 'climate',
              value: 28.5,
              evidence_level: 'B',
              is_usable: true,
              quality_state: 'coarse_context',
              native_resolution_m: 11132,
            },
            {
              metric_key: 'solar_radiation',
              domain: 'climate',
              value: null,
              evidence_level: 'C',
              is_usable: false,
              quality_state: 'unavailable',
            },
          ],
          unavailable: [],
        },
      },
    };

    const counts = getCoverageCounts(legacyResponse);
    // vegetation: 2 valid, 1 unavailable (ndre) = 3 total
    // climate: 1 coarse_context, 1 unavailable (solar_radiation) = 2 total
    // sum: valid = 2, coarse = 1, unavailable = 2, total = 5
    assert.equal(counts.valid, 2);
    assert.equal(counts.coarse_context, 1);
    assert.equal(counts.unavailable, 2);
    assert.equal(counts.total, 5);
    assert.equal(counts.valid_ratio, 0.4);

    assert.equal(counts.by_domain?.vegetation?.valid, 2);
    assert.equal(counts.by_domain?.vegetation?.coarse_context, 0);
    assert.equal(counts.by_domain?.vegetation?.unavailable, 1);

    assert.equal(counts.by_domain?.climate?.valid, 0);
    assert.equal(counts.by_domain?.climate?.coarse_context, 1);
    assert.equal(counts.by_domain?.climate?.unavailable, 1);
  });

  it('partitions evidence items into valid, coarse_context, and unavailable buckets', () => {
    const bundles: Record<string, EvidenceBundleResponse> = {
      water: {
        domain: 'water',
        is_sufficient: true,
        evidence_count: 3,
        quality_level: 'B',
        summary: 'Water summary',
        items: [
          {
            metric_key: 'ndwi',
            display_name: 'شاخص رطوبت NDWI',
            domain: 'water',
            value: 0.22,
            unit: '',
            evidence_level: 'A',
            is_usable: true,
            quality_state: 'valid',
            provenance: {
              source_dataset_name: 'Sentinel-2',
              native_resolution_m: 10,
            },
          },
          {
            metric_key: 'smap_surface_moisture',
            display_name: 'رطوبت سطحی SMAP',
            domain: 'water',
            value: 0.18,
            unit: 'm3/m3',
            evidence_level: 'B',
            is_usable: true,
            quality_state: 'coarse_context',
            provenance: {
              source_dataset_name: 'NASA SMAP',
              native_resolution_m: 9000,
            },
          },
          {
            metric_key: 'canopy_water_index',
            display_name: 'شاخص آب پوشش',
            domain: 'water',
            value: null,
            unit: '',
            evidence_level: 'B',
            is_usable: false,
            quality_state: 'unavailable',
            unavailable_reason: 'پوشش ابر یا عدم دسترسی به داده',
          },
        ],
        unavailable: ['et_actual'],
      },
    };

    const { validMetrics, coarseMetrics, unavailableMetrics } = partitionMetricsForInventory(bundles);

    assert.equal(validMetrics.length, 1);
    assert.equal(validMetrics[0].metricKey, 'ndwi');
    assert.equal(validMetrics[0].qualityState, 'valid');

    assert.equal(coarseMetrics.length, 1);
    assert.equal(coarseMetrics[0].metricKey, 'smap_surface_moisture');
    assert.equal(coarseMetrics[0].qualityState, 'coarse_context');
    assert.equal(coarseMetrics[0].nativeResolutionM, 9000);

    assert.equal(unavailableMetrics.length, 2);
    const unavKeys = unavailableMetrics.map((m) => m.metricKey);
    assert.ok(unavKeys.includes('canopy_water_index'));
    assert.ok(unavKeys.includes('et_actual'));
  });
});
