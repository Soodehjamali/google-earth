import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import MapView from '../components/MapView';
import type {
  AgriculturalAnalysisResponse,
  AgricultureGeometry,
} from '../types';
import {
  asArray,
  asSynthesisStatement,
} from '../components/agriculture/parse';
import AnalysisRequestForm from '../components/agriculture/AnalysisRequestForm';
import SynthesisHeader from '../components/agriculture/SynthesisHeader';
import SynthesisStatementCard from '../components/agriculture/SynthesisStatementCard';
import { statementKeyFor } from '../components/agriculture/SynthesisStatementCard';
import DomainSummaryBlock from '../components/agriculture/DomainSummaryBlock';
import SpatialSection from '../components/agriculture/SpatialSection';
import DomainNavCards from '../components/agriculture/DomainNavCards';
import ValidationSection from '../components/agriculture/ValidationSection';
import AgricultureHealthCard from '../components/agriculture/AgricultureHealthCard';
import LimitationsBanner, {
  ScopeBanner,
} from '../components/agriculture/LimitationsBanner';
import { DOMAIN_PAGE_CONFIGS } from '../components/agriculture/domainPages';
import type { DomainGroupOption } from '../components/agriculture/request';
import { ndviProfileOf } from '../components/agriculture/yearComparison';
import {
  metricProfileOf,
  usableComparisonMetrics,
} from '../components/agriculture/yearComparison';
import { mapProfilePoints } from '../components/agriculture/temporalChart';
import TemporalLineChart from '../components/agriculture/TemporalLineChart';
import { patternsInResponse } from '../components/agriculture/evidence';
import { useAgricultureContext } from '../components/agriculture/AgricultureLayout';

/**
 * Agriculture Analysis Workspace (Prompt 3).
 * Multi-domain selection maps directly onto the existing `domains[]`
 * request field — no metric-level selection exists in the current
 * contract, so metric lists are informational only and no metric-level
 * payload is ever built. Consumes the parent-owned analysis context;
 * calls only the Comprehensive API via that context — never Legacy.
 * Advanced capabilities below are derived strictly from response fields
 * that are actually present; absent capabilities render as unavailable
 * information, never as fabricated results.
 */

interface WorkspaceGroupDef {
  pageKey: string;
  label: string;
  labelFa: string;
  icon: string;
}

const WORKSPACE_GROUPS: WorkspaceGroupDef[] = [
  { pageKey: 'vegetation', label: 'Vegetation & Canopy', labelFa: 'پوشش گیاهی و کانوپی', icon: '🌿' },
  { pageKey: 'water', label: 'Water & Moisture', labelFa: 'آب و رطوبت', icon: '💧' },
  { pageKey: 'soil', label: 'Soil', labelFa: 'خاک', icon: '🌍' },
  { pageKey: 'climate', label: 'Climate', labelFa: 'اقلیم', icon: '🌤️' },
  { pageKey: 'thermal', label: 'Thermal', labelFa: 'حرارتی', icon: '🌡️' },
  { pageKey: 'land-crop', label: 'Land Cover & Crop', labelFa: 'پوشش ارضی و زراعی', icon: '🗺️' },
  { pageKey: 'phenology', label: 'Phenology', labelFa: 'فنولوژی', icon: '📅' },
  { pageKey: 'stress-irrigation', label: 'Stress & Irrigation', labelFa: 'تنش و آبیاری', icon: '🚿' },
  { pageKey: 'terrain', label: 'Terrain', labelFa: 'توپوگرافی', icon: '⛰️' },
  { pageKey: 'history', label: 'Historical', labelFa: 'تاریخی', icon: '🕓' },
];

/** Real metric keys of one locked domain config — display only. */
function groupMetricKeys(pageKey: string): string[] {
  const config = DOMAIN_PAGE_CONFIGS[pageKey];
  if (!config) return [];
  const keys = new Set<string>();
  for (const section of config.sections) {
    for (const key of section.metricKeys) keys.add(key);
  }
  return [...keys].sort();
}

