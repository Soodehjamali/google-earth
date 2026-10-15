/**
 * Point-support presentation (F-A12 product acceptance).
 *
 * A GeoJSON Point has no area, so the backend reduces each dataset over
 * a support region sized from that dataset's own grid, or reads the one
 * containing pixel for coarse reanalysis products. The user must be able
 * to see which of the two a number is. This module only turns the
 * disclosure fields the backend returned into display text; it never
 * decides a radius, never infers one, and returns null when the backend
 * disclosed nothing (a Polygon request, or a result the policy did not
 * govern), so absence stays meaningful.
 */
import type { ProvenanceResponse, SupportInputDTO } from '../../types/index.ts';

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export type SupportKind = 'window' | 'pixel';

export interface SupportInfo {
  kind: SupportKind;
  /** Support radius in metres; 0 for a containing-pixel read. */
  radiusM: number;
  areaSqM: number;
  nativeResolutionM: number | null;
  family: string | null;
  policy: string | null;
  /** Regional / district-scale product: not a field-level measurement. */
  regionalScale: boolean;
  /** Short badge text, e.g. "Area around point · r 60 m". */
  badgeEn: string;
  badgeFa: string;
  /** One concise sentence saying what the value describes. */
  explanationEn: string;
  explanationFa: string;
  /** Original request coordinate as "lat, lng" when disclosed. */
  originalPoint: string | null;
  /** Every support region a derived value was built from, if more than one. */
  inputs: SupportInputDTO[];
}

/** "60 m" / "1.5 km". */
export function formatDistance(metres: number): string {
  if (!isFiniteNumber(metres)) return '—';
  if (metres >= 1000) {
    const km = metres / 1000;
    return `${Number.isInteger(km) ? km : km.toFixed(1)} km`;
  }
  return `${Number.isInteger(metres) ? metres : metres.toFixed(0)} m`;
}

/** "11,310 m² (1.13 ha)" / "7.07 km²". */
export function formatArea(sqMetres: number): string {
  if (!isFiniteNumber(sqMetres)) return '—';
  if (sqMetres >= 1_000_000) {
    return `${(sqMetres / 1_000_000).toFixed(2)} km²`;
  }
  const grouped = Math.round(sqMetres).toLocaleString('en-US');
  const hectares = sqMetres / 10_000;
  return hectares >= 0.1
    ? `${grouped} m² (${hectares.toFixed(2)} ha)`
    : `${grouped} m²`;
}

const REGIONAL_FAMILIES: ReadonlySet<string> = new Set(['soil', 'regional', 'coarse']);

function originalPointText(provenance: ProvenanceResponse): string | null {
  const geo = provenance.original_geometry;
  if (!geo || geo.type !== 'Point' || !Array.isArray(geo.coordinates)) return null;
  const [lng, lat] = geo.coordinates as unknown[];
  if (!isFiniteNumber(lat) || !isFiniteNumber(lng)) return null;
  return `${lat}, ${lng}`;
}

/**
 * What a value describes, from the backend's own disclosure fields.
 * Returns null when no Point-support disclosure is present.
 */
