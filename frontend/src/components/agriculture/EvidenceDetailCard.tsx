import type { EvidenceItemResponse } from '../../types';
import { formatEvidenceValue, qualityToKpiStatus, shouldRenderKpi } from './parse';
import { isStateProxyItem } from './proxyState';
import ProxyStateCard from './ProxyStateCard';
import ClassHistogramDetail from './ClassHistogramDetail';
import DynamicWorldBands from './DynamicWorldBands';
import ProvenanceDrawer from './ProvenanceDrawer';
import { CropShareDetail, SpatialStatsDetail, TemporalRangeDetail } from './StructuredDetails';
import KPICard from '../KPICard';

interface EvidenceDetailProps {
  item: EvidenceItemResponse;
  bundleName: string;
  showKpi?: boolean;
}

/**
 * Shared evidence renderer (F1).
 * A finite numeric value on a usable item may render as a KPI.
 * Null/unavailable items render an explicit textual state — never zero.
 */
export default function EvidenceDetailCard({
  item,
  bundleName,
  showKpi = true,
}: EvidenceDetailProps) {
  const renderKpi = showKpi && shouldRenderKpi(item);
  const unavailable = item.status === 'unavailable' || item.value === null || item.value === undefined;
  // Categorical proxy states keep their legend rendering; anything
  // without a finite value keeps the explicit textual branch below.
  const renderProxyState = showKpi && isStateProxyItem(item) && renderKpi;

  return (
    <div className="evidence-detail-card">
      <div className="evidence-detail-header">
        <code className="evidence-metric-key">{item.metric_key}</code>
        <div className="evidence-detail-badges">
          <span
            className={`badge ${item.status === 'unavailable' ? 'badge-danger' : 'badge-info'}`}
          >
            {item.status}
          </span>
          <span className={`badge badge-${qualityToKpiStatus(item.quality)}`}>
            {item.quality}
          </span>
          {item.is_proxy && <span className="badge badge-warning">proxy</span>}
        </div>
      </div>

      <div className="evidence-detail-body">
        {renderProxyState ? (
          <ProxyStateCard item={item} bundleName={bundleName} />
        ) : renderKpi ? (
          <KPICard
            title={item.metric_key}
            titleFa={item.display_name || item.metric_key}
            value={typeof item.value === 'number' ? item.value : null}
            unit={item.unit}
            icon="📊"
            status={qualityToKpiStatus(item.quality)}
            subtitle={item.source_dataset ?? undefined}
          />
        ) : (
          <div className="evidence-detail-row">
            <span className="text-muted">مقدار:</span>{' '}
            <span>
              <strong>{formatEvidenceValue(item.value)}</strong>{' '}
              {unavailable ? (
                <span className="badge badge-danger" style={{ fontSize: '11px' }}>
                  unavailable
                </span>
              ) : (
                item.unit
              )}
            </span>
          </div>
        )}

        <div className="evidence-detail-row">
          <span className="text-muted">مجموعه داده:</span>
          <span>{item.source_dataset || '—'}</span>
        </div>
        <div className="evidence-detail-row">
          <span className="text-muted">حوزه:</span>
          <span>{bundleName}</span>
        </div>
        {item.display_name && (
          <div className="evidence-detail-row">
            <span className="text-muted">نام:</span>
            <span>{item.display_name}</span>
          </div>
        )}

        <SpatialStatsDetail item={item} />
        <TemporalRangeDetail item={item} />
        <CropShareDetail item={item} />
        <ClassHistogramDetail item={item} />
        <DynamicWorldBands item={item} />

        <ProvenanceDrawer provenance={item.provenance} />
      </div>
    </div>
  );
}
