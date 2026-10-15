/**
 * Honest unavailable states (F-A12 product acceptance).
 *
 * The backend already says why a metric produced no value: a reason code
 * and a user-safe message. This module only sorts that reason into the
 * categories a user can act on. It never supplies a value, never
 * rewrites the backend message (the card always shows it verbatim), and
 * falls back to a neutral "insufficient data" category rather than
 * guessing when the reason is not recognised.
 */

export type UnavailableCategory =
  | 'product_not_available'
  | 'outside_temporal_coverage'
  | 'insufficient_temporal_window'
  | 'masked_at_location'
  | 'scientifically_insufficient'
  | 'not_produced'
  | 'insufficient_data'
  | 'unknown';

export interface UnavailableInfo {
  category: UnavailableCategory;
  labelEn: string;
  labelFa: string;
  /** One-line gloss of what the category means for the user. */
  glossEn: string;
  /** Raw backend reason code, if any. */
  reason: string | null;
  /** Backend message, verbatim, if any. */
  message: string | null;
}

const LABELS: Record<UnavailableCategory, { en: string; fa: string; gloss: string }> = {
  product_not_available: {
    en: 'Product not available',
    fa: 'محصول داده در دسترس نیست',
    gloss: 'No registered dataset provides this quantity.',
  },
  outside_temporal_coverage: {
    en: 'Outside product temporal coverage',
    fa: 'خارج از بازهٔ زمانی محصول',
    gloss: 'The requested period is outside the years this product covers.',
  },
  insufficient_temporal_window: {
    en: 'Insufficient temporal window',
    fa: 'بازهٔ زمانی ناکافی',
    gloss: 'The requested window is too short for this result to be certified.',
  },
  masked_at_location: {
    en: 'Product masked at this location',
    fa: 'محصول در این مکان ماسک شده است',
    gloss: 'The product returned no valid pixels here; nothing was substituted.',
  },
  scientifically_insufficient: {
    en: 'Scientifically insufficient',
    fa: 'از نظر علمی ناکافی',
    gloss: 'A required scientific basis is missing, so no defensible value exists.',
  },
  not_produced: {
    en: 'Not produced',
    fa: 'تولید نمی‌شود',
    gloss: 'This engine does not implement a verified method for it.',
  },
  insufficient_data: {
    en: 'Insufficient data',
    fa: 'داده ناکافی',
    gloss: 'The data available did not support a value.',
  },
  unknown: {
    en: 'Unavailable',
    fa: 'در دسترس نیست',
    gloss: 'The backend did not say why.',
  },
};

const PRODUCT_NOT_AVAILABLE: ReadonlySet<string> = new Set([
  'not_supported',
  'no_flowering_signal_product',
  'no_harvest_date_product',
  'no_planting_date_product',
  'no_crop_species_product',
  'no_general_irrigation_product',
  'no_earth_engine_soil_property_layer',
  'no_direct_salinity_observation',
  'no_texture_fractions',
  'no_flow_accumulation_primitive',
]);

const OUTSIDE_COVERAGE: ReadonlySet<string> = new Set([
  'outside_temporal_coverage',
  'outside_product_coverage',
]);

const NOT_PRODUCED: ReadonlySet<string> = new Set([
  'no_verified_biomass_model',
  'no_validated_yield_model',
  'no_yield_estimate_to_quantify',
  'no_verified_crop_coefficient',
  'no_efficiency_parameter',
  'unsupported_water_balance_terms',
]);

const SHORT_WINDOW_CODES: ReadonlySet<string> = new Set([
  'window_too_short',
  'insufficient_temporal_window',
]);

const SCIENTIFICALLY_INSUFFICIENT: ReadonlySet<string> = new Set([
  'no_scientific_weighting',
  'no_well_watered_baseline',
  'no_temperature_trapezoid_baseline',
  'no_documented_sign_convention',
  'integral_requires_gap_filling',
  'static_dataset_no_historical_series',
]);

/** Phrases the metrics use when a product returned nothing valid here. */
const MASKED_PATTERNS: readonly RegExp[] = [
  /0 valid pixel/i,
  /returned no valid pixels/i,
  /Insufficient valid coverage: 0(\.0)? percent/i,
  /none returned a usable spatial mean/i,
  /returned no usable prediction/i,
  /no (?:temporary-crops|usable) image/i,
];

/** Phrases the phenology metrics use when the window is too short. */
const SHORT_WINDOW_PATTERNS: readonly RegExp[] = [
  /distinct month\(s\) with usable data/i,
  /could not certify a season/i,
];

export function classifyUnavailable(
  reason: string | null | undefined,
  message: string | null | undefined,
): UnavailableInfo {
  const code = typeof reason === 'string' && reason.length > 0 ? reason : null;
  const text = typeof message === 'string' && message.length > 0 ? message : null;
  let category: UnavailableCategory = 'unknown';

  if (code !== null && OUTSIDE_COVERAGE.has(code)) category = 'outside_temporal_coverage';
  else if (code !== null && PRODUCT_NOT_AVAILABLE.has(code)) category = 'product_not_available';
  else if (code !== null && NOT_PRODUCED.has(code)) category = 'not_produced';
  else if (code !== null && SCIENTIFICALLY_INSUFFICIENT.has(code)) category = 'scientifically_insufficient';
  else if (code !== null && SHORT_WINDOW_CODES.has(code)) category = 'insufficient_temporal_window';
  else if (code === 'insufficient_data') {
    if (text !== null && SHORT_WINDOW_PATTERNS.some((p) => p.test(text))) {
      category = 'insufficient_temporal_window';
    } else if (text !== null && MASKED_PATTERNS.some((p) => p.test(text))) {
      category = 'masked_at_location';
    } else {
      category = 'insufficient_data';
    }
  }

  const label = LABELS[category];
  return {
    category,
    labelEn: label.en,
    labelFa: label.fa,
    glossEn: label.gloss,
    reason: code,
    message: text,
  };
}

/** True when an evidence item carries no usable numeric value. */
export function isUnavailableItem(item: {
  value?: unknown;
  status?: unknown;
}): boolean {
  return (
    item.status === 'unavailable' ||
    typeof item.value !== 'number' ||
    !Number.isFinite(item.value)
  );
}
