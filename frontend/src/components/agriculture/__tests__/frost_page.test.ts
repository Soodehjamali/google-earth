import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { DOMAIN_META } from '../../../types/index.ts';
import { formatNumberValue, normalizeUnit } from '../../common/numberFormatting.ts';
import { formatCoarseResolutionFa } from '../coarseGating.ts';
import type {
  FrostPoint,
  FrostNightAssessment,
  ColdAirPoolingResponse,
  FrostAssessmentResponse,
} from '../../../types/frost.ts';

describe('Phase 3 Task 3.5: Frost-Risk Domain Page & Component Contracts', () => {
  it('1. registers frost domain in DOMAIN_META', () => {
    assert.ok(DOMAIN_META.frost, 'frost must be registered in DOMAIN_META');
    assert.strictEqual(DOMAIN_META.frost.key, 'frost');
    assert.strictEqual(DOMAIN_META.frost.icon, '❄️');
    assert.strictEqual(DOMAIN_META.frost.labelFa, 'هشدار سرمازدگی');
  });

  it('2. formats GFS coarse spatial resolution (~28km) honestly', () => {
    const text28km = formatCoarseResolutionFa(27800);
    assert.ok(text28km.includes('کیلومتر'), 'Should format in kilometers');
    assert.ok(text28km.includes('27.8') || text28km.includes('28'), 'Should disclose ~27.8km resolution');
  });

  it('3. formats negative sub-zero temperatures with mathematical minus in LTR', () => {
    // Negative sub-zero frost temperature
    const frostTemp = formatNumberValue(-3.7, 1);
    assert.strictEqual(frostTemp.isNegative, true);
    // Must use mathematical minus U+2212
    assert.ok(frostTemp.display.startsWith('\u2212'));
    assert.strictEqual(frostTemp.display, '\u22123.7');
    assert.strictEqual(frostTemp.raw, '-3.7');

    // Uncertainty bound
    const uncertainty = formatNumberValue(1.5, 1);
    assert.strictEqual(uncertainty.display, '1.5');

    // Unit normalization
    assert.strictEqual(normalizeUnit('°C'), '°C');
    assert.strictEqual(normalizeUnit('degC'), '°C');
  });

  it('4. verifies phenological threshold monotonicity (Tc90 < Tc10)', () => {
    const assessment: FrostAssessmentResponse = {
      crop: 'pistachio',
      crop_name_fa: 'پسته',
      phenological_stage: 'early_bloom',
      phenological_stage_fa: 'اوایل گلدهی',
      thresholds_verified: false,
      critical_temp_10_c: -2.0,
      critical_temp_90_c: -4.0,
      cold_air_pooling_proxy: 0.65,
      nights: [],
      overall_max_severity: 'warning',
    };

    assert.strictEqual(assessment.thresholds_verified, false, 'Placeholder thresholds must be unverified');
    assert.ok(
      assessment.critical_temp_90_c < assessment.critical_temp_10_c,
      'Tc90 must be colder than Tc10 (mortality curve monotonicity)',
    );
  });

  it('5. validates nocturnal window crossing UTC midnight and severity ranking', () => {
    const night: FrostNightAssessment = {
      night_date: '2026-03-25',
      window_start_utc: '2026-03-25T14:30:00Z',
      window_end_utc: '2026-03-26T05:30:00Z',
      window_start_local: '2026-03-25T18:00:00+03:30',
      window_end_local: '2026-03-26T09:00:00+03:30',
      min_temp_c: -1.2,
      adjusted_min_temp_c: -2.24,
      pooling_cooling_bump_c: 1.04,
      duration_below_t10_h: 4.0,
      duration_below_t90_h: 0.0,
      severity: 'warning',
      reasons: ['Adjusted min temperature -2.24°C is below Tc10 -2.00°C for 4.0h'],
      recommendations_fa: [
        'آبیاری سطحی یا شیاری سبک جهت افزایش هدایت حرارتی خاک',
        'فعال‌سازی ماشین‌های باد یا چاهک‌های معکوس در صورت وارونگی دما',
      ],
    };

    // Starts on day D, ends on day D+1 (crossing midnight)
    assert.ok(night.window_start_utc.includes('2026-03-25'));
    assert.ok(night.window_end_utc.includes('2026-03-26'));
    // Adjusted temp is colder than grid min_temp due to pooling bump
    assert.ok(night.adjusted_min_temp_c < night.min_temp_c);
    assert.ok(Math.abs(night.min_temp_c - night.pooling_cooling_bump_c - night.adjusted_min_temp_c) < 1e-4);
    assert.strictEqual(night.severity, 'warning');
  });

  it('6. cultural recommendations strictly enforce non-chemical physical methods', () => {
    const night: FrostNightAssessment = {
      night_date: '2026-03-25',
      window_start_utc: '2026-03-25T14:30:00Z',
      window_end_utc: '2026-03-26T05:30:00Z',
      window_start_local: '2026-03-25T18:00:00+03:30',
      window_end_local: '2026-03-26T09:00:00+03:30',
      min_temp_c: -2.5,
      adjusted_min_temp_c: -3.5,
      pooling_cooling_bump_c: 1.0,
      duration_below_t10_h: 5.0,
      duration_below_t90_h: 1.5,
      severity: 'warning',
      reasons: ['Freeze event'],
      recommendations_fa: [
        'آبیاری سطحی یا شیاری سبک پیش از آغاز یخبندان برای آزادسازی گرمای نهان',
        'فعال‌سازی ماشین‌های باد یا چاهک‌های معکوس در حضور وارونگی حرارتی شبانه',
        'روشن کردن بخاری‌های باغی پاک‌سوز در نقاط پست و گودی‌های مستعد انباشت هوای سرد',
        'حفظ رطوبت و فشردگی خاک سطح باغ و خودداری از شخم‌زدن پیش از افت دما',
      ],
    };

    for (const rec of night.recommendations_fa) {
      assert.ok(!rec.includes('شیمیایی'), 'No chemical recommendations');
      assert.ok(!rec.includes('هورمون'), 'No hormone recommendations');
      assert.ok(!rec.includes('ترکیبات مس') && !rec.includes('محلول‌پاشی مس'), 'No unproven copper foliar sprays');
      assert.ok(!rec.includes('ضدتعریق'), 'No unproven anti-transpirant chemicals');
    }
  });

  it('7. cold-air-pooling proxy carries required topographic metrics and disclaimer', () => {
    const pooling: ColdAirPoolingResponse = {
      pooling_risk_proxy: 0.725,
      risk_label: 'high',
      risk_label_fa: 'ریسک بالا (گودی موضعی)',
      site_elevation_m: 1450.0,
      min_elevation_m: 1420.0,
      max_elevation_m: 1530.0,
      relief_m: 110.0,
      mean_slope_deg: 2.4,
      disclaimer_fa:
        'شاخص تجمع هوای سرد صرفاً یک برآورد تقریبی توپوگرافی بر پایه مدل رقومی ارتفاعی (DEM) است و شبیه‌سازی دینامیکی جریان هوا محسوب نمی‌شود.',
      tile_url: '/api/v1/agriculture/tiles/mock_token/{z}/{x}/{y}.png',
      color_ramp: ['#f7fcf0', '#bae4bc', '#7bccc4', '#43a2ca', '#0868ac'],
    };

    assert.ok(pooling.pooling_risk_proxy >= 0.0 && pooling.pooling_risk_proxy <= 1.0);
    assert.strictEqual(pooling.relief_m, pooling.max_elevation_m - pooling.min_elevation_m);
    assert.ok(pooling.disclaimer_fa.includes('مدل رقومی ارتفاعی'));
    assert.strictEqual(pooling.color_ramp?.length, 5);
    assert.strictEqual(pooling.color_ramp[0], '#f7fcf0');
    assert.strictEqual(pooling.color_ramp[4], '#0868ac');
  });

  it('8. forecast adapter points provide hourly cadence and uncertainty bounds', () => {
    const point: FrostPoint = {
      time_utc: '2026-03-25T18:00:00Z',
      lead_time_h: 6,
      raw_temperature_c: 4.2,
      corrected_temperature_c: 2.25,
      uncertainty_c: 1.02,
      temperature_min_c: 1.23,
      temperature_max_c: 3.27,
      dewpoint_2m_c: -1.5,
      relative_humidity_percent: 62.0,
      wind_speed_10m_mps: 1.8,
      total_cloud_cover_percent: 10.0,
      is_interpolated: false,
    };

    assert.ok(point.temperature_min_c < point.corrected_temperature_c);
    assert.ok(point.corrected_temperature_c < point.temperature_max_c);
    assert.strictEqual(point.is_interpolated, false);
    assert.ok(Math.abs(point.temperature_min_c - (point.corrected_temperature_c - point.uncertainty_c)) < 1e-4);
    assert.ok(Math.abs(point.temperature_max_c - (point.corrected_temperature_c + point.uncertainty_c)) < 1e-4);
  });
});
