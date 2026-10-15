/**
 * Tests for Spatial Heatmap Layer MVP (Phase P-AGRI-3).
 * Runs with Node's built-in test runner:
 *   node --test src/components/agriculture/__tests__/spatial_heatmap.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(agricultureDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('P-AGRI-3 Spatial Heatmap MVP Contract & Integrity', () => {
  it('1. exposes the exact four MVP spatial metrics', () => {
    const typesSrc = readSource('types/index.ts');
    assert.match(typesSrc, /type SpatialMetricType = 'ndvi' \| 'lst_day' \| 'soil_moisture' \| 'sar_vh'/);

    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(compSrc, /key:\s*'ndvi'/);
    assert.match(compSrc, /key:\s*'lst_day'/);
    assert.match(compSrc, /key:\s*'soil_moisture'/);
    assert.match(compSrc, /key:\s*'sar_vh'/);
  });

  it('2. discloses native resolutions and units honestly', () => {
    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    // NDVI 10m
    assert.match(compSrc, /resolution:\s*'10 m'/);
    assert.match(compSrc, /unit:\s*'index'/);
    // LST 1000m (°C)
    assert.match(compSrc, /resolution:\s*'1000 m/);
    assert.match(compSrc, /unit:\s*'°C'/);
    // SMAP 9000m (m³/m³)
    assert.match(compSrc, /resolution:\s*'9000 m/);
    assert.match(compSrc, /unit:\s*'m³\/m³'/);
    // SAR VH 10m (dB)
    assert.match(compSrc, /unit:\s*'dB'/);
  });

  it('3. MapView component accepts rasterTileUrl and rasterOpacity', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /rasterTileUrl\?: string \| null/);
    assert.match(mapSrc, /rasterOpacity\?: number/);
    assert.match(mapSrc, /ee-raster-layer/);
    assert.match(mapSrc, /ee-raster-source/);
  });

  it('4. SpatialIntelligenceSection is integrated into Agriculture page', () => {
    const pageSrc = readSource('pages/Agriculture.tsx');
    assert.match(pageSrc, /import SpatialIntelligenceSection from/);
    assert.match(pageSrc, /<SpatialIntelligenceSection/);
  });

  it('5. contains NO synthetic interpolation, mock raster, or noise generators', () => {
    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.doesNotMatch(compSrc, /Math\.random/);
    assert.doesNotMatch(compSrc, /simplex/i);
    assert.doesNotMatch(compSrc, /perlin/i);
    assert.doesNotMatch(compSrc, /mockRaster/i);
    assert.doesNotMatch(compSrc, /fakeHeatmap/i);
  });

  it('6. API client exposes getSpatialLayer endpoint', () => {
    const apiSrc = readSource('api/agriculture.ts');
    assert.match(apiSrc, /getSpatialLayer:\s*\(data: SpatialLayerRequest\)/);
    assert.match(apiSrc, /\/agriculture\/spatial-layer/);
  });

  it('7. Honest unavailable state and error state are implemented', () => {
    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(compSrc, /status === 'unavailable'/);
    assert.match(compSrc, /No spatial data available/);
    assert.match(compSrc, /Unable to load spatial layer/);
  });
});

describe('P-AGRI-4 Agricultural Interpretation Heatmaps Contract & Integrity', () => {
  it('1. exposes the three agricultural concepts with correct metadata', () => {
    const typesSrc = readSource('types/index.ts');
    assert.match(typesSrc, /type SpatialConceptType = 'vegetation_condition' \| 'thermal_stress' \| 'surface_dryness'/);

    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(compSrc, /key:\s*'vegetation_condition'/);
    assert.match(compSrc, /key:\s*'thermal_stress'/);
    assert.match(compSrc, /key:\s*'surface_dryness'/);
  });

  it('2. provides view mode toggle between Interpretation and Raw RS', () => {
    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(compSrc, /data-testid="spatial-mode-interpretation"/);
    assert.match(compSrc, /data-testid="spatial-mode-raw"/);
    assert.match(compSrc, /viewMode === 'interpretation'/);
  });

  it('3. renders qualitative legend and scientific caution without diagnostic overreach', () => {
    const compSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(compSrc, /data-testid="spatial-interpretation-card"/);
    assert.match(compSrc, /data-testid="spatial-scientific-caution"/);
    assert.match(compSrc, /layerData\.qualitative_legend/);
    assert.match(compSrc, /layerData\.scientific_caution/);

    // No diagnostic overreach in frontend code
    assert.doesNotMatch(compSrc, /crop is healthy/i);
    assert.doesNotMatch(compSrc, /disease confirmed/i);
    assert.doesNotMatch(compSrc, /pest detected/i);
  });

  it('4. preserves raw metrics and NDMI compatibility', () => {
    const typesSrc = readSource('types/index.ts');
    assert.match(typesSrc, /'ndmi'/);
  });
});

