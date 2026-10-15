/**
 * Dynamic Coverage Summary & Metric Partitioning Utilities (Phase 2 Task 2.3).
 *
 * Enforces strict scientific honesty:
 * 1. Coarse context metrics (K) are NEVER counted as valid (N) in the coverage numerator.
 * 2. Total applicable metrics (M) reflects the requested domains or all active registered metrics.
 * 3. Provides clean Persian formatting and partitioned metric inventory for drawer/modal inspection.
 */
import type {
  AgriculturalAnalysisResponse,
  CoverageSummaryResponse,
  EvidenceBundleResponse,
} from '../../types/index.ts';
import { isCoarseContext, formatCoarseResolutionFa } from './coarseGating.ts';

/**
 * Persian number formatter converting Western digits (0-9) to Persian digits (۰-۹).
 */
export function toPersianDigits(val: number | string): string {
  const str = String(val);
  const persianDigits = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
  return str.replace(/\d/g, (match) => persianDigits[Number(match)]);
}

/**
 * Parsed metric record categorized for the coverage inventory inspection.
 */
export interface InventoryMetricItem {
  metricKey: string;
  displayName: string;
  domainName: string;
  sourceDataset: string;
  valueDisplay: string;
  unit: string;
  qualityState: 'valid' | 'coarse_context' | 'unavailable';
  nativeResolutionM?: number | null;
  supportDescription?: string | null;
  resolutionFa?: string | null;
  unavailableReason?: string | null;
  unavailableMessage?: string | null;
}

/**
 * Extract or dynamically derive coverage counts from an analysis response.
 */
export function getCoverageCounts(result: AgriculturalAnalysisResponse): CoverageSummaryResponse {
  if (result.coverage && typeof result.coverage.total === 'number' && result.coverage.total > 0) {
    return result.coverage;
  }

  // Fallback: derive dynamically from evidence_bundles for legacy reports
  const bundles = result.evidence_bundles || {};
  let valid = 0;
  let coarse = 0;
  let unavailable = 0;
  const byDomain: CoverageSummaryResponse['by_domain'] = {};

  for (const [domainKey, bundle] of Object.entries(bundles)) {
    let dValid = 0;
    let dCoarse = 0;
    let dUnavailable = 0;

    const items = bundle.items || [];
    for (const item of items) {
      if (isCoarseContext(item)) {
        dCoarse += 1;
      } else if (item.is_usable && item.quality_state !== 'unavailable') {
        dValid += 1;
      } else {
        dUnavailable += 1;
      }
    }

    const unavKeys = bundle.unavailable || [];
    dUnavailable += unavKeys.length;

    const dTotal = dValid + dCoarse + dUnavailable;
    const dRatio = dTotal > 0 ? Number((dValid / dTotal).toFixed(4)) : 0;

    byDomain[domainKey] = {
      valid: dValid,
      coarse_context: dCoarse,
      unavailable: dUnavailable,
      total: dTotal,
      valid_ratio: dRatio,
    };

    valid += dValid;
    coarse += dCoarse;
    unavailable += dUnavailable;
  }

  const total = valid + coarse + unavailable;
  const validRatio = total > 0 ? Number((valid / total).toFixed(4)) : 0;

  return {
    valid,
    coarse_context: coarse,
    unavailable,
    total,
    valid_ratio: validRatio,
    by_domain: byDomain,
  };
}

/**
 * Formats the primary coverage line: "N از M شاخص دادهٔ معتبر دارند".
 */
export function formatCoveragePrimaryFa(validCount: number, totalCount: number): string {
  return `${toPersianDigits(validCount)} از ${toPersianDigits(totalCount)} شاخص دادهٔ معتبر دارند`;
}

/**
 * Formats the secondary regional context line: "+ K شاخص زمینه منطقه‌ای".
 */
export function formatCoverageSecondaryFa(coarseCount: number): string {
  return `+ ${toPersianDigits(coarseCount)} شاخص زمینه منطقه‌ای`;
}

/**
 * Formats the ratio percentage in Persian digits with percent sign.
 */
export function formatPercentageFa(ratio: number): string {
  const pct = Math.round(ratio * 100);
  return `${toPersianDigits(pct)}٪`;
}

/**
 * Partition all bundle items into valid, coarse context, and unavailable lists for detailed drill-down.
 */
export function partitionMetricsForInventory(
  bundles: Record<string, EvidenceBundleResponse>,
): {
  validMetrics: InventoryMetricItem[];
  coarseMetrics: InventoryMetricItem[];
  unavailableMetrics: InventoryMetricItem[];
} {
  const validMetrics: InventoryMetricItem[] = [];
  const coarseMetrics: InventoryMetricItem[] = [];
  const unavailableMetrics: InventoryMetricItem[] = [];
  const seenKeys = new Set<string>();

  for (const [domainKey, bundle] of Object.entries(bundles)) {
    const items = bundle.items || [];
    for (const item of items) {
      if (seenKeys.has(item.metric_key)) continue;
      seenKeys.add(item.metric_key);

      const prov = item.provenance;
      const nativeRes = item.native_resolution_m ?? prov?.native_resolution_m ?? null;
      const suppDesc = item.support_description ?? prov?.support_description ?? null;
      const resFa = formatCoarseResolutionFa(nativeRes);

      let valStr = '—';
      if (item.value !== null && item.value !== undefined) {
        valStr = `${toPersianDigits(item.value)} ${item.unit || ''}`.trim();
      }

      let qState: 'valid' | 'coarse_context' | 'unavailable' = 'valid';
      if (item.quality_state === 'valid' || item.quality_state === 'coarse_context' || item.quality_state === 'unavailable') {
        qState = item.quality_state;
      } else if (isCoarseContext(item)) {
        qState = 'coarse_context';
      } else if (item.is_usable) {
        qState = 'valid';
      } else {
        qState = 'unavailable';
      }

      const record: InventoryMetricItem = {
        metricKey: item.metric_key,
        displayName: item.display_name || item.metric_key,
        domainName: domainKey,
        sourceDataset: prov?.source_dataset_name || prov?.source_dataset_id || item.source_dataset || 'نامشخص',
        valueDisplay: valStr,
        unit: item.unit || '',
        qualityState: qState,
        nativeResolutionM: nativeRes,
        supportDescription: suppDesc,
        resolutionFa: resFa,
        unavailableReason: item.unavailable_reason || null,
        unavailableMessage: item.unavailable_message || null,
      };

      if (isCoarseContext(item)) {
        coarseMetrics.push(record);
      } else if (item.is_usable && item.quality_state !== 'unavailable') {
        validMetrics.push(record);
      } else {
        unavailableMetrics.push(record);
      }
    }

    // Explicitly unavailable keys in bundle
    for (const unavKey of bundle.unavailable || []) {
      if (seenKeys.has(unavKey)) continue;
      seenKeys.add(unavKey);

      unavailableMetrics.push({
        metricKey: unavKey,
        displayName: unavKey,
        domainName: domainKey,
        sourceDataset: '—',
        valueDisplay: 'ناموجود',
        unit: '',
        qualityState: 'unavailable',
        unavailableReason: 'پوشش ناکافی یا خطا در دریافت داده',
      });
    }
  }

  return { validMetrics, coarseMetrics, unavailableMetrics };
}
