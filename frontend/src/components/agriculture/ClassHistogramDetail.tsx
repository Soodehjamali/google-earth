import type { EvidenceItemResponse } from '../../types/index.ts';
import { formatEvidenceValue } from './parse.ts';
import { DetailDisclosure } from './StructuredDetails.tsx';
import { histogramRows, isHistogramMetric } from './evidenceDetails.ts';

/**
 * H — ranked class distribution for the two categorical metrics.
 *
 * Dominant line + compact table (code, name, pixels, % classified,
 * % of geometry), sorted by % classified descending with the code
 * always visible. CSS bars are plain divs with textual values.
 * No circular charts, no area conversion, classes 12/14 never merged
 * (merging would happen only in backend data, which is untouched).
 */
export default function ClassHistogramDetail({ item }: { item: EvidenceItemResponse }) {
  if (!isHistogramMetric(item.metric_key)) return null;
  const rows = histogramRows(item.class_histogram);
  if (rows.length === 0) {
    if (!item.class_histogram) return null;
    return (
      <div className="empty-state" style={{ padding: '12px' }}>
        <div className="empty-state-desc">توزیعی موجود نیست — no distribution</div>
      </div>
    );
  }
  const isQuality = item.metric_key === 'land_cover_quality';
  const top = rows[0];
  const maxPercent = top.percent > 0 ? top.percent : 1;
  return (
    <DetailDisclosure
      titleFa={isQuality ? 'توزیع پرچم‌های کیفیت' : 'توزیع کلاس'}
      titleEn={isQuality ? 'Flag distribution' : 'Class distribution'}
    >
      <div className="evidence-detail-row">
        <span className="text-muted">
          {isQuality ? 'Most frequent flag:' : 'Dominant:'}
        </span>{' '}
        <strong>
          {top.name || top.code} ({top.code}) —{' '}
          <code dir="ltr">{formatEvidenceValue(top.percent, 1)}%</code>{' '}
          {isQuality ? 'of flagged' : 'of classified'}
        </strong>
      </div>
      {isQuality && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
          QC codes are processing-event codes, not a quality ranking.
        </div>
      )}
      <div style={{ marginTop: 4 }} dir="ltr">
        {rows.map((row) => (
          <div key={row.code} style={{ marginBottom: 6 }}>
            <div
              style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: '0.8rem' }}
            >
              <span>
                <code>{row.code}</code> {row.name}
              </span>
              <span className="text-muted">
                <code>{formatEvidenceValue(row.pixel_count, 0)}</code> px ·{' '}
                <code>{formatEvidenceValue(row.percent, 1)}%</code> classified ·{' '}
                <code>{formatEvidenceValue(row.percent_of_geometry, 1)}%</code> of geometry
              </span>
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
                  width: `${Math.min(100, Math.max(0, (row.percent / maxPercent) * 100))}%`,
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
