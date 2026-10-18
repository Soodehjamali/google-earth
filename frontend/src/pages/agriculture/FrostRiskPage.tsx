import React, { useState, useEffect, useCallback } from 'react';
import { frostApi } from '../../api/frost';
import type {
  FrostAssessmentResponse,
  FrostAssessRequest,
  EvaluateAlertsResponse,
  OrchardSummaryItem,
  OrchardRiskReport,
  OrchardNightRiskDetail,
} from '../../types';
import FormattedNumber from '../../components/common/FormattedNumber';
import FrostWarningBanner from '../../components/agriculture/frost/FrostWarningBanner';
import FrostTimelineChart from '../../components/agriculture/frost/FrostTimelineChart';
import FrostNightCards from '../../components/agriculture/frost/FrostNightCards';
import ColdAirPoolingSection from '../../components/agriculture/frost/ColdAirPoolingSection';
import DomainNavCards from '../../components/agriculture/DomainNavCards';
import { useAgricultureContext } from '../../components/agriculture/AgricultureLayout';

const CROP_OPTIONS = [
  { value: 'pistachio', labelFa: 'پسته' },
];

export interface PhenologyStageOption {
  value: string;
  labelFa: string;
  disabled?: boolean;
  missingDataNote?: string;
  criticalTempC?: number | null;
}

export const PUBLISHED_V1_STAGES: PhenologyStageOption[] = [
  { value: 'unopened_bud', labelFa: 'جوانه بازنشده (−۴°C)', criticalTempC: -4.0 },
  { value: 'opening_bud', labelFa: 'جوانه در حال باز شدن (Opening bud) (−۲°C)', criticalTempC: -2.0 },
  { value: 'bloom', labelFa: 'گلدهی / شکوفه بازشده (−۱.۷°C)', criticalTempC: -1.7 },
  { value: 'fruit', labelFa: 'میوه (ارزنک) (−۲°C)', criticalTempC: -2.0 },
  {
    value: 'swelling_bud',
    labelFa: 'تورم جوانه (داده منتشرشده‌ای وجود ندارد)',
    disabled: true,
    missingDataNote: 'در منبع S2 هیچ رقمی برای مرحله تورم جوانه ذکر نشده است (داده منتشرشده‌ای وجود ندارد).',
    criticalTempC: null,
  },
];

export const ENGINE_DEFAULT_STAGES: PhenologyStageOption[] = [
  { value: 'dormant', labelFa: 'خواب زمستانه (پیش‌فرض فرضی)', criticalTempC: -5.0 },
  { value: 'swelling_bud', labelFa: 'تورم جوانه (پیش‌فرض فرضی)', criticalTempC: -4.0 },
  { value: 'bud_burst', labelFa: 'جوانه در حال باز شدن (پیش‌فرض فرضی)', criticalTempC: -3.0 },
  { value: 'early_bloom', labelFa: 'اوایل گلدهی (پیش‌فرض فرضی)', criticalTempC: -2.0 },
  { value: 'full_bloom', labelFa: 'گل کامل (پیش‌فرض فرضی)', criticalTempC: -1.0 },
  { value: 'fruit_set', labelFa: 'تشکیل میوه (پیش‌فرض فرضی)', criticalTempC: -1.0 },
];

const STAGE_NAME_MAP: Record<string, string> = {
  unopened_bud: 'جوانه بازنشده',
  opening_bud: 'جوانه در حال باز شدن (Opening bud)',
  bud_burst: 'جوانه در حال باز شدن (Opening bud)',
  bloom: 'گلدهی / شکوفه بازشده',
  full_bloom: 'گل کامل',
  early_bloom: 'اوایل گلدهی',
  fruit: 'میوه (ارزنک)',
  fruit_set: 'تشکیل میوه',
  swelling_bud: 'تورم جوانه (فاقد داده)',
  dormant: 'خواب زمستانه',
};