export function supportInfoOf(
  provenance: ProvenanceResponse | null | undefined,
): SupportInfo | null {
  if (!provenance || typeof provenance !== 'object') return null;
  if (provenance.geometry_type !== 'Point') return null;
  const radius = provenance.support_radius_m;
  if (!isFiniteNumber(radius)) return null;
  const area = isFiniteNumber(provenance.support_area_sq_m)
    ? provenance.support_area_sq_m
    : 0;
  const native = isFiniteNumber(provenance.support_native_resolution_m)
    ? provenance.support_native_resolution_m
    : null;
  const family = provenance.support_family ?? null;
  const kind: SupportKind =
    radius > 0 && family !== 'point_queryable' ? 'window' : 'pixel';
  const regionalScale = kind === 'window' && family !== null && REGIONAL_FAMILIES.has(family);
  const inputs = Array.isArray(provenance.support_inputs)
    ? provenance.support_inputs.filter((entry) => entry && typeof entry === 'object')
    : [];
  const nativeText = native !== null ? ` (native grid ${formatDistance(native)})` : '';
  const nativeTextFa = native !== null ? ` (شبکهٔ بومی ${formatDistance(native)})` : '';

  if (kind === 'window') {
    const base = `This value describes the area around the selected location: a ${formatDistance(radius)} radius, ${formatArea(area)}${nativeText}.`;
    const baseFa = `این مقدار، ناحیهٔ اطراف نقطهٔ انتخابی را توصیف می‌کند: شعاع ${formatDistance(radius)}، ${formatArea(area)}${nativeTextFa}.`;
    return {
      kind,
      radiusM: radius,
      areaSqM: area,
      nativeResolutionM: native,
      family,
      policy: provenance.support_policy ?? null,
      regionalScale,
      badgeEn: `Area around point · r ${formatDistance(radius)} (${formatArea(area)})`,
      badgeFa: `ناحیهٔ اطراف نقطه · شعاع ${formatDistance(radius)} (${formatArea(area)})`,
      explanationEn: regionalScale
        ? `${base} The product's pixel is far larger than a field, so this is regional/district-scale context, not a pinpoint field measurement.`
        : base,
      explanationFa: regionalScale
        ? `${baseFa} پیکسل این محصول بسیار بزرگ‌تر از یک مزرعه است؛ پس این مقدار زمینهٔ منطقه‌ای است نه اندازه‌گیری دقیق مزرعه.`
        : baseFa,
      originalPoint: originalPointText(provenance),
      inputs,
    };
  }
  return {
    kind,
    radiusM: 0,
    areaSqM: 0,
    nativeResolutionM: native,
    family,
    policy: provenance.support_policy ?? null,
    regionalScale: true,
    badgeEn: native !== null
      ? `Point pixel · ${formatDistance(native)} cell`
      : 'Point pixel',
    badgeFa: native !== null
      ? `پیکسل نقطه · سلول ${formatDistance(native)}`
      : 'پیکسل نقطه',
    explanationEn: `This value is the single native pixel that contains the selected location${nativeText}. The cell is far larger than a field, so it is district-scale context.`,
    explanationFa: `این مقدار تنها پیکسل بومی شامل نقطهٔ انتخابی است${nativeTextFa}. این سلول بسیار بزرگ‌تر از یک مزرعه است و زمینهٔ منطقه‌ای را نشان می‌دهد.`,
    originalPoint: originalPointText(provenance),
    inputs,
  };
}

/** Rows for the provenance drawer: structured support fields, bilingual labels. */
export function supportRows(
  provenance: ProvenanceResponse | null | undefined,
): Array<{ key: string; label: string; value: string }> {
  const info = supportInfoOf(provenance);
  if (!info) return [];
  const rows: Array<{ key: string; label: string; value: string }> = [];
  rows.push({
    key: 'support_kind',
    label: 'نوع پشتیبانی مکانی — Spatial support',
    value: info.kind === 'window' ? 'Area around the selected point' : 'Single containing pixel',
  });
  if (info.originalPoint) {
    rows.push({
      key: 'original_geometry',
      label: 'نقطهٔ اصلی — Selected point (lat, lng)',
      value: info.originalPoint,
    });
  }
  if (info.kind === 'window') {
    rows.push({
      key: 'support_radius_m',
      label: 'شعاع — Support radius',
      value: formatDistance(info.radiusM),
    });
    rows.push({
      key: 'support_area_sq_m',
      label: 'مساحت — Support area',
      value: formatArea(info.areaSqM),
    });
  }
  if (info.nativeResolutionM !== null) {
    rows.push({
      key: 'support_native_resolution_m',
      label: 'رزولوشن بومی — Native resolution',
      value: formatDistance(info.nativeResolutionM),
    });
  }
  if (info.family) {
    rows.push({ key: 'support_family', label: 'خانوادهٔ پشتیبانی — Support family', value: info.family });
  }
  if (info.policy) {
    rows.push({ key: 'support_policy', label: 'سیاست — Support policy', value: info.policy });
  }
  if (info.inputs.length > 1) {
    rows.push({
      key: 'support_inputs',
      label: 'ورودی‌ها — Inputs',
      value: info.inputs
        .map((input) => {
          const r = isFiniteNumber(input.radius_m) ? input.radius_m : 0;
          const where = r > 0 ? `r ${formatDistance(r)}` : 'point pixel';
          return `${input.dataset_id ?? '?'} (${where})`;
        })
        .join('; '),
    });
  }
  return rows;
}
