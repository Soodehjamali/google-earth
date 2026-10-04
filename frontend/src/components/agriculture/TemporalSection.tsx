import TemporalChartCard from './TemporalChartCard';
import type { ChartRelationship } from './TemporalChartCard';
import { thermalRelationshipLabel } from './thermal.ts';
import {
  asRecord,
  asArray,
  isFiniteNumber,
} from './parse.ts';
import {
  attachAnomalies,
  attachChanges,
  baselineLevels,
  concordanceMonths,
  findTemporalPayloads,
  hasUsableData,
  mapProfilePoints,
  payloadAnomalies,
  payloadChanges,
  payloadPoints,
  persistenceSummary,
  profileFor,
  anomalyFor,
  changeFor,
} from './temporalChart.ts';

export interface TemporalSeriesEntry {
  metricKey: string;
  label: string;
  labelFa: string;
  unit: string;
  sourceNote?: string | null;
  /** Thermal profile kind when this series is a thermal quantity. */
  thermalKind?: 'LST_PROFILE' | 'AIR_TEMPERATURE_PROFILE' | null;
}

interface TemporalSectionProps {
  title: string;
  titleFa: string;
  entries: TemporalSeriesEntry[];
  bundles: Record<string, { items?: unknown } | null | undefined> | null | undefined;
  /** Explicit backend temporal section (P5.3); preferred over sniffing. */
  temporal?: unknown;
}

/** Read a backend baseline shape without recomputing anything. */
function readBaseline(payload: Record<string, unknown>): ReturnType<typeof baselineLevels> {
  const record = asRecord(payload.baseline);
  if (!record || !isFiniteNumber(record.mean)) return null;
  return baselineLevels({
    mean: record.mean,
    minimum: record.minimum,
    maximum: record.maximum,
  });
}

/** Read a backend persistence shape as summary text. */
function readPersistence(payload: Record<string, unknown>): string | null {
  const record = asRecord(payload.persistence);
  if (!record || typeof record.state !== 'string') return null;
  return persistenceSummary({
    state: record.state,
    longest_run_below: record.longest_run_below,
    longest_run_above: record.longest_run_above,
  });
}

/** First non-empty per-point provenance record, if the backend sent one. */
function readProvenance(payload: Record<string, unknown>): unknown {
  for (const key of ['anomalies', 'points']) {
    for (const entry of asArray(payload[key])) {
      const record = asRecord(entry);
      if (!record) continue;
      const candidate = asRecord(record.thermal_provenance) ?? asRecord(record.provenance);
      if (candidate && typeof candidate.source_dataset_id === 'string') {
        return candidate;
      }
    }
  }
  return null;
}

/** Backend limitation strings, passed through verbatim. */
function readLimitations(payload: Record<string, unknown>): string[] {
  return asArray(payload.limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );
}

/** Concordance-shaped payloads keyed by exact month window. */
function findConcordanceByWindow(
  bundles: TemporalSectionProps['bundles'],
): Map<string, Record<string, unknown>> {
  const found = new Map<string, Record<string, unknown>>();
  if (!bundles || typeof bundles !== 'object') return found;
  for (const bundle of Object.values(bundles)) {
    if (!bundle || typeof bundle !== 'object') continue;
    for (const entry of asArray(bundle.items)) {
      const record = asRecord(entry);
      if (!record) continue;
      const months = asArray(record.months);
      const shaped = months.length > 0 && months.every((month) => {
        const item = asRecord(month);
        return !!item && typeof item.window_start === 'string'
          && (typeof item.lst_relationship === 'string'
            || typeof item.air_relationship === 'string');
      });
      if (!shaped) continue;
      for (const month of months) {
        const item = asRecord(month);
        if (!item) continue;
        const key = `${item.window_start} → ${item.window_end ?? ''}`;
        if (!found.has(key)) found.set(key, item);
      }
    }
  }
  return found;
}

/**
 * Temporal intelligence section: one card per configured series.
 * Series resolve from bundle payloads by exact metric key; a
 * series with no backend payload renders an explicit empty state
 * rather than an invented chart. LST and ERA5 resolve to separate
 * cards and are never pooled.
 */
export default function TemporalSection({
  title,
  titleFa,
  entries,
  bundles,
  temporal = null,
}: TemporalSectionProps): React.ReactElement {
  const sniffed = findTemporalPayloads(bundles);
  const sniffedConcordance = findConcordanceByWindow(bundles);
  const concordance = new Map(sniffedConcordance);
  for (const month of concordanceMonths(temporal)) {
    const end = typeof month.window_end === 'string' ? month.window_end : '';
    const key = `${month.window_start} → ${end}`;
    if (!concordance.has(key)) concordance.set(key, month);
  }

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">
          {titleFa} — {title}
        </span>
      </div>
      <div className="card-body" style={{ padding: 0 }}>
        {entries.map((entry) => {
          const payload = profileFor(temporal, entry.metricKey)
            ?? sniffed[entry.metricKey]
            ?? null;
          const anomalyPayload = anomalyFor(temporal, entry.metricKey);
          const changePayload = changeFor(temporal, entry.metricKey);
          const data = attachChanges(
            attachAnomalies(
              mapProfilePoints(payloadPoints(payload), entry.unit),
              payloadAnomalies(anomalyPayload ?? payload),
            ),
            payloadChanges(changePayload ?? payload),
          );
          const relationships: ChartRelationship[] = [];
          if (entry.thermalKind === 'LST_PROFILE' || entry.thermalKind === 'AIR_TEMPERATURE_PROFILE') {
            const side = entry.thermalKind === 'LST_PROFILE' ? 'LST' : 'ERA5 context';
            const states = new Set<string>();
            for (const datum of data) {
              const month = concordance.get(`${datum.window_start} → ${datum.window_end}`);
              if (!month) continue;
              const state = entry.thermalKind === 'LST_PROFILE'
                ? month.lst_relationship
                : month.air_relationship;
              if (typeof state === 'string') states.add(state);
            }
            for (const state of [...states].sort()) {
              relationships.push({
                label: `${side} relationship (${thermalRelationshipLabel(state)})`,
                state,
              });
            }
          }
          return (
            <TemporalChartCard
              key={entry.metricKey}
              title={entry.label}
              titleFa={entry.labelFa}
              metricKey={entry.metricKey}
              metricLabel={entry.label}
              unit={entry.unit}
              sourceNote={entry.sourceNote ?? null}
              data={data}
              baseline={readBaseline(anomalyPayload ?? payload)}
              persistenceText={readPersistence(changePayload ?? payload)}
              relationships={relationships}
              provenance={readProvenance(anomalyPayload ?? payload)}
              limitations={readLimitations(anomalyPayload ?? payload)}
            />
          );
        })}
        {entries.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-desc">No temporal series configured.</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function sectionHasUsableSeries(
  entries: TemporalSeriesEntry[],
  bundles: TemporalSectionProps['bundles'],
): boolean {
  const payloads = findTemporalPayloads(bundles);
  return entries.some((entry) => {
    const payload = payloads[entry.metricKey];
    if (!payload) return false;
    return hasUsableData(mapProfilePoints(payloadPoints(payload), entry.unit));
  });
}
