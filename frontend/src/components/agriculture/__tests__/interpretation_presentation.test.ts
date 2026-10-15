/**
 * Focused test suite for Real Agricultural Analysis Output - Interpretation & Presentation Layer
 * Verifies all 10 requirements of P-AGRI interpretation presentation:
 * 1. Sufficient evidence state
 * 2. Limited evidence state (coarse resolution / proxy)
 * 3. Insufficient evidence state
 * 4. Uncertain interpretation handling
 * 5. Conflicting signals aggregation & caution
 * 6. Missing metrics never render as 0
 * 7. Zero valid pixels never render as 0
 * 8. Real metric values preserved (precision, units, sources)
 * 9. Scientific non-claim language (zero fake AI crop health/disease/pest diagnoses)
 * 10. Metric grouping into 6 scientific categories
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  METRIC_CATEGORIES,
  evaluateMetricState,
  type MetricDefinition,
} from '../categorizedMetrics.ts';
import type {
  AgriculturalAnalysisResponse,
  EvidenceBundleResponse,
  EvidenceItemResponse,
} from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const componentsDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('Interpretation & Presentation Layer - Pure Logic & Safety', () => {
  const dummyMetricDef: MetricDefinition = {
    key: 'ndvi',
    name: 'Normalized Difference Vegetation Index (NDVI)',
    nameFa: 'شاخص پوشش گیاهی تفاضلی نرمال‌شده (NDVI)',
    category: 'vegetation',
    unitDefault: '',
    descriptionFa: 'شاخص عمومی سبزی',
    precision: 4,
  };

  const coarseMetricDef: MetricDefinition = {
    key: 'land_surface_temperature_day',
    name: 'Land Surface Temperature Day (LST Day)',
    nameFa: 'دمای روزانه سطح زمین (LST Day)',
    category: 'thermal',
    unitDefault: '°C',
    descriptionFa: 'دمای تابشی پوسته فیزیکی خاک',
    isCoarseResolution: true,
    coarseNoteFa: 'تفکیک مکانی ۱۰۰۰ متری',
    precision: 2,
  };

  it('1. Sufficient evidence produces available state with positive quality', () => {
    const item: EvidenceItemResponse = {
      metric_key: 'ndvi',
      value: 0.4285,
      unit: '',
      status: 'available',
      quality: 'nominal',
      display_name: 'NDVI',
      is_usable: true,
      is_proxy: false,
      source_dataset: 'Sentinel-2 MSI',
    };

    const res = evaluateMetricState(item, dummyMetricDef);
    assert.equal(res.state, 'available');
    assert.equal(res.displayValue, '0.4285');
    assert.match(res.badgeLabel, /Available/i);
    assert.equal(res.badgeClass, 'badge-good');
  });

  it('2. Limited evidence: coarse resolution or proxy receives limited status & disclaimer', () => {
    const item: EvidenceItemResponse = {
      metric_key: 'land_surface_temperature_day',
      value: 46.52,
      unit: '°C',
      status: 'available',
      quality: 'nominal',
      display_name: 'LST Day',
      is_usable: true,
      is_proxy: false,
      source_dataset: 'MODIS MOD11A2',
    };

    const res = evaluateMetricState(item, coarseMetricDef);
    assert.equal(res.state, 'limited');
    assert.equal(res.displayValue, '46.52');
    assert.equal(res.unit, '°C');
    assert.match(res.badgeLabel, /Limited/i);
    assert.equal(res.badgeClass, 'badge-warning');
    assert.match(res.reasonFa, /تفکیک مکانی ۱۰۰۰ متری/);
  });

  it('3. Insufficient evidence: marked as insufficient with explicit reason', () => {
    const item: EvidenceItemResponse = {
      metric_key: 'ndvi',
      value: null,
      unit: '',
      status: 'unavailable',
      quality: 'insufficient',
      display_name: 'NDVI',
      is_usable: false,
      is_proxy: false,
      unavailable_reason: 'پوشش ابری بالاتر از حد مجاز',
    };

    const res = evaluateMetricState(item, dummyMetricDef);
    assert.equal(res.state, 'insufficient');
    assert.equal(res.displayValue, 'داده قابل استفاده موجود نیست');
    assert.match(res.badgeLabel, /Insufficient/i);
    assert.equal(res.badgeClass, 'badge-danger');
    assert.equal(res.reasonFa, 'پوشش ابری بالاتر از حد مجاز');
  });

  it('4. Uncertain interpretation handles absent or unconfirmed values safely', () => {
    const item: EvidenceItemResponse = {
      metric_key: 'ndvi',
      value: undefined,
      unit: '',
      status: 'uncertain',
      quality: 'uncertain',
      display_name: 'NDVI',
      is_usable: false,
      is_proxy: false,
    };

    const res = evaluateMetricState(item, dummyMetricDef);
    assert.equal(res.state, 'insufficient');
    assert.equal(res.displayValue, 'داده قابل استفاده موجود نیست');
    assert.notEqual(res.displayValue, '0');
  });

  it('5. Conflicting signals: SMAP vs ERA5 soil divergence handled with explicit caution', () => {
    const ovSrc = readSource('components/agriculture/AnalysisOverviewSection.tsx');
    assert.match(ovSrc, /تعارض شواهد/);
    assert.match(ovSrc, /SMAP/);
    assert.match(ovSrc, /ERA5/);
    assert.match(ovSrc, /اختلاف چشمگیر/);
    assert.match(ovSrc, /توصیه نمی‌شود/);
  });

  it('6. Missing metrics NEVER display as numeric 0', () => {
    const nullItem: EvidenceItemResponse = {
      metric_key: 'precipitation',
      value: null,
      unit: 'mm',
      status: 'unavailable',
      quality: 'unavailable',
      display_name: 'Precipitation',
      is_usable: false,
      is_proxy: false,
    };

    const resNull = evaluateMetricState(nullItem, {
      key: 'precipitation',
      name: 'Precipitation',
      nameFa: 'بارندگی',
      category: 'soil_water',
      unitDefault: 'mm',
      descriptionFa: 'بارندگی کل',
    });

    assert.notEqual(resNull.displayValue, '0');
    assert.notEqual(resNull.displayValue, '0.0');
    assert.equal(resNull.displayValue, 'داده قابل استفاده موجود نیست');

    const resMissing = evaluateMetricState(undefined, dummyMetricDef);
    assert.notEqual(resMissing.displayValue, '0');
    assert.equal(resMissing.displayValue, 'داده قابل استفاده موجود نیست');
  });

  it('7. Zero valid pixels (0 valid pixels) NEVER displays as numeric 0', () => {
    const zeroPixelItem: EvidenceItemResponse = {
      metric_key: 'ndvi',
      value: 0, // backend might return 0 as aggregate of 0 pixels
      unit: '',
      status: 'available',
      quality: 'nominal',
      display_name: 'NDVI',
      is_usable: false, // flagged false due to zero pixels
      is_proxy: false,
      stats: {
        valid_pixel_count: 0,
        valid_area_sq_m: 0,
        total_pixel_count: 100,
        missing_pixel_count: 100,
        missing_percent: 100,
        coverage_percent: 0,
      },
    };

    const res = evaluateMetricState(zeroPixelItem, dummyMetricDef);
    assert.equal(res.state, 'insufficient');
    assert.notEqual(res.displayValue, '0');
    assert.equal(res.displayValue, 'داده قابل استفاده موجود نیست');
    assert.match(res.reasonFa, /۰ پیکسل معتبر/);
  });

  it('8. Real metric values preserved exactly with specified precision', () => {
    const item: EvidenceItemResponse = {
      metric_key: 'vh',
      value: -19.45821,
      unit: 'dB',
      status: 'available',
      quality: 'nominal',
      display_name: 'VH Backscatter',
      is_usable: true,
      is_proxy: false,
      source_dataset: 'Sentinel-1 GRD',
    };

    const vhDef: MetricDefinition = {
      key: 'vh',
      name: 'VH Backscatter',
      nameFa: 'پس‌پراکنش VH',
      category: 'radar',
      unitDefault: 'dB',
      descriptionFa: 'پراکنش متقاطع',
      precision: 2,
    };

    const res = evaluateMetricState(item, vhDef);
    assert.equal(res.state, 'available');
    assert.equal(res.displayValue, '-19.46');
    assert.equal(res.unit, 'dB');
  });

  it('9. Scientific non-claim language: NO fake crop health or disease diagnoses', () => {
    const compSrc = readSource('components/agriculture/CategorizedMetricCards.tsx');
    const overviewSrc = readSource('components/agriculture/AnalysisOverviewSection.tsx');

    // Forbidden diagnoses (per User Request 10 hard constraints)
    const forbiddenClaims = [
      'محصول سالم است',
      'گیاه بیمار است',
      'آفت وجود دارد',
      'زمین تشنه است',
      'تنش آبی قطعی است',
      'تنش گرمایی تأیید شد',
      'محصول در تنش گرمایی است',
      'بدون فتوسنتز',
      'عدم ذخیره آب برگ',
      'خاک لخت هموار است',
      'crop is healthy',
      'crop is unhealthy',
      'pest detected',
      'disease detected',
      'irrigation required',
      'crop is thirsty',
      'root-zone water stress confirmed',
      'heat stress confirmed',
      'yield prediction',
      'crop type confirmed',
    ];

    for (const claim of forbiddenClaims) {
      assert.doesNotMatch(compSrc, new RegExp(claim, 'i'), `Forbidden claim found: ${claim}`);
      assert.doesNotMatch(overviewSrc, new RegExp(claim, 'i'), `Forbidden claim found in overview: ${claim}`);
    }

    // Conservative scientific descriptions audited
    assert.match(overviewSrc, /سیگنال ضعیف یا تنک پوشش گیاهی/);
    assert.match(overviewSrc, /طبقه‌بندی قطعی کاربری یا وضعیت فیزیولوژیک گیاه نیست/);
    assert.match(overviewSrc, /پروکسی طیفی/);
    assert.match(overviewSrc, /دلالتی بر دمای برگ، اندام گیاهی یا تأیید تنش گرمایی محصول ندارد/);
    assert.match(overviewSrc, /سیگنال پس‌پراکنش نسبتاً ضعیف/);
    assert.match(overviewSrc, /Pairwise Consistency Checks/);

    // LST must strictly be Land Surface Temperature, not plant temperature
    assert.doesNotMatch(compSrc, /دمای اندام گیاه/);
    assert.doesNotMatch(compSrc, /plant temperature/i);
    assert.match(compSrc, /دمای تابشی فیزیکی پوسته سطح زمین/);
    assert.match(compSrc, /Land Surface Temperature/);
  });

  it('10. Metric grouping: Six distinct scientific categories with correct memberships', () => {
    assert.equal(METRIC_CATEGORIES.length, 6);

    const keys = METRIC_CATEGORIES.map((c) => c.key);
    assert.deepEqual(keys, [
      'vegetation',
      'moisture',
      'thermal',
      'radar',
      'terrain',
      'soil_water',
    ]);

    const veg = METRIC_CATEGORIES.find((c) => c.key === 'vegetation')!;
    assert.ok(veg.metrics.some((m) => m.key === 'ndvi'));
    assert.ok(veg.metrics.some((m) => m.key === 'savi'));
    assert.ok(veg.metrics.some((m) => m.key === 'evi'));
    assert.ok(veg.metrics.some((m) => m.key === 'ndre'));

    const moisture = METRIC_CATEGORIES.find((c) => c.key === 'moisture')!;
    assert.ok(moisture.metrics.some((m) => m.key === 'ndmi'));
    assert.ok(moisture.metrics.some((m) => m.key === 'msi'));

    const thermal = METRIC_CATEGORIES.find((c) => c.key === 'thermal')!;
    assert.ok(thermal.metrics.some((m) => m.key === 'land_surface_temperature_day'));

    const radar = METRIC_CATEGORIES.find((c) => c.key === 'radar')!;
    assert.ok(radar.metrics.some((m) => m.key === 'vh'));
    assert.ok(radar.metrics.some((m) => m.key === 'vv'));

    const terrain = METRIC_CATEGORIES.find((c) => c.key === 'terrain')!;
    assert.ok(terrain.metrics.some((m) => m.key === 'elevation'));
    assert.ok(terrain.metrics.some((m) => m.key === 'slope'));

    const soilWater = METRIC_CATEGORIES.find((c) => c.key === 'soil_water')!;
    assert.ok(soilWater.metrics.some((m) => m.key === 'soil_moisture_rootzone'));
    assert.ok(soilWater.metrics.some((m) => m.key === 'soil_moisture_rootzone_era5'));
    assert.ok(soilWater.metrics.some((m) => m.key === 'precipitation'));
  });

  it('11. P0 UX Refactor: 4-layer findings, Known vs Unknown area, and Technical Telemetry at bottom', () => {
    const ovSrc = readSource('components/agriculture/AnalysisOverviewSection.tsx');

    // 1. Two-Column Known vs Not Concluded
    assert.match(ovSrc, /known-vs-unknown-section/);
    assert.match(ovSrc, /چه چیزهایی با اطمینان مشاهده شد؟/);
    assert.match(ovSrc, /چه چیزهایی هنوز قابل نتیجه‌گیری نیست؟/);

    // 2. Three-Level Scientific Communication Guide
    assert.match(ovSrc, /scientific-levels-guide/);
    assert.match(ovSrc, /سطح A — مشاهده فیزیکی سنجنده/);
    assert.match(ovSrc, /سطح B — تفسیر شواهد/);
    assert.match(ovSrc, /سطح C — تشخیص زراعی/);

    // 3. 4-Layer Key Finding Cards
    assert.match(ovSrc, /۱\. مشاهده ماهواره:/);
    assert.match(ovSrc, /۲\. تفسیر شواهد:/);
    assert.match(ovSrc, /۳\. میزان قطعیت:/);
    assert.match(ovSrc, /۴\. محدودیت ابزار:/);

    // 4. Collapsible Technical Section at bottom
    assert.match(ovSrc, /technical-system-consistency-section/);
    assert.match(ovSrc, /تلمتری و بررسی‌های فنی سیستم/);
    assert.match(ovSrc, /Technical System Consistency/);

    // 5. Insufficient state reframing: communicated as data limitation, not analysis failure
    assert.match(ovSrc, /داده‌های ماهواره‌ای با موفقیت دریافت و پردازش شدند/);
    assert.doesNotMatch(ovSrc, /تحلیل با شکست مواجه شد/);
    assert.doesNotMatch(ovSrc, /داده‌های ماهواره نامعتبر است/);
  });
});
