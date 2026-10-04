import type { ProvenanceResponse } from '../../types';
import ProvenanceDrawer from './ProvenanceDrawer';
import TemporalLineChart from './TemporalLineChart';
import type { BaselineLevels, TemporalDatum } from './temporalChart.ts';
import { asRecord } from './parse.ts';

export interface ChartRelationship {
  /** Human label naming the side, e.g. 'LST' or 'ERA5 context'. */
  label: string;
  /** Backend relationship state, displayed verbatim as text. */
  state: string;
}

interface TemporalChartCardProps {
  title: string;
  titleFa: string;
  metricKey: string;
  metricLabel: string;
  unit: string;
  /** Source identity line, e.g. 'MODIS · Land Surface Temperature'. */
  sourceNote?: string | null;
  data: TemporalDatum[];
  baseline?: BaselineLevels | null;
  /** Backend persistence summary text, if the analysis exposed it. */
  persistenceText?: string | null;
  /** Backend relationship states with human side labels. */
  relationships?: ChartRelationship[];
  provenance?: unknown;
  limitations?: string[];
  loading?: boolean;
  error?: string | null;
  height?: number;
}

/** Narrow unknown provenance to the shared drawer shape. */
function asProvenance(value: unknown): ProvenanceResponse | null {
  const record = asRecord(value);
  if (!record) return null;
  if (typeof record.source_dataset_id !== 'string') return null;
  return value as ProvenanceResponse;
}

/**
 * One-metric temporal card. Renders backend monthly observations
 * with backend baselines, states, and provenance; missing months
 * render as gaps or as an explicit empty state — never as values.
 */
export default function TemporalChartCard({
  title,
  titleFa,
  metricKey,
  metricLabel,
  unit,
  sourceNote = null,
  data,
  baseline = null,
  persistenceText = null,
  relationships = [],
  provenance = null,
  limitations = [],
  loading = false,
  error = null,
  height = 300,
}: TemporalChartCardProps): React.ReactElement {
  const usable = data.filter((datum) => datum.value !== null).length;
  const provenanceRecord = asProvenance(provenance);
  const ariaLabel = `${metricLabel} monthly series in ${unit}, ${usable} of ${data.length} months observed`;

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">
          {titleFa} — {title}
        </span>
      </div>
      <div className="card-body">
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
          <code>{metricKey}</code> · {metricLabel} · {unit}
          {sourceNote ? ` · ${sourceNote}` : null}
        </div>
        {loading ? (
          <div className="loading">
            <span className="spinner" />
          </div>
        ) : error ? (
          <div className="error-banner">{error}</div>
        ) : data.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-title">No temporal points</div>
            <div className="empty-state-desc">
              Monthly profiles are not part of this analysis response yet.
            </div>
          </div>
        ) : usable === 0 ? (
          <div className="empty-state">
            <div className="empty-state-title">Insufficient evidence</div>
            <div className="empty-state-desc">
              Every month is missing, insufficient, or unavailable — nothing is plotted.
            </div>
          </div>
        ) : (
          <>
            <TemporalLineChart
              data={data}
              unit={unit}
              observedLabel={metricLabel}
              height={height}
              baseline={baseline}
              ariaLabel={ariaLabel}
            />
            {persistenceText ? (
              <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
                Persistence: <span>{persistenceText}</span>
              </div>
            ) : null}
            {relationships.length > 0 ? (
              <div style={{ marginTop: 8 }}>
                {relationships.map((entry) => (
                  <div
                    key={entry.label}
                    className="text-muted"
                    style={{ fontSize: '0.8rem' }}
                  >
                    {entry.label}: <span>{entry.state}</span>
                  </div>
                ))}
              </div>
            ) : null}
            <ProvenanceDrawer provenance={provenanceRecord} />
            {limitations.length > 0 ? (
              <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: 8 }}>
                {limitations.map((line, index) => (
                  <div key={index}>{line}</div>
                ))}
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
