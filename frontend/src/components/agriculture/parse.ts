import type {
  AgriculturalAnalysisResponse,
  AgricultureHealthResponse,
  DomainMeta,
  EvidenceItemResponse,
  PatternMeta,
  ProvenanceResponse,
  SynthesisStatementResponse,
} from '../../types/index.ts';
import { DOMAIN_META, PATTERN_META } from '../../types/index.ts';

/** Narrow an unknown value to a plain record without casting blindly. */
export function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

/** Narrow an unknown value to an array without casting blindly. */
export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** True only for finite numbers — never null, NaN, Infinity, or strings. */
export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Render a metric value safely. Anything that is not a finite number
 * becomes the explicit unavailable marker — never 0, never NaN text.
 */
export function formatEvidenceValue(value: unknown, digits = 4): string {
  if (!isFiniteNumber(value)) return '—';
  return value.toFixed(digits);
}

/**
 * A scalar may be rendered as a KPI only when it carries a finite numeric
 * value AND is not marked unavailable. Null/unavailable must stay textual.
 */
export function shouldRenderKpi(
  item: { value?: unknown; status?: unknown } | null | undefined,
): boolean {
  if (!item) return false;
  if (item.status === 'unavailable') return false;
  return isFiniteNumber(item.value);
}

export type KpiTone = 'good' | 'warning' | 'danger' | 'neutral';

/** Map backend quality strings to the existing KPICard tones. */
export function qualityToKpiStatus(quality: unknown): KpiTone {
  if (quality === 'good' || quality === 'excellent') return 'good';
  if (quality === 'moderate') return 'warning';
  if (quality === 'poor' || quality === 'insufficient' || quality === 'unavailable') {
    return 'danger';
  }
  return 'neutral';
}

/** Map sufficiency strings to existing badge classes. */
export function sufficiencyBadgeClass(level: unknown): string {
  if (level === 'sufficient') return 'badge-good';
  if (level === 'limited') return 'badge-warning';
  return 'badge-danger';
}

const FALLBACK_PATTERN: PatternMeta = {
  label: 'Unknown pattern',
  labelFa: 'الگوی نامشخص',
  color: 'var(--color-text-muted)',
};

/** Unknown backend patterns fall back generically — never crash, never redesign. */
export function patternMetaFor(pattern: unknown): PatternMeta {
  if (typeof pattern === 'string' && pattern in PATTERN_META) {
    return PATTERN_META[pattern];
  }
  return FALLBACK_PATTERN;
}

const FALLBACK_DOMAIN: DomainMeta = {
  key: 'unknown',
  label: 'Unknown',
  labelFa: 'نامشخص',
  icon: '📊',
};

/** Unknown domain keys fall back generically. */
export function domainMetaFor(domain: unknown): DomainMeta {
  if (typeof domain === 'string' && domain in DOMAIN_META) {
    return DOMAIN_META[domain];
  }
  return { ...FALLBACK_DOMAIN, key: typeof domain === 'string' ? domain : 'unknown' };
}

export interface ProvenanceRow {
  key: string;
  label: string;
  value: string;
}

/**
 * Expose only provenance fields the backend actually returned.
 * Missing provenance (or missing fields) yields rows safely omitted
 * by the caller — never fabricated.
 */
