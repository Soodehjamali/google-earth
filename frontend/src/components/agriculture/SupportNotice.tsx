import type { EvidenceItemResponse, ProvenanceResponse } from '../../types';
import { evidenceWindowText } from './evidence';
import { isFiniteNumber } from './parse';
import { supportInfoOf } from './support';
import { classifyUnavailable } from './unavailable';
import { formatPersianRangeString } from './persianDate';
import CoarseContextBadge from './CoarseContextBadge';

/**
 * Compact "what does this number describe" badge. Always visible on the
 * card; renders nothing when the backend disclosed no Point support (a
 * Polygon request), so absence is never turned into a claim.
 */
export function SupportBadge({
  provenance,
}: {
  provenance: ProvenanceResponse | null | undefined;
}) {
  const info = supportInfoOf(provenance);
  if (!info) return null;
  return (
    <span
      className={`support-badge support-${info.kind}`}
      title={info.explanationEn}
      data-support-kind={info.kind}
    >
      {info.kind === 'window' ? '◎' : '📍'} {info.badgeFa} — {info.badgeEn}
    </span>
  );
}

/**
 * Visible support + time context for a numeric evidence item: what the
 * value describes, over which area, from which dataset and native grid,
 * and for which period. Never inside a collapsed drawer.
 */
export function SupportStrip({ item }: { item: EvidenceItemResponse }) {
  const info = supportInfoOf(item.provenance);
  const windowText = evidenceWindowText(item);
  const scenes = item.provenance?.image_count;
  const temporalKind = item.provenance?.temporal_kind;
  const isCoarse = Boolean(
    item.quality_state === 'coarse_context' ||
      item.is_coarse_context ||
      item.provenance?.quality_state === 'coarse_context'
  );
  if (!info && !windowText && !isCoarse) return null;
  return (
    <div className="support-strip" data-testid="support-strip">
      <div className="support-strip-badge">
        <CoarseContextBadge item={item} provenance={item.provenance} />
        {info && <SupportBadge provenance={item.provenance} />}
      </div>
      {info && (
        <>
          <div className="support-strip-text">{info.explanationEn}</div>
          <div className="support-strip-text" dir="rtl">
            {info.explanationFa}
          </div>
        </>
      )}
      <div className="support-strip-meta" dir="ltr">
        {windowText && (
          <span title={windowText} data-iso-window={windowText}>
            🗓 {formatPersianRangeString(windowText)}
          </span>
        )}
        {isFiniteNumber(scenes) && scenes > 0 && <span>· {scenes} scene/period(s)</span>}
        {typeof temporalKind === 'string' && temporalKind && (
          <span>· {temporalKind}</span>
        )}
        {info && info.nativeResolutionM !== null && (
          <span>· native {info.nativeResolutionM >= 1000 ? `${info.nativeResolutionM / 1000} km` : `${info.nativeResolutionM} m`}</span>
        )}
      </div>
    </div>
  );
}

/**
 * Why a metric has no value: a category a user can act on plus the
 * backend's own message, verbatim. Never shows a number.
 */
export function UnavailableReason({
  item,
  compact = false,
}: {
  item: Pick<EvidenceItemResponse, 'unavailable_reason' | 'unavailable_message'>;
  compact?: boolean;
}) {
  const info = classifyUnavailable(item.unavailable_reason, item.unavailable_message);
  return (
    <div className="unavailable-reason" data-category={info.category}>
      <span className="badge badge-danger unavailable-category">
        {info.labelFa} — {info.labelEn}
      </span>
      {!compact && <div className="unavailable-gloss">{info.glossEn}</div>}
      {info.message ? (
        <div className="unavailable-message">{info.message}</div>
      ) : (
        <div className="unavailable-message text-muted">
          The backend did not return a reason for this metric.
        </div>
      )}
      {info.reason && !compact && (
        <code className="unavailable-code">{info.reason}</code>
      )}
    </div>
  );
}
