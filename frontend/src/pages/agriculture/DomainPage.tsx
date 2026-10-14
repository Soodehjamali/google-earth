import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import MapView from '../../components/MapView';
import type {
  AgriculturalAnalysisResponse,
  AgricultureAnalysisRequest,
  AgricultureGeometry,
  EvidenceBundleResponse,
} from '../../types';
import { agricultureApi } from '../../api/agriculture';
import { useAgricultureContext } from '../../components/agriculture/AgricultureLayout';
import { DOMAIN_PAGE_CONFIGS } from '../../components/agriculture/domainPages';
import {
  asArray,
  domainMetaFor,
  findEvidenceItem,
  normalizeResponse,
} from '../../components/agriculture/parse';
import AnalysisRequestForm, {
  type GeometryInputMode,
} from '../../components/agriculture/AnalysisRequestForm';
import { calculatePolygonCenter } from '../../components/agriculture/polygon';
import DomainNavCards from '../../components/agriculture/DomainNavCards';
import DomainSummaryBlock from '../../components/agriculture/DomainSummaryBlock';
import EvidenceSection from '../../components/agriculture/EvidenceSection';
import LandCoverSharesSection from '../../components/agriculture/LandCoverSharesSection';
import LimitationsBanner from '../../components/agriculture/LimitationsBanner';
import MetricKpiGrid from '../../components/agriculture/MetricKpiGrid';
import SeasonTimeline from '../../components/agriculture/SeasonTimeline';
import AspectDial from '../../components/agriculture/AspectDial';
import SpatialSection from '../../components/agriculture/SpatialSection';
import { formatPersianDateRange, toPersianDigits } from '../../components/agriculture/persianDate';
import TemporalSection from '../../components/agriculture/TemporalSection';
import ValidationSection from '../../components/agriculture/ValidationSection';
import YearComparisonSection from '../../components/agriculture/YearComparisonSection';
import { ndviProfileOf } from '../../components/agriculture/yearComparison';
import Historical10YearSection from '../../components/agriculture/Historical10YearSection';
import OrchardHeatmapSwipeSection from '../../components/agriculture/OrchardHeatmapSwipeSection';
import SoilIntelligenceSection from '../../components/agriculture/SoilIntelligenceSection';
import type { SpatialMetricType } from '../../types';

const DOMAIN_SWIPE_CONFIG: Record<
  string,
  {
    initialMetric: SpatialMetricType;
    allowedMetrics: SpatialMetricType[];
    titleFa: string;
  }
> = {
  vegetation: {
    initialMetric: 'ndvi',
    allowedMetrics: ['ndvi', 'ndre', 'msi'],
    titleFa: 'مقایسه کشویی: تصویر باغ ↔ نقشه حرارتی پوشش گیاهی (NDVI / NDRE)',
  },
  water: {
    initialMetric: 'ndmi',
    allowedMetrics: ['ndmi', 'msi'],
    titleFa: 'مقایسه کشویی: تصویر باغ ↔ نقشه حرارتی رطوبت (NDMI)',
  },
  'stress-irrigation': {
    initialMetric: 'msi',
    allowedMetrics: ['msi', 'ndmi', 'lst_day'],
    titleFa: 'مقایسه کشویی: تصویر باغ ↔ نقشه حرارتی تنش کانوپی و دما (MSI / LST)',
  },
  thermal: {
    initialMetric: 'lst_day',
    allowedMetrics: ['lst_day'],
    titleFa: 'مقایسه کشویی: تصویر باغ ↔ نقشه حرارتی دمای سطح زمین (LST)',
  },
  history: {
    initialMetric: 'ndvi',
    allowedMetrics: ['ndvi', 'ndmi', 'ndre', 'msi', 'lst_day', 'sar_vh'],
    titleFa: 'مقایسه کشویی: تصویر باغ ↔ شواهد مکانی چندمنبعی تاریخی',
  },
  soil: {
    initialMetric: 'soil_moisture',
    allowedMetrics: [
      'soil_moisture',
      'soil_soc',
      'soil_ph',
      'soil_clay',
      'soil_sand',
      'soil_cec',
      'soil_nitrogen',
    ],
    titleFa: 'مقایسه کشویی: تصویر باغ ↔ لایه‌های رستری خاک (رطوبت، کربن آلی، pH، رس)',
  },
};

interface DomainPageProps {
  pageKey: string;
}

/**
 * Independent domain view (Prompt 2). Owns its own location/date/geometry
 * inputs and runs its own analysis through the shared
 * POST /agriculture/analysis endpoint with this page's locked
 * `apiDomains` — never reads the hub result, never Legacy.
 * Rendered metric keys are exactly the locked per-domain lists in
 * domainPages.ts (backend registry contract); unavailable metrics render
 * as unavailable, never as invented values.
 */
