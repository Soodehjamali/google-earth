import type { EvidenceItemResponse, ProvenanceResponse } from '../../types';
import { isCoarseContext, formatCoarseResolutionFa } from './coarseGating';

export { isCoarseContext, formatCoarseResolutionFa };

interface CoarseContextBadgeProps {
  item?: EvidenceItemResponse | null;
  provenance?: ProvenanceResponse | null;
  className?: string;
}

export default function CoarseContextBadge({
  item,
  provenance,
  className = '',
}: CoarseContextBadgeProps) {
  const prov = provenance || item?.provenance;
  const isCoarse = isCoarseContext(item) || isCoarseContext(prov);
  if (!isCoarse) return null;

  const nativeM = prov?.native_resolution_m ?? item?.native_resolution_m;
  const badgeTextFa = prov?.support_description_fa || formatCoarseResolutionFa(nativeM);
  const elevNote =
    prov?.cell_elevation_m !== undefined &&
    prov?.cell_elevation_m !== null &&
    prov?.site_elevation_m !== undefined &&
    prov?.site_elevation_m !== null
      ? ` (تراز سلول: ${prov.cell_elevation_m}m، مزرعه: ${prov.site_elevation_m}m)`
      : '';

  const tooltip =
    (prov?.support_description || 'Regional reanalysis / satellite context; footprint is broader than field extent.') +
    ' داده‌های زمینه منطقه‌ای برای مقایسه درون‌مزرعه‌ای یا پهنه‌بندی استفاده نمی‌شوند.' +
    elevNote;

  return (
    <span
      className={`coarse-context-badge badge ${className}`}
      title={tooltip}
      data-testid="coarse-context-badge"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        backgroundColor: '#fef3c7',
        color: '#92400e',
        border: '1px solid #fcd34d',
        borderRadius: '4px',
        padding: '2px 6px',
        fontSize: '0.75rem',
        fontWeight: 600,
      }}
    >
      <span aria-hidden="true">🌐</span>
      <span>{badgeTextFa}</span>
    </span>
  );
}
