export type FrostSeverity = 'none' | 'advisory' | 'watch' | 'warning';

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
  grid_elevation_m: number;
  site_elevation_m: number;
  elevation_delta_m: number;
  temperature_adjustment_c: number;
  dem_source: string;
  elevation_uncertainty_c: number;
  lead_time_uncertainty_table: Record<string, number>;
  points: FrostPoint[];
  native_spatial_resolution_m?: number;
  quality_state?: string;
}

export interface ColdAirPoolingResponse {
  pooling_risk_proxy: number;
  risk_label: string;
  risk_label_fa: string;
  site_elevation_m: number;
  min_elevation_m: number;
  max_elevation_m: number;
  relief_m: number;
  mean_slope_deg: number;
  disclaimer_fa: string;
  tile_url?: string;
  color_ramp?: string[];
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
}

export interface FrostAssessmentResponse {
  crop: string;
  crop_name_fa: string;
  phenological_stage: string;
  phenological_stage_fa: string;
  thresholds_verified: boolean;
  evidence_level?: string;
  critical_temp_10_c: number;
  critical_temp_90_c: number;
  cold_air_pooling_proxy?: number | null;
  nights: FrostNightAssessment[];
  overall_max_severity: FrostSeverity;
  earliest_critical_night?: string | null;
  forecast?: FrostForecastResponse;
  cold_air_pooling?: ColdAirPoolingResponse;
}

export interface FrostAssessRequest {
  geometry: Record<string, any>;
  crop?: string;
  phenological_stage?: string;
  horizon_h?: number;
  pooling_risk_proxy?: number | null;
  use_live_gee?: boolean;
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
