import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { formatNumberValue, normalizeUnit } from '../../common/numberFormatting.ts';
import { formatCoordinates } from '../geocoding.ts';

describe('Step 2 & Step 7: FormattedNumber, Minus Signs, and Coordinate Labeling', () => {
  it('1. formatNumberValue formats numbers with Latin digits and mathematical minus U+2212', () => {
    // Standard positive number
    const pos = formatNumberValue(0.4567, 4);
    assert.strictEqual(pos.display, '0.4567');
    assert.strictEqual(pos.raw, '0.4567');
    assert.strictEqual(pos.isNegative, false);

    // Negative number: must use mathematical minus U+2212 ('\u2212') not ASCII '-'
    const neg = formatNumberValue(-0.1234, 4);
    assert.strictEqual(neg.display, '\u22120.1234');
    assert.ok(neg.display.startsWith('\u2212'));
    assert.strictEqual(neg.isNegative, true);
    // Raw value preserves normal parseable number string
    assert.strictEqual(neg.raw, '-0.1234');

    // Negative integer
    const negInt = formatNumberValue(-15, 0);
    assert.strictEqual(negInt.display, '\u221215');
    assert.strictEqual(negInt.isNegative, true);
  });

  it('2. formatNumberValue handles null, undefined, NaN, and positive signs', () => {
    assert.strictEqual(formatNumberValue(null).display, '—');
    assert.strictEqual(formatNumberValue(undefined).display, '—');
    assert.strictEqual(formatNumberValue(NaN).display, '—');
    assert.strictEqual(formatNumberValue('invalid').display, '—');

    const signedPos = formatNumberValue(2.5, 1, true);
    assert.strictEqual(signedPos.display, '+2.5');
  });

  it('3. normalizeUnit converts technical units to user-friendly symbols', () => {
    assert.strictEqual(normalizeUnit('degC'), '°C');
    assert.strictEqual(normalizeUnit('Celsius'), '°C');
    assert.strictEqual(normalizeUnit('m3/m3'), 'm³/m³');
    assert.strictEqual(normalizeUnit('index'), '');
    assert.strictEqual(normalizeUnit('ratio'), '');
    assert.strictEqual(normalizeUnit('dimensionless'), '');
    assert.strictEqual(normalizeUnit('mm'), 'mm');
    assert.strictEqual(normalizeUnit(''), '');
    assert.strictEqual(normalizeUnit(undefined), '');
  });

  it('4. formatCoordinates provides explicit Lat and Lon labels when requested', () => {
    // Default standard notation (preserves backward compatibility)
    const std = formatCoordinates(32.4279, 53.6880);
    assert.strictEqual(std, '32.4279° N, 53.6880° E');

    // Explicit Persian + Latin labels
    const labeledFull = formatCoordinates(32.4279, 53.6880, { labeled: true });
    assert.strictEqual(labeledFull, 'عرض (Lat): 32.4279° N | طول (Lon): 53.6880° E');

    // Explicit compact Lat / Lon labels (never bare '53.6880, 32.4279')
    const labeledCompact = formatCoordinates(32.4279, 53.6880, { labeled: true, compact: true });
    assert.strictEqual(labeledCompact, 'Lat: 32.4279° N, Lon: 53.6880° E');
    assert.doesNotMatch(labeledCompact, /^[0-9.]+, [0-9.]+$/);

    // Southern and Western hemispheres
    const southern = formatCoordinates(-34.5678, -58.3816, { labeled: true, compact: true });
    assert.strictEqual(southern, 'Lat: 34.5678° S, Lon: 58.3816° W');
  });
});
