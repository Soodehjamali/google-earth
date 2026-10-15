/**
 * Centralized Persian (Jalali) Date Presentation Formatter
 *
 * Scope: Presentation Layer ONLY
 * Integrates with central date utilities at src/utils/date/index.ts.
 * Guarantees:
 * 1. Zero duplicate logic.
 * 2. Deterministic UTC timezone handling: Parses ISO YYYY-MM-DD.
 * 3. Non-mutating: Never alters or overwrites the underlying API Gregorian dates.
 * 4. Graceful fallback: If input is null, undefined, or not an ISO date, safely passes through.
 */

export * from '../../utils/date/index.ts';
import { isoGregorianToJalali, toPersianDigits } from '../../utils/date/index.ts';

const JALALI_DATE_FORMATTER = new Intl.DateTimeFormat('fa-IR-u-ca-persian', {
  timeZone: 'UTC',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const JALALI_MONTH_YEAR_FORMATTER = new Intl.DateTimeFormat('fa-IR-u-ca-persian', {
  timeZone: 'UTC',
  year: 'numeric',
  month: 'long',
});

/**
 * Parses an ISO date string (YYYY-MM-DD) into a timezone-anchored UTC Date object.
 * Returns null if the string does not match the ISO date pattern or is invalid.
 */
function parseIsoToUtcMidday(iso: string): Date | null {
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const year = parseInt(match[1], 10);
  const month = parseInt(match[2], 10);
  const day = parseInt(match[3], 10);
  if (
    Number.isNaN(year) ||
    Number.isNaN(month) ||
    Number.isNaN(day) ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > 31
  ) {
    return null;
  }
  return new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
}

/**
 * Formats an ISO date string (e.g. "2025-06-01") into standard Jalali format (e.g. "۱۴۰۴/۰۳/۱۱").
 * If the input is not a valid ISO date, returns the input string unchanged.
 */
export function formatPersianDate(iso: string | null | undefined): string {
  if (!iso || typeof iso !== 'string') return '';
  const date = parseIsoToUtcMidday(iso);
  if (!date) return iso;
  try {
    return JALALI_DATE_FORMATTER.format(date);
  } catch {
    return iso;
  }
}

/**
 * Formats a date range into Persian Jalali format:
 * e.g. ("2025-06-01", "2025-09-01") -> "۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰"
 */
export function formatPersianDateRange(
  startIso: string | null | undefined,
  endIso: string | null | undefined,
  separator: string = ' تا ',
): string {
  const startFa = formatPersianDate(startIso);
  const endFa = formatPersianDate(endIso);
  if (startFa && endFa) return `${startFa}${separator}${endFa}`;
  if (startFa) return startFa;
  if (endFa) return endFa;
  return '—';
}

/**
 * Converts an arrow-delimited or dash-delimited range string (e.g. "2025-06-01 → 2025-09-01")
 * into a Jalali range string ("۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰").
 */
export function formatPersianRangeString(
  rangeText: string | null | undefined,
  separator: string = ' تا ',
): string {
  if (!rangeText || typeof rangeText !== 'string') return '';
  if (rangeText.includes(' → ')) {
    const parts = rangeText.split(' → ');
    return formatPersianDateRange(parts[0], parts[1], separator);
  }
  if (rangeText.includes(' to ')) {
    const parts = rangeText.split(' to ');
    return formatPersianDateRange(parts[0], parts[1], separator);
  }
  return formatPersianDate(rangeText);
}

/**
 * Formats an ISO date string into Jalali month and year:
 * e.g. "2025-06-01" -> "خرداد ۱۴۰۴"
 */
export function formatPersianMonthYear(iso: string | null | undefined): string {
  if (!iso || typeof iso !== 'string') return '';
  const date = parseIsoToUtcMidday(iso);
  if (!date) return iso;
  try {
    return JALALI_MONTH_YEAR_FORMATTER.format(date);
  } catch {
    return iso;
  }
}

/**
 * Formats the accurate Jalali year from an ISO Gregorian date string (e.g. "2026-06-01" -> "۱۴۰۵")
 * with Persian digits.
 *
 * SCOPE: Presentation Layer ONLY.
 * NOTE: Derives the Jalali year from the astronomical calendar conversion of the actual
 * period start date via `isoGregorianToJalali`, strictly avoiding naive arithmetic (e.g. NOT year - 621).
 */
export function formatPersianYear(
  isoDate: string | null | undefined,
  fallbackGregorianYear?: number,
): string {
  if (isoDate && typeof isoDate === 'string') {
    const parts = isoGregorianToJalali(isoDate);
    if (parts && parts.jy) {
      return toPersianDigits(parts.jy);
    }
  }
  if (fallbackGregorianYear !== undefined && !Number.isNaN(fallbackGregorianYear)) {
    return toPersianDigits(fallbackGregorianYear);
  }
  return '';
}

/**
 * Returns the numerical Jalali year from an ISO Gregorian date string (e.g. "2026-06-01" -> 1405).
 */
export function getJalaliYear(
  isoDate: string | null | undefined,
  fallbackGregorianYear?: number,
): number {
  if (isoDate && typeof isoDate === 'string') {
    const parts = isoGregorianToJalali(isoDate);
    if (parts && parts.jy) {
      return parts.jy;
    }
  }
  return fallbackGregorianYear ?? 0;
}

