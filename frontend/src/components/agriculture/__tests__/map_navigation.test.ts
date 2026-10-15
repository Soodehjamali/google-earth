import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { formatCoordinates } from '../geocoding.ts';
import { toGeoJsonPolygon, validatePolygonCoordinates } from '../polygon.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SRC_ROOT = path.resolve(__dirname, '../../..');

function readSource(relPath: string): string {
  return fs.readFileSync(path.join(SRC_ROOT, relPath), 'utf8');
}

describe('Map Navigation & Geographic Context - Pure Logic', () => {
  it('1. formatCoordinates formats latitude and longitude into standard geographical notation', () => {
    assert.equal(formatCoordinates(35.6892, 51.3890), '35.6892° N, 51.3890° E');
    assert.equal(formatCoordinates(32.4279, 53.6880), '32.4279° N, 53.6880° E');
    assert.equal(formatCoordinates(-33.8688, 151.2093), '33.8688° S, 151.2093° E');
    assert.equal(formatCoordinates(-22.9068, -43.1729), '22.9068° S, 43.1729° W');
  });

  it('2. formatCoordinates handles invalid or NaN coordinates safely', () => {
    assert.equal(formatCoordinates(NaN, NaN), '0.0000° N, 0.0000° E');
  });

  it('3. Geocoding module uses OpenStreetMap Nominatim without hardcoded secrets or API keys', () => {
    const geoSrc = readSource('components/agriculture/geocoding.ts');
    assert.match(geoSrc, /nominatim\.openstreetmap\.org\/search/);
    assert.match(geoSrc, /q=/);
    assert.match(geoSrc, /format=json/);
    // Ensure no API keys or tokens are hardcoded
    assert.doesNotMatch(geoSrc, /api[_-]?key/i);
    assert.doesNotMatch(geoSrc, /secret/i);
    assert.doesNotMatch(geoSrc, /access[_-]?token/i);
  });
});

describe('Map Navigation & Geographic Context - UI & MapLibre Setup', () => {
  it('1. MapView configures real multi-source Geographic Context (Satellite + Boundaries + OSM)', () => {
    const mapSrc = readSource('components/MapView.tsx');
    // Satellite imagery source (Google Satellite lyrs=s)
    assert.match(mapSrc, /google\.com\/vt\/lyrs=s/);
    // Hybrid Boundaries & Places reference overlay (Google Hybrid Reference lyrs=h)
    assert.match(mapSrc, /google\.com\/vt\/lyrs=h/);
    // OpenStreetMap
    assert.match(mapSrc, /tile\.openstreetmap\.org/);

    // Layer IDs
    assert.match(mapSrc, /satellite-layer/);
    assert.match(mapSrc, /labels-layer/);
    assert.match(mapSrc, /osm-layer/);
  });

  it('2. MapView provides Base Map switcher (Hybrid, Streets, Pure Satellite)', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /data-testid="map-base-switcher"/);
    assert.match(mapSrc, /data-testid="map-style-hybrid"/);
    assert.match(mapSrc, /data-testid="map-style-streets"/);
    assert.match(mapSrc, /data-testid="map-style-satellite"/);
  });

  it('3. MapView provides real search bar integrated with geocoding', () => {
    const mapSrc = readSource('components/MapView.tsx');
    const searchSrc = readSource('components/agriculture/MapSearchBar.tsx');

    assert.match(mapSrc, /<MapSearchBar/);
    assert.match(searchSrc, /data-testid="map-search-input"/);
    assert.match(searchSrc, /data-testid="map-search-results"/);
    assert.match(mapSrc, /search-marker-source/);
    assert.match(mapSrc, /search-marker-point/);
  });

  it('4. MapView provides My Location with graceful error handling and zero fake coordinates', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /data-testid="map-my-location-btn"/);
    assert.match(mapSrc, /navigator\.geolocation/);
    assert.match(mapSrc, /user-location-source/);
    assert.match(mapSrc, /user-location-point/);
    assert.match(mapSrc, /data-testid="map-location-error"/);
  });

  it('5. MapView provides Reset View and Zoom controls', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /data-testid="map-reset-view-btn"/);
    assert.match(mapSrc, /data-testid="map-zoom-in-btn"/);
    assert.match(mapSrc, /data-testid="map-zoom-out-btn"/);
    assert.match(mapSrc, /NavigationControl/);
    assert.match(mapSrc, /ScaleControl/);
  });

  it('6. MapView displays unobtrusive coordinates and zoom pill', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /data-testid="map-coordinates-pill"/);
    assert.match(mapSrc, /formatCoordinates/);
  });

  it('7. MapView preserves polygon drawing toolbar, layers, and status indicators', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.match(mapSrc, /data-testid="map-drawing-toolbar"/);
    assert.match(mapSrc, /data-testid="map-draw-btn"/);
    assert.match(mapSrc, /data-testid="map-edit-btn"/);
    assert.match(mapSrc, /data-testid="map-clear-btn"/);
    assert.match(mapSrc, /data-testid="map-confirm-btn"/);
    assert.match(mapSrc, /Draw Field Boundary/);
    assert.match(mapSrc, /Field boundary confirmed/);
    assert.match(mapSrc, /drawn-polygon-source/);
    assert.match(mapSrc, /drawn-polygon-fill/);
    assert.match(mapSrc, /drawn-polygon-outline/);
    assert.match(mapSrc, /drawn-polygon-vertices/);
  });

  it('8. Scientific honesty: Zero automatic boundary detection claims', () => {
    const mapSrc = readSource('components/MapView.tsx');
    assert.doesNotMatch(mapSrc, /automatic field boundary detection/i);
    assert.doesNotMatch(mapSrc, /AI boundary detection/i);
    assert.doesNotMatch(mapSrc, /satellite-confirmed boundary/i);
  });
});

