// Location types
export interface Location {
  id: string;
  name: string | null;
  geometry: GeoJSON.Geometry;
  latitude: number | null;
  longitude: number | null;
  area_sq_meters: number | null;
  centroid_lat: number | null;
  centroid_lng: number | null;
  geometry_type: string;
  created_at: string;
  updated_at: string;
}

export interface LocationCreate {
  name?: string;
  latitude?: number;
  longitude?: number;
  geometry?: GeoJSON.Geometry;
}

// Analysis types
export type AnalysisType = 'complete' | 'vegetation' | 'climate' | 'soil' | 'water' | 'landcover' | 'historical';
export type TemporalResolution = 'daily' | 'weekly' | 'monthly' | 'seasonal' | 'yearly';
export type AnalysisStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface AnalysisCreate {
  geometry: GeoJSON.Geometry;
  start_date: string;
  end_date: string;
  analysis_type: AnalysisType;
  temporal_resolution: TemporalResolution;
  location_id?: string;
}

export interface Analysis {
  id: string;
  location_id: string;
  start_date: string;
  end_date: string;
  analysis_type: AnalysisType;
  temporal_resolution: TemporalResolution;
  status: AnalysisStatus;
  error_message: string | null;
  completed_at: string | null;
  result_data: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

// Vegetation types
export interface VegetationStats {
  index_name: string;
  mean: number | null;
  median: number | null;
  min: number | null;
  max: number | null;
  std: number | null;
  percentile_10: number | null;
  percentile_25: number | null;
  percentile_75: number | null;
  percentile_90: number | null;
  unit: string;
  data_quality: string;
  observation_count: number;
}

export interface NDVIResult {
  latitude: number;
  longitude: number;
  ndvi_mean: number | null;
  ndvi_min: number | null;
  ndvi_max: number | null;
  ndvi_std: number | null;
  observation_count: number;
  cloud_coverage_percent: number | null;
  data_quality: string;
  interpretation: string;
}

// Time series types
export interface TimeSeriesPoint {
  date: string;
  ndvi: number | null;
  evi: number | null;
  savi: number | null;
  ndwi: number | null;
}

export interface TimeSeriesResponse {
  analysis_id: string;
  data: TimeSeriesPoint[];
  temporal_resolution: string;
  data_quality: string;
}

// Map types
export interface MapLayer {
  id: string;
  name: string;
  name_fa: string | null;
  visible: boolean;
  opacity: number;
  min_value: number | null;
  max_value: number | null;
  palette: string[] | null;
  dataset_id: string | null;
  band: string | null;
}

export interface MapVisualization {
  analysis_id: string;
  center: [number, number];
  zoom: number;
  layers: MapLayer[];
  bounds: [number, number][] | null;
}

export interface MapLegendItem {
  color: string;
  label: string;
}

export interface MapLegend {
  layer_id: string;
  title: string;
  items: MapLegendItem[];
}

// Earth Engine health types
export type EarthEngineErrorCode =
  | 'not_configured'
  | 'invalid_configuration'
  | 'auth_failed'
  | 'not_enabled'
  | 'not_registered'
  | 'permission_denied'
  | 'connection_failed'

export interface EarthEngineHealth {
  status: 'connected' | 'error'
  earth_engine: boolean
  authenticated?: boolean
  project?: string | null
  code?: EarthEngineErrorCode
  message?: string
  checked_at?: string
}

export type EarthEngineIndicatorState =
  | 'checking'
  | 'connected'
  | 'disconnected'
  | 'configuration_error'

// Risk types
export interface RiskScore {
  score: number | null;
  level: string | null;
  components: {
    vegetation?: number;
    water?: number;
    rainfall?: number;
    temperature?: number;
    soil?: number;
  };
}

// Agricultural Intelligence API types (Phase Q) — mirrors
// backend/app/schemas/agriculture.py exactly.

export interface PointGeometry {
  type: 'Point';
  coordinates: number[];
}

export interface PolygonGeometry {
  type: 'Polygon';
  coordinates: number[][][];
}

export type AgricultureGeometry = PointGeometry | PolygonGeometry;

export interface AgricultureAnalysisRequest {
  geometry: AgricultureGeometry;
  start_date: string;
  end_date: string;
  domains?: string[] | null;
  cloud_max_percent?: number;
  ground_truth?: GroundTruthObservationInput[] | null;
  name?: string | null;
  request_id?: string | null;
  location_id?: string | null;
}

export interface AgricultureHistoryItemSummary {
  id: string;
  location_id: string;
  location_name: string | null;
  geometry_type: string;
  latitude: number | null;
  longitude: number | null;
  area_sq_meters: number | null;
  start_date: string;
  end_date: string;
  status: 'completed' | 'running' | 'failed' | string;
  created_at: string;
  completed_at: string | null;
  overall_sufficiency: string | null;
  synthesis_status: string | null;
  error_message: string | null;
  model_version?: string | null;
}

export interface AgricultureHistoryListResponse {
  items: AgricultureHistoryItemSummary[];
  total: number;
  skip: number;
  limit: number;
}


/**
 * Reference observation record (P6.1 GroundTruthObservation-compatible).
 * Mirrors the existing backend contract: all fields optional here so the
 * form can submit partial drafts, but the backend ingestion boundary
 * decides usability (identity, time, variable, source/method required;
 * at least one of value/state). Invalid records are reported as
 * rejected — never silently repaired.
 */
export interface GroundTruthObservationInput {
  observation_id?: string;
  variable?: string;
  value?: number | null;
  unit?: string;
  state?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  observed_on?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  source?: string;
  method?: string;
  quality?: string;
  status?: string;
  metric_key?: string | null;
  domain?: string | null;
  cell_id?: string | null;
  provenance?: Record<string, unknown>;
  limitations?: string[];
}

export interface EvidenceItemInput {
  metric_key: string;
  value?: number | null;
  unit?: string;
  status?: string;
  quality?: string;
  source_dataset?: string | null;
  display_name?: string;
}

export interface DomainEvidenceInput {
  items: EvidenceItemInput[];
}

export interface SynthesisOnlyRequest {
  evidence_bundles: Record<string, DomainEvidenceInput>;
  time_start?: string | null;
  time_end?: string | null;
  spatial_context?: string | null;
}

export type QualityState = 'valid' | 'coarse_context' | 'unavailable';

export interface ProvenanceResponse {
  source_dataset_id?: string | null;
  source_dataset_name?: string | null;
  bands: string[];
  formula: string;
  unit: string;
  spatial_resolution: string;
  temporal_resolution: string;
  aggregation_method: string;
  measurement_basis: string;
  quality_level: string;
  quality_state?: QualityState | null;
  native_resolution_m?: number | null;
  support_description?: string | null;
  support_description_fa?: string | null;
  cell_elevation_m?: number | null;
  site_elevation_m?: number | null;
  raw_value?: number | null;
  corrected_value?: number | null;
  delta_c?: number | null;
  uncertainty_c?: number | null;
  temporal_kind: string;
  requested_start?: string | null;
  requested_end?: string | null;
  product_date?: string | null;
  date_start?: string | null;
  date_end?: string | null;
  image_count?: number | null;
  fallback_from?: string | null;
  limitations: string[];
  caveats: string[];
  citation: string;
  computed_at?: string | null;
  /**
   * Point-support disclosure. Present only when the request geometry
   * was a Point, which has no area of its own; absent for a Polygon.
   */
  geometry_type?: string | null;
  support_radius_m?: number | null;
  support_area_sq_m?: number | null;
  support_family?: string | null;
  support_policy?: string | null;
  support_native_resolution_m?: number | null;
  original_geometry?: { type?: string; coordinates?: unknown } | null;
  support_inputs?: SupportInputDTO[] | null;
}

/** One support region a derived value was built from. */
export interface SupportInputDTO {
  dataset_id?: string | null;
  family?: string | null;
  radius_m?: number | null;
  area_sq_m?: number | null;
  native_resolution_m?: number | null;
  point_queryable?: boolean | null;
}

export interface SpatialStatsDTO {
  mean?: number | null;
  median?: number | null;
  min?: number | null;
  max?: number | null;
  std_dev?: number | null;
  p10?: number | null;
  p25?: number | null;
  p75?: number | null;
  p90?: number | null;
  valid_pixel_count: number;
  valid_area_sq_m: number;
  total_pixel_count: number;
  missing_pixel_count: number;
  missing_percent: number;
  coverage_percent: number;
}

export interface ClassHistogramEntryDTO {
  code: number;
  name: string;
  pixel_count: number;
  percent: number;
  percent_of_geometry: number;
}

export interface ClassHistogramDTO {
  entries: ClassHistogramEntryDTO[];
  dominant_code?: number | null;
  dominant_name: string;
  valid_pixel_count: number;
  total_pixel_count: number;
}

export interface EvidenceItemResponse {
  metric_key: string;
  value?: number | null;
  unit: string;
  status: string;
  quality: string;
  quality_state?: QualityState | null;
  native_resolution_m?: number | null;
  support_description?: string | null;
  support_description_fa?: string | null;
  cell_elevation_m?: number | null;
  site_elevation_m?: number | null;
  raw_value?: number | null;
  corrected_value?: number | null;
  delta_c?: number | null;
  uncertainty_c?: number | null;
  source_dataset?: string | null;
  display_name: string;
  temporal_start?: string | null;
  temporal_end?: string | null;
  is_usable: boolean;
  is_proxy: boolean;
  is_coarse_context?: boolean;
  provenance?: ProvenanceResponse | null;
  stats?: SpatialStatsDTO | null;
  class_histogram?: ClassHistogramDTO | null;
  band_means?: Record<string, number | null> | null;
  /** Why the metric produced no value, verbatim from the metric. */
  unavailable_reason?: string | null;
  unavailable_message?: string | null;
}

export interface EvidenceConflictResponse {
  metric_a: string;
  metric_b: string;
  status: string;
  explanation: string;
  possible_explanations: string[];
}

export interface EvidenceSufficiencyResponse {
  level: string;
  available_count: number;
  unavailable_count: number;
  distinct_sources: number;
  min_quality?: string | null;
  has_conflicts: boolean;
  key_reasons: string[];
}

export interface EvidenceBundleResponse {
  name: string;
  items: EvidenceItemResponse[];
  available: string[];
  unavailable: string[];
  source_datasets: string[];
  conflicts: EvidenceConflictResponse[];
  sufficiency?: EvidenceSufficiencyResponse | null;
  limitations: string[];
}

export interface SynthesisStatementResponse {
  rule_id: string;
  domain: string;
  pattern: string;
  statement: string;
  evidence_keys: string[];
  evidence_values: Record<string, number | null>;
  scientific_basis: string;
  limitations: string[];
  sufficiency: string;
  conflicts: string[];
}

export interface DomainSummaryResponse {
  domain: string;
  statement_count: number;
  statements: SynthesisStatementResponse[];
  unavailable_evidence: string[];
  sufficiency: string;
  limitations: string[];
  conflicts?: string[];
  /** True when the bundle held ≥1 usable evidence item (finite value, not unavailable, usable quality) — independent of statement generation (F-CONTRACT-FIX-1). */
  has_usable_evidence?: boolean;
  vegetation_regime?: string | null;
}

export interface AgriculturalAnalysisResponse {
  request_id?: string | null;
  time_start?: string | null;
  time_end?: string | null;
  spatial_context?: string | null;
  generated_at?: string | null;
  geometry?: AgricultureGeometry | null;
  location_name?: string | null;
  area_sq_meters?: number | null;
  domain_summaries: Record<string, DomainSummaryResponse>;
  cross_domain_statements: SynthesisStatementResponse[];
  overall_sufficiency: string;
  evidence_bundles: Record<string, EvidenceBundleResponse>;
  available_domains: string[];
  unavailable_domains: string[];
  /** Domains whose bundles hold ≥1 usable evidence item — data presence, independent of statements (F-CONTRACT-FIX-1, additive). */
  domains_with_data?: string[];
  /** Domains where ≥1 synthesis rule fired — same content as the legacy statement-based available_domains (additive). */
  domains_with_statements?: string[];
  /** Domains whose bundles hold no usable evidence item at all (additive). */
  domains_without_data?: string[];
  /** De-duplicated unavailable metric keys across all bundles; each key counts exactly once (canonical aggregate, additive). */
  unavailable_metric_keys?: string[];
  limitations: string[];
  metadata: Record<string, string>;
  /** Additive P-AGRI-1 vegetation regime classification (e.g. non_vegetated, vegetated, uncertain). */
  vegetation_regime?: string | null;
  vegetation_regime_explanation?: string | null;
  /** Additive P5.3 temporal intelligence; null when the response predates it. */
  temporal?: TemporalSectionPayload | null;
  /** Additive P5.3-S spatial intelligence; null when no metric is spatially supported or cached response predates spatial contract. */
  spatial?: SpatialSectionPayload | null;
  /** Additive P6.3 ground-truth validation; null when no reference observations were supplied. */
  validation?: ValidationSection | null;
  /** Additive P-AGRI-SOIL soil intelligence; deterministic soil moisture and SoilGrids 2.0 properties. */
  soil_intelligence?: SoilIntelligenceResponse | null;
  /** Additive P1 pest & disease risk screening and multi-sensor inspection. */
  pest_disease_inspection?: PestDiseaseInspectionResponse | null;
  /** Additive Phase 2 Task 2.3 dynamic coverage summary partitioning valid, coarse context, and unavailable metrics. */
  coverage?: CoverageSummaryResponse | null;
}

export interface DomainCoverageResponse {
  valid: number;
  coarse_context: number;
  unavailable: number;
  total: number;
  valid_ratio: number;
}

export interface CoverageSummaryResponse {
  valid: number;
  coarse_context: number;
  unavailable: number;
  total: number;
  valid_ratio: number;
  by_domain: Record<string, DomainCoverageResponse>;
}

export interface ErrorResponse {
  error: string;
  detail: Record<string, unknown>;
  reason_code?: string | null;
}

export interface AgricultureHealthResponse {
  status: string;
  metrics_registered: number;
  evidence_layer: string;
  synthesis_layer: string;
  message: string;
}

// Temporal profile contract (P1.1 foundation) — mirrors the backend
// temporal_profile representation for a future temporal chart.
// Missing months are explicit nulls; no interpolation is represented.

export interface TemporalProfilePoint {
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
}

export interface TemporalProfile {
  metric_key: string;
  dataset_id?: string | null;
  unit: string;
  window_start: string;
  window_end: string;
  step: string;
  points: TemporalProfilePoint[];
}

// Baseline and anomaly contract (P1.2 foundation) — mirrors the
// backend baseline_anomaly representation. Categories are neutral
// statistics, never a diagnosis or probability.

export interface ProfileBaseline {
  metric_key: string;
  strategy: string;
  n_observations: number;
  n_usable: number;
  mean: number;
  std: number | null;
  minimum: number;
  maximum: number;
  median: number;
  reference_start?: string | null;
  reference_end?: string | null;
  window_start: string;
  window_end: string;
  spread_reliable: boolean;
  quality_counts: Record<string, number>;
  mean_coverage_percent: number | null;
}

export interface AnomalyPoint {
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  z_score: number | null;
  percentile: number | null;
  category: string;
}

export interface AnomalyProfile {
  metric_key: string;
  unit: string;
  window_start: string;
  window_end: string;
  step: string;
  baseline: ProfileBaseline | null;
  points: AnomalyPoint[];
}

// Change and breakpoint contract (P1.3 foundation) — mirrors the
// backend change_profile representation. Directions and flags are
// neutral statistics, never a diagnosis or probability.

export interface MonthChange {
  window_start: string;
  window_end: string;
  value: number | null;
  previous_window_start?: string | null;
  previous_window_end?: string | null;
  previous_value: number | null;
  absolute_change: number | null;
  relative_change: number | null;
  days_elapsed: number | null;
  rate_per_day: number | null;
  direction: string;
  rapid: string;
  z_score: number | null;
  percentile: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
}

export interface DeviationPersistence {
  longest_run_below: number;
  longest_run_above: number;
  n_anomalous: number;
  n_observed: number;
  n_missing: number;
  state: string;
}

export interface Breakpoint {
  onset_window_start: string;
  onset_window_end: string;
  direction: string;
  pre_level: number;
  post_level: number;
  magnitude: number;
  window_months: number;
  n_usable: number;
  method: string;
}

export interface ChangeProfile {
  metric_key: string;
  unit: string;
  window_start: string;
  window_end: string;
  step: string;
  changes: MonthChange[];
  persistence: DeviationPersistence;
  breakpoint: Breakpoint | null;
}

// Joint NDVI-moisture contract (P1.4 foundation) — mirrors the
// backend joint_profile representation. Patterns and states are
// neutral statistics, never a diagnosis or probability. The
// moisture side is NDMI (Gao); McFeeters NDWI is an open-water
// index and has no place in this contract.

export interface JointPoint {
  window_start: string;
  window_end: string;
  ndvi: number | null;
  moisture: number | null;
  ndvi_z: number | null;
  moisture_z: number | null;
  availability: string;
  ndvi_quality: string;
  moisture_quality: string;
  ndvi_coverage: number | null;
  moisture_coverage: number | null;
}

export interface JointProfile {
  ndvi_key: string;
  moisture_key: string;
  window_start: string;
  window_end: string;
  step: string;
  points: JointPoint[];
}

export interface JointChange {
  window_start: string;
  window_end: string;
  previous_window_start?: string | null;
  ndvi_change: number | null;
  moisture_change: number | null;
  ndvi_direction: string;
  moisture_direction: string;
  pattern: string;
  divergence: string;
  days_elapsed: number | null;
}

export interface LagResult {
  lag_months: number;
  n_paired: number;
  agreement: number | null;
  correlation: number | null;
  sufficient: boolean;
  method: string;
}

export interface ScatterPoint {
  window_start: string;
  ndvi: number;
  moisture: number;
  ndvi_z: number | null;
  moisture_z: number | null;
  ndvi_quality: string;
  moisture_quality: string;
}

export interface ScatterDataset {
  ndvi_key: string;
  moisture_key: string;
  points: ScatterPoint[];
  correlation: number | null;
  n_paired: number;
  method: string;
}

export interface JointAnalysis {
  ndvi_key: string;
  moisture_key: string;
  window_start: string;
  window_end: string;
  step: string;
  joint: JointProfile;
  changes: JointChange[];
  lags: LagResult[];
  scatter: ScatterDataset | null;
}

// Spatial anomaly and hotspot contract (P1.5 foundation) — mirrors
// the backend spatial_profile representation. Area and concordance
// states are neutral spatial posture, never a diagnosis or
// probability.

export interface SpatialCell {
  cell_id: string;
  row: number;
  col: number;
  west: number;
  south: number;
  east: number;
  north: number;
  geometry: Record<string, unknown>;
}

export interface CellObservation {
  cell_id: string;
  metric_key: string;
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  z_score: number | null;
  category: string | null;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
}

export interface SpatialSummary {
  metric_key: string;
  window_start: string;
  window_end: string;
  n_cells: number;
  n_usable: number;
  n_missing: number;
  mean: number | null;
  median: number | null;
  anomalous_count: number;
  anomalous_fraction: number | null;
  min_coverage_percent: number | null;
  mean_coverage_percent: number | null;
  quality_counts: Record<string, number>;
  state: string;
  method: string;
}

export interface CellConcordance {
  cell_id: string;
  window_start: string;
  window_end: string;
  metrics: string[];
  anomalous_metrics: string[];
  state: string;
}

export interface CellPersistence {
  cell_id: string;
  longest_run_below: number;
  longest_run_above: number;
  n_anomalous: number;
  n_observed: number;
  n_missing: number;
  state: string;
}

// Spectral-profile contract (P2.1 foundation) — mirrors the
// backend spectral_profile representation. Samples are discrete
// multispectral reflectance observations (never interpolated,
// never zero-filled); statuses are neutral availability states
// (available, insufficient, unavailable), never a cause
// attribution, threshold, score, or probability. No chart is
// built in this phase; these types only carry the contract.

export interface SpectralBandSample {
  band: string;
  wavelength_nm: number;
  value: number | null;
  unit: string;
  status: string;
  quality: string;
  coverage_percent: number | null;
}

export interface SpectralSlope {
  from_band: string;
  to_band: string;
  wavelength_from_nm: number;
  wavelength_to_nm: number;
  value_from: number | null;
  value_to: number | null;
  slope_per_nm: number | null;
}

export interface SpectralObservation {
  window_start: string;
  window_end: string;
  dataset_id?: string | null;
  unit: string;
  composite_method: string;
  image_count: number | null;
  coverage_percent: number | null;
  quality: string;
  samples: SpectralBandSample[];
  provenance?: Record<string, unknown> | null;
}

export interface SpectralProfile {
  band_set: string[];
  dataset_id?: string | null;
  unit: string;
  composite_method: string;
  window_start: string;
  window_end: string;
  step: string;
  observations: SpectralObservation[];
}

// Red-edge diagnostics contract (P2.2 foundation) — mirrors the
// backend red_edge representation. Diagnostics describe red-edge
// spectral behavior only (slopes in reflectance/nm, normalized
// differences as indices); statuses and directions are neutral
// availability/change states, never a cause attribution, cut-off,
// score, or probability. No chart is built in this phase; these
// types only carry the contract.

export interface RedEdgeDiagnostic {
  diagnostic_id: string;
  formula: string;
  input_bands: string[];
  wavelengths_nm: number[];
  value: number | null;
  unit: string;
  window_start: string;
  window_end: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  dataset_id?: string | null;
  status: string;
  limitations: string[];
  provenance?: Record<string, unknown> | null;
}

export interface RedEdgeObservationDiagnostics {
  window_start: string;
  window_end: string;
  dataset_id?: string | null;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  diagnostics: RedEdgeDiagnostic[];
  provenance?: Record<string, unknown> | null;
}

export interface RedEdgeChange {
  diagnostic_id: string;
  unit: string;
  window_start: string;
  window_end: string;
  previous_window_start?: string | null;
  previous_window_end?: string | null;
  value: number | null;
  previous_value: number | null;
  absolute_change: number | null;
  relative_change: number | null;
  days_elapsed: number | null;
  rate_per_day: number | null;
  direction: string;
}

export interface RedEdgeSeries {
  diagnostic_ids: string[];
  dataset_id?: string | null;
  window_start: string;
  window_end: string;
  step: string;
  monthly: RedEdgeObservationDiagnostics[];
  changes: RedEdgeChange[];
}

// Radar temporal profile contract (P2.3 foundation) — mirrors the
// backend radar_profile representation. Points are monthly
// Sentinel-1 observations in chronological order with explicit
// missing months (null values, no interpolation, no zero-fill);
// acquisition metadata restates the production composite contract,
// never a cause attribution, anomaly category, score, or
// probability. No chart is built in this phase; these types only
// carry the contract.

export interface RadarProfilePoint {
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  provenance?: Record<string, unknown> | null;
}

export interface RadarProfile {
  metric_key: string;
  dataset_id?: string | null;
  unit: string;
  polarizations: string[];
  mode: string;
  orbit_pass: string;
  scale_m: number | null;
  window_start: string;
  window_end: string;
  step: string;
  points: RadarProfilePoint[];
}

// Radar anomaly/change contract (P2.4 foundation) — mirrors the
// backend radar_anomaly representation, which only orchestrates the
// generic P1.2 baseline/anomaly and P1.3 change/persistence
// machinery over monthly radar profiles. Categories, directions,
// and states are neutral statistics, never a cause attribution,
// score, or probability. No chart is built in this phase; these
// types only carry the contract.

export interface RadarAnomalyAnalysis {
  metric_key: string;
  dataset_id?: string | null;
  unit: string;
  polarizations: string[];
  mode: string;
  orbit_pass: string;
  scale_m: number | null;
  window_start: string;
  window_end: string;
  step: string;
  observed: Record<string, unknown>;
  baseline?: ProfileBaseline | null;
  anomalies: AnomalyPoint[];
  changes: MonthChange[];
  persistence: DeviationPersistence;
  methods: Record<string, string>;
  limitations: string[];
}

// Multi-sensor concordance contract (P2.5 foundation) — mirrors
// the backend concordance representation, which only aligns
// existing optical, red-edge, and radar evidence by exact monthly
// window and reports deterministic categorical states, never a
// cause attribution, score, or probability. No chart is built in
// this phase; these types only carry the contract.

export interface ConcordanceEvidence {
  family: string;
  sensor: string;
  metric_id: string;
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  state_kind: string;
  state?: string | null;
  orientation: string;
  provenance?: Record<string, unknown> | null;
}

export interface FamilyEvidence {
  family: string;
  sensor: string;
  orientation: string;
  usable_count: number;
  directional_count: number;
  metric_ids: string[];
  items: ConcordanceEvidence[];
}

export interface ConcordanceMonth {
  window_start: string;
  window_end: string;
  state: string;
  rule_id: string;
  rule: string;
  reasons: string[];
  families: FamilyEvidence[];
}

export interface ConcordanceSummary {
  n_months: number;
  n_concordant: number;
  n_divergent: number;
  n_mixed: number;
  n_optical_only: number;
  n_radar_only: number;
  n_insufficient: number;
  concordant_months: string[];
  divergent_months: string[];
  longest_concordant_run: number;
  longest_concordant_run_start?: string | null;
  longest_concordant_run_end?: string | null;
  longest_divergent_run: number;
  longest_divergent_run_start?: string | null;
  longest_divergent_run_end?: string | null;
}

export interface ConcordanceSeries {
  window_start?: string | null;
  window_end?: string | null;
  rule_id: string;
  rule: string;
  months: ConcordanceMonth[];
  summary?: ConcordanceSummary | null;
  methods: Record<string, string>;
  limitations: string[];
}

// Evidence pattern engine contract (P3.1 foundation) — mirrors
// the backend pattern_engine representation, which only describes
// combinations of already-computed evidence with generic,
// sensor-agnostic pattern types and a small status vocabulary,
// never a cause attribution, score, or probability. No numeric
// confidence exists. No chart is built in this phase; these types
// only carry the contract.

export interface PatternEvidence {
  evidence_id: string;
  source_module: string;
  metric_id: string;
  sensor: string;
  family: string;
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  anomaly_state?: string | null;
  change_direction?: string | null;
  rapid?: string | null;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  provenance?: Record<string, unknown> | null;
  limitations: string[];
}

export interface EvidencePattern {
  pattern_id: string;
  pattern_type: string;
  window_start: string;
  window_end: string;
  status: string;
  contributing_evidence_ids: string[];
  contributing_metric_ids: string[];
  contributing_sensors: string[];
  source_states: Record<string, string>;
  rule_id: string;
  rule_version: string;
  rule_description: string;
  explanation: string;
  quality_by_evidence: Record<string, string>;
  coverage_by_evidence: Record<string, number | null>;
  provenance_by_evidence: Record<string, Record<string, unknown>>;
  limitations: string[];
}

export interface PatternRule {
  rule_id: string;
  rule_version: string;
  name: string;
  pattern_type: string;
  requires: string[];
  predicate: string;
  limitations: string[];
}

/** Bilingual display metadata for an analysis domain. */
export interface DomainMeta {
  key: string;
  label: string;
  labelFa: string;
  icon: string;
}

/** Bilingual display metadata for a synthesis pattern. */
export interface PatternMeta {
  label: string;
  labelFa: string;
  color: string;
}

export const DOMAIN_META: Record<string, DomainMeta> = {
  vegetation: { key: 'vegetation', label: 'Vegetation', labelFa: 'پوشش گیاهی', icon: '🌿' },
  water: { key: 'water', label: 'Water', labelFa: 'آب', icon: '💧' },
  thermal: { key: 'thermal', label: 'Thermal', labelFa: 'حرارتی', icon: '🌡️' },
  soil: { key: 'soil', label: 'Soil moisture', labelFa: 'رطوبت خاک', icon: '🟤' },
  climate: { key: 'climate', label: 'Climate', labelFa: 'اقلیم', icon: '☁️' },
  crop: { key: 'crop', label: 'Crop', labelFa: 'زراعی', icon: '🌾' },
  phenology: { key: 'phenology', label: 'Phenology', labelFa: 'فنولوژی', icon: '📅' },
  productivity: { key: 'productivity', label: 'Productivity', labelFa: 'بهره‌وری', icon: '📈' },
  historical: { key: 'historical', label: 'Historical', labelFa: 'تاریخی', icon: '🕓' },
  terrain: { key: 'terrain', label: 'Terrain', labelFa: 'توپوگرافی', icon: '⛰️' },
  landcover: { key: 'landcover', label: 'Land cover', labelFa: 'کاربری اراضی', icon: '🗺️' },
  stress: { key: 'stress', label: 'Stress', labelFa: 'تنش', icon: '⚠️' },
  irrigation: { key: 'irrigation', label: 'Irrigation', labelFa: 'آبیاری', icon: '🚿' },
  cross_domain: { key: 'cross_domain', label: 'Cross-domain', labelFa: 'میان‌حوزه‌ای', icon: '🔗' },
};

export const PATTERN_META: Record<string, PatternMeta> = {
  below_context: { label: 'Below context', labelFa: 'زیر بافت', color: '#c0392b' },
  near_context: { label: 'Near context', labelFa: 'نزدیک بافت', color: '#7f8c8d' },
  above_context: { label: 'Above context', labelFa: 'بالای بافت', color: '#27ae60' },
  mixed_evidence: { label: 'Mixed evidence', labelFa: 'شواهد مختلط', color: '#f39c12' },
  sufficient: { label: 'Sufficient', labelFa: 'کافی', color: '#2980b9' },
  limited: { label: 'Limited', labelFa: 'محدود', color: '#8e44ad' },
  insufficient: { label: 'Insufficient', labelFa: 'ناکافی', color: '#95a5a6' },
  coherent: { label: 'Coherent', labelFa: 'همخوان', color: '#16a085' },
};

// Thermal visualization contract (P4.2-P4.4 layers) — mirrors the
// backend thermal schema section, which only describes
// already-computed monthly observations, baselines, anomalies,
// changes, and concordance relationships. MODIS LST
// (land-surface / skin temperature) and ERA5-Land 2 m air
// temperature keep separate interfaces and separate fields —
// they are never collapsed into one generic temperature, and
// neither is presented as canopy temperature. No chart is built
// in this phase; these types only carry the contract.

export interface ThermalProfilePoint {
  window_start: string;
  window_end: string;
  value: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  source_dataset_id: string;
  source_band: string;
  physical_quantity: string;
  aggregation_method: string;
  temporal_resolution: string;
  provenance?: Record<string, unknown> | null;
}

export interface ThermalSourceProfile {
  profile_kind: string;
  metric_key: string;
  dataset_id?: string | null;
  fallback_dataset_id?: string | null;
  band: string;
  unit: string;
  physical_quantity: string;
  physical_quantity_label: string;
  measurement_basis: string;
  temporal_resolution: string;
  aggregation_method: string;
  window_start: string;
  window_end: string;
  step: string;
  limitations: string[];
  points: ThermalProfilePoint[];
}

export interface ThermalHarmonizedPeriod {
  window_start: string;
  window_end: string;
  lst_celsius: number | null;
  lst?: ThermalProfilePoint | null;
  air_temperature_celsius: number | null;
  air?: ThermalProfilePoint | null;
  harmonization_method: string;
  contributing_lst_windows: string[][];
  contributing_air_windows: string[][];
}

export interface ThermalHarmonizedProfile {
  window_start: string;
  window_end: string;
  step: string;
  harmonization: string;
  harmonization_method: string;
  limitations: string[];
  periods: ThermalHarmonizedPeriod[];
}

export interface ThermalAnomalyPoint extends AnomalyPoint {
  derivation: string;
  profile_kind: string;
  physical_quantity: string;
  thermal_provenance?: Record<string, unknown> | null;
}

export interface ThermalChange extends MonthChange {
  derivation: string;
  profile_kind: string;
  physical_quantity: string;
  thermal_provenance?: Record<string, unknown> | null;
}

export interface ThermalMetricAnalysis {
  profile_kind: string;
  physical_quantity: string;
  physical_quantity_label: string;
  metric_key: string;
  dataset_id?: string | null;
  band: string;
  measurement_basis: string;
  unit: string;
  window_start: string;
  window_end: string;
  step: string;
  observed: Record<string, unknown>;
  baseline?: ProfileBaseline | null;
  baseline_refusal_reason?: string | null;
  anomalies: ThermalAnomalyPoint[];
  changes: ThermalChange[];
  persistence: DeviationPersistence;
  methods: Record<string, string>;
  limitations: string[];
}

export interface ThermalPairAnalysis {
  lst: ThermalMetricAnalysis;
  air: ThermalMetricAnalysis;
  alignment: string;
  alignment_method: string;
  limitations: string[];
}

export interface ThermalSideEvidence {
  window_start: string;
  window_end: string;
  profile_kind: string;
  physical_quantity: string;
  source_role: string;
  metric_id: string;
  dataset_id?: string | null;
  band: string;
  orientation: string;
  orientation_source: string;
  source_state?: string | null;
  source_state_kind: string;
  value: number | null;
  unit: string;
  quality: string;
  coverage_percent: number | null;
  image_count: number | null;
  provenance?: Record<string, unknown> | null;
}

export interface ThermalConcordanceMonth {
  window_start: string;
  window_end: string;
  rule_id: string;
  rule: string;
  lst?: ThermalSideEvidence | null;
  air?: ThermalSideEvidence | null;
  p25_state?: string | null;
  p25_rule_id?: string | null;
  optical_orientation?: string | null;
  red_edge_orientation?: string | null;
  radar_orientation?: string | null;
  lst_relationship: string;
  air_relationship: string;
  lst_era5_agreement?: string | null;
  observational_sensor_count: number;
  meteorological_context_present: boolean;
  explanations: string[];
}

export interface ThermalConcordanceAnalysis {
  window_start?: string | null;
  window_end?: string | null;
  rule_id: string;
  rule: string;
  months: ThermalConcordanceMonth[];
  summary: Record<string, number>;
  methods: Record<string, string>;
  limitations: string[];
}

// Analysis temporal section (P5.3 integration) — mirrors the
// backend TemporalSectionModel, which only transports
// already-computed P1-P4 monthly intelligence. Records are keyed
// by exact metric key; months keep exact windows; nulls stay
// null; LST and ERA5 air temperature stay separate.

export interface TemporalSectionPayload {
  window_start: string;
  window_end: string;
  profiles: Record<string, TemporalProfile>;
  anomalies: Record<string, AnomalyProfile>;
  changes: Record<string, ChangeProfile>;
  radar_profiles: Record<string, RadarProfile>;
  radar_analyses: Record<string, RadarAnomalyAnalysis>;
  joint?: JointAnalysis | null;
  concordance?: ConcordanceSeries | null;
  thermal_profiles: Record<string, ThermalSourceProfile>;
  thermal_analyses: Record<string, ThermalMetricAnalysis>;
  thermal_harmonized?: ThermalHarmonizedProfile | null;
  thermal_pair?: ThermalPairAnalysis | null;
  thermal_concordance?: ThermalConcordanceAnalysis | null;
  limitations: string[];
}

/** Additive P5.3-S spatial intelligence; null when no metric is spatially supported or cached response predates spatial contract. */

export interface SpatialSectionPayload {
  window_start: string;
  window_end: string;
  grid_rows: number;
  grid_cols: number;
  bbox: number[];
  cells: SpatialCellPayload[];
  observations: CellObservationPayload[];
  summaries: Record<string, SpatialSummaryPayload>;
  concordance: CellConcordancePayload[];
  persistence: CellPersistencePayload[];
  limitations: string[];
}

/** One deterministic grid cell with WGS84 lon/lat bounds. */

export interface SpatialCellPayload {
  cell_id: string;
  row: number;
  col: number;
  west: number;
  south: number;
  east: number;
  north: number;
  geometry: GeoJSON.Polygon;
}

/** One cell's observation for one metric and window. */

export interface CellObservationPayload {
  cell_id: string;
  metric_key: string;
  window_start: string;
  window_end: string;
  value?: number | null;
  unit: string;
  z_score?: number | null;
  category?: string | null;
  quality: string;
  coverage_percent?: number | null;
  image_count?: number | null;
}

/** Area-level aggregation over one metric's cell observations. */

export interface SpatialSummaryPayload {
  metric_key: string;
  window_start: string;
  window_end: string;
  n_cells: number;
  n_usable: number;
  n_missing: number;
  anomalous_count: number;
  anomalous_fraction?: number | null;
  min_coverage_percent?: number | null;
  mean_coverage_percent?: number | null;
  quality_counts: Record<string, number>;
  state: string;
  method: string;
}

/** Multi-metric agreement for one cell and window. */

export interface CellConcordancePayload {
  cell_id: string;
  window_start: string;
  window_end: string;
  metrics: string[];
  anomalous_metrics: string[];
  state: string;
}

/** Per-cell deviation runs across consecutive valid periods. */

export interface CellPersistencePayload {
  cell_id: string;
  longest_run_below: number;
  longest_run_above: number;
  n_anomalous: number;
  n_observed: number;
  n_missing: number;
  state: string;
}

// Cross-pattern validation contract (P3.3 validation layer) — mirrors
// backend CrossPatternValidationModel, which only validates
// already-established P3.1/P3.2 pattern outputs for one exact window
// with a descriptive status vocabulary (CONSISTENT, MIXED_EVIDENCE,
// INSUFFICIENT_EVIDENCE). Pattern counts are descriptive audit counts,
// never strength readings. No numeric grade exists. The /analysis
// response does not currently carry this section; this interface only
// carries the contract so a future additive field can render verbatim.

export interface CrossPatternValidation {
  validation_id: string;
  window_start: string;
  window_end: string;
  status: string;
  contributing_pattern_ids: string[];
  compatible_pattern_ids: string[];
  conflicting_pattern_ids: string[];
  contributing_metric_ids: string[];
  contributing_sensors: string[];
  contributing_families: string[];
  pattern_count: number;
  independent_sensor_count: number;
  overlapping_evidence: boolean;
  overlapping_metric_ids: string[];
  overlapping_evidence_ids: string[];
  source_pattern_types: Record<string, string>;
  source_pattern_states: Record<string, string>;
  rule_id: string;
  rule_version: string;
  rule_description: string;
  explanation: string;
  overlap_explanation: string;
  provenance: Record<string, unknown>;
  limitations: string[];
}

export interface ValidationRule {
  rule_id: string;
  rule_version: string;
  name: string;
  pattern_type: string;
  requires: string[];
  predicate: string;
  limitations: string[];
}

// Ground-truth validation contract (P6.1–P6.3 foundation) — mirrors the
// backend validation_engine representation and the P6.3
// ValidationSectionModel. One analysis output set beside one
// independently supplied reference observation. Every source value
// stays traceable; relationships and states stay descriptive. No
// numeric reading exists anywhere in this contract.

export interface RejectedRecord {
  index: number;
  observation_id: string;
  reasons: string[];
}

export interface DuplicateRecord {
  observation_id: string;
  kept_index: number;
  dropped_indices: number[];
  reason: string;
}

export interface ValidationResult {
  validation_id: string;
  target_id: string;
  observation_id: string;
  metric_key: string;
  domain: string;
  analysis_id?: string | null;
  analysis_window_start: string;
  analysis_window_end: string;
  analysis_cell_id?: string | null;
  analysis_value: number | null;
  analysis_unit: string;
  analysis_state?: string | null;
  reference_variable: string;
  reference_value: number | null;
  reference_unit: string;
  reference_state?: string | null;
  reference_source: string;
  reference_method: string;
  reference_time?: string | null;
  temporal_relationship: string;
  spatial_relationship: string;
  metric_relationship: string;
  states_agree: boolean | null;
  values_comparable: boolean | null;
  difference?: number | null;
  relative_difference_percent?: number | null;
  validation_status_code?: string | null;
  sample_count?: number;
  status: string;
  linkage_reason: string;
  contract_version: string;
  engine_version: string;
  provenance: Record<string, unknown>;
  limitations: string[];
}

export interface ValidationSection {
  results: ValidationResult[];
  rejected_references: RejectedRecord[];
  duplicates: DuplicateRecord[];
  limitations: string[];
  contract_version: string;
  engine_version: string;
}

// ---------------------------------------------------------------------------
// Spatial Heatmap Layer (Phase P-AGRI-3 & P-AGRI-4)
// ---------------------------------------------------------------------------

export type SpatialMetricType = 'ndvi' | 'lst_day' | 'soil_moisture' | 'sar_vh' | 'ndmi' | 'ndre' | 'msi' | 'soil_soc' | 'soil_ph' | 'soil_clay' | 'soil_sand' | 'soil_cec' | 'soil_nitrogen' | 'true_color';

export type SpatialConceptType = 'vegetation_condition' | 'thermal_stress' | 'surface_dryness' | 'soil_organic_carbon' | 'soil_acidity_ph' | 'soil_texture_clay';

export interface SpatialLayerRequest {
  metric?: SpatialMetricType;
  concept?: SpatialConceptType;
  geometry: GeoJSON.Geometry | AgricultureGeometry;
  start_date: string;
  end_date: string;
  cloud_max_percent?: number;
  support_radius_m?: number;
}

export interface SpatialLayerResponse {
  metric: string;
  display_name: string;
  source_dataset: string;
  tile_url_template: string | null;
  proxied_tile_url_template?: string | null;
  min_val: number;
  max_val: number;
  unit: string;
  palette: string[];
  native_resolution_m: number;
  spatial_resolution: string;
  geometry_type: string;
  support_radius_m?: number | null;
  support_area_sq_m?: number | null;
  start_date: string;
  end_date: string;
  status: 'available' | 'unavailable';
  unavailable_reason?: string | null;
  limitations: string[];
  bounds?: [number, number, number, number] | null;
  // Phase P-AGRI-4 Additive Agricultural Interpretation fields
  concept?: string | null;
  concept_name?: string | null;
  concept_name_fa?: string | null;
  interpretation?: string | null;
  interpretation_fa?: string | null;
  qualitative_legend?: string[] | null;
  scientific_caution?: string | null;
  scientific_caution_fa?: string | null;
}

export type LandUseType = 'field_crop' | 'orchard' | 'pistachio' | 'other';

// ---------------------------------------------------------------------------
// 10-Year Same-Period Historical Comparison (Phase P-AGRI-HIST-10Y)
// ---------------------------------------------------------------------------

export type HistoricalYearStatus = 'current' | 'available' | 'partial' | 'unavailable';

export interface HistoricalYearRecord {
  year: number;
  start_date: string;
  end_date: string;
  status: HistoricalYearStatus;
  scene_count: number;
  metrics: Record<string, number | null>;
}

export type HistoricalTrendDirection =
  | 'improving'
  | 'declining'
  | 'stable'
  | 'variable'
  | 'increasing'
  | 'decreasing'
  | 'insufficient_evidence';

export type HistoricalSufficiency = 'sufficient' | 'partial' | 'insufficient';

export interface HistoricalMetricTrend {
  metric_key: string;
  display_name: string;
  display_name_fa: string;
  unit: string;
  current_value: number | null;
  baseline_median: number | null;
  baseline_mean: number | null;
  delta_from_baseline: number | null;
  trend_direction: HistoricalTrendDirection;
  trend_slope_per_year: number | null;
  trend_label_fa: string;
  trend_label_en: string;
  sufficiency: HistoricalSufficiency;
  scientific_summary_fa: string;
  scientific_summary_en: string;
}

export interface HistoricalComparisonResponse {
  requested_period: {
    start_date: string;
    end_date: string;
  };
  same_period_label_fa: string;
  same_period_label_en: string;
  domain?: string | null;
  available_metrics: string[];
  years: HistoricalYearRecord[];
  trends: Record<string, HistoricalMetricTrend>;
  limitations: string[];
}

export interface HistoricalComparisonRequest {
  geometry: GeoJSON.Geometry | AgricultureGeometry;
  start_date: string;
  end_date: string;
  domain?: string;
  metric_keys?: string[];
  cloud_max_percent?: number;
}

// ---------------------------------------------------------------------------
// Soil Intelligence (Phase P-AGRI-SOIL)
// ---------------------------------------------------------------------------

export interface SoilMoistureLayer {
  band: string;
  depth_en: string;
  depth_fa: string;
  depth_top_cm: number;
  depth_bottom_cm: number;
  value: number | null;
  unit: string;
  status: string;
  source: string;
  dataset: string;
  scale_m: number;
  modelled: boolean;
}

export interface SoilMoistureReading {
  value: number | null;
  unit: string;
  depth: string;
  depth_fa: string;
  source: string;
  dataset: string;
  scale_m: number;
  status: string;
  measurement_basis: string;
  scientific_status?: string;
  scientific_status_fa?: string | null;
  validation_status?: string;
  validation_note_fa?: string | null;
  data_status?: string;
}

export interface SoilMoistureResponse {
  surface?: SoilMoistureReading | null;
  rootzone?: SoilMoistureReading | null;
  multilayer_era5: SoilMoistureLayer[];
  coarse_warning: boolean;
  spatial_resolution_m: number;
  limitations: string[];
}

export interface SoilPropertyDepth {
  depth_code: string;
  depth_en: string;
  depth_fa: string;
  depth_top_cm: number;
  depth_bottom_cm: number;
  thickness_cm: number;
  value: number | null;
  unit: string;
  status: string;
}

export interface SoilPropertyRecord {
  property_key: string;
  name_fa: string;
  name_en: string;
  unit: string;
  root_zone_value: number | null;
  root_zone_depth: string;
  root_zone_depth_fa: string;
  depth_profiles: SoilPropertyDepth[];
  source: string;
  dataset_id: string;
  scale_m: number;
  reference_period: string;
  reference_period_fa: string;
  status: string;
  is_modelled_baseline: boolean;
  reason?: string | null;
}

export interface SoilWaterRetention {
  field_capacity_33kpa: number | null;
  wilting_point_1500kpa: number | null;
  available_water_capacity: number | null;
  unit: string;
  depth: string;
  depth_fa: string;
  source: string;
  dataset_id: string;
  scale_m: number;
  status: string;
}

export interface SoilTextureClassification {
  class_en: string;
  class_fa: string;
  sand_percent?: number | null;
  silt_percent?: number | null;
  clay_percent?: number | null;
  method: string;
  status: string;
}

export interface UnavailableNutrient {
  key: string;
  name_fa: string;
  name_en: string;
  status: string;
  scientific_status?: string;
  validation_status?: string;
  reason: string;
  message_fa: string;
  message_en: string;
  satellite_estimable: boolean;
  next_action?: string;
  next_action_fa?: string;
}

export interface SoilMetricAvailabilityItem {
  metric_key: string;
  label_en: string;
  label_fa: string;
  value?: number | null;
  unit?: string | null;
  source?: string | null;
  dataset_id?: string | null;
  variable?: string | null;
  band?: string | null;
  status: string;
  data_status?: string;
  scientific_status?: string;
  scientific_status_fa?: string | null;
  validation_status: string;
  validation_note_fa?: string | null;
  availability_message_fa?: string | null;
  depth?: string | null;
  depth_cm?: number[] | null;
  spatial_resolution?: string | null;
  spatial_resolution_m?: number | null;
  temporal_resolution?: string | null;
  temporal_period?: string | null;
  is_ground_truth?: boolean;
  requires_lab_validation?: boolean;
  reason?: string | null;
  reason_fa?: string | null;
  limitations?: string[];
  next_action?: string | null;
  next_action_fa?: string | null;
}

export interface SoilObservation {
  observation_id: string;
  latitude: number;
  longitude: number;
  sample_date: string;
  depth_top_cm: number;
  depth_bottom_cm: number;
  pH?: number | null;
  EC?: number | null;
  total_n?: number | null;
  available_p?: number | null;
  exchangeable_k?: number | null;
  nitrate?: number | null;
  laboratory?: string | null;
  method?: string | null;
  quality?: string | null;
  notes?: string | null;
  source_type: string;
  is_derived: boolean;
}

export interface SoilLaboratoryFramework {
  is_lab_calibrated: boolean;
  ml_nutrient_mapping_status: string;
  message_fa: string;
  message_en: string;
  supported_sample_fields: string[];
}

export interface SoilIntelligenceResponse {
  start_date: string;
  end_date: string;
  moisture: SoilMoistureResponse;
  properties: {
    soc?: SoilPropertyRecord;
    phh2o?: SoilPropertyRecord;
    clay?: SoilPropertyRecord;
    sand?: SoilPropertyRecord;
    silt?: SoilPropertyRecord;
    cec?: SoilPropertyRecord;
    nitrogen?: SoilPropertyRecord;
    water_retention?: SoilWaterRetention;
    texture_classification?: SoilTextureClassification;
    [key: string]: any;
  };
  unavailable_nutrients: UnavailableNutrient[];
  data_availability_matrix?: SoilMetricAvailabilityItem[];
  laboratory_framework: SoilLaboratoryFramework;
  limitations: string[];
}

export interface SoilIntelligenceRequest {
  geometry: GeoJSON.Geometry | AgricultureGeometry;
  start_date: string;
  end_date: string;
}

// ---------------------------------------------------------------------------
// Ground Truth & Field Observations (Phase P1)
// ---------------------------------------------------------------------------

export interface GroundTruthObservation {
  observation_id: string;
  variable: string;
  value?: number | null;
  unit?: string;
  state?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  observed_on?: string | null;
  window_start?: string | null;
  window_end?: string | null;
  source: string;
  method: string;
  quality?: string;
  status?: string;
  metric_key?: string | null;
  domain?: string | null;
  cell_id?: string | null;
  crop_type?: string | null;
  growth_stage?: string | null;
  condition_summary?: string | null;
  observed_stress?: string | null;
  pest_observation?: string | null;
  disease_observation?: string | null;
  irrigation_status?: string | null;
  soil_observation?: string | null;
  laboratory_result?: string | null;
  yield_observation?: number | null;
  notes?: string | null;
  is_derived?: boolean;
  is_test_fixture?: boolean;
  contract_version?: string;
  provenance?: Record<string, unknown>;
  limitations?: string[];
}

// ---------------------------------------------------------------------------
// Pest / Disease Inspection & Risk Screening (Phase P1)
// ---------------------------------------------------------------------------

export type PestDiseaseRiskLevel = 'none' | 'low' | 'moderate' | 'elevated' | 'high' | 'insufficient';

export type PestDiseasePatternType =
  | 'no_significant_anomaly_detected'
  | 'vegetation_stress_pattern'
  | 'moisture_stress_pattern'
  | 'persistent_vegetation_decline'
  | 'possible_biotic_stress_compatible_pattern'
  | 'possible_abiotic_stress_compatible_pattern'
  | 'mixed_conflicting_evidence'
  | 'insufficient_evidence';

export interface SensorEvidenceDetail {
  sensor_family: 'optical' | 'radar' | 'thermal' | 'ground_truth' | string;
  metric_key: string;
  display_name_fa: string;
  value?: number | null;
  baseline_value?: number | null;
  anomaly_z_score?: number | null;
  status: string;
  indication: string;
  weight_in_assessment: number;
  notes_fa: string;
}

export interface BioticAbioticAssessment {
  compatible_stress_type: 'biotic' | 'abiotic' | 'mixed' | 'indeterminate' | 'none' | string;
  biotic_compatibility_score: number;
  abiotic_compatibility_score: number;
  spatial_uniformity: string;
  weather_correlation: string;
  canopy_structural_decay: string;
  reasoning_fa: string;
  reasoning_en: string;
}

export interface PestDiseaseInspectionResponse {
  request_id?: string | null;
  start_date: string;
  end_date: string;
  overall_risk_level: PestDiseaseRiskLevel;
  risk_level_fa: string;
  pattern_type: PestDiseasePatternType;
  pattern_title_fa: string;
  pattern_summary_fa: string;
  evidence_hierarchy_level: number;
  evidence_hierarchy_title_fa: string;
  evidence_hierarchy_description_fa: string;
  optical_evidence: SensorEvidenceDetail[];
  radar_evidence: SensorEvidenceDetail[];
  thermal_evidence: SensorEvidenceDetail[];
  biotic_abiotic_assessment: BioticAbioticAssessment;
  ground_truth_corroboration: Record<string, any>;
  temporal_persistence: Record<string, any>;
  scientific_disclaimer_fa: string;
  scientific_disclaimer_en: string;
  recommended_field_actions_fa: string[];
  limitations: string[];
}

export interface PestDiseaseInspectionRequest {
  geometry: GeoJSON.Geometry | AgricultureGeometry;
  start_date: string;
  end_date: string;
  ground_truth?: GroundTruthObservation[] | any[];
  cloud_max_percent?: number;
}