const DOMAIN_GROUP_OPTIONS: DomainGroupOption[] = WORKSPACE_GROUPS.map((group) => {
  const config = DOMAIN_PAGE_CONFIGS[group.pageKey];
  return {
    key: group.pageKey,
    label: group.label,
    labelFa: group.labelFa,
    icon: group.icon,
    domains: config ? [...config.apiDomains] : [],
    metrics: groupMetricKeys(group.pageKey),
  };
});

function countKeys(value: Record<string, unknown> | null | undefined): number {
  return value ? Object.keys(value).length : 0;
}

/** Backend-reported available metric keys across all evidence bundles. */
function availableMetricKeys(result: AgriculturalAnalysisResponse): Set<string> {
  const out = new Set<string>();
  const bundles = result.evidence_bundles ?? {};
  for (const bundle of Object.values(bundles)) {
    if (!bundle || !Array.isArray(bundle.available)) continue;
    for (const key of bundle.available) {
      if (typeof key === 'string') out.add(key);
    }
  }
  return out;
}

/**
 * Data-domain keys of one response (F-CONTRACT-FIX-1 semantics).
 *
 * Prefers the backend's explicit `domains_with_data`; falls back to a
 * bundle-derived read only for responses predating the additive field.
 * Data presence means the bundle holds at least one usable evidence
 * item — never merely that a bundle or structure exists.
 */
function dataDomainsOf(result: AgriculturalAnalysisResponse): string[] {
  const explicit = asArray(result.domains_with_data).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  if (explicit.length > 0) return explicit;
  const out: string[] = [];
  const bundles = result.evidence_bundles ?? {};
  for (const [domain, bundle] of Object.entries(bundles)) {
    if (!bundle || !Array.isArray(bundle.items)) continue;
    const hasUsable = bundle.items.some(
      (item) =>
        item &&
        item.is_usable === true &&
        item.status !== 'unavailable' &&
        typeof item.value === 'number' &&
        Number.isFinite(item.value),
    );
    if (hasUsable) out.push(domain);
  }
  return out;
}

const SPECTRAL_KEYS = [
  'ndvi', 'evi', 'savi', 'msavi', 'ndre',
  'ndwi', 'ndmi', 'mndwi', 'msi',
];

const RADAR_KEYS = ['vv', 'vh', 'vh_vv', 'rvi'];

const THERMAL_KEYS = [
  'land_surface_temperature_day',
  'land_surface_temperature_night',
  'land_surface_temperature_mean',
  'landsat_surface_temperature',
  'surface_temperature_range',
  'temperature_mean',
  'temperature_max',
  'temperature_min',
];

interface CapabilityEntry {
  key: string;
  icon: string;
  labelFa: string;
  labelEn: string;
  active: boolean;
  detail: string;
}

/**
 * Capability mapping (Prompt 3 §9): backend response fields →
 * workspace capabilities. Every entry is gated on data actually present
 * in the response; nothing here triggers a separate request.
 */