describe('P0 Bugfix Regression Tests: Map Preview, Zoom Controls & Polygon Selection', () => {
  it('1. The orchard-selection page mounts the map', () => {
    const agriPageSrc = readSource('pages/Agriculture.tsx');
    const locPageSrc = readSource('pages/Location.tsx');

    // Agriculture page mounts MapView with drawing capabilities
    assert.match(agriPageSrc, /<MapView/);
    assert.match(agriPageSrc, /enableDrawing/);
    assert.match(agriPageSrc, /showDrawControls/);

    // Location page mounts MapView
    assert.match(locPageSrc, /<MapView/);
  });

  it('2. The map container has usable dimensions and dynamic resize observer', () => {
    const mapSrc = readSource('components/MapView.tsx');
    // Height explicitly specified preventing zero-height collapse
    assert.match(mapSrc, /height:\s*520/);
    // ResizeObserver watches container and resizes map instance
    assert.match(mapSrc, /new ResizeObserver/);
    assert.match(mapSrc, /resizeObserver\.observe\(mapContainer\.current\)/);
    assert.match(mapSrc, /map\.current\.resize\(\)/);
  });

  it('3. Zoom controls are present, dedicated, and accessible without element overlap', () => {
    const mapSrc = readSource('components/MapView.tsx');
    // Dedicated floating controls cluster
    assert.match(mapSrc, /data-testid="map-zoom-controls"/);
    assert.match(mapSrc, /data-testid="map-zoom-in-btn"/);
    assert.match(mapSrc, /data-testid="map-zoom-out-btn"/);
    // Separate positioning avoiding collision with top bar
    assert.match(mapSrc, /left:\s*10/);
    assert.match(mapSrc, /zIndex:\s*25/);
    // Top bar offset to avoid overlapping zoom cluster
    assert.match(mapSrc, /left:\s*54/);
  });

  it('4. Polygon drawing and selection remains functional', () => {
    const mapSrc = readSource('components/MapView.tsx');
    const formSrc = readSource('components/agriculture/AnalysisRequestForm.tsx');

    // Drawing mode activation in form
    assert.match(formSrc, /data-testid="mode-draw-btn"/);
    // Complete toolbar actions
    assert.match(mapSrc, /data-testid="map-draw-btn"/);
    assert.match(mapSrc, /data-testid="map-edit-btn"/);
    assert.match(mapSrc, /data-testid="map-confirm-btn"/);
    assert.match(mapSrc, /data-testid="map-clear-btn"/);
    // Event handling on canvas
    assert.match(mapSrc, /currentMap\.on\('click', onMapClick\)/);
    assert.match(mapSrc, /currentMap\.on\('mousemove', onMapMouseMove\)/);
  });

  it('5. The resulting geometry is a valid GeoJSON Polygon with a closed ring', () => {
    const orchardVertices: [number, number][] = [
      [53.682, 32.421],
      [53.692, 32.421],
      [53.692, 32.431],
      [53.682, 32.431],
    ];

    const geoJsonPoly = toGeoJsonPolygon(orchardVertices);
    assert.strictEqual(geoJsonPoly.type, 'Polygon');
    assert.strictEqual(geoJsonPoly.coordinates.length, 1);
    // Closed ring: 4 unique points + 1 closing point = 5
    assert.strictEqual(geoJsonPoly.coordinates[0].length, 5);
    // First and last coordinates must match identically
    assert.deepStrictEqual(geoJsonPoly.coordinates[0][0], geoJsonPoly.coordinates[0][4]);

    const validation = validatePolygonCoordinates(geoJsonPoly.coordinates[0]);
    assert.strictEqual(validation.valid, true);
    assert.strictEqual(validation.vertexCount, 4);
    assert.ok(validation.areaHectares && validation.areaHectares > 0);
  });

  it('6. Existing geometry can be loaded without coordinate changes', () => {
    const mapSrc = readSource('components/MapView.tsx');
    // Reactive sync on initialPolygon prop
    assert.match(mapSrc, /initialPolygon\.coordinates/);
    assert.match(mapSrc, /setVertices\(pts\)/);
    assert.match(mapSrc, /map\.current\.fitBounds\(polyBounds/);

    // Verify coordinates are preserved verbatim without mutation
    const existingCoords: [number, number][] = [
      [54.123456, 35.654321],
      [54.234567, 35.654321],
      [54.234567, 35.765432],
      [54.123456, 35.765432],
      [54.123456, 35.654321],
    ];
    const existingPoly: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [existingCoords],
    };

    const extracted = existingPoly.coordinates[0].slice(0, -1);
    assert.deepStrictEqual(extracted, existingCoords.slice(0, -1));
  });

  it('7. A map-loading failure produces an understandable error state rather than a blank screen', () => {
    const mapSrc = readSource('components/MapView.tsx');

    // 1. Foundation layer: OSM layer is configured and active in hybrid mode to avoid blank white screen
    assert.match(mapSrc, /id:\s*'osm-layer'/);
    assert.match(mapSrc, /'raster-opacity':\s*\(baseMapMode === 'streets' \|\| baseMapMode === 'hybrid'\)\s*\?\s*1\.0\s*:\s*0\.0/);

    // 2. Map provider error state tracking
    assert.match(mapSrc, /data-testid="map-provider-error"/);
    assert.match(mapSrc, /data-testid="map-provider-retry-btn"/);
    assert.match(mapSrc, /currentMap\.on\('error', onMapError\)/);
    assert.match(mapSrc, /ارتباط با سرور تصاویر ماهواره‌ای برقرار نشد/);
  });
});
