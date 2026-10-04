import { useMemo, useState } from 'react';
import type {
  CellObservationPayload,
  SpatialSectionPayload,
} from '../../types';
import MapView from '../MapView';
import { formatEvidenceValue } from './parse';
import {
  cellPolygonFeature,
  concordanceForCell,
  concordanceStateLabel,
  distinctConcordanceStates,
  distinctSpatialMetrics,
  observationsForCell,
  persistenceForCell,
  persistenceStateLabel,
  spatialCells,
  spatialLimitations,
  spatialMapCenter,
  spatialObservations,
  spatialStateLabel,
  spatialSummaries,
} from './spatial';

interface SpatialSectionProps {
  spatial: SpatialSectionPayload | null | undefined;
}

const ALL_METRICS = '__all_metrics__';
const ALL_STATES = '__all_states__';

/**
 * Spatial grid section (P5.3-S visualization).
 * Renders the backend spatial payload exactly as received: grid
 * summary, per-metric area summaries, cell polygons on the shared
 * map where the backend supplied valid geometry, and a per-cell
 * table carrying observations, concordance, and persistence as
 * text. Filters only narrow by values already present. Nothing is
 * computed, reclassified, or invented here.
 */
export default function SpatialSection({ spatial }: SpatialSectionProps) {
  const [metricFilter, setMetricFilter] = useState<string>(ALL_METRICS);
  const [concordanceFilter, setConcordanceFilter] = useState<string>(ALL_STATES);

  const cells = useMemo(() => spatialCells(spatial), [spatial]);
  const observations = useMemo(() => spatialObservations(spatial), [spatial]);
  const summaries = useMemo(() => spatialSummaries(spatial), [spatial]);
  const limitations = useMemo(() => spatialLimitations(spatial), [spatial]);
  const metrics = useMemo(() => distinctSpatialMetrics(spatial), [spatial]);
  const concordanceStates = useMemo(
    () => distinctConcordanceStates(spatial),
    [spatial],
  );
  const mapCenter = useMemo(() => spatialMapCenter(spatial), [spatial]);

  const overlays = useMemo(() => {
    const features: GeoJSON.Feature[] = [];
    for (const cell of cells) {
      const feature = cellPolygonFeature(cell);
      if (feature) features.push(feature);
    }
    return features;
  }, [cells]);

  if (!spatial || typeof spatial !== 'object') {
    return (
      <section aria-label="Spatial grid" className="card mb-3">
        <div className="card-header">
          <span className="card-title">🗺️ شبکه مکانی — Spatial Grid</span>
        </div>
        <div className="card-body">
          <div className="empty-state">
            <div className="empty-state-title">No spatial data</div>
            <div className="empty-state-desc">
              The analysis response carries no spatial section.
            </div>
          </div>
        </div>
      </section>
    );
  }

  const gridRows = typeof spatial.grid_rows === 'number' ? spatial.grid_rows : 0;
  const gridCols = typeof spatial.grid_cols === 'number' ? spatial.grid_cols : 0;
  const unmappable = cells.length - overlays.length;

  const visibleCells = cells.filter((cell) => {
    if (concordanceFilter === ALL_STATES) return true;
    const record = concordanceForCell(spatial, cell.cell_id);
    return record !== null && record.state === concordanceFilter;
  });

  return (
    <section aria-label="Spatial grid" className="card mb-3">
      <div className="card-header">
        <span className="card-title">🗺️ شبکه مکانی — Spatial Grid</span>
      </div>
      <div className="card-body">
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 8 }}>
          <span>
            Grid {gridRows} × {gridCols} · {cells.length}{' '}
            {cells.length === 1 ? 'cell' : 'cells'} · {observations.length}{' '}
            observations
          </span>
          {(spatial.window_start || spatial.window_end) && (
            <span>
              {' · '}
              {spatial.window_start || '—'} → {spatial.window_end || '—'}
            </span>
          )}
        </div>

        {summaries.length > 0 && (
          <div className="table-container" style={{ marginBottom: 12 }}>
            <table aria-label="Per-metric area summaries">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Usable / Missing</th>
                  <th>Anomalous</th>
                  <th>State</th>
                  <th>Method</th>
                </tr>
              </thead>
              <tbody>
                {summaries.map((summary) => (
                  <tr key={summary.metric_key}>
                    <td>
                      <code>{summary.metric_key}</code>
                    </td>
                    <td>
                      {summary.n_usable} / {summary.n_missing}
                    </td>
                    <td>
                      {summary.anomalous_count}
                      {typeof summary.anomalous_fraction === 'number' &&
                      Number.isFinite(summary.anomalous_fraction)
                        ? ` (${summary.anomalous_fraction})`
                        : ''}
                    </td>
                    <td>
                      {spatialStateLabel(summary.state)}{' '}
                      <span className="text-muted">({summary.state})</span>
                    </td>
                    <td>{summary.method || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {overlays.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <MapView
              overlays={overlays}
              center={mapCenter ?? undefined}
              zoom={10}
            />
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
              Cell outlines from the backend grid; states are listed in the
              table below.
            </div>
          </div>
        )}
        {cells.length > 0 && overlays.length === 0 && (
          <div className="empty-state" style={{ padding: '16px' }}>
            <div className="empty-state-desc">
              Cells carry no mappable geometry — table representation below.
            </div>
          </div>
        )}
        {unmappable > 0 && overlays.length > 0 && (
          <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 8 }}>
            {unmappable} {unmappable === 1 ? 'cell' : 'cells'} without mappable geometry — listed in the table only.
          </div>
        )}

        {cells.length > 0 && (
          <div
            style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}
          >
            <label className="text-muted" style={{ fontSize: '0.8rem' }}>
              Metric:{' '}
              <select
                aria-label="Filter cells by metric"
                value={metricFilter}
                onChange={(e) => setMetricFilter(e.target.value)}
              >
                <option value={ALL_METRICS}>All metrics</option>
                {metrics.map((metric) => (
                  <option key={metric} value={metric}>
                    {metric}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-muted" style={{ fontSize: '0.8rem' }}>
              Concordance:{' '}
              <select
                aria-label="Filter cells by concordance state"
                value={concordanceFilter}
                onChange={(e) => setConcordanceFilter(e.target.value)}
              >
                <option value={ALL_STATES}>All states</option>
                {concordanceStates.map((state) => (
                  <option key={state} value={state}>
                    {concordanceStateLabel(state)} ({state})
                  </option>
                ))}
              </select>
            </label>
            <span className="text-muted" style={{ fontSize: '0.8rem' }}>
              Showing {visibleCells.length} of {cells.length} cells
            </span>
          </div>
        )}

        {visibleCells.length === 0 ? (
          <div className="empty-state" style={{ padding: '16px' }}>
            <div className="empty-state-desc">
              {cells.length === 0
                ? 'No grid cells in this response.'
                : 'No cells match the selected filters.'}
            </div>
          </div>
        ) : (
          <div className="table-container">
            <table aria-label="Grid cells">
              <thead>
                <tr>
                  <th>Cell</th>
                  <th>Row / Col</th>
                  <th>Observations</th>
                  <th>Concordance</th>
                  <th>Persistence</th>
                </tr>
              </thead>
              <tbody>
                {visibleCells.map((cell) => (
                  <CellRow
                    key={cell.cell_id}
                    cellId={cell.cell_id}
                    row={cell.row}
                    col={cell.col}
                    observations={observationsForCell(
                      metricFilter === ALL_METRICS
                        ? observations
                        : observations.filter(
                            (item) => item.metric_key === metricFilter,
                          ),
                      cell.cell_id,
                    )}
                    spatial={spatial}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}

        {limitations.length > 0 && (
          <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: 8 }}>
            {limitations.map((line, index) => (
              <div key={index}>{line}</div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function CellRow({
  cellId,
  row,
  col,
  observations,
  spatial,
}: {
  cellId: string;
  row: number;
  col: number;
  observations: CellObservationPayload[];
  spatial: SpatialSectionPayload;
}) {
  const concordance = concordanceForCell(spatial, cellId);
  const persistence = persistenceForCell(spatial, cellId);
  return (
    <tr>
      <td>
        <code>{cellId}</code>
      </td>
      <td>
        {row} / {col}
      </td>
      <td>
        {observations.length === 0 ? (
          <span className="text-muted">—</span>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 16 }}>
            {observations.map((item, index) => (
              <li key={`${item.metric_key}-${index}`}>
                <code>{item.metric_key}</code>{' '}
                {formatEvidenceValue(item.value)} {item.unit || ''}
                {item.category ? ` · ${item.category}` : ''} · {item.quality}
                {typeof item.coverage_percent === 'number' &&
                Number.isFinite(item.coverage_percent)
                  ? ` · coverage ${item.coverage_percent}`
                  : ''}
                {typeof item.image_count === 'number' ? ` · n=${item.image_count}` : ''}
                {typeof item.z_score === 'number' && Number.isFinite(item.z_score)
                  ? ` · z=${item.z_score}`
                  : ''}
              </li>
            ))}
          </ul>
        )}
      </td>
      <td>
        {concordance === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span>
            {concordanceStateLabel(concordance.state)}{' '}
            <span className="text-muted">({concordance.state})</span>
            {concordance.anomalous_metrics.length > 0 && (
              <span className="text-muted">
                {' '}
                · anomalous: {concordance.anomalous_metrics.join(', ')}
              </span>
            )}
          </span>
        )}
      </td>
      <td>
        {persistence === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span>
            {persistenceStateLabel(persistence.state)}{' '}
            <span className="text-muted">({persistence.state})</span>
            <span className="text-muted">
              {' '}
              · below {persistence.longest_run_below} / above{' '}
              {persistence.longest_run_above} · observed {persistence.n_observed} /
              missing {persistence.n_missing}
            </span>
          </span>
        )}
      </td>
    </tr>
  );
}
