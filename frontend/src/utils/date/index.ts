/**
 * Centralized Date Architecture for Agricultural Intelligence Platform
 *
 * Guarantees:
 * 1. Presentation Layer ONLY displays Jalali (Persian) calendar to users.
 * 2. API Contract & GEE ONLY receives Gregorian ISO dates (YYYY-MM-DD).
 * 3. Exact astronomical calendar conversion via tested mathematical algorithms.
 * 4. Leap years, month boundaries, and year boundaries are strictly respected.
 * 5. Zero duplicate conversion logic.
 */

import {
  isLeapJalaaliYear,
  isValidJalaaliDate,
  jalaaliMonthLength,
  toGregorian,
  toJalaali,
} from 'jalaali-js';

export interface JalaliDateParts {
  jy: number;
  jm: number;
  jd: number;
}

export interface GregorianDateParts {
  gy: number;
  gm: number;
  gd: number;
}

export const JALALI_MONTH_NAMES_FA: readonly string[] = [
  'فروردین',
  'اردیبهشت',
  'خرداد',
  'تیر',
  'مرداد',
  'شهریور',
  'مهر',
  'آبان',
  'آذر',
  'دی',
  'بهمن',
  'اسفند',
];

const PERSIAN_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

/** Converts any English digits in a string to Persian digits */
export function toPersianDigits(input: string | number): string {
  const str = String(input);
  return str.replace(/[0-9]/g, (w) => PERSIAN_DIGITS[parseInt(w, 10)] ?? w);
}

/** Converts any Persian or Arabic-Indic digits to English ASCII digits */
export function toEnglishDigits(input: string): string {
  return input
    .replace(/[۰-۹]/g, (w) => String(w.charCodeAt(0) - 1776))
    .replace(/[٠-٩]/g, (w) => String(w.charCodeAt(0) - 1632));
}

/** Pads a number to 2 digits */
function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

/** Check if a Jalali year is a leap year (366 days) */
export function isJalaliLeapYear(jy: number): boolean {
  return isLeapJalaaliYear(jy);
}

/** Get number of days in a specific Jalali year and month */
export function getJalaliMonthDays(jy: number, jm: number): number {
  if (jm < 1 || jm > 12) return 0;
  return jalaaliMonthLength(jy, jm);
}

/** Validates whether a given Jalali date is mathematically and calendar-wise valid */
export function isValidJalali(jy: number, jm: number, jd: number): boolean {
  return isValidJalaaliDate(jy, jm, jd);
}

/**
 * Converts Jalali date parts to Gregorian date parts.
 */
export function jalaliToGregorian(jy: number, jm: number, jd: number): GregorianDateParts {
  const res = toGregorian(jy, jm, jd);
  return { gy: res.gy, gm: res.gm, gd: res.gd };
}

/**
 * Converts Gregorian date parts to Jalali date parts.
 */
export function gregorianToJalali(gy: number, gm: number, gd: number): JalaliDateParts {
  const res = toJalaali(gy, gm, gd);
  return { jy: res.jy, jm: res.jm, jd: res.jd };
}

/**
 * Parses an ISO Gregorian date string (YYYY-MM-DD) and converts to Jalali parts.
 * Returns null if invalid.
 */
export function isoGregorianToJalali(iso: string | null | undefined): JalaliDateParts | null {
  if (!iso || typeof iso !== 'string') return null;
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const gy = parseInt(match[1], 10);
  const gm = parseInt(match[2], 10);
  const gd = parseInt(match[3], 10);
  if (Number.isNaN(gy) || Number.isNaN(gm) || Number.isNaN(gd) || gm < 1 || gm > 12 || gd < 1 || gd > 31) {
    return null;
  }
  return gregorianToJalali(gy, gm, gd);
}

/**
 * Parses a Jalali string like "1404/03/11", "1404-03-11", "۱۴۰۴/۰۳/۱۱" into Jalali parts.
 */
export function parseJalaliDateString(str: string | null | undefined): JalaliDateParts | null {
  if (!str || typeof str !== 'string') return null;
  const clean = toEnglishDigits(str).trim();
  const match = clean.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/);
  if (!match) return null;
  const jy = parseInt(match[1], 10);
  const jm = parseInt(match[2], 10);
  const jd = parseInt(match[3], 10);
  if (!isValidJalaaliDate(jy, jm, jd)) return null;
  return { jy, jm, jd };
}

