import type {
  CellConcordancePayload,
  CellObservationPayload,
  CellPersistencePayload,
  SpatialCellPayload,
  SpatialSectionPayload,
  SpatialSummaryPayload,
} from '../../types/index.ts';
import { asArray, asRecord, isFiniteNumber } from './parse.ts';

/**
 * Spatial visualization mapping (UI-2 presentation layer).
 *
 * Pure read-only helpers over the P5.3-S spatial section of the
 * Agriculture /analysis response. Backend records are narrowed for
 * display in response order; nothing is computed, interpolated, or
 * reclassified here. Geometry passes through verbatim when it is a
 * valid Polygon, otherwise the cell is listed without a map shape.
 * Nulls stay null. Absent sections yield empty results.
 */

/** Grid cells in backend order; unshaped rows omitted. */
export function spatialCells(
  spatial: SpatialSectionPayload | null | undefined,
): SpatialCellPayload[] {
  if (!spatial || typeof spatial !== 'object') return [];
  const out: SpatialCellPayload[] = [];
  for (const entry of asArray((spatial as { cells?: unknown }).cells)) {
    const record = asRecord(entry);
    if (!record || typeof record.cell_id !== 'string') continue;
    out.push(entry as SpatialCellPayload);
  }
  return out;
}

/** Cell observations in backend order; unshaped rows omitted. */
export function spatialObservations(
  spatial: SpatialSectionPayload | null | undefined,
): CellObservationPayload[] {
  if (!spatial || typeof spatial !== 'object') return [];
  const out: CellObservationPayload[] = [];
  for (const entry of asArray((spatial as { observations?: unknown }).observations)) {
    const record = asRecord(entry);
    if (!record || typeof record.cell_id !== 'string') continue;
    if (typeof record.metric_key !== 'string') continue;
    out.push(entry as CellObservationPayload);
  }
  return out;
}

/** Per-metric summaries in backend key order. */
export function spatialSummaries(
  spatial: SpatialSectionPayload | null | undefined,
): SpatialSummaryPayload[] {
  if (!spatial || typeof spatial !== 'object') return [];
  const summaries = asRecord((spatial as { summaries?: unknown }).summaries);
  if (!summaries) return [];
  const out: SpatialSummaryPayload[] = [];
  for (const summary of Object.values(summaries)) {
    const record = asRecord(summary);
    if (!record || typeof record.metric_key !== 'string') continue;
    out.push(summary as SpatialSummaryPayload);
  }
  return out;
}