function capabilitiesOf(result: AgriculturalAnalysisResponse): CapabilityEntry[] {
  const temporal = result.temporal ?? null;
  const profiles =
    countKeys(temporal?.profiles) +
    countKeys(temporal?.radar_profiles) +
    countKeys(temporal?.thermal_profiles);
  const anomalies =
    countKeys(temporal?.anomalies) +
    countKeys(temporal?.radar_analyses) +
    countKeys(temporal?.thermal_analyses);
  const changes = countKeys(temporal?.changes);
  const concordant =
    temporal?.joint != null ||
    temporal?.concordance != null ||
    temporal?.thermal_concordance != null;
  const patterns = patternsInResponse(result).length;
  const validations =
    result.validation && Array.isArray(result.validation.results)
      ? result.validation.results.length
      : 0;
  // Synthesis statement semantics (F-CONTRACT-FIX-1): statement-bearing
  // domains, not data-bearing domains.  Falls back to counting domain
  // summaries with fired statements when the additive field is absent.
  const statementDomains = asArray(result.domains_with_statements).filter(
    (entry): entry is string => typeof entry === 'string',
  );
  const synthesis =
    statementDomains.length > 0
      ? statementDomains.length
      : Object.values(result.domain_summaries ?? {}).filter(
          (summary) => {
            if (!summary || typeof summary !== 'object') return false;
            const statements = (summary as { statements?: unknown }).statements;
            if (Array.isArray(statements) && statements.length > 0) return true;
            const count = (summary as { statement_count?: unknown }).statement_count;
            return typeof count === 'number' && count > 0;
          },
        ).length;
  const available = availableMetricKeys(result);
  const present = (keys: string[]): string[] => keys.filter((key) => available.has(key));
  const spectral = present(SPECTRAL_KEYS);
  const radar = present(RADAR_KEYS);
  const thermal = present(THERMAL_KEYS);
  // Spatial: a present-but-empty section is partial, not active
  // (F-CONTRACT-FIX-1 audit: the backend's explicit 0x0 refusal section
  // is a dict, so null-checking alone overstated the capability).
  const spatialUsable =
    result.spatial != null &&
    Array.isArray(result.spatial.cells) &&
    result.spatial.cells.length > 0;
  // Year comparison: a genuine multi-year comparison needs at least two
  // distinct years carrying finite profile points (P1 grouping contract,
  // MIN_COMPARABLE_YEARS).  A single-window profile is not a comparison.
  const ndviProfile = ndviProfileOf(temporal);
  const yearComparable =
    ndviProfile != null &&
    new Set(
      ndviProfile.points
        .filter((point) => point.value !== null && typeof point.window_start === 'string')
        .map((point) => point.window_start.slice(0, 4)),
    ).size >= 2;
  return [
    {
      key: 'temporal',
      icon: '📈',
      labelFa: 'تحلیل زمانی',
      labelEn: 'Temporal Analysis',
      active: profiles > 0,
      detail: profiles > 0 ? `${profiles} monthly profiles in response` : 'no profiles in response — see domain pages after a run',
    },
    {
      key: 'anomaly-change',
      icon: '🚨',
      labelFa: 'ناهنجاری و تغییر',
      labelEn: 'Anomaly & Change',
      active: anomalies > 0 || changes > 0,
      detail:
        anomalies > 0 || changes > 0
          ? `${anomalies} anomaly / ${changes} change analyses in response`
          : 'not present in response',
    },
    {
      key: 'spectral',
      icon: '🔬',
      labelFa: 'تحلیل طیفی',
      labelEn: 'Spectral Analysis',
      active: spectral.length > 0,
      detail: spectral.length > 0 ? `available: ${spectral.join(', ')} — detail on vegetation & water pages` : 'no spectral metrics available in response',
    },
    {
      key: 'radar',
      icon: '📡',
      labelFa: 'تحلیل راداری',
      labelEn: 'Radar Analysis',
      active: radar.length > 0,
      detail: radar.length > 0 ? `available: ${radar.join(', ')} — detail on the vegetation page` : 'no radar metrics available in response',
    },
    {
      key: 'concordance',
      icon: '🔗',
      labelFa: 'همخوانی نوری + راداری',
      labelEn: 'Optical + Radar Concordance',
      active: concordant,
      detail: concordant ? 'joint/concordance section in response' : 'not present in response',
    },
    {
      key: 'thermal',
      icon: '🌡️',
      labelFa: 'تحلیل حرارتی',
      labelEn: 'Thermal Analysis',
      active: thermal.length > 0,
      detail: thermal.length > 0 ? `available: ${thermal.join(', ')} — detail on thermal & climate pages` : 'no thermal metrics available in response',
    },
    {
      key: 'spatial',
      icon: '🗺️',
      labelFa: 'تحلیل مکانی',
      labelEn: 'Spatial Analysis',
      active: spatialUsable,
      detail: spatialUsable
        ? 'spatial section rendered below'
        : result.spatial != null
          ? 'spatial section present but carries no usable grid'
          : 'not present in response',
    },
    {
      key: 'year',
      icon: '📅',
      labelFa: 'مقایسه سال‌به‌سال',
      labelEn: 'Year Comparison',
      active: yearComparable,
      detail: yearComparable
        ? 'multi-year NDVI profile present — detail on the history page'
        : ndviProfile != null
          ? 'NDVI profile present but spans fewer than two years'
          : 'no NDVI profile in response',
    },
    {
      key: 'patterns',
      icon: '🧩',
      labelFa: 'تحلیل الگو',
      labelEn: 'Pattern Analysis',
      active: patterns > 0,
      detail: patterns > 0 ? `${patterns} patterns in response evidence` : 'not carried in the analysis response',
    },
    {
      key: 'validation',
      icon: '✅',
      labelFa: 'اعتبارسنجی',
      labelEn: 'Validation',
      active: validations > 0,
      detail: validations > 0 ? `${validations} validation results below` : 'runs only when reference observations are supplied',
    },
    {
      key: 'synthesis',
      icon: '💡',
      labelFa: 'سنتز',
      labelEn: 'Synthesis',
      active: synthesis > 0,
      detail: synthesis > 0 ? `${synthesis} domain(s) with fired synthesis statements` : 'no synthesis statements in response',
    },
  ];
}

