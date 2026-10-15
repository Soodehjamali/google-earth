/**
 * Dedicated test suite for Persian (Jalali) Date Presentation Layer.
 * Verifies:
 * 1. Correct Jalali conversion for known ISO dates (Nowruz, leap years, summer dates).
 * 2. Deterministic UTC midday anchoring (zero timezone off-by-one shifts).
 * 3. Range formatting with standard Persian separator ("تا").
 * 4. Month-year and chart short date formatting.
 * 5. Input safety and graceful fallbacks for malformed or absent inputs.
 * 6. Non-mutation of input strings or API data structures.
 * 7. Outgoing API request payload invariance (strictly Gregorian ISO YYYY-MM-DD).
 * 8. UI component integration across SynthesisHeader, DomainPage, SupportNotice,
 *    SpatialIntelligenceSection, AnalysisRequestForm, and TemporalLineChart.
 * 9. Technical provenance and historical year comparison invariance.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  formatPersianDate,
  formatPersianDateRange,
  formatPersianRangeString,
  formatPersianMonthYear,
  jalaliToGregorian,
  gregorianToJalali,
  isJalaliLeapYear,
  getJalaliMonthDays,
  formatGregorianForApi,
  validateJalaliDateRange,
} from '../persianDate.ts';
import { formatShortDate } from '../temporalChart.ts';
import { buildAgricultureRequest } from '../request.ts';
import { getProvenanceRows } from '../parse.ts';
import { groupPointsByYear } from '../yearComparison.ts';
import type { AgriculturalAnalysisResponse, ProvenanceResponse } from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const componentsDir = dirname(here);
const srcDir = dirname(dirname(componentsDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('Persian (Jalali) Date Presentation Layer', () => {
  describe('1. Pure Formatter Logic & Exact Date Conversion', () => {
    it('correctly converts known ISO dates to Jalali format', () => {
      // Standard summer dates
      assert.equal(formatPersianDate('2025-06-01'), '۱۴۰۴/۰۳/۱۱');
      assert.equal(formatPersianDate('2025-09-01'), '۱۴۰۴/۰۶/۱۰');

      // Nowruz / Vernal Equinox (1 Farvardin 1403)
      assert.equal(formatPersianDate('2024-03-20'), '۱۴۰۳/۰۱/۰۱');

      // Winter date
      assert.equal(formatPersianDate('2024-01-01'), '۱۴۰۲/۱۰/۱۱');

      // Leap year boundary check
      assert.equal(formatPersianDate('2024-02-29'), '۱۴۰۲/۱۲/۱۰');
    });

    it('anchors to UTC midday preventing timezone off-by-one shifts', () => {
      // Even if ISO date string has trailing time or is just date, the day remains exact
      assert.equal(formatPersianDate('2025-06-01'), '۱۴۰۴/۰۳/۱۱');
      assert.equal(formatPersianDate('2025-06-01T00:00:00Z'), '۱۴۰۴/۰۳/۱۱');
      assert.equal(formatPersianDate('2025-06-01T23:59:59Z'), '۱۴۰۴/۰۳/۱۱');
    });

    it('gracefully handles empty, null, undefined, and non-ISO strings', () => {
      assert.equal(formatPersianDate(null), '');
      assert.equal(formatPersianDate(undefined), '');
      assert.equal(formatPersianDate(''), '');
      assert.equal(formatPersianDate('invalid-date'), 'invalid-date');
      assert.equal(formatPersianDate('2025-99-99'), '2025-99-99');
    });

    it('formats date ranges with standard Persian separator "تا"', () => {
      const range = formatPersianDateRange('2025-06-01', '2025-09-01');
      assert.equal(range, '۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰');

      // Custom separator
      const customRange = formatPersianDateRange('2025-06-01', '2025-09-01', ' — ');
      assert.equal(customRange, '۱۴۰۴/۰۳/۱۱ — ۱۴۰۴/۰۶/۱۰');

      // Partial ranges
      assert.equal(formatPersianDateRange('2025-06-01', null), '۱۴۰۴/۰۳/۱۱');
      assert.equal(formatPersianDateRange(null, '2025-09-01'), '۱۴۰۴/۰۶/۱۰');
      assert.equal(formatPersianDateRange(null, null), '—');
      assert.equal(formatPersianDateRange('', ''), '—');
    });

    it('formats arrow-delimited or dash-delimited range strings', () => {
      assert.equal(
        formatPersianRangeString('2025-06-01 → 2025-09-01'),
        '۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰',
      );
      assert.equal(
        formatPersianRangeString('2025-06-01 to 2025-09-01'),
        '۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰',
      );
      assert.equal(formatPersianRangeString('2025-06-01'), '۱۴۰۴/۰۳/۱۱');
      assert.equal(formatPersianRangeString(''), '');
      assert.equal(formatPersianRangeString(null), '');
    });

    it('formats Persian month and year', () => {
      const formatted = formatPersianMonthYear('2025-06-01');
      assert.match(formatted, /خرداد/);
      assert.match(formatted, /۱۴۰۴/);

      const nowruz = formatPersianMonthYear('2024-03-20');
      assert.match(nowruz, /فروردین/);
      assert.match(nowruz, /۱۴۰۳/);
    });

    it('formats temporal chart short axis dates with Persian month and 2-digit year', () => {
      const short = formatShortDate('2025-06-01');
      assert.equal(short, 'خرداد ۰۴');

      const shortNowruz = formatShortDate('2024-03-20');
      assert.equal(shortNowruz, 'فروردین ۰۳');
    });
  });

  describe('2. Contract Invariance & Non-Mutation', () => {
    it('never mutates input strings or objects', () => {
      const start = '2025-06-01';
      const end = '2025-09-01';
      const mockResult: AgriculturalAnalysisResponse = {
        request_id: 'test-req',
        geometry: { type: 'Point', coordinates: [51.4, 35.7] },
        time_start: start,
        time_end: end,
        domains: ['vegetation'],
        bundles: {},
        cross_domain_statements: [],
        overall_sufficiency: 'sufficient',
        limitations: [],
      };

      const formatted = formatPersianDateRange(mockResult.time_start, mockResult.time_end);
      assert.equal(formatted, '۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰');
      // Original object remains strict Gregorian ISO
      assert.equal(mockResult.time_start, '2025-06-01');
      assert.equal(mockResult.time_end, '2025-09-01');
    });

    it('outgoing API request payload strictly preserves Gregorian ISO dates', () => {
      const req = buildAgricultureRequest({
        geometry: { type: 'Point', coordinates: [51.4, 35.7] },
        start_date: '2025-06-01',
        end_date: '2025-09-01',
        selectedDomains: ['vegetation', 'water'],
        cloud_max_percent: 20,
      });

      // API contract guarantee: Gregorian ISO YYYY-MM-DD
      assert.equal(req.start_date, '2025-06-01');
      assert.equal(req.end_date, '2025-09-01');
      assert.match(req.start_date, /^\d{4}-\d{2}-\d{2}$/);
      assert.match(req.end_date, /^\d{4}-\d{2}-\d{2}$/);
    });

    it('raw technical provenance preserves Gregorian ISO dates verbatim', () => {
      const prov: ProvenanceResponse = {
        date_start: '2024-01-01',
        date_end: '2024-06-30',
        dataset_id: 'MODIS/061/MOD11A2',
        platform_or_sensor: 'Terra',
        resolution_meters: 1000,
        pixel_count: 50,
      };

      const rows = getProvenanceRows(prov);
      const byKey = Object.fromEntries(rows.map((r) => [r.key, r.value]));
      // Must remain exact Gregorian strings for test & contract auditability
      assert.equal(byKey.date_start, '2024-01-01');
      assert.equal(byKey.date_end, '2024-06-30');
    });

    it('historical year-over-year bucketing remains intact on Gregorian months', () => {
      const samplePoints = [
        { window_start: '2023-05-01', window_end: '2023-05-31', value: 0.45 },
        { window_start: '2024-05-01', window_end: '2024-05-31', value: 0.52 },
      ];
      const grouped = groupPointsByYear(samplePoints);
      assert.equal(grouped.years.length, 2);
      assert.equal(grouped.years[0].year, '2023');
      assert.equal(grouped.years[1].year, '2024');
      assert.equal(grouped.skipped, 0);
    });
  });

  describe('3. UI Component Integration & Presentation Traceability', () => {
    it('SynthesisHeader uses formatPersianDateRange on result.time_start and result.time_end', () => {
      const code = readSource('components/agriculture/SynthesisHeader.tsx');
      assert.match(code, /import.*formatPersianDateRange.*from.*persianDate/);
      assert.match(code, /data-testid="synthesis-header-period"/);
      assert.match(code, /formatPersianDateRange\(result\.time_start,\s*result\.time_end\)/);
    });

    it('AnalysisOverviewSection uses formatPersianDateRange on result.time_start and result.time_end', () => {
      const code = readSource('components/agriculture/AnalysisOverviewSection.tsx');
      assert.match(code, /import.*formatPersianDateRange.*from.*persianDate/);
      assert.match(code, /data-testid="overview-header-period"/);
      assert.match(code, /formatPersianDateRange\(result\.time_start,\s*result\.time_end\)/);
    });

    it('DomainPage uses formatPersianDateRange on result.time_start and result.time_end', () => {
      const code = readSource('pages/agriculture/DomainPage.tsx');
      assert.match(code, /import.*formatPersianDateRange.*from.*persianDate/);
      assert.match(code, /data-testid="domain-header-period"/);
      assert.match(code, /formatPersianDateRange\(result\.time_start,\s*result\.time_end\)/);
    });

    it('SupportNotice formats observation window with Persian range while keeping ISO in data attribute', () => {
      const code = readSource('components/agriculture/SupportNotice.tsx');
      assert.match(code, /import.*formatPersianRangeString.*from.*persianDate/);
      assert.match(code, /data-iso-window=\{windowText\}/);
      assert.match(code, /formatPersianRangeString\(windowText\)/);
    });

    it('SpatialIntelligenceSection formats raster layer date range with formatPersianDateRange', () => {
      const code = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
      assert.match(code, /import.*formatPersianDateRange.*from.*persianDate/);
      assert.match(code, /data-testid="spatial-layer-period"/);
      assert.match(code, /formatPersianDateRange\(layerData\.start_date,\s*layerData\.end_date\)/);
    });

    it('AnalysisRequestForm uses JalaliDatePicker and provides pure Persian calendar inputs', () => {
      const code = readSource('components/agriculture/AnalysisRequestForm.tsx');
      assert.match(code, /JalaliDatePicker/);
      assert.match(code, /dataTestId="start-date-jalali-picker"/);
      assert.match(code, /dataTestId="end-date-jalali-picker"/);
      assert.match(code, /validateJalaliDateRange/);
    });

    it('TemporalLineChart displays Persian period in tooltip alongside ISO period', () => {
      const code = readSource('components/agriculture/TemporalLineChart.tsx');
      assert.match(code, /import.*formatPersianRangeString.*from.*persianDate/);
      assert.match(code, /rows\.push\(\['دوره \(شمسی\)', formatPersianRangeString\(datum\.period\)\]\)/);
      assert.match(code, /rows\.push\(\['Period \(ISO\)', datum\.period\]\)/);
    });

    it('zero hardcoded runtime dates or mock data in persianDate utility', () => {
      const code = readSource('components/agriculture/persianDate.ts');
      // No mock data or artificial test dates hardcoded
      assert.doesNotMatch(code, /mock/i);
      assert.doesNotMatch(code, /synthetic/i);
      assert.doesNotMatch(code, /fake/i);
    });
  });

  describe('4. Central Date Conversion & Validation Architecture (P-AGRI-DSS-2)', () => {
    it('converts Jalali to Gregorian accurately across boundaries and leap years', () => {
      // Nowruz 1404
      assert.deepEqual(jalaliToGregorian(1404, 1, 1), { gy: 2025, gm: 3, gd: 21 });
      // Summer dates
      assert.deepEqual(jalaliToGregorian(1404, 3, 11), { gy: 2025, gm: 6, gd: 1 });
      assert.deepEqual(jalaliToGregorian(1404, 6, 10), { gy: 2025, gm: 9, gd: 1 });
      // Jalali Leap year 1403 (Esfand has 30 days)
      assert.equal(isJalaliLeapYear(1403), true);
      assert.equal(getJalaliMonthDays(1403, 12), 30);
      assert.deepEqual(jalaliToGregorian(1403, 12, 30), { gy: 2025, gm: 3, gd: 20 });
      // Non-leap year 1404 (Esfand has 29 days)
      assert.equal(isJalaliLeapYear(1404), false);
      assert.equal(getJalaliMonthDays(1404, 12), 29);
      // Month boundary: Shahrivar 31 to Mehr 1
      assert.deepEqual(jalaliToGregorian(1404, 6, 31), { gy: 2025, gm: 9, gd: 22 });
      assert.deepEqual(jalaliToGregorian(1404, 7, 1), { gy: 2025, gm: 9, gd: 23 });
    });

    it('converts Gregorian to Jalali accurately', () => {
      assert.deepEqual(gregorianToJalali(2025, 6, 1), { jy: 1404, jm: 3, jd: 11 });
      assert.deepEqual(gregorianToJalali(2025, 9, 1), { jy: 1404, jm: 6, jd: 10 });
      assert.deepEqual(gregorianToJalali(2024, 3, 20), { jy: 1403, jm: 1, jd: 1 });
      assert.deepEqual(gregorianToJalali(2025, 3, 20), { jy: 1403, jm: 12, jd: 30 });
    });

    it('formats Gregorian for API payload strictly in ISO YYYY-MM-DD', () => {
      assert.equal(formatGregorianForApi('1404/03/11'), '2025-06-01');
      assert.equal(formatGregorianForApi('1404/06/10'), '2025-09-01');
      assert.equal(formatGregorianForApi('۱۴۰۴/۰۳/۱۱'), '2025-06-01');
      assert.equal(formatGregorianForApi({ jy: 1404, jm: 3, jd: 11 }), '2025-06-01');
    });

    it('validates date ranges rejecting invalid dates, same dates, reversed dates, and excessive ranges', () => {
      // Valid range
      const valid = validateJalaliDateRange('1404/03/11', '1404/06/10');
      assert.equal(valid.isValid, true);
      assert.equal(valid.startGregorian, '2025-06-01');
      assert.equal(valid.endGregorian, '2025-09-01');

      // Invalid date format/values
      const invalidDate = validateJalaliDateRange('1404/13/40', '1404/06/10');
      assert.equal(invalidDate.isValid, false);
      assert.match(invalidDate.errorFa!, /نامعتبر/);

      // Same date (minimum 1 day difference required)
      const sameDate = validateJalaliDateRange('1404/03/11', '1404/03/11');
      assert.equal(sameDate.isValid, false);
      assert.match(sameDate.errorFa!, /یکسان/);

      // Reversed dates (start > end)
      const reversed = validateJalaliDateRange('1404/06/10', '1404/03/11');
      assert.equal(reversed.isValid, false);
      assert.match(reversed.errorFa!, /قبل از تاریخ شروع/);

      // Exceeding MAX_TEMPORAL_MONTHS (e.g. 50 months)
      const excessive = validateJalaliDateRange('1400/01/01', '1405/01/01', 36);
      assert.equal(excessive.isValid, false);
      assert.match(excessive.errorFa!, /بیش از حد مجاز/);
    });
  });
});

