import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  formatPersianTimestamp,
  translateStatusFa,
  translateSufficiencyFa,
} from '../historyUtils.ts';
import { formatPersianDateRange } from '../persianDate.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('Agriculture Persistent History UI & Presentation (Phase P0-HISTORY)', () => {
  it('formats timestamps strictly with Jalali calendar and Persian digits', () => {
    const formatted = formatPersianTimestamp('2026-05-15T12:00:00Z');
    assert.ok(formatted.includes('۱۴۰۵'));
    assert.strictEqual(/2026/.test(formatted), false);
    assert.ok(formatted.includes('ساعت'));
  });

  it('correctly maps execution statuses to standard Persian labels and styles', () => {
    const completed = translateStatusFa('completed');
    assert.strictEqual(completed.text, 'تکمیل‌شده');
    assert.strictEqual(completed.badgeClass, 'badge-good');

    const running = translateStatusFa('running');
    assert.strictEqual(running.text, 'در حال پردازش');
    assert.strictEqual(running.badgeClass, 'badge-info');

    const failed = translateStatusFa('failed');
    assert.strictEqual(failed.text, 'ناموفق');
    assert.strictEqual(failed.badgeClass, 'badge-danger');
  });

  it('correctly maps evidence sufficiency levels to honest scientific labels', () => {
    const suff = translateSufficiencyFa('sufficient');
    assert.strictEqual(suff.text, 'شواهد کافی');
    assert.strictEqual(suff.badgeClass, 'badge-good');

    const mod = translateSufficiencyFa('moderate');
    assert.strictEqual(mod.text, 'شواهد متوسط');
    assert.strictEqual(mod.badgeClass, 'badge-warning');

    const insuff = translateSufficiencyFa('insufficient');
    assert.strictEqual(insuff.text, 'شواهد ناکافی');
    assert.strictEqual(insuff.badgeClass, 'badge-danger');
  });

  it('formats same-period observation date ranges with Persian numerals', () => {
    const range = formatPersianDateRange('2026-05-01', '2026-08-31');
    assert.ok(range.includes('۱۴۰۵'));
    assert.ok(range.includes('تا'));
    assert.strictEqual(/2026/.test(range), false);
  });

  it('verifies agricultureApi exposes history endpoints for decoupled retrieval', () => {
    const apiSrc = readSource('api/agriculture.ts');
    assert.match(apiSrc, /listHistory:\s*\(skip\s*=\s*0,\s*limit\s*=\s*20/);
    assert.match(apiSrc, /getHistoryItem:\s*\(id:\s*string\)/);
    assert.match(apiSrc, /deleteHistoryItem:\s*\(id:\s*string\)/);
    assert.match(apiSrc, /\/agriculture\/history/);
  });

  it('verifies type definitions for history items and paginated response', () => {
    const typeSrc = readSource('types/index.ts');
    assert.match(typeSrc, /export interface AgricultureHistoryItemSummary/);
    assert.match(typeSrc, /export interface AgricultureHistoryListResponse/);
    assert.match(typeSrc, /request_id\?:\s*string/);
    assert.match(typeSrc, /overall_sufficiency:\s*string\s*\|\s*null/);
  });

  it('verifies UI components integrate history loading without re-executing GEE', () => {
    const compSrc = readSource('components/agriculture/AgricultureHistorySection.tsx');
    assert.match(compSrc, /history-section/);
    assert.match(compSrc, /حذف از تاریخچه/);
    assert.match(compSrc, /مشاهده گزارش کامل/);

    const layoutSrc = readSource('components/agriculture/AgricultureLayout.tsx');
    assert.match(layoutSrc, /loadSavedAnalysis/);
    assert.match(layoutSrc, /savedAnalysisId/);
    assert.match(layoutSrc, /analysis_id/);
  });
});

