import type { AgriculturalAnalysisResponse } from '../../types';
import {
  asArray,
  countEvidenceItems,
  countUnavailableMetrics,
  patternMetaFor,
  sufficiencyBadgeClass,
} from './parse';
import { formatPersianDateRange } from './persianDate.ts';

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
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {result.vegetation_regime && (
            <span
              className={`badge ${
                result.vegetation_regime === 'vegetated'
                  ? 'badge-success'
                  : result.vegetation_regime === 'non_vegetated'
                  ? 'badge-secondary'
                  : 'badge-warning'
              }`}
              title={result.vegetation_regime_explanation ?? undefined}
            >
              {result.vegetation_regime === 'non_vegetated'
                ? 'خاک لخت / بدون پوشش (Non-vegetated)'
                : result.vegetation_regime === 'vegetated'
                ? 'دارای پوشش گیاهی (Vegetated)'
                : 'رژیم نامشخص (Uncertain regime)'}
            </span>
          )}
          <span className={`badge ${sufficiencyBadgeClass(overall)}`}>
            {meta.labelFa} / {meta.label}
          </span>
        </div>
      </div>
      <div className="card-body">
        <div className="form-row" style={{ flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <span className="text-muted">نام باغ / موقعیت: </span>
            <strong data-testid="synthesis-header-location-name">
              {result.location_name?.trim() || 'لوکیشن بدون نام'}
            </strong>
          </div>
          {result.time_start && (
            <div>
              <span className="text-muted">دوره زمانی: </span>
              <strong data-testid="synthesis-header-period">
                {formatPersianDateRange(result.time_start, result.time_end)}
              </strong>
            </div>
          )}
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

        {result.vegetation_regime_explanation && (
          <div
            className="regime-explanation-banner mt-2 text-muted"
            style={{
              fontSize: '0.85rem',
              padding: '8px 12px',
              backgroundColor: 'rgba(0, 0, 0, 0.03)',
              borderRadius: '4px',
              borderRight: '3px solid #6c757d',
            }}
          >
            <strong>وضعیت پوشش زمین (Vegetation Regime): </strong>
            <span>{result.vegetation_regime_explanation}</span>
          </div>
        )}
      </div>
    </div>
  );
}
