import type { PolygonGeometry } from '../../types/index.ts';

export interface PolygonValidationResult {
  valid: boolean;
  error?: string;
  areaSqM?: number;
  areaHectares?: number;
  vertexCount?: number;
}

/**
 * Validate that coordinates form a valid GeoJSON Polygon outer ring.
 *
 * Rules:
 * - Must be an array of at least 4 coordinates (3 unique points + closing point).
 * - Ring must be closed (first coordinate == last coordinate).
 * - Coordinates must be [longitude, latitude] numbers.
 * - Longitude must be in [-180, 180].
 * - Latitude must be in [-90, 90].
 * - No NaN or non-finite values.
 */
export function validatePolygonCoordinates(
  coordinates: unknown,
): PolygonValidationResult {
  if (!Array.isArray(coordinates)) {
    return { valid: false, error: 'مختصات باید یک آرایه باشد — Coordinates must be an array' };
  }

  if (coordinates.length < 4) {
    return {
      valid: false,
      error: 'چندضلعی باید حداقل ۳ نقطه مجزا داشته باشد (حداقل ۴ نقطه با نقطه پایانی) — Polygon ring must have at least 4 points (3 unique vertices + closing point)',
    };
  }

  for (let i = 0; i < coordinates.length; i++) {
    const pt = coordinates[i];
    if (!Array.isArray(pt) || pt.length < 2) {
      return {
        valid: false,
        error: `نقطه ${i + 1} نامعتبر است — Coordinate ${i + 1} is invalid`,
      };
    }
    const [lon, lat] = pt;
    if (typeof lon !== 'number' || !Number.isFinite(lon) || lon < -180 || lon > 180) {
      return {
        valid: false,
        error: `طول جغرافیایی نقطه ${i + 1} نامعتبر است (-180 تا 180) — Longitude ${i + 1} out of bounds`,
      };
    }
    if (typeof lat !== 'number' || !Number.isFinite(lat) || lat < -90 || lat > 90) {
      return {
        valid: false,
        error: `عرض جغرافیایی نقطه ${i + 1} نامعتبر است (-90 تا 90) — Latitude ${i + 1} out of bounds`,
      };
    }
  }

  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  const isClosed = Math.abs(first[0] - last[0]) < 1e-7 && Math.abs(first[1] - last[1]) < 1e-7;

  if (!isClosed) {
    return {
      valid: false,
      error: 'حلقه چندضلعی بسته نیست؛ نقطه پایانی باید با نقطه شروع برابر باشد — Polygon ring must be closed (first == last point)',
    };
  }

  const coords = coordinates as [number, number][];
  const areaSqM = calculatePolygonAreaSqMeters(coords.slice(0, -1));
  const areaHectares = areaSqM / 10000;
  const vertexCount = coordinates.length - 1; // unique vertices

  return {
    valid: true,
    areaSqM,
    areaHectares,
    vertexCount,
  };
}

/**
 * Calculate geodesic area of a polygon on the WGS84 sphere in square meters.
 * Expects unclosed or closed ring of [longitude, latitude] coordinates.
 */
export function calculatePolygonAreaSqMeters(
  coordinates: readonly [number, number][],
): number {
  if (coordinates.length < 3) return 0;

  // If closed ring passed, take unique points
  let pts = coordinates;
  if (
    pts.length >= 4 &&
    Math.abs(pts[0][0] - pts[pts.length - 1][0]) < 1e-7 &&
    Math.abs(pts[0][1] - pts[pts.length - 1][1]) < 1e-7
  ) {
    pts = pts.slice(0, -1);
  }

  const radius = 6378137; // WGS84 mean earth radius in meters
  let total = 0;
  const n = pts.length;

  for (let i = 0; i < n; i++) {
    const [lon1, lat1] = pts[i];
    const [lon2, lat2] = pts[(i + 1) % n];
    const p1 = (lat1 * Math.PI) / 180;
    const p2 = (lat2 * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    total += dLon * (2 + Math.sin(p1) + Math.sin(p2));
  }

  return Math.abs((total * radius * radius) / 4);
}

/**
 * Calculate the centroid/center [longitude, latitude] of a polygon.
 */
export function calculatePolygonCenter(
  coordinates: readonly [number, number][],
): [number, number] {
  if (coordinates.length === 0) return [53.688, 32.4279];

  let sumLon = 0;
  let sumLat = 0;
  let count = 0;

  // Handle closed or unclosed
  const isClosed =
    coordinates.length >= 4 &&
    Math.abs(coordinates[0][0] - coordinates[coordinates.length - 1][0]) < 1e-7 &&
    Math.abs(coordinates[0][1] - coordinates[coordinates.length - 1][1]) < 1e-7;
  const n = isClosed ? coordinates.length - 1 : coordinates.length;

  for (let i = 0; i < n; i++) {
    sumLon += coordinates[i][0];
    sumLat += coordinates[i][1];
    count++;
  }

  if (count === 0) return [53.688, 32.4279];
  return [sumLon / count, sumLat / count];
}

/**
 * Convert an array of vertices [ [lon, lat], ... ] into a standard GeoJSON PolygonGeometry.
 * Automatically closes the outer ring if needed.
 */
export function toGeoJsonPolygon(
  vertices: readonly [number, number][],
): PolygonGeometry {
  if (vertices.length < 3) {
    throw new Error('At least 3 vertices required to create a Polygon');
  }

  const ring: number[][] = vertices.map(([lon, lat]) => [lon, lat]);
  const first = ring[0];
  const last = ring[ring.length - 1];

  if (Math.abs(first[0] - last[0]) > 1e-7 || Math.abs(first[1] - last[1]) > 1e-7) {
    ring.push([first[0], first[1]]);
  }

  return {
    type: 'Polygon',
    coordinates: [ring],
  };
}
