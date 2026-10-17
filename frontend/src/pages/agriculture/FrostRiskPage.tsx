import React, { useState, useEffect, useCallback } from 'react';
import { agricultureApi } from '../../api/agriculture';
import type {
  FrostAssessmentResponse,
  FrostAssessRequest,
  FrostOrchard,
  EvaluateAlertsResponse,
} from '../../types';
import FormattedNumber from '../../components/common/FormattedNumber';
import FrostWarningBanner from '../../components/agriculture/frost/FrostWarningBanner';
import FrostTimelineChart from '../../components/agriculture/frost/FrostTimelineChart';
import FrostNightCards from '../../components/agriculture/frost/FrostNightCards';
import ColdAirPoolingSection from '../../components/agriculture/frost/ColdAirPoolingSection';
import DomainNavCards from '../../components/agriculture/DomainNavCards';

const CROP_OPTIONS = [
  { value: 'pistachio', labelFa: 'پسته (Pistachio)' },
];

const PHENOLOGY_STAGES = [
  { value: 'dormant', labelFa: 'خواب زمستانه (Dormant)' },
  { value: 'bud_burst', labelFa: 'تورم و باز شدن جوانه (Bud Burst)' },
  { value: 'early_bloom', labelFa: 'اوایل گلدهی (Early Bloom)' },
  { value: 'full_bloom', labelFa: 'گلدهی کامل (Full Bloom)' },
  { value: 'fruit_set', labelFa: 'تشکیل میوه (Fruit Set)' },
];

