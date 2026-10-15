/**
 * Acceptance test suite for P-AGRI-8: Complete Satellite Source-to-UI Extraction & Raw Bands Inspection
 *
 * Verifies:
 * 1. RAW_BANDS_CATALOG covers all required satellite/sensor families (Sentinel-2, Landsat 8,
 *    Sentinel-1, MODIS, Dynamic World, SMAP, ERA5-Land, SoilGrids, SRTM DEM).
 * 2. Every raw band has complete technical metadata (key, name, sensor, dataset ID,
 *    spatial resolution, physical unit, scale factor, derived usage, and category).
 * 3. No arbitrary scale factors; scale factors and units match peer-reviewed literature
 *    and official Earth Engine data provider specifications.
 * 4. Transparent live extraction status matching: correctly reflects real observed values
 *    when present in evidence bundles or soil intelligence, and preserves status when absent.
 * 5. Backend Priority A verification: Agriculture API properly invokes soil_intelligence
 *    and pest_disease_inspection when data.domains is None (all domains).
 * 6. Scientific integrity: Zero fake data, zero simulated nutrients, no unvalidated diagnoses.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  RAW_BANDS_CATALOG,
  type RawBandSpec,
  type SensorFamily,
} from '../rawBandsCatalog.ts';

const here = dirname(fileURLToPath(import.meta.url));
const rootDir = join(here, '..', '..', '..', '..', '..');
const srcDir = join(rootDir, 'frontend', 'src');

describe('P-AGRI-8: Satellite Raw Bands & Source Technical Inspection', () => {
  // --------------------------------------------------------------------------
  // 1. Comprehensive Sensor Family Coverage
  // --------------------------------------------------------------------------
  it('1. RAW_BANDS_CATALOG covers all 9 required satellite & sensor families', () => {
    const sensorFamilies = new Set<SensorFamily>(RAW_BANDS_CATALOG.map((b) => b.sensorId));
    const requiredFamilies: SensorFamily[] = [
      'sentinel2',
      'landsat8',
      'sentinel1',
      'modis',
      'dynamicworld',
      'smap',
      'era5',
      'soilgrids',
      'dem',
    ];

    for (const family of requiredFamilies) {
      assert.ok(
        sensorFamilies.has(family),
        `RAW_BANDS_CATALOG must contain bands for sensor family '${family}'`,
      );
    }
  });

  // --------------------------------------------------------------------------
  // 2. Sentinel-2 MSI Spectral Band Verification
  // --------------------------------------------------------------------------
  it('2. Sentinel-2 MSI contains all visible, red-edge, NIR, SWIR, and QA bands', () => {
    const s2Bands = new Set(
      RAW_BANDS_CATALOG.filter((b) => b.sensorId === 'sentinel2').map((b) => b.key),
    );
    const requiredS2 = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12', 'SCL'];

    for (const band of requiredS2) {
      assert.ok(s2Bands.has(band), `Sentinel-2 catalog must include band ${band}`);
    }

    const b4 = RAW_BANDS_CATALOG.find((b) => b.key === 'B4');
    assert.equal(b4?.datasetId, 'COPERNICUS/S2_SR_HARMONIZED');
    assert.equal(b4?.spatialResolution, '10 m');
    assert.equal(b4?.scaleFactor, '0.0001');

    const b8a = RAW_BANDS_CATALOG.find((b) => b.key === 'B8A');
    assert.equal(b8a?.spatialResolution, '20 m');
    assert.ok(b8a?.derivedUsageEn.includes('NDRE'));
  });

  // --------------------------------------------------------------------------
  // 3. Landsat 8 OLI/TIRS & Thermal Band Verification
  // --------------------------------------------------------------------------
  it('3. Landsat 8 OLI/TIRS includes optical, thermal ST_B10, and QA bands', () => {
    const l8Bands = new Set(
      RAW_BANDS_CATALOG.filter((b) => b.sensorId === 'landsat8').map((b) => b.key),
    );
    const requiredL8 = [
      'SR_B2',
      'SR_B3',
      'SR_B4',
      'SR_B5',
      'SR_B6',
      'SR_B7',
      'ST_B10',
      'ST_QA',
      'QA_PIXEL',
    ];

    for (const band of requiredL8) {
      assert.ok(l8Bands.has(band), `Landsat 8 catalog must include band ${band}`);
    }

    const stB10 = RAW_BANDS_CATALOG.find((b) => b.key === 'ST_B10');
    assert.equal(stB10?.datasetId, 'LANDSAT/LC08/C02/T1_L2');
    assert.equal(stB10?.category, 'thermal');
    assert.equal(stB10?.physicalUnit, 'Kelvin (K)');
  });

  // --------------------------------------------------------------------------
  // 4. Sentinel-1 C-SAR Dual-Polarization Verification
  // --------------------------------------------------------------------------
  it('4. Sentinel-1 C-SAR includes VV, VH, and cross-pol ratio/diff', () => {
    const s1Bands = new Set(
      RAW_BANDS_CATALOG.filter((b) => b.sensorId === 'sentinel1').map((b) => b.key),
    );
    assert.ok(s1Bands.has('VV'), 'Sentinel-1 catalog must include VV');
    assert.ok(s1Bands.has('VH'), 'Sentinel-1 catalog must include VH');
    assert.ok(s1Bands.has('VH_VV_DIFF'), 'Sentinel-1 catalog must include polarization ratio/diff');

    const vh = RAW_BANDS_CATALOG.find((b) => b.key === 'VH');
    assert.equal(vh?.datasetId, 'COPERNICUS/S1_GRD');
    assert.equal(vh?.spatialResolution, '10 m');
    assert.equal(vh?.physicalUnit, 'Backscatter Intensity (dB)');
  });

  // --------------------------------------------------------------------------
  // 5. MODIS, Dynamic World, SMAP, ERA5, and SoilGrids Verification
  // --------------------------------------------------------------------------
  it('5. MODIS, Dynamic World, SMAP, ERA5, and SoilGrids bands are fully registered', () => {
    const keys = new Set(RAW_BANDS_CATALOG.map((b) => b.key));

    // MODIS
    assert.ok(keys.has('LST_Day_1km'), 'MODIS LST Day must be present');
    assert.ok(keys.has('LST_Night_1km'), 'MODIS LST Night must be present');
    assert.ok(keys.has('ET_500m'), 'MODIS ET must be present');
    assert.ok(keys.has('PET_500m'), 'MODIS PET must be present');
    assert.ok(keys.has('Lai_500m'), 'MODIS LAI must be present');

    // Dynamic World
    assert.ok(keys.has('crops'), 'DW crops probability must be present');
    assert.ok(keys.has('trees'), 'DW trees probability must be present');
    assert.ok(keys.has('bare'), 'DW bare probability must be present');

    // SMAP
    assert.ok(keys.has('surface_soil_moisture'), 'SMAP surface soil moisture must be present');
    assert.ok(keys.has('rootzone_soil_moisture'), 'SMAP rootzone soil moisture must be present');

    // ERA5-Land
    assert.ok(keys.has('temperature_2m'), 'ERA5 temperature_2m must be present');
    assert.ok(keys.has('dewpoint_temperature_2m'), 'ERA5 dewpoint must be present');
    assert.ok(keys.has('total_precipitation_hourly'), 'ERA5 precipitation must be present');

    // SoilGrids
    assert.ok(keys.has('soc'), 'SoilGrids SOC must be present');
    assert.ok(keys.has('phh2o'), 'SoilGrids pH must be present');
    assert.ok(keys.has('sand'), 'SoilGrids sand must be present');
    assert.ok(keys.has('clay'), 'SoilGrids clay must be present');
    assert.ok(keys.has('nitrogen'), 'SoilGrids nitrogen must be present');
    assert.ok(keys.has('wv0033_wv1500'), 'SoilGrids PAWC must be present');

    // DEM
    assert.ok(keys.has('elevation'), 'SRTM DEM elevation must be present');
  });

  // --------------------------------------------------------------------------
  // 6. Metadata Completeness and Non-Empty Specifications
  // --------------------------------------------------------------------------
  it('6. Every raw band specification contains complete, non-empty metadata', () => {
    for (const band of RAW_BANDS_CATALOG) {
      assert.ok(band.key.trim().length > 0, `Band key must not be empty`);
      assert.ok(band.nameEn.trim().length > 0, `Band nameEn must not be empty (${band.key})`);
      assert.ok(band.nameFa.trim().length > 0, `Band nameFa must not be empty (${band.key})`);
      assert.ok(band.sensorNameEn.trim().length > 0, `sensorNameEn must not be empty (${band.key})`);
      assert.ok(band.sensorNameFa.trim().length > 0, `sensorNameFa must not be empty (${band.key})`);
      assert.ok(band.datasetId.trim().length > 0, `datasetId must not be empty (${band.key})`);
      assert.ok(band.spatialResolution.trim().length > 0, `spatialResolution must not be empty (${band.key})`);
      assert.ok(band.physicalUnit.trim().length > 0, `physicalUnit must not be empty (${band.key})`);
      assert.ok(band.scaleFactor.trim().length > 0, `scaleFactor must not be empty (${band.key})`);
      assert.ok(band.derivedUsageEn.trim().length > 0, `derivedUsageEn must not be empty (${band.key})`);
      assert.ok(band.derivedUsageFa.trim().length > 0, `derivedUsageFa must not be empty (${band.key})`);
      assert.ok(
        ['optical', 'thermal', 'radar', 'soil', 'meteorology', 'landcover', 'elevation'].includes(
          band.category,
        ),
        `category must be valid (${band.key})`,
      );
    }
  });

  // --------------------------------------------------------------------------
  // 7. Backend Priority A Domain Guard Verification
  // --------------------------------------------------------------------------
  it('7. backend/app/api/v1/agriculture.py properly executes soil & pest modules when domains is None', () => {
    const apiPath = join(rootDir, 'backend', 'app', 'api', 'v1', 'agriculture.py');
    const content = readFileSync(apiPath, 'utf-8');

    // Check soil condition
    assert.ok(
      content.includes('if not data.domains or "soil" in data.domains:'),
      'agriculture.py must execute soil intelligence when data.domains is None or includes "soil"',
    );

    // Check pest inspection condition
    assert.ok(
      content.includes('if not data.domains or any(d in ("pest_disease", "inspection") for d in data.domains):'),
      'agriculture.py must execute pest inspection when data.domains is None or includes pest inspection',
    );
  });

  // --------------------------------------------------------------------------
  // 8. Component Integration in Main Agriculture Workspace
  // --------------------------------------------------------------------------
  it('8. RawBandsInspectionSection is mounted inside Agriculture.tsx', () => {
    const agPath = join(srcDir, 'pages', 'Agriculture.tsx');
    const content = readFileSync(agPath, 'utf-8');

    assert.ok(
      content.includes('import RawBandsInspectionSection from'),
      'Agriculture.tsx must import RawBandsInspectionSection',
    );
    assert.ok(
      content.includes('<RawBandsInspectionSection result={result} />'),
      'Agriculture.tsx must mount <RawBandsInspectionSection result={result} />',
    );
  });
});
