import type {
  ConcordanceSeries,
  DomainSummaryResponse,
  EvidenceBundleResponse,
  JointAnalysis,
  RadarAnomalyAnalysis,
  SpatialSectionPayload,
  SynthesisStatementResponse,
  TemporalSectionPayload,
} from '../../types/index.ts';
import { asArray, asRecord, domainMetaFor, formatEvidenceValue } from './parse.ts';
import EvidenceDetailCard from './EvidenceDetailCard.tsx';
import { thermalRelationshipLabel } from './thermal.ts';
import {
  bundleItems,
  bundleLimitations,
  bundleSourceDatasets,
  bundleSufficiencyLevel,
  bundleUnavailableKeys,
  concordanceMonthsOf,
  concordanceSeriesOf,
  concordanceSummaryOf,
  evidenceWindowText,
  jointAnalysisOf,
  orderedBundleEntries,
  patternsInResponse,
  radarAnalysesOf,
  spatialReferenceFor,
  synthesisLinksFor,
  temporalReferenceFor,
  thermalConcordanceMonthsOf,
  validationsInResponse,
} from './evidence.ts';

interface EvidenceSectionProps {
  bundles: Record<string, EvidenceBundleResponse> | null | undefined;
  domainSummaries?: Record<string, DomainSummaryResponse> | null;
  crossDomainStatements?: SynthesisStatementResponse[] | null;
  temporal?: TemporalSectionPayload | null;
  spatial?: SpatialSectionPayload | null;
  rawResponse?: unknown;
}

/**
 * Evidence traceability section (P5.5).
 * Renders backend evidence bundles exactly as received, grouped by
 * backend domain identity in response order. Each metric links to
 * its observation window, backend monthly presence, backend spatial
 * presence, and backend synthesis references by exact key. Absent
 * sections render honest empty text. Nothing is derived here.
 */
