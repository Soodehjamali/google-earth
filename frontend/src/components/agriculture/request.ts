import type {
  AgricultureAnalysisRequest,
  AgricultureGeometry,
  GroundTruthObservationInput,
} from '../../types/index.ts';

/**
 * Locked Comprehensive API domain names (Phase 0B §2).
 * API spelling is authoritative here — notably `historical`
 * (the internal metric registry uses `history`; the bridge
 * historical → history → historical lives in the backend).
 */
export const API_DOMAINS = [
  'vegetation',
  'water',
  'thermal',
  'soil',
  'climate',
  'crop',
  'phenology',
  'productivity',
  'historical',
  'terrain',
  'landcover',
  'stress',
  'irrigation',
] as const;

export type ApiDomain = (typeof API_DOMAINS)[number];

const API_DOMAIN_SET: ReadonlySet<string> = new Set(API_DOMAINS);

/**
 * Primary-route → `domains[]` payload mapping (Phase 0B §13).
 * F2 domain pages send exactly these values.
 */
export const DOMAIN_ROUTE_PAYLOADS: Record<string, ApiDomain[]> = {
  '/agriculture/vegetation': ['vegetation'],
  '/agriculture/phenology': ['phenology', 'productivity'],
  // P4: `thermal` travels with `climate` because the backend builds
  // `temporal.thermal_profiles.temperature_mean` only when the
  // requested domains include `thermal`.
  '/agriculture/climate': ['climate', 'thermal'],
  '/agriculture/water': ['water'],
  '/agriculture/soil': ['soil'],
  '/agriculture/thermal': ['thermal'],
  '/agriculture/terrain': ['terrain'],
  '/agriculture/land-crop': ['landcover', 'crop'],
  '/agriculture/stress-irrigation': ['stress', 'irrigation'],
  '/agriculture/history': ['historical'],
};

/**
 * Workspace domain group (Prompt 3). One user-facing toggle that maps to
 * one or more locked `domains[]` payload values. `metrics` is an
 * informational list of the group's real metric keys (taken from the
 * locked domain configs) — it is displayed only and never sent to the
 * backend, because the current contract has no metric-level selection.
 */
export interface DomainGroupOption {
  key: string;
  label: string;
  labelFa: string;
  icon: string;
  domains: ApiDomain[];
  metrics: string[];
}

export const CLOUD_DEFAULT = 20;
export const CLOUD_MIN = 0;
export const CLOUD_MAX = 100;

/** Clamp any input to the backend-accepted cloud range (0–100). */
export function clampCloudPercent(raw: unknown): number {
  const n = typeof raw === 'string' ? parseFloat(raw) : raw;
  if (typeof n !== 'number' || Number.isNaN(n)) return CLOUD_DEFAULT;
  if (n < CLOUD_MIN) return CLOUD_MIN;
  if (n > CLOUD_MAX) return CLOUD_MAX;
  return n;
}

/** Keep only valid locked API domain names, deduplicated and sorted. */
export function normalizeSelectedDomains(selected: readonly unknown[]): ApiDomain[] {
  const valid = new Set<ApiDomain>();
  for (const entry of selected) {
    if (typeof entry === 'string' && API_DOMAIN_SET.has(entry)) {
      valid.add(entry as ApiDomain);
    }
  }
  return [...valid].sort();
}

export interface AnalysisInputs {
  geometry: AgricultureGeometry;
  start_date: string;
  end_date: string;
  selectedDomains: readonly unknown[];
  cloud_max_percent: unknown;
  groundTruth?: readonly GroundTruthObservationInput[];
}

/**
 * Reference-observation vocabularies (P6.1 contract mirrors).
 * The backend ingestion boundary is authoritative; these lists only
 * drive form dropdowns and light client-side checks.
 */
export const REFERENCE_VARIABLES = [
  'observed_stress',
  'observed_damage',
  'observed_disease',
  'observed_pest_presence',
  'observed_pest_absence',
  'observed_management_event',
  'unknown',
  'not_assessed',
] as const;

export const REFERENCE_SOURCES = [
  'field_observation',
  'laboratory_result',
  'agronomist_observation',
  'farmer_observation',
  'uav_derived_observation',
  'manually_verified_reference',
] as const;

