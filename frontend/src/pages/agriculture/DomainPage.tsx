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
import { DOMAIN_PAGE_CONFIGS } from '../../components/agriculture/domainPages';
import {
  asArray,
  domainMetaFor,
  findEvidenceItem,
  normalizeResponse,
} from '../../components/agriculture/parse';
import AnalysisRequestForm from '../../components/agriculture/AnalysisRequestForm';
import DomainNavCards from '../../components/agriculture/DomainNavCards';
import DomainSummaryBlock from '../../components/agriculture/DomainSummaryBlock';
import EvidenceSection from '../../components/agriculture/EvidenceSection';
import LandCoverSharesSection from '../../components/agriculture/LandCoverSharesSection';
import LimitationsBanner from '../../components/agriculture/LimitationsBanner';
import MetricKpiGrid from '../../components/agriculture/MetricKpiGrid';
import SeasonTimeline from '../../components/agriculture/SeasonTimeline';
import AspectDial from '../../components/agriculture/AspectDial';
import SpatialSection from '../../components/agriculture/SpatialSection';
import TemporalSection from '../../components/agriculture/TemporalSection';
import ValidationSection from '../../components/agriculture/ValidationSection';
import YearComparisonSection from '../../components/agriculture/YearComparisonSection';
import { ndviProfileOf } from '../../components/agriculture/yearComparison';

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

  const [result, setResult] = useState<AgriculturalAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRequest, setLastRequest] =
    useState<AgricultureAnalysisRequest | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [previewGeometry, setPreviewGeometry] = useState<
    AgricultureGeometry | undefined
  >(undefined);
  const [previewCenter, setPreviewCenter] = useState<[number, number]>([55.0, 32.0]);

  const runAnalysis = useCallback(async (request: AgricultureAnalysisRequest) => {
    setLoading(true);
    setError(null);
    try {
      const raw: unknown = await agricultureApi.analyze(request);
      const normalized = normalizeResponse(raw);
      if (!normalized) {
        setResult(null);
        setLastRequest(null);
        setError('پاسخ تحلیل نامعتبر — Invalid analysis response');
        return;
      }
      setResult(normalized);
      setLastRequest(request);
    } catch (err) {
      setResult(null);
      setLastRequest(null);
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

  if (!config) return null;
  const meta = domainMetaFor(config.metaKey);
  const bannerError = formError || error;

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

      {bannerError && (
        <div className="error-banner">
          <span>⚠️</span>
          <span>{bannerError}</span>
        </div>
      )}

      <div className="grid-2">
        <AnalysisRequestForm
          loading={loading}
          showDomainSelection={false}
          fixedDomains={config.apiDomains}
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

      <div className="card mb-3">
        <div className="card-body">
          <span className="text-muted">حوزه‌های درخواستی این صفحه — Requested domains: </span>
          <strong>{config.apiDomains.join(', ')}</strong>
        </div>
      </div>

      <div className="mt-2">
        <DomainNavCards />
      </div>

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <span>در حال تحلیل...</span>
        </div>
      )}

      {!result && !loading && (
        <div className="card">
          <div className="card-body">
            <div className="empty-state">
              <div className="empty-state-icon">{meta.icon}</div>
              <div className="empty-state-title">هنوز تحلیلی برای این حوزه اجرا نشده است</div>
              <div className="empty-state-desc">
                مکان و بازه زمانی را بالا تنظیم کنید و تحلیل همین حوزه را اجرا کنید.
              </div>
            </div>
          </div>
        </div>
      )}

      {result && !loading && (
        <>
          <div className="card mb-3">
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
