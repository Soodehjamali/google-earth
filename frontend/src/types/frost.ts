export type FrostSeverity = 'none' | 'advisory' | 'watch' | 'warning' | 'critical';

export interface FrostPoint {
  time_utc: string;
  lead_time_h: number;
  raw_temperature_c: number;
  corrected_temperature_c: number;
  uncertainty_c: number;
  lower_bound_c: number;
  upper_bound_c: number;
  temperature_min_c?: number; // deprecated alias
  temperature_max_c?: number; // deprecated alias
  dewpoint_2m_c?: number | null;
  relative_humidity_percent?: number | null;
  wind_speed_10m_mps?: number | null;
  total_cloud_cover_percent?: number | null;
  is_interpolated: boolean;
}

export interface FrostForecastResponse {
  source?: string;
  is_fake?: boolean;
  metadata?: Record<string, any>;
  grid_elevation_m: number;
  site_elevation_m: number;
  elevation_delta_m: number;
  temperature_adjustment_c: number;
  dem_source: string;
  elevation_uncertainty_c: number;
  lead_time_uncertainty_table?: Record<string, number>;
  points?: FrostPoint[];
  series?: FrostPoint[];
  uncertainty_elevation_c?: number;
  uncertainty_forecast_c?: number;
  uncertainty_total_c?: number;
  native_spatial_resolution_m?: number;
  quality_state?: string;
}

export interface ColdAirPoolingResponse {
  pooling_risk_proxy: number;
  risk_label?: string;
  risk_label_fa?: string;
  site_elevation_m?: number;
  min_elevation_m?: number;
  max_elevation_m?: number;
  mean_elevation_m?: number;
  height_above_valley_floor_m?: number;
  p90_pooling_risk_proxy?: number;
  min_pooling_risk_proxy?: number;
  max_pooling_risk_proxy?: number;
  tpi_300m?: number;
  tpi_1000m?: number;
  relief_m?: number;
  mean_slope_deg?: number;
  disclaimer_fa?: string;
  tile_url?: string;
  raster_tile_url?: string | null;
  color_ramp?: string[];
}

export interface FactorModifier {
  id: string;
  name_fa: string;
  direction: 'aggravating' | 'protective';
  data_source: string;
  quality_state: string;
  effect_c: number;
  cap_c: number;
  applied: boolean;
  status: string;
  source: string;
  note_fa: string;
  tooltip_fa?: string | null;
}

export interface FrostRegime {
  regime: 'radiative' | 'advective' | 'mixed' | 'unknown';
  regime_fa: string;
  advice_fa: string;
  review_flag?: string | null;
  wind_speed_mps?: number | null;
  cloud_cover_percent?: number | null;
}

export interface FrostNightAssessment {
  night_date: string;
  window_start_utc: string;
  window_end_utc: string;
  window_start_local: string;
  window_end_local: string;
  min_temp_c: number;
  adjusted_min_temp_c: number;
  pooling_cooling_bump_c: number;
  duration_below_t10_h: number;
  duration_below_t90_h: number;
  severity: FrostSeverity;
  reasons: string[];
  recommendations_fa: string[];
  duration_display_text?: string;
  duration_rule_explanation_fa?: string;
  min_temp_timestamp_local?: string;
  active_rule_source?: string | null;
  duration_resolvable?: boolean;
  short_dip?: boolean;
  duration_escalated?: boolean;
  conflicting_published_value?: number | null;
  conflicting_value_note_fa?: string | null;
  regime?: FrostRegime;
  factor_modifiers?: FactorModifier[];
  effective_tmin_c?: number;
  applied_protective_credit_c?: number;
  active_threshold_set?: string;
  window_coverage?: number;
  is_partial_night?: boolean;
  cadence_label_fa?: string;
  windows?: OrchardNightRiskWindow[];
  tmin_label?: string;
  tmin_display_label_fa?: string;
  illustrative_only?: boolean;
}

