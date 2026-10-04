/**
 * Temporal chart data mapping (P5.2 visualization layer).
 *
 * Pure presentation mapping only: backend model records become
 * chart datums with coordinates, labels, and passthrough fields.
 * This module performs no scientific computation — no means, no
 * spreads, no z-scores, no percentiles, no baselines, no changes,
 * no rates, no interpolation, no gap filling. Every numeric or
 * categorical field on a datum originates from a backend value.
 */
import type {
  MonthChange,
  AnomalyPoint as P12AnomalyPoint,
  ThermalConcordanceMonth,
  ThermalMetricAnalysis,
} from '../../types/index.ts';
import { asArray, asRecord, isFiniteNumber } from './parse.ts';

/** One plotted month. Null value renders as a gap, never as zero. */
export interface TemporalDatum {
  window_start: string;
  window_end: string;
  /** Short axis label, formatted from window_start for display. */
  label: string;
  /** Full period text for tooltips. */
  period: string;
  value: number | null;
  unit: string;
  /** Backend categorical state (category or direction), verbatim. */
  state: string | null;
  quality: string | null;
  coverage: number | null;
  baselineMean: number | null;
  z: number | null;
  percentile: number | null;
  absoluteChange: number | null;
  relativeChange: number | null;
  ratePerDay: number | null;
  direction: string | null;
  rapid: string | null;
}

export interface BaselineLevels {
  mean: number | null;
  min: number | null;
  max: number | null;
}

/** Backend profile point shape accepted by the mappers. */
export interface MappablePoint {
  window_start: string;
  window_end: string;
  value?: unknown;
  unit?: unknown;
  quality?: unknown;
  coverage_percent?: unknown;
}

/** Backend anomaly scoring read from an analysis payload. */
export interface ScoredPoint {
  window_start: string;
  category?: unknown;
  z_score?: unknown;
  percentile?: unknown;
}

/** Backend change record read from an analysis payload. */
export interface ChangePoint {
  window_start: string;
  direction?: unknown;
  rapid?: unknown;
  absolute_change?: unknown;
  relative_change?: unknown;
  rate_per_day?: unknown;
}

function isWindowed(
  item: Record<string, unknown>,
): item is Record<string, unknown> & { window_start: string } {
  return typeof item.window_start === 'string';
}

/** Short axis label for a window start; invalid input passes through. */
export function formatShortDate(iso: string): string {
  if (typeof iso !== 'string' || iso.length < 7) return String(iso ?? '');
  const parsed = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return iso;
  const month = parsed.toLocaleDateString('en-US', {
    month: 'short',
    timeZone: 'UTC',
  });
  const year = parsed.toLocaleDateString('en-US', {
    year: '2-digit',
    timeZone: 'UTC',
  });
  return `${month} ${year}`;
}

/** Finite numbers only — non-finite backend values become gaps. */
export function toGapValue(value: unknown): number | null {
  return isFiniteNumber(value) ? value : null;
}

