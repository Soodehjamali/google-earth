import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

describe('Phase 3 Redesign v2 Item R7: Published Threshold Set Fix and Dynamic Stages', () => {
  const pagePath = path.resolve('src/pages/agriculture/FrostRiskPage.tsx');
  const pageSource = fs.readFileSync(pagePath, 'utf-8');

  const configPath = path.resolve('../config/frost_thresholds.yaml');
  const configSource = fs.readFileSync(configPath, 'utf-8');

  it('1. published_v1 defines only sourced stages with single critical temperatures in config', () => {
    assert.ok(configSource.includes('single_critical: true'), 'Must declare single_critical: true in published_v1');
    assert.ok(configSource.includes('t_critical_90_c: null'), 'Must set t_critical_90_c to null in published_v1');

    // unopened_bud (-4 C)
    assert.ok(configSource.includes('unopened_bud:'), 'Must define unopened_bud');
    assert.ok(configSource.includes('t_critical_c: -4.0'), 'Must set unopened_bud t_critical_c to -4.0');

    // opening_bud (-2 C) with (Opening bud) label
    assert.ok(
      configSource.includes('name_fa: "جوانه در حال باز شدن (Opening bud)"'),
      'Must verify opening_bud label is "جوانه در حال باز شدن (Opening bud)"',
    );
    assert.ok(configSource.includes('t_critical_c: -2.0'), 'Must set opening_bud t_critical_c to -2.0');

    // bloom (-1.7 C)
    assert.ok(configSource.includes('t_critical_c: -1.7'), 'Must set bloom t_critical_c to -1.7');

    // swelling_bud is null with explicit missing note
    assert.ok(
      configSource.includes('در منبع S2 هیچ رقمی برای مرحله تورم جوانه ذکر نشده است (داده منتشرشده‌ای وجود ندارد).'),
      'Must contain verbatim missing data note for swelling_bud',
    );
  });

  it('2. UI defines PUBLISHED_V1_STAGES with sourced critical numbers and swelling_bud disabled', () => {
    assert.ok(pageSource.includes('PUBLISHED_V1_STAGES'), 'Must define PUBLISHED_V1_STAGES');
    assert.ok(pageSource.includes('unopened_bud'), 'Must contain unopened_bud');
    assert.ok(pageSource.includes('opening_bud'), 'Must contain opening_bud');
    assert.ok(pageSource.includes('Opening bud'), 'Must include Opening bud in stage label');
    assert.ok(pageSource.includes('bloom'), 'Must contain bloom');
    assert.ok(pageSource.includes('fruit'), 'Must contain fruit');
    assert.ok(pageSource.includes('swelling_bud'), 'Must contain swelling_bud');
    assert.ok(pageSource.includes('disabled: true'), 'Must disable swelling_bud in published_v1');
  });

  it('3. UI stage dropdown reflects active threshold set and drops T90 for published_v1', () => {
    // Stage dropdown reflects currentStageOptions
    assert.ok(pageSource.includes('currentStageOptions'), 'Must compute currentStageOptions');
    assert.ok(pageSource.includes('data-testid="stage-select-dropdown"'), 'Must have stage select dropdown testid');
    assert.ok(pageSource.includes('data-testid="threshold-set-select"'), 'Must have threshold set select testid');
    assert.ok(pageSource.includes('handleThresholdSetChange'), 'Must switch stages on threshold set change');

    // Missing swelling bud note rendered when selected
    assert.ok(
      pageSource.includes('data-testid="swelling-bud-missing-note"'),
      'Must have swelling bud missing note testid',
    );
    assert.ok(
      pageSource.includes('در منبع S2 هیچ رقمی برای مرحله تورم جوانه ذکر نشده است (داده منتشرشده‌ای وجود ندارد)'),
      'Must render verbatim Persian missing data note',
    );

    // T90 dropped when published_v1 / single_critical
    assert.ok(
      pageSource.includes('thresholdSet === \'published_v1\') ? undefined'),
      'Must drop critical_temp_90_c when published_v1 is active',
    );
  });
});
