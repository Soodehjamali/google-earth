import type { EvidenceBundleResponse } from '../../types';
import { findEvidenceItem, qualityToKpiStatus, shouldRenderKpi } from './parse';
import { bandRows, dominantClassLabel, isDynamicWorldMetric } from './evidenceDetails';
import { isStateProxyItem } from './proxyState';
import ProxyStateCard from './ProxyStateCard';
import KPICard from '../KPICard';
import { evidenceWindowText } from './evidence';
import { BAND_LABELS } from './DynamicWorldBands';
import { SupportBadge, UnavailableReason } from './SupportNotice';
import { supportInfoOf } from './support';
import { getMetricInterpretation } from './metricInterpretation';
import CoarseContextBadge from './CoarseContextBadge';

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
                  <div className="kpi-value kpi-value-block">
                    {missing ? (
                      <UnavailableReason item={item} compact />
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
            // Dynamic World: show candidate class context when band means exist.
            const dwCandidate = isDynamicWorldMetric(item.metric_key)
              ? bandRows(item.band_means).find((row) => row.value !== null)
              : undefined;
            const windowText = evidenceWindowText(item);
            const support = supportInfoOf(item.provenance);
            const interp = getMetricInterpretation(
              key,
              typeof item.value === 'number' ? item.value : null,
            );
            return (
              <KPICard
                key={key}
                title={dwCandidate ? `${key} — highest mean class` : key}
                titleFa={item.display_name || key}
                value={
                  dwCandidate && typeof dwCandidate.value === 'number'
                    ? `${BAND_LABELS[dwCandidate.band] ?? dwCandidate.band} ${dwCandidate.value.toFixed(2)}`
                    : typeof item.value === 'number'
                      ? item.value
                      : null
                }
                unit={dwCandidate ? (item.unit ?? '') : item.unit}
                icon="📊"
                status={qualityToKpiStatus(item.quality, item.quality_state)}
                subtitle={`${bundleName}${item.is_proxy ? ' • proxy' : ''}${
                  item.source_dataset ? ` • ${item.source_dataset}` : ''
                }${windowText ? ` • ${windowText}` : ''}`}
                referenceRange={interp.rangeLabelFa}
                farmerNote={interp.farmerSummaryFa}
                resolution={interp.spatialResolution}
                statusLabelFa={interp.statusLabelFa}
                footer={
                  <div className="kpi-support">
                    <CoarseContextBadge item={item} provenance={item.provenance} />
                    <SupportBadge provenance={item.provenance} />
                    {support && (
                      <div className="kpi-support-note">
                        {support.explanationEn}
                      </div>
                    )}
                  </div>
                }
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
