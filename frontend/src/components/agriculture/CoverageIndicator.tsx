import React, { useState, useMemo } from 'react';
import type { AgriculturalAnalysisResponse } from '../../types/index.ts';
import {
  getCoverageCounts,
  formatCoveragePrimaryFa,
  formatCoverageSecondaryFa,
  formatPercentageFa,
  toPersianDigits,
  partitionMetricsForInventory,
} from './coverageUtils.ts';

interface CoverageIndicatorProps {
  result: AgriculturalAnalysisResponse;
}

export const CoverageIndicator: React.FC<CoverageIndicatorProps> = ({ result }) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'valid' | 'coarse' | 'unavailable' | 'domains'>('valid');

  const coverage = useMemo(() => getCoverageCounts(result), [result]);
  const inventory = useMemo(
    () => partitionMetricsForInventory(result.evidence_bundles || {}),
    [result.evidence_bundles],
  );

  const { valid, coarse_context: coarse, unavailable, total, valid_ratio } = coverage;
  const validPercent = total > 0 ? (valid / total) * 100 : 0;
  const coarsePercent = total > 0 ? (coarse / total) * 100 : 0;
  const unavailablePercent = total > 0 ? (unavailable / total) * 100 : 0;

  return (
    <div
      className="card mb-3 coverage-indicator-card"
      data-testid="coverage-indicator-card"
      style={{
        border: '1px solid #cfd8dc',
        borderRadius: '8px',
        background: '#ffffff',
        boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
      }}
    >
      <div
        className="card-body"
        style={{ padding: '16px 20px' }}
      >
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
          <div>
            {/* Primary line: large, prominent */}
            <div
              className="coverage-primary-line"
              data-testid="coverage-primary-line"
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                color: '#263238',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <span style={{ fontSize: '1.4rem' }}>📊</span>
              <span>{formatCoveragePrimaryFa(valid, total)}</span>
              <span
                className="badge"
                data-testid="coverage-ratio-badge"
                style={{
                  fontSize: '0.82rem',
                  fontWeight: 600,
                  backgroundColor: '#eceff1',
                  color: '#37474f',
                  border: '1px solid #b0bec5',
                  padding: '3px 8px',
                  borderRadius: '12px',
                }}
              >
                {formatPercentageFa(valid_ratio)} پوشش مزرعه
              </span>
            </div>

            {/* Secondary line: regional context note */}
            <div
              className="coverage-secondary-line"
              data-testid="coverage-secondary-line"
              style={{
                fontSize: '0.92rem',
                color: '#546e7a',
                marginTop: '4px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <span style={{ fontWeight: 600, color: '#455a64' }}>
                {formatCoverageSecondaryFa(coarse)}
              </span>
              <span style={{ fontSize: '0.8rem', color: '#78909c' }}>
                (داده‌های اقلیمی و رطوبتی در مقیاس منطقه‌ای که مستقلاً ارزیابی شده و با ارقام مزرعه جمع نمی‌شوند)
              </span>
            </div>
          </div>

          {/* Action button to expand details */}
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={() => setIsExpanded(!isExpanded)}
            data-testid="toggle-coverage-details-btn"
            style={{
              fontSize: '0.85rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '6px 14px',
            }}
          >
            {isExpanded ? 'بستن تفکیک شاخص‌ها ▲' : 'مشاهده تفکیک شاخص‌ها و وضعیت داده‌ها ▼'}
          </button>
        </div>

        {/* Proportional Segmented Progress Bar */}
        <div
          className="coverage-progress-bar-container"
          style={{
            height: '10px',
            borderRadius: '5px',
            backgroundColor: '#eceff1',
            display: 'flex',
            overflow: 'hidden',
            marginTop: '12px',
          }}
          title={`معتبر: ${toPersianDigits(valid)} | زمینه منطقه‌ای: ${toPersianDigits(coarse)} | در دسترس نبوده: ${toPersianDigits(unavailable)}`}
        >
          {validPercent > 0 && (
            <div
              data-testid="coverage-bar-valid"
              style={{
                width: `${validPercent}%`,
                backgroundColor: '#43a047',
                transition: 'width 0.3s ease',
              }}
            />
          )}
          {coarsePercent > 0 && (
            <div
              data-testid="coverage-bar-coarse"
              style={{
                width: `${coarsePercent}%`,
                backgroundColor: '#fb8c00',
                transition: 'width 0.3s ease',
              }}
            />
          )}
          {unavailablePercent > 0 && (
            <div
              data-testid="coverage-bar-unavailable"
              style={{
                width: `${unavailablePercent}%`,
                backgroundColor: '#cfd8dc',
                transition: 'width 0.3s ease',
              }}
            />
          )}
        </div>

        {/* Expandable Drawer / Inspection Panel */}
        {isExpanded && (
          <div
            className="coverage-details-panel mt-3 pt-3"
            data-testid="coverage-details-panel"
            style={{ borderTop: '1px solid #e0e0e0' }}
          >
            {/* Tab navigation */}
            <div className="d-flex gap-2 mb-3 flex-wrap" role="tablist">
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'valid' ? 'btn-success' : 'btn-outline-secondary'}`}
                onClick={() => setActiveTab('valid')}
                data-testid="tab-valid-metrics"
                style={{ fontSize: '0.82rem' }}
              >
                🌿 شاخص‌های معتبر مزرعه ({toPersianDigits(valid)})
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'coarse' ? 'btn-warning' : 'btn-outline-secondary'}`}
                onClick={() => setActiveTab('coarse')}
                data-testid="tab-coarse-metrics"
                style={{ fontSize: '0.82rem' }}
              >
                🌐 زمینه منطقه‌ای ({toPersianDigits(coarse)})
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'unavailable' ? 'btn-secondary' : 'btn-outline-secondary'}`}
                onClick={() => setActiveTab('unavailable')}
                data-testid="tab-unavailable-metrics"
                style={{ fontSize: '0.82rem' }}
              >
                ⚪ در دسترس نبوده ({toPersianDigits(unavailable)})
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'domains' ? 'btn-info' : 'btn-outline-secondary'}`}
                onClick={() => setActiveTab('domains')}
                data-testid="tab-domain-breakdown"
                style={{ fontSize: '0.82rem' }}
              >
                📋 تفکیک بر اساس دامین
              </button>
            </div>

            {/* Tab Content: Valid Field Metrics */}
            {activeTab === 'valid' && (
              <div data-testid="coverage-valid-list">
                <div className="text-muted mb-2" style={{ fontSize: '0.8rem' }}>
                  این شاخص‌ها دارای وضوح مکانی مناسب (≤ ۳۰ متر یا متناسب با ابعاد قطعه) بوده و مستقیماً وضعیت گیاه، خاک یا سطح مزرعه را بازتاب می‌دهند.
                </div>
                {inventory.validMetrics.length === 0 ? (
                  <div className="alert alert-light text-muted" style={{ fontSize: '0.85rem' }}>
                    هیچ شاخص مقیاس مزرعه با دادهٔ معتبر در این بازه زمانی یافت نشد.
                  </div>
                ) : (
                  <div className="table-responsive" style={{ maxHeight: '280px', overflowY: 'auto' }}>
                    <table className="table table-sm table-striped" style={{ fontSize: '0.8rem' }}>
                      <thead>
                        <tr>
                          <th>شناسه</th>
                          <th>عنوان شاخص</th>
                          <th>دامین</th>
                          <th>منبع ماهواره‌ای</th>
                          <th>مقدار مشاهده‌شده</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inventory.validMetrics.map((m) => (
                          <tr key={m.metricKey}>
                            <td><code>{m.metricKey}</code></td>
                            <td><strong>{m.displayName}</strong></td>
                            <td>{m.domainName}</td>
                            <td>{m.sourceDataset}</td>
                            <td style={{ direction: 'ltr', textAlign: 'right' }}>{m.valueDisplay}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Tab Content: Regional Coarse Context */}
            {activeTab === 'coarse' && (
              <div data-testid="coverage-coarse-list">
                <div
                  className="alert alert-warning mb-2"
                  style={{
                    backgroundColor: '#fff8e1',
                    border: '1px solid #ffe082',
                    color: '#6d4c41',
                    fontSize: '0.82rem',
                    padding: '8px 12px',
                  }}
                >
                  <strong>هشدار شفافیت علمی:</strong> این داده‌ها واقعی و معتبرند، اما وسعت پیکسل آنها (مثلاً ۱۱ کیلومتر ERA5 یا ۹ کیلومتر SMAP) بسیار بزرگ‌تر از مساحت باغ است. این ارقام صرفاً به عنوان بافت اقلیمی و رطوبتی منطقه ارائه شده و نباید برای پهنه‌بندی داخل مزرعه یا ادعاهای قطعی استفاده شوند.
                </div>
                {inventory.coarseMetrics.length === 0 ? (
                  <div className="alert alert-light text-muted" style={{ fontSize: '0.85rem' }}>
                    شاخص زمینه منطقه‌ای در این دامین‌ها ثبت نشده است.
                  </div>
                ) : (
                  <div className="table-responsive" style={{ maxHeight: '280px', overflowY: 'auto' }}>
                    <table className="table table-sm table-striped" style={{ fontSize: '0.8rem' }}>
                      <thead>
                        <tr>
                          <th>شناسه</th>
                          <th>عنوان شاخص</th>
                          <th>منبع</th>
                          <th>وضوح و بافت</th>
                          <th>مقدار</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inventory.coarseMetrics.map((m) => (
                          <tr key={m.metricKey}>
                            <td><code>{m.metricKey}</code></td>
                            <td><strong>{m.displayName}</strong></td>
                            <td>{m.sourceDataset}</td>
                            <td>
                              <span
                                className="badge"
                                data-testid="coarse-context-badge"
                                style={{
                                  backgroundColor: '#fff3e0',
                                  color: '#e65100',
                                  border: '1px solid #ffcc80',
                                  fontSize: '0.74rem',
                                }}
                              >
                                {m.resolutionFa || 'وضوح منطقه‌ای'}
                              </span>
                              {m.supportDescription && (
                                <div style={{ fontSize: '0.72rem', color: '#6d4c41', marginTop: '2px' }}>
                                  {m.supportDescription}
                                </div>
                              )}
                            </td>
                            <td style={{ direction: 'ltr', textAlign: 'right' }}>{m.valueDisplay}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Tab Content: Unavailable Metrics */}
            {activeTab === 'unavailable' && (
              <div data-testid="coverage-unavailable-list">
                <div className="text-muted mb-2" style={{ fontSize: '0.8rem' }}>
                  شاخص‌هایی که به دلیل پوشش ابری، عدم عبور ماهواره در بازه انتخابی، یا نیاز به نمونه‌برداری میدانی/آزمایشگاهی گزارش نشده‌اند:
                </div>
                {inventory.unavailableMetrics.length === 0 ? (
                  <div className="alert alert-success text-muted" style={{ fontSize: '0.85rem' }}>
                    همه شاخص‌های این حوزه با موفقیت دریافت و پردازش شده‌اند.
                  </div>
                ) : (
                  <div className="table-responsive" style={{ maxHeight: '280px', overflowY: 'auto' }}>
                    <table className="table table-sm table-striped" style={{ fontSize: '0.8rem' }}>
                      <thead>
                        <tr>
                          <th>شناسه</th>
                          <th>عنوان شاخص</th>
                          <th>دامین</th>
                          <th>علت عدم دسترسی (صادقانه)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inventory.unavailableMetrics.map((m) => (
                          <tr key={m.metricKey}>
                            <td><code>{m.metricKey}</code></td>
                            <td>{m.displayName}</td>
                            <td>{m.domainName}</td>
                            <td style={{ color: '#78909c' }}>
                              {m.unavailableReason || m.unavailableMessage || 'عدم پوشش سنسور در بازه انتخابی'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* Tab Content: Domain Breakdown */}
            {activeTab === 'domains' && (
              <div data-testid="coverage-domain-breakdown">
                <div className="table-responsive" style={{ maxHeight: '280px', overflowY: 'auto' }}>
                  <table className="table table-sm table-bordered" style={{ fontSize: '0.8rem' }}>
                    <thead>
                      <tr style={{ backgroundColor: '#f5f5f5' }}>
                        <th>دامین (حوزه)</th>
                        <th>معتبر مزرعه (N)</th>
                        <th>زمینه منطقه‌ای (K)</th>
                        <th>در دسترس نبوده (U)</th>
                        <th>مجموع قابل اعمال (M)</th>
                        <th>درصد پوشش معتبر</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(coverage.by_domain || {}).map(([dName, dCov]) => (
                        <tr key={dName}>
                          <td><strong>{dName}</strong></td>
                          <td style={{ color: '#2e7d32', fontWeight: 600 }}>{toPersianDigits(dCov.valid)}</td>
                          <td style={{ color: '#ef6c00', fontWeight: 600 }}>{toPersianDigits(dCov.coarse_context)}</td>
                          <td style={{ color: '#78909c' }}>{toPersianDigits(dCov.unavailable)}</td>
                          <td><strong>{toPersianDigits(dCov.total)}</strong></td>
                          <td>
                            <span
                              className="badge"
                              style={{
                                backgroundColor: dCov.valid_ratio >= 0.7 ? '#e8f5e9' : '#f5f5f5',
                                color: dCov.valid_ratio >= 0.7 ? '#2e7d32' : '#455a64',
                              }}
                            >
                              {formatPercentageFa(dCov.valid_ratio)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