export interface FrostAssessmentResponse {
  crop: string;
  crop_name_fa: string;
  phenological_stage: string;
  phenological_stage_fa: string;
  thresholds_verified: boolean;
  evidence_level?: string;
  critical_temp_10_c?: number | null;
  critical_temp_90_c?: number | null;
  single_critical?: boolean;
  cold_air_pooling_proxy?: number | null;
  geometry_type?: string;
  location_sampling_method?: string;
  nights: FrostNightAssessment[];
  overall_max_severity: FrostSeverity;
  earliest_critical_night?: string | null;
  forecast?: FrostForecastResponse;
  cold_air_pooling?: ColdAirPoolingResponse;
  active_threshold_set?: string;
  active_threshold_set_name_fa?: string;
  active_threshold_set_status?: string;
}

export interface FrostAssessRequest {
  geometry: Record<string, any>;
  crop?: string;
  phenological_stage?: string;
  horizon_h?: number;
  pooling_risk_proxy?: number | null;
  use_live_gee?: boolean;
  threshold_set?: string;
  user_management_flags?: Record<string, boolean>;
}

export interface FrostAlertRule {
  id: string;
  orchard_id: string;
  recipient: string;
  channel: string;
  lead_time_h: number;
  enabled: boolean;
  created_at: string;
}

export interface FrostOrchard {
  id: string;
  name: string;
  geometry: Record<string, any>;
  latitude?: number | null;
  longitude?: number | null;
  elevation?: number | null;
  crop: string;
  default_phenology_stage: string;
  created_at: string;
  alert_rules?: FrostAlertRule[];
}

export interface FrostOrchardCreate {
  name: string;
  geometry: Record<string, any>;
  latitude?: number | null;
  longitude?: number | null;
  elevation?: number | null;
  crop?: string;
  default_phenology_stage?: string;
}

export interface FrostAlertRuleCreate {
  recipient: string;
  channel?: string;
  lead_time_h?: number;
  enabled?: boolean;
}

export interface EvaluateAlertsRequest {
  dry_run?: boolean;
  admin_override?: boolean;
  force_crop?: string | null;
  use_live_gee?: boolean;
}

export interface NotificationLogEntry {
  id: string;
  dispatched_at: string;
  orchard_id?: string | null;
  alert_rule_id?: string | null;
  recipient: string;
  channel: string;
  status: string;
  error_message?: string | null;
  payload: Record<string, any>;
}

export interface EvaluateAlertsResponse {
  evaluated_orchards: number;
  evaluated_rules: number;
  dispatched_notifications: number;
  dry_run: boolean;
  thresholds_verified: boolean;
  safety_lock_active: boolean;
  notifications: NotificationLogEntry[];
}

export interface OrchardObservation {
  id: string;
  orchard_id: string;
  observation_date: string;
  phenological_stage: string;
  min_temp_observed_c?: number | null;
  damage_observed_fa?: string | null;
  damage_severity: 'none' | 'light' | 'moderate' | 'severe' | 'total';
  notes_fa?: string | null;
  created_at?: string;
}

export interface OrchardObservationCreate {
  observation_date: string;
  phenological_stage: string;
  min_temp_observed_c?: number | null;
  damage_observed_fa?: string | null;
  damage_severity?: 'none' | 'light' | 'moderate' | 'severe' | 'total';
  notes_fa?: string | null;
}

export interface OrchardSummaryItem {
  orchard_id: string;
  name: string;
  crop: string;
  current_stage: string;
  stage_is_stale: boolean;
  worst_night_date: string | null;
  worst_effective_tmin_c: number | null;
  hours_below_threshold: number;
  relative_rootzone_moisture: number | null;
  wind_speed_mps: number | null;
  risk_index: number;
  final_category: string;
  final_category_fa: string;
  gate_triggered: boolean;
  forecast_source?: string;
  is_fake?: boolean;
  cadence_label_fa?: string;
  worst_night_resolvable?: boolean;
  critical_temp_c?: number | null;
  stage_updated_at?: string | null;
  archived_at?: string | null;
}

