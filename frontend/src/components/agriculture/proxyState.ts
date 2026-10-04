/**
 * Middle-canopy dryness proxy presentation contract (CD-6).
 *
 * Mirrors the backend state legend exactly — codes 1–5 keep the
 * backend's names and meanings. Nothing here invents an
 * interpretation or a physical quantity.
 */
export const PROXY_METRIC_KEY = 'middle_canopy_dryness_proxy';

export interface ProxyStateMeta {
  code: number;
  /** Backend state name, verbatim. */
  name: string;
  label: string;
  labelFa: string;
}

export const PROXY_STATE_META: Record<number, ProxyStateMeta> = {
  1: {
    code: 1,
    name: 'OPTICAL_STRESS_ONLY',
    label: 'Optical stress only',
    labelFa: 'تنش نوری',
  },
  2: {
    code: 2,
    name: 'RADAR_STRUCTURAL_CONTEXT_ONLY',
    label: 'Radar structural context',
    labelFa: 'بافت ساختاری راداری',
  },
  3: {
    code: 3,
    name: 'CONCORDANT_STRESS',
    label: 'Concordant stress',
    labelFa: 'تنش همخوان',
  },
  4: {
    code: 4,
    name: 'MIXED_OR_CONTRADICTORY',
    label: 'Mixed evidence',
    labelFa: 'شواهد مختلط',
  },
  5: {
    code: 5,
    name: 'NO_STRESS_EVIDENCE',
    label: 'No stress evidence',
    labelFa: 'بدون شواهد تنش',
  },
};

/** Backend rule ids that surface proxy-derived synthesis statements. */
export const PROXY_RULE_IDS: ReadonlySet<string> = new Set([
  'canopy_proxy_concordant_stress',
  'canopy_proxy_optical_stress_only',
  'canopy_proxy_radar_context_only',
  'canopy_proxy_mixed',
  'canopy_proxy_no_stress',
]);

/**
 * True only for state-based proxy evidence: the backend contract
 * marks it `is_proxy` with unit `state`. Ordinary proxy-flavoured
 * scalar metrics (other units) keep their numeric KPI rendering.
 */
export function isStateProxyItem(
  item: { is_proxy?: unknown; unit?: unknown } | null | undefined,
): boolean {
  if (!item || typeof item !== 'object') return false;
  return item.is_proxy === true && item.unit === 'state';
}

/**
 * Resolve a backend state code to its legend entry. Only exact
 * integer codes 1–5 resolve — anything else (null, strings,
 * out-of-range numbers) yields null so the caller renders the
 * explicit unavailable marker instead of a fabricated label.
 */
export function proxyStateFor(value: unknown): ProxyStateMeta | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return PROXY_STATE_META[value] ?? null;
}

/** True only for the five backend proxy synthesis rule ids (exact match). */
export function isProxyRuleId(ruleId: unknown): boolean {
  return typeof ruleId === 'string' && PROXY_RULE_IDS.has(ruleId);
}
