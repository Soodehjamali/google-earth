/**
 * Unit & Contract Tests for Interactive Manual Polygon Field Boundary Drawing.
 * Runs with Node's built-in test runner:
 *   node --test src/components/agriculture/__tests__/polygon_drawing.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  validatePolygonCoordinates,
  calculatePolygonAreaSqMeters,
  calculatePolygonCenter,
  toGeoJsonPolygon,
} from '../polygon.ts';

import {
  buildAgricultureRequest,
  validateAnalysisInputs,
  parseGpsInput,
  parseGeoJsonInput,
} from '../request.ts';

import type { PolygonGeometry } from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(agricultureDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('Polygon Boundary Drawing - Pure Logic & Geometry Integrity', () => {
  // Test coordinate ring: 4 unique points around F-A12 test location in Iran [53.688, 32.4279]
  const validClosedRing: [number, number][] = [
    [53.680, 32.420],
    [53.695, 32.420],
    [53.695, 32.435],
    [53.680, 32.435],
    [53.680, 32.420], // closed
  ];

  it('1. validatePolygonCoordinates validates correct closed rings and calculates area', () => {
    const result = validatePolygonCoordinates(validClosedRing);
    assert.strictEqual(result.valid, true);
    assert.strictEqual(result.vertexCount, 4);
    assert.ok(result.areaSqM && result.areaSqM > 100000, `Area in sq meters should be > 100k, got ${result.areaSqM}`);
    assert.ok(result.areaHectares && result.areaHectares > 10, `Area in hectares should be > 10, got ${result.areaHectares}`);
  });

  it('2. validatePolygonCoordinates rejects unclosed rings', () => {
    const unclosedRing = [
      [53.680, 32.420],
      [53.695, 32.420],
      [53.695, 32.435],
      [53.680, 32.435],
    ];
    const result = validatePolygonCoordinates(unclosedRing);
    assert.strictEqual(result.valid, false);
    assert.match(result.error || '', /بسته نیست|closed/);
  });

  it('3. validatePolygonCoordinates rejects fewer than 4 coordinates', () => {
    const triangleClosed = [
      [53.680, 32.420],
      [53.695, 32.420],
      [53.680, 32.420],
    ];
    const result = validatePolygonCoordinates(triangleClosed);
    assert.strictEqual(result.valid, false);
    assert.match(result.error || '', /حداقل ۳ نقطه مجزا|at least 4 points/);
  });

  it('4. validatePolygonCoordinates rejects out-of-bounds coordinates (lon/lat)', () => {
    const invalidLon = [
      [-195.0, 32.420],
      [53.695, 32.420],
      [53.695, 32.435],
      [-195.0, 32.420],
    ];
    const resLon = validatePolygonCoordinates(invalidLon);
    assert.strictEqual(resLon.valid, false);
    assert.match(resLon.error || '', /طول جغرافیایی|Longitude/);

    const invalidLat = [
      [53.680, 95.0],
      [53.695, 32.420],
      [53.695, 32.435],
      [53.680, 95.0],
    ];
    const resLat = validatePolygonCoordinates(invalidLat);
    assert.strictEqual(resLat.valid, false);
    assert.match(resLat.error || '', /عرض جغرافیایی|Latitude/);
  });

  it('5. validatePolygonCoordinates rejects non-array or NaN input', () => {
    assert.strictEqual(validatePolygonCoordinates(null).valid, false);
    assert.strictEqual(validatePolygonCoordinates('invalid').valid, false);
    assert.strictEqual(
      validatePolygonCoordinates([[NaN, 32.4], [53.6, 32.4], [53.6, 32.5], [NaN, 32.4]]).valid,
      false
    );
  });

  it('6. calculatePolygonAreaSqMeters calculates spherical geodesic area correctly', () => {
    // 0 points or < 3 vertices gives 0
    assert.strictEqual(calculatePolygonAreaSqMeters([]), 0);
    assert.strictEqual(calculatePolygonAreaSqMeters([[53.68, 32.42], [53.69, 32.42]]), 0);

    const areaClosed = calculatePolygonAreaSqMeters(validClosedRing);
    const areaUnclosed = calculatePolygonAreaSqMeters(validClosedRing.slice(0, -1));
    assert.ok(areaClosed > 0);
    // Closed and unclosed unique points give equivalent area
    assert.ok(Math.abs(areaClosed - areaUnclosed) < 1e-4);
  });

  it('7. calculatePolygonCenter calculates centroid correctly without skewing on closed ring', () => {
    const unclosed: [number, number][] = [
      [0, 0],
      [10, 0],
      [10, 10],
      [0, 10],
    ];
    const closed: [number, number][] = [...unclosed, [0, 0]];

    const centerUnclosed = calculatePolygonCenter(unclosed);
    const centerClosed = calculatePolygonCenter(closed);

    assert.strictEqual(centerUnclosed[0], 5);
    assert.strictEqual(centerUnclosed[1], 5);
    assert.strictEqual(centerClosed[0], 5);
    assert.strictEqual(centerClosed[1], 5);
  });

  it('8. toGeoJsonPolygon converts vertex array to standard GeoJSON Polygon', () => {
    const vertices: [number, number][] = [
      [53.680, 32.420],
      [53.695, 32.420],
      [53.695, 32.435],
      [53.680, 32.435],
    ];
    const poly = toGeoJsonPolygon(vertices);
    assert.strictEqual(poly.type, 'Polygon');
    assert.strictEqual(poly.coordinates.length, 1);
    assert.strictEqual(poly.coordinates[0].length, 5); // 4 + closed ring point
    assert.deepStrictEqual(poly.coordinates[0][0], poly.coordinates[0][4]); // closed
  });

  it('9. buildAgricultureRequest preserves all F-A12 fields when given PolygonGeometry', () => {
    const polygonGeom: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [validClosedRing],
    };

    const req = buildAgricultureRequest({
      geometry: polygonGeom,
      start_date: '2025-06-01',
      end_date: '2025-09-01',
      cloud_max_percent: 20,
      selectedDomains: ['vegetation', 'soil'],
    });

    assert.strictEqual(req.geometry.type, 'Polygon');
    assert.deepStrictEqual(req.geometry.coordinates, [validClosedRing]);
    assert.strictEqual(req.start_date, '2025-06-01');
    assert.strictEqual(req.end_date, '2025-09-01');
    assert.strictEqual(req.cloud_max_percent, 20);
    assert.deepStrictEqual(req.domains, ['soil', 'vegetation']);
  });

  it('10. validateAnalysisInputs validates polygon and catches invalid polygon geometry', () => {
    const validPoly: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [validClosedRing],
    };
    assert.strictEqual(
      validateAnalysisInputs(validPoly, '2025-06-01', '2025-09-01'),
      null
    );

    const invalidPoly: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [[[53.68, 32.42], [53.69, 32.42], [53.68, 32.42]]],
    };
    const err = validateAnalysisInputs(invalidPoly, '2025-06-01', '2025-09-01');
    assert.ok(err !== null);
  });

  it('11. preserves backward compatibility with GPS Point input', () => {
    const gpsRes = parseGpsInput('32.4279', '53.688');
    assert.strictEqual('geometry' in gpsRes, true);
    if ('geometry' in gpsRes) {
      assert.strictEqual(gpsRes.geometry.type, 'Point');
      assert.deepStrictEqual(gpsRes.geometry.coordinates, [53.688, 32.4279]);
    }
  });

  it('12. parseGeoJsonInput continues to accept standard GeoJSON Polygon string', () => {
    const rawGeoJson = JSON.stringify({
      type: 'Polygon',
      coordinates: [validClosedRing],
    });
    const parsed = parseGeoJsonInput(rawGeoJson);
    assert.strictEqual('geometry' in parsed, true);
    if ('geometry' in parsed) {
      assert.strictEqual(parsed.geometry.type, 'Polygon');
    }
  });
});

describe('Polygon Boundary Drawing - UI Components & Scientific Honesty', () => {
  it('1. MapView includes manual polygon drawing toolbar and layer setup', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /data-testid="map-drawing-toolbar"/);
    assert.match(mapSrc, /data-testid="map-draw-btn"/);
    assert.match(mapSrc, /data-testid="map-edit-btn"/);
    assert.match(mapSrc, /data-testid="map-clear-btn"/);
    assert.match(mapSrc, /data-testid="map-confirm-btn"/);
    assert.match(mapSrc, /drawn-polygon-source/);
    assert.match(mapSrc, /drawn-polygon-fill/);
    assert.match(mapSrc, /drawn-polygon-outline/);
    assert.match(mapSrc, /drawn-polygon-vertices/);
  });

  it('2. AnalysisRequestForm supports draw mode and displays confirmed polygon status', () => {
    const formSrc = readSource('components/agriculture/AnalysisRequestForm.tsx');
    assert.match(formSrc, /type GeometryInputMode = 'draw' \| 'gps' \| 'geojson'/);
    assert.match(formSrc, /data-testid="mode-draw-btn"/);
    assert.match(formSrc, /data-testid="draw-field-panel"/);
    assert.match(formSrc, /data-testid="draw-field-confirmed"/);
  });

  it('3. Scientific honesty: Discloses as User-defined field boundary without AI/auto claims', () => {
    const formSrc = readSource('components/agriculture/AnalysisRequestForm.tsx');
    assert.match(formSrc, /User-defined field boundary/);
    // Must NOT claim automatic detection
    assert.doesNotMatch(formSrc, /Automatically detected field/);
    assert.doesNotMatch(formSrc, /AI detected boundary/);
    assert.doesNotMatch(formSrc, /Satellite-confirmed boundary/);
  });

  it('4. Agriculture page coordinates state between MapView and AnalysisRequestForm', () => {
    const pageSrc = readSource('pages/Agriculture.tsx');
    assert.match(pageSrc, /confirmedPolygon/);
    assert.match(pageSrc, /isPolygonConfirmed/);
    assert.match(pageSrc, /onPolygonConfirm/);
  });
});
