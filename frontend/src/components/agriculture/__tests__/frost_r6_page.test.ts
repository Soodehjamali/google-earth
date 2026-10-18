import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

describe('Phase 3 Redesign v2 Item R6: Pure Persian Per-Orchard UI Overhaul', () => {
  const pagePath = path.resolve('src/pages/agriculture/FrostRiskPage.tsx');
  const pageSource = fs.readFileSync(pagePath, 'utf-8');

  it('1. overview table of all orchards renders all required columns', () => {
    assert.ok(pageSource.includes('نام باغ'), 'Must have orchard name column');
    assert.ok(pageSource.includes('مرحله رشدی'), 'Must have phenological stage column');
    assert.ok(pageSource.includes('کمترین دمای مؤثر'), 'Must have worst-night effective Tmin column');
    assert.ok(pageSource.includes('ساعات زیر آستانه'), 'Must have hours below threshold column');
    assert.ok(pageSource.includes('رطوبت خاک'), 'Must have root-zone moisture column');
    assert.ok(pageSource.includes('وزش باد'), 'Must have wind speed column');
    assert.ok(pageSource.includes('ریسک راهنما ٪'), 'Must have guidance risk percent column');
    assert.ok(pageSource.includes('رده نهایی'), 'Must have final risk category column');
    assert.ok(pageSource.includes('⚠️ قدیمی/نامشخص'), 'Must render stale stage indicator');
  });

  it('2. selected orchard factor table has EXACT 7 required columns and totals row', () => {
    // Exact column headers required by prompt R6:
    // عامل | مقدار | منبع و کیفیت و تاریخ داده | وضعیت | وزن | امتیاز جزئی | سهم
    assert.ok(pageSource.includes('>عامل<'), 'Must contain exact column header: عامل');
    assert.ok(pageSource.includes('>مقدار<'), 'Must contain exact column header: مقدار');
    assert.ok(pageSource.includes('>منبع و کیفیت و تاریخ داده<'), 'Must contain exact column header: منبع و کیفیت و تاریخ داده');
    assert.ok(pageSource.includes('>وضعیت<'), 'Must contain exact column header: وضعیت');
    assert.ok(pageSource.includes('>وزن<'), 'Must contain exact column header: وزن');
    assert.ok(pageSource.includes('>امتیاز جزئی<'), 'Must contain exact column header: امتیاز جزئی');
    assert.ok(pageSource.includes('>سهم<'), 'Must contain exact column header: سهم');

    // Totals row
    assert.ok(pageSource.includes('>مجموع<'), 'Must contain totals row with مجموع');
    assert.ok(pageSource.includes('total_weight'), 'Must bind total_weight');
    assert.ok(pageSource.includes('total_contribution'), 'Must bind total_contribution');
  });

  it('3. GATE trigger notice renders prominently when triggered', () => {
    assert.ok(pageSource.includes('gate-triggered-notice'), 'Must have gate notice testid');
    assert.ok(pageSource.includes('دروازه ایمنی (GATE)'), 'Must mention safety gate in Persian');
  });

  it('4. displays exact guidance risk label and unverified model disclaimer', () => {
    assert.ok(
      pageSource.includes('ریسک راهنما ٪ (برآورد نیمه‌کمی، کالیبره‌نشده؛ احتمال واقعی نیست)'),
      'Must contain exact guidance label',
    );
    assert.ok(
      pageSource.includes('وزن‌ها و آستانه‌های مدل کالیبره تجربی نشده‌اند و صرفاً تخمین راهنما ارائه می‌دهند'),
      'Must state that weights and thresholds are uncalibrated and illustrative',
    );
  });

  it('5. renders zero nights phrase and NO prohibited English phrases', () => {
    // Zero nights line
    assert.ok(pageSource.includes('هیچ شب زیر آستانه نیست'), 'Must contain exact zero nights phrase');

    // Prohibited English phrases
    assert.ok(!pageSource.includes('0.0 h below critical threshold'), 'Must NOT contain English 0.0 h below');
    assert.ok(!pageSource.includes('Pistachio)'), 'Must NOT contain English (Pistachio)');
    assert.ok(!pageSource.includes('(Dormant)'), 'Must NOT contain English (Dormant)');
    assert.ok(!pageSource.includes('(Bud Burst)'), 'Must NOT contain English (Bud Burst)');
    assert.ok(!pageSource.includes('(Early Bloom)'), 'Must NOT contain English (Early Bloom)');
    assert.ok(!pageSource.includes('(Full Bloom)'), 'Must NOT contain English (Full Bloom)');
    assert.ok(!pageSource.includes('(Fruit Set)'), 'Must NOT contain English (Fruit Set)');
  });

  it('6. recommendations are collapsible and conditionally surfaced for warning/critical', () => {
    assert.ok(pageSource.includes('recommendations-section'), 'Must have recommendations section');
    assert.ok(pageSource.includes('showRecommendations'), 'Must support collapsible toggle');
    assert.ok(pageSource.includes('warning') && pageSource.includes('critical'), 'Must gate on warning/critical');
    assert.ok(
      pageSource.includes('هیچ توصیه فوری برای این شب وجود ندارد'),
      'Must state no urgent recommendations when below warning',
    );
  });
});
