import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

describe('PHASE 3 CLOSE-OUT: V1, V2, V7 UI Requirements', () => {
  const pagePath = path.resolve('src/pages/agriculture/FrostRiskPage.tsx');
  const pageSource = fs.readFileSync(pagePath, 'utf-8');
  const typesPath = path.resolve('src/types/frost.ts');
  const typesSource = fs.readFileSync(typesPath, 'utf-8');

  it('V1: Single source of truth factor resolution mapping is complete and strictly adheres to requirements', () => {
    // Check types/frost.ts contains canonical FACTOR_RESOLUTION_MAP and FACTOR_SOURCE_FA_MAP
    assert.ok(typesSource.includes('export const FACTOR_RESOLUTION_MAP'), 'Must export FACTOR_RESOLUTION_MAP');
    assert.ok(typesSource.includes('export const FACTOR_SOURCE_FA_MAP'), 'Must export FACTOR_SOURCE_FA_MAP');

    // GFS rows must be ~۲۸ کیلومتر
    assert.ok(typesSource.includes("temperature_duration: '~۲۸ کیلومتر'"), 'temperature_duration must be ~۲۸ کیلومتر');
    assert.ok(typesSource.includes("wind_speed: '~۲۸ کیلومتر'"), 'wind_speed must be ~۲۸ کیلومتر');
    assert.ok(typesSource.includes("wind_direction: '~۲۸ کیلومتر'"), 'wind_direction must be ~۲۸ کیلومتر');
    assert.ok(typesSource.includes("cloud_cover: '~۲۸ کیلومتر'"), 'cloud_cover must be ~۲۸ کیلومتر');
    assert.ok(typesSource.includes("humidity_dewpoint: '~۲۸ کیلومتر'"), 'humidity_dewpoint must be ~۲۸ کیلومتر');

    // SMAP / ERA5-Land soil moisture
    assert.ok(typesSource.includes("soil_rootzone_moisture: '~۹–۱۱ کیلومتر'"), 'soil_rootzone_moisture must be ~۹–۱۱ کیلومتر');

    // SoilGrids 250m
    assert.ok(typesSource.includes("soil_texture_depth: '۲۵۰ متر'"), 'soil_texture_depth must be ۲۵۰ متر');

    // DEM 30m
    assert.ok(typesSource.includes("topography_pooling: '۳۰ متر'"), 'topography_pooling must be ۳۰ متر');
    assert.ok(typesSource.includes("topography_slope_aspect: '۳۰ متر'"), 'topography_slope_aspect must be ۳۰ متر');

    // Farmer
    assert.ok(typesSource.includes("phenological_stage: 'داده باغدار'"), 'phenological_stage must be داده باغدار');
  });

  it('V1 & V7: Factor table reads resolution and Persian source names from single mapping', () => {
    assert.ok(pageSource.includes('FACTOR_RESOLUTION_MAP'), 'Must reference FACTOR_RESOLUTION_MAP in FrostRiskPage');
    assert.ok(pageSource.includes('FACTOR_SOURCE_FA_MAP'), 'Must reference FACTOR_SOURCE_FA_MAP in FrostRiskPage');
    assert.ok(pageSource.includes('title={f.source_module}'), 'Must put source_module in tooltip only');
  });

  it('V2: Detail Card Header displays applied critical temperature with stale stage note', () => {
    assert.ok(
      pageSource.includes('data-testid="detail-applied-critical-temp"'),
      'Must have detail-applied-critical-temp testid',
    );
    assert.ok(
      pageSource.includes('دمای بحرانی اعمال‌شده:'),
      'Must use explicit title: دمای بحرانی اعمال‌شده:',
    );
    assert.ok(
      pageSource.includes('data-testid="detail-stale-stage-critical-temp-note"'),
      'Must have detail-stale-stage-critical-temp-note testid',
    );
    assert.ok(
      pageSource.includes('(به‌دلیل انقضای مرحله، حساس‌ترین مرحله اعمال شده است)'),
      'Must show explicit explanation when stage is stale',
    );
  });

  it('V7: Persian dates, summary text, and mobile card layout', () => {
    // Summary table zero-threshold text
    assert.ok(
      pageSource.includes('بدون ساعت زیر آستانه'),
      'Must display بدون ساعت زیر آستانه in overview table',
    );
    // Jalali / Persian date formatting
    assert.ok(
      pageSource.includes('formatPersianDate'),
      'Must include formatPersianDate helper',
    );
    assert.ok(
      pageSource.includes('formatNightDisplayFa'),
      'Must include formatNightDisplayFa helper',
    );
    // Mobile cards
    assert.ok(
      pageSource.includes('data-testid="orchards-mobile-cards"'),
      'Must render mobile cards wrapper with testid orchards-mobile-cards',
    );
    assert.ok(
      pageSource.includes('orchard-mobile-card-'),
      'Must render individual mobile cards',
    );
    assert.ok(
      pageSource.includes('orchards-desktop-table-wrapper'),
      'Must separate desktop table with class orchards-desktop-table-wrapper',
    );
  });
});
