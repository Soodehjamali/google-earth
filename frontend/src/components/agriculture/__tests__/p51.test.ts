/**
 * P5.1 focused tests — Agriculture visualization contract.
 * Runs with Node's built-in runner, no new dependencies:
 *   node --test src/components/agriculture/__tests__/p51.test.ts
 * Covers pure presentation helpers + static source guards: the
 * frontend displays backend-derived evidence and never computes
 * science of its own.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DOMAIN_META } from '../../../types/index.ts';
import { formatEvidenceValue } from '../parse.ts';
import {
  THERMAL_SOURCE_META,
  hasThermalValue,
  thermalOrientationLabel,
  thermalRelationshipLabel,
  thermalSourceMetaFor,
} from '../thermal.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function listSources(dirs: string[]): string[] {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        if (entry === '__tests__') continue;
        walk(full);
      } else if (/\.(ts|tsx)$/.test(entry)) {
        files.push(full);
      }
    }
  };
  for (const dir of dirs) walk(dir);
  return files;
}

function scanSources(dirs: string[], pattern: RegExp): string[] {
  return listSources(dirs).filter((file) =>
    pattern.test(readFileSync(file, 'utf-8')),
  );
}

const AG_DIRS = [agricultureDir, join(srcDir, 'pages', 'agriculture')];

// --- 1. Missing values render as gaps, never as zero ------------------------

describe('1. null renders as a gap', () => {
  it('formatEvidenceValue marks non-finite values unavailable', () => {
    assert.equal(formatEvidenceValue(null), '—');
    assert.equal(formatEvidenceValue(undefined), '—');
    assert.equal(formatEvidenceValue(Number.NaN), '—');
    assert.equal(formatEvidenceValue(Number.POSITIVE_INFINITY), '—');
    assert.equal(formatEvidenceValue('26.85'), '—');
  });

  it('finite thermal values keep full backend precision', () => {
    assert.equal(formatEvidenceValue(26.85), '26.8500');
    assert.equal(formatEvidenceValue(0), '0.0000');
    assert.equal(formatEvidenceValue(-3.5, 2), '-3.50');
  });
});

// --- 2. States pass through; labels never rename meaning --------------------

describe('2. relationship labels preserve backend states', () => {
  it('every known relationship state has a distinct display label', () => {
    const states = [
      'THERMAL_CONCORDANT',
      'THERMAL_DIVERGENT',
      'THERMAL_MIXED_EVIDENCE',
      'THERMAL_ONLY',
      'THERMAL_CONTEXT_CONCORDANT',
      'THERMAL_CONTEXT_DIVERGENT',
      'THERMAL_CONTEXT_MIXED_EVIDENCE',
      'THERMAL_CONTEXT_ONLY',
      'INSUFFICIENT_EVIDENCE',
    ];
    const labels = states.map(thermalRelationshipLabel);
    assert.equal(new Set(labels).size, states.length);
    for (const label of labels) assert.ok(label.length > 0);
  });

  it('unknown states fall back without inventing a meaning', () => {
    assert.equal(thermalRelationshipLabel('HOT'), 'Insufficient evidence');
    assert.equal(thermalRelationshipLabel(undefined), 'Insufficient evidence');
    assert.equal(thermalOrientationLabel('SEVERE'), 'Insufficient evidence');
  });

  it('orientation labels stay distinct and non-biological', () => {
    assert.equal(thermalOrientationLabel('UP'), 'Increased');
    assert.equal(thermalOrientationLabel('DOWN'), 'Decreased');
    assert.equal(thermalOrientationLabel('NEUTRAL'), 'Neutral');
    assert.equal(thermalOrientationLabel('INSUFFICIENT'), 'Insufficient evidence');
  });
});

// --- 3. Thermal sources stay distinct ----------------------------------------

describe('3. MODIS LST and ERA5 air temperature stay separate', () => {
  it('source roles are exact and different', () => {
    const lst = thermalSourceMetaFor('LST_PROFILE');
    const air = thermalSourceMetaFor('AIR_TEMPERATURE_PROFILE');
    assert.equal(lst.sourceRole, 'REMOTE_SENSING_LAND_SURFACE');
    assert.equal(air.sourceRole, 'METEOROLOGICAL_CONTEXT');
    assert.notEqual(lst.sourceRole, air.sourceRole);
  });

  it('display labels never collapse into a generic Temperature', () => {
    const lst = thermalSourceMetaFor('LST_PROFILE');
    const air = thermalSourceMetaFor('AIR_TEMPERATURE_PROFILE');
    assert.notEqual(lst.displayLabel, air.displayLabel);
    assert.notEqual(lst.displayLabel, 'Temperature');
    assert.notEqual(air.displayLabel, 'Temperature');
    assert.ok(lst.displayLabel.includes('Land Surface'));
    assert.ok(air.displayLabel.includes('Air Temperature'));
    assert.notEqual(lst.physicalQuantity, air.physicalQuantity);
    assert.notEqual(lst.datasetId, air.datasetId);
  });

  it('unknown profile kinds resolve to an explicit unknown meta', () => {
    const meta = thermalSourceMetaFor('temperature_profile');
    assert.equal(meta.sourceRole, 'UNKNOWN');
    assert.equal(meta.displayLabel, 'Unknown thermal source');
  });

  it('hasThermalValue admits finite values only', () => {
    const base = {
      window_start: '2024-01-01',
      window_end: '2024-01-31',
      profile_kind: 'LST_PROFILE',
      physical_quantity: 'land_surface_temperature',
      source_role: 'REMOTE_SENSING_LAND_SURFACE',
      metric_id: 'land_surface_temperature_day',
      dataset_id: 'MODIS/061/MOD11A2',
      band: 'LST_Day_1km',
      orientation: 'UP',
      orientation_source: 'anomaly',
      source_state: 'ABOVE_BASELINE',
      source_state_kind: 'anomaly',
      unit: 'degC',
      quality: 'good',
      coverage_percent: 100,
      image_count: 6,
    };
    assert.equal(hasThermalValue({ ...base, value: 26.85 }), true);
    assert.equal(hasThermalValue({ ...base, value: null }), false);
    assert.equal(hasThermalValue({ ...base, value: Number.NaN }), false);
    assert.equal(hasThermalValue(null), false);
    assert.equal(hasThermalValue(undefined), false);
  });

  it('DOMAIN_META keeps the thermal domain entry', () => {
    assert.equal(DOMAIN_META.thermal.label, 'Thermal');
    assert.ok(DOMAIN_META.thermal.labelFa.length > 0);
  });
});

// --- 4. Static guards: the frontend computes no science -----------------------

describe('4. no scientific computation in visualization sources', () => {
  it('no anomaly/baseline scoring identifiers', () => {
    const hits = scanSources(
      AG_DIRS,
      /standardizedAnomaly|computeBaseline|calculateZScore|build_baseline|score_profile|percentile\(|zScore/,
    );
    assert.deepEqual(hits, []);
  });

  it('no concordance or pattern-engine recomputation', () => {
    const hits = scanSources(
      AG_DIRS,
      /analyze_concordance|evaluate_concordance_month|detect_breakpoint|compute_persistence/,
    );
    assert.deepEqual(hits, []);
  });

  it('no thermal subtraction or canopy-temperature inference', () => {
    const hits = scanSources(
      AG_DIRS,
      /canopy_temperature|canopyTemperature|\blst\s*[-−+*/]\s*\S|temperature_2m\s*[-−+*/]|LST_Day_1km\s*[-−+*/]/i,
    );
    assert.deepEqual(hits, []);
  });

  it('no biological or stress labels', () => {
    const pattern =
      /pest|disease|heat stress|heat_stress|thermal stress|canopy stress|defoliation|fungal/i;
    const hits = scanSources(AG_DIRS, pattern);
    // Narrow exception: the P6.1 reference-side vocabulary mirrored
    // verbatim in request.ts REFERENCE_VARIABLES. These are labels the
    // *user* asserts about their own observation (backend contract);
    // the frontend never assigns them from analysis. Any other match
    // in that file — or any match elsewhere — still fails.
    const remaining = hits.filter((file) => {
      if (!file.replace(/\\/g, '/').endsWith('components/agriculture/request.ts')) {
        return true;
      }
      const withoutVocabulary = readFileSync(file, 'utf-8').replace(
        /export const REFERENCE_VARIABLES = \[[\s\S]*?\];/,
        '',
      );
      return pattern.test(withoutVocabulary);
    });
    assert.deepEqual(remaining, []);
  });

  it('no score, risk, or probability vocabulary', () => {
    const hits = scanSources(
      AG_DIRS,
      /risk_score|confidence_score|probability_of|severity_score|thermal stress score/i,
    );
    assert.deepEqual(hits, []);
  });
});
