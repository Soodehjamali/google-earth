import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { BaselineLevels, TemporalDatum } from './temporalChart.ts';
import { stateTone } from './temporalChart.ts';
import { formatEvidenceValue } from './parse.ts';

interface TemporalLineChartProps {
  data: TemporalDatum[];
  unit: string;
  observedLabel: string;
  height?: number;
  baseline?: BaselineLevels | null;
  ariaLabel: string;
}

interface TooltipEntry {
  name?: string;
  value?: number | string | null;
  payload?: TemporalDatum;
}

/** Render one observed point; gaps (null) render nothing at all. */
function ObservedDot(dotProps: unknown): React.ReactElement | null {
  const props = (dotProps ?? {}) as {
    cx?: unknown;
    cy?: unknown;
    payload?: unknown;
  };
  if (typeof props.cx !== 'number' || typeof props.cy !== 'number') {
    return null;
  }
  const payload = (props.payload ?? {}) as Partial<TemporalDatum>;
  if (payload.value === null || payload.value === undefined) return null;
  const fill = stateTone(
    typeof payload.state === 'string' ? payload.state : null,
  );
  return <circle cx={props.cx} cy={props.cy} r={4} fill={fill} stroke="#fff" strokeWidth={1} />;
}

function ChartTooltip(tooltipProps: unknown): React.ReactElement | null {
  const props = (tooltipProps ?? {}) as {
    active?: boolean;
    label?: unknown;
    payload?: TooltipEntry[];
  };
  if (!props.active || !props.payload || props.payload.length === 0) return null;
  const datum = props.payload[0]?.payload;
  if (!datum) return null;
  const rows: Array<[string, string]> = [];
  rows.push(['Period', datum.period]);
  rows.push([
    'Value',
    datum.value === null ? 'No observation (gap)' : `${formatEvidenceValue(datum.value)} ${datum.unit}`,
  ]);
  if (datum.state) rows.push(['State', datum.state]);
  if (datum.quality) rows.push(['Quality', datum.quality]);
  if (datum.coverage !== null && datum.coverage !== undefined) {
    rows.push(['Coverage', `${formatEvidenceValue(datum.coverage, 1)} %`]);
  }
  if (datum.baselineMean !== null && datum.baselineMean !== undefined) {
    rows.push(['Baseline', formatEvidenceValue(datum.baselineMean)]);
  }
  if (datum.z !== null && datum.z !== undefined) {
    rows.push(['Z-score', formatEvidenceValue(datum.z)]);
  }
  if (datum.percentile !== null && datum.percentile !== undefined) {
    rows.push(['Percentile', formatEvidenceValue(datum.percentile, 1)]);
  }
  if (datum.absoluteChange !== null && datum.absoluteChange !== undefined) {
    rows.push(['Change', formatEvidenceValue(datum.absoluteChange)]);
  }
  if (datum.relativeChange !== null && datum.relativeChange !== undefined) {
    rows.push(['Relative change', formatEvidenceValue(datum.relativeChange)]);
  }
  if (datum.ratePerDay !== null && datum.ratePerDay !== undefined) {
    rows.push(['Rate per day', formatEvidenceValue(datum.ratePerDay)]);
  }
  if (datum.direction) rows.push(['Direction', datum.direction]);
  if (datum.rapid) rows.push(['Rapid state', datum.rapid]);
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
      {rows.map(([key, text]) => (
        <div key={key}>
          <span className="text-muted">{key}:</span> <span>{text}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Observed monthly series with backend reference lines. Null values
 * break the line (connectNulls is false); no interpolation, no
 * zero-fill, no fabricated points. Baseline levels draw as
 * reference lines only when the backend supplied them.
 */
export default function TemporalLineChart({
  data,
  unit,
  observedLabel,
  height = 300,
  baseline = null,
  ariaLabel,
}: TemporalLineChartProps): React.ReactElement {
  return (
    <div dir="ltr" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis dataKey="label" tick={{ fontSize: 12 }} />
          <YAxis
            tick={{ fontSize: 12 }}
            tickFormatter={(value: number) => formatEvidenceValue(value, 1)}
            domain={['auto', 'auto']}
          />
          <Tooltip content={<ChartTooltip />} />
          {baseline && baseline.mean !== null ? (
            <ReferenceLine
              y={baseline.mean}
              stroke="#1565c0"
              strokeDasharray="6 3"
              label={{ value: 'Baseline', fontSize: 11 }}
            />
          ) : null}
          {baseline && baseline.min !== null ? (
            <ReferenceLine y={baseline.min} stroke="#90a4ae" strokeDasharray="2 3" />
          ) : null}
          {baseline && baseline.max !== null ? (
            <ReferenceLine y={baseline.max} stroke="#90a4ae" strokeDasharray="2 3" />
          ) : null}
          <Line
            type="monotone"
            dataKey="value"
            name={`${observedLabel} (${unit})`}
            stroke="#2e7d32"
            strokeWidth={2}
            dot={<ObservedDot />}
            activeDot={{ r: 6 }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#2e7d32' }} />
          {observedLabel} ({unit})
        </span>
        {baseline && baseline.mean !== null ? (
          <span className="legend-item">
            <span className="legend-color" style={{ backgroundColor: '#1565c0' }} />
            Baseline
          </span>
        ) : null}
      </div>
    </div>
  );
}