export const REFERENCE_STATES = [
  'present',
  'absent',
  'unknown',
  'not_assessed',
] as const;

const REFERENCE_VARIABLE_SET: ReadonlySet<string> = new Set(REFERENCE_VARIABLES);
const REFERENCE_SOURCE_SET: ReadonlySet<string> = new Set(REFERENCE_SOURCES);
const REFERENCE_STATE_SET: ReadonlySet<string> = new Set(REFERENCE_STATES);

/** Blank reference-observation draft for the optional form section. */
export function blankGroundTruthDraft(): GroundTruthObservationInput {
  return {
    observation_id: '',
    variable: 'observed_stress',
    value: null,
    unit: '',
    state: null,
    observed_on: '',
    source: 'field_observation',
    method: '',
    metric_key: null,
    cell_id: null,
    window_start: null,
    window_end: null,
  };
}

/**
 * Light client-side check mirroring the backend refusal rules.
 * Returns an error message or null when the draft is submittable.
 * The backend remains authoritative: usable-looking records may
 * still be reported as rejected, which the UI renders as-is.
 */
export function validateGroundTruthDraft(
  draft: GroundTruthObservationInput,
): string | null {
  if (!draft.variable || !REFERENCE_VARIABLE_SET.has(draft.variable)) {
    return 'نامعتبر — Unknown variable';
  }
  const hasValue =
    typeof draft.value === 'number' && Number.isFinite(draft.value);
  const hasState =
    typeof draft.state === 'string' &&
    draft.state.length > 0 &&
    REFERENCE_STATE_SET.has(draft.state);
  if (!hasValue && !hasState) {
    return 'مقدار یا وضعیت لازم است — Value or state required';
  }
  if (typeof draft.state === 'string' && draft.state.length > 0 && !hasState) {
    return 'نامعتبر — Unknown state';
  }
  if (!draft.observed_on || !/^\d{4}-\d{2}-\d{2}$/.test(draft.observed_on)) {
    return 'تاریخ مشاهده لازم است — Observation date (YYYY-MM-DD) required';
  }
  if (!draft.source || !REFERENCE_SOURCE_SET.has(draft.source)) {
    return 'نامعتبر — Unknown source';
  }
  if (!draft.method || draft.method.trim().length === 0) {
    return 'روش لازم است — Method required';
  }
  return null;
}

/**
 * Normalize a validated draft to the backend record shape.
 * Drops empty optional strings (never sends invalid empty objects);
 * nulls for value/state stay null so the backend sees them as absent.
 */
export function toGroundTruthRecord(
  draft: GroundTruthObservationInput,
  fallbackId: string,
): GroundTruthObservationInput {
  const record: GroundTruthObservationInput = {
    observation_id:
      draft.observation_id && draft.observation_id.trim().length > 0
        ? draft.observation_id.trim()
        : fallbackId,
    variable: draft.variable,
    value:
      typeof draft.value === 'number' && Number.isFinite(draft.value)
        ? draft.value
        : null,
    state:
      typeof draft.state === 'string' && draft.state.length > 0
        ? draft.state
        : null,
    observed_on: draft.observed_on,
    source: draft.source,
    method: draft.method && draft.method.trim().length > 0 ? draft.method.trim() : '',
  };
  if (draft.unit && draft.unit.trim().length > 0) record.unit = draft.unit.trim();
  if (draft.window_start) record.window_start = draft.window_start;
  if (draft.window_end) record.window_end = draft.window_end;
  if (draft.metric_key && draft.metric_key.trim().length > 0) {
    record.metric_key = draft.metric_key.trim();
  }
  if (draft.cell_id && draft.cell_id.trim().length > 0) {
    record.cell_id = draft.cell_id.trim();
  }
  if (typeof draft.latitude === 'number' && Number.isFinite(draft.latitude)) {
    record.latitude = draft.latitude;
  }
  if (typeof draft.longitude === 'number' && Number.isFinite(draft.longitude)) {
    record.longitude = draft.longitude;
  }
  return record;
}

/**
 * P4 climate thermal routing: the backend builds the air-temperature
 * temporal profile (`temporal.thermal_profiles.temperature_mean`) only
 * when `thermal` is among the requested domains, so every explicit
 * selection containing `climate` also carries `thermal`. The locked
 * all-selected/empty behaviour is untouched: those requests still omit
 * `domains`.
 */
