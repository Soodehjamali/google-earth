import React from 'react';
import {
  formatNumberValue,
  normalizeUnit,
  type FormattedNumberResult,
} from './numberFormatting.ts';

export { formatNumberValue, normalizeUnit, type FormattedNumberResult };

export interface FormattedNumberProps {
  /** Numeric value or string representation of a number */
  value: number | string | null | undefined;
  /** Optional unit string (e.g. '°C', 'm3/m3', 'dB', 'mm', 'ha') */
  unit?: string;
  /** Optional fixed decimal digits */
  digits?: number;
  /** Optional custom class name */
  className?: string;
  /** Optional style override */
  style?: React.CSSProperties;
  /** Prefix with explicit '+' for positive numbers */
  showPositiveSign?: boolean;
}

/**
 * Robust RTL-isolated Number Presentation Component.
 * Guarantees:
 * - Mathematical minus '−' never flips to the right of digits in RTL context.
 * - Value stays Latin digits.
 * - Raw value is stored in data-raw-value for tests and clipboard operations.
 */
export const FormattedNumber: React.FC<FormattedNumberProps> = ({
  value,
  unit,
  digits,
  className = '',
  style,
  showPositiveSign = false,
}) => {
  const { display, raw, isNegative } = formatNumberValue(value, digits, showPositiveSign);
  const unitDisplay = normalizeUnit(unit);

  if (display === '—') {
    return (
      <span className={`formatted-number-empty ${className}`} style={style}>
        —
      </span>
    );
  }

  return (
    <span
      className={`formatted-number ${isNegative ? 'is-negative' : ''} ${className}`}
      dir="ltr"
      data-raw-value={raw}
      style={{
        unicodeBidi: 'isolate',
        display: 'inline-flex',
        alignItems: 'baseline',
        direction: 'ltr',
        fontVariantNumeric: 'tabular-nums',
        ...style,
      }}
    >
      <span className="num-val">{display}</span>
      {unitDisplay && (
        <span className="num-unit" style={{ marginLeft: 3, opacity: 0.85 }}>
          {unitDisplay}
        </span>
      )}
    </span>
  );
};

export default FormattedNumber;