export default function FrostRiskPage() {
  // Input states
  const [crop, setCrop] = useState<string>('pistachio');
  const [stage, setStage] = useState<string>('early_bloom');
  const [horizonH, setHorizonH] = useState<number>(72);
  const [latitude, setLatitude] = useState<number>(30.40);
  const [longitude, setLongitude] = useState<number>(55.99);
  const [useLiveGee, setUseLiveGee] = useState<boolean>(false);

  // Assessment results
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<FrostAssessmentResponse | null>(null);

  // Orchards & alerts
  const [orchards, setOrchards] = useState<FrostOrchard[]>([]);
  const [loadingOrchards, setLoadingOrchards] = useState<boolean>(false);
  const [orchardName, setOrchardName] = useState<string>('');
  const [alertRecipient, setAlertRecipient] = useState<string>('');
  const [alertChannel, setAlertChannel] = useState<string>('sms');
  const [evalResult, setEvalResult] = useState<EvaluateAlertsResponse | null>(null);
  const [evaluating, setEvaluating] = useState<boolean>(false);

  // Fetch initial assessment with default coordinates on mount
  const handleRunAssessment = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const geo = {
        type: 'Point',
        coordinates: [longitude, latitude],
      };
      const req: FrostAssessRequest = {
        geometry: geo,
        crop,
        phenological_stage: stage,
        horizon_h: horizonH,
        use_live_gee: useLiveGee,
      };
      const res: any = await agricultureApi.assessFrost(req);
      const normalized: FrostAssessmentResponse = {
        crop: res.crop,
        crop_name_fa: res.crop_fa || res.crop_name_fa || 'پسته',
        phenological_stage: res.phenological_stage,
        phenological_stage_fa: res.stage_fa || res.phenological_stage_fa || 'اوایل گلدهی',
        thresholds_verified: Boolean(res.thresholds_verified),
        evidence_level: res.evidence_level || (Boolean(res.thresholds_verified) ? 'B' : 'C'),
        critical_temp_10_c: res.t_critical_10_c ?? res.critical_temp_10_c,
        critical_temp_90_c: res.t_critical_90_c ?? res.critical_temp_90_c,
        cold_air_pooling_proxy: res.pooling_risk_proxy ?? res.cold_air_pooling_proxy,
        overall_max_severity: (res.overall_risk_level || res.overall_max_severity || 'none') as any,
        earliest_critical_night: res.nightly_risks?.find((n: any) => n.risk_level === 'warning' || n.risk_level === 'critical')?.night_date || null,
        nights: (res.nightly_risks || res.nights || []).map((n: any) => ({
          night_date: n.night_date,
          window_start_utc: n.start_time_utc || n.window_start_utc,
          window_end_utc: n.end_time_utc || n.window_end_utc,
          window_start_local: n.night_display_fa || n.window_start_local || '',
          window_end_local: n.end_time_utc || '',
          min_temp_c: n.tmin_forecast_c ?? n.min_temp_c,
          adjusted_min_temp_c: n.tmin_adjusted_c ?? n.adjusted_min_temp_c,
          pooling_cooling_bump_c: n.pooling_cooling_bump_c ?? 0,
          duration_below_t10_h: n.hours_below_tc10 ?? n.duration_below_t10_h ?? 0,
          duration_below_t90_h: n.hours_below_tc90 ?? n.duration_below_t90_h ?? 0,
          severity: n.risk_level || n.severity || 'none',
          reasons: n.recommendations_fa || n.reasons || [],
          recommendations_fa: n.recommendations_fa || [],
        })),
        forecast: res.forecast ? {
          grid_elevation_m: res.forecast.cell_elevation_m ?? res.forecast.grid_elevation_m ?? 0,
          site_elevation_m: res.forecast.site_elevation_m ?? 0,
          elevation_delta_m: res.forecast.series?.[0]?.elevation_delta_m ?? res.forecast.elevation_delta_m ?? 0,
          temperature_adjustment_c: res.forecast.series?.[0]?.elevation_correction_c ?? res.forecast.temperature_adjustment_c ?? 0,
          dem_source: res.forecast.source ?? res.forecast.dem_source ?? 'NASADEM',
          elevation_uncertainty_c: res.forecast.series?.[0]?.elevation_uncertainty_c ?? res.forecast.elevation_uncertainty_c ?? 0,
          lead_time_uncertainty_table: res.forecast.lead_time_uncertainty_table || {},
          points: (res.forecast.series || res.forecast.points || []).map((s: any) => ({
            time_utc: s.timestamp_utc || s.time_utc,
            lead_time_h: s.lead_hours ?? s.lead_time_h,
            raw_temperature_c: s.temperature_2m_c_raw ?? s.raw_temperature_c,
            corrected_temperature_c: s.temperature_2m_c ?? s.corrected_temperature_c,
            uncertainty_c: s.total_uncertainty_c ?? s.uncertainty_c,
            lower_bound_c: s.lower_bound_c ?? s.temperature_min_c,
            upper_bound_c: s.upper_bound_c ?? s.temperature_max_c,
            temperature_min_c: s.lower_bound_c ?? s.temperature_min_c,
            temperature_max_c: s.upper_bound_c ?? s.temperature_max_c,
            dewpoint_2m_c: s.dewpoint_2m_c,
            relative_humidity_percent: s.relative_humidity_percent,
            wind_speed_10m_mps: s.wind_speed_10m_mps,
            total_cloud_cover_percent: s.total_cloud_cover_percent,
            is_interpolated: s.is_interpolated,
          })),
          native_spatial_resolution_m: res.forecast.native_spatial_resolution_m,
          quality_state: res.forecast.quality_state,
        } : undefined,
        cold_air_pooling: res.cold_air_pooling ? {
          pooling_risk_proxy: res.cold_air_pooling.mean_pooling_risk_proxy ?? res.cold_air_pooling.pooling_risk_proxy,
          risk_label: res.cold_air_pooling.risk_level || res.cold_air_pooling.risk_label || 'neutral',
          risk_label_fa: res.cold_air_pooling.risk_level_fa || res.cold_air_pooling.risk_label_fa || 'خنثی',
          site_elevation_m: res.cold_air_pooling.site_elevation_m ?? 0,
          min_elevation_m: res.cold_air_pooling.min_elevation_m ?? 0,
          max_elevation_m: res.cold_air_pooling.max_elevation_m ?? 0,
          relief_m: res.cold_air_pooling.relief_m ?? 0,
          mean_slope_deg: res.cold_air_pooling.mean_slope_deg ?? 0,
          disclaimer_fa: res.cold_air_pooling.disclaimer_fa || '',
          tile_url: res.cold_air_pooling.tile_url,
          color_ramp: res.cold_air_pooling.color_ramp,
        } : undefined,
      };
      setAssessment(normalized);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در اجرای ارزیابی ریسک سرمازدگی');
    } finally {
      setLoading(false);
    }
  }, [longitude, latitude, crop, stage, horizonH, useLiveGee]);

  const loadOrchards = useCallback(async () => {
    setLoadingOrchards(true);
    try {
      const list = await agricultureApi.listFrostOrchards();
      setOrchards(list);
    } catch {
      // Non-fatal if DB table is unpopulated
    } finally {
      setLoadingOrchards(false);
    }
  }, []);

  useEffect(() => {
    handleRunAssessment();
    loadOrchards();
  }, [handleRunAssessment, loadOrchards]);

  const handleCreateOrchard = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orchardName.trim()) return;
    try {
      const geo = {
        type: 'Polygon',
        coordinates: [
          [
            [longitude - 0.005, latitude - 0.005],
            [longitude + 0.005, latitude - 0.005],
            [longitude + 0.005, latitude + 0.005],
            [longitude - 0.005, latitude + 0.005],
            [longitude - 0.005, latitude - 0.005],
          ],
        ],
      };
      const created = await agricultureApi.createFrostOrchard({
        name: orchardName,
        geometry: geo,
        latitude,
        longitude,
        crop,
        default_phenology_stage: stage,
      });

      if (alertRecipient.trim()) {
        await agricultureApi.createFrostAlertRule(created.id, {
          recipient: alertRecipient,
          channel: alertChannel,
          lead_time_h: 24,
          enabled: true,
        });
      }
      setOrchardName('');
      setAlertRecipient('');
      await loadOrchards();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در ثبت باغ');
    }
  };

  const handleEvaluateAlerts = async (dryRun: boolean) => {
    setEvaluating(true);
    try {
      const res = await agricultureApi.evaluateFrostAlerts({
        dry_run: dryRun,
        admin_override: false,
        use_live_gee: useLiveGee,
      });
      setEvalResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در ارزیابی هشدارها');
    } finally {
      setEvaluating(false);
    }
  };

  return (
    <div className="frost-risk-page" data-testid="frost-risk-page">
      <DomainNavCards />

      {/* Page Header */}
      <div className="card mb-3">
        <div className="card-body">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span style={{ fontSize: '1.6rem' }}>❄️</span>
                <h2 style={{ margin: 0, fontSize: '1.35rem', fontWeight: 700 }}>
                  سامانه پایش و هشدار سرمازدگی دیررس بهاره
                </h2>
              </div>
              <div className="text-muted" style={{ fontSize: '0.85rem' }}>
                Frost Risk Early Warning & Cold-Air-Pooling Microclimate Advisory
              </div>
            </div>

            {/* Coarse Context Badge */}
            <div
              className="coarse-context-badge"
              data-testid="coarse-context-badge"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: '#fef3c7',
                color: '#92400e',
                border: '1px solid #fcd34d',
                borderRadius: '6px',
                padding: '4px 10px',
                fontSize: '0.8rem',
                fontWeight: 600,
              }}
            >
              <span>🌐</span>
              <span>تفکیک مکانی ~۲۸ کیلومتر (GFS) - پیش‌بینی منطقه‌ای با تصحیح تراز ارتفاع DEM</span>
            </div>
            {assessment && (
              <div
                data-testid="evidence-level-badge"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: assessment.evidence_level === 'B' ? '#e0f2fe' : '#fef2f2',
                  color: assessment.evidence_level === 'B' ? '#0369a1' : '#991b1b',
                  border: `1px solid ${assessment.evidence_level === 'B' ? '#7dd3fc' : '#f87171'}`,
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                }}
              >
                <span>📊</span>
                <span>
                  {assessment.evidence_level === 'B'
                    ? 'سطح شواهد: B (آستانه‌های تأیید شده)'
                    : 'سطح شواهد: C (آستانه‌های آزمایشی/کالیبره‌نشده)'}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Unverified Thresholds Warning Banner */}
      {assessment && !assessment.thresholds_verified && (
        <FrostWarningBanner
          thresholdsVerified={assessment.thresholds_verified}
          evidenceLevel={assessment.evidence_level}
          cropNameFa={assessment.crop_name_fa}
          stageNameFa={assessment.phenological_stage_fa}
          t10={assessment.critical_temp_10_c}
          t90={assessment.critical_temp_90_c}
        />
      )}

      {/* Parameter Controls Form */}
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">⚙️ تنظیمات تحلیل و مختصات مزرعه</span>
        </div>
        <div className="card-body">
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '14px',
              marginBottom: '14px',
            }}
          >
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '4px' }}>
                محصول باغی:
              </label>
              <select
                className="form-control"
                value={crop}
                onChange={(e) => setCrop(e.target.value)}
                style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
              >
                {CROP_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.labelFa}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '4px' }}>
                مرحله فنولوژیکی:
              </label>
              <select
                className="form-control"
                value={stage}
                onChange={(e) => setStage(e.target.value)}
                style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
              >
                {PHENOLOGY_STAGES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.labelFa}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '4px' }}>
                افق پیش‌بینی (ساعت):
              </label>
              <select
                className="form-control"
                value={horizonH}
                onChange={(e) => setHorizonH(Number(e.target.value))}
                style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
              >
                <option value={24}>۲۴ ساعت (۱ روز)</option>
                <option value={48}>۴۸ ساعت (۲ روز)</option>
                <option value={72}>۷۲ ساعت (۳ روز)</option>
                <option value={120}>۱۲۰ ساعت (۵ روز)</option>
                <option value={240}>۲۴۰ ساعت (۱۰ روز)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '4px' }}>
                عرض جغرافیایی (Latitude):
              </label>
              <input
                type="number"
                step="0.001"
                className="form-control"
                value={latitude}
                onChange={(e) => setLatitude(Number(e.target.value))}
                style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '4px' }}>
                طول جغرافیایی (Longitude):
              </label>
              <input
                type="number"
                step="0.001"
                className="form-control"
                value={longitude}
                onChange={(e) => setLongitude(Number(e.target.value))}
                style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.85rem' }}>
              <input
                type="checkbox"
                checked={useLiveGee}
                onChange={(e) => setUseLiveGee(e.target.checked)}
              />
              <span>دریافت زنده از Google Earth Engine (GFS / NASADEM)</span>
            </label>

            <button
              type="button"
              className="btn btn-primary"
              onClick={handleRunAssessment}
              disabled={loading}
              data-testid="run-frost-btn"
              style={{ minWidth: '160px' }}
            >
              {loading ? 'در حال تحلیل...' : 'اجرای ارزیابی ریسک ❄️'}
            </button>
          </div>

          {error && (
            <div
              style={{
                marginTop: '12px',
                padding: '10px 14px',
                backgroundColor: '#fee2e2',
                border: '1px solid #f87171',
                borderRadius: '6px',
                color: '#991b1b',
                fontSize: '0.85rem',
              }}
            >
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Assessment Results Section */}
      {assessment && (
        <>
          {/* Top Summary KPI Cards */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '14px',
              marginBottom: '16px',
            }}
          >
            <div className="card p-3" style={{ borderRight: '4px solid #ef4444' }}>
              <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                بالاترین سطح ریسک در افق
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                {assessment.overall_max_severity === 'warning'
                  ? '🚨 اخطار سرمازدگی (Warning)'
                  : assessment.overall_max_severity === 'watch'
                    ? '⚠️ دیده‌بانی سرما (Watch)'
                    : assessment.overall_max_severity === 'advisory'
                      ? 'ℹ️ هشدار مقدماتی (Advisory)'
                      : '✅ بدون ریسک (None)'}
              </div>
              <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                اولین شب بحرانی: {assessment.earliest_critical_night || 'ندارد'}
              </div>
            </div>

            <div className="card p-3" style={{ borderRight: '4px solid #f59e0b' }}>
              <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                آستانه‌های خسارت فنولوژیکی
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600 }}>
                ۱۰٪ خسارت (Tc10):{' '}
                <FormattedNumber value={assessment.critical_temp_10_c} unit="°C" />
              </div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#dc2626' }}>
                ۹۰٪ خسارت (Tc90):{' '}
                <FormattedNumber value={assessment.critical_temp_90_c} unit="°C" />
              </div>
              <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                مرحله: {assessment.phenological_stage_fa}
              </div>
            </div>

            {assessment.forecast && (
              <div className="card p-3" style={{ borderRight: '4px solid #3b82f6' }}>
                <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                  تصحیح تراز ارتفاعی (Lapse Rate)
                </div>
                <div style={{ fontSize: '0.95rem', fontWeight: 600 }}>
                  اختلاف ارتفاع مزرعه با سلول (Δz):{' '}
                  <FormattedNumber value={assessment.forecast.elevation_delta_m} unit="m" />
                </div>
                <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#1d4ed8' }}>
                  تعدیل دما (ΔT):{' '}
                  <FormattedNumber value={assessment.forecast.temperature_adjustment_c} unit="°C" />
                </div>
                <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                  تراز سلول: {assessment.forecast.grid_elevation_m}m | مزرعه: {assessment.forecast.site_elevation_m}m
                </div>
              </div>
            )}

            {assessment.cold_air_pooling && (
              <div className="card p-3" style={{ borderRight: '4px solid #06b6d4' }}>
                <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                  شاخص توپوگرافی تجمع هوای سرد
                </div>
                <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0891b2' }}>
                  <FormattedNumber value={assessment.cold_air_pooling.pooling_risk_proxy} digits={3} />
                </div>
                <div style={{ fontSize: '0.8rem', color: '#475569', marginTop: '2px' }}>
                  وضعیت: {assessment.cold_air_pooling.risk_label_fa}
                </div>
                <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: '2px' }}>
                  شیب میانگین: {assessment.cold_air_pooling.mean_slope_deg}° | اختلاف ارتفاع: {assessment.cold_air_pooling.relief_m}m
                </div>
              </div>
            )}
          </div>

          {/* Timeline Chart */}
          {assessment.forecast && (
            <FrostTimelineChart
              points={assessment.forecast.points}
              nights={assessment.nights}
              criticalTemp10={assessment.critical_temp_10_c}
              criticalTemp90={assessment.critical_temp_90_c}
            />
          )}

          {/* Nocturnal Risk Cards */}
          <FrostNightCards
            nights={assessment.nights}
            criticalTemp10={assessment.critical_temp_10_c}
            criticalTemp90={assessment.critical_temp_90_c}
          />

          {/* Cold-Air-Pooling Analysis & Raster Map Toggle */}
          {assessment.cold_air_pooling && (
            <ColdAirPoolingSection
              pooling={assessment.cold_air_pooling}
              geometry={{
                type: 'Point',
                coordinates: [longitude, latitude],
              }}
            />
          )}
        </>
      )}

      {/* Orchard Alert Subscription Management */}
      <div className="card mb-3" data-testid="orchards-management-card">
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="card-title">🔔 مدیریت باغات و تنظیم قواعد هشدار پیامکی / تلگرامی</span>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => handleEvaluateAlerts(true)}
              disabled={evaluating}
              data-testid="test-dry-run-eval-btn"
            >
              {evaluating ? 'در حال ارزیابی...' : 'شبیه‌سازی هشدار (Dry-Run) 🧪'}
            </button>
          </div>
        </div>

        <div className="card-body">
          {/* Add Orchard Form */}
          <form onSubmit={handleCreateOrchard} style={{ marginBottom: '20px' }}>
            <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '8px', color: '#334155' }}>
              ثبت باغ جدید در مختصات فعلی:
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                gap: '10px',
                alignItems: 'end',
              }}
            >
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', marginBottom: '3px' }}>نام باغ:</label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="مثال: باغ پسته رفسنجان قطعه ۲"
                  value={orchardName}
                  onChange={(e) => setOrchardName(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', marginBottom: '3px' }}>
                  گیرنده هشدار (موبایل یا چت‌آیدی):
                </label>
                <input
                  type="text"
                  className="form-control"
                  placeholder="+989123456789"
                  value={alertRecipient}
                  onChange={(e) => setAlertRecipient(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', marginBottom: '3px' }}>کانال ارسال:</label>
                <select
                  className="form-control"
                  value={alertChannel}
                  onChange={(e) => setAlertChannel(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                >
                  <option value="sms">پیامک (SMS)</option>
                  <option value="telegram">تلگرام (Telegram)</option>
                  <option value="webhook">وبهوک (Webhook)</option>
                  <option value="email">ایمیل (Email)</option>
                </select>
              </div>

              <div>
                <button
                  type="submit"
                  className="btn btn-secondary"
                  disabled={!orchardName.trim()}
                  style={{ width: '100%' }}
                >
                  افزودن باغ و قاعده هشدار ➕
                </button>
              </div>
            </div>
          </form>

          {/* Dry Run Evaluation Result */}
          {evalResult && (
            <div
              style={{
                backgroundColor: '#f8fafc',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                padding: '12px',
                marginBottom: '16px',
                fontSize: '0.82rem',
              }}
              data-testid="evaluation-result-panel"
            >
              <div style={{ fontWeight: 700, marginBottom: '6px', color: '#1e293b' }}>
                نتیجه ارزیابی قواعد هشدار ({evalResult.dry_run ? 'شبیه‌سازی آزمایشی / Dry-Run' : 'ارسال واقعی'}):
              </div>
              <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginBottom: '8px' }}>
                <span>باغات بررسی‌شده: {evalResult.evaluated_orchards}</span>
                <span>قواعد بررسی‌شده: {evalResult.evaluated_rules}</span>
                <span>اعلانات تولیدشده: {evalResult.dispatched_notifications}</span>
                <span style={{ color: evalResult.safety_lock_active ? '#b45309' : '#15803d' }}>
                  قفل ایمنی آستانه‌های تأییدنشده: {evalResult.safety_lock_active ? 'فعال 🔒' : 'غیرفعال'}
                </span>
              </div>
              {evalResult.notifications.map((n, idx) => (
                <div
                  key={idx}
                  style={{
                    backgroundColor: '#ffffff',
                    border: '1px solid #e2e8f0',
                    borderRadius: '4px',
                    padding: '8px 12px',
                    marginTop: '6px',
                  }}
                >
                  <div>
                    <strong>کانال:</strong> {n.channel} | <strong>گیرنده:</strong> {n.recipient} |{' '}
                    <strong>وضعیت:</strong> {n.status}
                  </div>
                  {n.payload?.reasons && (
                    <div style={{ color: '#475569', fontSize: '0.78rem', marginTop: '2px' }}>
                      علت: {n.payload.reasons.join('، ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* List Registered Orchards */}
          {loadingOrchards ? (
            <div className="text-muted text-center p-2">در حال بارگذاری باغات...</div>
          ) : orchards.length === 0 ? (
            <div className="text-muted text-center p-2">هیچ باغی تاکنون ثبت نشده است.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {orchards.map((orchard) => (
                <div
                  key={orchard.id}
                  style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '6px',
                    padding: '10px 14px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '8px',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{orchard.name}</div>
                    <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                      محصول: {orchard.crop} | مرحله: {orchard.default_phenology_stage} | قواعد فعال:{' '}
                      {orchard.alert_rules?.length || 0}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    {orchard.alert_rules?.map((rule) => (
                      <span
                        key={rule.id}
                        className="badge"
                        style={{
                          backgroundColor: '#e0f2fe',
                          color: '#0369a1',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          fontSize: '0.75rem',
                        }}
                      >
                        {rule.channel}: {rule.recipient} ({rule.lead_time_h}h)
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
