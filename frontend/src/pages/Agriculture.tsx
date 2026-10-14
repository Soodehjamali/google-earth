import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import MapView from '../components/MapView';
import type {
  AgriculturalAnalysisResponse,
  AgricultureGeometry,
  LandUseType,
} from '../types';
import AnalysisRequestForm, {
  formatElapsedFa,
  type GeometryInputMode,
} from '../components/agriculture/AnalysisRequestForm';
import { calculatePolygonCenter } from '../components/agriculture/polygon';
import {
  asArray,
  asSynthesisStatement,
} from '../components/agriculture/parse';
import SynthesisHeader from '../components/agriculture/SynthesisHeader';
import SynthesisStatementCard from '../components/agriculture/SynthesisStatementCard';
import { statementKeyFor } from '../components/agriculture/SynthesisStatementCard';
import DomainSummaryBlock from '../components/agriculture/DomainSummaryBlock';
import AnalysisOverviewSection from '../components/agriculture/AnalysisOverviewSection';
import AgronomicDecisionSupportSection from '../components/agriculture/AgronomicDecisionSupportSection';
import CategorizedMetricCards from '../components/agriculture/CategorizedMetricCards';
import SpatialSection from '../components/agriculture/SpatialSection';
import SpatialIntelligenceSection from '../components/agriculture/SpatialIntelligenceSection';
import OrchardHeatmapSwipeSection from '../components/agriculture/OrchardHeatmapSwipeSection';
import Historical10YearSection from '../components/agriculture/Historical10YearSection';
import SoilIntelligenceSection from '../components/agriculture/SoilIntelligenceSection';
import RawBandsInspectionSection from '../components/agriculture/RawBandsInspectionSection';
import DomainNavCards from '../components/agriculture/DomainNavCards';
import ValidationSection from '../components/agriculture/ValidationSection';
import AgricultureHealthCard from '../components/agriculture/AgricultureHealthCard';
import AgricultureHistorySection from '../components/agriculture/AgricultureHistorySection';
import LimitationsBanner, {

  ScopeBanner,
} from '../components/agriculture/LimitationsBanner';
import { DOMAIN_PAGE_CONFIGS } from '../components/agriculture/domainPages';
import type { DomainGroupOption } from '../components/agriculture/request';
import { ndviProfileOf } from '../components/agriculture/yearComparison';
import {
  ALL_TEMPORAL_METRICS,
  usableTemporalMetrics,
} from '../components/agriculture/yearComparison';
import {
  anomalyFor,
  attachAnomalies,
  attachChanges,
  baselineLevels,
  changeFor,
  mapProfilePoints,
  payloadAnomalies,
  payloadChanges,
  payloadPoints,
  profileFor,
} from '../components/agriculture/temporalChart';
import TemporalLineChart from '../components/agriculture/TemporalLineChart';
import { patternsInResponse } from '../components/agriculture/evidence';
import { useAgricultureContext } from '../components/agriculture/AgricultureLayout';
import KeyReadings from '../components/agriculture/KeyReadings';
import { SupportBadge } from '../components/agriculture/SupportNotice';
import { asRecord, findEvidenceItem, isFiniteNumber } from '../components/agriculture/parse';
import { supportInfoOf } from '../components/agriculture/support';
import ErrorBanner from '../components/agriculture/ErrorBanner.tsx';

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

function readBaseline(payload: Record<string, unknown> | null): ReturnType<typeof baselineLevels> {
  if (!payload) return null;
  const record = asRecord(payload.baseline);
  if (!record || !isFiniteNumber(record.mean)) return null;
  return baselineLevels({
    mean: record.mean,
    minimum: record.minimum,
    maximum: record.maximum,
  });
}

interface TemporalFamilyDef {
  id: string;
  title: string;
  titleFa: string;
  icon: string;
  metrics: string[];
  defaultMetric: string;
  domainRoute: string;
}

