import { apiGet, apiPost, apiDelete } from './client';
import type {
  AgricultureAnalysisRequest,
  AgriculturalAnalysisResponse,
  AgricultureHealthResponse,
  SpatialLayerRequest,
  SpatialLayerResponse,
  SynthesisOnlyRequest,
  HistoricalComparisonRequest,
  HistoricalComparisonResponse,
  SoilIntelligenceRequest,
  SoilIntelligenceResponse,
  PestDiseaseInspectionRequest,
  PestDiseaseInspectionResponse,
  AgricultureHistoryListResponse,
} from '../types';

export const agricultureApi = {
  /** Health check for the agricultural subsystem */
  health: () =>
    apiGet<AgricultureHealthResponse>('/agriculture/health'),

  /** Run full agricultural analysis */
  analyze: (data: AgricultureAnalysisRequest) =>
    apiPost<AgriculturalAnalysisResponse>('/agriculture/analysis', data),

  /** Fetch paginated list of saved agricultural analysis history runs (Phase P0-HISTORY) */
  listHistory: (skip = 0, limit = 20, locationId?: string) => {
    const locParam = locationId ? `&location_id=${locationId}` : '';
    return apiGet<AgricultureHistoryListResponse>(`/agriculture/history?skip=${skip}&limit=${limit}${locParam}`);
  },

  /** Fetch full stored agricultural analysis report by persistent ID with ZERO GEE execution */
  getHistoryItem: (id: string) =>
    apiGet<AgriculturalAnalysisResponse>(`/agriculture/history/${id}`),

  /** Manually delete a single agricultural analysis run from persistent history */
  deleteHistoryItem: (id: string) =>
    apiDelete(`/agriculture/history/${id}`),

  /** Fetch real Earth Engine spatial raster tile layer (Phase P-AGRI-3) */
  getSpatialLayer: (data: SpatialLayerRequest) =>
    apiPost<SpatialLayerResponse>('/agriculture/spatial-layer', data),

  /** Fetch 10-year same-period historical comparison (Phase P-AGRI-HIST-10Y) */
  getHistoricalComparison: (data: HistoricalComparisonRequest) =>
    apiPost<HistoricalComparisonResponse>('/agriculture/historical-comparison', data),

  /** Fetch real GEE soil moisture and SoilGrids 2.0 properties (Phase P-AGRI-SOIL) */
  getSoilIntelligence: (data: SoilIntelligenceRequest) =>
    apiPost<SoilIntelligenceResponse>('/agriculture/soil-intelligence', data),

  /** Run multi-sensor pest & disease risk screening (Phase P1) */
  inspectPestDisease: (data: PestDiseaseInspectionRequest) =>
    apiPost<PestDiseaseInspectionResponse>('/agriculture/pest-disease-inspection', data),

  /** Run synthesis from pre-built evidence (for development/testing) */
  synthesisOnly: (data: SynthesisOnlyRequest) =>
    apiPost<AgriculturalAnalysisResponse>('/agriculture/analysis/synthesis-only', data),
};



