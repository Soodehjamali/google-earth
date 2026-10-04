import type { EvidenceBundleResponse } from '../../types';
import { findEvidenceItem, formatEvidenceValue, isFiniteNumber } from './parse';

interface AspectDialProps {
  title: string;
  titleFa: string;
  metricKey: string;
  bundles: Record<string, EvidenceBundleResponse>;
}

const SECTORS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

/** Standard 8-wind compass sector for a degrees-clockwise-from-north scalar. */
function sectorFor(degrees: number): string {
  const normalized = ((degrees % 360) + 360) % 360;
  return SECTORS[Math.round(normalized / 45) % 8];
}

/**
 * Aspect dial from the actual aspect scalar (F2 §13).
 * A non-finite value falls back to scalar text — never a guessed direction.
 */
export default function AspectDial({ title, titleFa, metricKey, bundles }: AspectDialProps) {
  const found = findEvidenceItem(bundles, metricKey);
  const value = found?.item.value;

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">
          {titleFa} — {title}
        </span>
      </div>
      <div className="card-body">
        {!isFiniteNumber(value) ? (
          <div className="kpi-value">
            <span className="kpi-no-data">داده موجود نیست</span>{' '}
            <code>{metricKey}</code>
          </div>
        ) : (
          <div className="flex gap-1" style={{ alignItems: 'center' }} dir="ltr">
            <div
              style={{
                width: 72,
                height: 72,
                borderRadius: '50%',
                border: '2px solid var(--color-border)',
                position: 'relative',
                flexShrink: 0,
              }}
            >
              <span
                style={{
                  position: 'absolute',
                  top: 2,
                  left: '50%',
                  fontSize: '0.7rem',
                  transform: 'translateX(-50%)',
                }}
              >
                N
              </span>
              <span
                style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  width: 2,
                  height: 26,
                  backgroundColor: 'var(--color-primary)',
                  transformOrigin: '50% 0%',
                  transform: `translateX(-50%) rotate(${value}deg)`,
                }}
              />
              <span
                style={{
                  position: 'absolute',
                  top: '50%',
                  left: '50%',
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  backgroundColor: 'var(--color-primary-dark)',
                  transform: 'translate(-50%, -50%)',
                }}
              />
            </div>
            <div>
              <div>
                <strong>{formatEvidenceValue(value, 1)}°</strong>{' '}
                <span className="badge badge-info">{sectorFor(value)}</span>
              </div>
              <div className="text-muted" style={{ fontSize: '0.8rem' }}>
                <code>{metricKey}</code> {found?.item.unit ?? ''}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
