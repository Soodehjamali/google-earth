/**
 * Number & Unit Presentation Utilities
 *
 * Guarantees:
 * - Mathematical minus U+2212 ('−') for negative numbers in display only.
 * - Latin digits (0-9) for metrics and coordinates.
 * - Raw value preserved for data attributes and calculations.
 * - Proper unit normalization (e.g. degC -> °C, m3/m3 -> m³/m³).
 */

export interface FormattedNumberResult {
  display: string;
  raw: string;
  isNegative: boolean;
}

/**
 * Normalizes units for presentation (e.g. 'degC' -> '°C', 'm3/m3' -> 'm³/m³')
 */
export function normalizeUnit(unit?: string): string {
  if (!unit) return '';
  switch (unit.trim()) {
    case 'degC':
    case 'Celsius':
      return '°C';
    case 'm3/m3':
      return 'm³/m³';
    case 'index':
    case 'ratio':
    case 'dimensionless':
      return '';
    default:
      return unit;
  }
}

/**
 * Formats a raw number for display:
 * 1. Always uses Latin digits (0-9).
 * 2. Uses mathematical minus U+2212 ('−') for negative numbers in display only.
 * 3. Keeps the raw value accessible in data attributes.
 */
export function formatNumberValue(
  value: number | string | null | undefined,
  digits?: number,
  showPositiveSign: boolean = false,
): FormattedNumberResult {
  if (value === null || value === undefined || value === '') {
    return { display: '—', raw: '', isNegative: false };
  }

  const num = typeof value === 'number' ? value : parseFloat(String(value));
  if (Number.isNaN(num) || !Number.isFinite(num)) {
    return { display: '—', raw: String(value), isNegative: false };
  }

  const formattedStr = typeof digits === 'number' ? num.toFixed(digits) : String(num);
  const isNegative = num < 0;

  let displayStr: string;
  if (isNegative) {
    // Replace ASCII '-' with mathematical minus U+2212 '−' for presentation
    displayStr = `\u2212${Math.abs(num).toFixed(typeof digits === 'number' ? digits : undefined)}`;
  } else if (showPositiveSign && num > 0) {
    displayStr = `+${formattedStr}`;
  } else {
    displayStr = formattedStr;
  }

  return { display: displayStr, raw: String(value), isNegative };
}