const TEMPORAL_FAMILIES: TemporalFamilyDef[] = [
  {
    id: 'optical',
    title: 'Optical Vegetation & Moisture Profiles',
    titleFa: 'پوشش گیاهی و رطوبت — اپتیکال',
    icon: '🌿',
    metrics: ['ndvi', 'ndmi', 'ndre', 'msi'],
    defaultMetric: 'ndvi',
    domainRoute: '/agriculture/vegetation',
  },
  {
    id: 'radar',
    title: 'Radar Backscatter Profiles (Sentinel-1)',
    titleFa: 'پس‌پراکنش رادار — سنتینل-۱',
    icon: '📡',
    metrics: ['vv', 'vh', 'vh_vv', 'rvi'],
    defaultMetric: 'vv',
    domainRoute: '/agriculture/vegetation',
  },
  {
    id: 'thermal',
    title: 'Thermal & Surface Temperature Profiles',
    titleFa: 'دما و حرارتی — مودیس و ارا۵',
    icon: '🌡️',
    metrics: ['land_surface_temperature_day', 'temperature_mean'],
    defaultMetric: 'land_surface_temperature_day',
    domainRoute: '/agriculture/thermal',
  },
];

function HubTemporalFamilyCard({
  family,
  temporal,
  result,
}: {
  family: TemporalFamilyDef;
  temporal: unknown;
  result: AgriculturalAnalysisResponse;
}) {
  const usable = useMemo(
    () => usableTemporalMetrics(temporal, family.metrics),
    [temporal, family.metrics],
  );
  const [selected, setSelected] = useState<string>(() =>
    usable.includes(family.defaultMetric) ? family.defaultMetric : usable[0] ?? family.defaultMetric,
  );
  const activeMetric = usable.includes(selected) ? selected : usable[0] ?? null;
  const payload = activeMetric ? profileFor(temporal, activeMetric) : null;
  const anomalyPayload = activeMetric ? anomalyFor(temporal, activeMetric) : null;
  const changePayload = activeMetric ? changeFor(temporal, activeMetric) : null;
  const unit = (payload?.unit as string) ?? '';
  const basePoints = useMemo(
    () => (payload ? mapProfilePoints(payloadPoints(payload), unit) : []),
    [payload, unit],
  );
  const data = useMemo(
    () =>
      attachChanges(
        attachAnomalies(basePoints, payloadAnomalies(anomalyPayload ?? payload)),
        payloadChanges(changePayload ?? payload),
      ),
    [basePoints, anomalyPayload, changePayload, payload],
  );
  const baseline = useMemo(
    () => readBaseline(anomalyPayload ?? payload),
    [anomalyPayload, payload],
  );
  const provenance = activeMetric
    ? findEvidenceItem(result.evidence_bundles, activeMetric)?.item.provenance
    : null;
  const support = supportInfoOf(provenance);

  if (usable.length === 0) return null;

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">
          {family.icon} {family.titleFa} — {family.title}
        </span>
      </div>
      <div className="card-body">
        {usable.length > 1 && activeMetric && (
          <div className="form-row" style={{ marginBottom: 8 }}>
            <label className="text-muted" htmlFor={`hub-temporal-${family.id}`}>
              شاخص — Metric:
            </label>
            <select
              id={`hub-temporal-${family.id}`}
              value={activeMetric}
              onChange={(event) => setSelected(event.target.value)}
            >
              {usable.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </div>
        )}
        {activeMetric && payload && (
          <>
            <TemporalLineChart
              data={data}
              unit={unit}
              observedLabel={activeMetric}
              height={180}
              baseline={baseline}
              ariaLabel={`Hub temporal preview for ${activeMetric}`}
            />
            <div className="support-strip-badge" style={{ marginTop: 8 }}>
              <SupportBadge provenance={provenance} />{' '}
              <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                {support?.explanationEn ??
                  'Monthly values describe the support area around the selected point.'}
              </span>
            </div>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 8 }}>
              Backend monthly {activeMetric} observations with gaps preserved. Full
              anomaly, change, and year-over-year detail on the{' '}
              <Link to={family.domainRoute}>domain page</Link>.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Compact hub temporal preview covering all available profile families.
 * Renders dedicated preview cards for optical, radar, and thermal profiles.
 */
function HubTemporalStrip({ result }: { result: AgriculturalAnalysisResponse }) {
  const temporal = result.temporal ?? null;
  const allUsable = useMemo(
    () => usableTemporalMetrics(temporal, ALL_TEMPORAL_METRICS),
    [temporal],
  );
  const state = hubTemporalStateOf(temporal, allUsable);

  if (state === 'absent') {
    return (
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">📈 نمای زمانی — Temporal Preview</span>
        </div>
        <div className="card-body">
          <div className="empty-state">
            <div className="empty-state-title">No temporal section in response</div>
            <div className="empty-state-desc">
              The backend did not attach the temporal section to this
              response (analysis skipped or pre-contract payload).
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (state === 'no-usable-points') {
    return (
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">📈 نمای زمانی — Temporal Preview</span>
        </div>
        <div className="card-body">
          <div className="empty-state">
            <div className="empty-state-title">
              Temporal section present — no usable monthly profile
            </div>
            <div className="empty-state-desc">
              The response carries a temporal section, but none of the
              monthly profiles contains a usable point value to chart.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <section aria-label="Temporal preview" className="hub-temporal-section mb-3">
      {TEMPORAL_FAMILIES.map((family) => (
        <HubTemporalFamilyCard
          key={family.id}
          family={family}
          temporal={temporal}
          result={result}
        />
      ))}
    </section>
  );
}

export default function Agriculture() {
  const {
    result,
    loading,
    error,
    runAnalysis,
    lastRequest,
    savedAnalysisId,
    loadSavedAnalysis,
  } = useAgricultureContext();
  const [formError, setFormError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [showHistory, setShowHistory] = useState<boolean>(false);

  useEffect(() => {
    if (!loading) {
      setElapsedSeconds(0);
      return;
    }
    const startTime = Date.now();
    setElapsedSeconds(0);
    const timer = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [loading]);

  const [previewGeometry, setPreviewGeometry] = useState<
    AgricultureGeometry | undefined
  >(undefined);
  const [previewCenter, setPreviewCenter] = useState<[number, number]>([55.0, 32.0]);
  const [confirmedPolygon, setConfirmedPolygon] = useState<GeoJSON.Polygon | null>(null);
  const [isPolygonConfirmed, setIsPolygonConfirmed] = useState<boolean>(false);
  const [activeGeometryMode, setActiveGeometryMode] = useState<GeometryInputMode>('draw');
  const [landUseType, setLandUseType] = useState<LandUseType>('field_crop');
  const [isCreatingNew, setIsCreatingNew] = useState<boolean>(false);
  const [expandedStatements, setExpandedStatements] = useState<Set<string>>(new Set());
  const [expandedEvidence, setExpandedEvidence] = useState<Set<string>>(new Set());
  const [showTechnicalDetails, setShowTechnicalDetails] = useState<boolean>(false);

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
      <div className="page-header d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div>
          <h2 className="page-title">تحلیل کشاورزی</h2>
          <p className="page-subtitle">Agriculture Analysis Workspace — domain-based multi-analysis</p>
        </div>
        <div className="d-flex align-items-center gap-2">
          <button
            type="button"
            className={`btn btn-sm ${showHistory ? 'btn-primary' : 'btn-outline-primary'}`}
            onClick={() => setShowHistory((prev) => !prev)}
            data-testid="toggle-history-btn"
          >
            📜 {showHistory ? 'بستن تاریخچه' : 'تاریخچه تحلیل‌ها'}
          </button>
          {result && !isCreatingNew && (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setIsCreatingNew(true)}
              data-testid="create-new-analysis-btn"
            >
              ➕ ایجاد لوکیشن جدید
            </button>
          )}
          {result && isCreatingNew && (
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={() => setIsCreatingNew(false)}
              data-testid="cancel-create-new-btn"
            >
              ↩️ انصراف و بازگشت به تحلیل فعال
            </button>
          )}
        </div>
      </div>

      {/* Persistent History Panel */}
      {showHistory && (
        <AgricultureHistorySection
          className="mb-4"
          activeAnalysisId={savedAnalysisId}
          onSelectAnalysis={(id) => {
            void loadSavedAnalysis(id);
            setShowHistory(false);
            setIsCreatingNew(false);
          }}
        />
      )}

      {/* Notice when user is creating a new location while previous analysis is preserved */}
      {isCreatingNew && result && (
        <div
          className="alert alert-warning d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3"
          data-testid="creating-new-notice-banner"
          style={{
            backgroundColor: '#fff8e1',
            border: '1px solid #ffe082',
            color: '#795548',
            padding: '10px 16px',
            borderRadius: '6px',
          }}
        >
          <div className="d-flex align-items-center gap-2">
            <span>✏️</span>
            <span style={{ fontSize: '0.88rem' }}>
              <strong>ایجاد لوکیشن جدید:</strong> تحلیل فعال جاری محفوظ است. در صورت تمایل می‌توانید با دکمه «انصراف» به تحلیل فعال بازگردید.
            </span>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={() => setIsCreatingNew(false)}
            data-testid="cancel-create-new-banner-btn"
          >
            انصراف و بازگشت
          </button>
        </div>
      )}

      {/* Stored Report Retrieval Banner (Phase P0-HISTORY) */}
      {savedAnalysisId && result && (
        <div
          className="alert alert-info d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3"
          data-testid="retrieved-from-history-banner"
          style={{
            backgroundColor: '#e8f5e9',
            border: '1px solid #81c784',
            color: '#1b5e20',
            padding: '10px 16px',
            borderRadius: '6px',
          }}
        >
          <div className="d-flex align-items-center gap-2">
            <span>💾</span>
            <span style={{ fontSize: '0.88rem' }}>
              <strong>گزارش بازیابی‌شده از تاریخچه دائمی:</strong> این گزارش مستقیماً از دیتابیس PostgreSQL لود شده و هیچ درخواست مجددی به موتور گوگل ارث (GEE) ارسال نشده است.
            </span>
          </div>
          <div className="d-flex align-items-center gap-2">
            <span className="badge badge-good" style={{ padding: '4px 8px' }}>
              بدون اجرای مجدد GEE
            </span>
            <code style={{ fontSize: '0.78rem', color: '#2e7d32' }}>
              {savedAnalysisId.slice(0, 8)}
            </code>
          </div>
        </div>
      )}

      {bannerError && (
        <ErrorBanner error={bannerError} />
      )}

      {(!result || isCreatingNew) && (
        <>
          <div className="text-muted" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
            بخش ۱ — فضای کاری تحلیل: مکان، تاریخ و انتخاب چند دامین (domains[] واقعی)
          </div>

          <div className="grid-2">
            <AnalysisRequestForm
              loading={loading}
              showDomainSelection
              domainGroups={DOMAIN_GROUP_OPTIONS}
              onSubmit={async (request) => {
                await runAnalysis(request);
                setIsCreatingNew(false);
              }}
              onPreviewChange={handlePreviewChange}
              onError={setFormError}
              confirmedPolygon={confirmedPolygon}
              isPolygonConfirmed={isPolygonConfirmed}
              onPolygonClear={() => {
                setConfirmedPolygon(null);
                setIsPolygonConfirmed(false);
              }}
              onPolygonEdit={() => {
                setIsPolygonConfirmed(false);
              }}
              onModeChange={setActiveGeometryMode}
              initialMode="draw"
              landUse={landUseType}
              onLandUseChange={setLandUseType}
            />

            <div className="card">
              <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="card-title">🗺️ نقشه</span>
                {activeGeometryMode === 'draw' && (
                  <span className="badge badge-info" style={{ fontSize: '0.75rem' }}>
                    ✏️ حالت رسم مرز زمین فعال است
                  </span>
                )}
              </div>
              <div className="card-body" style={{ padding: 0 }}>
                <MapView
                  geometry={previewGeometry}
                  center={previewCenter}
                  zoom={previewGeometry?.type === 'Point' ? 12 : previewGeometry?.type === 'Polygon' ? 13 : 11}
                  enableDrawing={activeGeometryMode === 'draw'}
                  showDrawControls={activeGeometryMode === 'draw'}
                  initialPolygon={confirmedPolygon}
                  onPolygonConfirm={(poly) => {
                    setConfirmedPolygon(poly);
                    setIsPolygonConfirmed(true);
                    setPreviewGeometry(poly as AgricultureGeometry);
                    setPreviewCenter(calculatePolygonCenter(poly.coordinates[0] as [number, number][]));
                  }}
                  onPolygonChange={(poly, confirmed) => {
                    setConfirmedPolygon(poly);
                    setIsPolygonConfirmed(confirmed);
                    if (poly) {
                      setPreviewGeometry(poly as AgricultureGeometry);
                      setPreviewCenter(calculatePolygonCenter(poly.coordinates[0] as [number, number][]));
                    }
                  }}
                  onPolygonClear={() => {
                    setConfirmedPolygon(null);
                    setIsPolygonConfirmed(false);
                    setPreviewGeometry(undefined);
                  }}
                />
              </div>
            </div>
          </div>

          <div className="mt-2">
            <AgricultureHealthCard />
          </div>
        </>
      )}

      <div className="text-muted" style={{ fontSize: '0.85rem', margin: '12px 0 8px' }}>
        صفحات مستقل دامین — هر کدام تحلیل جداگانه خودش را اجرا می‌کند
      </div>

      <div className="mt-2">
        <DomainNavCards />
      </div>

      {loading && (
        <div
          data-testid="agriculture-loading-card"
          className="card mt-3 mb-3"
          style={{
            padding: 24,
            textAlign: 'center',
            border: '1px solid #90caf9',
            background: 'var(--bg-secondary, #f8fbfd)',
            borderRadius: 8,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
            <div className="spinner" style={{ width: 36, height: 36, borderWidth: 3 }} />
          </div>
          <h3 style={{ margin: '0 0 8px', color: '#1565c0', fontSize: '1.15rem' }}>
            تحلیل در حال انجام است
          </h3>
          <p style={{ margin: '0 0 12px', color: '#455a64', fontSize: '0.9rem', lineHeight: 1.6 }}>
            این تحلیل با داده‌های ماهواره‌ای واقعی انجام می‌شود و ممکن است چند دقیقه زمان ببرد.
          </p>
          <div
            data-testid="agriculture-elapsed-time"
            style={{
              fontSize: '0.85rem',
              color: '#546e7a',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: '#e3f2fd',
              padding: '6px 14px',
              borderRadius: 16,
            }}
          >
            <span>⏱️ زمان سپری‌شده:</span>
            <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>
              {formatElapsedFa(elapsedSeconds)}
            </span>
          </div>
        </div>
      )}

      {result && !loading && (
        <>
          <div className="text-muted" style={{ fontSize: '0.85rem', margin: '16px 0 10px' }}>
            بخش ۲ — خروجی تحلیل کشاورزی: لایه پشتیبانی تصمیم و شواهد چندمنبعی (Decision Support & Evidence)
          </div>

          {/* 0. Primary Farmer Decision Support Layer (P-AGRI-DSS-1) */}
          <AgronomicDecisionSupportSection
            result={result}
            landUseType={landUseType}
            onLandUseChange={setLandUseType}
          />

          {/* 1. First Screen: Executive Interpretation Summary & Overall Status */}
          <AnalysisOverviewSection result={result} />

          {/* 2. Grouped Metric Cards (Vegetation, Moisture, Thermal, Radar, Terrain, Soil/Water) */}
          <CategorizedMetricCards bundles={result.evidence_bundles ?? {}} />

          {/* 2.5 Soil Intelligence (Depth Profiles, SoilGrids 2.0, USDA Texture, Lab Ground Truth) */}
          {result.soil_intelligence && (
            <SoilIntelligenceSection
              initialSoilData={result.soil_intelligence}
              geometry={lastRequest?.geometry ?? result.geometry ?? previewGeometry ?? null}
              startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
              endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
              cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
              isSavedReport={Boolean(savedAnalysisId)}
            />
          )}

          {/* 3. 10-Year Same-Period Historical Comparison (Phase P-AGRI-HIST-10Y) */}
          <Historical10YearSection
            geometry={lastRequest?.geometry ?? previewGeometry ?? null}
            startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
            endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
            cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
            domain="vegetation"
            disableAutoFetch={Boolean(savedAnalysisId)}
          />

          {/* 4. Interactive Current Orchard ↔ Evidence Heatmap Swipe (Phase P-AGRI-MAP-SWIPE) */}
          <OrchardHeatmapSwipeSection
            geometry={lastRequest?.geometry ?? previewGeometry ?? null}
            startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
            endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
            cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
            disableAutoFetch={Boolean(savedAnalysisId)}
          />

          {/* 5. Spatial Intelligence & Spatial Heatmap Section */}
          <SpatialIntelligenceSection
            geometry={lastRequest?.geometry ?? previewGeometry ?? null}
            startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
            endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
            cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
            disableAutoFetch={Boolean(savedAnalysisId)}
          />

          {/* 4. Deep Technical Evidence Details & Telemetry (Collapsible Progressive Disclosure) */}
          <div className="card mb-4" style={{ marginTop: 20 }}>
            <div
              className="card-header"
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                cursor: 'pointer',
              }}
              onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
            >
              <div>
                <span className="card-title" style={{ fontSize: '0.95rem', fontWeight: 700 }}>
                  🔬 شواهد و تلمتری عمیق فنی — Deep Technical Evidence & Telemetry
                </span>
                <div className="text-muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>
                  شامل پروفایل‌های زمانی، گزاره‌های سنتز چندحوزه‌ای، خلاصه‌های دامین و اعتبارسنجی زمینی
                </div>
              </div>
              <button
                type="button"
                className="button button-sm button-outline"
                style={{ fontSize: '0.78rem' }}
                onClick={(e) => {
                  e.stopPropagation();
                  setShowTechnicalDetails(!showTechnicalDetails);
                }}
                aria-expanded={showTechnicalDetails}
              >
                {showTechnicalDetails ? 'بستن جزئیات فنی ▲' : 'نمایش شواهد فنی و سنتز ▼'}
              </button>
            </div>

            {showTechnicalDetails && (
              <div className="card-body">
                <SynthesisHeader result={result} />

                <KeyReadings bundles={result.evidence_bundles ?? {}} />

                <RawBandsInspectionSection result={result} />

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
                  </div>
                </div>

                <HubTemporalStrip result={result} />

                {crossDomainStatements.length > 0 && (
                  <div className="card mb-3">
                    <div className="card-header">
                      <span className="card-title">🔗 تحلیل بین‌حوزه‌ای — Cross-Domain Synthesis</span>
                    </div>
                    <div className="card-body">
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

                <ValidationSection validation={result.validation ?? null} />

                <SpatialSection spatial={result.spatial ?? null} />
              </div>
            )}
          </div>

          {hasResults === 0 && result.overall_sufficiency === 'insufficient' && (
            <div className="empty-state">
              <div className="empty-state-icon">🌾</div>
              <div className="empty-state-title">داده کافی یافت نشد</div>
              <div className="empty-state-desc">
                تحلیل اجرا شد اما هیچ حوزه‌ای شواهد قابل استفاده نداشت.
              </div>
            </div>
          )}

          <LimitationsBanner limitations={result.limitations ?? []} />
          <ScopeBanner />
        </>
      )}
    </div>
  );
}
