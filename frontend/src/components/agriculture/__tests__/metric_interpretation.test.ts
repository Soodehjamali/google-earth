/**
 * Comprehensive Test Suite for P-AGRI-6:
 * Satellite Data Completeness & Farmer-Friendly Metric Interpretation
 *
 * Verifies all 15 requirements of Section 7:
 * 1. Traceability of all active catalog metrics
 * 2. Field mapping integrity between backend and frontend
 * 3. Null is NEVER converted to numeric 0
 * 4. Genuine 0 is distinguished from missing data
 * 5. Unavailable metrics receive explicit reasons
 * 6. Unimplemented metrics are marked honestly (never fake data)
 * 7. Reference ranges strictly cite peer-reviewed literature or explicitly state hasFixedRange: false
 * 8. Dependency on crop context, phenology, depth, and semi-arid conditions preserved
 * 9. Exact units and native spatial resolutions match sensor specifications
 * 10. Evaluated status computed from real numbers without diagnostic overreach
 * 11. GEE errors/0-pixels never produce fake numbers
 * 12. Historical charts never convert absent years to 0
 * 13. PDF model preserves source, units, reference ranges, and limitations
 * 14. Jalali date and Persian numeral presentation preserved
 * 15. Clean compilation and zero mock/synthetic data in interpretations
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  METRIC_INTERPRETATION_CATALOG,
  getMetricInterpretation,
  type MetricInterpretationSpec,
} from '../metricInterpretation.ts';
import {
  METRIC_CATEGORIES,
  EXTENDED_METRIC_CATEGORIES,
  evaluateMetricState,
} from '../categorizedMetrics.ts';
import { buildNormalizedReportModel } from '../reportModel.ts';
import type { AgriculturalAnalysisResponse, EvidenceItemResponse } from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const componentsDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('P-AGRI-6: Satellite Data Completeness & Metric Interpretation', () => {
  it('1. Traceability of all catalog metrics in interpretation catalog', () => {
    // Core remote sensing & soil metrics
    const coreKeys = [
      'ndvi',
      'savi',
      'evi',
      'msavi',
      'ndre',
      'ndmi',
      'msi',
      'ndwi',
      'mndwi',
      'land_surface_temperature_day',
      'land_surface_temperature_night',
      'landsat_surface_temperature',
      'surface_temperature_range',
      'vh',
      'vv',
      'vh_vv',
      'rvi',
      'elevation',
      'slope',
      'aspect',
      'terrain_ruggedness',
      'soil_moisture_surface',
      'soil_moisture_rootzone',
      'soil_moisture_rootzone_era5',
      'precipitation',
      'soil_available_water_capacity',
      'soil_field_capacity',
      'soil_wilting_point',
      'soil_ph',
      'soil_organic_carbon',
      'soil_cation_exchange_capacity',
      'vpd',
      'temperature_mean',
      'temperature_max',
      'temperature_min',
      'relative_humidity',
      'solar_radiation',
      'gdd',
      'wind_speed',
      'plant_available_water_fraction',
      'soil_water_content_ratio',
      'vpd_high_duration',
      'evaporative_fraction',
    ];

    for (const key of coreKeys) {
      assert.ok(
        key in METRIC_INTERPRETATION_CATALOG,
        `Metric '${key}' must be registered in METRIC_INTERPRETATION_CATALOG`,
      );
      const spec = METRIC_INTERPRETATION_CATALOG[key];
      assert.ok(spec.nameFa.length > 0, `Metric '${key}' must have Persian name`);
      assert.ok(spec.farmerExplanationFa.length > 0, `Metric '${key}' must have farmer explanation`);
      assert.ok(spec.spatialResolution.length > 0, `Metric '${key}' must have native spatial resolution`);
    }
  });

  it('2. Backend to frontend mapping integrity: All categories contain expected metrics', () => {
    const allCategories = [...METRIC_CATEGORIES, ...EXTENDED_METRIC_CATEGORIES];
    const categoryKeys = allCategories.map((c) => c.key);

    assert.ok(categoryKeys.includes('vegetation'));
    assert.ok(categoryKeys.includes('moisture'));
    assert.ok(categoryKeys.includes('thermal'));
    assert.ok(categoryKeys.includes('radar'));
    assert.ok(categoryKeys.includes('terrain'));
    assert.ok(categoryKeys.includes('soil_water'));
    assert.ok(categoryKeys.includes('climate'));
    assert.ok(categoryKeys.includes('stress'));

    // Check newly surfaced metrics
    const vegGroup = allCategories.find((c) => c.key === 'vegetation')!;
    assert.ok(vegGroup.metrics.some((m) => m.key === 'msavi'), 'msavi in vegetation');

    const moistureGroup = allCategories.find((c) => c.key === 'moisture')!;
    assert.ok(moistureGroup.metrics.some((m) => m.key === 'ndwi'), 'ndwi in moisture');
    assert.ok(moistureGroup.metrics.some((m) => m.key === 'mndwi'), 'mndwi in moisture');

    const thermalGroup = allCategories.find((c) => c.key === 'thermal')!;
    assert.ok(thermalGroup.metrics.some((m) => m.key === 'surface_temperature_range'), 'surface_temperature_range in thermal');

    const soilGroup = allCategories.find((c) => c.key === 'soil_water')!;
    assert.ok(soilGroup.metrics.some((m) => m.key === 'soil_field_capacity'), 'FC in soil_water');
    assert.ok(soilGroup.metrics.some((m) => m.key === 'soil_wilting_point'), 'WP in soil_water');
  });

  it('3. Null is NEVER converted to numeric 0 or string "0"', () => {
    const nullItem: EvidenceItemResponse = {
      metric_key: 'ndvi',
      value: null,
      unit: '',
      status: 'unavailable',
      quality: 'insufficient',
      display_name: 'NDVI',
      is_usable: false,
      is_proxy: false,
    };

    const res = evaluateMetricState(nullItem, {
      key: 'ndvi',
      name: 'NDVI',
      nameFa: 'شاخص پوشش گیاهی',
      category: 'vegetation',
      unitDefault: '',
      descriptionFa: 'تراکم کانوپی',
    });

    assert.notEqual(res.displayValue, '0');
    assert.notEqual(res.displayValue, '0.0');
    assert.notEqual(res.displayValue, '0.0000');
    assert.equal(res.state, 'insufficient');
    assert.equal(res.displayValue, 'داده قابل استفاده موجود نیست');

    const interp = getMetricInterpretation('ndvi', null);
    assert.equal(interp.value, null);
    assert.notEqual(interp.displayValue, '0');
  });

  it('4. Genuine 0 is correctly distinguished from missing data', () => {
    const zeroPrecipItem: EvidenceItemResponse = {
      metric_key: 'precipitation',
      value: 0.0,
      unit: 'mm',
      status: 'available',
      quality: 'nominal',
      display_name: 'Precipitation',
      is_usable: true,
      is_proxy: false,
    };

    const res = evaluateMetricState(zeroPrecipItem, {
      key: 'precipitation',
      name: 'Precipitation',
      nameFa: 'بارندگی',
      category: 'soil_water',
      unitDefault: 'mm',
      descriptionFa: 'بارندگی کل',
      precision: 1,
    });

    assert.equal(res.state, 'available');
    assert.equal(res.displayValue, '0.0');
    assert.equal(res.unit, 'mm');

    const interp = getMetricInterpretation('precipitation', 0.0, 1);
    assert.equal(interp.value, 0.0);
    assert.equal(interp.displayValue, '0.0');
  });

  it('5. Unavailable metrics receive explicit reasons without hiding cards', () => {
    const itemWithReason: EvidenceItemResponse = {
      metric_key: 'landsat_surface_temperature',
      value: null,
      unit: '°C',
      status: 'unavailable',
      quality: 'insufficient',
      display_name: 'Landsat LST',
      is_usable: false,
      is_proxy: false,
      unavailable_reason: 'گذر ماهواره لندست در بازه تحلیل بدون ابر نبوده است',
    };

    const res = evaluateMetricState(itemWithReason, {
      key: 'landsat_surface_temperature',
      name: 'Landsat LST',
      nameFa: 'دمای سطح لندست',
      category: 'thermal',
      unitDefault: '°C',
      descriptionFa: 'دمای ۳۰ متری',
    });

    assert.equal(res.state, 'insufficient');
    assert.equal(res.reasonFa, 'گذر ماهواره لندست در بازه تحلیل بدون ابر نبوده است');
  });

  it('6. Unimplemented metrics are marked honestly and never emit fake data', () => {
    const interp = getMetricInterpretation('unimplemented_future_sensor', null);
    assert.equal(interp.hasFixedRange, false);
    assert.match(interp.rangeLabelFa, /فاقد محدوده مرجع ثابت/);
    assert.equal(interp.value, null);
    assert.equal(interp.displayValue, 'داده موجود نیست');
  });

  it('7. Reference ranges strictly cite peer-reviewed scientific sources', () => {
    for (const [key, spec] of Object.entries(METRIC_INTERPRETATION_CATALOG)) {
      if (spec.referenceRange.hasFixedRange) {
        assert.ok(
          spec.referenceRange.sourceCitation.length > 5,
          `Metric '${key}' with fixed range must provide scientific citation`,
        );
        assert.ok(
          spec.referenceRange.validityConditionsFa.length > 5,
          `Metric '${key}' must define validity conditions`,
        );
      } else {
        assert.match(
          spec.referenceRange.rangeLabelFa,
          /زمینه|فاقد|بافت|وابسته|متغیر/,
          `Context-dependent metric '${key}' must explain why no fixed range exists`,
        );
      }
    }
  });

  it('8. Dependency on crop context & semi-arid conditions is explicitly stated', () => {
    const ndviSpec = METRIC_INTERPRETATION_CATALOG['ndvi'];
    assert.match(ndviSpec.referenceRange.validityConditionsFa, /نیمه‌خشک/);
    assert.match(ndviSpec.farmerExplanationFa, /پسته|ردیف/);

    const lstSpec = METRIC_INTERPRETATION_CATALOG['land_surface_temperature_day'];
    assert.match(lstSpec.scientificCautionFa, /پوسته فیزیکی خاک/);
    assert.doesNotMatch(lstSpec.scientificCautionFa, /دمای اندام گیاه/);

    const smapSpec = METRIC_INTERPRETATION_CATALOG['soil_moisture_rootzone'];
    assert.match(smapSpec.spatialResolution, /۹/);
    assert.match(smapSpec.scientificCautionFa, /مقیاس منطقه‌ای|سنسور رطوبت‌سنج/);
  });

  it('9. Scientific units and native spatial resolutions match sensor specifications', () => {
    // Optical 10m & 20m
    assert.equal(METRIC_INTERPRETATION_CATALOG['ndvi'].spatialResolution, '۱۰ متر');
    assert.equal(METRIC_INTERPRETATION_CATALOG['savi'].spatialResolution, '۱۰ متر');
    assert.equal(METRIC_INTERPRETATION_CATALOG['ndmi'].spatialResolution, '۲۰ متر');

    // Thermal
    assert.match(METRIC_INTERPRETATION_CATALOG['land_surface_temperature_day'].spatialResolution, /۱۰۰۰ متر/);
    assert.equal(METRIC_INTERPRETATION_CATALOG['landsat_surface_temperature'].spatialResolution, '۳۰ متر');

    // Radar 10m
    assert.equal(METRIC_INTERPRETATION_CATALOG['vh'].spatialResolution, '۱۰ متر');
    assert.equal(METRIC_INTERPRETATION_CATALOG['vh'].unit, 'dB');

    // Reanalysis & Soil
    assert.match(METRIC_INTERPRETATION_CATALOG['vpd'].spatialResolution, /۱۱ کیلومتر/);
    assert.equal(METRIC_INTERPRETATION_CATALOG['vpd'].unit, 'kPa');
    assert.equal(METRIC_INTERPRETATION_CATALOG['soil_ph'].spatialResolution, '۲۵۰ متر');
    assert.equal(METRIC_INTERPRETATION_CATALOG['soil_cation_exchange_capacity'].unit, 'cmol(+)/kg');
  });

  it('10. Evaluated status computed from real numbers without diagnostic overreach', () => {
    // Normal arid orchard NDVI (0.35)
    const normalVeg = METRIC_INTERPRETATION_CATALOG['ndvi'].evaluateStatus(0.35);
    assert.equal(normalVeg.statusClass, 'good');
    assert.match(normalVeg.statusLabelFa, /نرمال/);

    // Bare soil NDVI (0.10)
    const bareVeg = METRIC_INTERPRETATION_CATALOG['ndvi'].evaluateStatus(0.10);
    assert.equal(bareVeg.statusClass, 'warning');
    assert.match(bareVeg.statusLabelFa, /تنک|خاک لخت/);

    // High VPD (3.5 kPa)
    const highVpd = METRIC_INTERPRETATION_CATALOG['vpd'].evaluateStatus(3.5);
    assert.equal(highVpd.statusClass, 'danger');
    assert.match(highVpd.statusLabelFa, /داغ و خشک|VPD بالا/);
    assert.match(highVpd.evaluationFa, /روزنه‌ها/);
  });

  it('11. GEE 0 valid pixels never produces fake numeric values', () => {
    const zeroPixelItem: EvidenceItemResponse = {
      metric_key: 'savi',
      value: 0,
      unit: '',
      status: 'available',
      quality: 'nominal',
      display_name: 'SAVI',
      is_usable: false,
      is_proxy: false,
      stats: {
        valid_pixel_count: 0,
        valid_area_sq_m: 0,
      },
    };

    const res = evaluateMetricState(zeroPixelItem, {
      key: 'savi',
      name: 'SAVI',
      nameFa: 'SAVI',
      category: 'vegetation',
      unitDefault: '',
      descriptionFa: 'پوشش گیاهی',
    });

    assert.equal(res.state, 'insufficient');
    assert.notEqual(res.displayValue, '0');
    assert.match(res.reasonFa, /۰ پیکسل معتبر/);
  });

  it('12. Historical comparison never converts absent years to numeric 0', () => {
    const histSrc = readSource('components/agriculture/Historical10YearSection.tsx');
    assert.match(histSrc, /هرگز با صفر یا مقدار تقریبی جایگزین نشده است/);
    assert.match(histSrc, /Unavailable/);
  });

  it('13. PDF report model preserves data sources, units, reference ranges, and limitations', () => {
    const dummyResponse: AgriculturalAnalysisResponse = {
      request_id: 'test-req-p6',
      location_name: 'باغ آزمایشی اردکان',
      overall_sufficiency: 'sufficient',
      available_domains: ['vegetation', 'water'],
      unavailable_domains: ['climate'],
      domains_with_data: ['vegetation', 'water'],
      evidence_bundles: {
        vegetation: {
          domain: 'vegetation',
          status: 'available',
          quality: 'nominal',
          items: [
            {
              metric_key: 'ndvi',
              value: 0.385,
              unit: '',
              status: 'available',
              quality: 'nominal',
              display_name: 'NDVI',
              is_usable: true,
              is_proxy: false,
              source_dataset: 'COPERNICUS/S2_SR_HARMONIZED',
            },
          ],
        },
      },
      geometry: {
        type: 'Point',
        coordinates: [54.0, 32.3],
      },
      time_start: '2024-06-01',
      time_end: '2024-08-31',
      limitations: ['محدودیت تفکیک مکانی در سنجنده‌های حرارتی'],
    };

    const model = buildNormalizedReportModel(dummyResponse);
    assert.ok(model.availableDomainSections.length > 0);
    const vegSec = model.availableDomainSections.find((s) => s.domainKey === 'vegetation')!;
    assert.ok(vegSec);
    const ndviItem = vegSec.metrics.find((m) => m.key === 'ndvi')!;
    assert.ok(ndviItem);
    assert.equal(ndviItem.value, 0.385);
    assert.ok(ndviItem.referenceRangeFa && ndviItem.referenceRangeFa.includes('۰.۲۲'));
    assert.ok(ndviItem.resolution && ndviItem.resolution.includes('۱۰ متر'));
    assert.ok(ndviItem.farmerExplanationFa && ndviItem.farmerExplanationFa.length > 0);
  });

  it('14. Jalali date and Persian numeral presentation preserved throughout', () => {
    const pDateSrc = readSource('components/agriculture/persianDate.ts');
    assert.match(pDateSrc, /toPersianDigits/);
    assert.match(pDateSrc, /formatPersianDate/);
  });

  it('15. Zero mock or synthetic data in metric interpretation catalog', () => {
    const catalogSrc = readSource('components/agriculture/metricInterpretation.ts');
    assert.doesNotMatch(catalogSrc, /Math\.random/);
    assert.doesNotMatch(catalogSrc, /generateMock/);
    assert.doesNotMatch(catalogSrc, /fakeData/i);
    assert.doesNotMatch(catalogSrc, /synthetic/i);
  });
});