export interface OrchardNightRiskFactor {
  id: string;
  label_fa: string;
  raw_value: any;
  unit: string;
  source_module: string;
  quality_state: string;
  as_of: string;
  status: string; // مطلوب / خنثی / نامطلوب / نامشخص
  weight: number;
  subscore: number;
  contribution: number;
  applied: boolean;
  source_note: string;
  is_stale: boolean;
  static?: boolean;
  details?: Record<string, any>;
  spatial_resolution_fa?: string;
  source_name_fa?: string;
}

export const FACTOR_RESOLUTION_MAP: Record<string, string> = {
  temperature_duration: '~۲۸ کیلومتر',
  phenological_stage: 'داده باغدار',
  soil_rootzone_moisture: '~۹–۱۱ کیلومتر',
  soil_texture_depth: '۲۵۰ متر',
  wind_speed: '~۲۸ کیلومتر',
  wind_direction: '~۲۸ کیلومتر',
  cloud_cover: '~۲۸ کیلومتر',
  humidity_dewpoint: '~۲۸ کیلومتر',
  topography_pooling: '۳۰ متر',
  topography_slope_aspect: '۳۰ متر',
};

export const FACTOR_SOURCE_FA_MAP: Record<string, string> = {
  temperature_duration: 'پیش‌بینی عددی GFS و مدل رقومی ارتفاع',
  phenological_stage: 'داده ثبت‌شده باغدار',
  soil_rootzone_moisture: 'پایش رطوبت ماهواره‌ای و بازتحلیل (SMAP / ERA5-Land)',
  soil_texture_depth: 'نقشه‌برداری رقومی خاک (SoilGrids)',
  wind_speed: 'پیش‌بینی جوی GFS NOAA',
  wind_direction: 'پیش‌بینی باد GFS NOAA و مدل شیب',
  cloud_cover: 'پیش‌بینی تابش و ابرناکی GFS NOAA',
  humidity_dewpoint: 'پیش‌بینی رطوبت جوی و محاسبات روان‌سنجی GFS',
  topography_pooling: 'مدل رقومی ارتفاع راداری (NASADEM)',
  topography_slope_aspect: 'مدل رقومی ارتفاع راداری (NASADEM)',
};

export interface OrchardNightRiskWindow {
  start_local: string;
  end_local: string;
  hours: number;
  min_temp_c: number;
  display_text_fa: string;
}

export interface OrchardNightRiskDetail {
  night_date: string;
  night_display_fa: string;
  start_time_utc: string;
  end_time_utc: string;
  min_temp_local_time: string;
  effective_tmin_c: number;
  hours_below_threshold: number;
  longest_continuous_hours: number;
  risk_index: number;
  index_category: string;
  gate_category: string;
  final_category: string;
  final_category_fa: string;
  gate_triggered: boolean;
  gate_reason_fa: string | null;
  factors: OrchardNightRiskFactor[];
  total_weight: number;
  total_contribution: number;
  wind_speed_mps: number | null;
  relative_moisture: number | null;
  window_coverage: number;
  is_partial_night: boolean;
  duration_display_text: string;
  cadence_label_fa?: string;
  is_duration_resolvable?: boolean;
  windows?: OrchardNightRiskWindow[];
}

export interface OrchardRiskReport {
  orchard_id: string;
  orchard_name: string;
  crop: string;
  crop_fa: string;
  current_stage: string;
  stage_fa: string;
  stage_is_stale: boolean;
  critical_temperature_c: number;
  threshold_set: string;
  thresholds_verified: boolean;
  evidence_level: string;
  index_is_probability: boolean;
  stage_updated_at?: string | null;
  guidance_risk_label_fa: string;
  overall_final_category: string;
  overall_final_category_fa: string;
  worst_night: {
    night_date: string;
    effective_tmin_c: number;
    risk_index: number;
    final_category: string;
    final_category_fa: string;
    gate_triggered: boolean;
    hours_below_threshold: number;
  } | null;
  nights: OrchardNightRiskDetail[];
  recommendations_fa: string[];
  assembled_at: string;
  forecast_source?: string;
  is_fake?: boolean;
  registered_elevation_m?: number | null;
  dem_elevation_m?: number | null;
  has_elevation_discrepancy?: boolean;
  elevation_discrepancy_warning_fa?: string | null;
}

