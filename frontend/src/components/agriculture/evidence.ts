/**
 * Evidence visualization mapping (P5.5 presentation layer).
 *
 * Pure read-only helpers over the Agriculture /analysis response.
 * Backend records become display rows with fields copied verbatim;
 * nothing here derives new values, fills gaps, or links unrelated
 * objects. Ordering follows response insertion order. All states,
 * keys, units, windows, and counts travel through intact. Nulls stay
 * null. Absent sections yield empty results, never invented rows.
 */
import type {
  CellConcordancePayload,
  CellObservationPayload,
  ConcordanceMonth,
  ConcordanceSeries,
  ConcordanceSummary,
  CrossPatternValidation,
  DomainSummaryResponse,
  EvidenceBundleResponse,
  EvidenceItemResponse,
  EvidencePattern,
  JointAnalysis,
  RadarAnomalyAnalysis,
  SpatialSectionPayload,
  SynthesisStatementResponse,
  TemporalSectionPayload,
  ThermalConcordanceMonth,
} from '../../types/index.ts';
import { asArray, asRecord, formatEvidenceValue, isFiniteNumber } from './parse.ts';

export interface OrderedBundle {
  domain: string;
  bundle: EvidenceBundleResponse;
}

export interface SynthesisLink {
  rule_id: string;
  domain: string;
  pattern: string;
}

/**
 * Bundles in response insertion order. No reordering by any notion
 * of importance. Entries with unusable shapes are skipped.
 */
export function orderedBundleEntries(
  bundles: Record<string, EvidenceBundleResponse> | null | undefined,
): OrderedBundle[] {
  if (!bundles || typeof bundles !== 'object') return [];
  const out: OrderedBundle[] = [];
  for (const [domain, bundle] of Object.entries(bundles)) {
    const record = asRecord(bundle);
    if (!record) continue;
    if (typeof (bundle as EvidenceBundleResponse).name !== 'string') continue;
    out.push({ domain, bundle: bundle as EvidenceBundleResponse });
  }
  return out;
}

/** Items of one bundle in backend order; unshaped rows omitted. */
export function bundleItems(
  bundle: EvidenceBundleResponse | null | undefined,
): EvidenceItemResponse[] {
  if (!bundle || typeof bundle !== 'object') return [];
  const out: EvidenceItemResponse[] = [];
  for (const entry of asArray((bundle as { items?: unknown }).items)) {
    const record = asRecord(entry);
    if (!record || typeof record.metric_key !== 'string') continue;
    out.push(entry as EvidenceItemResponse);
  }
  return out;
}

/** Verbatim sufficiency level, or null when the backend sent none. */
export function bundleSufficiencyLevel(
  bundle: EvidenceBundleResponse | null | undefined,
): string | null {
  const record = asRecord(bundle);
  const suff = record ? asRecord(record.sufficiency) : null;
  const level = suff ? suff.level : null;
  return typeof level === 'string' && level.length > 0 ? level : null;
}

