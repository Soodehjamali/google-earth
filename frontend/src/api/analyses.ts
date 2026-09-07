import { apiGet, apiPost } from './client';
import type {
  Analysis,
  AnalysisCreate,
  NDVIResult,
  TimeSeriesResponse,
  MapVisualization,
  MapLegend,
} from '../types';

export const analysesApi = {
  list: (skip = 0, limit = 20) =>
    apiGet<Analysis[]>(`/analyses?skip=${skip}&limit=${limit}`),

  get: (id: string) =>
    apiGet<Analysis>(`/analyses/${id}`),

  create: (data: AnalysisCreate) =>
    apiPost<Analysis>('/analyses', data),

  getSummary: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/summary`),

  getVegetation: (id: string) =>
    apiGet<NDVIResult>(`/analyses/${id}/vegetation`),

  getClimate: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/climate`),

  getSoil: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/soil`),

  getWater: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/water`),

  getLandcover: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/landcover`),

  getStress: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/stress`),

  getRisk: (id: string) =>
    apiGet<Record<string, unknown>>(`/analyses/${id}/risk`),

  getTimeSeries: (id: string, variable?: string) => {
    const params = variable ? `?variable=${variable}` : '';
    return apiGet<TimeSeriesResponse>(`/analyses/${id}/timeseries${params}`);
  },

  getMaps: (id: string) =>
    apiGet<MapVisualization>(`/analyses/${id}/maps`),

  getMapLegend: (analysisId: string, layerId: string) =>
    apiGet<MapLegend>(`/analyses/${analysisId}/maps/${layerId}/legend`),
};

// NDVI quick endpoint
export const vegetationApi = {
  analyzeNdvi: (data: {
    latitude: number;
    longitude: number;
    start_date: string;
    end_date: string;
    cloud_max_percent?: number;
  }) => apiPost<NDVIResult>('/vegetation/ndvi', data),

  getIndices: () =>
    apiGet<Record<string, unknown>>('/vegetation/indices'),
};
