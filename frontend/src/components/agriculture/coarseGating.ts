import type { EvidenceItemResponse, ProvenanceResponse } from '../../types/index.ts';

/**
 * Determine if an evidence item or provenance describes a coarse regional context.
 */
export function isCoarseContext(
  itemOrProv?: EvidenceItemResponse | ProvenanceResponse | null,
): boolean {
  if (!itemOrProv) return false;
  if ('quality_state' in itemOrProv && itemOrProv.quality_state === 'coarse_context') {
    return true;
  }
  if ('is_coarse_context' in itemOrProv && Boolean((itemOrProv as EvidenceItemResponse).is_coarse_context)) {
    return true;
  }
  if ('provenance' in itemOrProv) {
    const prov = (itemOrProv as EvidenceItemResponse).provenance;
    if (prov && (prov.quality_state === 'coarse_context' || (prov.native_resolution_m && prov.native_resolution_m > 30))) {
      return true;
    }
  }
  return false;
}

/**
 * Format a Persian badge description for coarse context resolution.
 */
export function formatCoarseResolutionFa(nativeM?: number | null): string {
  if (!nativeM || nativeM <= 30) return 'زمینه منطقه‌ای';
  const km = nativeM / 1000;
  if (km >= 1) {
    const kmStr = Number.isInteger(km) ? km.toString() : km.toFixed(1);
    return `زمینه منطقه‌ای ~${kmStr} کیلومتر`;
  }
  return `زمینه منطقه‌ای ~${Math.round(nativeM)} متر`;
}
