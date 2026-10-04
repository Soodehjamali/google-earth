import type {
  DuplicateRecord,
  RejectedRecord,
  ValidationResult,
  ValidationSection as ValidationSectionPayload,
} from '../../types/index.ts';
import { asArray, formatEvidenceValue } from './parse.ts';
import {
  duplicateReferences,
  optionalText,
  rejectedReferences,
  triStateLabel,
  validationLimitations,
  validationProvenanceEntries,
  validationResults,
  validationStatusLabel,
} from './validation.ts';

interface ValidationSectionProps {
  validation: ValidationSectionPayload | null | undefined;
}

/**
 * Ground-truth validation section (P6.4).
 * Renders the P6.3 validation section exactly as received, in
 * backend order. Reference validation only: a side-by-side record
 * of supplied observations against analysis outputs, never an
 * automatic diagnosis. Nothing is computed here.
 */
export default function ValidationSection({
  validation,
}: ValidationSectionProps): React.ReactElement | null {
  if (!validation || typeof validation !== 'object') return null;

  const results = validationResults(validation);
  const rejected = rejectedReferences(validation);
  const duplicates = duplicateReferences(validation);
  const limitations = validationLimitations(validation);

  return (
    <section aria-label="Ground truth validation" className="card mb-3 validation-section">
      <div className="card-header">
        <span className="card-title">🧬 اعتبارسنجی مرجع — Ground Truth Validation</span>
      </div>
      <div className="card-body" style={{ padding: 0 }}>
        <div className="validation-summary">
          <span className="text-muted" style={{ fontSize: '0.8rem' }}>
            {results.length} {results.length === 1 ? 'result' : 'results'} ·{' '}
            {rejected.length} rejected · {duplicates.length}{' '}
            {duplicates.length === 1 ? 'duplicate' : 'duplicates'}
          </span>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>
            Reference validation — comparison against independently supplied
            observations, not an automatic diagnosis.
          </div>
        </div>

        {results.length === 0 ? (
          <div className="empty-state" style={{ padding: '24px' }}>
            <div className="empty-state-desc">
              No validation results in this response.
            </div>
          </div>
        ) : (
          <ul className="validation-result-list">
            {results.map((result) => (
              <li key={result.validation_id}>
                <ValidationResultCard result={result} />
              </li>
            ))}
          </ul>
        )}

        {rejected.length > 0 && <RejectedBlock rejected={rejected} />}
        {duplicates.length > 0 && <DuplicatesBlock duplicates={duplicates} />}

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
    </section>
  );
}