export default function EvidenceSection({
  bundles,
  domainSummaries = null,
  crossDomainStatements = null,
  temporal = null,
  spatial = null,
  rawResponse = null,
}: EvidenceSectionProps): React.ReactElement {
  const entries = orderedBundleEntries(bundles);
  const patterns = patternsInResponse(rawResponse);
  const validations = validationsInResponse(rawResponse);
  const concordanceMonths = concordanceMonthsOf(temporal);
  const concordanceSummary = concordanceSummaryOf(temporal);
  const concordanceSeries = concordanceSeriesOf(temporal);
  const joint = jointAnalysisOf(temporal);
  const radarAnalyses = radarAnalysesOf(temporal);
  const thermalMonths = thermalConcordanceMonthsOf(temporal);

  if (entries.length === 0) {
    return (
      <section aria-label="Evidence" className="card mb-3 evidence-section">
        <div className="card-header">
          <span className="card-title">🧾 شواهد — Evidence</span>
        </div>
        <div className="card-body">
          <div className="empty-state">
            <div className="empty-state-title">No evidence is available for this analysis.</div>
            <div className="empty-state-desc">
              The response carried no evidence bundles for the requested domains.
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section aria-label="Evidence" className="card mb-3 evidence-section">
      <div className="card-header">
        <span className="card-title">🧾 شواهد — Evidence</span>
      </div>
      <div className="card-body" style={{ padding: 0 }}>
        {entries.map(({ domain, bundle }) => (
          <BundleBlock
            key={domain}
            domain={domain}
            bundle={bundle}
            domainSummaries={domainSummaries}
            crossDomainStatements={crossDomainStatements}
            temporal={temporal}
            spatial={spatial}
          />
        ))}

        {concordanceMonths.length > 0 && (
          <ConcordanceReference
            months={concordanceMonths}
            summary={concordanceSummary}
            series={concordanceSeries}
          />
        )}
        {joint !== null && <JointReference joint={joint} />}
        {radarAnalyses.length > 0 && (
          <RadarMetadataBlock analyses={radarAnalyses} />
        )}
        {thermalMonths.length > 0 && (
          <ThermalReference months={thermalMonths} />
        )}
        {spatial && <SpatialReferenceBlock spatial={spatial} domains={entries.map((e) => e.domain)} />}

        {patterns.length > 0 && <PatternReference patterns={patterns} />}
        {validations.length > 0 && <ValidationReference validations={validations} />}
      </div>
    </section>
  );
}

function BundleBlock({
  domain,
  bundle,
  domainSummaries,
  crossDomainStatements,
  temporal,
  spatial,
}: {
  domain: string;
  bundle: EvidenceBundleResponse;
  domainSummaries: Record<string, DomainSummaryResponse> | null | undefined;
  crossDomainStatements: SynthesisStatementResponse[] | null | undefined;
  temporal: TemporalSectionPayload | null | undefined;
  spatial: SpatialSectionPayload | null | undefined;
}): React.ReactElement {
  const meta = domainMetaFor(domain);
  const items = bundleItems(bundle);
  const sufficiency = bundleSufficiencyLevel(bundle);
  const sources = bundleSourceDatasets(bundle);
  const unavailable = bundleUnavailableKeys(bundle);
  const limitations = bundleLimitations(bundle);
  const conflicts = asArray((bundle as { conflicts?: unknown }).conflicts);
  const availableKeys = asArray((bundle as { available?: unknown }).available).filter(
    (entry): entry is string => typeof entry === 'string',
  );

  return (
    <article aria-label={`Evidence bundle ${domain}`} className="evidence-bundle">
      <div className="evidence-bundle-header">
        <span className="domain-icon">{meta.icon}</span>
        <span className="domain-title">
          {meta.labelFa} — {meta.label} <code>{domain}</code>
        </span>
        {sufficiency && <span className="badge badge-info">{sufficiency}</span>}
        <span className="text-muted" style={{ fontSize: '0.8rem' }}>
          {items.length} items · {availableKeys.length} available · {unavailable.length} unavailable
        </span>
      </div>

      {sources.length > 0 && (
        <div className="evidence-detail-row">
          <span className="text-muted">Sources:</span>{' '}
          <span>{sources.join(', ')}</span>
        </div>
      )}

      {items.length === 0 ? (
        <div className="empty-state" style={{ padding: '24px' }}>
          <div className="empty-state-desc">Insufficient evidence.</div>
          {unavailable.length > 0 && (
            <ul className="evidence-unavailable">
              {unavailable.map((key) => (
                <li key={key}>
                  <span className="badge badge-danger" style={{ fontSize: '11px' }}>
                    unavailable
                  </span>{' '}
                  <code>{key}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <ul className="evidence-item-list">
          {items.map((item) => (
            <li key={item.metric_key}>
              <EvidenceDetailCard item={item} bundleName={domain} />
              <ItemRelationships
                metricKey={item.metric_key}
                domainSummaries={domainSummaries}
                crossDomainStatements={crossDomainStatements}
                temporal={temporal}
                spatial={spatial}
                windowText={evidenceWindowText(item)}
                valueText={formatEvidenceValue(item.value)}
                unit={item.unit}
                status={item.status}
                quality={item.quality}
              />
            </li>
          ))}
        </ul>
      )}

      {conflicts.length > 0 && (
        <details className="evidence-relationships">
          <summary>Conflicts ({conflicts.length})</summary>
          <ul>
            {conflicts.map((entry, i) => {
              const record = asRecord(entry);
              if (!record) return null;
              const a = typeof record.metric_a === 'string' ? record.metric_a : '—';
              const b = typeof record.metric_b === 'string' ? record.metric_b : '—';
              const status = typeof record.status === 'string' ? record.status : '—';
              const explanation =
                typeof record.explanation === 'string' ? record.explanation : '';
              return (
                <li key={i}>
                  <code>{a}</code> ↔ <code>{b}</code> · <span>{status}</span>
                  {explanation && <div className="text-muted">{explanation}</div>}
                </li>
              );
            })}
          </ul>
        </details>
      )}

      {unavailable.length > 0 && items.length > 0 && (
        <div className="unavailable-section">
          <h4 className="unavailable-title">Unavailable — در دسترس نیست</h4>
          <ul className="evidence-unavailable">
            {unavailable.map((key) => (
              <li key={key}>
                <span className="badge badge-danger" style={{ fontSize: '11px' }}>
                  unavailable
                </span>{' '}
                <code>{key}</code>
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
    </article>
  );
}

function ItemRelationships({
  metricKey,
  domainSummaries,
  crossDomainStatements,
  temporal,
  spatial,
  windowText,
  valueText,
  unit,
  status,
  quality,
}: {
  metricKey: string;
  domainSummaries: Record<string, DomainSummaryResponse> | null | undefined;
  crossDomainStatements: SynthesisStatementResponse[] | null | undefined;
  temporal: TemporalSectionPayload | null | undefined;
  spatial: SpatialSectionPayload | null | undefined;
  windowText: string | null;
  valueText: string;
  unit: string;
  status: string;
  quality: string;
}): React.ReactElement {
  const links = synthesisLinksFor(metricKey, domainSummaries, crossDomainStatements);
  const temporalRef = temporalReferenceFor(metricKey, temporal);
  const spatialRef = spatialReferenceFor(metricKey, spatial);
  const hasTemporal =
    temporalRef.hasProfile ||
    temporalRef.hasAnomaly ||
    temporalRef.hasChange ||
    temporalRef.hasRadar ||
    temporalRef.hasThermal;
  const hasSpatial = spatialRef.observationCount > 0 || spatialRef.summaryState !== null;

  return (
    <details className="evidence-relationships">
      <summary>
        Trace — <code>{metricKey}</code>
      </summary>
      <ul>
        <li>
          <span className="text-muted">Observed:</span>{' '}
          <span>
            {valueText} {unit} · <span>{status}</span> · <span>{quality}</span>
          </span>
        </li>
        <li>
          <span className="text-muted">Window:</span>{' '}
          <span>{windowText ?? '—'}</span>
        </li>
        <li>
          <span className="text-muted">Monthly intelligence:</span>{' '}
          {hasTemporal ? (
            <span>
              {[
                temporalRef.hasProfile ? 'profile' : null,
                temporalRef.hasAnomaly ? 'anomaly' : null,
                temporalRef.hasChange ? 'change' : null,
                temporalRef.hasRadar ? 'radar' : null,
                temporalRef.hasThermal ? 'thermal' : null,
              ]
                .filter((entry): entry is string => entry !== null)
                .join(', ')}
              {' — '}
              <span>monthly detail available</span>
            </span>
          ) : (
            <span>—</span>
          )}
        </li>
        <li>
          <span className="text-muted">Spatial evidence:</span>{' '}
          {hasSpatial ? (
            <span>
              {spatialRef.observationCount} observations
              {spatialRef.summaryState ? ` · ${spatialRef.summaryState}` : ''}
            </span>
          ) : (
            <span>—</span>
          )}
        </li>
        <li>
          <span className="text-muted">Synthesis references:</span>{' '}
          {links.length > 0 ? (
            <span>
              {links.map((link) => (
                <span key={`${link.domain}:${link.rule_id}`} style={{ marginRight: 8 }}>
                  <code>{link.rule_id}</code> ({link.domain}
                  {link.pattern ? ` · ${link.pattern}` : ''})
                </span>
              ))}
            </span>
          ) : (
            <span>—</span>
          )}
        </li>
      </ul>
    </details>
  );
}

function ConcordanceReference({
  months,
  summary,
  series,
}: {
  months: ReturnType<typeof concordanceMonthsOf>;
  summary: ReturnType<typeof concordanceSummaryOf>;
  series: ConcordanceSeries | null;
}): React.ReactElement {
  const counts: Array<[string, unknown]> = summary
    ? [
        ['months', summary.n_months],
        ['concordant', summary.n_concordant],
        ['divergent', summary.n_divergent],
        ['mixed', summary.n_mixed],
        ['optical only', summary.n_optical_only],
        ['radar only', summary.n_radar_only],
        ['insufficient', summary.n_insufficient],
      ]
    : [];
  const seriesRule =
    series && typeof series.rule === 'string' && series.rule.length > 0
      ? series.rule
      : null;
  const seriesMethods = series ? asRecord(series.methods) : null;
  const methodEntries = seriesMethods
    ? Object.entries(seriesMethods).filter(
        ([, value]) => typeof value === 'string' && value.length > 0,
      )
    : [];
  const seriesLimitations = series
    ? asArray(series.limitations).filter(
        (entry): entry is string =>
          typeof entry === 'string' && entry.length > 0,
      )
    : [];
  return (
    <details className="evidence-compact-ref">
      <summary>Multi-sensor concordance — {months.length} months</summary>
      {series && typeof series.rule_id === 'string' && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
          <span>Rule — قاعده:</span> <code>{series.rule_id}</code>
        </div>
      )}
      {counts.length > 0 && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
          {counts
            .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
            .map(([label, value]) => `${label} ${value}`)
            .join(' · ')}
        </div>
      )}
      <ul>
        {months.map((month, i) => {
          const record = asRecord(month);
          if (!record) return null;
          const state = typeof record.state === 'string' ? record.state : '—';
          const rule = typeof record.rule_id === 'string' ? record.rule_id : '';
          const reasons = asArray(record.reasons).filter(
            (entry): entry is string =>
              typeof entry === 'string' && entry.length > 0,
          );
          const families = asArray(record.families)
            .map((entry) => asRecord(entry))
            .filter(
              (
                entry,
              ): entry is Record<string, unknown> & {
                family?: unknown;
                sensor?: unknown;
                orientation?: unknown;
                usable_count?: unknown;
                metric_ids?: unknown;
              } => entry !== null,
            );
          return (
            <li key={i}>
              <span className="text-muted">
                {String(record.window_start)} → {String(record.window_end ?? '')}:
              </span>{' '}
              <span>{state}</span>
              {rule && (
                <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                  {' '}
                  · <code>{rule}</code>
                </span>
              )}
              {families.length > 0 && (
                <ul>
                  {families.map((family, j) => {
                    const name =
                      typeof family.family === 'string' ? family.family : '—';
                    const sensor =
                      typeof family.sensor === 'string' ? family.sensor : '—';
                    const orientation =
                      typeof family.orientation === 'string'
                        ? family.orientation
                        : '—';
                    const usable =
                      typeof family.usable_count === 'number'
                        ? family.usable_count
                        : null;
                    const metricIds = asArray(family.metric_ids).filter(
                      (entry): entry is string => typeof entry === 'string',
                    );
                    return (
                      <li key={j}>
                        <code>{name}</code>{' '}
                        <span className="text-muted">
                          · {sensor} · {orientation}
                          {usable !== null && ` · usable ${usable}`}
                          {metricIds.length > 0 && ` · ${metricIds.join(', ')}`}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
              {reasons.length > 0 && (
                <ul>
                  {reasons.map((reason, k) => (
                    <li key={k}>
                      <span className="text-muted">{reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      {seriesRule && (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
          <span>Method rule text:</span> <span>{seriesRule}</span>
        </div>
      )}
      {methodEntries.length > 0 && (
        <ul>
          {methodEntries.map(([key, value]) => (
            <li key={key}>
              <span className="text-muted">{key}:</span>{' '}
              <span>{String(value)}</span>
            </li>
          ))}
        </ul>
      )}
      {seriesLimitations.length > 0 && (
        <ul>
          {seriesLimitations.map((limitation, i) => (
            <li key={`conc-lim-${i}`}>
              <span className="text-muted">{limitation}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function JointReference({
  joint,
}: {
  joint: NonNullable<ReturnType<typeof jointAnalysisOf>>;
}): React.ReactElement {
  const changes = asArray(joint.changes);
  const lags = asArray(joint.lags);
  const scatter = asRecord(joint.scatter);
  return (
    <details className="evidence-compact-ref">
      <summary>
        Joint NDVI-moisture analysis — <code>{joint.ndvi_key}</code> /{' '}
        <code>{joint.moisture_key}</code>
      </summary>
      <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
        {joint.window_start} → {joint.window_end} · step {joint.step || '—'}
      </div>
      {changes.length > 0 && (
        <ul>
          {changes.map((change, i) => {
            const record = asRecord(change);
            if (!record) return null;
            const pattern = typeof record.pattern === 'string' ? record.pattern : '—';
            const divergence =
              typeof record.divergence === 'string' ? record.divergence : '—';
            const ndviDirection =
              typeof record.ndvi_direction === 'string' ? record.ndvi_direction : '—';
            const moistureDirection =
              typeof record.moisture_direction === 'string'
                ? record.moisture_direction
                : '—';
            return (
              <li key={i}>
                <span className="text-muted">
                  {String(record.window_start)} → {String(record.window_end ?? '')}:
                </span>{' '}
                <span>{pattern}</span>
                <span className="text-muted">
                  {' '}
                  · NDVI {ndviDirection} / moisture {moistureDirection} · {divergence}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {lags.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
            Lags — تأخیرها (descriptive co-movement only, never causal):
          </div>
          <div className="table-container">
            <table aria-label="Joint lag results">
              <thead>
                <tr>
                  <th>lag (months)</th>
                  <th>paired</th>
                  <th>agreement</th>
                  <th>sufficient</th>
                  <th>method</th>
                </tr>
              </thead>
            <tbody>
              {lags.map((lag, i) => {
                const record = asRecord(lag);
                if (!record) return null;
                return (
                  <tr key={`lag-${i}`}>
                    <td>{finiteOrDash(record.lag_months)}</td>
                    <td>{finiteOrDash(record.n_paired)}</td>
                    <td>{finiteOrDash(record.agreement)}</td>
                    <td>
                      {typeof record.sufficient === 'boolean'
                        ? String(record.sufficient)
                        : '—'}
                    </td>
                    <td className="text-muted">
                      {typeof record.method === 'string' && record.method.length > 0
                        ? record.method
                        : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </div>
      ) : (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
          No lag results were reported for this analysis.
        </div>
      )}
      {scatter !== null ? (
        <ScatterTable joint={joint} scatter={scatter} />
      ) : (
        <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
          No scatter dataset was reported for this analysis.
        </div>
      )}
    </details>
  );
}

/** Format a backend number for display; nulls and non-numbers stay honest. */
function finiteOrDash(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return formatEvidenceValue(value);
  }
  return '—';
}

/**
 * Paired NDVI-moisture scatter points, verbatim. No trend line, no
 * fitted relationship is drawn: association is the backend's own
 * refused-or-reported business, and the UI must not imply one either.
 */
function ScatterTable({
  joint,
  scatter,
}: {
  joint: JointAnalysis;
  scatter: Record<string, unknown>;
}): React.ReactElement {
  const points = asArray(scatter.points);
  const nPaired =
    typeof scatter.n_paired === 'number' ? scatter.n_paired : null;
  const method =
    typeof scatter.method === 'string' && scatter.method.length > 0
      ? scatter.method
      : '—';
  if (points.length === 0) {
    return (
      <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
        Scatter: paired {nPaired ?? '—'} · method {method} · no paired points
        reported.
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8 }}>
      <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 4 }}>
        Scatter — پراکندگی: <code>{joint.ndvi_key}</code> /{' '}
        <code>{joint.moisture_key}</code> · paired {nPaired ?? '—'} · {method}
      </div>
      <div className="table-container">
        <table aria-label="Joint scatter points">
          <thead>
            <tr>
              <th>window</th>
              <th>{joint.ndvi_key}</th>
              <th>{joint.moisture_key}</th>
              <th>ndvi z</th>
              <th>moisture z</th>
            </tr>
          </thead>
        <tbody>
          {points.map((point, i) => {
            const record = asRecord(point);
            if (!record) return null;
            return (
              <tr key={i}>
                <td className="text-muted">
                  {typeof record.window_start === 'string'
                    ? record.window_start
                    : '—'}
                </td>
                <td>{finiteOrDash(record.ndvi)}</td>
                <td>{finiteOrDash(record.moisture)}</td>
                <td>{finiteOrDash(record.ndvi_z)}</td>
                <td>{finiteOrDash(record.moisture_z)}</td>
              </tr>
            );
          })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Backend radar anomaly metadata, verbatim and secondary to the
 * measured profiles/charts rendered elsewhere. Metrics whose
 * analysis carries no metadata at all produce no card.
 */
function RadarMetadataBlock({
  analyses,
}: {
  analyses: Array<{ metricKey: string; analysis: RadarAnomalyAnalysis }>;
}): React.ReactElement {
  const cards = analyses
    .map(({ metricKey, analysis }) => ({ metricKey, analysis, rows: radarMetaRows(analysis) }))
    .filter((entry) => entry.rows.hasContent);
  if (cards.length === 0) return <></>;
  return (
    <details className="evidence-compact-ref">
      <summary>Radar analysis metadata — {cards.length} metrics</summary>
      {cards.map(({ metricKey, rows }) => (
        <div key={metricKey} style={{ marginTop: 8 }}>
          <div style={{ fontSize: '0.85rem', marginBottom: 4 }}>
            <code>{metricKey}</code>
          </div>
          <ul>
            {rows.items.map(({ label, value }) => (
              <li key={label}>
                <span className="text-muted">{label}:</span>{' '}
                <span>{value}</span>
              </li>
            ))}
          </ul>
          {rows.methods.length > 0 && (
            <ul>
              {rows.methods.map(([key, value]) => (
                <li key={key}>
                  <span className="text-muted">{key}:</span>{' '}
                  <span>{value}</span>
                </li>
              ))}
            </ul>
          )}
          {rows.limitations.length > 0 && (
            <ul>
              {rows.limitations.map((limitation, i) => (
                <li key={`radar-lim-${i}`}>
                  <span className="text-muted">{limitation}</span>
                </li>
              ))}
            </ul>
          )}
          {rows.observation !== null && (
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>
              {rows.observation}
            </div>
          )}
        </div>
      ))}
    </details>
  );
}

/**
 * Collect the displayable radar metadata of one analysis. Returns
 * `hasContent: false` when the backend sent no metadata at all so
 * the caller renders nothing for that metric.
 */
function radarMetaRows(analysis: RadarAnomalyAnalysis): {
  hasContent: boolean;
  items: Array<{ label: string; value: string }>;
  methods: Array<[string, string]>;
  limitations: string[];
  observation: string | null;
} {
  const items: Array<{ label: string; value: string }> = [];
  const polarizations = asArray(analysis.polarizations).filter(
    (entry): entry is string => typeof entry === 'string' && entry.length > 0,
  );
  if (polarizations.length > 0) {
    items.push({ label: 'polarizations', value: polarizations.join(', ') });
  }
  if (typeof analysis.mode === 'string' && analysis.mode.length > 0) {
    items.push({ label: 'mode', value: analysis.mode });
  }
  if (typeof analysis.orbit_pass === 'string' && analysis.orbit_pass.length > 0) {
    items.push({ label: 'orbit pass', value: analysis.orbit_pass });
  }
  if (typeof analysis.scale_m === 'number' && Number.isFinite(analysis.scale_m)) {
    items.push({ label: 'scale', value: `${formatEvidenceValue(analysis.scale_m)} m` });
  }
  const methodsRecord = asRecord(analysis.methods);
  const methods = methodsRecord
    ? Object.entries(methodsRecord).filter(
        (entry): entry is [string, string] =>
          typeof entry[1] === 'string' && (entry[1] as string).length > 0,
      )
    : [];
  const limitations = asArray(analysis.limitations).filter(
    (entry): entry is string => typeof entry === 'string' && entry.length > 0,
  );
  let observation: string | null = null;
  const observed = asRecord(analysis.observed);
  const baseline = asRecord(analysis.baseline);
  if (observed || baseline) {
    const parts: string[] = [];
    if (observed) {
      const derivation =
        typeof observed.derivation === 'string' && observed.derivation.length > 0
          ? observed.derivation
          : 'observed';
      const nPoints = asArray(observed.points).length;
      parts.push(`Observed: ${derivation} · ${nPoints} monthly points`);
    }
    if (baseline) {
      const nObs = baseline.n_observations;
      const mean = baseline.mean;
      const window = typeof baseline.reference_start === 'string' ? baseline.reference_start : null;
      const windowEnd = typeof baseline.reference_end === 'string' ? baseline.reference_end : null;
      let text = 'Baseline: ';
      text += typeof nObs === 'number' ? `${nObs} observations` : 'observations not reported';
      if (typeof mean === 'number' && Number.isFinite(mean)) {
        text += `, mean ${formatEvidenceValue(mean)}`;
      }
      if (window) {
        text += ` (${window}${windowEnd ? ` → ${windowEnd}` : ''})`;
      }
      parts.push(text);
    }
    observation = parts.join(' · ');
  }
  return {
    hasContent:
      items.length > 0 ||
      methods.length > 0 ||
      limitations.length > 0 ||
      observation !== null,
    items,
    methods,
    limitations,
    observation,
  };
}

function ThermalReference({
  months,
}: {
  months: ReturnType<typeof thermalConcordanceMonthsOf>;
}): React.ReactElement {
  return (
    <details className="evidence-compact-ref">
      <summary>Thermal concordance — {months.length} months</summary>
      <ul>
        {months.map((month, i) => {
          const record = asRecord(month);
          if (!record) return null;
          const lstRel =
            typeof record.lst_relationship === 'string' ? record.lst_relationship : '—';
          const airRel =
            typeof record.air_relationship === 'string' ? record.air_relationship : '—';
          return (
            <li key={i}>
              <span className="text-muted">
                {String(record.window_start)} → {String(record.window_end ?? '')}:
              </span>{' '}
              <span>LST {lstRel} ({thermalRelationshipLabel(lstRel)})</span>
              {' · '}
              <span>ERA5 {airRel} ({thermalRelationshipLabel(airRel)})</span>
            </li>
          );
        })}
      </ul>
      <div className="text-muted" style={{ fontSize: '0.8rem' }}>
        MODIS Land Surface Temperature and ERA5-Land Modelled 2 m Air Temperature stay
        separate with distinct datasets and quantities.
      </div>
    </details>
  );
}

function SpatialReferenceBlock({
  spatial,
  domains,
}: {
  spatial: SpatialSectionPayload;
  domains: string[];
}): React.ReactElement {
  const bag = asRecord(spatial);
  const summaries = bag ? asRecord(bag.summaries) : null;
  const entries = summaries ? Object.entries(summaries) : [];
  if (entries.length === 0) return <></>;
  return (
    <details className="evidence-compact-ref">
      <summary>Spatial evidence available — {entries.length} metrics</summary>
      <ul>
        {entries.map(([metricKey, summary]) => {
          const record = asRecord(summary);
          const state =
            record && typeof record.state === 'string' ? record.state : '—';
          const usable =
            record && typeof record.n_usable === 'number' ? record.n_usable : null;
          const missing =
            record && typeof record.n_missing === 'number' ? record.n_missing : null;
          return (
            <li key={metricKey}>
              <code>{metricKey}</code> · <span>{state}</span>
              {usable !== null && <span className="text-muted"> · usable {usable}</span>}
              {missing !== null && <span className="text-muted"> · missing {missing}</span>}
              <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                {' '}
                · domains: {domains.join(', ')}
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function PatternReference({
  patterns,
}: {
  patterns: ReturnType<typeof patternsInResponse>;
}): React.ReactElement {
  return (
    <details className="evidence-compact-ref">
      <summary>Evidence patterns — {patterns.length}</summary>
      <ul>
        {patterns.map((pattern) => {
          const record = asRecord(pattern);
          if (!record) return null;
          const id = typeof record.pattern_id === 'string' ? record.pattern_id : '—';
          const type = typeof record.pattern_type === 'string' ? record.pattern_type : '—';
          const status = typeof record.status === 'string' ? record.status : '—';
          const explanation =
            typeof record.explanation === 'string' ? record.explanation : '';
          return (
            <li key={id}>
              <code>{id}</code> · <span>{type}</span> · <span>{status}</span>
              {explanation && <div className="text-muted">{explanation}</div>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function ValidationReference({
  validations,
}: {
  validations: ReturnType<typeof validationsInResponse>;
}): React.ReactElement {
  return (
    <details className="evidence-compact-ref">
      <summary>Cross-pattern validation — {validations.length}</summary>
      <ul>
        {validations.map((validation) => {
          const record = asRecord(validation);
          if (!record) return null;
          const id =
            typeof record.validation_id === 'string' ? record.validation_id : '—';
          const status = typeof record.status === 'string' ? record.status : '—';
          const explanation =
            typeof record.explanation === 'string' ? record.explanation : '';
          const contributing = asArray(record.contributing_pattern_ids).filter(
            (entry): entry is string => typeof entry === 'string',
          );
          return (
            <li key={id}>
              <code>{id}</code> · <span>{status}</span>
              {contributing.length > 0 && (
                <span className="text-muted"> · {contributing.join(', ')}</span>
              )}
              {explanation && <div className="text-muted">{explanation}</div>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
