import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TemporalProfilePoint } from '../../types/index.ts';
import { formatEvidenceValue } from './parse.ts';
import {
  MIN_COMPARABLE_YEARS,
  canCompareYears,
  comparableYears,
  groupPointsByYear,
  metricProfileOf,
  usableComparisonMetrics,
} from './yearComparison.ts';

interface YearComparisonSectionProps {
  /** NDVI monthly points from the shared analysis result, if present. */
  profile: { points: TemporalProfilePoint[]; unit: string } | null | undefined;
  title: string;
  titleFa: string;
  /**
   * Full temporal section the comparison reads metric profiles from.
   * When provided, a selector offers every comparison metric that
   * carries usable backend points (ndvi preferred); otherwise the
   * legacy NDVI-only `profile` prop drives the chart unchanged.
   */
  temporal?: unknown;
}

/** Neutral qualitative palette: years are distinguished, never graded. */
const YEAR_COLORS = [
  '#1565c0',
  '#6a1b9a',
  '#00897b',
  '#ef6c00',
  '#455a64',
  '#ad1457',
  '#2e7d32',
  '#5d4037',
];

interface YearTooltipEntry {
  name?: string;
  value?: number | string | null;
  color?: string;
}

function YearTooltip(tooltipProps: unknown): React.ReactElement | null {
  const props = (tooltipProps ?? {}) as {
    active?: boolean;
    label?: unknown;
    payload?: YearTooltipEntry[];
  };
  if (!props.active || !props.payload || props.payload.length === 0) return null;
  return (
    <div
      style={{
        backgroundColor: 'rgba(255,255,255,0.95)',
        border: '1px solid #ddd',
        borderRadius: '8px',
        padding: '8px 12px',
        fontSize: '0.8rem',
      }}
    >
      <div>
        <span className="text-muted">Month:</span>{' '}
        <span>{typeof props.label === 'string' ? props.label : '—'}</span>
      </div>
      {props.payload.map((entry) => (
        <div key={String(entry.name)}>
          <span className="text-muted">{String(entry.name)}:</span>{' '}
          <span>
            {typeof entry.value === 'number'
              ? formatEvidenceValue(entry.value)
              : 'No observation (gap)'}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Year-over-year comparison (P1 consolidation), extended to the
 * backend monthly profiles actually present (ndvi, ndmi, ndre, msi).
 * Groups one metric's monthly points by calendar year and overlays
 * one neutral line per year. Gaps stay gaps (connectNulls is false);
 * no interpolation, no filling, no verdicts, no year ordering by
 * value. Fewer than two comparable years renders an honest
 * incomplete-data state instead of a chart.
 */
export default function YearComparisonSection({
  profile: legacyProfile,
  title,
  titleFa,
  temporal,
}: YearComparisonSectionProps): React.ReactElement {
  const hasTemporal = temporal !== undefined;
  const usable = useMemo(
    () => (hasTemporal ? usableComparisonMetrics(temporal) : []),
    [hasTemporal, temporal],
  );
  const [override, setOverride] = useState<string | null>(null);
  const selected = hasTemporal
    ? override && usable.includes(override)
      ? override
      : usable.includes('ndvi')
        ? 'ndvi'
        : (usable[0] ?? 'ndvi')
    : 'ndvi';
  const profile = hasTemporal
    ? metricProfileOf(temporal, selected)
    : legacyProfile;
  const grouped = useMemo(
    () => groupPointsByYear(profile?.points ?? []),
    [profile],
  );
  const comparable = useMemo(() => comparableYears(grouped), [grouped]);
  const comparableNow = useMemo(() => canCompareYears(grouped), [grouped]);

  const rows = useMemo(() => {
    const slotLabels = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    return slotLabels.map((label, index) => {
      const month = String(index + 1).padStart(2, '0');
      const row: Record<string, string | number | null> = { month: label };
      for (const series of comparable) {
        const slot = series.months.find((entry) => entry.month === month);
        row[series.year] = slot ? slot.value : null;
      }
      return row;
    });
  }, [comparable]);

  const unit = profile?.unit ?? '';
  const metricLabel = selected.toUpperCase();
  const ariaLabel =
    comparable.length > 0
      ? `${metricLabel} year comparison across ${comparable.map((series) => series.year).join(', ')}`
      : `${metricLabel} year comparison unavailable`;

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">
          {titleFa} — {title}
        </span>
      </div>
      <div className="card-body">
        {hasTemporal && usable.length > 1 && (
          <div className="form-row" style={{ marginBottom: 8 }}>
            <label className="text-muted" htmlFor="year-comparison-metric">
              شاخص — Metric:
            </label>
            <select
              id="year-comparison-metric"
              value={selected}
              onChange={(event) => setOverride(event.target.value)}
            >
              {usable.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </div>
        )}
        {!comparableNow ? (
          <div className="empty-state">
            <div className="empty-state-title">مقایسه سال‌به‌سال در دسترس نیست</div>
            <div className="empty-state-desc">
              Year-over-year comparison needs monthly {metricLabel} observations spanning at
              least {MIN_COMPARABLE_YEARS} calendar years. The current response
              carries {comparable.length}{' '}
              {comparable.length === 1 ? 'such year' : 'such years'}
              {grouped.skipped > 0 ? ` (${grouped.skipped} records skipped)` : ''}.
              Run an analysis over a multi-year window (backend monthly
              intelligence covers up to 36 months) including vegetation data.
            </div>
          </div>
        ) : (
          <>
            <div dir="ltr" role="img" aria-label={ariaLabel}>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={rows} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis
                    tick={{ fontSize: 12 }}
                    tickFormatter={(value: number) => formatEvidenceValue(value, 1)}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip content={<YearTooltip />} />
                  <Legend />
                  {comparable.map((series, index) => (
                    <Line
                      key={series.year}
                      type="monotone"
                      dataKey={series.year}
                      name={series.year}
                      stroke={YEAR_COLORS[index % YEAR_COLORS.length]}
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 5 }}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
              <div className="chart-legend">
                {comparable.map((series, index) => (
                  <span key={series.year} className="legend-item">
                    <span
                      className="legend-color"
                      style={{ backgroundColor: YEAR_COLORS[index % YEAR_COLORS.length] }}
                    />
                    {series.year} ({unit || '—'})
                  </span>
                ))}
              </div>
            </div>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
              Monthly {metricLabel} values placed side by side by calendar year. Missing
              months render as gaps; each line is one calendar year and
              carries no value judgment.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