export function getProvenanceRows(
  provenance: ProvenanceResponse | null | undefined,
): ProvenanceRow[] {
  if (!provenance || typeof provenance !== 'object') return [];
  const rows: ProvenanceRow[] = [];
  const push = (key: string, label: string, value: unknown) => {
    if (typeof value === 'string' && value.length > 0) {
      rows.push({ key, label, value });
    }
  };
  push('source_dataset_id', 'شناسه مجموعه', provenance.source_dataset_id);
  push('source_dataset_name', 'نام مجموعه', provenance.source_dataset_name);
  if (Array.isArray(provenance.bands)) {
    const bands = provenance.bands.filter(
      (entry): entry is string => typeof entry === 'string' && entry.length > 0,
    );
    if (bands.length > 0) {
      rows.push({ key: 'bands', label: 'باندها — bands', value: bands.join(', ') });
    }
  }
  push('temporal_kind', 'نوع زمانی', provenance.temporal_kind);
  push('measurement_basis', 'نوع اندازه‌گیری', provenance.measurement_basis);
  push('quality_level', 'سطح کیفیت', provenance.quality_level);
  push('spatial_resolution', 'رزولوشن مکانی', provenance.spatial_resolution);
  push('temporal_resolution', 'رزولوشن زمانی', provenance.temporal_resolution);
  push('aggregation_method', 'روش تجمیع', provenance.aggregation_method);
  push('unit', 'واحد', provenance.unit);
  push('requested_start', 'شروع درخواستی', provenance.requested_start);
  push('requested_end', 'پایان درخواستی', provenance.requested_end);
  push('date_start', 'شروع داده', provenance.date_start);
  push('date_end', 'پایان داده', provenance.date_end);
  if (isFiniteNumber(provenance.image_count)) {
    rows.push({
      key: 'image_count',
      label: 'تعداد تصاویر — image count',
      value: String(provenance.image_count),
    });
  }
  push('fallback_from', 'جایگزین از', provenance.fallback_from);
  push('computed_at', 'زمان محاسبه', provenance.computed_at);
  push('product_date', 'تاریخ محصول', provenance.product_date);
  push('formula', 'فرمول', provenance.formula);
  push('citation', 'استناد', provenance.citation);
  return rows;
}

/**
 * Defensive top-level normalization of the Comprehensive response.
 * Returns null when the payload is not an object at all; otherwise
 * guarantees the collections the hub iterates are safe to read.
 * Sub-objects are passed through — deeper guards live at render sites.
 */
export function normalizeResponse(
  raw: unknown,
): AgriculturalAnalysisResponse | null {
  const record = asRecord(raw);
  if (!record) return null;
  const domainSummaries = asRecord(record.domain_summaries) ?? {};
  const evidenceBundles = asRecord(record.evidence_bundles) ?? {};
  const stringList = (value: unknown): string[] =>
    asArray(value).filter((entry): entry is string => typeof entry === 'string');
  const normalized = {
    ...(record as object),
    domain_summaries: domainSummaries,
    evidence_bundles: evidenceBundles,
    available_domains: stringList(record.available_domains),
    unavailable_domains: stringList(record.unavailable_domains),
    // F-CONTRACT-FIX-1 additive fields: defensive defaults so responses
    // from a backend predating the contract stay safe to read.
    domains_with_data: stringList(record.domains_with_data),
    domains_with_statements: stringList(record.domains_with_statements),
    domains_without_data: stringList(record.domains_without_data),
    unavailable_metric_keys: stringList(record.unavailable_metric_keys),
    cross_domain_statements: asArray(record.cross_domain_statements),
    limitations: stringList(record.limitations),
  };
  return normalized as AgriculturalAnalysisResponse;
}

/** Defensive normalization of the agriculture health payload. */
export function normalizeHealth(raw: unknown): AgricultureHealthResponse | null {
  const record = asRecord(raw);
  if (!record) return null;
  return {
    status: typeof record.status === 'string' ? record.status : 'unknown',
    metrics_registered:
      typeof record.metrics_registered === 'number'
        ? record.metrics_registered
        : 0,
    evidence_layer:
      typeof record.evidence_layer === 'string' ? record.evidence_layer : 'unknown',
    synthesis_layer:
      typeof record.synthesis_layer === 'string' ? record.synthesis_layer : 'unknown',
    message: typeof record.message === 'string' ? record.message : '',
  };
}

