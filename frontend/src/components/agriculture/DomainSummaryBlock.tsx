import { useState } from 'react';
import { Link } from 'react-router-dom';
import type {
  DomainSummaryResponse,
  EvidenceBundleResponse,
} from '../../types';
import {
  asArray,
  asEvidenceItem,
  asRecord,
  asSynthesisStatement,
  domainMetaFor,
  sufficiencyBadgeClass,
} from './parse';
import SynthesisStatementCard from './SynthesisStatementCard';
import { statementKeyFor } from './SynthesisStatementCard';
import EvidenceDetailCard from './EvidenceDetailCard';
import { routePathForDomain } from './domainPages';
import { UnavailableReason } from './SupportNotice';

interface DomainSummaryBlockProps {
  domainKey: string;
  summary: DomainSummaryResponse | null | undefined;
  bundles: Record<string, EvidenceBundleResponse>;
  defaultExpanded?: boolean;
}

/**
 * Reusable per-domain renderer for all future domain pages (F1).
 * Domain-agnostic: no vegetation-specific assumptions.
 * Scalar usable evidence renders as KPI cards; unavailable stays textual.
 */
export default function DomainSummaryBlock({
  domainKey,
  summary,
  bundles,
  defaultExpanded = false,
}: DomainSummaryBlockProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [expandedStatements, setExpandedStatements] = useState<Set<string>>(new Set());
  const [expandedEvidence, setExpandedEvidence] = useState<Set<string>>(new Set());
  const meta = domainMetaFor(domainKey);

  if (!summary) return null;

  const statements = asArray(summary.statements);
  const hasUsableEvidence = summary.has_usable_evidence === true;
  const unavailable = asArray(summary.unavailable_evidence).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  const limitations = asArray(summary.limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  const bundle = bundles?.[domainKey];
  const bundleItems = bundle && Array.isArray(bundle.items) ? bundle.items : [];
  const bundleConflicts = bundle && Array.isArray(bundle.conflicts) ? bundle.conflicts : [];
  const summaryConflicts = asArray(summary.conflicts).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  const significantConflicts = bundleConflicts.filter(
    (entry) =>
      entry &&
      typeof entry === 'object' &&
      ((entry as { status?: string }).status === 'conflicting' ||
        (entry as { status?: string }).status === 'partially_consistent'),
  );
  const scalarItems = bundleItems
    .map(asEvidenceItem)
    .filter(
      (entry): entry is NonNullable<ReturnType<typeof asEvidenceItem>> =>
        entry !== null,
    );

  function toggleStatement(key: string) {
    setExpandedStatements((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleEvidence(key: string) {
    setExpandedEvidence((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="domain-section">
      <button className="domain-header" onClick={() => setExpanded((prev) => !prev)}>
        <span className="domain-header-left">
          <span className="domain-icon">{meta.icon}</span>
          <span className="domain-title">
            {meta.labelFa} — {meta.label}
          </span>
        </span>
        <span className="domain-header-right">
          {/* F-CONTRACT-FRONTEND-CONTRACT-1 §5: factual data-vs-statement
              indicator. A domain with usable evidence but no statement must
              never read as a data-less domain; a domain without either is
              labelled exactly that. Backend fields only — no inference. */}
          {hasUsableEvidence && statements.length === 0 && (
            <span className="badge badge-info" title="شواهد قابل استفاده موجود است؛ هیچ قانون سنتز فعال نشده است — usable evidence present; no synthesis rule fired">
              شواهد موجود — Evidence available, no synthesis statement
            </span>
          )}
          {!hasUsableEvidence && statements.length === 0 && (
            <span className="badge badge-danger" title="هیچ شواهد قابل استفاده‌ای در پاسخ نیست — no usable evidence in the response">
              بدون شواهد قابل استفاده — No usable evidence
            </span>
          )}
          <span className={`badge ${sufficiencyBadgeClass(summary.sufficiency)}`}>
            {summary.statement_count} {summary.statement_count === 1 ? 'statement' : 'statements'}
          </span>
          <span className="expand-icon">{expanded ? '▼' : '▶'}</span>
        </span>
      </button>

      {expanded && (
        <div className="domain-content">
          {routePathForDomain(domainKey) && (
            <div style={{ padding: '8px 16px 0' }}>
              <Link
                to={routePathForDomain(domainKey) as string}
                className="btn btn-sm btn-secondary"
              >
                View details →
              </Link>
            </div>
          )}
          {statements.length === 0 && scalarItems.length === 0 && unavailable.length === 0 && (
            <div className="empty-state" style={{ padding: '24px' }}>
              <div className="empty-state-desc">هیچ داده یا تحلیلی برای این حوزه یافت نشد</div>
            </div>
          )}

          {statements.map((stmt, i) => {
            const statement = asSynthesisStatement(stmt);
            if (!statement) return null;
            return (
              <SynthesisStatementCard
                key={`${domainKey}-${i}`}
                statement={statement}
                index={i}
                expanded={expandedStatements.has(statementKeyFor(statement, i))}
                expandedEvidence={expandedEvidence}
                toggleStatement={toggleStatement}
                toggleEvidence={toggleEvidence}
                bundles={bundles}
              />
            );
          })}

          {scalarItems.length > 0 && (
            <div className="domain-evidence">
              <h4 className="unavailable-title">شواهد — Evidence</h4>
              {scalarItems.map((item) => (
                <EvidenceDetailCard
                  key={item.metric_key}
                  item={item}
                  bundleName={domainKey}
                />
              ))}
            </div>
          )}

          {unavailable.length > 0 && (
            <div className="unavailable-section">
              <h4 className="unavailable-title">داده‌های در دسترس نیست — Unavailable Evidence</h4>
              {unavailable.map((key) => {
                const source = scalarItems.find((entry) => entry.metric_key === key);
                return (
                  <div key={key} className="unavailable-item">
                    <code>{key}</code>
                    {source ? (
                      <UnavailableReason item={source} compact />
                    ) : (
                      <span className="badge badge-danger" style={{ fontSize: '11px' }}>
                        unavailable
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {(significantConflicts.length > 0 || summaryConflicts.length > 0) && (
            <div className="domain-conflicts mt-2">
              <h4 className="unavailable-title">
                تناقضات و عدم تطابق مدل‌ها — Model Conflicts & Discrepancies ({significantConflicts.length + summaryConflicts.length})
              </h4>
              <ul className="conflicts-list" style={{ paddingLeft: '16px', margin: '4px 0' }}>
                {significantConflicts.map((c, i) => {
                  const record = asRecord(c);
                  if (!record) return null;
                  const a = typeof record.metric_a === 'string' ? record.metric_a : '—';
                  const b = typeof record.metric_b === 'string' ? record.metric_b : '—';
                  const status = typeof record.status === 'string' ? record.status : '—';
                  const explanation = typeof record.explanation === 'string' ? record.explanation : '';
                  return (
                    <li key={`sc-${i}`} style={{ marginBottom: '6px' }}>
                      <code>{a}</code> ↔ <code>{b}</code>{' '}
                      <span
                        className={`badge ${status === 'conflicting' ? 'badge-danger' : 'badge-warning'}`}
                        style={{ fontSize: '11px' }}
                      >
                        {status}
                      </span>
                      {explanation && (
                        <div className="text-muted" style={{ fontSize: '0.85rem', marginTop: '2px' }}>
                          {explanation}
                        </div>
                      )}
                    </li>
                  );
                })}
                {summaryConflicts.map((text, i) => (
                  <li key={`sumc-${i}`} style={{ marginBottom: '6px' }}>
                    <span className="badge badge-danger" style={{ fontSize: '11px' }}>conflict</span>
                    <span style={{ fontSize: '0.85rem', marginLeft: '6px' }}>{text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {limitations.length > 0 && (
            <div className="domain-limitations">
              {limitations.map((lim, i) => (
                <div key={i} className="info-banner" style={{ marginTop: '8px' }}>
                  <span>ℹ️</span>
                  <span>{lim}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
