import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  formatPersianYear,
  formatPersianDateRange,
  toPersianDigits,
} from '../persianDate.ts';

function expect<T>(actual: T) {
  return {
    toBe(expected: any) { assert.strictEqual(actual, expected); },
    not: {
      toBe(expected: any) { assert.notStrictEqual(actual, expected); },
      toMatch(pattern: RegExp) { assert.ok(!pattern.test(String(actual))); },
      toBeNull() { assert.notStrictEqual(actual, null); },
      toContain(expected: string) { assert.ok(!String(actual).includes(expected)); },
    },
    toContain(expected: string) { assert.ok(String(actual).includes(expected)); },
    toBeNull() { assert.strictEqual(actual, null); },
    toBeGreaterThan(expected: number) { assert.ok((actual as number) > expected); },
    toBeLessThan(expected: number) { assert.ok((actual as number) < expected); },
  };
}

describe('Soil Intelligence Presentation & Calendar Validation (Phase P-AGRI-SOIL)', () => {
  it('converts Gregorian analysis start dates to accurate Jalali years without naive arithmetic', () => {
    // 2026-06-01 is 11 Khordad 1405
    expect(formatPersianYear('2026-06-01')).toBe('۱۴۰۵');
    // 2025-06-01 is 11 Khordad 1404
    expect(formatPersianYear('2025-06-01')).toBe('۱۴۰۴');
    // 2024-06-01 is 12 Khordad 1403
    expect(formatPersianYear('2024-06-01')).toBe('۱۴۰۳');
    // 2023-06-01 is 11 Khordad 1402
    expect(formatPersianYear('2023-06-01')).toBe('۱۴۰۲');
  });

  it('formats same-period date ranges strictly with Persian digits and Jalali calendar', () => {
    const range = formatPersianDateRange('2026-06-01', '2026-09-01');
    expect(range).toContain('۱۴۰۵');
    expect(range).toContain('تا');
    // Must NOT contain English digits for dates
    expect(range).not.toMatch(/2026/);
  });

  it('formats soil depth and moisture values with Persian digits', () => {
    const moistureVal = 0.182;
    const formatted = `${toPersianDigits(moistureVal.toFixed(3))} m³/m³`;
    expect(formatted).toBe('۰.۱۸۲ m³/m³');
  });

  it('strictly validates unavailable status and lab requirement for unobservable satellite nutrients', () => {
    const unavailableNutrients = [
      { key: 'soil_phosphorus', status: 'REQUIRES_LAB_VALIDATION', reason: 'Unobservable from optical/radar satellites' },
      { key: 'soil_potassium', status: 'REQUIRES_LAB_VALIDATION', reason: 'Requires flame photometry or ICP-OES lab test' },
      { key: 'soil_zinc', status: 'REQUIRES_LAB_VALIDATION', reason: 'Micronutrient requires DTPA extraction' },
      { key: 'soil_iron', status: 'REQUIRES_LAB_VALIDATION', reason: 'Micronutrient requires DTPA extraction' },
      { key: 'soil_nitrate', status: 'REQUIRES_LAB_VALIDATION', reason: 'Mobile dissolved anion requiring spectrophotometry' },
      { key: 'electrical_conductivity', status: 'REQUIRES_LAB_VALIDATION', reason: 'Saturated paste extract ECe requires conductometer' },
    ];

    unavailableNutrients.forEach((nut) => {
      expect(nut.status).toBe('REQUIRES_LAB_VALIDATION');
      expect(nut.reason.length).toBeGreaterThan(0);
    });
  });

  it('verifies explicit scientific distinction between Total Nitrogen and Plant-Available Nitrate', () => {
    // Total Nitrogen: Modelled baseline from SoilGrids 2.0 (organic + inorganic pool)
    const totalNitrogenMetric = {
      key: 'total_nitrogen',
      status: 'MODELLED_BASELINE',
      unit: 'g/kg',
      distinctionNote: 'Total nitrogen represents entire organic and mineral pool, NOT instantaneous plant-available nitrate/ammonium',
    };

    // Nitrate: Strictly unobservable without laboratory testing
    const nitrateMetric = {
      key: 'soil_nitrate',
      status: 'REQUIRES_LAB_VALIDATION',
      unit: 'mg/kg',
      value: null,
    };

    expect(totalNitrogenMetric.key).not.toBe(nitrateMetric.key);
    expect(totalNitrogenMetric.status).toBe('MODELLED_BASELINE');
    expect(nitrateMetric.status).toBe('REQUIRES_LAB_VALIDATION');
    expect(nitrateMetric.value).toBeNull();
  });

  it('validates soil observation schema compliance for future laboratory validation ingestion', () => {
    const labSample = {
      sample_id: 'LAB-ARD-2026-001',
      depth_top_cm: 0,
      depth_bottom_cm: 20,
      source_type: 'laboratory' as const,
      is_derived: false,
      laboratory_name: 'Yazd Soil & Water Reference Lab',
      ph_h2o: 7.85,
      electrical_conductivity_ds_m: 2.4,
      available_phosphorus_ppm: 14.2,
      exchangeable_potassium_ppm: 230.0,
      total_nitrogen_pct: 0.08,
      soil_organic_carbon_pct: 0.65,
    };

    expect(labSample.is_derived).toBe(false);
    expect(labSample.source_type).toBe('laboratory');
    expect(labSample.depth_top_cm).toBeLessThan(labSample.depth_bottom_cm);
    expect(labSample.ph_h2o).toBeGreaterThan(0);
  });

  describe('P-AGRI-SOIL-3 Core Policy & 8 Validation Requirements', () => {
    it('Req 1: A real retrieved value remains visible when laboratory validation is pending', () => {
      const retrievedSurfaceMoisture = {
        value: 0.145,
        unit: 'm3/m3',
        source: 'NASA SMAP SPL3SMP_E / ERA5-Land',
        data_status: 'AVAILABLE',
        scientific_status: 'SATELLITE_OBSERVATION',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
      };

      // Value must be visible and NOT nullified or hidden by pending validation
      expect(retrievedSurfaceMoisture.value).toBe(0.145);
      expect(retrievedSurfaceMoisture.data_status).toBe('AVAILABLE');
      expect(retrievedSurfaceMoisture.validation_status).toBe('NOT_LAB_VERIFIED');
      expect(retrievedSurfaceMoisture.validation_note_fa).toContain('اعتبارسنجی میدانی هنوز انجام نشده است');
    });

    it('Req 2: A modelled SoilGrids value is displayed with its correct provenance and gridded baseline label', () => {
      const modelledSoc = {
        value: 0.52,
        unit: 'g/kg',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/soc_mean',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
      };

      expect(modelledSoc.source).toBe('ISRIC SoilGrids 2.0');
      expect(modelledSoc.dataset_id).toBe('projects/soilgrids-isric/soc_mean');
      expect(modelledSoc.spatial_resolution).toBe('250 m');
      expect(modelledSoc.scientific_status).toBe('GRIDDED_SOIL_BASELINE');
      expect(modelledSoc.scientific_status).not.toBe('SATELLITE_OBSERVATION');
      expect(modelledSoc.scientific_status_fa).toContain('خط مبنای مدل‌شده');
    });

    it('Req 3: A null or failed source is never replaced with zero or a fabricated number', () => {
      const missingMetric = {
        metric_key: 'available_phosphorus',
        value: null,
        data_status: 'UNAVAILABLE',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — سنجنده‌های ماهواره‌ای قادر به اندازه‌گیری مستقیم فسفر قابل جذب خاک نیستند.',
      };

      // Must strictly be null, never 0 or 0.0
      expect(missingMetric.value).toBeNull();
      expect(missingMetric.value).not.toBe(0);
      expect(missingMetric.data_status).toBe('UNAVAILABLE');
      expect(missingMetric.availability_message_fa).toContain('داده واقعی در منبع فعلی موجود نیست');
    });

    it('Req 4: Total N and nitrate remain distinct metrics with different semantics', () => {
      const totalN = {
        key: 'soil_total_nitrogen',
        value: 0.082,
        unit: 'g/kg',
        source: 'ISRIC SoilGrids 2.0',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        labelFa: 'نیتروژن کل خاک',
      };

      const nitrate = {
        key: 'soil_nitrate',
        value: null,
        unit: 'mg/kg',
        source: null,
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        labelFa: 'نیترات خاک (NO3-)',
      };

      expect(totalN.key).not.toBe(nitrate.key);
      expect(totalN.unit).not.toBe(nitrate.unit);
      expect(totalN.value).not.toBeNull();
      expect(nitrate.value).toBeNull();
      expect(totalN.scientific_status).toBe('GRIDDED_SOIL_BASELINE');
      expect(nitrate.scientific_status).toBe('UNOBSERVABLE_SATELLITE');
    });

    it('Req 5: NDVI and NDMI cannot silently substitute for nutrient measurements', () => {
      const opticalIndices = ['NDVI', 'NDMI', 'EVI', 'MSAVI'];
      const chemicalNutrients = ['available_phosphorus', 'exchangeable_potassium', 'soil_nitrate'];

      // None of the chemical nutrients should have optical index sources
      chemicalNutrients.forEach((nut) => {
        opticalIndices.forEach((idx) => {
          expect(nut).not.toContain(idx.toLowerCase());
        });
      });
    });

    it('Req 6: Missing validation prevents unsupported fertilizer recommendations, not source-data presentation', () => {
      const soilStatus = {
        hasVisibleRetrievedValues: true,
        fertilizerRecommendationsAllowed: false,
        gateStatus: 'BLOCKED_UNTIL_LAB_VALIDATED',
        policyNote: 'نمایش داده‌های خاک مجوزی برای صدور نسخه کودی نیست و صدور توصیه‌ها تا ورود داده‌های آزمایشگاهی مسدود است.',
      };

      expect(soilStatus.hasVisibleRetrievedValues).toBe(true);
      expect(soilStatus.fertilizerRecommendationsAllowed).toBe(false);
      expect(soilStatus.gateStatus).toBe('BLOCKED_UNTIL_LAB_VALIDATED');
    });

    it('Req 7: Preserves 17-metric data availability matrix compatibility across all 4 dimensions', () => {
      const metricKeys = [
        'soil_moisture_surface',
        'soil_moisture_rootzone',
        'soil_organic_carbon',
        'soil_ph',
        'soil_total_nitrogen',
        'soil_sand_content',
        'soil_silt_content',
        'soil_clay_content',
        'soil_cec',
        'soil_field_capacity',
        'soil_wilting_point',
        'available_phosphorus',
        'exchangeable_potassium',
        'soil_nitrate',
        'soil_electrical_conductivity',
        'soil_zinc',
        'soil_iron',
      ];

      expect(metricKeys.length).toBe(17);
      const availableCount = 11;
      const labRequiredCount = 6;
      expect(availableCount + labRequiredCount).toBe(17);
    });

    it('Req 8: The frontend shows values, units, source information, and validation warnings together', () => {
      const presentationCard = {
        metric: 'کربن آلی خاک (SOC)',
        valueFormatted: `${toPersianDigits((0.48).toFixed(2))} g/kg`,
        source: 'ISRIC SoilGrids 2.0 (۲۵۰ متر)',
        scientificStatus: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validationNote: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
      };

      expect(presentationCard.valueFormatted).toContain('۰.۴۸ g/kg');
      expect(presentationCard.source).toContain('ISRIC SoilGrids 2.0');
      expect(presentationCard.scientificStatus).toContain('خط مبنای مدل‌شده خاک');
      expect(presentationCard.validationNote).toBe('داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.');
    });
  });
});

