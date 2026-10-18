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
import { useAgricultureContext } from '../../components/agriculture/AgricultureLayout';

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
  // Shared analysis scope context inheritance (E7)
  let agriContext: ReturnType<typeof useAgricultureContext> | null = null;
  try {
    agriContext = useAgricultureContext();
  } catch {
    agriContext = null;
  }

  const sharedGeometry = agriContext?.lastRequest?.geometry || agriContext?.result?.geometry || null;
  const sharedLocationName = agriContext?.lastRequest?.name || agriContext?.result?.location_name || 'محدوده انتخاب‌شده در تحلیل';

  // Input states (no manual lat/lon or two points inputs)
  const [crop, setCrop] = useState<string>('pistachio');
  const [stage, setStage] = useState<string>('early_bloom');
  const [horizonH, setHorizonH] = useState<number>(72);

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

  // Run assessment on the inherited shared geometry
  const handleRunAssessment = useCallback(async () => {
    if (!sharedGeometry) return;
    setLoading(true);
    setError(null);
    try {
      const req: FrostAssessRequest = {
        geometry: sharedGeometry,
        crop,
        phenological_stage: stage,
        horizon_h: horizonH,
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
        geometry_type: res.geometry_type || (sharedGeometry.type as string),
        location_sampling_method: res.location_sampling_method || '',
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
          uncertainty_forecast_c: res.forecast.series?.[0]?.lead_time_uncertainty_c ?? res.forecast.uncertainty_forecast_c ?? 0,
          uncertainty_total_c: res.forecast.series?.[0]?.total_uncertainty_c ?? res.forecast.uncertainty_total_c ?? 0,
          series: res.forecast.series || [],
        } : undefined,
        cold_air_pooling: res.cold_air_pooling ? {
          pooling_risk_proxy: res.cold_air_pooling.mean_pooling_risk_proxy ?? res.cold_air_pooling.pooling_risk_proxy ?? 0,
          p90_pooling_risk_proxy: res.cold_air_pooling.p90_pooling_risk_proxy ?? 0,
          min_pooling_risk_proxy: res.cold_air_pooling.min_pooling_risk_proxy ?? 0,
          max_pooling_risk_proxy: res.cold_air_pooling.max_pooling_risk_proxy ?? 0,
          min_elevation_m: res.cold_air_pooling.min_elevation_m ?? 0,
          max_elevation_m: res.cold_air_pooling.max_elevation_m ?? 0,
          mean_elevation_m: res.cold_air_pooling.mean_elevation_m ?? 0,
          height_above_valley_floor_m: res.cold_air_pooling.height_above_valley_floor_m ?? 0,
          mean_slope_deg: res.cold_air_pooling.mean_slope_deg ?? 0,
          tpi_300m: res.cold_air_pooling.tpi_300m ?? 0,
          tpi_1000m: res.cold_air_pooling.tpi_1000m ?? 0,
          raster_tile_url: res.cold_air_pooling.tile_url ?? res.cold_air_pooling.raster_tile_url ?? null,
          color_ramp: [
            '#f7fcf0',
            '#bae4bc',
            '#7bccc4',
            '#43a2ca',
            '#0868ac',
          ],
        } : undefined,
      };
      setAssessment(normalized);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در اجرای ارزیابی سرمازدگی');
    } finally {
      setLoading(false);
    }
  }, [crop, stage, horizonH, sharedGeometry]);

  // Automatically trigger assessment on mount if shared location is present
  useEffect(() => {
    if (sharedGeometry) {
      handleRunAssessment();
    }
  }, [sharedGeometry, handleRunAssessment]);

  // Load registered orchards
  const loadOrchards = useCallback(async () => {
    setLoadingOrchards(true);
    try {
      const data = await agricultureApi.listFrostOrchards();
      setOrchards(data || []);
    } catch {
      // Non-blocking in dev
    } finally {
      setLoadingOrchards(false);
    }
  }, []);

  useEffect(() => {
    loadOrchards();
  }, [loadOrchards]);

  // "Save as orchard" reuses shared analysis geometry without re-entry
  const handleCreateOrchard = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orchardName.trim() || !sharedGeometry) return;
    try {
      const created = await agricultureApi.createFrostOrchard({
        name: orchardName,
        geometry: sharedGeometry,
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

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
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
      </div>

      {/* Shared Location Empty State (E7) */}
      {!sharedGeometry ? (
        <div
          data-testid="frost-empty-state"
          style={{
            padding: '40px 20px',
            textAlign: 'center',
            backgroundColor: '#0f172a',
            border: '2px dashed #334155',
            borderRadius: '12px',
            margin: '24px 0',
          }}
        >
          <div style={{ fontSize: '2.5rem', marginBottom: '12px' }}>📍</div>
          <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#f1f5f9', marginBottom: '8px' }}>
            موقعیتی تعیین نشده است
          </h3>
          <p style={{ fontSize: '0.95rem', color: '#94a3b8', margin: 0 }}>
            ابتدا موقعیت را در کادر محدوده تعیین کنید
          </p>
        </div>
      ) : (
        <>
          {/* Shared Analysis Location Scope Badge */}
          <div
            data-testid="shared-location-badge"
            style={{
              padding: '12px 16px',
              backgroundColor: '#1e293b',
              border: '1px solid #334155',
              borderRadius: '8px',
              marginBottom: '16px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '12px',
              fontSize: '0.85rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '1.2rem' }}>🏡</span>
              <strong style={{ color: '#f8fafc' }}>موقعیت تحلیل:</strong>
              <span style={{ color: '#cbd5e1' }}>{sharedLocationName}</span>
              <span
                style={{
                  backgroundColor: '#0f172a',
                  color: '#34d399',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                  border: '1px solid #334155',
                  fontWeight: 600,
                }}
              >
                {sharedGeometry.type === 'Polygon' ? 'چندضلعی باغ (Polygon)' : 'نقطه مکانی (GPS Point)'}
              </span>
            </div>
            {assessment && (
              <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>
                {assessment.location_sampling_method || (assessment.geometry_type === 'Point' ? 'نمونه‌برداری در نقطه GPS با بافر حوضچه' : 'پیش‌بینی سلول مرکز چندضلعی')}
              </div>
            )}
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

          {/* Parameter Controls Form (No manual coordinates) */}
          <div className="card mb-3" data-testid="frost-parameters-card">
            <div className="card-header">
              <span className="card-title">⚙️ تنظیمات تحلیل سرمازدگی</span>
            </div>
            <div className="card-body">
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
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
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleRunAssessment}
                  disabled={loading}
                  data-testid="run-frost-btn"
                  style={{ minWidth: '180px' }}
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
                    {assessment.overall_max_severity === 'critical' && '🔴 بحرانی (خطر بسیار بالا)'}
                    {assessment.overall_max_severity === 'warning' && '🟠 هشدار (خطر جدی)'}
                    {assessment.overall_max_severity === 'watch' && '🟡 مراقبت (پایش مستمر)'}
                    {assessment.overall_max_severity === 'none' && '🟢 ایمن (بدون سرمازدگی)'}
                  </div>
                </div>

                <div className="card p-3" style={{ borderRight: '4px solid #3b82f6' }}>
                  <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                    اولین شب مواجهه با دمای بحرانی
                  </div>
                  <div style={{ fontSize: '1.15rem', fontWeight: 700 }}>
                    {assessment.earliest_critical_night || 'هیچ شبی زیر آستانه بحرانی نیست'}
                  </div>
                </div>

                <div className="card p-3" style={{ borderRight: '4px solid #10b981' }}>
                  <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                    آستانه تحمل مرحله (T10 / T90)
                  </div>
                  <div style={{ fontSize: '1.15rem', fontWeight: 700, display: 'flex', gap: '8px' }}>
                    <span>
                      T10: <FormattedNumber value={assessment.critical_temp_10_c} unit="°C" />
                    </span>
                    <span className="text-muted">|</span>
                    <span>
                      T90: <FormattedNumber value={assessment.critical_temp_90_c} unit="°C" />
                    </span>
                  </div>
                </div>

                <div className="card p-3" style={{ borderRight: '4px solid #8b5cf6' }}>
                  <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '4px' }}>
                    شاخص تجمع هوای سرد (ناهمواری)
                  </div>
                  <div style={{ fontSize: '1.15rem', fontWeight: 700 }}>
                    {assessment.cold_air_pooling_proxy !== undefined && assessment.cold_air_pooling_proxy !== null ? (
                      <span>{assessment.cold_air_pooling_proxy.toFixed(2)} / 1.00</span>
                    ) : (
                      'محاسبه‌نشده'
                    )}
                  </div>
                </div>
              </div>

              {/* Hourly Forecast Timeline Chart */}
              {assessment.forecast && (
                <FrostTimelineChart
                  points={assessment.forecast.series}
                  forecast={assessment.forecast}
                  criticalT10={assessment.critical_temp_10_c}
                  criticalT90={assessment.critical_temp_90_c}
                  cropNameFa={assessment.crop_name_fa}
                  stageNameFa={assessment.phenological_stage_fa}
                />
              )}

              {/* Nightly Frost Assessment Cards */}
              <FrostNightCards
                nights={assessment.nights}
                criticalT10={assessment.critical_temp_10_c}
                criticalT90={assessment.critical_temp_90_c}
              />

              {/* Cold-Air Pooling Topography Section */}
              {assessment.cold_air_pooling && (
                <ColdAirPoolingSection
                  pooling={assessment.cold_air_pooling}
                  geometry={sharedGeometry}
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
              {/* Add Orchard Form (Reuses shared analysis geometry) */}
              <form onSubmit={handleCreateOrchard} style={{ marginBottom: '20px' }} data-testid="save-as-orchard-form">
                <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '8px', color: '#334155' }}>
                  ثبت محدوده تحلیل جاری به عنوان باغ پسته (استفاده مستقیم از هندسه تحلیل):
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
                      data-testid="save-orchard-submit-btn"
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
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