/**
 * Which temporal state a response is in (F-CONTRACT-FRONTEND-CONTRACT-1 §4):
 * A — the backend sent no temporal section at all (skipped/pre-contract);
 * B — a section exists but no profile carries a usable point value;
 * C — usable profile points exist and can be charted.
 */
type HubTemporalState = 'absent' | 'no-usable-points' | 'chartable';

function hubTemporalStateOf(
  temporal: unknown,
  usable: string[],
): HubTemporalState {
  if (temporal === null || temporal === undefined) return 'absent';
  return usable.length > 0 ? 'chartable' : 'no-usable-points';
}

/**
 * Compact hub temporal preview (F-A3.2). Reuses the shared monthly
 * chart over the backend profiles actually present (ndvi preferred,
 * otherwise the first usable comparison metric). No fetching, no
 * derivation, no duplication of the full TemporalSection: a visual
 * preview with a link to the detailed domain view.  Empty states are
 * split by cause (F-CONTRACT-FRONTEND-CONTRACT-1 §4): section absent
 * vs section present without usable points.
 */
function HubTemporalStrip({ result }: { result: AgriculturalAnalysisResponse }) {
  const temporal = result.temporal ?? null;
  const usable = useMemo(() => usableComparisonMetrics(temporal), [temporal]);
  const [override, setOverride] = useState<string | null>(null);
  const selected =
    override && usable.includes(override)
      ? override
      : usable.includes('ndvi')
        ? 'ndvi'
        : (usable[0] ?? null);
  const profile = selected ? metricProfileOf(temporal, selected) : null;
  const data = useMemo(
    () => mapProfilePoints(profile?.points ?? [], profile?.unit ?? ''),
    [profile],
  );
  const state = hubTemporalStateOf(temporal, usable);

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">📈 نمای زمانی — Temporal Preview</span>
      </div>
      <div className="card-body">
        {usable.length > 1 && selected && (
          <div className="form-row" style={{ marginBottom: 8 }}>
            <label className="text-muted" htmlFor="hub-temporal-metric">
              شاخص — Metric:
            </label>
            <select
              id="hub-temporal-metric"
              value={selected}
              onChange={(event) => setOverride(event.target.value)}
            >
              {usable.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </div>
        )}
        {state === 'absent' ? (
          <div className="empty-state">
            <div className="empty-state-title">No temporal section in response</div>
            <div className="empty-state-desc">
              The backend did not attach the temporal section to this
              response (analysis skipped or pre-contract payload).
            </div>
          </div>
        ) : state === 'no-usable-points' ? (
          <div className="empty-state">
            <div className="empty-state-title">
              Temporal section present — no usable monthly profile
            </div>
            <div className="empty-state-desc">
              The response carries a temporal section, but none of the
              ndvi, ndmi, ndre, or msi profiles contains a usable point
              value to chart.
            </div>
          </div>
        ) : (
          <>
            <TemporalLineChart
              data={data}
              unit={profile?.unit ?? ''}
              observedLabel={selected}
              height={180}
              ariaLabel={`Hub temporal preview for ${selected}`}
            />
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
              Backend monthly {selected} observations with gaps preserved. Full
              anomaly, change, and year-over-year detail on the{' '}
              <Link to="/agriculture/vegetation">vegetation page</Link>.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Agriculture() {
  const { result, loading, error, runAnalysis } = useAgricultureContext();
  const [formError, setFormError] = useState<string | null>(null);
  const [previewGeometry, setPreviewGeometry] = useState<
    AgricultureGeometry | undefined
  >(undefined);
  const [previewCenter, setPreviewCenter] = useState<[number, number]>([55.0, 32.0]);
  const [expandedStatements, setExpandedStatements] = useState<Set<string>>(new Set());
  const [expandedEvidence, setExpandedEvidence] = useState<Set<string>>(new Set());

  const handlePreviewChange = useCallback(
    (geometry: AgricultureGeometry | undefined, center: [number, number]) => {
      setPreviewGeometry((prev) => {
        const before = JSON.stringify(prev ?? null);
        const after = JSON.stringify(geometry ?? null);
        return before === after ? prev : geometry;
      });
      setPreviewCenter((prev) =>
        prev[0] === center[0] && prev[1] === center[1] ? prev : center,
      );
    },
    [],
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

  const bannerError = formError || error;
  const crossDomainStatements = result ? asArray(result.cross_domain_statements) : [];
  // Domain visibility (F-CONTRACT-FRONTEND-CONTRACT-1 §1): the hub
  // renders evidence/data sections for every data-bearing domain —
  // domains_with_data — not only the statement-bearing available_domains,
  // so a domain like soil with usable values but no fired rule is no
  // longer hidden.  Statement/synthesis semantics stay on
  // available_domains (below, via DomainSummaryBlock statements).
  const dataDomains = result ? dataDomainsOf(result) : [];
  const availableDomains = result ? asArray(result.available_domains) : [];
  const hasResults = dataDomains.length;
  const capabilities = result ? capabilitiesOf(result) : [];

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">تحلیل کشاورزی</h2>
        <p className="page-subtitle">Agriculture Analysis Workspace — domain-based multi-analysis</p>
      </div>

      {bannerError && (
        <div className="error-banner">
          <span>⚠️</span>
          <span>{bannerError}</span>
        </div>
      )}

      <div className="text-muted" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
        بخش ۱ — فضای کاری تحلیل: مکان، تاریخ و انتخاب چند دامین (domains[] واقعی)
      </div>

      <div className="grid-2">
        <AnalysisRequestForm
          loading={loading}
          showDomainSelection
          domainGroups={DOMAIN_GROUP_OPTIONS}
          onSubmit={(request) => void runAnalysis(request)}
          onPreviewChange={handlePreviewChange}
          onError={setFormError}
        />

        <div className="card">
          <div className="card-header">
            <span className="card-title">🗺️ نقشه</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <MapView
              geometry={previewGeometry}
              center={previewCenter}
              zoom={previewGeometry?.type === 'Point' ? 12 : 10}
            />
          </div>
        </div>
      </div>

      <div className="mt-2">
        <AgricultureHealthCard />
      </div>

      <div className="text-muted" style={{ fontSize: '0.85rem', margin: '12px 0 8px' }}>
        صفحات مستقل دامین — هر کدام تحلیل جداگانه خودش را اجرا می‌کند
      </div>

      <div className="mt-2">
        <DomainNavCards />
      </div>

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <span>در حال تحلیل کشاورزی...</span>
        </div>
      )}

      {result && !loading && (
        <>
          <div className="text-muted" style={{ fontSize: '0.85rem', margin: '12px 0 8px' }}>
            بخش ۲ — نمای کلی نتیجه (Overview)
          </div>

          <SynthesisHeader result={result} />

          <div className="card mb-3">
            <div className="card-header">
              <span className="card-title">🧰 قابلیت‌های تحلیلی — Analysis Capabilities</span>
            </div>
            <div className="card-body">
              <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 8 }}>
                فقط قابلیت‌هایی که پاسخ Backend واقعاً داده دارد فعال‌اند — بدون درخواست جداگانه و بدون نتیجه ساختگی.
              </div>
              <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
                {capabilities.map((cap) => (
                  <span
                    key={cap.key}
                    className={`badge ${cap.active ? 'badge-good' : ''}`}
                    title={`${cap.labelEn}: ${cap.detail}`}
                  >
                    {cap.icon} {cap.labelFa} — {cap.active ? 'فعال' : 'غیرفعال'}
                  </span>
                ))}
              </div>
              <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
                جزئیات زمانی، ناهنجاری، تغییر و الگو در صفحات مستقل دامین نمایش داده می‌شود.
              </div>
            </div>
          </div>

          <HubTemporalStrip result={result} />

          {crossDomainStatements.length > 0 && (
            <div className="card mb-3">
              <div className="card-header">
                <span className="card-title">🔗 تحلیل بین‌حوزه‌ای — Cross-Domain Synthesis</span>
              </div>
              <div className="card-body">
                <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 8 }}>
                  گزاره‌های زیر عیناً از موتور سنتز Backend آمده‌اند — هیچ ادعای علّی جدیدی اضافه نشده است.
                </div>
                {crossDomainStatements.map((stmt, i) => {
                  const statement = asSynthesisStatement(stmt);
                  if (!statement) return null;
                  return (
                    <SynthesisStatementCard
                      key={`cross-${i}`}
                      statement={statement}
                      index={i}
                      expanded={expandedStatements.has(statementKeyFor(statement, i))}
                      expandedEvidence={expandedEvidence}
                      toggleStatement={toggleStatement}
                      toggleEvidence={toggleEvidence}
                      bundles={result.evidence_bundles ?? {}}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {hasResults > 0 && (
            <div className="card mb-3">
              <div className="card-header">
                <span className="card-title">📊 خلاصه حوزه‌ها — Domain Summaries</span>
              </div>
              <div className="card-body" style={{ padding: 0 }}>
                {/* Data domains first, verbatim backend order preserved within
                    each list; statement-only legacy ordering follows for any
                    statement-bearing domain that carried no usable items. */}
                {dataDomains.map((domainKey) => (
                  <DomainSummaryBlock
                    key={domainKey}
                    domainKey={domainKey}
                    summary={result.domain_summaries?.[domainKey]}
                    bundles={result.evidence_bundles ?? {}}
                    defaultExpanded
                  />
                ))}
                {availableDomains
                  .filter(
                    (domainKey): domainKey is string =>
                      typeof domainKey === 'string' && !dataDomains.includes(domainKey),
                  )
                  .map((domainKey) => (
                    <DomainSummaryBlock
                      key={domainKey}
                      domainKey={domainKey}
                      summary={result.domain_summaries?.[domainKey]}
                      bundles={result.evidence_bundles ?? {}}
                    />
                  ))}
              </div>
            </div>
          )}

          {hasResults === 0 && result.overall_sufficiency === 'insufficient' && (
            <div className="empty-state">
              <div className="empty-state-icon">🌾</div>
              <div className="empty-state-title">داده کافی یافت نشد</div>
              <div className="empty-state-desc">
                تحلیل اجرا شد اما هیچ حوزه‌ای شواهد قابل استفاده نداشت.
              </div>
            </div>
          )}

          <ValidationSection validation={result.validation ?? null} />

          <SpatialSection spatial={result.spatial ?? null} />

          <LimitationsBanner limitations={result.limitations ?? []} />
          <ScopeBanner />
        </>
      )}
    </div>
  );
}
