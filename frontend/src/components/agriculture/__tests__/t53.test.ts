/**
 * P5.3 focused tests — real temporal payloads render through the
 * P5.2 chart layer without new computation.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/t53.test.ts
 * Fixtures mirror the backend TemporalSectionModel to_dict shapes
 * produced by the /analysis temporal section.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  anomalyFor,
  attachAnomalies,
  attachChanges,
  baselineLevels,
  changeFor,
  concordanceMonths,
  mapProfilePoints,
  orientationFor,
  payloadPoints,
  persistenceSummary,
  profileFor,
  relationshipFor,
} from '../temporalChart.ts';

const WINDOWS = [
  ['2024-01-01', '2024-01-31'],
  ['2024-02-01', '2024-02-29'],
  ['2024-03-01', '2024-03-31'],
  ['2024-04-01', '2024-04-30'],
];

function point(window: string[], value: number | null, unit: string) {
  return {
    window_start: window[0],
    window_end: window[1],
    value,
    unit,
    quality: value === null ? 'insufficient' : 'good',
    coverage_percent: value === null ? 0 : 100,
    image_count: 4,
  };
}

const NDVI_PROFILE = {
  metric_key: 'ndvi',
  dataset_id: 'COPERNICUS/S2_SR_HARMONIZED',
  unit: 'index',
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  step: 'calendar_month',
  points: [0.6, null, 0.7, 0.65].map((value, i) =>
    point(WINDOWS[i] as string[], value, 'index'),
  ),
};

const NDVI_ANOMALY = {
  metric_key: 'ndvi',
  unit: 'index',
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  step: 'calendar_month',
  baseline: {
    metric_key: 'ndvi',
    strategy: 'full_period',
    n_observations: 4,
    n_usable: 3,
    mean: 0.65,
    std: 0.05,
    minimum: 0.6,
    maximum: 0.7,
    median: 0.65,
  },
  points: [
    { ...point(WINDOWS[0] as string[], 0.6, 'index'), z_score: -1.0, percentile: null, category: 'BELOW_BASELINE' },
    { ...point(WINDOWS[1] as string[], null, 'index'), z_score: null, percentile: null, category: 'INSUFFICIENT_BASELINE' },
    { ...point(WINDOWS[2] as string[], 0.7, 'index'), z_score: 1.0, percentile: null, category: 'ABOVE_BASELINE' },
    { ...point(WINDOWS[3] as string[], 0.65, 'index'), z_score: 0.0, percentile: null, category: 'NORMAL' },
  ],
};

const NDVI_CHANGE = {
  metric_key: 'ndvi',
  unit: 'index',
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  step: 'calendar_month',
  changes: [
    {
      window_start: '2024-04-01', window_end: '2024-04-30', value: 0.65,
      previous_window_start: '2024-03-01', previous_window_end: '2024-03-31',
      previous_value: 0.7, absolute_change: -0.05,
      relative_change: -0.0714, days_elapsed: 31,
      rate_per_day: -0.0016, direction: 'DECREASE', rapid: 'NOT_RAPID',
      z_score: 0.0, percentile: null, unit: 'index', quality: 'good',
      coverage_percent: 100, image_count: 4,
    },
  ],
  persistence: {
    longest_run_below: 1, longest_run_above: 1, n_anomalous: 2,
    n_observed: 3, n_missing: 1, state: 'NO_PERSISTENCE',
  },
};

const VV_PROFILE = {
  metric_key: 'vv',
  dataset_id: 'COPERNICUS/S1_GRD',
  unit: 'dB',
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  step: 'calendar_month',
  points: [-8.0, -8.5, -9.0, -8.2].map((value, i) =>
    point(WINDOWS[i] as string[], value, 'dB'),
  ),
};

const LST_PROFILE = {
  profile_kind: 'LST_PROFILE',
  metric_key: 'land_surface_temperature_day',
  dataset_id: 'MODIS/061/MOD11A2',
  band: 'LST_Day_1km',
  unit: 'degC',
  physical_quantity: 'land_surface_temperature',
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  step: 'calendar_month',
  points: [26.0, 27.0, 28.0, 29.0].map((value, i) =>
    point(WINDOWS[i] as string[], value, 'degC'),
  ),
};

const AIR_PROFILE = {
  profile_kind: 'AIR_TEMPERATURE_PROFILE',
  metric_key: 'temperature_mean',
  dataset_id: 'ECMWF/ERA5_LAND/DAILY_AGGR',
  band: 'temperature_2m',
  unit: 'degC',
  physical_quantity: 'air_temperature_2m',
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  step: 'calendar_month',
  points: [15.0, 16.0, 17.0, 18.0].map((value, i) =>
    point(WINDOWS[i] as string[], value, 'degC'),
  ),
};

const TEMPORAL = {
  window_start: '2024-01-01',
  window_end: '2024-04-30',
  profiles: { ndvi: NDVI_PROFILE },
  anomalies: { ndvi: NDVI_ANOMALY },
  changes: { ndvi: NDVI_CHANGE },
  radar_profiles: { vv: VV_PROFILE },
  radar_analyses: {},
  joint: null,
  concordance: null,
  thermal_profiles: {
    land_surface_temperature_day: LST_PROFILE,
    temperature_mean: AIR_PROFILE,
  },
  thermal_analyses: {},
  thermal_harmonized: null,
  thermal_pair: null,
  thermal_concordance: {
    window_start: '2024-01-01',
    window_end: '2024-04-30',
    rule_id: 'P44_THERMAL_CONCORDANCE_V1',
    months: [
      {
        window_start: '2024-01-01',
        window_end: '2024-01-31',
        rule_id: 'P44_THERMAL_CONCORDANCE_V1',
        lst: { orientation: 'UP' },
        air: { orientation: 'UP' },
        lst_relationship: 'THERMAL_CONCORDANT',
        air_relationship: 'THERMAL_CONTEXT_CONCORDANT',
      },
    ],
  },
  limitations: [],
};

// --- 1-3. Real payload renders chronologically with gaps -----------------------

describe('1-3. real temporal payload renders', () => {
  it('explicit profile resolves by exact metric key', () => {
    const payload = profileFor(TEMPORAL, 'ndvi');
    assert.ok(payload);
    assert.equal(payload?.metric_key, 'ndvi');
    assert.equal(profileFor(TEMPORAL, 'evi'), null);
  });

  it('multiple months render chronologically', () => {
    const data = mapProfilePoints(payloadPoints(profileFor(TEMPORAL, 'ndvi')), 'index');
    assert.deepEqual(
      data.map((d) => d.window_start),
      ['2024-01-01', '2024-02-01', '2024-03-01', '2024-04-01'],
    );
    assert.deepEqual(
      data.map((d) => d.value),
      [0.6, null, 0.7, 0.65],
    );
  });

  it('null months remain gaps', () => {
    const data = mapProfilePoints(payloadPoints(profileFor(TEMPORAL, 'ndvi')), 'index');
    assert.equal(data[1]?.value, null);
    assert.notEqual(data[1]?.value, 0);
  });
});

// --- 4-7. Backend anomaly, change, persistence ----------------------------------

describe('4-7. backend derived values render unchanged', () => {
  it('baseline renders from the backend payload', () => {
    const levels = baselineLevels(
      (anomalyFor(TEMPORAL, 'ndvi') as Record<string, unknown>).baseline as never,
    );
    assert.deepEqual(levels, { mean: 0.65, min: 0.6, max: 0.7 });
  });

  it('anomaly renders from the backend payload', () => {
    const anomalyPayload = anomalyFor(TEMPORAL, 'ndvi') as Record<string, unknown>;
    const data = attachAnomalies(
      mapProfilePoints(payloadPoints(profileFor(TEMPORAL, 'ndvi')), 'index'),
      anomalyPayload.points as never,
    );
    assert.equal(data[0]?.z, -1.0);
    assert.equal(data[0]?.state, 'BELOW_BASELINE');
    assert.equal(data[1]?.state, 'INSUFFICIENT_BASELINE');
    assert.equal(data[1]?.value, null);
    assert.equal(data[2]?.value, 0.7);
  });

  it('change renders from the backend payload', () => {
    const payload = changeFor(TEMPORAL, 'ndvi');
    assert.ok(payload);
    const data = attachChanges(
      mapProfilePoints(payloadPoints(profileFor(TEMPORAL, 'ndvi')), 'index'),
      ((payload as Record<string, unknown>).changes as never[]).map((c) => c),
    );
    const april = data[3];
    assert.equal(april?.absoluteChange, -0.05);
    assert.equal(april?.direction, 'DECREASE');
    assert.equal(april?.rapid, 'NOT_RAPID');
    assert.equal(april?.ratePerDay, -0.0016);
  });

  it('persistence renders from the backend payload', () => {
    const payload = changeFor(TEMPORAL, 'ndvi') as Record<string, unknown>;
    const text = persistenceSummary(payload.persistence as never);
    assert.ok(text?.includes('NO_PERSISTENCE'));
  });
});

// --- 8-12. Units, separation, relationships --------------------------------------

describe('8-12. units, separation, and relationships', () => {
  it('radar units remain correct through the payload path', () => {
    const data = mapProfilePoints(payloadPoints(profileFor(TEMPORAL, 'vv')), 'dB');
    assert.equal(data[0]?.unit, 'dB');
    assert.equal(data[0]?.value, -8.0);
  });

  it('LST remains separate land-surface temperature', () => {
    const payload = profileFor(TEMPORAL, 'land_surface_temperature_day');
    assert.ok(payload);
    assert.equal(payload?.physical_quantity, 'land_surface_temperature');
    const data = mapProfilePoints(payloadPoints(payload), 'degC');
    assert.deepEqual(data.map((d) => d.value), [26.0, 27.0, 28.0, 29.0]);
  });

  it('ERA5 remains separate modelled air temperature', () => {
    const payload = profileFor(TEMPORAL, 'temperature_mean');
    assert.ok(payload);
    assert.equal(payload?.physical_quantity, 'air_temperature_2m');
    const data = mapProfilePoints(payloadPoints(payload), 'degC');
    assert.deepEqual(data.map((d) => d.value), [15.0, 16.0, 17.0, 18.0]);
  });

  it('thermal relationship remains backend state', () => {
    const months = concordanceMonths(TEMPORAL);
    assert.equal(months.length, 1);
    assert.equal(relationshipFor(months[0] as never, 'lst'), 'THERMAL_CONCORDANT');
    assert.equal(
      relationshipFor(months[0] as never, 'air'),
      'THERMAL_CONTEXT_CONCORDANT',
    );
    assert.equal(orientationFor(months[0] as never, 'lst'), 'UP');
  });

  it('NDMI keying stays exact and separate from NDWI', () => {
    const ndmi = {
      ...NDVI_PROFILE,
      metric_key: 'ndmi',
      points: NDVI_PROFILE.points.map((p) => ({ ...p })),
    };
    const bag = { ...TEMPORAL, profiles: { ndmi } };
    assert.ok(profileFor(bag, 'ndmi'));
    assert.equal(profileFor(bag, 'ndwi'), null);
  });
});
