import React, { useMemo } from 'react';
import {
  getJalaliMonthDays,
  JALALI_MONTH_NAMES_FA,
  jalaliToGregorian,
  parseJalaliDateString,
  toEnglishDigits,
  toPersianDigits,
} from '../../utils/date/index.ts';

interface JalaliDatePickerProps {
  label: string;
  valueJalali: string; // e.g. "1404/03/11" or "۱۴۰۴/۰۳/۱۱"
  onChange: (jalaliAscii: string, isoGregorian: string) => void;
  dataTestId?: string;
  minYear?: number;
  maxYear?: number;
  error?: string | null;
  disabled?: boolean;
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

export default function JalaliDatePicker({
  label,
  valueJalali,
  onChange,
  dataTestId = 'jalali-date-picker',
  minYear = 1395,
  maxYear = 1406,
  error,
  disabled = false,
}: JalaliDatePickerProps) {
  const parts = useMemo(() => {
    const parsed = parseJalaliDateString(valueJalali);
    if (parsed) return parsed;
    // Default fallback to 1404/01/01 if empty/invalid
    return { jy: 1404, jm: 1, jd: 1 };
  }, [valueJalali]);

  const maxDaysInMonth = useMemo(
    () => getJalaliMonthDays(parts.jy, parts.jm),
    [parts.jy, parts.jm],
  );

  const years = useMemo(() => {
    const list: number[] = [];
    for (let y = minYear; y <= maxYear; y += 1) {
      list.push(y);
    }
    return list;
  }, [minYear, maxYear]);

  const days = useMemo(() => {
    const list: number[] = [];
    for (let d = 1; d <= maxDaysInMonth; d += 1) {
      list.push(d);
    }
    return list;
  }, [maxDaysInMonth]);

  const emitChange = (newJy: number, newJm: number, newJd: number) => {
    const maxDays = getJalaliMonthDays(newJy, newJm);
    const validJd = Math.min(newJd, maxDays);
    const jalaliAscii = `${newJy}/${pad2(newJm)}/${pad2(validJd)}`;
    const g = jalaliToGregorian(newJy, newJm, validJd);
    const isoGregorian = `${g.gy}-${pad2(g.gm)}-${pad2(g.gd)}`;
    onChange(jalaliAscii, isoGregorian);
  };

  const handleYearChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const y = parseInt(toEnglishDigits(e.target.value), 10);
    if (!Number.isNaN(y)) {
      emitChange(y, parts.jm, parts.jd);
    }
  };

  const handleMonthChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const m = parseInt(toEnglishDigits(e.target.value), 10);
    if (!Number.isNaN(m)) {
      emitChange(parts.jy, m, parts.jd);
    }
  };

  const handleDayChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const d = parseInt(toEnglishDigits(e.target.value), 10);
    if (!Number.isNaN(d)) {
      emitChange(parts.jy, parts.jm, d);
    }
  };

  const formattedDisplay = `${toPersianDigits(parts.jy)}/${toPersianDigits(pad2(parts.jm))}/${toPersianDigits(pad2(parts.jd))}`;

  return (
    <div className="form-group" data-testid={dataTestId}>
      <label className="form-label" style={{ fontWeight: 600, display: 'flex', justifyContent: 'space-between' }}>
        <span>{label}</span>
        <span
          style={{
            fontSize: '0.82rem',
            color: '#2e7d32',
            fontWeight: 700,
            direction: 'rtl',
          }}
          data-testid={`${dataTestId}-display`}
        >
          {formattedDisplay}
        </span>
      </label>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1.2fr 1.6fr 1fr',
          gap: 6,
          direction: 'rtl',
        }}
      >
        {/* Day Select */}
        <select
          aria-label={`${label} - روز`}
          data-testid={`${dataTestId}-day`}
          className="form-select"
          value={parts.jd}
          onChange={handleDayChange}
          disabled={disabled}
          style={{ fontSize: '0.85rem', padding: '6px 8px' }}
        >
          {days.map((d) => (
            <option key={d} value={d}>
              {toPersianDigits(d)}
            </option>
          ))}
        </select>

        {/* Month Select */}
        <select
          aria-label={`${label} - ماه`}
          data-testid={`${dataTestId}-month`}
          className="form-select"
          value={parts.jm}
          onChange={handleMonthChange}
          disabled={disabled}
          style={{ fontSize: '0.85rem', padding: '6px 8px' }}
        >
          {JALALI_MONTH_NAMES_FA.map((name, idx) => {
            const m = idx + 1;
            return (
              <option key={m} value={m}>
                {toPersianDigits(m)} - {name}
              </option>
            );
          })}
        </select>

        {/* Year Select */}
        <select
          aria-label={`${label} - سال`}
          data-testid={`${dataTestId}-year`}
          className="form-select"
          value={parts.jy}
          onChange={handleYearChange}
          disabled={disabled}
          style={{ fontSize: '0.85rem', padding: '6px 8px' }}
        >
          {years.map((y) => (
            <option key={y} value={y}>
              {toPersianDigits(y)}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <span className="text-danger" style={{ fontSize: '0.75rem', marginTop: 3, display: 'block' }}>
          {error}
        </span>
      )}
    </div>
  );
}
