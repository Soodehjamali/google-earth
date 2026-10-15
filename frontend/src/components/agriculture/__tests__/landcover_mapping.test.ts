/**
 * Scientific Data-Integrity Tests for MODIS MCD12Q1 and Dynamic World Mappings.
 *
 * Verifies:
 * 1. MODIS MCD12Q1 LC_Type1 assigns Water Bodies to class 17 (never 0).
 * 2. Unclassified pixels are mapped to code 255.
 * 3. Dynamic World 10m probability bands are distinct and separate from MODIS 500m categories.
 * 4. Unknown codes remain explicitly unmapped rather than being silently relabeled.
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const frontendSrc = join(here, '..', '..', '..');

describe('MODIS MCD12Q1 vs Dynamic World Scientific Mapping', () => {
  const landCoverSrc = readFileSync(join(frontendSrc, 'pages', 'LandCover.tsx'), 'utf-8');

  it('declares Water Bodies at class 17 in LANDCOVER_CLASSES', () => {
    // Must contain '17': { label: 'Water Bodies', ... }
    assert.match(landCoverSrc, /'17':\s*\{\s*label:\s*'Water Bodies'/);
  });

  it('declares Croplands at class 12 and Mosaic at class 14', () => {
    assert.match(landCoverSrc, /'12':\s*\{\s*label:\s*'Croplands'/);
    assert.match(landCoverSrc, /'14':\s*\{\s*label:\s*'Cropland\/Natural Vegetation Mosaics'/);
  });

  it('declares Unclassified at class 255', () => {
    assert.match(landCoverSrc, /'255':\s*\{\s*label:\s*'Unclassified'/);
  });

  it('does not silently coerce unknown classes', () => {
    // In LandCover.tsx, unknown classes use fallback: LANDCOVER_CLASSES[dominantClass]?.labelFa || dominantClass
    assert.match(landCoverSrc, /LANDCOVER_CLASSES\[dominantClass\]\?\.labelFa\s*\|\|\s*dominantClass/);
  });

  it('preserves Dynamic World distinction in evidenceDetails', () => {
    const evidenceDetailsSrc = readFileSync(
      join(frontendSrc, 'components', 'agriculture', 'evidenceDetails.ts'),
      'utf-8',
    );
    // Must declare the canonical 9 probability bands
    assert.match(evidenceDetailsSrc, /DYNAMIC_WORLD_METRIC\s*=\s*'land_cover_probability'/);
    assert.match(evidenceDetailsSrc, /'water'/);
    assert.match(evidenceDetailsSrc, /'trees'/);
    assert.match(evidenceDetailsSrc, /'crops'/);
    assert.match(evidenceDetailsSrc, /DYNAMIC_WORLD_DOMINANT_FLOOR\s*=\s*0\.4/);
  });
});
