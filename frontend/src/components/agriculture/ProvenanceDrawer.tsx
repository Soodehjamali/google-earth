import { useState } from 'react';
import type { ProvenanceResponse } from '../../types';
import { getProvenanceRows } from './parse';

interface ProvenanceDrawerProps {
  provenance: ProvenanceResponse | null | undefined;
}

/**
 * Shared provenance renderer (F1). Exposes only fields the backend
 * actually returned. Missing provenance renders nothing — never fabricated.
 */
export default function ProvenanceDrawer({ provenance }: ProvenanceDrawerProps) {
  const [open, setOpen] = useState(false);
  const rows = getProvenanceRows(provenance);
  const limitations = Array.isArray(provenance?.limitations)
    ? provenance.limitations.filter(
        (entry): entry is string => typeof entry === 'string',
      )
    : [];
  const caveats = Array.isArray(provenance?.caveats)
    ? provenance.caveats.filter(
        (entry): entry is string => typeof entry === 'string',
      )
    : [];

  if (!provenance) return null;

  return (
    <div className="evidence-provenance">
      <button
        className="btn btn-sm btn-secondary"
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? '▼' : '▶'} منبع — Provenance
      </button>
      {open && (
        <>
          {rows.length > 0 ? (
            <div className="provenance-grid">
              {rows.map((row) => (
                <div key={row.key} className="provenance-item">
                  <span className="text-muted">{row.label}:</span>{' '}
                  {row.key === 'formula' || row.key === 'source_dataset_id' ? (
                    <code>{row.value}</code>
                  ) : (
                    <span>{row.value}</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>
              جزئیات منبع موجود نیست
            </div>
          )}

          {limitations.length > 0 && (
            <div className="provenance-limitations">
              <strong>محدودیت‌های علمی:</strong>
              <ul>
                {limitations.map((lim, i) => (
                  <li key={i}>{lim}</li>
                ))}
              </ul>
            </div>
          )}

          {caveats.length > 0 && (
            <div className="provenance-caveats">
              <strong>تذکرات:</strong>
              <ul>
                {caveats.map((cav, i) => (
                  <li key={i}>{cav}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