function toText(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function toCoverage(value: unknown): number | null {
  return isFiniteNumber(value) ? value : null;
}

/**
 * Map backend profile points to chart datums in backend order.
 * Values, units, quality, and coverage pass through untouched;
 * non-finite values become nulls so the chart renders gaps.
 */
export function mapProfilePoints(
  points: MappablePoint[],
  fallbackUnit: string,
): TemporalDatum[] {
  return (Array.isArray(points) ? points : []).map((point) => ({
    window_start: point.window_start,
    window_end: point.window_end,
    label: formatShortDate(point.window_start),
    period: `${point.window_start} → ${point.window_end}`,
    value: toGapValue(point.value),
    unit: typeof point.unit === 'string' && point.unit ? point.unit : fallbackUnit,
    state: null,
    quality: toText(point.quality),
    coverage: toCoverage(point.coverage_percent),
    baselineMean: null,
    z: null,
    percentile: null,
    absoluteChange: null,
    relativeChange: null,
    ratePerDay: null,
    direction: null,
    rapid: null,
  }));
}

/**
 * Attach backend anomaly scoring to datums by exact window_start.
 * Categories, z-scores, and percentiles are read, never derived.
 */
export function attachAnomalies(
  data: TemporalDatum[],
  anomalies: ScoredPoint[] | null | undefined,
): TemporalDatum[] {
  if (!Array.isArray(anomalies) || anomalies.length === 0) return data;
  const byWindow = new Map(
    anomalies
      .filter((point) => point && typeof point.window_start === 'string')
      .map((point) => [point.window_start, point]),
  );
  return data.map((datum) => {
    const scored = byWindow.get(datum.window_start);
    if (!scored) return datum;
    return {
      ...datum,
      state: typeof scored.category === 'string' ? scored.category : datum.state,
      z: isFiniteNumber(scored.z_score) ? scored.z_score : null,
      percentile: isFiniteNumber(scored.percentile) ? scored.percentile : null,
    };
  });
}

/**
 * Attach backend change records to datums by exact window_start.
 * Absolute/relative change, rate, direction, and rapid flags are
 * read, never recomputed from adjacent points.
 */
export function attachChanges(
  data: TemporalDatum[],
  changes: ChangePoint[] | null | undefined,
): TemporalDatum[] {
  if (!Array.isArray(changes) || changes.length === 0) return data;
  const byWindow = new Map(
    changes
      .filter((change) => change && typeof change.window_start === 'string')
      .map((change) => [change.window_start, change]),
  );
  return data.map((datum) => {
    const change = byWindow.get(datum.window_start);
    if (!change) return datum;
    const direction =
      typeof change.direction === 'string' ? change.direction : null;
    return {
      ...datum,
      state: datum.state ?? direction,
      absoluteChange: isFiniteNumber(change.absolute_change)
        ? change.absolute_change
        : null,
      relativeChange: isFiniteNumber(change.relative_change)
        ? change.relative_change
        : null,
      ratePerDay: isFiniteNumber(change.rate_per_day) ? change.rate_per_day : null,
      direction,
      rapid: typeof change.rapid === 'string' ? change.rapid : null,
    };
  });
}

/** Read backend baseline levels for reference lines; null when absent. */
export function baselineLevels(
  baseline:
    | {
        mean?: unknown;
        minimum?: unknown;
        maximum?: unknown;
      }
    | null
    | undefined,
): BaselineLevels | null {
  if (!baseline || typeof baseline !== 'object') return null;
  if (!isFiniteNumber(baseline.mean)) return null;
  return {
    mean: baseline.mean,
    min: isFiniteNumber(baseline.minimum) ? baseline.minimum : null,
    max: isFiniteNumber(baseline.maximum) ? baseline.maximum : null,
  };
}

/** True when at least one datum carries a finite value. */
export function hasUsableData(data: TemporalDatum[]): boolean {
  return data.some((datum) => datum.value !== null);
}

/**
 * Presentation tone for a backend state, following the existing
 * pattern-meta palette. Text labels always accompany color, so no
 * meaning travels through color alone.
 */
export function stateTone(state: string | null): string {
  if (state === 'ABOVE_BASELINE' || state === 'INCREASE' || state === 'RAPID_INCREASE') {
    return '#27ae60';
  }
  if (state === 'BELOW_BASELINE' || state === 'DECREASE' || state === 'RAPID_DECREASE') {
    return '#c0392b';
  }
  if (state === 'NORMAL' || state === 'STABLE' || state === 'NOT_RAPID') {
    return '#7f8c8d';
  }
  if (state === 'UP') return '#27ae60';
  if (state === 'DOWN') return '#c0392b';
  if (state === 'NEUTRAL') return '#7f8c8d';
  return '#95a5a6';
}

/** Persistence summary text from backend values only. */
export function persistenceSummary(
  persistence:
    | {
        state?: unknown;
        longest_run_below?: unknown;
        longest_run_above?: unknown;
      }
    | null
    | undefined,
): string | null {
  if (!persistence || typeof persistence !== 'object') return null;
  if (typeof persistence.state !== 'string') return null;
  const runs: string[] = [];
  if (isFiniteNumber(persistence.longest_run_below) && persistence.longest_run_below > 0) {
    runs.push(`below: ${persistence.longest_run_below}`);
  }
  if (isFiniteNumber(persistence.longest_run_above) && persistence.longest_run_above > 0) {
    runs.push(`above: ${persistence.longest_run_above}`);
  }
  const detail = runs.length > 0 ? ` (longest run ${runs.join(', ')})` : '';
  return `${persistence.state}${detail}`;
}

/**
 * Locate profile-shaped payloads inside evidence bundles by exact
 * metric key. A payload qualifies only when it carries a points
 * array of windowed records; anything else is ignored so the
 * section renders an honest empty state instead of guessing.
 */
export function findTemporalPayloads(
  bundles: Record<string, { items?: unknown } | null | undefined> | null | undefined,
): Record<string, Record<string, unknown>> {
  const found: Record<string, Record<string, unknown>> = {};
  if (!bundles || typeof bundles !== 'object') return found;
  for (const bundle of Object.values(bundles)) {
    if (!bundle || typeof bundle !== 'object') continue;
    for (const entry of asArray(bundle.items)) {
      const record = asRecord(entry);
      if (!record || typeof record.metric_key !== 'string') continue;
      const points = asArray(record.points);
      const shaped = points.length > 0 && points.every((point) => {
        const item = asRecord(point);
        return !!item && typeof item.window_start === 'string';
      });
      if (shaped && !(record.metric_key in found)) {
        found[record.metric_key] = record;
      }
    }
  }
  return found;
}

/** Narrow a payload's points for the profile mapper. */
export function payloadPoints(
  payload: Record<string, unknown> | null | undefined,
): MappablePoint[] {
  if (!payload) return [];
  return asArray(payload.points)
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => item !== null)
    .filter((item) => typeof item.window_start === 'string')
    .map((item) => ({
      window_start: item.window_start as string,
      window_end: typeof item.window_end === 'string' ? item.window_end : '',
      value: item.value,
      unit: item.unit,
      quality: item.quality,
      coverage_percent: item.coverage_percent,
    }));
}

