import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

describe('Phase 3 Redesign v2 Item R8: Source Honesty Banner and Native Unsmoothed Chart', () => {
  const chartPath = path.resolve('src/components/agriculture/frost/FrostTimelineChart.tsx');
  const chartSource = fs.readFileSync(chartPath, 'utf-8');

  const pagePath = path.resolve('src/pages/agriculture/FrostRiskPage.tsx');
  const pageSource = fs.readFileSync(pagePath, 'utf-8');

  it('1. eliminates artificial spline smoothing and renders native linear connects', () => {
    // Assert NO type="monotone" in FrostTimelineChart
    assert.ok(
      !chartSource.includes('type="monotone"'),
      'Must NOT use type="monotone" cubic spline interpolation in chart lines or area',
    );

    // Assert type="linear" is used
    assert.ok(
      chartSource.includes('type="linear"'),
      'Must use type="linear" to connect native points without artificial overshoot or dipping',
    );

    // Assert native points are drawn on the main forecast line
    assert.ok(
      chartSource.includes('dot={{ r: 2.5, fill: \'#2563eb\' }}'),
      'Main forecast line must render native discrete forecast points',
    );
  });

  it('2. renders source honesty banner when fake forecast provider is detected', () => {
    // Banner presence and exact Persian warning text from prompt
    assert.ok(
      pageSource.includes('data-testid="fake-provider-honesty-banner"'),
      'Must render fake-provider-honesty-banner',
    );
    assert.ok(
      pageSource.includes('داده شبیه‌سازی‌شده؛ برای تصمیم استفاده نشود'),
      'Must display exact verbatim warning: داده شبیه‌سازی‌شده؛ برای تصمیم استفاده نشود',
    );

    // Source honesty detection logic
    assert.ok(
      pageSource.includes('isFakeForecastUsed'),
      'Must check whether fake provider is used across orchards or ad-hoc assessment',
    );
    assert.ok(
      pageSource.includes('deterministic_fake'),
      'Must identify deterministic_fake source key',
    );
  });
});