/** Verbatim source dataset list, strings only. */
export function bundleSourceDatasets(
  bundle: EvidenceBundleResponse | null | undefined,
): string[] {
  if (!bundle || typeof bundle !== 'object') return [];
  return asArray((bundle as { source_datasets?: unknown }).source_datasets).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

/** Verbatim unavailable keys, strings only. */
export function bundleUnavailableKeys(
  bundle: EvidenceBundleResponse | null | undefined,
): string[] {
  if (!bundle || typeof bundle !== 'object') return [];
  return asArray((bundle as { unavailable?: unknown }).unavailable).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

/** Verbatim limitation strings, strings only. */
export function bundleLimitations(
  bundle: EvidenceBundleResponse | null | undefined,
): string[] {
  if (!bundle || typeof bundle !== 'object') return [];
  return asArray((bundle as { limitations?: unknown }).limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

/**
 * Exact observation window for one evidence item, verbatim.
 * Returns null when the backend sent no window.
 */
export function evidenceWindowText(
  item: EvidenceItemResponse | null | undefined,
): string | null {
  if (!item || typeof item !== 'object') return null;
  const start = (item as { temporal_start?: unknown }).temporal_start;
  const end = (item as { temporal_end?: unknown }).temporal_end;
  const hasStart = typeof start === 'string' && start.length > 0;
  const hasEnd = typeof end === 'string' && end.length > 0;
  if (!hasStart && !hasEnd) return null;
  if (hasStart && hasEnd) return `${start} → ${end}`;
  return (hasStart ? start : end) as string;
}

/** Display text for an observed value; non-finite values stay marked. */
export function evidenceDisplayValue(
  item: EvidenceItemResponse | null | undefined,
): string {
  if (!item || typeof item !== 'object') return '—';
  return formatEvidenceValue((item as { value?: unknown }).value);
}

/** True only for finite observed values on usable items. */
export function hasObservedValue(
  item: EvidenceItemResponse | null | undefined,
): boolean {
  if (!item || typeof item !== 'object') return false;
  const record = item as { value?: unknown; status?: unknown };
  if (record.status === 'unavailable') return false;
  return isFiniteNumber(record.value);
}

/**
 * Statements that reference one metric key by exact match against
 * their backend evidence_keys. Domain summaries plus cross-domain
 * statements are both searched. No substring matching, no inference.
 */
export function synthesisLinksFor(
  metricKey: string,
  domainSummaries: Record<string, DomainSummaryResponse> | null | undefined,
  crossDomainStatements: SynthesisStatementResponse[] | null | undefined,
): SynthesisLink[] {
  if (typeof metricKey !== 'string' || metricKey.length === 0) return [];
  const out: SynthesisLink[] = [];
  const seen = new Set<string>();
  const consider = (stmt: unknown) => {
    const record = asRecord(stmt);
    if (!record) return;
    if (typeof record.rule_id !== 'string') return;
    if (typeof record.domain !== 'string') return;
    const keys = asArray(record.evidence_keys).filter(
      (entry): entry is string => typeof entry === 'string',
    );
    if (!keys.includes(metricKey)) return;
    const id = `${record.domain}:${record.rule_id}`;
    if (seen.has(id)) return;
    seen.add(id);
    out.push({
      rule_id: record.rule_id,
      domain: record.domain,
      pattern: typeof record.pattern === 'string' ? record.pattern : '',
    });
  };
  if (domainSummaries && typeof domainSummaries === 'object') {
    for (const summary of Object.values(domainSummaries)) {
      const record = asRecord(summary);
      if (!record) continue;
      for (const stmt of asArray(record.statements)) consider(stmt);
    }
  }
  for (const stmt of asArray(crossDomainStatements)) consider(stmt);
  return out;
}

export interface TemporalReference {
  hasProfile: boolean;
  hasAnomaly: boolean;
  hasChange: boolean;
  hasRadar: boolean;
  hasThermal: boolean;
}

/**
 * Presence of backend monthly records for one metric key.
 * Booleans only; no values are read and nothing is combined.
 */
export function temporalReferenceFor(
  metricKey: string,
  temporal: TemporalSectionPayload | null | undefined,
): TemporalReference {
  const ref: TemporalReference = {
    hasProfile: false,
    hasAnomaly: false,
    hasChange: false,
    hasRadar: false,
    hasThermal: false,
  };
  if (typeof metricKey !== 'string' || metricKey.length === 0) return ref;
  const bag = asRecord(temporal);
  if (!bag) return ref;
  const hasKey = (table: unknown): boolean => {
    const records = asRecord(table);
    return !!records && asRecord(records[metricKey]) !== null;
  };
  ref.hasProfile = hasKey(bag.profiles);
  ref.hasAnomaly = hasKey(bag.anomalies);
  ref.hasChange = hasKey(bag.changes);
  ref.hasRadar =
    hasKey(bag.radar_profiles) || hasKey(bag.radar_analyses);
  ref.hasThermal =
    hasKey(bag.thermal_profiles) || hasKey(bag.thermal_analyses);
  return ref;
}

export interface SpatialReference {
  observationCount: number;
  summaryState: string | null;
  hasConcordance: boolean;
  hasPersistence: boolean;
}

/**
 * Compact spatial presence for one metric key. Counts and the
 * backend summary state travel verbatim; nothing is aggregated
 * beyond counting exact-key observations.
 */
export function spatialReferenceFor(
  metricKey: string,
  spatial: SpatialSectionPayload | null | undefined,
): SpatialReference {
  const ref: SpatialReference = {
    observationCount: 0,
    summaryState: null,
    hasConcordance: false,
    hasPersistence: false,
  };
  if (typeof metricKey !== 'string' || metricKey.length === 0) return ref;
  const bag = asRecord(spatial);
  if (!bag) return ref;
  let count = 0;
  for (const entry of asArray(bag.observations)) {
    const record = asRecord(entry) as CellObservationPayload | null;
    if (!record) continue;
    if ((record as { metric_key?: unknown }).metric_key === metricKey) count += 1;
  }
  ref.observationCount = count;
  const summaries = asRecord(bag.summaries);
  const summary = summaries ? asRecord(summaries[metricKey]) : null;
  const state = summary ? summary.state : null;
  ref.summaryState = typeof state === 'string' ? state : null;
  for (const entry of asArray(bag.concordance)) {
    const record = asRecord(entry) as CellConcordancePayload | null;
    if (!record) continue;
    const metrics = asArray((record as { metrics?: unknown }).metrics);
    if (metrics.includes(metricKey)) {
      ref.hasConcordance = true;
      break;
    }
  }
  ref.hasPersistence = asArray(bag.persistence).length > 0 && count > 0;
  return ref;
}

/** Backend P2.5 concordance months, verbatim passthrough. */
export function concordanceMonthsOf(
  temporal: TemporalSectionPayload | null | undefined,
): ConcordanceMonth[] {
  const bag = asRecord(temporal);
  const section = bag ? asRecord(bag.concordance) : null;
  const out: ConcordanceMonth[] = [];
  for (const entry of asArray(section ? section.months : [])) {
    const record = asRecord(entry);
    if (!record || typeof record.window_start !== 'string') continue;
    out.push(entry as ConcordanceMonth);
  }
  return out;
}

/** Backend P2.5 concordance summary counts, verbatim passthrough. */
export function concordanceSummaryOf(
  temporal: TemporalSectionPayload | null | undefined,
): ConcordanceSummary | null {
  const bag = asRecord(temporal);
  const section = bag ? asRecord(bag.concordance) : null;
  if (!section) return null;
  const summary: unknown = section.summary;
  if (!asRecord(summary)) return null;
  return summary as ConcordanceSummary;
}

/** Backend P1.4 joint NDVI-moisture analysis, verbatim passthrough. */
export function jointAnalysisOf(
  temporal: TemporalSectionPayload | null | undefined,
): JointAnalysis | null {
  const bag = asRecord(temporal);
  if (!bag) return null;
  const joint: unknown = bag.joint;
  const record = asRecord(joint);
  if (!record || typeof record.ndvi_key !== 'string') return null;
  if (typeof record.moisture_key !== 'string') return null;
  return joint as JointAnalysis;
}

/** Backend P2.5 concordance series (rule, methods, limitations), verbatim passthrough. */
export function concordanceSeriesOf(
  temporal: TemporalSectionPayload | null | undefined,
): ConcordanceSeries | null {
  const bag = asRecord(temporal);
  const section = bag ? asRecord(bag.concordance) : null;
  if (!section || typeof section.rule_id !== 'string') return null;
  const methods: Record<string, string> = {};
  const methodBag = asRecord(section.methods);
  if (methodBag) {
    for (const [key, value] of Object.entries(methodBag)) {
      if (typeof value === 'string') methods[key] = value;
    }
  }
  return {
    rule_id: section.rule_id,
    rule: typeof section.rule === 'string' ? section.rule : '',
    months: concordanceMonthsOf(temporal),
    summary: concordanceSummaryOf(temporal),
    methods,
    limitations: asArray(section.limitations).filter(
      (entry): entry is string => typeof entry === 'string',
    ),
  };
}

/** Backend radar anomaly analyses keyed by metric, verbatim passthrough. */
export function radarAnalysesOf(
  temporal: TemporalSectionPayload | null | undefined,
): Array<{ metricKey: string; analysis: RadarAnomalyAnalysis }> {
  const bag = asRecord(temporal);
  const table = bag ? asRecord(bag.radar_analyses) : null;
  if (!table) return [];
  const out: Array<{ metricKey: string; analysis: RadarAnomalyAnalysis }> = [];
  for (const [metricKey, entry] of Object.entries(table)) {
    const record = asRecord(entry);
    if (!record || typeof record.metric_key !== 'string') continue;
    out.push({ metricKey, analysis: entry as RadarAnomalyAnalysis });
  }
  return out;
}

/** Backend P4.4 thermal-concordance months, verbatim passthrough. */
export function thermalConcordanceMonthsOf(
  temporal: TemporalSectionPayload | null | undefined,
): ThermalConcordanceMonth[] {
  const bag = asRecord(temporal);
  const section = bag ? asRecord(bag.thermal_concordance) : null;
  const out: ThermalConcordanceMonth[] = [];
  for (const entry of asArray(section ? section.months : [])) {
    const record = asRecord(entry);
    if (!record || typeof record.window_start !== 'string') continue;
    out.push(entry as ThermalConcordanceMonth);
  }
  return out;
}

/**
 * Additive P3 pattern rows when a response carries them under a
 * known key. The /analysis response does not currently include
 * this section, so the usual result is an empty list. Rows are
 * never built here; only backend rows pass through.
 */
export function patternsInResponse(response: unknown): EvidencePattern[] {
  const bag = asRecord(response);
  if (!bag) return [];
  const out: EvidencePattern[] = [];
  for (const key of ['patterns', 'evidence_patterns']) {
    for (const entry of asArray(bag[key])) {
      const record = asRecord(entry);
      if (!record || typeof record.pattern_id !== 'string') continue;
      if (typeof record.pattern_type !== 'string') continue;
      out.push(entry as EvidencePattern);
    }
    if (out.length > 0) return out;
  }
  return out;
}

/**
 * Additive P3.3 validation rows when a response carries them under
 * a known key. The /analysis response does not currently include
 * this section, so the usual result is an empty list. Rows are
 * never built here; only backend rows pass through.
 */
export function validationsInResponse(response: unknown): CrossPatternValidation[] {
  const bag = asRecord(response);
  if (!bag) return [];
  const out: CrossPatternValidation[] = [];
  for (const key of ['cross_pattern_validations', 'validations']) {
    for (const entry of asArray(bag[key])) {
      const record = asRecord(entry);
      if (!record || typeof record.validation_id !== 'string') continue;
      if (typeof record.status !== 'string') continue;
      out.push(entry as CrossPatternValidation);
    }
    if (out.length > 0) return out;
  }
  return out;
}
