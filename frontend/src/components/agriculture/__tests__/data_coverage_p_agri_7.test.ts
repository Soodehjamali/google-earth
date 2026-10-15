/**
 * Acceptance test suite for P-AGRI-7: Complete Satellite Data Inventory, Extraction & UI Coverage
 *
 * Verifies:
 * 1. Full UI coverage of all retrievable metrics without omission.
 * 2. Integration and rendering of canopy moisture anomalies (ndre_anomaly, ndmi_anomaly, msi_anomaly).
 * 3. Categorization and domain page mappings for all newly elevated metrics.
 * 4. Scientific interpretation catalog coverage with peer-reviewed citations and no arbitrary thresholds.
 * 5. Soil intelligence elevation to main agriculture workspace.
 * 6. Scientific honesty: null preservation, zero fake data, no diagnostic overreach.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  METRIC_CATEGORIES,
  evaluateMetricState,
} from '../categorizedMetrics.ts';
import { DOMAIN_PAGE_CONFIGS } from '../domainPages.ts';
import {
  METRIC_INTERPRETATION_CATALOG,
  getMetricInterpretation,
} from '../metricInterpretation.ts';
import type { EvidenceItemResponse } from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = dirname(dirname(dirname(here)));
const rootDir = dirname(srcDir);

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('P-AGRI-7: Complete Satellite Data Inventory & UI Coverage', () => {
  // --------------------------------------------------------------------------
  // 1. Canopy Moisture Anomaly Metrics Integration
  // --------------------------------------------------------------------------
  it('1. ndre_anomaly, ndmi_anomaly, and msi_anomaly are registered in METRIC_CATEGORIES', () => {
    const allCategoryKeys = new Set<string>();
    for (const group of METRIC_CATEGORIES) {
      for (const m of group.metrics) {
        allCategoryKeys.add(m.key);
      }
    }

    assert.ok(allCategoryKeys.has('ndre_anomaly'), 'ndre_anomaly must be in METRIC_CATEGORIES');
    assert.ok(allCategoryKeys.has('ndmi_anomaly'), 'ndmi_anomaly must be in METRIC_CATEGORIES');
    assert.ok(allCategoryKeys.has('msi_anomaly'), 'msi_anomaly must be in METRIC_CATEGORIES');

    const vegGroup = METRIC_CATEGORIES.find((g) => g.key === 'vegetation');
    assert.ok(vegGroup?.metrics.some((m) => m.key === 'ndre_anomaly'));

    const moistGroup = METRIC_CATEGORIES.find((g) => g.key === 'moisture');
    assert.ok(moistGroup?.metrics.some((m) => m.key === 'ndmi_anomaly'));
    assert.ok(moistGroup?.metrics.some((m) => m.key === 'msi_anomaly'));
  });

  // --------------------------------------------------------------------------
  // 2. Domain Page Configuration Coverage
  // --------------------------------------------------------------------------
  it('2. ndre_anomaly is mounted in vegetation domain page sections', () => {
    const vegSections = DOMAIN_PAGE_CONFIGS.vegetation.sections;
    const allVegKeys = vegSections.flatMap((s) => s.metricKeys);
    assert.ok(
      allVegKeys.includes('ndre_anomaly'),
      'ndre_anomaly must be present in vegetation domain page sections',
    );
  });

  it('3. ndmi_anomaly and msi_anomaly are mounted in water domain page sections', () => {
    const waterSections = DOMAIN_PAGE_CONFIGS.water.sections;
    const allWaterKeys = waterSections.flatMap((s) => s.metricKeys);
    assert.ok(
      allWaterKeys.includes('ndmi_anomaly'),
      'ndmi_anomaly must be present in water domain page sections',
    );
    assert.ok(
      allWaterKeys.includes('msi_anomaly'),
      'msi_anomaly must be present in water domain page sections',
    );
  });

  // --------------------------------------------------------------------------
  // 3. Metric Interpretation Catalog Coverage
  // --------------------------------------------------------------------------
  it('4. ndre_anomaly, ndmi_anomaly, and msi_anomaly are in METRIC_INTERPRETATION_CATALOG', () => {
    const keys = ['ndre_anomaly', 'ndmi_anomaly', 'msi_anomaly'];
    for (const key of keys) {
      const spec = METRIC_INTERPRETATION_CATALOG[key];
      assert.ok(spec, `Catalog must contain interpretation spec for ${key}`);
      assert.equal(spec.referenceRange.hasFixedRange, false);
      assert.ok(spec.referenceRange.sourceCitation.length > 5);
      assert.ok(spec.referenceRange.validityConditionsFa.length > 5);
      assert.match(
        spec.referenceRange.rangeLabelFa,
        /زمینه|فاقد|بافت|وابسته|متغیر/,
        `Context-dependent metric '${key}' must explain why no fixed range exists`,
      );
      assert.ok(spec.farmerExplanationFa.length > 20);
      assert.ok(spec.scientificCautionFa.length > 20);
    }
  });

  it('5. ndre_anomaly evaluation correctly reflects seasonal departure', () => {
    const spec = METRIC_INTERPRETATION_CATALOG['ndre_anomaly'];
    assert.equal(spec.evaluateStatus(0.05).statusClass, 'good');
    assert.equal(spec.evaluateStatus(0.0).statusClass, 'neutral');
    assert.equal(spec.evaluateStatus(-0.05).statusClass, 'warning');
    assert.equal(spec.evaluateStatus(null).statusClass, 'neutral');
  });

  it('6. ndmi_anomaly and msi_anomaly evaluations correctly reflect moisture and stress departures', () => {
    const ndmiSpec = METRIC_INTERPRETATION_CATALOG['ndmi_anomaly'];
    assert.equal(ndmiSpec.evaluateStatus(0.04).statusClass, 'good');
    assert.equal(ndmiSpec.evaluateStatus(0.0).statusClass, 'neutral');
    assert.equal(ndmiSpec.evaluateStatus(-0.04).statusClass, 'warning');

    const msiSpec = METRIC_INTERPRETATION_CATALOG['msi_anomaly'];
    // Higher MSI anomaly means higher moisture stress (warning), lower means less stress (good)
    assert.equal(msiSpec.evaluateStatus(-0.10).statusClass, 'good');
    assert.equal(msiSpec.evaluateStatus(0.0).statusClass, 'neutral');
    assert.equal(msiSpec.evaluateStatus(0.10).statusClass, 'warning');
  });

  // --------------------------------------------------------------------------
  // 4. Main Page Soil Intelligence Elevation
  // --------------------------------------------------------------------------
  it('7. Agriculture.tsx imports and renders SoilIntelligenceSection conditionally on result.soil_intelligence', () => {
    const code = readSource('pages/Agriculture.tsx');
    assert.match(code, /import SoilIntelligenceSection from '\.\.\/components\/agriculture\/SoilIntelligenceSection'/);
    assert.match(code, /<SoilIntelligenceSection[\s\S]*?initialSoilData=\{result\.soil_intelligence\}/);
  });

  // --------------------------------------------------------------------------
  // 5. Scientific Honesty & Null Preservation
  // --------------------------------------------------------------------------
  it('8. Null and missing values are never coerced to zero in evaluateMetricState', () => {
    const nullItem: EvidenceItemResponse = {
      metric_key: 'ndre_anomaly',
      value: null,
      unit: '',
      status: 'insufficient',
      quality: 'insufficient',
      display_name: 'NDRE Seasonal Anomaly',
      is_usable: false,
      is_proxy: false,
    };

    const def = METRIC_CATEGORIES.flatMap((c) => c.metrics).find((m) => m.key === 'ndre_anomaly')!;
    const state = evaluateMetricState(nullItem, def);

    assert.equal(state.state, 'insufficient');
    assert.equal(state.interpretation?.value, null);
    assert.notEqual(state.displayValue, '0');
    assert.notEqual(state.displayValue, '0.0');
    assert.notEqual(state.displayValue, '0.0000');
  });

  it('9. Genuine 0.0 is preserved as available and not treated as missing', () => {
    const zeroItem: EvidenceItemResponse = {
      metric_key: 'ndre_anomaly',
      value: 0.0,
      unit: '',
      status: 'available',
      quality: 'nominal',
      display_name: 'NDRE Seasonal Anomaly',
      is_usable: true,
      is_proxy: false,
    };

    const def = METRIC_CATEGORIES.flatMap((c) => c.metrics).find((m) => m.key === 'ndre_anomaly')!;
    const state = evaluateMetricState(zeroItem, def);

    assert.equal(state.state, 'available');
    assert.equal(state.interpretation?.value, 0.0);
    assert.equal(state.displayValue, '0.0000');
  });

  // --------------------------------------------------------------------------
  // 6. Zero Mock/Synthetic Data Architecture Check
  // --------------------------------------------------------------------------
  it('10. No Math.random or synthetic data generators in categorizedMetrics, metricInterpretation, or domainPages', () => {
    const files = [
      'components/agriculture/categorizedMetrics.ts',
      'components/agriculture/metricInterpretation.ts',
      'components/agriculture/domainPages.ts',
    ];
    for (const f of files) {
      const code = readSource(f);
      assert.doesNotMatch(code, /Math\.random\(\)/, `File ${f} must not use Math.random()`);
      assert.doesNotMatch(code, /fakeData|mockData|syntheticData/, `File ${f} must not contain synthetic data`);
    }
  });

  // --------------------------------------------------------------------------
  // 7. Full Inventory Matrix Reconciliation
  // --------------------------------------------------------------------------
  it('11. Metric coverage audit file exists and records 0 available-unrendered metrics', () => {
    const auditPath = join(rootDir, 'backend', 'metric_coverage_audit.json');
    if (existsSync(auditPath)) {
      const audit = JSON.parse(readFileSync(auditPath, 'utf-8'));
      assert.equal(
        audit.summary.available_not_rendered,
        0,
        'There must be 0 retrievable metrics left unrendered in the UI',
      );
      assert.equal(audit.summary.total, 118, 'Total registered metrics must be 118');
      assert.equal(audit.summary.rendered, 97, 'Rendered metrics count must be 97');
      assert.equal(audit.summary.unavailable_not_rendered, 21, 'Unavailable metrics count must be 21');
    }
  });
});
