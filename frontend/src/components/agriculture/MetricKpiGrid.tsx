import type { EvidenceBundleResponse } from '../../types';
import { findEvidenceItem, qualityToKpiStatus, shouldRenderKpi } from './parse';
import { dominantClassLabel } from './evidenceDetails';
import { isStateProxyItem } from './proxyState';
import ProxyStateCard from './ProxyStateCard';
import KPICard from '../KPICard';

interface MetricKpiGridProps {
  title: string;
  titleFa: string;
  metricKeys: string[];
  bundles: Record<string, EvidenceBundleResponse>;
  note?: string;
}

/**
 * Grouped scalar KPI grid (F2). Each key resolves by exact metric key
 * across the page's bundles. Usable finite values render as KPICard;
 * null/unavailable/absent keys render explicit textual rows — never
 * zero, never a fabricated distribution.
 */
export default function MetricKpiGrid({
  title,
  titleFa,
  metricKeys,
  bundles,
  note,
}: MetricKpiGridProps) {
  return (
    <div className="card mb-3">
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
        <div className="kpi-grid">
          {metricKeys.map((key) => {
            const found = findEvidenceItem(bundles, key);
            if (!found) {
              return (
                <div key={key} className="kpi-card kpi-status-neutral">
                  <div className="kpi-header">
                    <div className="kpi-titles">
                      <h3 className="kpi-title-fa">{key}</h3>
                    </div>
                  </div>
                  <div className="kpi-value">
                    <span className="kpi-no-data">در نتیجه فعلی نیست — not in current result</span>
                  </div>
                </div>
              );
            }
            const { item, bundleName } = found;
            if (!shouldRenderKpi(item)) {
              // P2A: the land-cover class key is categorical, not
              // scalar. When the response carries its class shares it
              // shows the dominant class instead of an "unavailable"
              // card that would contradict the shares section above.
              const dominantLabel = dominantClassLabel(item);
              if (dominantLabel !== null) {
                return (
                  <div key={key} className="kpi-card kpi-status-neutral">
                    <div className="kpi-header">
                      <div className="kpi-titles">
                        <h3 className="kpi-title-fa">{item.display_name || key}</h3>
                        <span className="kpi-title-en">{key}</span>
                      </div>
                    </div>
                    <div className="kpi-value">
                      <span style={{ fontSize: '1rem', fontWeight: 600, wordBreak: 'break-word' }}>
                        {dominantLabel}
                      </span>
                    </div>
                    <div className="kpi-subtitle">
                      {bundleName} • dominant class
                    </div>
                  </div>
                );
              }
              const missing =
                item.status === 'unavailable' || item.value === null || item.value === undefined;
              return (
                <div key={key} className="kpi-card kpi-status-neutral">
                  <div className="kpi-header">
                    <div className="kpi-titles">
                      <h3 className="kpi-title-fa">{item.display_name || key}</h3>
                      <span className="kpi-title-en">{key}</span>
                    </div>
                  </div>
                  <div className="kpi-value">
                    {missing ? (
                      <span>
                        <span className="kpi-no-data">داده موجود نیست</span>{' '}
                        <span className="badge badge-danger" style={{ fontSize: '11px' }}>
                          unavailable
                        </span>
                      </span>
                    ) : (
                      <span className="kpi-no-data">—</span>
                    )}
                  </div>
                  <div className="kpi-subtitle">
                    {bundleName}
                    {item.is_proxy ? ' • proxy' : ''}
                  </div>
                </div>
              );
            }
            // State-based proxy evidence renders its categorical legend,
            // never a numeric KPI. Null/unavailable proxies stay on the
            // textual branch above, so state 5 and missing stay distinct.
            if (isStateProxyItem(item)) {
              return <ProxyStateCard key={key} item={item} bundleName={bundleName} />;
            }
            return (
              <KPICard
                key={key}
                title={key}
                titleFa={item.display_name || key}
                value={typeof item.value === 'number' ? item.value : null}
                unit={item.unit}
                icon="📊"
                status={qualityToKpiStatus(item.quality)}
                subtitle={`${bundleName}${item.is_proxy ? ' • proxy' : ''}`}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
