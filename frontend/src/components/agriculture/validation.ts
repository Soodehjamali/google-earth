import type {
  DuplicateRecord,
  RejectedRecord,
  ValidationResult,
  ValidationSection,
} from '../../types/index.ts';
import { asArray, asRecord } from './parse.ts';

/**
 * Ground-truth validation presentation mapping (P6.4).
 *
 * Pure read-only helpers over the P6.3 validation section of the
 * Agriculture /analysis response. Backend records are narrowed and
 * relabeled for display; nothing is computed, compared, converted,
 * ranked, or graded here. Backend ordering is always preserved.
 */

/** The exact six backend validation states — never extended. */
export const VALIDATION_STATUSES = [
  'MATCHED_REFERENCE',
  'MISMATCHED_REFERENCE',
  'INSUFFICIENT_REFERENCE',
  'INSUFFICIENT_ANALYSIS',
  'UNAVAILABLE',
  'NOT_VALIDATED',
] as const;

export type ValidationStatus = (typeof VALIDATION_STATUSES)[number];

/**
 * Neutral human-readable labels for the six backend states.
 * Descriptive only: no correctness, severity, confidence, risk,
 * accuracy, or pass/fail wording is attached to any state.
 */
const STATUS_LABELS: Record<string, string> = {
  MATCHED_REFERENCE: 'Matched reference',
  MISMATCHED_REFERENCE: 'Mismatched reference',
  INSUFFICIENT_REFERENCE: 'Insufficient reference',
  INSUFFICIENT_ANALYSIS: 'Insufficient analysis',
  UNAVAILABLE: 'Unavailable',
  NOT_VALIDATED: 'Not validated',
};

/** Display label for a backend status; unknown states pass through verbatim. */
export function validationStatusLabel(status: unknown): string {
  if (typeof status === 'string' && status in STATUS_LABELS) {
    return STATUS_LABELS[status];
  }
  return typeof status === 'string' && status.length > 0 ? status : '—';
}

/** Narrow an unknown value to a validation section without blind casts. */
export function asValidationSection(value: unknown): ValidationSection | null {
  const record = asRecord(value);
  if (!record) return null;
  if (!Array.isArray(record.results)) return null;
  return value as ValidationSection;
}

/** Results in backend order; unshaped rows omitted, never reordered. */
export function validationResults(
  section: ValidationSection | null | undefined,
): ValidationResult[] {
  if (!section || typeof section !== 'object') return [];
  const out: ValidationResult[] = [];
  for (const entry of asArray((section as { results?: unknown }).results)) {
    const record = asRecord(entry);
    if (!record || typeof record.validation_id !== 'string') continue;
    if (typeof record.status !== 'string') continue;
    out.push(entry as ValidationResult);
  }
  return out;
}

/** Rejected references in backend order; unshaped rows omitted. */
export function rejectedReferences(
  section: ValidationSection | null | undefined,
): RejectedRecord[] {
  if (!section || typeof section !== 'object') return [];
  const out: RejectedRecord[] = [];
  for (const entry of asArray(
    (section as { rejected_references?: unknown }).rejected_references,
  )) {
    const record = asRecord(entry);
    if (!record) continue;
    out.push(entry as RejectedRecord);
  }
  return out;
}

/** Duplicate records in backend order; unshaped rows omitted. */
export function duplicateReferences(
  section: ValidationSection | null | undefined,
): DuplicateRecord[] {
  if (!section || typeof section !== 'object') return [];
  const out: DuplicateRecord[] = [];
  for (const entry of asArray(
    (section as { duplicates?: unknown }).duplicates,
  )) {
    const record = asRecord(entry);
    if (!record) continue;
    out.push(entry as DuplicateRecord);
  }
  return out;
}

/** Verbatim limitation strings; non-strings omitted, never invented. */
export function validationLimitations(
  section: ValidationSection | null | undefined,
): string[] {
  if (!section || typeof section !== 'object') return [];
  return asArray((section as { limitations?: unknown }).limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

/**
 * Display text for a tri-state backend flag (states_agree,
 * values_comparable). True/false render as words; null, undefined,
 * and non-booleans render as the unavailable marker.
 */
export function triStateLabel(value: unknown): string {
  if (value === true) return 'yes';
  if (value === false) return 'no';
  return '—';
}

/** Display text for an optional backend string; missing renders as a marker. */
export function optionalText(value: unknown): string {
  return typeof value === 'string' && value.length > 0 ? value : '—';
}

/**
 * Verbatim provenance entries for display. Only string, finite
 * number, and boolean values are shown; anything else renders as
 * the unavailable marker so no value is ever reinterpreted.
 * Entries keep backend key order.
 */
export interface ValidationProvenanceEntry {
  key: string;
  value: string;
}

export function validationProvenanceEntries(
  provenance: Record<string, unknown> | null | undefined,
): ValidationProvenanceEntry[] {
  const record = asRecord(provenance);
  if (!record) return [];
  const out: ValidationProvenanceEntry[] = [];
  for (const [key, value] of Object.entries(record)) {
    if (typeof value === 'string') {
      out.push({ key, value: value.length > 0 ? value : '—' });
    } else if (typeof value === 'number' && Number.isFinite(value)) {
      out.push({ key, value: String(value) });
    } else if (typeof value === 'boolean') {
      out.push({ key, value: value ? 'yes' : 'no' });
    } else if (value === null || value === undefined) {
      out.push({ key, value: '—' });
    } else {
      out.push({ key, value: '—' });
    }
  }
  return out;
}
