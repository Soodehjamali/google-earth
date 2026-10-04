import type { EvidenceItemResponse } from '../../types/index.ts';
import { formatEvidenceValue } from './parse.ts';
import { DetailDisclosure } from './StructuredDetails.tsx';
import {
  DYNAMIC_WORLD_DOMINANT_FLOOR,
  bandRows,
  isDynamicWorldMetric,
} from './evidenceDetails.ts';

const BAND_LABELS: Record<string, string> = {
  water: 'Water',
  trees: 'Trees',
  grass: 'Grass',
  flooded_vegetation: 'Flooded vegetation',
  crops: 'Crops',
  shrub_and_scrub: 'Shrub and scrub',
  built: 'Built',
  bare: 'Bare',
  snow_and_ice: 'Snow and ice',
};

/**
 * DW — nine-band mean-probability list for land_cover_probability.
 *
 * Ranked descending (nulls last, shown as em dash), values as 0-1
 * probabilities with a 0-1 bar track. The top non-null row carries the
 * candidate marker. No percentages, no area, no label/argmax band
 * (structurally excluded by bandRows), no dominant-class invention.
 */
export default function DynamicWorldBands({ item }: { item: EvidenceItemResponse }) {
  if (!isDynamicWorldMetric(item.metric_key)) return null;
  const rows = bandRows(item.band_means);
  if (rows.length === 0) return null;
  if (rows.every((row) => row.value === null)) {
    return (
      <div className="empty-state" style={{ padding: '12px' }}>
        <div className="empty-state-desc">احتمال باندی موجود نیست — no band probabilities</div>
      </div>
    );
  }
  const candidate = rows.find((row) => row.value !== null)?.band;
  return (
    <DetailDisclosure titleFa="احتمال‌های باند" titleEn="Band probabilities">
      <div className="evidence-detail-row">
        <span className="text-muted">Candidate dominant context:</span>{' '}
        <strong>
          {candidate ? (BAND_LABELS[candidate] ?? candidate) : '—'}
        </strong>{' '}
        <span className="text-muted" style={{ fontSize: '0.8rem' }}>
          (context signal, not a hard classification)
        </span>
      </div>
      <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
        Reporting convention: below {DYNAMIC_WORLD_DOMINANT_FLOOR.toFixed(2)} mean
        probability no class is called dominant. Values are mean probabilities
        (0–1), not shares of the area.
      </div>
      <div style={{ marginTop: 4 }} dir="ltr">
        {rows.map((row) => (
          <div key={row.band} style={{ marginBottom: 6 }}>
            <div
              style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: '0.8rem' }}
            >
              <span>
                {BAND_LABELS[row.band] ?? row.band}{' '}
                {row.band === candidate && (
                  <span className="badge badge-info" style={{ fontSize: '10px' }}>
                    candidate
                  </span>
                )}
              </span>
              <code>{row.value === null ? '—' : formatEvidenceValue(row.value, 2)}</code>
            </div>
            <div
              style={{
                height: 6,
                backgroundColor: 'var(--color-border)',
                borderRadius: 3,
                marginTop: 2,
              }}
            >
              <div
                style={{
                  width: `${row.value === null ? 0 : Math.min(100, Math.max(0, row.value * 100))}%`,
                  height: '100%',
                  backgroundColor: 'var(--color-primary)',
                  borderRadius: 3,
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </DetailDisclosure>
  );
}
