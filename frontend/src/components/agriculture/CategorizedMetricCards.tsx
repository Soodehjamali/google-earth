import { useState } from 'react';
import type {
  EvidenceBundleResponse,
} from '../../types/index.ts';
import { findEvidenceItem } from './parse.ts';
import { supportInfoOf } from './support.ts';
import {
  METRIC_CATEGORIES,
  EXTENDED_METRIC_CATEGORIES,
  evaluateMetricState,
} from './categorizedMetrics.ts';
import FormattedNumber from '../common/FormattedNumber.tsx';

interface CategorizedMetricCardsProps {
  bundles: Record<string, EvidenceBundleResponse>;
}

export default function CategorizedMetricCards({
  bundles,
}: CategorizedMetricCardsProps) {
  const [activeCategory, setActiveCategory] = useState<string>('all');

  const allCategories = [...METRIC_CATEGORIES, ...EXTENDED_METRIC_CATEGORIES];

  const visibleCategories =
    activeCategory === 'all'
      ? allCategories
      : allCategories.filter((c) => c.key === activeCategory);

  return (
    <section
      aria-label="Categorized agricultural metrics"
      className="categorized-metrics-section mb-4"
      data-testid="categorized-metrics"
    >
      <div className="card">
        <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div>
            <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 700 }}>
              📊 کارت‌های شاخص‌های کشاورزی بر پایه دسته‌بندی علمی
            </span>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 2 }}>
              نمایش داده‌های واقعی ماهواره‌ای بدون تعمیم نامعتبر به سلامت یا بیماری محصول
            </div>
          </div>

          {/* Category Filter Tabs */}
          <div
            className="flex gap-1"
            style={{ flexWrap: 'wrap', alignItems: 'center' }}
            role="tablist"
            aria-label="فیلتر دسته‌بندی شاخص‌ها"
          >
            <button
              type="button"
              className={`button button-sm ${activeCategory === 'all' ? 'button-primary' : 'button-outline'}`}
              onClick={() => setActiveCategory('all')}
              role="tab"
              aria-selected={activeCategory === 'all'}
            >
              همه شاخص‌ها (All)
            </button>
            {allCategories.map((cat) => (
              <button
                key={cat.key}
                type="button"
                className={`button button-sm ${activeCategory === cat.key ? 'button-primary' : 'button-outline'}`}
                onClick={() => setActiveCategory(cat.key)}
                role="tab"
                aria-selected={activeCategory === cat.key}
              >
                {cat.icon} {cat.titleFa}
              </button>
            ))}
          </div>
        </div>

        <div className="card-body">
          {visibleCategories.map((cat) => (
            <div key={cat.key} className="mb-4" style={{ borderBottom: '1px solid var(--border-color, #e0e0e0)', paddingBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                <div>
                  <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span>{cat.icon}</span>
                    <span>{cat.titleFa}</span>
                    <span className="text-muted" style={{ fontSize: '0.8rem', fontWeight: 400 }}>
                      — {cat.title}
                    </span>
                  </h4>
                  <div className="text-muted" style={{ fontSize: '0.78rem', marginTop: 3 }}>
                    {cat.descriptionFa}
                  </div>
                </div>
              </div>

              {/* Thermal Special Caution Alert */}
              {cat.key === 'thermal' && (
                <div
                  className="mb-3"
                  style={{
                    background: '#fff9c4',
                    border: '1px solid #fbc02d',
                    borderRadius: 6,
                    padding: '8px 12px',
                    fontSize: '0.82rem',
                    color: '#5d4037',
                    lineHeight: 1.5,
                  }}
                  data-testid="thermal-lst-caution"
                >
                  <strong>⚠️ تذکر علمی دمای سطح زمین (LST Caution):</strong> مقادیر دمای ارائه‌شده مربوط به
                  <strong> دمای تابشی فیزیکی پوسته سطح زمین (Land Surface Temperature) </strong> است و به هیچ عنوان
                  به عنوان «دمای فیزیولوژیک اندام گیاهی» یا «تأیید تنش گرمایی بوته» تعبیر نمی‌شود.
                </div>
              )}

              {/* Metric Cards Grid */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                  gap: 12,
                }}
              >
                {cat.metrics.map((metricDef) => {
                  const found = findEvidenceItem(bundles, metricDef.key);
                  const item = found?.item;
                  const evaluation = evaluateMetricState(item, metricDef);
                  const support = supportInfoOf(item?.provenance);
                  const interp = evaluation.interpretation;

                  return (
                    <div
                      key={metricDef.key}
                      className="card"
                      style={{
                        padding: 12,
                        background:
                          evaluation.state === 'insufficient'
                            ? 'var(--bg-danger-subtle, #fdf7f7)'
                            : evaluation.state === 'limited'
                              ? 'var(--bg-warning-subtle, #fffdf5)'
                              : 'var(--card-bg, #ffffff)',
                        border:
                          evaluation.state === 'insufficient'
                            ? '1px solid #ffcdd2'
                            : evaluation.state === 'limited'
                              ? '1px solid #ffe082'
                              : '1px solid var(--border-color, #e0e0e0)',
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'space-between',
                      }}
                      data-testid={`metric-card-${metricDef.key}`}
                    >
                      <div>
                        {/* Header & Status Badges */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6, marginBottom: 6 }}>
                          <div>
                            <div style={{ fontWeight: 700, fontSize: '0.88rem' }}>
                              {metricDef.nameFa}
                            </div>
                            <div className="text-muted" style={{ fontSize: '0.72rem', direction: 'ltr', textAlign: 'right' }}>
                              {metricDef.key.toUpperCase()}
                            </div>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
                            <span
                              className={`badge ${evaluation.badgeClass}`}
                              style={{ fontSize: '0.7rem', whiteSpace: 'nowrap' }}
                            >
                              {evaluation.badgeLabel}
                            </span>
                            {interp && evaluation.state === 'available' && (
                              <span
                                style={{
                                  fontSize: '0.66rem',
                                  padding: '2px 5px',
                                  borderRadius: 4,
                                  background: interp.statusClass === 'good' ? '#e8f5e9' : interp.statusClass === 'warning' ? '#fff8e1' : '#f5f5f5',
                                  color: interp.statusClass === 'good' ? '#1b5e20' : interp.statusClass === 'warning' ? '#795548' : '#616161',
                                  border: '1px solid rgba(0,0,0,0.08)',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {interp.statusLabelFa}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Value & Unit */}
                        <div style={{ margin: '6px 0' }}>
                          {evaluation.state === 'insufficient' ? (
                            <div style={{ color: '#c62828', fontSize: '0.86rem', fontWeight: 600 }}>
                              {evaluation.displayValue}
                            </div>
                          ) : (
                            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                              <FormattedNumber
                                value={item?.value}
                                unit={evaluation.unit}
                                digits={metricDef.precision ?? 4}
                                style={{
                                  fontSize: '1.4rem',
                                  fontWeight: 800,
                                  fontFamily: 'monospace',
                                  color: 'var(--text-primary, #212121)',
                                }}
                              />
                            </div>
                          )}
                        </div>

                        {/* Reference Range Box */}
                        {interp && (
                          <div
                            style={{
                              fontSize: '0.73rem',
                              padding: '4px 8px',
                              borderRadius: 4,
                              background: interp.hasFixedRange ? '#e8f5e9' : '#f0f4f8',
                              color: interp.hasFixedRange ? '#1b5e20' : '#37474f',
                              border: interp.hasFixedRange ? '1px solid #c8e6c9' : '1px solid #cfd8dc',
                              marginBottom: 6,
                              lineHeight: 1.4,
                            }}
                          >
                            {interp.hasFixedRange ? (
                              <>🎯 <strong>محدوده مرجع:</strong> {interp.rangeLabelFa}</>
                            ) : (
                              <>ℹ️ <strong>محدوده مرجع:</strong> {interp.rangeLabelFa}</>
                            )}
                          </div>
                        )}

                        {/* Farmer-friendly Plain Persian Interpretation */}
                        {interp && (
                          <div
                            style={{
                              fontSize: '0.76rem',
                              color: '#37474f',
                              lineHeight: 1.45,
                              marginBottom: 6,
                              background: 'rgba(0,0,0,0.02)',
                              padding: '5px 8px',
                              borderRadius: 4,
                              borderRight: '3px solid #4caf50',
                            }}
                          >
                            🌱 <strong>راهنمای باغدار:</strong> {interp.farmerSummaryFa}
                          </div>
                        )}

                        {/* Insufficient / Limited Note */}
                        {evaluation.state === 'insufficient' && (
                          <div style={{ fontSize: '0.74rem', color: '#b71c1c', marginBottom: 6 }}>
                            ⚠️ {evaluation.reasonFa}
                          </div>
                        )}

                        {evaluation.state === 'limited' && (
                          <div
                            style={{
                              fontSize: '0.72rem',
                              background: '#fff8e1',
                              color: '#6d4c41',
                              padding: '4px 6px',
                              borderRadius: 4,
                              marginBottom: 6,
                            }}
                          >
                            ℹ️ {evaluation.reasonFa}
                          </div>
                        )}
                      </div>

                      {/* Expandable Scientific Metadata & Provenance */}
                      <details style={{ fontSize: '0.7rem', color: 'var(--text-muted, #757575)', marginTop: 4, borderTop: '1px solid rgba(0,0,0,0.06)', paddingTop: 4 }}>
                        <summary style={{ cursor: 'pointer', fontWeight: 600, color: '#546e7a', padding: '2px 0' }}>
                          🔬 جزئیات علمی، سنجنده و محدودیت‌ها
                        </summary>
                        <div
                          style={{
                            padding: '6px 8px',
                            background: '#fafafa',
                            borderRadius: 4,
                            marginTop: 4,
                            border: '1px solid #eeeeee',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 3,
                            lineHeight: 1.4,
                          }}
                        >
                          <div>
                            🌐 <strong>سنجنده / منبع داده:</strong> {interp?.datasetNameFa || item?.source_dataset || 'سنجنده ماهواره‌ای'}
                          </div>
                          <div>
                            📐 <strong>تفکیک مکانی (وضوح):</strong> {interp?.spatialResolution || 'مطابق کاتالوگ'}
                          </div>
                          {interp?.sourceCitation && (
                            <div>
                              📚 <strong>مرجع علمی استناد:</strong> {interp.sourceCitation}
                            </div>
                          )}
                          {interp?.validityConditionsFa && (
                            <div>
                              📋 <strong>شرایط اعتبار:</strong> {interp.validityConditionsFa}
                            </div>
                          )}
                          {interp?.scientificCautionFa && (
                            <div style={{ color: '#b71c1c' }}>
                              ⚠️ <strong>محدودیت ابزار:</strong> {interp.scientificCautionFa}
                            </div>
                          )}
                          {item?.quality && (
                            <div>
                              کیفیت داده: <span>{item.quality}</span>
                            </div>
                          )}
                          {support?.badgeEn && (
                            <div style={{ direction: 'ltr', textAlign: 'left', fontSize: '0.66rem', color: '#888' }}>
                              Support: {support.badgeEn}
                            </div>
                          )}
                        </div>
                      </details>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