const CATEGORY_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  critical: { bg: '#fef2f2', text: '#991b1b', border: '#f87171' },
  warning: { bg: '#fff7ed', text: '#c2410c', border: '#fb923c' },
  watch: { bg: '#fefce8', text: '#854d0e', border: '#facc15' },
  none: { bg: '#f0fdf4', text: '#166534', border: '#86efac' },
};

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
  const [stage, setStage] = useState<string>('unopened_bud');
  const [horizonH, setHorizonH] = useState<number>(72);
  const [thresholdSet, setThresholdSet] = useState<string>('published_v1');
  const [managementSoilFirmMoist, setManagementSoilFirmMoist] = useState<boolean>(false);
  const [managementIrrigated, setManagementIrrigated] = useState<boolean>(false);

  // Ad-hoc assessment results
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<FrostAssessmentResponse | null>(null);

  // Orchards list & risk summaries (R5/R6)
  const [summaries, setSummaries] = useState<OrchardSummaryItem[]>([]);
  const [loadingSummaries, setLoadingSummaries] = useState<boolean>(false);
  const [selectedOrchardId, setSelectedOrchardId] = useState<string | null>(null);
  const [orchardRiskReport, setOrchardRiskReport] = useState<OrchardRiskReport | null>(null);
  const [loadingOrchardRisk, setLoadingOrchardRisk] = useState<boolean>(false);
  const [selectedNightDate, setSelectedNightDate] = useState<string | null>(null);
  const [showRecommendations, setShowRecommendations] = useState<boolean>(true);

  // Stage update state
  const [editingStage, setEditingStage] = useState<string>('unopened_bud');
  const [updatingStage, setUpdatingStage] = useState<boolean>(false);
  const [stageUpdateMsg, setStageUpdateMsg] = useState<string | null>(null);

  // Orchard creation & alert subscription
  const [orchardName, setOrchardName] = useState<string>('');
  const [alertRecipient, setAlertRecipient] = useState<string>('');
  const [alertChannel, setAlertChannel] = useState<string>('sms');
  const [evalResult, setEvalResult] = useState<EvaluateAlertsResponse | null>(null);
  const [evaluating, setEvaluating] = useState<boolean>(false);

  // Dynamic stages based on active threshold set (R7)
  const currentStageOptions = thresholdSet === 'published_v1' ? PUBLISHED_V1_STAGES : ENGINE_DEFAULT_STAGES;

  const handleThresholdSetChange = (newSet: string) => {
    setThresholdSet(newSet);
    const options = newSet === 'published_v1' ? PUBLISHED_V1_STAGES : ENGINE_DEFAULT_STAGES;
    const currentIsValid = options.some((opt) => opt.value === stage && !opt.disabled);
    if (!currentIsValid) {
      setStage(options[0].value);
    }
  };

  // Load registered orchards summaries (R5/R6)
  const loadSummaries = useCallback(async () => {
    setLoadingSummaries(true);
    try {
      const data = await frostApi.getFrostOrchardsRiskSummary(horizonH, thresholdSet);
      setSummaries(data || []);
      if (data && data.length > 0 && !selectedOrchardId) {
        setSelectedOrchardId(data[0].orchard_id);
      }
    } catch {
      // Non-blocking in dev
    } finally {
      setLoadingSummaries(false);
    }
  }, [horizonH, thresholdSet, selectedOrchardId]);

  useEffect(() => {
    loadSummaries();
  }, [loadSummaries]);

  // Load detailed risk report when an orchard is selected
  useEffect(() => {
    if (!selectedOrchardId) {
      setOrchardRiskReport(null);
      return;
    }
    let cancelled = false;
    setLoadingOrchardRisk(true);
    frostApi
      .getFrostOrchardRisk(selectedOrchardId, horizonH, thresholdSet)
      .then((rep) => {
        if (!cancelled) {
          setOrchardRiskReport(rep);
          setEditingStage(rep.current_stage || 'unopened_bud');
          if (rep.worst_night?.night_date) {
            setSelectedNightDate(rep.worst_night.night_date);
          } else if (rep.nights && rep.nights.length > 0) {
            setSelectedNightDate(rep.nights[0].night_date);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'خطا در بارگذاری ارزیابی باغ');
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingOrchardRisk(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedOrchardId, horizonH, thresholdSet]);

  // Update current stage handler
  const handleUpdateStage = async () => {
    if (!selectedOrchardId) return;
    setUpdatingStage(true);
    setStageUpdateMsg(null);
    try {
      await frostApi.updateFrostOrchard(selectedOrchardId, { current_stage: editingStage });
      setStageUpdateMsg('مرحله فنولوژیکی با موفقیت به‌روزرسانی شد.');
      // Refetch report and summary
      const rep = await frostApi.getFrostOrchardRisk(selectedOrchardId, horizonH, thresholdSet);
      setOrchardRiskReport(rep);
      await loadSummaries();
    } catch (err) {
      setStageUpdateMsg(err instanceof Error ? err.message : 'خطا در ثبت مرحله');
    } finally {
      setUpdatingStage(false);
    }
  };

  // Run ad-hoc assessment on the inherited shared geometry
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
        threshold_set: thresholdSet,
        user_management_flags: {
          soil_firm_moist_weedfree: managementSoilFirmMoist,
          irrigated_pre_frost: managementIrrigated,
        },
      };
      const res: any = await frostApi.assessFrost(req);
      const normalized: FrostAssessmentResponse = {
        crop: res.crop,
        crop_name_fa: res.crop_fa || res.crop_name_fa || 'پسته',
        phenological_stage: res.phenological_stage,
        phenological_stage_fa: res.stage_fa || res.phenological_stage_fa || 'اوایل گلدهی',
        thresholds_verified: Boolean(res.thresholds_verified),
        evidence_level: res.evidence_level || (Boolean(res.thresholds_verified) ? 'B' : 'C'),
        critical_temp_10_c: res.t_critical_10_c ?? res.critical_temp_10_c,
        critical_temp_90_c: (res.single_critical || thresholdSet === 'published_v1') ? undefined : (res.t_critical_90_c ?? res.critical_temp_90_c),
        single_critical: Boolean(res.single_critical || thresholdSet === 'published_v1'),
        cold_air_pooling_proxy: res.pooling_risk_proxy ?? res.cold_air_pooling_proxy,
        geometry_type: res.geometry_type || (sharedGeometry.type as string),
        location_sampling_method: res.location_sampling_method || '',
        overall_max_severity: (res.overall_risk_level || res.overall_max_severity || 'none') as any,
        earliest_critical_night: res.nightly_risks?.find((n: any) => n.risk_level === 'warning' || n.risk_level === 'critical')?.night_date || null,
        active_threshold_set: res.threshold_set || res.active_threshold_set || thresholdSet,
        active_threshold_set_name_fa: res.threshold_set_name_fa || (thresholdSet === 'published_v1' ? 'آستانه‌های منتشرشده در متون علمی' : 'تنظیمات اولیه موتور (کالیبره‌نشده)'),
        active_threshold_set_status: res.threshold_set_status,
        nights: (res.nightly_risks || res.nights || []).map((n: any) => ({
          night_date: n.night_date,
          window_start_utc: n.start_time_utc || n.window_start_utc,
          window_end_utc: n.end_time_utc || n.window_end_utc,
          window_start_local: n.night_display_fa || n.window_start_local || '',
          window_end_local: n.end_time_utc || '',
          min_temp_c: n.tmin_forecast_c ?? n.min_temp_c,
          adjusted_min_temp_c: n.tmin_adjusted_c ?? n.adjusted_min_temp_c,
          effective_tmin_c: n.effective_tmin_c ?? n.tmin_adjusted_c,
          applied_protective_credit_c: n.applied_protective_credit_c ?? 0,
          pooling_cooling_bump_c: n.pooling_cooling_bump_c ?? 0,
          duration_below_t10_h: n.hours_below_tc10 ?? n.duration_below_t10_h ?? 0,
          duration_below_t90_h: n.hours_below_tc90 ?? n.duration_below_t90_h ?? 0,
          severity: n.risk_level || n.severity || 'none',
          reasons: n.recommendations_fa || n.reasons || [],
          recommendations_fa: n.recommendations_fa || [],
          duration_display_text: n.duration_display_text,
          duration_rule_explanation_fa: n.duration_rule_explanation_fa,
          min_temp_timestamp_local: n.min_temp_timestamp_local,
          active_rule_source: n.nominal_exposure?.active_rule_source,
          duration_resolvable: n.duration_resolvable,
          short_dip: n.short_dip,
          duration_escalated: n.duration_escalated,
          conflicting_published_value: n.conflicting_published_value,
          conflicting_value_note_fa: n.conflicting_value_note_fa,
          regime: n.regime,
          factor_modifiers: n.factor_modifiers || [],
          active_threshold_set: n.active_threshold_set || res.threshold_set || thresholdSet,
        })),
        forecast: res.forecast ? {
          source: res.forecast.source,
          is_fake: res.forecast.source === 'deterministic_fake' || res.forecast.metadata?.provider === 'FakeForecastProvider',
          metadata: res.forecast.metadata,
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
  }, [crop, stage, horizonH, thresholdSet, managementSoilFirmMoist, managementIrrigated, sharedGeometry]);

  // Trigger assessment on mount if shared location is present
  useEffect(() => {
    if (sharedGeometry) {
      handleRunAssessment();
    }
  }, [sharedGeometry, handleRunAssessment]);

  // "Save as orchard" reuses shared analysis geometry without re-entry
  const handleCreateOrchard = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!orchardName.trim() || !sharedGeometry) return;
    try {
      const created = await frostApi.createFrostOrchard({
        name: orchardName,
        geometry: sharedGeometry,
        crop,
        default_phenology_stage: stage,
      });

      if (alertRecipient.trim()) {
        await frostApi.createFrostAlertRule(created.id, {
          recipient: alertRecipient,
          channel: alertChannel,
          lead_time_h: 24,
          enabled: true,
        });
      }
      setOrchardName('');
      setAlertRecipient('');
      await loadSummaries();
      setSelectedOrchardId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در ثبت باغ');
    }
  };

  const handleEvaluateAlerts = async (dryRun: boolean) => {
    setEvaluating(true);
    try {
      const res = await frostApi.evaluateFrostAlerts({
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

  // Find currently active night in selected orchard risk report
  const selectedNight: OrchardNightRiskDetail | null =
    orchardRiskReport?.nights?.find((n) => n.night_date === selectedNightDate) ||
    orchardRiskReport?.nights?.[0] ||
    null;

  // Source honesty detection (R8): fake provider indicator
  const isFakeForecastUsed = Boolean(
    orchardRiskReport?.is_fake ||
    orchardRiskReport?.forecast_source === 'deterministic_fake' ||
    (assessment?.forecast && (assessment.forecast.source === 'deterministic_fake' || (assessment.forecast as any).metadata?.provider === 'FakeForecastProvider')) ||
    summaries.some((s) => s.is_fake || s.forecast_source === 'deterministic_fake')
  );

  return (
    <div className="frost-risk-page" data-testid="frost-risk-page">
      <DomainNavCards />

      {/* Source Honesty Banner (R8): Fake Provider Warning */}
      {isFakeForecastUsed && (
        <div
          data-testid="fake-provider-honesty-banner"
          style={{
            backgroundColor: '#fef2f2',
            color: '#991b1b',
            border: '2px solid #ef4444',
            borderRadius: '8px',
            padding: '12px 18px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            fontWeight: 700,
            fontSize: '0.95rem',
          }}
        >
          <span style={{ fontSize: '1.4rem' }}>⚠️</span>
          <span>داده شبیه‌سازی‌شده؛ برای تصمیم استفاده نشود</span>
        </div>
      )}

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
                پایش پیش‌بینی دما، ارزیابی اراضی باغی و هشدارهای سرمازدگی دیررس بهاره بر اساس داده‌های یکپارچه سامانه
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
              <div
                data-testid="threshold-set-badge"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: thresholdSet === 'published_v1' ? '#f0fdf4' : '#fffbeb',
                  color: thresholdSet === 'published_v1' ? '#166534' : '#92400e',
                  border: `1px solid ${thresholdSet === 'published_v1' ? '#86efac' : '#fcd34d'}`,
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                }}
              >
                <span>📚</span>
                <span>
                  {thresholdSet === 'published_v1'
                    ? 'مجموعه آستانه: published_v1 (مستند به پژوهش‌های منتشرشده پسته)'
                    : 'مجموعه آستانه: engine_default_v0 (قدیمی / کالیبره‌نشده)'}
                </span>
              </div>
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

          {/* SECTION A: Overview Table of ALL Orchards (R6 Item a) */}
          <div className="card mb-4" data-testid="orchards-overview-card">
            <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
              <div>
                <span className="card-title" style={{ fontSize: '1rem', fontWeight: 700 }}>
                  📋 جدول خلاصه وضعیت ریسک سرمازدگی باغ‌های ثبت‌شده
                </span>
                <span className="text-muted" style={{ marginRight: '8px', fontSize: '0.8rem' }}>
                  (مرتب‌شده نزولی بر اساس بیشترین شدت خطر)
                </span>
              </div>
              <div style={{ fontSize: '0.78rem', color: '#64748b' }}>
                ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)
              </div>
            </div>

            <div className="card-body" style={{ padding: 0, overflowX: 'auto' }}>
              {loadingSummaries ? (
                <div className="text-center p-4 text-muted">در حال بارگذاری خلاصه باغات...</div>
              ) : summaries.length === 0 ? (
                <div className="text-center p-4 text-muted">
                  هنوز هیچ باغی در سامانه ثبت نشده است. از فرم زیر برای ثبت باغ استفاده نمایید.
                </div>
              ) : (
                <table className="table" style={{ width: '100%', marginBottom: 0, fontSize: '0.85rem' }}>
                  <thead style={{ backgroundColor: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                    <tr>
                      <th style={{ padding: '10px 12px', textAlign: 'right' }}>نام باغ</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>مرحله رشدی</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>کمترین دمای مؤثر</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>ساعات زیر آستانه</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>رطوبت خاک</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>وزش باد</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>ریسک راهنما ٪</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>رده نهایی</th>
                      <th style={{ padding: '10px 12px', textAlign: 'center' }}>عملیات</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summaries.map((item) => {
                      const isSelected = item.orchard_id === selectedOrchardId;
                      const catStyle = CATEGORY_STYLE[item.final_category] || CATEGORY_STYLE.none;
                      const stageLabel = STAGE_NAME_MAP[item.current_stage] || item.current_stage;

                      return (
                        <tr
                          key={item.orchard_id}
                          style={{
                            backgroundColor: isSelected ? '#eff6ff' : '#ffffff',
                            borderBottom: '1px solid #f1f5f9',
                          }}
                        >
                          <td style={{ padding: '10px 12px', fontWeight: 600 }}>{item.name}</td>
                          <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                            <span>{stageLabel}</span>
                            {item.stage_is_stale && (
                              <span
                                style={{
                                  display: 'block',
                                  fontSize: '0.7rem',
                                  color: '#b45309',
                                  backgroundColor: '#fef3c7',
                                  borderRadius: '4px',
                                  padding: '1px 4px',
                                  marginTop: '2px',
                                }}
                              >
                                ⚠️ قدیمی/نامشخص
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center', direction: 'ltr' }}>
                            {item.worst_effective_tmin_c !== null && item.worst_effective_tmin_c !== undefined ? (
                              <FormattedNumber value={item.worst_effective_tmin_c} unit="°C" />
                            ) : (
                              '—'
                            )}
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                            {item.hours_below_threshold > 0 ? (
                              <span>
                                <FormattedNumber value={item.hours_below_threshold} /> ساعت
                              </span>
                            ) : (
                              <span style={{ color: '#166534' }}>هیچ شب زیر آستانه نیست</span>
                            )}
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center', direction: 'ltr' }}>
                            {item.relative_rootzone_moisture !== null && item.relative_rootzone_moisture !== undefined ? (
                              <FormattedNumber value={Math.round(item.relative_rootzone_moisture * 100)} unit="٪" />
                            ) : (
                              <span style={{ color: '#64748b' }}>نامشخص</span>
                            )}
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center', direction: 'ltr' }}>
                            {item.wind_speed_mps !== null && item.wind_speed_mps !== undefined ? (
                              <FormattedNumber value={item.wind_speed_mps} unit="m/s" />
                            ) : (
                              <span style={{ color: '#64748b' }}>نامشخص</span>
                            )}
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 700, direction: 'ltr' }}>
                            <FormattedNumber value={item.risk_index} unit="٪" />
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                            <span
                              style={{
                                display: 'inline-block',
                                padding: '2px 8px',
                                borderRadius: '4px',
                                fontSize: '0.78rem',
                                fontWeight: 600,
                                backgroundColor: catStyle.bg,
                                color: catStyle.text,
                                border: `1px solid ${catStyle.border}`,
                              }}
                            >
                              {item.final_category_fa}
                            </span>
                          </td>
                          <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                            <button
                              type="button"
                              className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-outline-primary'}`}
                              onClick={() => setSelectedOrchardId(item.orchard_id)}
                              style={{ fontSize: '0.75rem', padding: '3px 8px' }}
                            >
                              {isSelected ? 'در حال بررسی' : 'مشاهده جزئیات'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* SECTION B: Selected Orchard Factor Breakdown (R6 Item b) */}
          {selectedOrchardId && (
            loadingOrchardRisk ? (
              <div className="card mb-4 p-4 text-center text-muted" style={{ border: '2px solid #93c5fd' }}>
                در حال بارگذاری ارزیابی ریسک اختصاصی باغ...
              </div>
            ) : orchardRiskReport ? (
              <div className="card mb-4" data-testid="selected-orchard-detail-card" style={{ border: '2px solid #93c5fd' }}>
              <div className="card-header" style={{ backgroundColor: '#f0f9ff', borderBottom: '1px solid #bfdbfe' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#1e3a8a' }}>
                      🏡 ارزیابی ریسک اختصاصی: {orchardRiskReport.orchard_name}
                    </h3>
                    <div style={{ fontSize: '0.8rem', color: '#475569', marginTop: '2px' }}>
                      محصول: {orchardRiskReport.crop_fa} | دمای بحرانی مرحله:{' '}
                      <FormattedNumber value={orchardRiskReport.critical_temperature_c} unit="°C" /> | مجموعه آستانه:{' '}
                      {orchardRiskReport.threshold_set}
                    </div>
                  </div>

                  {/* Stage Update Control */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#1e3a8a', margin: 0 }}>
                      مرحله فنولوژیکی:
                    </label>
                    <select
                      className="form-control"
                      value={editingStage}
                      onChange={(e) => setEditingStage(e.target.value)}
                      data-testid="editing-stage-select-dropdown"
                      style={{ padding: '4px 8px', fontSize: '0.8rem', borderRadius: '4px', border: '1px solid #93c5fd' }}
                    >
                      {currentStageOptions.map((s) => (
                        <option key={s.value} value={s.value} disabled={s.disabled}>
                          {s.labelFa}
                        </option>
                      ))}
                    </select>
                    {editingStage === 'swelling_bud' && (
                      <span
                        data-testid="editing-stage-missing-note"
                        style={{ fontSize: '0.75rem', color: '#b91c1c', fontWeight: 600 }}
                      >
                        ⚠️ داده منتشرشده‌ای وجود ندارد
                      </span>
                    )}
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={handleUpdateStage}
                      disabled={updatingStage}
                      style={{ fontSize: '0.75rem', padding: '4px 10px' }}
                    >
                      {updatingStage ? 'در حال ثبت...' : 'به‌روزرسانی مرحله 🔄'}
                    </button>
                  </div>
                </div>

                {stageUpdateMsg && (
                  <div style={{ marginTop: '8px', fontSize: '0.8rem', color: '#15803d' }}>
                    {stageUpdateMsg}
                  </div>
                )}

                {/* Stale Stage Conservative Warning */}
                {orchardRiskReport.stage_is_stale && (
                  <div
                    style={{
                      marginTop: '8px',
                      padding: '8px 12px',
                      backgroundColor: '#fffbeb',
                      border: '1px solid #fcd34d',
                      borderRadius: '6px',
                      color: '#92400e',
                      fontSize: '0.8rem',
                    }}
                  >
                    ⚠️ <strong>توجه محافظه‌کارانه:</strong> مرحله رشدی این باغ بیش از ۱۴ روز پیش ثبت شده یا نامشخص است؛ بر اساس رویکرد محافظه‌کارانه، حساس‌ترین مرحله منظور گردیده است. لطفاً مرحله فعلی را به‌روزرسانی نمایید.
                  </div>
                )}
              </div>

              <div className="card-body">
                {/* Compact Nights Table */}
                <div style={{ marginBottom: '16px' }}>
                  <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '8px', color: '#334155' }}>
                    🌙 پیش‌بینی شب‌های آتی باغ (جهت بررسی جزئیات عوامل، شب مورد نظر را انتخاب کنید):
                  </div>
                  <div style={{ overflowX: 'auto' }}>
                    <table className="table table-sm" style={{ width: '100%', marginBottom: 0, fontSize: '0.82rem' }}>
                      <thead style={{ backgroundColor: '#f8fafc' }}>
                        <tr>
                          <th style={{ padding: '6px 10px', textAlign: 'right' }}>شب / تاریخ</th>
                          <th style={{ padding: '6px 10px', textAlign: 'center' }}>کمترین دمای مؤثر</th>
                          <th style={{ padding: '6px 10px', textAlign: 'center' }}>ساعات زیر آستانه</th>
                          <th style={{ padding: '6px 10px', textAlign: 'center' }}>ریسک راهنما ٪</th>
                          <th style={{ padding: '6px 10px', textAlign: 'center' }}>دروازه ایمنی (GATE)</th>
                          <th style={{ padding: '6px 10px', textAlign: 'center' }}>رده نهایی</th>
                          <th style={{ padding: '6px 10px', textAlign: 'center' }}>انتخاب</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orchardRiskReport.nights.map((n) => {
                          const isNightSelected = n.night_date === selectedNight?.night_date;
                          const nStyle = CATEGORY_STYLE[n.final_category] || CATEGORY_STYLE.none;

                          return (
                            <tr
                              key={n.night_date}
                              style={{
                                backgroundColor: isNightSelected ? '#dbeafe' : '#ffffff',
                                cursor: 'pointer',
                              }}
                              onClick={() => setSelectedNightDate(n.night_date)}
                            >
                              <td style={{ padding: '6px 10px', fontWeight: 600 }}>{n.night_display_fa}</td>
                              <td style={{ padding: '6px 10px', textAlign: 'center', direction: 'ltr' }}>
                                <FormattedNumber value={n.effective_tmin_c} unit="°C" />
                              </td>
                              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                                {n.hours_below_threshold > 0 ? (
                                  <span>
                                    <FormattedNumber value={n.hours_below_threshold} /> ساعت
                                  </span>
                                ) : (
                                  <span style={{ color: '#166534' }}>هیچ شب زیر آستانه نیست</span>
                                )}
                              </td>
                              <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 700, direction: 'ltr' }}>
                                <FormattedNumber value={n.risk_index} unit="٪" />
                              </td>
                              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                                {n.gate_triggered ? (
                                  <span style={{ color: '#dc2626', fontWeight: 600 }}>🚨 فعال شد</span>
                                ) : (
                                  <span style={{ color: '#64748b' }}>عادی</span>
                                )}
                              </td>
                              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                                <span
                                  style={{
                                    display: 'inline-block',
                                    padding: '1px 6px',
                                    borderRadius: '4px',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    backgroundColor: nStyle.bg,
                                    color: nStyle.text,
                                    border: `1px solid ${nStyle.border}`,
                                  }}
                                >
                                  {n.final_category_fa}
                                </span>
                              </td>
                              <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                                <input
                                  type="radio"
                                  name="selected_night"
                                  checked={isNightSelected}
                                  onChange={() => setSelectedNightDate(n.night_date)}
                                />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* ONE Factor Table for Selected Night (EXACT COLUMNS REQUIRED BY R6) */}
                {selectedNight && (
                  <div style={{ marginTop: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                      <div style={{ fontWeight: 700, fontSize: '0.92rem', color: '#1e3a8a' }}>
                        📊 تفکیک عوامل ده‌گانه مدل وزن‌دهی برای {selectedNight.night_display_fa}
                      </div>
                      <div style={{ fontSize: '0.78rem', color: '#64748b' }}>
                        برچسب: ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)
                      </div>
                    </div>

                    <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: '6px' }}>
                      <table className="table" style={{ width: '100%', marginBottom: 0, fontSize: '0.82rem' }}>
                        <thead style={{ backgroundColor: '#f1f5f9', borderBottom: '2px solid #cbd5e1' }}>
                          <tr>
                            <th style={{ padding: '8px 10px', textAlign: 'right' }}>عامل</th>
                            <th style={{ padding: '8px 10px', textAlign: 'center' }}>مقدار</th>
                            <th style={{ padding: '8px 10px', textAlign: 'right' }}>منبع و کیفیت و تاریخ داده</th>
                            <th style={{ padding: '8px 10px', textAlign: 'center' }}>وضعیت</th>
                            <th style={{ padding: '8px 10px', textAlign: 'center' }}>وزن</th>
                            <th style={{ padding: '8px 10px', textAlign: 'center' }}>امتیاز جزئی</th>
                            <th style={{ padding: '8px 10px', textAlign: 'center' }}>سهم</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedNight.factors.map((f) => (
                            <tr key={f.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                              <td style={{ padding: '8px 10px', fontWeight: 600 }}>{f.label_fa}</td>
                              <td style={{ padding: '8px 10px', textAlign: 'center', direction: 'ltr' }}>
                                {typeof f.raw_value === 'number' ? (
                                  <FormattedNumber value={f.raw_value} unit={f.unit || ''} />
                                ) : (
                                  <span>{String(f.raw_value ?? '—')} {f.unit}</span>
                                )}
                              </td>
                              <td style={{ padding: '8px 10px', fontSize: '0.75rem', color: '#475569' }}>
                                <div>{f.source_module} ({f.quality_state})</div>
                                <div style={{ color: '#94a3b8' }}>{f.as_of}</div>
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                                <span
                                  style={{
                                    display: 'inline-block',
                                    padding: '1px 6px',
                                    borderRadius: '4px',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    backgroundColor:
                                      f.status === 'مطلوب'
                                        ? '#f0fdf4'
                                        : f.status === 'نامطلوب'
                                        ? '#fef2f2'
                                        : '#f8fafc',
                                    color:
                                      f.status === 'مطلوب'
                                        ? '#166534'
                                        : f.status === 'نامطلوب'
                                        ? '#991b1b'
                                        : '#475569',
                                    border: '1px solid #cbd5e1',
                                  }}
                                >
                                  {f.status}
                                </span>
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'center', direction: 'ltr' }}>
                                <FormattedNumber value={f.weight} unit="٪" />
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'center', direction: 'ltr' }}>
                                <FormattedNumber value={f.subscore} />
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'center', fontWeight: 600, direction: 'ltr' }}>
                                <FormattedNumber value={f.contribution} unit="٪" />
                              </td>
                            </tr>
                          ))}

                          {/* Totals Row */}
                          <tr style={{ backgroundColor: '#f8fafc', fontWeight: 700, borderTop: '2px solid #cbd5e1' }}>
                            <td style={{ padding: '10px', color: '#1e3a8a' }}>مجموع</td>
                            <td style={{ padding: '10px', textAlign: 'center' }}>—</td>
                            <td style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: '#64748b' }}>
                              وزن‌ها و آستانه‌های مدل کالیبره تجربی نشده‌اند و صرفاً تخمین راهنما ارائه می‌دهند.
                            </td>
                            <td style={{ padding: '10px', textAlign: 'center' }}>—</td>
                            <td style={{ padding: '10px', textAlign: 'center', direction: 'ltr', color: '#1e3a8a' }}>
                              <FormattedNumber value={selectedNight.total_weight} unit="٪" />
                            </td>
                            <td style={{ padding: '10px', textAlign: 'center' }}>—</td>
                            <td style={{ padding: '10px', textAlign: 'center', direction: 'ltr', color: '#1e3a8a', fontSize: '0.9rem' }}>
                              <FormattedNumber value={selectedNight.total_contribution} unit="٪" />
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>

                    {/* GATE Row / Notice if Triggered */}
                    {selectedNight.gate_triggered && (
                      <div
                        data-testid="gate-triggered-notice"
                        style={{
                          marginTop: '12px',
                          padding: '10px 14px',
                          backgroundColor: '#fef2f2',
                          border: '1px solid #f87171',
                          borderRadius: '6px',
                          color: '#991b1b',
                          fontSize: '0.85rem',
                          fontWeight: 600,
                        }}
                      >
                        🚨 <strong>فعال‌سازی دروازه ایمنی (GATE):</strong>{' '}
                        {selectedNight.gate_reason_fa ||
                          'دمای مؤثر پیش‌بینی‌شده یا مدت ماندگاری به آستانه کشنده رسیده است. بر اساس اصل عدم رقیق‌سازی خطر فیزیکی، رده نهایی بدون توجه به امتیاز تجمیعی ارتقا یافت.'}
                      </div>
                    )}
                  </div>
                )}

                {/* SECTION C: Collapsible Recommendations (R6 Item c) */}
                {selectedNight && (
                  <div style={{ marginTop: '20px' }} data-testid="recommendations-section">
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        backgroundColor: '#f8fafc',
                        border: '1px solid #e2e8f0',
                        borderRadius: '6px',
                        padding: '10px 14px',
                        cursor: 'pointer',
                      }}
                      onClick={() => setShowRecommendations(!showRecommendations)}
                    >
                      <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#334155' }}>
                        🛠️ توصیه‌های فنی و تمهیدات حفاظتی باغ{' '}
                        {selectedNight.final_category === 'warning' || selectedNight.final_category === 'critical' ? (
                          <span style={{ color: '#dc2626', fontSize: '0.8rem', marginRight: '6px' }}>(نیازمند اقدام فوری)</span>
                        ) : (
                          <span style={{ color: '#166534', fontSize: '0.8rem', marginRight: '6px' }}>(اقدام اضطراری نیاز نیست)</span>
                        )}
                      </div>
                      <span style={{ fontSize: '0.85rem', color: '#64748b' }}>
                        {showRecommendations ? 'بستن ▲' : 'مشاهده توصیه‌ها ▼'}
                      </span>
                    </div>

                    {showRecommendations && (
                      <div style={{ marginTop: '8px', padding: '12px', backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '6px' }}>
                        {selectedNight.final_category === 'warning' || selectedNight.final_category === 'critical' ? (
                          orchardRiskReport.recommendations_fa && orchardRiskReport.recommendations_fa.length > 0 ? (
                            <ul style={{ margin: 0, paddingRight: '20px', lineHeight: '1.8', fontSize: '0.85rem', color: '#1e293b' }}>
                              {orchardRiskReport.recommendations_fa.map((rec, i) => (
                                <li key={i}>{rec}</li>
                              ))}
                            </ul>
                          ) : (
                            <div className="text-muted" style={{ fontSize: '0.85rem' }}>
                              توصیه اختصاصی ثبت نشده است؛ انجام آبیاری متصل به رویداد سرما و آماده‌باش سامانه‌های حرارتی توصیه می‌شود.
                            </div>
                          )
                        ) : (
                          <div style={{ fontSize: '0.85rem', color: '#166534' }}>
                            ✅ هیچ توصیه فوری برای این شب وجود ندارد (رده خطر زیر سطح هشدار است). تمهیدات حرارتی یا آبیاری اضطراری نیاز نیست.
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            ) : null
          )}

          {/* Ad-Hoc Assessment Section & Hourly Chart */}
          <div className="card mb-3" data-testid="frost-parameters-card">
            <div className="card-header">
              <span className="card-title">⚙️ تحلیل فوری محدوده جاری (Ad-Hoc Analysis)</span>
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
                    data-testid="stage-select-dropdown"
                    style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                  >
                    {currentStageOptions.map((s) => (
                      <option key={s.value} value={s.value} disabled={s.disabled}>
                        {s.labelFa}
                      </option>
                    ))}
                  </select>
                  {stage === 'swelling_bud' && (
                    <div
                      data-testid="swelling-bud-missing-note"
                      style={{ marginTop: '6px', fontSize: '0.78rem', color: '#b91c1c', fontWeight: 600 }}
                    >
                      ⚠️ در منبع S2 هیچ رقمی برای مرحله تورم جوانه ذکر نشده است (داده منتشرشده‌ای وجود ندارد).
                    </div>
                  )}
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
                    مجموعه آستانه سرمازدگی:
                  </label>
                  <select
                    className="form-control"
                    value={thresholdSet}
                    onChange={(e) => handleThresholdSetChange(e.target.value)}
                    data-testid="threshold-set-select"
                    style={{ width: '100%', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                  >
                    <option value="published_v1">published_v1 (آستانه‌های مستند علمی - حکم‌آبادی ۱۳۸۹/۱۳۹۰)</option>
                    <option value="engine_default_v0">engine_default_v0 (قدیمی / فرضی و کالیبره‌نشده)</option>
                  </select>
                </div>
              </div>

              {/* User-entered Field-Scale Management Attributes (E9) */}
              <div
                style={{
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '6px',
                  padding: '10px 14px',
                  marginBottom: '14px',
                }}
                data-testid="user-management-flags-section"
              >
                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '6px', color: '#334155' }}>
                  ویژگی‌های مدیریتی سطح باغ (جهت اعمال تخفیف حفاظتی معتبر خاک - سقف ۱.۰°C):
                </div>
                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '0.8rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={managementSoilFirmMoist}
                      onChange={(e) => setManagementSoilFirmMoist(e.target.checked)}
                      data-testid="management-soil-checkbox"
                    />
                    <span>خاک فشرده، مرطوب و عاری از علف هرز (پوشش گیاهی کف باغ زدوده شده)</span>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={managementIrrigated}
                      onChange={(e) => setManagementIrrigated(e.target.checked)}
                      data-testid="management-irrigation-checkbox"
                    />
                    <span>آبیاری متصل به رویداد سرما انجام شده است</span>
                  </label>
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
              {/* Unverified Thresholds Warning Banner */}
              {!assessment.thresholds_verified && (
                <FrostWarningBanner
                  thresholdsVerified={assessment.thresholds_verified}
                  evidenceLevel={assessment.evidence_level}
                  cropNameFa={assessment.crop_name_fa}
                  stageNameFa={assessment.phenological_stage_fa}
                  t10={assessment.critical_temp_10_c ?? undefined}
                  t90={assessment.critical_temp_90_c ?? undefined}
                />
              )}

              {/* Hourly Forecast Timeline Chart */}
              {assessment.forecast && (
                <FrostTimelineChart
                  points={assessment.forecast.series}
                  forecast={assessment.forecast}
                  criticalT10={assessment.critical_temp_10_c ?? undefined}
                  criticalT90={assessment.critical_temp_90_c ?? undefined}
                  cropNameFa={assessment.crop_name_fa}
                  stageNameFa={assessment.phenological_stage_fa}
                />
              )}

              {/* Nightly Frost Assessment Cards */}
              <FrostNightCards
                nights={assessment.nights}
                criticalT10={assessment.critical_temp_10_c ?? undefined}
                criticalT90={assessment.critical_temp_90_c ?? undefined}
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
              <span className="card-title">🔔 ثبت باغ جدید و مدیریت قواعد هشدار پیامکی</span>
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
                      گیرنده هشدار (موبایل یا ایمیل):
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
                      <option value="sms">پیامک</option>
                      <option value="email">ایمیل</option>
                      <option value="telegram">تلگرام</option>
                      <option value="webhook">وبهوک</option>
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
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