/** Count scalar evidence items across all bundles (for the header summary). */
export function countEvidenceItems(
  result: AgriculturalAnalysisResponse | null | undefined,
): number {
  if (!result || typeof result !== 'object') return 0;
  const bundles = asRecord(result.evidence_bundles);
  if (!bundles) return 0;
  let count = 0;
  for (const bundle of Object.values(bundles)) {
    const record = asRecord(bundle);
    if (!record) continue;
    count += asArray(record.items).length;
  }
  return count;
}

/** Count unavailable entries across bundles + domain summaries. */
export function countUnavailable(
  result: AgriculturalAnalysisResponse | null | undefined,
): number {
  if (!result || typeof result !== 'object') return 0;
  let count = 0;
  const bundles = asRecord(result.evidence_bundles);
  if (bundles) {
    for (const bundle of Object.values(bundles)) {
      const record = asRecord(bundle);
      if (!record) continue;
      count += asArray(record.unavailable).length;
    }
  }
  const summaries = asRecord(result.domain_summaries);
  if (summaries) {
    for (const summary of Object.values(summaries)) {
      const record = asRecord(summary);
      if (!record) continue;
      count += asArray(record.unavailable_evidence).length;
    }
  }
  return count;
}

/**
 * Canonical unavailable-metric count (F-CONTRACT-FIX-1).
 *
 * Reads the backend's de-duplicated `unavailable_metric_keys` aggregate
 * so each missing metric counts exactly once.  `countUnavailable` above
 * sums the per-bundle and per-summary lists, which carry the same keys
 * and therefore double every missing metric; it is retained only for
 * backward compatibility and must not drive summary counts.
 * Falls back to the deduplicated read of the detailed lists only when
 * the response predates the aggregate field.
 */
export function countUnavailableMetrics(
  result: AgriculturalAnalysisResponse | null | undefined,
): number {
  if (!result || typeof result !== 'object') return 0;
  const canonical = asArray(result.unavailable_metric_keys).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  if (canonical.length > 0) return canonical.length;
  // Pre-contract response: deduplicate the detailed lists ourselves,
  // preserving exact-key identity (same guard rule, same source data).
  const seen = new Set<string>();
  const bundles = asRecord(result.evidence_bundles);
  if (bundles) {
    for (const bundle of Object.values(bundles)) {
      const record = asRecord(bundle);
      if (!record) continue;
      for (const entry of asArray(record.unavailable)) {
        if (typeof entry === 'string' && !seen.has(entry)) seen.add(entry);
      }
    }
  }
  return seen.size;
}

/** Narrow a bundle item to an evidence item shape without blind casts. */
export function asEvidenceItem(value: unknown): EvidenceItemResponse | null {
  const record = asRecord(value);
  if (!record || typeof record.metric_key !== 'string') return null;
  return value as EvidenceItemResponse;
}

export interface FoundEvidenceItem {
  item: EvidenceItemResponse;
  bundleName: string;
}

/**
 * Locate one metric's evidence across the given bundles by exact key —
 * never by substring matching. Returns null when the key is absent.
 */
export function findEvidenceItem(
  bundles: Record<string, { items?: unknown } | null | undefined> | null | undefined,
  metricKey: string,
): FoundEvidenceItem | null {
  if (!bundles || typeof bundles !== 'object') return null;
  for (const [bundleName, bundle] of Object.entries(bundles)) {
    if (!bundle || typeof bundle !== 'object') continue;
    const items = asArray(bundle.items);
    for (const entry of items) {
      const item = asEvidenceItem(entry);
      if (item && item.metric_key === metricKey) {
        return { item, bundleName };
      }
    }
  }
  return null;
}

/** Narrow a summary entry to a synthesis statement without blind casts. */
export function asSynthesisStatement(
  value: unknown,
): SynthesisStatementResponse | null {
  const record = asRecord(value);
  if (!record) return null;
  if (typeof record.rule_id !== 'string') return null;
  if (typeof record.domain !== 'string') return null;
  if (typeof record.statement !== 'string') return null;
  return value as SynthesisStatementResponse;
}
