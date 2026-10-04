import type {
  ClassHistogramDTO,
  ClassHistogramEntryDTO,
  SpatialStatsDTO,
} from '../../types/index.ts';
import { isFiniteNumber } from './parse.ts';

/**
 * F3-B semantic maps + pure helpers for the F3-A structured fields.
 *
 * The three structured fields (`stats`, `class_histogram`, `band_means`)
 * are NOT interchangeable: source audit proved that `stats` truthfully
 * describes the reported quantity only for some metrics, carries
 * across-time figures for others, and describes a different quantity for
 * a third group. These explicit maps — never a generic "if stats exists"
 * check — decide which renderer may consume an item.
 *
 * No JSX here so `node --test` can exercise this module directly.
 * No network, no API calls, no warning-string parsing.
 */

/** Type-A: stats truthfully describe the spatial spread of the value. */
const TYPE_A_KEYS: ReadonlySet<string> = new Set([
  // Vegetation — median composite, then spatial mean.
  'ndvi',
  'evi',
  'savi',
  'msavi',
  'ndre',
  'lai',
  'fapar',
  'fcover',
  // Thermal — converted same-quantity spatial stats.
  'land_surface_temperature_day',
  'land_surface_temperature_night',
  'land_surface_temperature_mean',
  'landsat_surface_temperature',
  // Thermal — per-quantile day-night differences (provenance-caveated).
  'surface_temperature_range',
  // Climate — spatial stats of the ERA5 time-mean image.
  'precipitation',
  'temperature_max',
  'temperature_min',
  'temperature_mean',
  'solar_radiation',
  // Climate — same spatial stats, proxy measurement basis.
  'par',
  // Soil — same-quantity spatial stats (ERA5 variant is a
  // thickness-weighted layer merge; value == combined.mean).
  'soil_moisture_surface',
  'soil_moisture_surface_evening',
  'soil_moisture_rootzone',
  'soil_moisture_rootzone_era5',
  'soil_moisture_wetness',
  'root_zone_soil_moisture_gldas',
  // Soil properties — static-surface same-quantity stats.
  'soil_field_capacity',
  'soil_wilting_point',
  'soil_available_water_capacity',
  'soil_temperature_0_7cm',
  'soil_temperature_7_28cm',
  // Water — MOD16 same-quantity spatial stats.
  'evapotranspiration',
  'potential_evapotranspiration',
  // Terrain — same-quantity spatial stats.
  'elevation',
  'slope',
]);

/**
 * Type-B: synthetic stats whose mean equals the value but whose
 * min/max/counts are across-time figures, NOT spatial spread.
 * The label selects the truthful temporal wording.
 */
const TYPE_B_LABELS: Readonly<Record<string, 'daily' | 'composite'>> = {
  evapotranspiration_cumulative: 'composite',
  era5_evaporation: 'daily',
  wind_speed: 'daily',
  vpd: 'daily',
  relative_humidity: 'daily',
  gdd: 'daily',
};

/** S3: binary-masks stats in 0-100 units; value is the share fraction. */
const CROP_SHARE_KEYS: ReadonlySet<string> = new Set([
  'temporary_crop_context',
  'maize_context',
  'cereal_context',
  'temporary_crop_area',
]);

/** H: categorical metrics carrying a class histogram. */
const HISTOGRAM_KEYS: ReadonlySet<string> = new Set([
  'land_cover_class',
  'land_cover_quality',
]);

/** The Dynamic World probability metric — the only band_means source. */
export const DYNAMIC_WORLD_METRIC = 'land_cover_probability';

/** The nine canonical probability bands, in documented order. */
export const DYNAMIC_WORLD_BANDS = [
  'water',
  'trees',
  'grass',
  'flooded_vegetation',
  'crops',
  'shrub_and_scrub',
  'built',
  'bare',
  'snow_and_ice',
] as const;

export type DynamicWorldBand = (typeof DYNAMIC_WORLD_BANDS)[number];

/**
 * Dominant-reporting floor: engine reporting convention (not a
 * scientific probability boundary). Shown as explanatory text only.
 */
export const DYNAMIC_WORLD_DOMINANT_FLOOR = 0.4;

/** True when S1 (spatial spread detail) may render for this key. */
export function isSpatialStatsMetric(metricKey: string): boolean {
  return TYPE_A_KEYS.has(metricKey);
}

/** 'daily' | 'composite' when S2 may render, else null. */
export function temporalRangeKind(metricKey: string): 'daily' | 'composite' | null {
  return TYPE_B_LABELS[metricKey] ?? null;
}

/** True when S3 (classified-share detail) may render for this key. */
export function isCropShareMetric(metricKey: string): boolean {
  return CROP_SHARE_KEYS.has(metricKey);
}

/** True when the histogram detail may render for this key. */
export function isHistogramMetric(metricKey: string): boolean {
  return HISTOGRAM_KEYS.has(metricKey);
}

