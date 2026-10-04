import type { EvidenceItemResponse } from '../../types/index.ts';
import { classShareModel } from './evidenceDetails.ts';
import { formatEvidenceValue } from './parse.ts';

interface LandCoverSharesSectionProps {
  title: string;
  titleFa: string;
  note?: string;
  item: EvidenceItemResponse | null;
}

/**
 * P2A land-cover class shares (presentation parity with the legacy
 * land-cover view, using only fields the comprehensive response
 * already transports).
 *
 * Renders the dominant class, every supplied class (backend taxonomy
 * name + code), both supplied ratios, and plain CSS bars in a single
 * neutral accent — no per-class color mapping, because the legacy
 * palette is not authoritative for this product. Area in km² is
 * reported as not provided: this contract carries no geometry and no
 * area field, so no conversion is performed or implied.
 */
export default function LandCoverSharesSection({
  title,
  titleFa,
  note,
  item,
}: LandCoverSharesSectionProps): React.ReactElement {
  const model = classShareModel(item);

  let body: React.ReactElement;
  if (model.rows.length === 0) {
    const description = !item
      ? 'Not in current result — the response carried no land-cover class evidence.'
      : model.carried
        ? 'The response carried the metric but no class shares for this analysis.'
        : 'Not in current result — no class shares were transported in this response.';
    body = (
      <div className="empty-state" style={{ padding: '16px' }}>
        <div className="empty-state-title">No class shares to show</div>
        <div className="empty-state-desc">{description}</div>
      </div>
    );
  } else {
    const top = model.rows[0];
    const dominant = model.dominant ?? top;
    const maxPercent = top.percent > 0 ? top.percent : 1;
    const pixels =
      model.valid_pixel_count !== null && model.total_pixel_count !== null
        ? `${formatEvidenceValue(model.valid_pixel_count, 0)} classified of ${formatEvidenceValue(
            model.total_pixel_count,
            0,
          )} total pixels`
        : null;
    body = (
      <>
        <div className="evidence-detail-row">
          <span className="text-muted">Dominant class:</span>{' '}
          <strong>
            {dominant.name || dominant.code} ({dominant.code}) —{' '}
            <code dir="ltr">{formatEvidenceValue(dominant.percent, 1)}%</code> of classified
          </strong>
        </div>
        {pixels !== null && (
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>
            {pixels}
          </div>
        )}
        <div style={{ marginTop: 8 }} dir="ltr">
          {model.rows.map((row) => (
            <div key={row.code} style={{ marginBottom: 6 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 8,
                  fontSize: '0.8rem',
                }}
              >
                <span>
                  <code>{row.code}</code> {row.name}
                </span>
                <span className="text-muted">
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
        <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
          Area per class (km²): not provided by this response — no geometry or
          area field accompanies the class shares, so no area figure is derived here.
        </div>
      </>
    );
  }

  return (
    <section className="card mb-3" aria-label={title}>
      <div className="card-header">
        <span className="card-title">
          {titleFa} — {title}
        </span>
      </div>
      <div className="card-body">
        {note && (
          <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 8 }}>
            {note}
          </div>
        )}
        {body}
      </div>
    </section>
  );
}