/**
 * Formats a Jalali date to ASCII string YYYY/MM/DD (e.g. "1404/03/11")
 */
export function formatJalaliAscii(parts: JalaliDateParts): string {
  return `${parts.jy}/${pad2(parts.jm)}/${pad2(parts.jd)}`;
}

/**
 * Formats a Jalali date with Persian digits (e.g. "۱۴۰۴/۰۳/۱۱")
 */
export function formatJalaliPersian(parts: JalaliDateParts): string {
  return toPersianDigits(formatJalaliAscii(parts));
}

/**
 * Converts a Jalali date (parts or string) to Gregorian ISO string for API payload.
 * e.g. "1404/03/11" -> "2025-06-01"
 */
export function formatGregorianForApi(input: JalaliDateParts | string): string {
  const parts = typeof input === 'string' ? parseJalaliDateString(input) : input;
  if (!parts || !isValidJalaaliDate(parts.jy, parts.jm, parts.jd)) {
    throw new Error(`Invalid Jalali date provided for API conversion: ${JSON.stringify(input)}`);
  }
  const g = jalaliToGregorian(parts.jy, parts.jm, parts.jd);
  return `${g.gy}-${pad2(g.gm)}-${pad2(g.gd)}`;
}

/**
 * Converts an ISO Gregorian date string to formatted Jalali string.
 * e.g. "2025-06-01" -> "۱۴۰۴/۰۳/۱۱"
 */
export function formatGregorianToJalali(iso: string | null | undefined, persianDigits = true): string {
  const j = isoGregorianToJalali(iso);
  if (!j) return iso ?? '';
  return persianDigits ? formatJalaliPersian(j) : formatJalaliAscii(j);
}

export interface DateRangeValidationResult {
  isValid: boolean;
  errorFa: string | null;
  startGregorian?: string;
  endGregorian?: string;
}

/**
 * Validates a user-selected Jalali date range.
 * Enforces:
 * 1. Both dates are mathematically valid Jalali dates
 * 2. start date < end date
 * 3. Range does not exceed maxTemporalMonths (backend threshold, default: 36 months)
 * Returns Gregorian ISO strings ready for API payload if valid.
 */
export function validateJalaliDateRange(
  startJalali: string,
  endJalali: string,
  maxTemporalMonths = 36,
): DateRangeValidationResult {
  const startParts = parseJalaliDateString(startJalali);
  if (!startParts) {
    return {
      isValid: false,
      errorFa: 'تاریخ شروع نامعتبر است (فرمت صحیح: ۱۴۰۴/۰۳/۱۱)',
    };
  }

  const endParts = parseJalaliDateString(endJalali);
  if (!endParts) {
    return {
      isValid: false,
      errorFa: 'تاریخ پایان نامعتبر است (فرمت صحیح: ۱۴۰۴/۰۶/۱۰)',
    };
  }

  const startG = jalaliToGregorian(startParts.jy, startParts.jm, startParts.jd);
  const endG = jalaliToGregorian(endParts.jy, endParts.jm, endParts.jd);

  const startIso = `${startG.gy}-${pad2(startG.gm)}-${pad2(startG.gd)}`;
  const endIso = `${endG.gy}-${pad2(endG.gm)}-${pad2(endG.gd)}`;

  if (startIso === endIso) {
    return {
      isValid: false,
      errorFa: 'تاریخ پایان و تاریخ شروع نمی‌توانند یکسان باشند (حداقل یک روز فاصله الزامی است)',
    };
  }

  if (endIso < startIso) {
    return {
      isValid: false,
      errorFa: 'تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد',
    };
  }

  // Calculate approximate months difference
  const startDateObj = new Date(Date.UTC(startG.gy, startG.gm - 1, startG.gd));
  const endDateObj = new Date(Date.UTC(endG.gy, endG.gm - 1, endG.gd));
  const diffDays = (endDateObj.getTime() - startDateObj.getTime()) / (1000 * 60 * 60 * 24);
  const diffMonths = diffDays / 30.4375;

  if (diffMonths > maxTemporalMonths) {
    return {
      isValid: false,
      errorFa: `طول بازه زمانی انتخابی بیش از حد مجاز است (حداکثر ${maxTemporalMonths} ماه مجاز است)`,
    };
  }

  return {
    isValid: true,
    errorFa: null,
    startGregorian: startIso,
    endGregorian: endIso,
  };
}
