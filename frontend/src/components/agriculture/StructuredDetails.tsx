import { useId, useState } from 'react';
import type { EvidenceItemResponse } from '../../types/index.ts';
import { formatEvidenceValue } from './parse.ts';
import {
  coverageRows,
  cropShare,
  isCropShareMetric,
  isSpatialStatsMetric,
  spatialStatRows,
  temporalRange,
} from './evidenceDetails.ts';

/**
 * F3-B structured detail renderers (S1/S2/S3).
 *
 * Pattern: existing KPI stays primary; each renderer below is an
 * optional collapsible secondary detail using the ProvenanceDrawer
 * interaction shape (real button, expanded state, textual values).
 * Every renderer returns null outside its explicit semantic map, so a
 * Type-B/C metric can never flow through S1 and coverage fields can
 * never leak from synthetic stats.
 */

export function DetailDisclosure({
  titleFa,
  titleEn,
  children,
}: {
  titleFa: string;
  titleEn: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <div className="evidence-detail-row">
      <button
        className="btn btn-sm btn-secondary"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-controls={panelId}
      >
        {open ? '▼' : '▶'} {titleFa} — {titleEn}
      </button>
      {open && (
        <div id={panelId} style={{ marginTop: 8 }}>
          {children}
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="evidence-detail-row"
      style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}
      dir="ltr"
    >
      <span className="text-muted">{label}</span>
      <code>{value}</code>
    </div>
  );
}

/**
 * S1 — spatial spread detail for Type-A metrics only.
 * Fixed field order; null fields omitted; stats-null renders nothing.
 */
export function SpatialStatsDetail({ item }: { item: EvidenceItemResponse }) {
  if (!isSpatialStatsMetric(item.metric_key)) return null;
  const statRows = spatialStatRows(item.stats);
  const coverRows = coverageRows(item.stats);
  if (statRows.length === 0 && coverRows.length === 0) return null;
  const showApproximationNote = item.metric_key === 'surface_temperature_range';
  const showProxyNote = item.metric_key === 'par';
  return (
    <DetailDisclosure titleFa="پراکندگی مکانی" titleEn="Spatial spread">
      <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
        Spatial distribution over the analysis area ({item.unit || '—'})
      </div>
      {showApproximationNote && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
          Approximate: per-quantile day−night differences — see provenance.
        </div>
      )}
      {showProxyNote && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
          Fixed-coefficient approximation, not a measurement — see provenance.
        </div>
      )}
      {statRows.map((row) => (
        <DetailRow
          key={row.key}
          label={`${row.labelFa} (${row.labelEn})`}
          value={formatEvidenceValue(row.value, 3)}
        />
      ))}
      {coverRows.length > 0 && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
          {coverRows.map((row) => (
            <DetailRow
              key={row.key}
              label={`${row.labelFa} (${row.labelEn})`}
              value={formatEvidenceValue(row.value, 1)}
            />
          ))}
        </div>
      )}
    </DetailDisclosure>
  );
}

/**
 * S2 — temporal/composite range for Type-B metrics only.
 * Min/max with the truthful temporal label; coverage fields and mean
 * are never rendered here (counts are days/composites; mean is the KPI).
 */
export function TemporalRangeDetail({ item }: { item: EvidenceItemResponse }) {
  const range = temporalRange(item.metric_key, item.stats);
  if (!range) return null;
  const label =
    range.kind === 'daily'
      ? 'محدوده روزانه — daily range'
      : 'محدوده دوره ترکیبی — composite range';
  return (
    <div className="evidence-detail-row">
      <span className="text-muted">{label}:</span>{' '}
      <code dir="ltr">
        {formatEvidenceValue(range.min, 3)} – {formatEvidenceValue(range.max, 3)}{' '}
        {item.unit}
      </code>
    </div>
  );
}

/**
 * S3 — classified share for the four WorldCereal crop-context metrics.
 * Mean only (as %); distribution fields suppressed; no area conversion.
 */
export function CropShareDetail({ item }: { item: EvidenceItemResponse }) {
  if (!isCropShareMetric(item.metric_key)) return null;
  const share = cropShare(item.metric_key, item.stats);
  if (!share) return null;
  const coverRows = coverageRows(item.stats);
  return (
    <DetailDisclosure titleFa="سهم طبقه‌بندی‌شده" titleEn="Classified share">
      <div className="evidence-detail-row">
        <span className="text-muted">Share of classified area:</span>{' '}
        <strong>
          <code dir="ltr">{formatEvidenceValue(share.percent, 1)}%</code>
        </strong>
      </div>
      {coverRows
        .filter((row) =>
          ['coverage_percent', 'valid_pixel_count', 'total_pixel_count'].includes(row.key),
        )
        .map((row) => (
          <DetailRow
            key={row.key}
            label={`${row.labelFa} (${row.labelEn})`}
            value={formatEvidenceValue(row.value, 1)}
          />
        ))}
      <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
        2021 reference-year product; the share describes the classified part only —
        never total agricultural area.
      </div>
    </DetailDisclosure>
  );
}
