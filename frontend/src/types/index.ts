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
