import { apiGet, apiPost, apiPut, apiPatch, apiDelete } from './client';
import type {
  FrostAssessRequest,
  FrostAssessmentResponse,
  FrostOrchard,
  FrostOrchardCreate,
  FrostAlertRule,
  FrostAlertRuleCreate,
  EvaluateAlertsRequest,
  EvaluateAlertsResponse,
  OrchardSummaryItem,
  OrchardRiskReport,
} from '../types';

export const frostApi = {
  /** Run frost risk assessment */
  assessFrost: (data: FrostAssessRequest) =>
    apiPost<FrostAssessmentResponse>('/agriculture/frost/assess', data),

  /** List registered orchards */
  listFrostOrchards: (includeArchived = false) =>
    apiGet<FrostOrchard[]>(`/agriculture/frost/orchards${includeArchived ? '?include_archived=true' : ''}`),

  /** Register an orchard */
  createFrostOrchard: (data: FrostOrchardCreate) =>
    apiPost<FrostOrchard>('/agriculture/frost/orchards', data),

  /** Add an alert rule for an orchard */
  createFrostAlertRule: (orchardId: string, data: FrostAlertRuleCreate) =>
    apiPost<FrostAlertRule>(`/agriculture/frost/orchards/${orchardId}/alert-rules`, data),

  /** Evaluate frost alert rules (dry_run or dispatch) */
  evaluateFrostAlerts: (data: EvaluateAlertsRequest) =>
    apiPost<EvaluateAlertsResponse>('/agriculture/frost/evaluate-alerts', data),

  /** Batch frost risk summary for all registered orchards sorted by risk (R5/R6) */
  getFrostOrchardsRiskSummary: (horizonH = 240, thresholdSet = 'published_v1', includeArchived = false) =>
    apiGet<OrchardSummaryItem[]>(
      `/agriculture/frost/orchards/risk-summary?horizon_h=${horizonH}&threshold_set=${thresholdSet}&include_archived=${includeArchived}`
    ),

  /** Detailed per-night weighted factor risk assessment for an orchard (R5/R6) */
  getFrostOrchardRisk: (orchardId: string, horizonH = 240, thresholdSet = 'published_v1') =>
    apiGet<OrchardRiskReport>(
      `/agriculture/frost/orchards/${orchardId}/risk?horizon_h=${horizonH}&threshold_set=${thresholdSet}`
    ),

  /** Update orchard details including current phenological stage (R4/R5) */
  updateFrostOrchard: (orchardId: string, data: { name?: string; crop?: string; current_stage?: string; elevation?: number }) =>
    apiPut<FrostOrchard>(`/agriculture/frost/orchards/${orchardId}`, data),

  /** Patch only orchard phenological stage (S8) */
  patchFrostOrchardStage: (orchardId: string, current_stage: string) =>
    apiPatch<FrostOrchard>(`/agriculture/frost/orchards/${orchardId}/stage`, { current_stage }),

  /** Soft delete (archive) an orchard parcel (R5, S5, T7) */
  deleteFrostOrchard: (orchardId: string) =>
    apiDelete(`/agriculture/frost/orchards/${orchardId}`),

  /** Restore an archived orchard parcel (S5, T7) */
  restoreFrostOrchard: (orchardId: string) =>
    apiPost<{ status: string; orchard_id: string; name: string }>(`/agriculture/frost/orchards/${orchardId}/restore`, {}),
};