/** Narrow a payload's anomalies for the anomaly mapper. */
export function payloadAnomalies(
  payload: Record<string, unknown> | null | undefined,
): ScoredPoint[] {
  if (!payload) return [];
  // P1.2 anomaly profiles carry scored months under `points`;
  // P2.4/P4.3 analyses carry them under `anomalies`. Both shapes
  // hold the same backend-scored records.
  const source = asArray(payload.anomalies).length > 0
    ? payload.anomalies
    : payload.points;
  return asArray(source)
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => item !== null)
    .filter(isWindowed)
    .map((item) => ({
      window_start: item.window_start,
      category: item.category,
      z_score: item.z_score,
      percentile: item.percentile,
    }));
}

/** Narrow a payload's changes for the change mapper. */
export function payloadChanges(
  payload: Record<string, unknown> | null | undefined,
): ChangePoint[] {
  if (!payload) return [];
  return asArray(payload.changes)
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => item !== null)
    .filter(isWindowed)
    .map((item) => ({
      window_start: item.window_start,
      direction: item.direction,
      rapid: item.rapid,
      absolute_change: item.absolute_change,
      relative_change: item.relative_change,
      rate_per_day: item.rate_per_day,
    }));
}

/** Read a thermal relationship state for one side of a month. */
export function relationshipFor(
  month: ThermalConcordanceMonth | null | undefined,
  side: 'lst' | 'air',
): string | null {
  if (!month) return null;
  const value = side === 'lst' ? month.lst_relationship : month.air_relationship;
  return typeof value === 'string' ? value : null;
}

/** Read a thermal orientation for one side of a month. */
export function orientationFor(
  month: ThermalConcordanceMonth | null | undefined,
  side: 'lst' | 'air',
): string | null {
  if (!month) return null;
  const evidence = side === 'lst' ? month.lst : month.air;
  if (!evidence || typeof evidence.orientation !== 'string') return null;
  return evidence.orientation;
}

/** Match months of a thermal analysis to chart windows by identity. */
export function monthsForAnalysis(
  analysis: ThermalMetricAnalysis | null | undefined,
): { window_start: string; anomalies: P12AnomalyPoint[]; changes: MonthChange[] }[] {
  if (!analysis) return [];
  const anomalies = Array.isArray(analysis.anomalies) ? analysis.anomalies : [];
  const changes = Array.isArray(analysis.changes) ? analysis.changes : [];
  const starts = new Set<string>();
  for (const point of anomalies) starts.add(point.window_start);
  for (const change of changes) starts.add(change.window_start);
  return [...starts].map((window_start) => ({
    window_start,
    anomalies: anomalies.filter((p) => p.window_start === window_start),
    changes: changes.filter((c) => c.window_start === window_start),
  }));
}

const PROFILE_TABLES = ['profiles', 'radar_profiles', 'thermal_profiles'];
const ANOMALY_TABLES = ['anomalies', 'radar_analyses', 'thermal_analyses'];
const CHANGE_TABLES = ['changes', 'radar_analyses', 'thermal_analyses'];

function tableEntry(
  temporal: unknown,
  tables: string[],
  metricKey: string,
): Record<string, unknown> | null {
  const bag = asRecord(temporal);
  if (!bag) return null;
  for (const table of tables) {
    const records = asRecord(bag[table]);
    const entry = records ? asRecord(records[metricKey]) : null;
    if (entry) return entry;
  }
  return null;
}

/**
 * Explicit backend temporal payload for one metric, preferred over
 * bundle sniffing. Reads the P5.3 `temporal` section produced by
 * the analysis response: profiles, radar/thermal variants keyed
 * by exact metric key. Returns null when the backend sent none.
 */
export function profileFor(
  temporal: unknown,
  metricKey: string,
): Record<string, unknown> | null {
  return tableEntry(temporal, PROFILE_TABLES, metricKey);
}

/** Explicit backend anomaly payload for one metric, if present. */
export function anomalyFor(
  temporal: unknown,
  metricKey: string,
): Record<string, unknown> | null {
  return tableEntry(temporal, ANOMALY_TABLES, metricKey);
}

/** Explicit backend change payload for one metric, if present. */
export function changeFor(
  temporal: unknown,
  metricKey: string,
): Record<string, unknown> | null {
  return tableEntry(temporal, CHANGE_TABLES, metricKey);
}

/** Explicit backend thermal-concordance months, if present. */
export function concordanceMonths(
  temporal: unknown,
): Record<string, unknown>[] {
  const bag = asRecord(temporal);
  const section = bag ? asRecord(bag.thermal_concordance) : null;
  const months = section ? asArray(section.months) : [];
  return months
    .map(asRecord)
    .filter((item): item is Record<string, unknown> => item !== null)
    .filter((item) => typeof item.window_start === 'string');
}