/** True only for the Dynamic World probability metric. */
export function isDynamicWorldMetric(metricKey: string): boolean {
  return metricKey === DYNAMIC_WORLD_METRIC;
}

export interface StatRow {
  key: string;
  labelFa: string;
  labelEn: string;
  value: number;
}

/** S1 distribution fields in the frozen display order. */
const STAT_FIELD_ORDER: ReadonlyArray<{
  key: keyof SpatialStatsDTO;
  labelFa: string;
  labelEn: string;
}> = [
  { key: 'mean', labelFa: 'میانگین', labelEn: 'mean' },
  { key: 'median', labelFa: 'میانه', labelEn: 'median' },
  { key: 'min', labelFa: 'کمینه', labelEn: 'min' },
  { key: 'max', labelFa: 'بیشینه', labelEn: 'max' },
  { key: 'std_dev', labelFa: 'انحراف معیار', labelEn: 'std dev' },
  { key: 'p10', labelFa: 'صدک ۱۰', labelEn: 'p10' },
  { key: 'p25', labelFa: 'صدک ۲۵', labelEn: 'p25' },
  { key: 'p75', labelFa: 'صدک ۷۵', labelEn: 'p75' },
  { key: 'p90', labelFa: 'صدک ۹۰', labelEn: 'p90' },
];

/** S1 secondary coverage metadata, in display order. */
const COVERAGE_FIELD_ORDER: ReadonlyArray<{
  key: keyof SpatialStatsDTO;
  labelFa: string;
  labelEn: string;
}> = [
  { key: 'coverage_percent', labelFa: 'پوشش', labelEn: 'coverage' },
  { key: 'valid_pixel_count', labelFa: 'پیکسل معتبر', labelEn: 'valid pixels' },
  { key: 'total_pixel_count', labelFa: 'کل پیکسل', labelEn: 'total pixels' },
  { key: 'missing_pixel_count', labelFa: 'پیکسل فاقد داده', labelEn: 'missing pixels' },
  { key: 'missing_percent', labelFa: 'درصد فاقد داده', labelEn: 'missing' },
  { key: 'valid_area_sq_m', labelFa: 'مساحت معتبر (متر مربع)', labelEn: 'valid area (m²)' },
];

/** Non-null S1 distribution rows in frozen order. Nulls are omitted. */
export function spatialStatRows(stats: SpatialStatsDTO | null | undefined): StatRow[] {
  if (!stats || typeof stats !== 'object') return [];
  const rows: StatRow[] = [];
  for (const field of STAT_FIELD_ORDER) {
    const value: unknown = stats[field.key];
    if (isFiniteNumber(value)) {
      rows.push({ key: field.key, labelFa: field.labelFa, labelEn: field.labelEn, value });
    }
  }
  return rows;
}

/** Non-null S1 coverage rows in frozen order. Nulls are omitted. */
export function coverageRows(stats: SpatialStatsDTO | null | undefined): StatRow[] {
  if (!stats || typeof stats !== 'object') return [];
  const rows: StatRow[] = [];
  for (const field of COVERAGE_FIELD_ORDER) {
    const value: unknown = stats[field.key];
    if (isFiniteNumber(value)) {
      rows.push({ key: field.key, labelFa: field.labelFa, labelEn: field.labelEn, value });
    }
  }
  return rows;
}

export interface TemporalRange {
  kind: 'daily' | 'composite';
  min: number;
  max: number;
}

/**
 * S2 range — min/max only, and only for Type-B keys. Returns null when
 * the key is not Type-B or either bound is missing. Never exposes
 * coverage/pixel fields (they count days/composites, not pixels).
 */
export function temporalRange(
  metricKey: string,
  stats: SpatialStatsDTO | null | undefined,
): TemporalRange | null {
  const kind = temporalRangeKind(metricKey);
  if (!kind || !stats || typeof stats !== 'object') return null;
  if (!isFiniteNumber(stats.min) || !isFiniteNumber(stats.max)) return null;
  return { kind, min: stats.min, max: stats.max };
}

export interface CropShare {
  /** Share of the classified area, 0-100. */
  percent: number;
}

/**
 * S3 share — derived ONLY from stats.mean (mask units 0-100, the same
 * conversion the backend formula documents). Distribution fields are
 * never exposed: min/max/percentiles of a binary mask are artifacts.
 */
export function cropShare(
  metricKey: string,
  stats: SpatialStatsDTO | null | undefined,
): CropShare | null {
  if (!isCropShareMetric(metricKey)) return null;
  if (!stats || typeof stats !== 'object') return null;
  if (!isFiniteNumber(stats.mean)) return null;
  return { percent: stats.mean / 100.0 };
}

export interface HistogramRow {
  code: number;
  name: string;
  pixel_count: number;
  percent: number;
  percent_of_geometry: number;
}

/**
 * H rows — present classes sorted by percent descending (stable).
 * Never fabricates rows; never converts pixels to area.
 */
