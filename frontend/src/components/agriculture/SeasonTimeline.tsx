import type { EvidenceBundleResponse } from '../../types';
import { findEvidenceItem, formatEvidenceValue, isFiniteNumber } from './parse';

interface SeasonTimelineProps {
  title: string;
  titleFa: string;
  metricKeys: string[];
  bundles: Record<string, EvidenceBundleResponse>;
}

interface SeasonPoint {
  key: string;
  label: string;
  labelFa: string;
  value: unknown;
}

/** Fractional-year position (0–100) of a decimal-year scalar, or null. */
function decimalYearPosition(value: unknown): number | null {
  if (!isFiniteNumber(value)) return null;
  const fractional = value - Math.floor(value);
  if (fractional < 0 || fractional >= 1) return null;
  return Math.round(fractional * 100);
}

/**
 * Season timeline from actual scalar decimal-year points (F2 §8/§18).
 * Missing points render as dashes — never converted into dates.
 */
export default function SeasonTimeline({
  title,
  titleFa,
  metricKeys,
  bundles,
}: SeasonTimelineProps) {
  const points: SeasonPoint[] = metricKeys.map((key) => {
    const found = findEvidenceItem(bundles, key);
    const labels: Record<string, [string, string]> = {
      vegetation_season_onset: ['Onset', 'آغاز'],
      vegetation_activity_peak: ['Peak', 'اوج'],
      vegetation_season_end: ['End', 'پایان'],
    };
    const label = labels[key] ?? [key, key];
    return { key, label: label[0], labelFa: label[1], value: found?.item.value };
  });

  const allMissing = points.every((point) => !isFiniteNumber(point.value));

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">
          {titleFa} — {title}
        </span>
      </div>
      <div className="card-body">
        {allMissing ? (
          <div className="empty-state" style={{ padding: '16px' }}>
            <div className="empty-state-desc">نقاط فصل موجود نیست — no season points</div>
          </div>
        ) : (
          <div style={{ position: 'relative', height: 92, marginTop: 8 }} dir="ltr">
            <div
              style={{
                position: 'absolute',
                top: 40,
                left: 0,
                right: 0,
                height: 4,
                backgroundColor: 'var(--color-border)',
                borderRadius: 2,
              }}
            />
            {points.map((point) => {
              const position = decimalYearPosition(point.value);
              if (position === null) {
                return (
                  <div key={point.key} style={{ marginBottom: 4 }}>
                    <code>{point.key}</code>{' '}
                    <span className="text-muted">—</span>
                  </div>
                );
              }
              return (
                <div
                  key={point.key}
                  style={{ position: 'absolute', left: `${position}%`, top: 0 }}
                >
                  <div style={{ fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                    {point.labelFa} ({point.label})
                  </div>
                  <div
                    style={{
                      width: 12,
                      height: 12,
                      borderRadius: '50%',
                      backgroundColor: 'var(--color-primary)',
                      margin: '2px auto',
                    }}
                  />
                  <div style={{ fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                    <code>{formatEvidenceValue(point.value, 2)}</code>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