function withClimateThermalDomains(domains: ApiDomain[]): ApiDomain[] {
  if (!domains.includes('climate') || domains.includes('thermal')) {
    return domains;
  }
  return normalizeSelectedDomains([...domains, 'thermal']);
}

/**
 * Build a Comprehensive analysis request.
 *
 * NEVER emits `domains: []` — the backend treats `[]` as "all domains",
 * so "all selected" is represented by omitting `domains` (undefined),
 * per the existing client contract and Phase 0B §4.
 *
 * `ground_truth` is attached only when a non-empty validated list is
 * supplied; otherwise the field is omitted so the request — and the
 * backend behavior — is exactly as before.
 */
export function buildAgricultureRequest(
  inputs: AnalysisInputs,
): AgricultureAnalysisRequest {
  const valid = withClimateThermalDomains(
    normalizeSelectedDomains(inputs.selectedDomains),
  );
  const allSelected =
    valid.length === 0 || valid.length === API_DOMAINS.length;
  const request: AgricultureAnalysisRequest = {
    geometry: inputs.geometry,
    start_date: inputs.start_date,
    end_date: inputs.end_date,
    cloud_max_percent: clampCloudPercent(inputs.cloud_max_percent),
  };
  if (!allSelected) {
    request.domains = valid;
  }
  if (Array.isArray(inputs.groundTruth) && inputs.groundTruth.length > 0) {
    request.ground_truth = [...inputs.groundTruth];
  }
  return request;
}

/** Frontend pre-validation. Returns an error message or null when valid. */
export function validateAnalysisInputs(
  geometry: AgricultureGeometry | undefined,
  start_date: string,
  end_date: string,
): string | null {
  if (!geometry) return 'مختصات نامعتبر — Invalid coordinates';
  if (!start_date || !end_date) return 'بازه زمانی را وارد کنید — Date range required';
  // YYYY-MM-DD strings compare lexicographically.
  if (end_date <= start_date) return 'تاریخ پایان باید بعد از تاریخ شروع باشد';
  return null;
}

export type GeometryInput = 'gps' | 'geojson';

export type GeometryParseResult =
  | { geometry: AgricultureGeometry }
  | { error: string };

/** GPS parsing — same mechanism as the existing hub (Point, [lng, lat]). */
export function parseGpsInput(latitude: string, longitude: string): GeometryParseResult {
  const lat = parseFloat(latitude);
  const lng = parseFloat(longitude);
  if (Number.isNaN(lat) || Number.isNaN(lng)) {
    return { error: 'مختصات نامعتبر — Invalid coordinates' };
  }
  if (lat < -90 || lat > 90) {
    return { error: 'عرض جغرافیایی باید بین -90 تا 90 باشد' };
  }
  if (lng < -180 || lng > 180) {
    return { error: 'طول جغرافیایی باید بین -180 تا 180 باشد' };
  }
  return { geometry: { type: 'Point', coordinates: [lng, lat] } };
}

function isPointLike(value: unknown): value is AgricultureGeometry {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return record.type === 'Point' && Array.isArray(record.coordinates);
}

function isPolygonLike(value: unknown): value is AgricultureGeometry {
  if (typeof value !== 'object' || value === null) return false;
  const record = value as Record<string, unknown>;
  return record.type === 'Polygon' && Array.isArray(record.coordinates);
}

/** GeoJSON parsing — Point or Polygon (or Feature wrapping one). No new format. */
export function parseGeoJsonInput(raw: string): GeometryParseResult {
  if (!raw.trim()) return { error: 'GeoJSON را وارد کنید' };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { error: 'GeoJSON نامعتبر — Invalid JSON' };
  }
  if (typeof parsed === 'object' && parsed !== null) {
    const record = parsed as Record<string, unknown>;
    if (record.type === 'Feature' && isPointLike(record.geometry)) {
      return { geometry: record.geometry };
    }
    if (record.type === 'Feature' && isPolygonLike(record.geometry)) {
      return { geometry: record.geometry };
    }
  }
  if (isPointLike(parsed) || isPolygonLike(parsed)) {
    return { geometry: parsed };
  }
  return { error: 'نوع هندسه پشتیبانی نمی‌شود — Only Point and Polygon are supported' };
}