export function histogramRows(
  histogram: ClassHistogramDTO | null | undefined,
): HistogramRow[] {
  if (!histogram || typeof histogram !== 'object') return [];
  const entries: unknown = histogram.entries;
  if (!Array.isArray(entries)) return [];
  const rows: HistogramRow[] = [];
  for (const entry of entries) {
    const record = entry as Partial<ClassHistogramEntryDTO> | null;
    if (!record || typeof record !== 'object' || typeof record.code !== 'number') continue;
    rows.push({
      code: record.code,
      name: typeof record.name === 'string' ? record.name : '',
      pixel_count: isFiniteNumber(record.pixel_count) ? record.pixel_count : 0,
      percent: isFiniteNumber(record.percent) ? record.percent : 0,
      percent_of_geometry: isFiniteNumber(record.percent_of_geometry)
        ? record.percent_of_geometry
        : 0,
    });
  }
  return rows.sort((a, b) => b.percent - a.percent);
}

/** P2A presentation input: the categorical land-cover evidence item. */
export interface ClassShareInput {
  metric_key?: string;
  class_histogram?: ClassHistogramDTO | null;
}

/**
 * P2A presentation model for the land-cover class shares.
 *
 * Everything returned here is transported by the response itself:
 * class code + backend-provided taxonomy name, both supplied ratios,
 * and the response's own dominant class. Pixels are never converted
 * to area — this contract carries no geometry, so no km² figure is
 * derivable and none is produced.
 */
export interface ClassShareModel {
  rows: HistogramRow[];
  dominant: HistogramRow | null;
  /** True when the response carried a distribution at all (even an empty one). */
  carried: boolean;
  valid_pixel_count: number | null;
  total_pixel_count: number | null;
}

/** Shares for `land_cover_class` only; every other key yields an empty model. */
export function classShareModel(
  item: ClassShareInput | null | undefined,
): ClassShareModel {
  const empty: ClassShareModel = {
    rows: [],
    dominant: null,
    carried: false,
    valid_pixel_count: null,
    total_pixel_count: null,
  };
  if (!item || typeof item !== 'object') return empty;
  if (item.metric_key !== 'land_cover_class') return empty;
  const distribution = item.class_histogram;
  const rows = histogramRows(distribution);
  if (rows.length === 0) {
    return {
      ...empty,
      carried: distribution !== null && distribution !== undefined,
      valid_pixel_count:
        distribution && isFiniteNumber(distribution.valid_pixel_count)
          ? distribution.valid_pixel_count
          : null,
      total_pixel_count:
        distribution && isFiniteNumber(distribution.total_pixel_count)
          ? distribution.total_pixel_count
          : null,
    };
  }
  const dominantCode =
    distribution && isFiniteNumber(distribution.dominant_code)
      ? distribution.dominant_code
      : null;
  const dominant =
    dominantCode !== null
      ? (rows.find((row) => row.code === dominantCode) ?? rows[0])
      : rows[0];
  return {
    rows,
    dominant,
    carried: true,
    valid_pixel_count:
      distribution && isFiniteNumber(distribution.valid_pixel_count)
        ? distribution.valid_pixel_count
        : null,
    total_pixel_count:
      distribution && isFiniteNumber(distribution.total_pixel_count)
        ? distribution.total_pixel_count
        : null,
  };
}

/**
 * P2A: dominant class label for the scalar grid — `Name (code)` when
 * the response carries land-cover class shares, otherwise null so the
 * ordinary scalar/unavailable branches keep deciding. The class key is
 * categorical: without this it would render an "unavailable" card
 * while the same response carries its full class shares.
 */
export function dominantClassLabel(
  item: ClassShareInput | null | undefined,
): string | null {
  const model = classShareModel(item);
  if (model.dominant === null) return null;
  const { dominant } = model;
  return `${dominant.name || dominant.code} (${dominant.code})`;
}

export interface BandRow {
  band: DynamicWorldBand;
  value: number | null;
}

/**
 * DW rows — exactly the nine canonical bands (unknown keys, including
 * any argmax/label key, are dropped structurally). Non-null values sort
 * descending; nulls go last in canonical order.
 */
export function bandRows(
  bandMeans: Record<string, number | null> | null | undefined,
): BandRow[] {
  if (!bandMeans || typeof bandMeans !== 'object') return [];
  const present = DYNAMIC_WORLD_BANDS.filter((band) =>
    Object.prototype.hasOwnProperty.call(bandMeans, band),
  );
  if (present.length === 0) return [];
  const rows: BandRow[] = DYNAMIC_WORLD_BANDS.filter((band) =>
    present.includes(band),
  ).map((band) => {
    const raw: unknown = (bandMeans as Record<string, unknown>)[band];
    return { band, value: isFiniteNumber(raw) ? raw : null };
  });
  const ranked = rows.filter((row) => row.value !== null) as Array<{
    band: DynamicWorldBand;
    value: number;
  }>;
  ranked.sort((a, b) => b.value - a.value);
  const missing = rows.filter((row) => row.value === null);
  return [...ranked, ...missing];
}