function ValidationResultCard({ result }: { result: ValidationResult }) {
  const provenanceEntries = validationProvenanceEntries(result.provenance);
  const resultLimitations = asArray(result.limitations).filter(
    (entry): entry is string => typeof entry === 'string',
  );

  return (
    <article
      aria-label={`Validation result ${result.validation_id}`}
      className="validation-result-card"
    >
      <div className="validation-result-header">
        <span className="badge badge-info">{validationStatusLabel(result.status)}</span>
        <code>{result.status}</code>
        <code>{result.validation_id}</code>
      </div>

      <div className="validation-detail-body">
        <div className="evidence-detail-row">
          <span className="text-muted">Metric:</span>{' '}
          <code>{optionalText(result.metric_key)}</code>{' '}
          <span className="text-muted">· Domain:</span>{' '}
          <span>{optionalText(result.domain)}</span>
        </div>

        <div className="evidence-detail-row">
          <span className="text-muted">Analysis:</span>{' '}
          <span>
            {formatEvidenceValue(result.analysis_value)}{' '}
            {optionalText(result.analysis_unit)}
            {' · '}
            {optionalText(result.analysis_state)}
          </span>
        </div>
        {(result.analysis_window_start || result.analysis_window_end) && (
          <div className="evidence-detail-row">
            <span className="text-muted">Analysis window:</span>{' '}
            <span>
              {optionalText(result.analysis_window_start)} →{' '}
              {optionalText(result.analysis_window_end)}
            </span>
          </div>
        )}
        {result.analysis_cell_id && (
          <div className="evidence-detail-row">
            <span className="text-muted">Analysis cell:</span>{' '}
            <code>{result.analysis_cell_id}</code>
          </div>
        )}

        <div className="evidence-detail-row">
          <span className="text-muted">Reference:</span>{' '}
          <span>
            <code>{optionalText(result.reference_variable)}</code>{' '}
            {formatEvidenceValue(result.reference_value)}{' '}
            {optionalText(result.reference_unit)}
            {' · '}
            {optionalText(result.reference_state)}
          </span>
        </div>
        <div className="evidence-detail-row">
          <span className="text-muted">Source:</span>{' '}
          <span>{optionalText(result.reference_source)}</span>{' '}
          <span className="text-muted">· Method:</span>{' '}
          <span>{optionalText(result.reference_method)}</span>{' '}
          <span className="text-muted">· Time:</span>{' '}
          <span>{optionalText(result.reference_time)}</span>
        </div>
        {result.observation_id && (
          <div className="evidence-detail-row">
            <span className="text-muted">Observation:</span>{' '}
            <code>{result.observation_id}</code>
          </div>
        )}

        <div className="evidence-detail-row">
          <span className="text-muted">Temporal:</span>{' '}
          <span>{optionalText(result.temporal_relationship)}</span>{' '}
          <span className="text-muted">· Spatial:</span>{' '}
          <span>{optionalText(result.spatial_relationship)}</span>{' '}
          <span className="text-muted">· Metric:</span>{' '}
          <span>{optionalText(result.metric_relationship)}</span>
        </div>

        <div className="evidence-detail-row">
          <span className="text-muted">States agree:</span>{' '}
          <span>{triStateLabel(result.states_agree)}</span>{' '}
          <span className="text-muted">· Values comparable:</span>{' '}
          <span>{triStateLabel(result.values_comparable)}</span>
        </div>

        {result.linkage_reason && (
          <div className="evidence-detail-row">
            <span className="text-muted">Linkage:</span>{' '}
            <span>{result.linkage_reason}</span>
          </div>
        )}

        {provenanceEntries.length > 0 && (
          <details className="evidence-relationships">
            <summary>Provenance ({provenanceEntries.length})</summary>
            <div className="provenance-grid">
              {provenanceEntries.map((entry) => (
                <div key={entry.key} className="provenance-item">
                  <span className="text-muted">{entry.key}:</span>{' '}
                  <span>{entry.value}</span>
                </div>
              ))}
            </div>
          </details>
        )}

        {resultLimitations.length > 0 && (
          <div className="validation-result-limitations">
            <ul>
              {resultLimitations.map((lim, i) => (
                <li key={i} className="text-muted">
                  {lim}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </article>
  );
}

function RejectedBlock({ rejected }: { rejected: RejectedRecord[] }) {
  return (
    <details className="evidence-compact-ref">
      <summary>Rejected references ({rejected.length})</summary>
      <ul>
        {rejected.map((entry, i) => {
          const reasons = asArray(entry.reasons).filter(
            (reason): reason is string => typeof reason === 'string',
          );
          return (
            <li key={i}>
              <span className="text-muted">Index {entry.index}:</span>{' '}
              <code>{optionalText(entry.observation_id)}</code>
              {reasons.length > 0 && (
                <span className="text-muted"> · {reasons.join(', ')}</span>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function DuplicatesBlock({ duplicates }: { duplicates: DuplicateRecord[] }) {
  return (
    <details className="evidence-compact-ref">
      <summary>Duplicate references ({duplicates.length})</summary>
      <ul>
        {duplicates.map((entry, i) => {
          const dropped = asArray(entry.dropped_indices).filter(
            (index): index is number => typeof index === 'number',
          );
          return (
            <li key={i}>
              <code>{optionalText(entry.observation_id)}</code>{' '}
              <span className="text-muted">
                · kept index {entry.kept_index}
                {dropped.length > 0 && ` · dropped ${dropped.join(', ')}`}
              </span>
              {entry.reason && (
                <div className="text-muted">{entry.reason}</div>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