export default function DomainPage({ pageKey }: DomainPageProps) {
  const config = DOMAIN_PAGE_CONFIGS[pageKey];

  const [pageResult, setPageResult] = useState<AgriculturalAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pageLastRequest, setPageLastRequest] =
    useState<AgricultureAnalysisRequest | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [previewGeometry, setPreviewGeometry] = useState<
    AgricultureGeometry | undefined
  >(undefined);
  const [previewCenter, setPreviewCenter] = useState<[number, number]>([55.0, 32.0]);
  const [confirmedPolygon, setConfirmedPolygon] = useState<GeoJSON.Polygon | null>(null);
  const [isPolygonConfirmed, setIsPolygonConfirmed] = useState<boolean>(false);
  const [activeGeometryMode, setActiveGeometryMode] = useState<GeometryInputMode>('draw');

  const runAnalysis = useCallback(async (request: AgricultureAnalysisRequest) => {
    setLoading(true);
    setError(null);
    try {
      const raw: unknown = await agricultureApi.analyze(request);
      const normalized = normalizeResponse(raw);
      if (!normalized) {
        setPageResult(null);
        setPageLastRequest(null);
        setError('پاسخ تحلیل نامعتبر — Invalid analysis response');
        return;
      }
      setPageResult(normalized);
      setPageLastRequest(request);
    } catch (err) {
      setPageResult(null);
      setPageLastRequest(null);
      setError(err instanceof Error ? err.message : 'خطا در تحلیل');
    } finally {
      setLoading(false);
    }
  }, []);

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

  let parentContext: ReturnType<typeof useAgricultureContext> | null = null;
  try {
    parentContext = useAgricultureContext();
  } catch {
    parentContext = null;
  }

  const isSavedReport = Boolean(parentContext?.savedAnalysisId);
  const result = isSavedReport
    ? (parentContext?.result ?? null)
    : (pageResult ?? parentContext?.result ?? null);
  const lastRequest = isSavedReport
    ? (parentContext?.lastRequest ?? null)
    : (pageLastRequest ?? parentContext?.lastRequest ?? null);

  const isContextLoading = Boolean(parentContext?.loading);
  const isPageLoading = loading;
  const isAnyLoading = isContextLoading || isPageLoading;
  const activeError = parentContext?.error || formError || error;

  const [showManualForm, setShowManualForm] = useState<boolean>(false);
  const isFormVisible = showManualForm || (!isSavedReport && !result && !isContextLoading && !loading);

  if (!config) return null;
  const meta = domainMetaFor(config.metaKey);

  const hasDomainData = result
    ? config.pageKey === 'soil' ||
      (result.domains_with_data ?? []).some((k) => config.bundleKeys.includes(k)) ||
      config.bundleKeys.some((k) => {
        const bundle = result.evidence_bundles?.[k];
        const summary = result.domain_summaries?.[k];
        if (summary && ((summary.statements && summary.statements.length > 0) || (typeof summary.statement_count === 'number' && summary.statement_count > 0))) return true;
        return (
          bundle &&
          Array.isArray(bundle.items) &&
          bundle.items.some(
            (item) =>
              item &&
              item.is_usable === true &&
              item.status !== 'unavailable' &&
              typeof item.value === 'number' &&
              Number.isFinite(item.value),
          )
        );
      })
    : false;

  const bundles: Record<string, EvidenceBundleResponse> = result
    ? config.bundleKeys.reduce<Record<string, EvidenceBundleResponse>>(
        (acc, key) => {
          const bundle = result.evidence_bundles?.[key];
          if (bundle) acc[key] = bundle;
          return acc;
        },
        {},
      )
    : {};
  const requested =
    lastRequest?.domains && lastRequest.domains.length > 0
      ? lastRequest.domains.join(', ')
      : 'all domains';

  return (
    <div>
      <PageHeader metaIcon={meta.icon} metaFa={meta.labelFa} metaEn={meta.label} />

      {/* Persistent History Retrieval Banner */}
      {isSavedReport && result && (
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
              <strong>گزارش بازیابی‌شده از تاریخچه دائمی:</strong> شاخص‌های حوزه «{meta.labelFa}» از دیتابیس بارگذاری شده و مجدداً محاسبه نمی‌شوند (بدون اجرای مجدد GEE)، اما تایل‌های نقشه هنگام مشاهده به‌صورت پویا بازتولید می‌گردند.
            </span>
          </div>
          <div className="d-flex align-items-center gap-2">
            <span className="badge badge-good" style={{ padding: '4px 8px' }}>
              محاسبات دیتابیس (بدون اجرای مجدد GEE) • بازتولید پویای تایل‌های نقشه
            </span>
            <code style={{ fontSize: '0.78rem', color: '#2e7d32' }}>
              {toPersianDigits(parentContext?.savedAnalysisId?.slice(0, 8) || '')}
            </code>
          </div>
        </div>
      )}

      {activeError && (
        <div className="error-banner mb-3" data-testid="domain-error-banner">
          <span>⚠️</span>
          <span>{activeError}</span>
        </div>
      )}

      {isSavedReport && (
        <div className="d-flex justify-content-end mb-2">
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={() => setShowManualForm((prev) => !prev)}
            data-testid="toggle-manual-form-btn"
            style={{ fontSize: '0.8rem' }}
          >
            {showManualForm ? 'بستن فرم تحلیل جدید' : '✏️ اجرای تحلیل مستقل جدید برای این حوزه'}
          </button>
        </div>
      )}

      {isFormVisible && (
        <div className="grid-2">
          <AnalysisRequestForm
            loading={loading}
            showDomainSelection={false}
            fixedDomains={config.apiDomains}
            onSubmit={(request) => void runAnalysis(request)}
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
      )}

      <div className="card mb-3">
        <div className="card-body">
          <span className="text-muted">حوزه‌های درخواستی این صفحه — Requested domains: </span>
          <strong>{config.apiDomains.join(', ')}</strong>
        </div>
      </div>

      <div className="mt-2">
        <DomainNavCards />
      </div>

      {isAnyLoading && (
        <div className="card mt-3 mb-3 p-4 text-center" data-testid="domain-loading">
          <div className="spinner mx-auto mb-2" />
          <div className="text-primary font-bold">در حال بارگذاری اطلاعات شاخص...</div>
        </div>
      )}

      {!result && !isAnyLoading && (
        <div className="card" data-testid="domain-empty-state">
          <div className="card-body">
            <div className="empty-state">
              <div className="empty-state-icon">{meta.icon}</div>
              <div className="empty-state-title">هنوز تحلیلی برای این حوزه اجرا نشده است</div>
              <div className="empty-state-desc">
                برای مشاهده اطلاعات، یا از صفحه «گزارش‌ها» یک تحلیل ذخیره‌شده را انتخاب کنید یا فرم بالا را جهت اجرای تحلیل جدید تکمیل فرمایید.
              </div>
            </div>
          </div>
        </div>
      )}

      {result && !isAnyLoading && !hasDomainData && (
        <div className="card mb-3" data-testid="domain-unavailable-card">
          <div className="card-header">
            <span className="card-title">⚠️ وضعیت شواهد ماهواره‌ای حوزه {meta.labelFa}</span>
          </div>
          <div className="card-body">
            <div className="empty-state">
              <div className="empty-state-icon">{meta.icon}</div>
              <div className="empty-state-title">
                شواهد ماهواره‌ای برای حوزه «{meta.labelFa}» در این گزارش موجود نیست
              </div>
              <div className="empty-state-desc" style={{ maxWidth: 540, margin: '8px auto', color: '#607d8b', lineHeight: 1.7 }}>
                در زمان اجرای این تحلیل، این حوزه در فهرست دامنه‌های درخواستی نبوده یا شواهد ماهواره‌ای معتبری برای آن در بازه زمانی گزارش ثبت نشده است. این وضعیت به منزله مقدار عددی صفر یا نامطلوب بودن وضعیت باغ نیست.
              </div>
            </div>
          </div>
        </div>
      )}

      {result && !isAnyLoading && hasDomainData && (
        <>
          <div className="card mb-3">
            <div className="card-body">
              <div className="form-row" style={{ flexWrap: 'wrap', gap: '16px' }}>
                {result.time_start && (
                  <div>
                    <span className="text-muted">دوره زمانی: </span>
                    <strong data-testid="domain-header-period">
                      {formatPersianDateRange(result.time_start, result.time_end)}
                    </strong>
                  </div>
                )}
                <div>
                  <span className="text-muted">حوزه‌های درخواستی: </span>
                  <strong>{requested}</strong>
                </div>
              </div>
            </div>
          </div>

          {config.sections.map((section) => {
            if (section.kind === 'timeline') {
              return (
                <SeasonTimeline
                  key={section.id}
                  title={section.title}
                  titleFa={section.titleFa}
                  metricKeys={section.metricKeys}
                  bundles={bundles}
                />
              );
            }
            if (section.kind === 'aspect') {
              return (
                <AspectDial
                  key={section.id}
                  title={section.title}
                  titleFa={section.titleFa}
                  metricKey={section.metricKeys[0] ?? 'aspect'}
                  bundles={bundles}
                />
              );
            }
            if (section.kind === 'temporal') {
              return (
                <TemporalSection
                  key={section.id}
                  title={section.title}
                  titleFa={section.titleFa}
                  entries={section.temporalSeries ?? []}
                  bundles={bundles}
                  temporal={result.temporal ?? null}
                />
              );
            }
            if (section.kind === 'year-comparison') {
              return (
                <YearComparisonSection
                  key={section.id}
                  title={section.title}
                  titleFa={section.titleFa}
                  profile={ndviProfileOf(result.temporal ?? null)}
                  temporal={result.temporal ?? null}
                />
              );
            }
            if (section.kind === 'landcover-shares') {
              const found = findEvidenceItem(
                bundles,
                section.metricKeys[0] ?? 'land_cover_class',
              );
              return (
                <LandCoverSharesSection
                  key={section.id}
                  title={section.title}
                  titleFa={section.titleFa}
                  note={section.note}
                  item={found ? found.item : null}
                />
              );
            }
            return (
              <MetricKpiGrid
                key={section.id}
                title={section.title}
                titleFa={section.titleFa}
                metricKeys={section.metricKeys}
                bundles={bundles}
                note={section.note}
              />
            );
          })}

          {/* Soil Intelligence (Phase P-AGRI-SOIL) */}
          {pageKey === 'soil' ? (
            <SoilIntelligenceSection
              initialSoilData={result.soil_intelligence ?? null}
              geometry={lastRequest?.geometry ?? result.geometry ?? previewGeometry ?? null}
              startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
              endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
              cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
              isSavedReport={isSavedReport}
            />
          ) : (
            <>
              {/* 10-Year Same-Period Historical Comparison (Phase P-AGRI-HIST-10Y) */}
              <Historical10YearSection
                geometry={lastRequest?.geometry ?? result.geometry ?? previewGeometry ?? null}
                startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
                endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
                cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
                domain={pageKey === 'stress-irrigation' ? 'stress' : pageKey === 'land-crop' ? 'vegetation' : pageKey}
                disableAutoFetch={isSavedReport}
              />

              {/* Interactive Current Orchard ↔ Evidence Heatmap Swipe (Phase P-AGRI-MAP-SWIPE) */}
              {DOMAIN_SWIPE_CONFIG[pageKey] && (
                <OrchardHeatmapSwipeSection
                  geometry={lastRequest?.geometry ?? result.geometry ?? previewGeometry ?? null}
                  startDate={lastRequest?.start_date ?? result.time_start ?? '2025-06-01'}
                  endDate={lastRequest?.end_date ?? result.time_end ?? '2025-09-01'}
                  cloudMaxPercent={lastRequest?.cloud_max_percent ?? 20}
                  initialMetric={DOMAIN_SWIPE_CONFIG[pageKey].initialMetric}
                  allowedMetrics={DOMAIN_SWIPE_CONFIG[pageKey].allowedMetrics}
                  titleFa={DOMAIN_SWIPE_CONFIG[pageKey].titleFa}
                  disableAutoFetch={isSavedReport}
                />
              )}
            </>
          )}

          <EvidenceSection
            bundles={bundles}
            domainSummaries={Object.fromEntries(
              config.bundleKeys
                .map((domainKey) => [domainKey, result.domain_summaries?.[domainKey]] as const)
                .filter(([, summary]) => summary !== null && summary !== undefined),
            )}
            crossDomainStatements={result.cross_domain_statements ?? []}
            temporal={result.temporal ?? null}
            spatial={result.spatial ?? null}
            rawResponse={result}
          />

          <ValidationSection validation={result.validation ?? null} />

          <SpatialSection spatial={result.spatial ?? null} />

          <div className="card mb-3">
            <div className="card-header">
              <span className="card-title">📊 خلاصه حوزه‌ها — Domain Summaries</span>
            </div>            <div className="card-body" style={{ padding: 0 }}>
              {config.bundleKeys.map((domainKey) => (
                <DomainSummaryBlock
                  key={domainKey}
                  domainKey={domainKey}
                  summary={result.domain_summaries?.[domainKey]}
                  bundles={result.evidence_bundles ?? {}}
                />
              ))}
            </div>
          </div>

          <LimitationsBanner limitations={result.limitations ?? []} />

          {asArray(result.cross_domain_statements).length > 0 && (
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>
              Cross-domain synthesis is available on the{' '}
              <Link to="/agriculture">hub page</Link>.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PageHeader({
  metaIcon,
  metaFa,
  metaEn,
}: {
  metaIcon: string;
  metaFa: string;
  metaEn: string;
}) {
  return (
    <div className="page-header">
      <h2 className="page-title">
        {metaIcon} {metaFa}
      </h2>
      <p className="page-subtitle">{metaEn} — Independent domain analysis</p>
    </div>
  );
}
