import type { AgriculturalAnalysisResponse } from '../../types';
import {
  asArray,
  countEvidenceItems,
  countUnavailableMetrics,
  patternMetaFor,
  sufficiencyBadgeClass,
} from './parse';

interface SynthesisHeaderProps {
  result: AgriculturalAnalysisResponse;
}

/**
 * Shared summary header for a Comprehensive result (F1).
 * Reports only what the response contains — no invented health score.
 */
export default function SynthesisHeader({ result }: SynthesisHeaderProps) {
  const overall = result.overall_sufficiency;
  const meta = patternMetaFor(overall);
  const evidenceCount = countEvidenceItems(result);
  // Canonical de-duplicated count (F-CONTRACT-FIX-1): each unavailable
  // metric counts exactly once; the per-bundle + per-summary lists are
  // the same keys and double every entry.
  const unavailableCount = countUnavailableMetrics(result);
  const crossDomainCount = asArray(result.cross_domain_statements).length;
  const limitationCount = asArray(result.limitations).length;

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">📋 خلاصه تحلیل — Analysis Summary</span>
        <span className={`badge ${sufficiencyBadgeClass(overall)}`}>
          {meta.labelFa} / {meta.label}
        </span>
      </div>
      <div className="card-body">
        <div className="form-row" style={{ flexWrap: 'wrap', gap: '16px' }}>
          {result.time_start && (
            <div>
              <span className="text-muted">دوره زمانی: </span>
              <strong>
                {result.time_start} → {result.time_end ?? '—'}
              </strong>
            </div>
          )}
          {/* spatial_context intentionally not shown: the backend formats it
              as a request echo ("Analysis {request_id}"), not a geographic
              location, so no location label may claim it. */}
          <div>
            <span className="text-muted">حوزه‌های فعال: </span>
            <strong>{asArray(result.available_domains).length}</strong>
          </div>
          <div>
            <span className="text-muted">شواهد: </span>
            <strong>{evidenceCount}</strong>
          </div>
          {(unavailableCount > 0 || limitationCount > 0) && (
            <div>
              <span className="text-muted">ناموجود/محدودیت: </span>
              <strong>
                {unavailableCount} / {limitationCount}
              </strong>
            </div>
          )}
          {crossDomainCount > 0 && (
            <div>
              <span className="text-muted">تحلیل بین‌حوزه‌ای: </span>
              <strong>{crossDomainCount}</strong>
            </div>
          )}
        </div>

        {/* Full limitation strings render once via LimitationsBanner on the
            hub — duplicating the list here double-presents the same data. */}
      </div>
    </div>
  );
}
