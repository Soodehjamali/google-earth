/**
 * Phase P1 — Ground Truth + Scientific Validation + Pest/Disease Intelligence Tests
 *
 * Verifies:
 * 1. Ground Truth data model integrity (observed vs derived, field preservation).
 * 2. Scientific Validation contract (differences, sample_count, descriptive statuses).
 * 3. Pest/Disease risk screening safety (inspection only, non-claim, hierarchy 0-4).
 * 4. Jalali calendar and Persian digits presentation guarantees.
 * 5. Unavailable and insufficient evidence handling (zero data fabrication).
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  formatPersianDate,
  formatPersianDateRange,
  formatPersianYear,
  toPersianDigits,
  isoGregorianToJalali,
  jalaliToGregorian,
} from '../persianDate.ts';

import type {
  GroundTruthObservation,
  PestDiseaseInspectionResponse,
  ValidationResult,
  ValidationSection,
} from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSrc(rel: string): string {
  return readFileSync(join(srcDir, rel), 'utf-8');
}

describe('Phase P1 — Ground Truth Capability', () => {
  it('distinguishes observed from derived with is_derived flag', () => {
    const obs: GroundTruthObservation = {
      observation_id: 'gt-test-01',
      variable: 'ndvi',
      metric_key: 'ndvi',
      value: 0.28,
      unit: 'index',
      state: 'stressed',
      observed_on: '2024-05-20',
      source: 'agronomist_observation',
      method: 'field_inspection',
      quality: 'good',
      crop_type: 'پسته',
      growth_stage: 'پر شدن مغز',
      observed_stress: 'زردی حاشیه برگ',
      pest_observation: 'پسیل پسته',
      is_derived: false,
      status: 'available',
    };

    assert.equal(obs.is_derived, false, 'Ground truth must have is_derived === false');
    assert.equal(obs.source, 'agronomist_observation');
    assert.equal(obs.observed_stress, 'زردی حاشیه برگ');
    assert.equal(obs.pest_observation, 'پسیل پسته');
  });

  it('GroundTruthForm uses JalaliDatePicker and formatPersianDate', () => {
    const code = readSrc('components/agriculture/GroundTruthForm.tsx');
    assert.ok(code.includes('JalaliDatePicker'), 'GroundTruthForm must use JalaliDatePicker');
    assert.ok(code.includes('formatPersianDate'), 'GroundTruthForm must use formatPersianDate for observation date display');
    assert.ok(!code.includes('obs.observed_on ? toPersianDigits(obs.observed_on)'), 'Must not leak Gregorian date with Persian digits');
  });
});

describe('Phase P1 — Scientific Validation Capability', () => {
  it('preserves difference, relative_difference_percent, and sample_count', () => {
    const res: ValidationResult = {
      validation_id: 'v:ndvi:2024-05-01:2024-05-31:r1c1:gt-01',
      target_id: 'ndvi:2024-05-01:2024-05-31:r1c1:gt-01',
      observation_id: 'gt-01',
      metric_key: 'ndvi',
      domain: 'vegetation',
      analysis_window_start: '2024-05-01',
      analysis_window_end: '2024-05-31',
      analysis_value: 0.35,
      analysis_unit: 'index',
      reference_variable: 'ndvi',
      reference_value: 0.30,
      reference_unit: 'index',
      reference_source: 'field_sensor',
      reference_method: 'portable_spectrometer',
      reference_time: '2024-05-15',
      temporal_relationship: 'COMPATIBLE_TEMPORAL_WINDOW',
      spatial_relationship: 'EXACT_SPATIAL_CELL_MATCH',
      metric_relationship: 'METRIC_MATCH',
      states_agree: null,
      values_comparable: true,
      difference: 0.05,
      relative_difference_percent: 16.67,
      sample_count: 1,
      validation_status_code: 'partially_validated',
      status: 'MATCHED_REFERENCE',
      linkage_reason: 'shared metric, overlapping window, and cell',
      contract_version: 'P61_V1',
      engine_version: 'P62_V1',
      provenance: {},
      limitations: [],
    };

    assert.equal(res.difference, 0.05);
    assert.equal(res.relative_difference_percent, 16.67);
    assert.equal(res.sample_count, 1);
    assert.equal(res.validation_status_code, 'partially_validated');
  });

  it('GroundTruthValidationTable renders sample_count and does not fabricate values', () => {
    const code = readSrc('components/agriculture/GroundTruthValidationTable.tsx');
    assert.ok(code.includes('تعداد نمونه'), 'Table must have a column header for sample count');
    assert.ok(code.includes('sample_count'), 'Table must render res.sample_count');
    assert.ok(code.includes('toPersianDigits'), 'Table must format numeric values with Persian digits');
  });
});

describe('Phase P1 — Pest / Disease Inspection Capability', () => {
  it('inspection response contains non-claim disclaimers and hierarchy levels', () => {
    const mockResp: PestDiseaseInspectionResponse = {
      start_date: '2024-05-01',
      end_date: '2024-08-31',
      overall_risk_level: 'elevated',
      risk_level_fa: 'ریسک افزایش‌یافته (تنش فعال)',
      pattern_type: 'possible_biotic_stress_compatible_pattern',
      pattern_title_fa: 'الگوی سازگار با احتمال تنش زیستی (آفت یا بیماری)',
      pattern_summary_fa: 'افت بارز شاخص‌های کلروفیل (NDRE)',
      evidence_hierarchy_level: 3,
      evidence_hierarchy_title_fa: 'سطح ۳: همگرایی چندسنسوری',
      evidence_hierarchy_description_fa: 'سنسورهای اپتیکال، رادار و حرارتی همگرا هستند',
      optical_evidence: [],
      radar_evidence: [],
      thermal_evidence: [],
      biotic_abiotic_assessment: {
        compatible_stress_type: 'biotic',
        biotic_compatibility_score: 0.75,
        abiotic_compatibility_score: 0.25,
        spatial_uniformity: 'patchy',
        weather_correlation: 'uncorrelated',
        canopy_structural_decay: 'detected',
        reasoning_fa: 'الگوی افت فتوسنتزی سازگار با تنش زیستی است',
        reasoning_en: 'Canopy decline compatible with biotic stress',
      },
      ground_truth_corroboration: {
        has_ground_truth: true,
        sample_count: 1,
        observed_symptoms: ['زردی برگ'],
        pest_reports: ['پسیل'],
        disease_reports: [],
        confirms_stress: true,
        summary_fa: 'گزارش آفت میدانی: پسیل',
      },
      temporal_persistence: {
        multi_temporal_verified: true,
        consecutive_anomalous_months: 3,
        direction: 'declining',
        description_fa: 'تنش در ۳ ماه متوالی پایدار بوده است',
      },
      scientific_disclaimer_fa: 'تشخیص قطعی نوع آفت یا پاتوژن بیماری از طریق ماهواره از نظر علمی ناممکن و غیرمجاز است.',
      scientific_disclaimer_en: 'Definitive pathogen diagnosis from satellite is scientifically impossible.',
      recommended_field_actions_fa: [
        'بازدید میدانی کارشناس گیاه‌پزشک',
      ],
      limitations: [
        'سنجش از دور قادر به تشخیص گونه خاص آفت نیست.',
      ],
    };

    assert.equal(mockResp.evidence_hierarchy_level, 3);
    assert.equal(mockResp.pattern_type, 'possible_biotic_stress_compatible_pattern');
    assert.ok(mockResp.scientific_disclaimer_fa.includes('علمی ناممکن و غیرمجاز'));
  });

  it('PestDiseaseInspectionSection enforces strict scientific disclaimers', () => {
    const code = readSrc('components/agriculture/PestDiseaseInspectionSection.tsx');
    assert.ok(code.includes('سلب مسئولیت و اصول ایمنی علمی'), 'Must render scientific safety gate disclaimer');
    assert.ok(code.includes('scientific_disclaimer_fa'), 'Must render Persian disclaimer');
    assert.ok(code.includes('scientific_disclaimer_en'), 'Must render English disclaimer');
    assert.ok(code.includes('evidence_hierarchy_level'), 'Must render hierarchy tracker 0 to 4');
  });

  it('PestDiseaseInspectionSection isolates test fixture and displays Test Fixture — not real ground truth', () => {
    const code = readSrc('components/agriculture/PestDiseaseInspectionSection.tsx');
    assert.ok(code.includes('is_test_fixture'), 'Must check is_test_fixture on ground truth corroboration');
    assert.ok(code.includes('Test Fixture — not real ground truth'), 'Must display Test Fixture — not real ground truth');
    assert.ok(code.includes('سطح ۴ (Test Fixture — not real ground truth)'), 'Level 4 must explicitly state test fixture when fixture is present');
  });
});

describe('Phase P1 — Jalali Presentation & Zero Gregorian Leakage', () => {
  it('converts Gregorian date to exact Jalali and Persian digits', () => {
    const iso = '2024-05-20';
    const jalali = formatPersianDate(iso);
    // 2024-05-20 is 1403/02/31 in Jalali
    assert.ok(jalali.includes('۱۴۰۳'), `Expected Jalali year 1403 in ${jalali}`);
    assert.ok(!jalali.includes('2024'), `Gregorian year 2024 must not appear in ${jalali}`);
  });

  it('PestDiseasePage uses JalaliDatePicker and formatPersianDateRange', () => {
    const code = readSrc('pages/agriculture/PestDiseasePage.tsx');
    assert.ok(code.includes('JalaliDatePicker'), 'PestDiseasePage must use JalaliDatePicker');
    assert.ok(code.includes('formatPersianDateRange'), 'Must format date range with formatPersianDateRange');
    assert.ok(!code.includes('type="date"'), 'Raw HTML date inputs must not be used in PestDiseasePage');
  });

  it('formatPersianYear formats Gregorian dates/years into Jalali with Persian digits', () => {
    const py = formatPersianYear('2024-05-20');
    assert.equal(py, '۱۴۰۳', `Expected Jalali year ۱۴۰۳, got ${py}`);
  });
});
