import type { EvidenceItemResponse } from '../../types';
import { PROXY_STATE_META, proxyStateFor } from './proxyState';
import { qualityToKpiStatus } from './parse';

interface ProxyStateCardProps {
  item: EvidenceItemResponse;
  bundleName: string;
}

/**
 * Categorical state rendering for the middle-canopy dryness proxy
 * (CD-6). Shows the backend state label — never a numeric share, a
 * dryness score, or a physical quantity. All five states share one
 * neutral tone so no state visually implies a severity level.
 * Unknown codes render an explicit marker, never a guessed label.
 */
export default function ProxyStateCard({ item, bundleName }: ProxyStateCardProps) {
  const state = proxyStateFor(item.value);
  const codes = Object.values(PROXY_STATE_META).sort((a, b) => a.code - b.code);

  return (
    <div className="kpi-card kpi-status-neutral">
      <div className="kpi-header">
        <span className="kpi-icon">🧭</span>
        <div className="kpi-titles">
          <h3 className="kpi-title-fa">{item.display_name || item.metric_key}</h3>
          <span className="kpi-title-en">{item.metric_key}</span>
        </div>
      </div>
      <div className="kpi-value">
        {state ? (
          <span>
            <strong>{state.labelFa}</strong> — <span>{state.label}</span>{' '}
            <code className="evidence-key-link">state {state.code}</code>
          </span>
        ) : (
          <span className="kpi-no-data">حالت نامشخص — unrecognized state code</span>
        )}
      </div>
      <div className="kpi-subtitle">
        {bundleName} • proxy • categorical state, not a measurement
      </div>
      <div style={{ marginTop: 8 }}>
        <span className="badge badge-warning">proxy</span>{' '}
        <span className={`badge badge-${qualityToKpiStatus(item.quality)}`}>
          {item.quality}
        </span>
      </div>
      <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: 8 }}>
        {codes.map((entry) => (
          <span key={entry.code}>
            <span style={entry.code === state?.code ? { fontWeight: 'bold' } : undefined}>
              {entry.code}: {entry.labelFa}
            </span>
            {entry.code < codes.length ? ' · ' : ''}
          </span>
        ))}
      </div>
    </div>
  );
}
