import type {
  EvidenceBundleResponse,
  SynthesisStatementResponse,
} from '../../types';
import { asArray, domainMetaFor, formatEvidenceValue, patternMetaFor } from './parse';
import { PROXY_METRIC_KEY, isProxyRuleId, proxyStateFor } from './proxyState';
import EvidenceDetailCard from './EvidenceDetailCard';

interface StatementProps {
  statement: SynthesisStatementResponse;
  index: number;
  expanded: boolean;
  expandedEvidence: Set<string>;
  toggleStatement: (key: string) => void;
  toggleEvidence: (key: string) => void;
  bundles: Record<string, EvidenceBundleResponse>;
}

/**
 * Canonical expansion key for one rendered statement (F-FIX-1).
 * The card sends this key to `toggleStatement` and both consumers
 * (hub cross-domain list, domain summary blocks) read it back with
 * the same function, so producer and consumer can never disagree.
 */
export function statementKeyFor(
  statement: SynthesisStatementResponse,
  index: number,
): string {
  return `${statement.domain}-${statement.rule_id}-${index}`;
}

/**
 * Shared synthesis statement renderer (F1), extracted from the hub.
 * Unknown patterns/domains fall back generically (Phase 0B §9).
 */
export default function SynthesisStatementCard({
  statement,
  index,
  expanded,
  expandedEvidence,
  toggleStatement,
  toggleEvidence,
  bundles,
}: StatementProps) {
  const patternMeta = patternMetaFor(statement.pattern);
  const domainMeta = domainMetaFor(statement.domain);
  const statementKey = statementKeyFor(statement, index);
  const evidenceKeys = asArray(statement.evidence_keys).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  const evidenceEntries = Object.entries(statement.evidence_values ?? {});
  const limitations = asArray(statement.limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  const sufficiency =
    typeof statement.sufficiency === 'string' && statement.sufficiency.length > 0
      ? statement.sufficiency
      : null;
  const conflicts = dedupedConflicts(statement.conflicts);

  return (
    <div className="synthesis-statement">
      <button
        className="synthesis-header"
        onClick={() => toggleStatement(statementKey)}
      >
        <span className="synthesis-header-left">
          <span
            className="synthesis-pattern-dot"
            style={{ backgroundColor: patternMeta.color }}
          />
          <span className="synthesis-rule">{statement.rule_id}</span>
          <span className="synthesis-domain-badge">
            {domainMeta.icon} {domainMeta.labelFa}
          </span>
          {isProxyRuleId(statement.rule_id) && (
            <span className="badge badge-warning">proxy</span>
          )}
          {sufficiency && (
            <span className="badge badge-info" title="کفایت — sufficiency">
              {sufficiency}
            </span>
          )}
        </span>
        <span className="expand-icon">{expanded ? '▼' : '▶'}</span>
      </button>

      <div className="synthesis-statement-text">{statement.statement}</div>

      {expanded && (
        <div className="synthesis-details">
          {evidenceKeys.length > 0 && (
            <div className="synthesis-evidence-keys">
              <strong>کلیدهای شواهد:</strong>{' '}
              {evidenceKeys.map((key, i) => (
                <span key={key}>
                  <code
                    className="evidence-key-link"
                    onClick={() => toggleEvidence(`${statementKey}-${key}`)}
                  >
                    {key}
                  </code>
                  {i < evidenceKeys.length - 1 ? ', ' : ''}
                </span>
              ))}
            </div>
          )}

          {evidenceEntries.length > 0 && (
            <div className="synthesis-evidence-values">
              <strong>مقدار شواهد:</strong>
              <div className="evidence-values-grid">
                {evidenceEntries.map(([key, val]) => (
                  <div key={key} className="evidence-value-item">
                    <code>{key}</code>
                    <span>{formatProxyEvidenceValue(key, val)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {statement.scientific_basis && (
            <div className="synthesis-scientific">
              <strong>پایه علمی:</strong>
              <p>{statement.scientific_basis}</p>
            </div>
          )}

          {conflicts.length > 0 && (
            <div className="synthesis-conflicts">
              <strong>تعارض‌ها:</strong>
              <ul>
                {conflicts.map(({ text, count }) => (
                  <li key={text}>
                    <span>{text}</span>
                    {count > 1 && (
                      <span className="text-muted"> ×{count}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {limitationsVisible(limitations) && (
            <div className="synthesis-limitations">
              <strong>محدودیت‌ها:</strong>
              <ul>
                {limitations.map((lim, i) => (
                  <li key={i}>{lim}</li>
                ))}
              </ul>
            </div>
          )}

          {evidenceKeys.map((key) => {
            const evKey = `${statementKey}-${key}`;
            if (!expandedEvidence.has(evKey)) return null;

            let bundleName = '';
            let foundKey: string | null = null;
            for (const [bName, bundle] of Object.entries(bundles ?? {})) {
              const items = Array.isArray(bundle?.items) ? bundle.items : [];
              if (items.some((entry) => entry?.metric_key === key)) {
                bundleName = bName;
                foundKey = key;
                break;
              }
            }

            if (!foundKey) {
              return (
                <div key={key} className="evidence-detail-card">
                  <div className="evidence-detail-header">
                    <code>{key}</code>
                    <span className="badge badge-warning">یافت نشد</span>
                  </div>
                </div>
              );
            }

            const item = Object.values(bundles ?? {})
              .flatMap((bundle) =>
                Array.isArray(bundle?.items) ? bundle.items : [],
              )
              .find((entry) => entry?.metric_key === key);
            if (!item) return null;
            return (
              <EvidenceDetailCard key={key} item={item} bundleName={bundleName} />
            );
          })}
        </div>
      )}
    </div>
  );
}

function limitationsVisible(limitations: string[]): boolean {
  return limitations.length > 0;
}

/**
 * Backend statement conflicts are pairwise check notes that repeat
 * verbatim (one entry per evidence pair). Collapse exact duplicates
 * with a repeat count so the card stays compact. Verbatim text is
 * preserved; only repetition is folded. Empty input renders nothing.
 */
function dedupedConflicts(
  conflicts: unknown,
): Array<{ text: string; count: number }> {
  const texts = asArray(conflicts).filter(
    (entry): entry is string => typeof entry === 'string' && entry.length > 0,
  );
  const counts = new Map<string, number>();
  for (const text of texts) {
    counts.set(text, (counts.get(text) ?? 0) + 1);
  }
  return [...counts.entries()].map(([text, count]) => ({ text, count }));
}

/**
 * Proxy state codes are identifiers, not magnitudes: render the
 * backend legend label instead of a formatted number so the grid
 * never reads as a dryness score. All other keys keep the generic
 * numeric formatting.
 */
function formatProxyEvidenceValue(key: string, value: unknown): string {
  if (key === PROXY_METRIC_KEY) {
    const state = proxyStateFor(value);
    if (state) return `${state.label} (state ${state.code})`;
    return formatEvidenceValue(value);
  }
  return formatEvidenceValue(value);
}
