import { apiGet, apiPost } from './client';
import type {
  AgricultureAnalysisRequest,
  AgriculturalAnalysisResponse,
  AgricultureHealthResponse,
  SynthesisOnlyRequest,
} from '../types';

export const agricultureApi = {
  /** Health check for the agricultural subsystem */
  health: () =>
    apiGet<AgricultureHealthResponse>('/agriculture/health'),

  /** Run full agricultural analysis */
  analyze: (data: AgricultureAnalysisRequest) =>
    apiPost<AgriculturalAnalysisResponse>('/agriculture/analysis', data),

  /** Run synthesis from pre-built evidence (for development/testing) */
  synthesisOnly: (data: SynthesisOnlyRequest) =>
    apiPost<AgriculturalAnalysisResponse>('/agriculture/analysis/synthesis-only', data),
};