/** Verbatim limitation strings; non-strings omitted. */
export function spatialLimitations(
  spatial: SpatialSectionPayload | null | undefined,
): string[] {
  if (!spatial || typeof spatial !== 'object') return [];
  return asArray((spatial as { limitations?: unknown }).limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

/** Observations belonging to one cell, in backend order. */
export function observationsForCell(
  observations: CellObservationPayload[],
  cellId: string,
): CellObservationPayload[] {
  return (Array.isArray(observations) ? observations : []).filter(
    (item) => item && item.cell_id === cellId,
  );
}

/** Concordance record for one cell, or null when absent. */
export function concordanceForCell(
  spatial: SpatialSectionPayload | null | undefined,
  cellId: string,
): CellConcordancePayload | null {
  if (!spatial || typeof spatial !== 'object') return null;
  for (const entry of asArray((spatial as { concordance?: unknown }).concordance)) {
    const record = asRecord(entry);
    if (!record || record.cell_id !== cellId) continue;
    return entry as CellConcordancePayload;
  }
  return null;
}

/** Persistence record for one cell, or null when absent. */
export function persistenceForCell(
  spatial: SpatialSectionPayload | null | undefined,
  cellId: string,
): CellPersistencePayload | null {
  if (!spatial || typeof spatial !== 'object') return null;
  for (const entry of asArray((spatial as { persistence?: unknown }).persistence)) {
    const record = asRecord(entry);
    if (!record || record.cell_id !== cellId) continue;
    return entry as CellPersistencePayload;
  }
  return null;
}

/** Exact metric keys present in observations or summaries, sorted. */
export function distinctSpatialMetrics(
  spatial: SpatialSectionPayload | null | undefined,
): string[] {
  const keys = new Set<string>();
  for (const item of spatialObservations(spatial)) {
    if (item.metric_key) keys.add(item.metric_key);
  }
  for (const summary of spatialSummaries(spatial)) {
    if (summary.metric_key) keys.add(summary.metric_key);
  }
  return [...keys].sort();
}

/** Exact concordance states present, sorted. No reclassification. */
export function distinctConcordanceStates(
  spatial: SpatialSectionPayload | null | undefined,
): string[] {
  if (!spatial || typeof spatial !== 'object') return [];
  const states = new Set<string>();
  for (const entry of asArray((spatial as { concordance?: unknown }).concordance)) {
    const record = asRecord(entry);
    if (record && typeof record.state === 'string' && record.state) {
      states.add(record.state);
    }
  }
  return [...states].sort();
}

/** True only for finite numbers; used to validate cell bounds. */
function isBound(value: unknown): value is number {
  return isFiniteNumber(value);
}

/**
 * A cell as a GeoJSON Feature when its geometry is a valid
 * Polygon, otherwise null. The ring coordinates travel verbatim;
 * nothing is projected, simplified, or invented.
 */
export function cellPolygonFeature(
  cell: SpatialCellPayload | null | undefined,
): GeoJSON.Feature<GeoJSON.Polygon> | null {
  const record = asRecord(cell);
  if (!record || typeof record.cell_id !== 'string') return null;
  const geometry = asRecord(record.geometry);
  if (!geometry || geometry.type !== 'Polygon') return null;
  if (!Array.isArray(geometry.coordinates)) return null;
  const polygon = {
    type: 'Polygon',
    coordinates: geometry.coordinates,
  } as GeoJSON.Polygon;
  return {
    type: 'Feature',
    geometry: polygon,
    properties: { cell_id: record.cell_id },
  };
}

/** Map center from the backend bbox, or null when unusable. */
export function spatialMapCenter(
  spatial: SpatialSectionPayload | null | undefined,
): [number, number] | null {
  if (!spatial || typeof spatial !== 'object') return null;
  const bbox = (spatial as { bbox?: unknown }).bbox;
  if (!Array.isArray(bbox) || bbox.length < 4) return null;
  const [west, south, east, north] = bbox;
  if (!isBound(west) || !isBound(south) || !isBound(east) || !isBound(north)) {
    return null;
  }
  return [(west + east) / 2, (south + north) / 2];
}

/** Backend state vocabularies stay descriptive; counts are never grades. */
export const SPATIAL_STATE_VALUES = {
  concentration: ['NORMAL_AREA', 'ANOMALOUS_AREA', 'CONCENTRATED_ANOMALY', 'INSUFFICIENT'],
  concordance: [
    'MULTI_METRIC_ANOMALY',
    'SINGLE_METRIC_ANOMALY',
    'MIXED_METRICS',
    'NO_CONCORDANCE',
    'INSUFFICIENT',
  ],
  persistence: ['PERSISTENT', 'NONE', 'INSUFFICIENT'],
};

/** Render the spatial state as neutral terminology */
export function spatialStateLabel(state: string): string {
  switch (state) {
    case 'NORMAL_AREA':
      return 'Normal area';
    case 'ANOMALOUS_AREA':
      return 'Anomalous area';
    case 'CONCENTRATED_ANOMALY':
      return 'Concentrated anomaly';
    case 'INSUFFICIENT':
      return 'Insufficient evidence';
    default:
      return state;
  }
}

/** Render the concordance state as neutral terminology */
export function concordanceStateLabel(state: string): string {
  switch (state) {
    case 'MULTI_METRIC_ANOMALY':
      return 'Multi-metric anomaly';
    case 'SINGLE_METRIC_ANOMALY':
      return 'Single-metric anomaly';
    case 'MIXED_METRICS':
      return 'Mixed metrics';
    case 'NO_CONCORDANCE':
      return 'No concordance';
    case 'INSUFFICIENT':
      return 'Insufficient';
    default:
      return state;
  }
}

/** Render the persistence state */
export function persistenceStateLabel(state: string): string {
  switch (state) {
    case 'PERSISTENT':
      return 'Persistent';
    case 'NONE':
      return 'None';
    case 'INSUFFICIENT':
      return 'Insufficient';
    default:
      return state;
  }
}
