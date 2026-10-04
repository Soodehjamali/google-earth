import type { TemporalProfilePoint } from '../../types/index.ts';
import { asArray, asRecord, isFiniteNumber } from './parse.ts';

/**
 * Year-over-year grouping over backend monthly profile points (P1).
 *
 * Pure presentation mapping only: points are bucketed by the calendar
 * year of their exact `window_start` into month slots 01–12. Values —
 * including nulls — travel verbatim; malformed dates are skipped and
 * counted, never fabricated. Gaps are preserved as gaps: no filling,
 * no aggregation, no ranking.
 */

/** Minimum distinct years with data required for a comparison. */
export const MIN_COMPARABLE_YEARS = 2;

export interface YearMonthSlot {
  /** Two-digit month slot, '01'–'12'. */
  month: string;
  /** Short display label for the slot. */
  label: string;
  /** Observed value or null gap, verbatim from the backend point. */
  value: number | null;
}

export interface YearSeries {
  /** Four-digit calendar year. */
  year: string;
  /** Month slots in chronological order. */
  months: YearMonthSlot[];
}

export interface GroupedYears {
  /** One series per distinct year, ascending. */
  years: YearSeries[];
  /** Points skipped for malformed dates. */
  skipped: number;
}

const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** Strict YYYY-MM-DD prefix check; anything else is unusable. */
function splitYearMonth(windowStart: unknown): { year: string; month: string } | null {
  if (typeof windowStart !== 'string' || windowStart.length < 7) return null;
  const year = windowStart.slice(0, 4);
  const month = windowStart.slice(5, 7);
  if (!/^\d{4}$/.test(year) || !/^(0[1-9]|1[0-2])$/.test(month)) return null;
  if (windowStart[4] !== '-' || windowStart[7] !== '-') return null;
  return { year, month };
}

/**
 * Bucket monthly points into per-year series aligned on month slots.
 * Accepts raw backend point records; unshaped or misdated points are
 * skipped and counted. Output years ascend; months run 01–12.
 */
export function groupPointsByYear(points: unknown): GroupedYears {
  const byYear = new Map<string, Map<string, number | null>>();
  let skipped = 0;
  for (const entry of asArray(points)) {
    const record = asRecord(entry);
    if (!record) {
      skipped += 1;
      continue;
    }
    const split = splitYearMonth(record.window_start);
    if (!split) {
      skipped += 1;
      continue;
    }
    const rawValue = (record as { value?: unknown }).value;
    const value = isFiniteNumber(rawValue) ? rawValue : null;
    let year = byYear.get(split.year);
    if (!year) {
      year = new Map<string, number | null>();
      byYear.set(split.year, year);
    }
    // Later points for the same month slot replace earlier ones so
    // one slot never carries two values; input order decides.
    year.set(split.month, value);
  }
  const years: YearSeries[] = [...byYear.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([year, slots]) => ({
      year,
      months: [...slots.entries()]
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([month, value]) => ({
          month,
          label: MONTH_LABELS[Number(month) - 1] ?? month,
          value,
        })),
    }));
  return { years, skipped };
}

/** Years carrying at least one finite observation, in ascending order. */
export function comparableYears(grouped: GroupedYears): YearSeries[] {
  if (!grouped || !Array.isArray(grouped.years)) return [];
  return grouped.years.filter((series) =>
    series.months.some((slot) => slot.value !== null),
  );
}

/** True when a genuine multi-year comparison is possible. */
export function canCompareYears(grouped: GroupedYears): boolean {
  return comparableYears(grouped).length >= MIN_COMPARABLE_YEARS;
}

/**
 * Narrow an unknown value to the NDVI temporal profile shape the
 * comparison reads. Returns null when no usable profile exists.
 */
export function ndviProfileOf(temporal: unknown): {
  points: TemporalProfilePoint[];
  unit: string;
} | null {
  return metricProfileOf(temporal, 'ndvi');
}

/** Metrics the year comparison can render, in preferred order. */
export const COMPARISON_METRICS = ['ndvi', 'ndmi', 'ndre', 'msi'];

/**
 * Narrow an unknown value to one metric's temporal profile shape.
 * Same narrowing as the NDVI reader, keyed by the requested metric.
 * Returns null when no usable profile exists for that key.
 */
export function metricProfileOf(
  temporal: unknown,
  metricKey: string,
): {
  points: TemporalProfilePoint[];
  unit: string;
} | null {
  const bag = asRecord(temporal);
  if (!bag) return null;
  const profiles = asRecord(bag.profiles);
  if (!profiles) return null;
  const profile = asRecord(profiles[metricKey]);
  if (!profile) return null;
  const points = asArray(profile.points)
    .map((entry) => asRecord(entry))
    .filter((record): record is Record<string, unknown> => record !== null)
    .filter((record) => typeof record.window_start === 'string')
    .map((record): TemporalProfilePoint => ({
      window_start: record.window_start as string,
      window_end: typeof record.window_end === 'string' ? record.window_end : '',
      value: isFiniteNumber(record.value) ? record.value : null,
      unit: typeof record.unit === 'string' ? record.unit : '',
      quality: typeof record.quality === 'string' ? record.quality : 'unavailable',
      coverage_percent: isFiniteNumber(record.coverage_percent)
        ? (record.coverage_percent as number)
        : null,
      image_count: typeof record.image_count === 'number' ? record.image_count : null,
    }));
  const unit = typeof profile.unit === 'string' ? profile.unit : '';
  return { points, unit };
}

/**
 * Comparison metrics carrying at least one finite backend point, in
 * preferred order. Only these keys are offered by the metric
 * selector; a metric with no usable data never appears as an option.
 */
export function usableComparisonMetrics(temporal: unknown): string[] {
  const out: string[] = [];
  for (const key of COMPARISON_METRICS) {
    const profile = metricProfileOf(temporal, key);
    if (!profile) continue;
    if (profile.points.some((point) => point.value !== null)) {
      out.push(key);
    }
  }
  return out;
}
