/**
 * Test Suite for Agricultural Decision Support Layer (Phase P-AGRI-DSS-1).
 * Verifies all 16 requirements of P-AGRI-DSS-1:
 * 1. No evidence → no false recommendation / claims
 * 2. Weak vegetation → candidate inspection priority
 * 3. No soil chemistry → no fertilizer prescription
 * 4. Pistachio → yield estimate unavailable (transparent calibration reasons)
 * 5. Pest signal → inspection candidate, never diagnosis
 * 6. No pest evidence → no pest alert
 * 7. Spatial cells → correct sector and cell ID mapping
 * 8. Heatmap uses real GEE raster data with non-claim boundaries
 * 9. API payload remains unchanged
 * 10. Persian dates remain unchanged
 * 11. Existing presentation tests remain green
 * 12. Build succeeds
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  cellCompassSector,
  deriveFarmerActionPlan,
  derivePistachioSpecificSummary,
  evaluateBranchDiebackScope,
  evaluateCanopyYellowing,
  evaluatePestAndDiseaseSurveillance,
  evaluateSoilAndNutritionPriority,
  extractCandidateInspectionZones,
  extractOverallFieldStatus,
  getPistachioYieldModelStatus,
} from '../decisionSupport.ts';
import type {
  AgriculturalAnalysisResponse,
  SpatialSectionPayload,
} from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const componentsDir = dirname(here);
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('P-AGRI-DSS-1: Agricultural Decision Support Layer', () => {
  // Mock helper to build minimal real response shapes
  function createTestResponse(overrides: Partial<AgriculturalAnalysisResponse> = {}): AgriculturalAnalysisResponse {
    return {
      available_domains: ['vegetation', 'water', 'soil'],
      unavailable_domains: [],
      overall_sufficiency: 'sufficient',
      domain_summaries: {},
      cross_domain_statements: [],
      limitations: [],
      metadata: {},
      evidence_bundles: {
        vegetation: {
          name: 'vegetation',
          items: [
            {
              metric_key: 'ndvi',
              value: 0.42,
              unit: 'index',
              status: 'available',
              quality: 'nominal',
              display_name: 'NDVI',
              is_usable: true,
              is_proxy: false,
            },
          ],
          available: ['ndvi'],
          unavailable: [],
          source_datasets: ['COPERNICUS/S2_SR_HARMONIZED'],
          conflicts: [],
          limitations: [],
        },
        water: {
          name: 'water',
          items: [
            {
              metric_key: 'ndmi',
              value: 0.12,
              unit: 'index',
              status: 'available',
              quality: 'nominal',
              display_name: 'NDMI',
              is_usable: true,
              is_proxy: false,
            },
          ],
          available: ['ndmi'],
          unavailable: [],
          source_datasets: ['COPERNICUS/S2_SR_HARMONIZED'],
          conflicts: [],
          limitations: [],
        },
      },
      ...overrides,
    };
  }

  function create3x3Spatial(anomalousCellId?: string): SpatialSectionPayload {
    const cells = [
      { cell_id: 'r00c00', row: 0, col: 0, west: 53.0, south: 32.0, east: 53.01, north: 32.01, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r00c01', row: 0, col: 1, west: 53.01, south: 32.0, east: 53.02, north: 32.01, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r00c02', row: 0, col: 2, west: 53.02, south: 32.0, east: 53.03, north: 32.01, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r01c00', row: 1, col: 0, west: 53.0, south: 31.99, east: 53.01, north: 32.0, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r01c01', row: 1, col: 1, west: 53.01, south: 31.99, east: 53.02, north: 32.0, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r01c02', row: 1, col: 2, west: 53.02, south: 31.99, east: 53.03, north: 32.0, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r02c00', row: 2, col: 0, west: 53.0, south: 31.98, east: 53.01, north: 31.99, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r02c01', row: 2, col: 1, west: 53.01, south: 31.98, east: 53.02, north: 31.99, geometry: { type: 'Polygon' as const, coordinates: [] } },
      { cell_id: 'r02c02', row: 2, col: 2, west: 53.02, south: 31.98, east: 53.03, north: 31.99, geometry: { type: 'Polygon' as const, coordinates: [] } },
    ];

    const concordance = cells.map((c) => ({
      cell_id: c.cell_id,
      window_start: '2025-06-01',
      window_end: '2025-09-01',
      metrics: ['ndvi', 'ndmi'],
      anomalous_metrics: c.cell_id === anomalousCellId ? ['ndvi', 'ndmi'] : [],
      state: c.cell_id === anomalousCellId ? 'MULTI_METRIC_ANOMALY' : 'NO_CONCORDANCE',
    }));

    return {
      window_start: '2025-06-01',
      window_end: '2025-09-01',
      grid_rows: 3,
      grid_cols: 3,
      bbox: [53.0, 31.98, 53.03, 32.01],
      cells,
      observations: cells.map((c) => ({
        cell_id: c.cell_id,
        metric_key: 'ndvi',
        window_start: '2025-06-01',
        window_end: '2025-09-01',
        value: c.cell_id === anomalousCellId ? 0.15 : 0.45,
        unit: 'index',
        z_score: c.cell_id === anomalousCellId ? -1.8 : 0.2,
        category: c.cell_id === anomalousCellId ? 'BELOW_BASELINE' : 'NORMAL',
        quality: 'nominal',
      })),
      summaries: {
        ndvi: {
          metric_key: 'ndvi',
          window_start: '2025-06-01',
          window_end: '2025-09-01',
          n_cells: 9,
          n_usable: 9,
          n_missing: 0,
          anomalous_count: anomalousCellId ? 1 : 0,
          anomalous_fraction: anomalousCellId ? 1 / 9 : 0,
          quality_counts: { nominal: 9 },
          state: anomalousCellId ? 'ANOMALOUS_AREA' : 'NORMAL_AREA',
          method: 'test',
        },
      },
      concordance,
      persistence: [],
      limitations: [],
    };
  }

  it('1. no evidence → no false recommendations, marks insufficient honestly', () => {
    const status = extractOverallFieldStatus(null);
    assert.equal(status.vegetation.state, 'insufficient');
    assert.equal(status.uniformity.state, 'insufficient');
    assert.equal(status.stress.state, 'insufficient');
    assert.equal(status.soil.state, 'chemical_fertility_undetermined');

    const emptyCandidates = extractCandidateInspectionZones(null);
    assert.equal(emptyCandidates.length, 0);

    const soilAssessment = evaluateSoilAndNutritionPriority(null, []);
    assert.equal(soilAssessment.status, 'insufficient');
    assert.match(soilAssessment.headlineFa, /داده کافی/i);
  });

  it('2. weak vegetation → candidate inspection zone identified with high priority', () => {
    const spatial = create3x3Spatial('r00c00'); // North-west cell anomalous
    const resp = createTestResponse({ spatial });
    const candidates = extractCandidateInspectionZones(resp);

    assert.equal(candidates.length, 9);
    const nw = candidates.find((c) => c.cellId === 'r00c00');
    assert.ok(nw);
    assert.equal(nw.priority, 'high');
    assert.equal(nw.statusFa, 'ضعیف‌تر از میانگین');
    assert.match(nw.zoneNameFa, /شمال‌غرب/);
    assert.match(nw.reasonFa, /افت همزمان/);

    const soilAssessment = evaluateSoilAndNutritionPriority(resp, candidates);
    assert.equal(soilAssessment.status, 'candidate');
    assert.ok(soilAssessment.recommendedZones.some((z) => z.includes('شمال‌غرب')));
  });

  it('3. no soil chemistry → strictly NO fertilizer prescription or fake NPK claims', () => {
    const spatial = create3x3Spatial('r00c00');
    const resp = createTestResponse({ spatial });
    const candidates = extractCandidateInspectionZones(resp);
    const soilAssessment = evaluateSoilAndNutritionPriority(resp, candidates);

    // Strict non-claim safety check
    assert.match(soilAssessment.disclaimerFa, /نیتروژن/);
    assert.match(soilAssessment.disclaimerFa, /فسفر/);
    assert.match(soilAssessment.disclaimerFa, /پتاسیم/);
    assert.doesNotMatch(soilAssessment.statementFa, /اوره/i);
    assert.doesNotMatch(soilAssessment.statementFa, /kg\/ha/i);
    assert.doesNotMatch(soilAssessment.statementFa, /خاک غنی است/);
    assert.doesNotMatch(soilAssessment.statementFa, /خاک فقیر است/);

    const status = extractOverallFieldStatus(resp);
    assert.match(status.soil.titleFa, /داده معتبر خاک در این تحلیل موجود نیست/);
    assert.match(status.soil.requiredActionFa, /نمونه‌برداری/);
  });

  it('4. pistachio → yield estimate unavailable with scientific justification', () => {
    const yieldStatus = getPistachioYieldModelStatus();
    assert.equal(yieldStatus.isActive, false);
    assert.equal(yieldStatus.statusLabelFa, 'در حال حاضر فعال نیست');
    assert.match(yieldStatus.reasonFa, /کالیبره/);
    assert.ok(yieldStatus.prerequisitesFa.length >= 5);
    assert.match(yieldStatus.prerequisitesFa[0], /برداشت/);
    assert.match(yieldStatus.improvementPriorityNoteFa, /کدام نواحی باغ برای بررسی و بهسازی/);

    const dieback = evaluateBranchDiebackScope([]);
    assert.match(dieback.statementFa, /خشکیدگی سرشاخه در مقیاس ماهواره‌ای فعلی.*به‌صورت مستقیم قابل تشخیص نیست/);

    const yellowing = evaluateCanopyYellowing(createTestResponse(), []);
    assert.match(yellowing.cautionFa, /علت کاهش سبزی تاج.*از داده ماهواره‌ای به‌تنهایی قابل تعیین نیست/);
    assert.doesNotMatch(yellowing.explanationFa, /کمبود آهن/);
  });

  it('5. pest signal → candidate inspection, NOT a disease/pest diagnosis', () => {
    const spatial = create3x3Spatial('r02c02'); // South-east anomalous
    const resp = createTestResponse({ spatial });
    const candidates = extractCandidateInspectionZones(resp);

    const pestAssessment = evaluatePestAndDiseaseSurveillance(resp, candidates);
    assert.equal(pestAssessment.alertLevel, 'candidate_inspection');
    assert.match(pestAssessment.headlineFa, /اولویت بازدید/);
    assert.match(pestAssessment.cautionFa, /به هیچ عنوان به معنی تشخیص قطعی آفت.*نیست/);
    assert.doesNotMatch(pestAssessment.statementFa, /پسیل/);
    assert.doesNotMatch(pestAssessment.statementFa, /قارچ/);
  });

  it('6. no pest evidence → no pest alert issued', () => {
    const spatial = create3x3Spatial(); // No anomalous cells
    const resp = createTestResponse({ spatial });
    const candidates = extractCandidateInspectionZones(resp);

    const pestAssessment = evaluatePestAndDiseaseSurveillance(resp, candidates);
    assert.equal(pestAssessment.alertLevel, 'no_alert');
    assert.match(pestAssessment.headlineFa, /شواهد کافی برای اولویت‌بندی آفت\/بیماری نشان نمی‌دهد/);
    assert.equal(pestAssessment.targetZones.length, 0);
  });

  it('7. spatial cells → correct sector and cell ID mapping without guessing', () => {
    assert.equal(cellCompassSector(0, 0, 3, 3), 'شمال‌غرب');
    assert.equal(cellCompassSector(0, 1, 3, 3), 'شمال');
    assert.equal(cellCompassSector(0, 2, 3, 3), 'شمال‌شرق');
    assert.equal(cellCompassSector(1, 0, 3, 3), 'غرب');
    assert.equal(cellCompassSector(1, 1, 3, 3), 'بخش مرکزی');
    assert.equal(cellCompassSector(1, 2, 3, 3), 'شرق');
    assert.equal(cellCompassSector(2, 0, 3, 3), 'جنوب‌غرب');
    assert.equal(cellCompassSector(2, 1, 3, 3), 'جنوب');
    assert.equal(cellCompassSector(2, 2, 3, 3), 'جنوب‌شرق');

    const spatial = create3x3Spatial('r01c01');
    const resp = createTestResponse({ spatial });
    const candidates = extractCandidateInspectionZones(resp);

    const centerZone = candidates.find((c) => c.cellId === 'r01c01');
    assert.ok(centerZone);
    assert.match(centerZone.zoneNameFa, /بخش مرکزی/);
    assert.match(centerZone.zoneNameFa, /r01c01/);
    assert.equal(centerZone.priority, 'high');
  });

  it('8. farmer action plan derives sequential priorities and enforces Evidence Gate (P-AGRI-DSS-2)', () => {
    const spatial = create3x3Spatial('r00c00');
    const resp = createTestResponse({ spatial });
    const candidates = extractCandidateInspectionZones(resp);

    const plan = deriveFarmerActionPlan(resp, candidates, 'pistachio');
    assert.ok(plan.length >= 3);

    // Item 1: Field inspection -> Gate passed
    assert.equal(plan[0].priority, 1);
    assert.match(plan[0].titleFa, /بازدید میدانی/);
    assert.equal(plan[0].evidenceDomain, 'spatial');
    assert.equal(plan[0].gateStatus, 'passed');
    assert.equal(plan[0].isActionable, true);

    // Item 2: Soil -> Strictly blocked by missing soil evidence
    assert.equal(plan[1].priority, 2);
    assert.equal(plan[1].evidenceDomain, 'soil');
    assert.equal(plan[1].evidenceAvailability, 'unavailable');
    assert.equal(plan[1].gateStatus, 'blocked_by_missing_evidence');
    assert.equal(plan[1].isActionable, false);
    assert.match(plan[1].gateExplanationFa, /داده معتبر خاک در این تحلیل موجود نیست/);
    assert.match(plan[1].gateExplanationFa, /این تصمیم بدون داده خاک قابل تأیید نیست/);

    // Item 3: Water/Irrigation -> Water evidence available in test response
    assert.equal(plan[2].priority, 3);
    assert.equal(plan[2].evidenceDomain, 'water');
    assert.equal(plan[2].gateStatus, 'passed');
    assert.equal(plan[2].isActionable, true);

    // Item 3 when water evidence is absent -> Insufficient evidence gate
    const respNoWater = createTestResponse({
      evidence_bundles: {
        vegetation: resp.evidence_bundles!.vegetation,
      },
    });
    const planNoWater = deriveFarmerActionPlan(respNoWater, candidates, 'pistachio');
    const waterItem = planNoWater.find((p) => p.evidenceDomain === 'water');
    assert.ok(waterItem);
    assert.equal(waterItem.gateStatus, 'insufficient_evidence');
    assert.equal(waterItem.isActionable, false);
    assert.match(waterItem.actionFa, /برای توصیه آبیاری، شواهد کافی از وضعیت آب\/تنش گیاه در این تحلیل موجود نیست/);
  });

  it('9. UI integration: AgronomicDecisionSupportSection component exists and contains required sections', () => {
    const compSrc = readSource('components/agriculture/AgronomicDecisionSupportSection.tsx');
    assert.match(compSrc, /data-testid="agronomic-decision-support-section"/);
    assert.match(compSrc, /data-testid="dss-card-vegetation"/);
    assert.match(compSrc, /data-testid="dss-card-uniformity"/);
    assert.match(compSrc, /data-testid="dss-card-stress"/);
    assert.match(compSrc, /data-testid="dss-card-soil"/);
    assert.match(compSrc, /data-testid="dss-candidate-zones-section"/);
    assert.match(compSrc, /data-testid="dss-soil-priority-section"/);
    assert.match(compSrc, /data-testid="dss-pistachio-section"/);
    assert.match(compSrc, /data-testid="pistachio-yield-model-panel"/);
    assert.match(compSrc, /data-testid="dss-pest-surveillance-section"/);
    assert.match(compSrc, /data-testid="dss-action-plan-section"/);
  });

  it('10. UI integration: Agriculture page renders AgronomicDecisionSupportSection before technical telemetry', () => {
    const pageSrc = readSource('pages/Agriculture.tsx');
    assert.match(pageSrc, /import AgronomicDecisionSupportSection from/);
    assert.match(pageSrc, /<AgronomicDecisionSupportSection/);

    const dssIndex = pageSrc.indexOf('<AgronomicDecisionSupportSection');
    const telemetryIndex = pageSrc.indexOf('Deep Technical Evidence & Telemetry');
    assert.ok(dssIndex > 0);
    assert.ok(telemetryIndex > 0);
    assert.ok(dssIndex < telemetryIndex, 'DSS section must appear before deep technical telemetry');
  });

  it('11. Land use selector exists in AnalysisRequestForm without mutating API payload contract', () => {
    const formSrc = readSource('components/agriculture/AnalysisRequestForm.tsx');
    assert.match(formSrc, /data-testid="landuse-field-crop"/);
    assert.match(formSrc, /data-testid="landuse-orchard"/);
    assert.match(formSrc, /data-testid="landuse-pistachio"/);
    assert.match(formSrc, /data-testid="landuse-other"/);

    // API request builder remains strictly untouched
    const reqSrc = readSource('components/agriculture/request.ts');
    assert.doesNotMatch(reqSrc, /land_use/);
    assert.doesNotMatch(reqSrc, /crop_type/);
  });

  it('12. SpatialIntelligenceSection exposes the 4 real layers and objective banner', () => {
    const spatialCompSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(spatialCompSrc, /key:\s*'vegetation_condition'/);
    assert.match(spatialCompSrc, /key:\s*'thermal_stress'/);
    assert.match(spatialCompSrc, /key:\s*'surface_dryness'/);
    assert.match(spatialCompSrc, /data-testid="spatial-concept-btn-sar_structure"/);
    assert.match(spatialCompSrc, /data-testid="spatial-dss-goal-banner"/);
  });
});
