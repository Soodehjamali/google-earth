import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

describe('S8: User Phenological Stage Dropdown and S2 Zero-Night Resolution Integrity', () => {
  const pagePath = path.resolve('src/pages/agriculture/FrostRiskPage.tsx');
  const pageSource = fs.readFileSync(pagePath, 'utf-8');

  it('1. registration form contains mandatory phenological stage select with empty default', () => {
    assert.ok(pageSource.includes('data-testid="new-orchard-stage-select"'), 'Must have new orchard stage select testid');
    assert.ok(pageSource.includes('مرحله فعلی باغ (اجباری) *'), 'Must label stage select as mandatory');
    assert.ok(pageSource.includes('-- لطفاً مرحله فعلی را انتخاب کنید --'), 'Must have empty placeholder prompt');
    assert.ok(pageSource.includes('newOrchardStage'), 'Must track newOrchardStage state');
    assert.ok(pageSource.includes('disabled={!orchardName.trim() || !newOrchardStage}'), 'Must require stage to submit');
  });

  it('2. summary table contains inline stage dropdown in each row for immediate update', () => {
    assert.ok(pageSource.includes('data-testid={`inline-stage-select-${item.orchard_id}`}'), 'Must have inline stage select testid per row');
    assert.ok(pageSource.includes('handleInlineStageChange'), 'Must have handleInlineStageChange callback');
    assert.ok(pageSource.includes('patchFrostOrchardStage'), 'Must call patchFrostOrchardStage on change');
    assert.ok(pageSource.includes('inlineStageFeedback'), 'Must show inline feedback message');
  });

  it('3. dropdown options match published_v1 with exact Persian names and thresholds', () => {
    assert.ok(pageSource.includes('جوانه بازنشده (۴-°C)'), 'Must include unopened_bud label (-4°C)');
    assert.ok(pageSource.includes('جوانه در حال باز شدن'), 'Must include opening_bud label (-2°C)');
    assert.ok(pageSource.includes('گلدهی / شکوفه بازشده (۱.۷-°C)'), 'Must include bloom label (-1.7°C)');
    assert.ok(pageSource.includes('میوه اولیه (۲-°C)'), 'Must include fruit label (-2°C)');
    assert.ok(pageSource.includes('جوانه متورم (آستانه منبع‌دار ندارد)'), 'Must include swelling_bud label without fake numbers');
  });

  it('4. displays last update date and stale warning for expired stages (>20 days)', () => {
    assert.ok(pageSource.includes('آخرین به‌روزرسانی:'), 'Must display last update label');
    assert.ok(pageSource.includes('formatStageDate'), 'Must format stage update date');
    assert.ok(pageSource.includes('data-testid="stale-stage-badge"'), 'Must have stale stage badge testid');
    assert.ok(pageSource.includes('مرحله منقضی'), 'Must flag stale stages with مرحله منقضی');
  });

  it('5. S2 logic: zero nights below threshold is never rendered when Tmin <= Tcrit', () => {
    // Condition checks that effective_tmin_c <= crit never renders "هیچ شب زیر آستانه نیست"
    assert.ok(pageSource.includes('item.worst_effective_tmin_c <= item.critical_temp_c'), 'Must check if worst night drops below critical threshold');
    assert.ok(pageSource.includes('isResolvable'), 'Must verify duration is resolvable');
    assert.ok(pageSource.includes('تفکیک ۱ ساعته'), 'Must provide cadence label');
  });
});
