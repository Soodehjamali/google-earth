/**
 * P1 focused tests — year-over-year NDVI comparison over the
 * existing comprehensive temporal payload.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/t54.test.ts
 * Covers pure year grouping (multiple years, single year, nulls,
 * misdated records, no fabrication), the history config wiring,
 * and static guards (no new requests, no verdicts, no thresholds).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import {
  MIN_COMPARABLE_YEARS,
  canCompareYears,
  comparableYears,
  groupPointsByYear,
  ndviProfileOf,
} from '../yearComparison.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

function point(windowStart: string, value: number | null) {
  return {
    window_start: windowStart,
    window_end: `${windowStart.slice(0, 7)}-28`,
    value,
    unit: 'index',
    quality: value === null ? 'insufficient' : 'good',
    coverage_percent: value === null ? 0 : 100,
    image_count: 4,
  };
}

function temporalWith(points: unknown[]) {
  return {
    profiles: {
      ndvi: {
        metric_key: 'ndvi',
        unit: 'index',
        window_start: '2024-01-01',
        window_end: '2026-12-31',
        step: 'calendar_month',
        points,
      },
    },
  };
}

// --- 1-2. Grouping and the two-year boundary ------------------------------------

describe('1-2. year grouping and comparability', () => {
  it('1. multiple years produce multiple ascending groups', () => {
    const grouped = groupPointsByYear([
      point('2025-03-01', 0.5),
      point('2024-01-01', 0.6),
      point('2026-06-01', 0.7),
    ]);
    assert.deepEqual(grouped.years.map((series) => series.year), [
      '2024',
      '2025',
      '2026',
    ]);
    assert.equal(grouped.skipped, 0);
    assert.equal(canCompareYears(grouped), true);
  });

  it('2. a single year yields the honest incomplete state', () => {
    const grouped = groupPointsByYear([point('2024-01-01', 0.6)]);
    assert.equal(comparableYears(grouped).length, 1);
    assert.equal(canCompareYears(grouped), false);
    assert.equal(MIN_COMPARABLE_YEARS, 2);
  });
});

// --- 3-5. Nulls, dates, no fabrication ----------------------------------------------

describe('3-5. gaps, dates, and no fabricated values', () => {
  it('3. missing and null observations stay gaps', () => {
    const grouped = groupPointsByYear([
      point('2024-01-01', null),
      point('2024-02-01', 0.6),
    ]);
    const months = grouped.years[0]?.months ?? [];
    assert.equal(months.find((slot) => slot.month === '01')?.value, null);
    assert.equal(months.find((slot) => slot.month === '02')?.value, 0.6);
    assert.ok(!months.some((slot) => slot.value === 0));
  });

  it('4. dates group into the correct calendar years and months', () => {
    const grouped = groupPointsByYear([
      point('2024-12-01', 0.4),
      point('2025-01-01', 0.5),
    ]);
    assert.equal(grouped.years[0]?.months[0]?.month, '12');
    assert.equal(grouped.years[0]?.months[0]?.label, 'Dec');
    assert.equal(grouped.years[1]?.months[0]?.month, '01');
    assert.equal(grouped.years[1]?.months[0]?.label, 'Jan');
  });

  it('5. malformed records are skipped, never fabricated', () => {
    const grouped = groupPointsByYear([
      point('2024-01-01', 0.6),
      { window_start: 'not-a-date', value: 0.9 },
      { value: 0.9 },
      null,
      'junk',
    ]);
    assert.equal(grouped.years.length, 1);
    assert.equal(grouped.skipped, 4);
    assert.deepEqual(comparableYears(grouped).length, 1);
  });

  it('non-finite values become gaps', () => {
    const grouped = groupPointsByYear([
      { window_start: '2024-01-01', value: Number.NaN },
      { window_start: '2024-02-01', value: Number.POSITIVE_INFINITY },
      { window_start: '2024-03-01', value: '0.6' },
    ]);
    assert.deepEqual(
      grouped.years[0]?.months.map((slot) => slot.value),
      [null, null, null],
    );
    assert.equal(comparableYears(grouped).length, 0);
  });
});

// --- Profile narrowing -----------------------------------------------------------------

describe('profile narrowing reads the existing contract only', () => {
  it('ndvi profile resolves with points and unit', () => {
    const profile = ndviProfileOf(temporalWith([point('2024-01-01', 0.6)]));
    assert.ok(profile);
    assert.equal(profile?.unit, 'index');
    assert.equal(profile?.points.length, 1);
  });

  it('absent ndvi profile yields null, never a substitute', () => {
    assert.equal(ndviProfileOf(null), null);
    assert.equal(ndviProfileOf({}), null);
    assert.equal(ndviProfileOf({ profiles: {} }), null);
    assert.equal(ndviProfileOf({ profiles: { ndmi: {} } }), null);
  });
});

// --- 6-7. History wiring, no new requests -------------------------------------------------

describe('6-7. history wiring without new requests', () => {
  it('6. history config keeps existing sections and adds the comparison', () => {
    const history = DOMAIN_PAGE_CONFIGS.history;
    assert.ok(history);
    const kinds = history.sections.map((section) => section.kind);
    assert.ok(kinds.includes('kpi'));
    const comparison = history.sections.find(
      (section) => section.kind === 'year-comparison',
    );
    assert.ok(comparison);
    assert.deepEqual(comparison?.metricKeys, ['ndvi']);
  });

  it('7. no additional API request is introduced', () => {
    for (const file of [
      'components/agriculture/yearComparison.ts',
      'components/agriculture/YearComparisonSection.tsx',
      'pages/agriculture/DomainPage.tsx',
    ]) {
      const source = readSource(file);
      assert.ok(!source.includes('agricultureApi'), file);
      assert.ok(!source.includes('fetch('), file);
      assert.ok(!source.includes('/analysis'), file);
    }
    const page = readSource('pages/agriculture/DomainPage.tsx');
    assert.ok(page.includes('ndviProfileOf(result.temporal'));
  });

  it('existing history data remains visible', () => {
    const history = DOMAIN_PAGE_CONFIGS.history;
    assert.ok(history);
    assert.ok(
      history.sections.some((section) => section.id === 'anomalies'),
    );
    assert.ok(
      history.sections.some((section) => section.id === 'change'),
    );
    assert.ok(
      history.sections.some((section) => section.id === 'climate-season'),
    );
  });
});

// --- Safeguards -------------------------------------------------------------------------------

describe('safeguards: descriptive comparison only', () => {
  it('no thresholds, verdicts, rankings, or best-year logic', () => {
    for (const file of [
      'components/agriculture/yearComparison.ts',
      'components/agriculture/YearComparisonSection.tsx',
    ]) {
      const source = readSource(file);
      const stripped = source
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|\s)\/\/.*$/gm, '$1');
      assert.ok(!/best\b/i.test(stripped), file);
      assert.ok(!/rank/i.test(stripped), file);
      assert.ok(!/threshold/i.test(stripped), file);
      assert.ok(!/health|disease|pest|stress/i.test(stripped), file);
      assert.ok(!/correct|wrong|winner/i.test(stripped), file);
      assert.ok(!/accuracy|precision|recall|confidence|probability/i.test(stripped), file);
      assert.ok(!/mean\s*\(|median\s*\(|average/i.test(stripped), file);
    }
  });

  it('no interpolation or gap filling', () => {
    const helper = readSource('components/agriculture/yearComparison.ts');
    assert.ok(!/interpolat/i.test(helper));
    const component = readSource('components/agriculture/YearComparisonSection.tsx');
    assert.ok(component.includes('connectNulls={false}'));
  });
});
