/**
 * Thermal presentation metadata (P5.1 visualization contract).
 *
 * Display labels only. The frontend renders backend-derived
 * evidence; it never calculates baselines, z-scores, percentiles,
 * anomalies, changes, concordance, or thermal relationships, and
 * it never renames a physical quantity. Every helper below maps a
 * backend machine-readable state to a bilingual label while the
 * underlying state travels through intact.
 */
import type { ThermalSideEvidence } from '../../types/index.ts';

export interface ThermalSourceMeta {
  profileKind: string;
  sourceRole: string;
  displayLabel: string;
  displayLabelFa: string;
  physicalQuantity: string;
  datasetId: string;
}

/** Presentation identity per thermal source; roles stay distinct. */
export const THERMAL_SOURCE_META: Record<string, ThermalSourceMeta> = {
  LST_PROFILE: {
    profileKind: 'LST_PROFILE',
    sourceRole: 'REMOTE_SENSING_LAND_SURFACE',
    displayLabel: 'Land Surface Temperature',
    displayLabelFa: 'دمای سطح زمین',
    physicalQuantity: 'land_surface_temperature',
    datasetId: 'MODIS/061/MOD11A2',
  },
  AIR_TEMPERATURE_PROFILE: {
    profileKind: 'AIR_TEMPERATURE_PROFILE',
    sourceRole: 'METEOROLOGICAL_CONTEXT',
    displayLabel: 'Modelled 2 m Air Temperature',
    displayLabelFa: 'دمای هوای مدل‌سازی‌شده در ارتفاع دو متری',
    physicalQuantity: 'air_temperature_2m',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
  },
};

const FALLBACK_SOURCE_META: ThermalSourceMeta = {
  profileKind: 'UNKNOWN',
  sourceRole: 'UNKNOWN',
  displayLabel: 'Unknown thermal source',
  displayLabelFa: 'منبع حرارتی نامشخص',
  physicalQuantity: 'unknown',
  datasetId: 'unknown',
};

/** Look up presentation identity by backend profile kind. */
export function thermalSourceMetaFor(profileKind: unknown): ThermalSourceMeta {
  if (typeof profileKind === 'string' && profileKind in THERMAL_SOURCE_META) {
    return THERMAL_SOURCE_META[profileKind];
  }
  return FALLBACK_SOURCE_META;
}

const RELATIONSHIP_LABELS: Record<string, { label: string; labelFa: string }> = {
  THERMAL_CONCORDANT: { label: 'Thermally concordant', labelFa: 'همخوان حرارتی' },
  THERMAL_DIVERGENT: { label: 'Thermally divergent', labelFa: 'واگرای حرارتی' },
  THERMAL_MIXED_EVIDENCE: { label: 'Mixed thermal evidence', labelFa: 'شواهد حرارتی مختلط' },
  THERMAL_ONLY: { label: 'Thermal only', labelFa: 'فقط حرارتی' },
  THERMAL_CONTEXT_CONCORDANT: { label: 'Context concordant', labelFa: 'همخوان بافتی' },
  THERMAL_CONTEXT_DIVERGENT: { label: 'Context divergent', labelFa: 'واگرای بافتی' },
  THERMAL_CONTEXT_MIXED_EVIDENCE: { label: 'Mixed context evidence', labelFa: 'شواهد بافتی مختلط' },
  THERMAL_CONTEXT_ONLY: { label: 'Context only', labelFa: 'فقط بافت' },
  INSUFFICIENT_EVIDENCE: { label: 'Insufficient evidence', labelFa: 'شواهد ناکافی' },
};

/**
 * Presentation label for a backend thermal relationship state.
 * The machine-readable state is preserved by the caller; only a
 * human label is returned. Unknown states fall back to the
 * insufficient-evidence label rather than inventing a meaning.
 */
export function thermalRelationshipLabel(state: unknown): string {
  if (typeof state === 'string' && state in RELATIONSHIP_LABELS) {
    return RELATIONSHIP_LABELS[state].label;
  }
  return RELATIONSHIP_LABELS.INSUFFICIENT_EVIDENCE.label;
}

const ORIENTATION_LABELS: Record<string, string> = {
  UP: 'Increased',
  DOWN: 'Decreased',
  NEUTRAL: 'Neutral',
  INSUFFICIENT: 'Insufficient evidence',
};

/**
 * Presentation label for a backend orientation. UP means the
 * quantity increased or sits above its own baseline — never
 * stress, risk, or a biological claim.
 */
export function thermalOrientationLabel(orientation: unknown): string {
  if (typeof orientation === 'string' && orientation in ORIENTATION_LABELS) {
    return ORIENTATION_LABELS[orientation];
  }
  return ORIENTATION_LABELS.INSUFFICIENT;
}

/** True only for side evidence carrying a finite observed value. */
export function hasThermalValue(side: ThermalSideEvidence | null | undefined): boolean {
  if (!side) return false;
  return typeof side.value === 'number' && Number.isFinite(side.value);
}
