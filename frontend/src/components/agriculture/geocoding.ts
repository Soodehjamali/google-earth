/**
 * Geocoding Service for Agricultural Intelligence Platform
 *
 * Uses OpenStreetMap Nominatim for real geographic search.
 * - Free and open, requires NO API key
 * - Supports Persian and English queries (e.g. Semnan, Isfahan, Tehran, Iran)
 * - Returns exact geographic coordinates, bounding boxes, and administrative hierarchy
 */

export interface GeocodingResult {
  id: string | number;
  displayName: string;
  shortName: string;
  lat: number;
  lon: number;
  boundingBox?: [number, number, number, number]; // [minLat, maxLat, minLon, maxLon]
  type?: string;
  category?: string;
}

/**
 * Searches real geographic locations using OpenStreetMap Nominatim.
 */
export async function searchLocations(
  query: string,
  signal?: AbortSignal
): Promise<GeocodingResult[]> {
  const trimmed = query.trim();
  if (trimmed.length < 2) return [];

  const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(
    trimmed
  )}&format=json&addressdetails=1&limit=5`;

  try {
    const response = await fetch(url, {
      signal,
      headers: {
        'Accept-Language': 'fa,en;q=0.8',
        'User-Agent': 'AgriculturalIntelligencePlatform/1.0',
      },
    });

    if (!response.ok) {
      return [];
    }

    const data = await response.json();
    if (!Array.isArray(data)) return [];

    return data.map((item, index) => {
      const lat = parseFloat(item.lat);
      const lon = parseFloat(item.lon);
      const bbox: [number, number, number, number] | undefined =
        Array.isArray(item.boundingbox) && item.boundingbox.length === 4
          ? [
              parseFloat(item.boundingbox[0]),
              parseFloat(item.boundingbox[1]),
              parseFloat(item.boundingbox[2]),
              parseFloat(item.boundingbox[3]),
            ]
          : undefined;

      const nameParts = (item.display_name || '').split(',');
      const shortName = nameParts[0]?.trim() || trimmed;

      return {
        id: item.place_id || index,
        displayName: item.display_name,
        shortName,
        lat,
        lon,
        boundingBox: bbox,
        type: item.type,
        category: item.class,
      };
    });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      return [];
    }
    console.warn('Geocoding request failed gracefully:', err);
    return [];
  }
}

/**
 * Formats coordinates with optional explicit Latitude and Longitude labels and directional markers.
 * When labeled option is provided, explicitly prepends Lat and Lon labels.
 * By default returns standard geographical notation with hemisphere direction (e.g. "35.6892° N, 51.3890° E").
 */
export function formatCoordinates(
  lat: number,
  lon: number,
  options?: { labeled?: boolean; compact?: boolean },
): string {
  if (typeof lat !== 'number' || typeof lon !== 'number' || isNaN(lat) || isNaN(lon)) {
    if (options?.labeled) {
      return options?.compact ? 'Lat: 0.0000° N, Lon: 0.0000° E' : 'عرض (Lat): 0.0000° N | طول (Lon): 0.0000° E';
    }
    return '0.0000° N, 0.0000° E';
  }
  const latDir = lat >= 0 ? 'N' : 'S';
  const lonDir = lon >= 0 ? 'E' : 'W';
  const latStr = `${Math.abs(lat).toFixed(4)}° ${latDir}`;
  const lonStr = `${Math.abs(lon).toFixed(4)}° ${lonDir}`;

  if (options?.labeled) {
    if (options?.compact) {
      return `Lat: ${latStr}, Lon: ${lonStr}`;
    }
    return `عرض (Lat): ${latStr} | طول (Lon): ${lonStr}`;
  }
  return `${latStr}, ${lonStr}`;
}


