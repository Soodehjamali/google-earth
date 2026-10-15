import { useEffect, useState, useMemo } from 'react';
import { agricultureApi } from '../../api/agriculture';
import type {
  AgricultureGeometry,
  HistoricalComparisonResponse,
  HistoricalMetricTrend,
  HistoricalYearRecord,
  HistoricalYearStatus,
} from '../../types';
import { formatEvidenceValue } from './parse';
import { formatPersianYear, formatPersianDateRange } from './persianDate';

interface Historical10YearSectionProps {
  geometry: GeoJSON.Geometry | AgricultureGeometry | null;
  startDate: string;
  endDate: string;
  domain?: string;
  cloudMaxPercent?: number;
  title?: string;
  titleFa?: string;
  disableAutoFetch?: boolean;
}

const STATUS_CONFIG: Record<
  HistoricalYearStatus,
  { labelFa: string; labelEn: string; badgeClass: string }
> = {
  current: {
    labelFa: 'دوره جاری',
    labelEn: 'Current',
    badgeClass: 'badge-primary',
  },
  available: {
    labelFa: 'موجود',
    labelEn: 'Available',
    badgeClass: 'badge-good',
  },
  partial: {
    labelFa: 'ناقص',
    labelEn: 'Partial',
    badgeClass: 'badge-warning',
  },
  unavailable: {
    labelFa: 'ناموجود',
    labelEn: 'Unavailable',
    badgeClass: 'badge-unavailable',
  },
};

const TREND_DIRECTION_CONFIG: Record<
  string,
  { icon: string; labelFa: string; color: string }
> = {
  improving: { icon: '↗️', labelFa: 'رو به بهبود (مساعد)', color: '#2e7d32' },
  declining: { icon: '↘️', labelFa: 'رو به کاهش (نامساعد)', color: '#c62828' },
  stable: { icon: '➡️', labelFa: 'پایدار و بدون تغییر عمده', color: '#1565c0' },
  variable: { icon: '〰️', labelFa: 'در حال نوسان و ناپایدار', color: '#ef6c00' },
  increasing: { icon: '📈', labelFa: 'افزایشی', color: '#0277bd' },
  decreasing: { icon: '📉', labelFa: 'کاهشی', color: '#455a64' },
  insufficient_evidence: {
    icon: '❓',
    labelFa: 'شواهد ناکافی (< ۳ مشاهده)',
    color: '#757575',
  },
};

export default function Historical10YearSection({
  geometry,
  startDate,
  endDate,
  domain = 'vegetation',
  cloudMaxPercent = 20,
  title = '10-Year Same-Period Historical Comparison',
  titleFa = 'مقایسه ۱۰ ساله دوره مشابه تاریخی',
  disableAutoFetch = false,
}: Historical10YearSectionProps) {
  const [userRequested, setUserRequested] = useState<boolean>(!disableAutoFetch);
  const [data, setData] = useState<HistoricalComparisonResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<string>('');

  useEffect(() => {
    if (!userRequested) return;
    if (!geometry || !startDate || !endDate) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    agricultureApi
      .getHistoricalComparison({
        geometry,
        start_date: startDate,
        end_date: endDate,
        domain,
        cloud_max_percent: cloudMaxPercent,
      })
      .then((res) => {
        if (!isMounted) return;
        setData(res);
        if (res.available_metrics && res.available_metrics.length > 0) {
          setSelectedMetric(res.available_metrics[0]);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        console.error('Failed to load 10-year historical comparison:', err);
        setError(err instanceof Error ? err.message : 'Error fetching historical data');
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [userRequested, geometry, startDate, endDate, domain, cloudMaxPercent]);

  // Metric columns present in response
  const metrics = useMemo(() => data?.available_metrics ?? [], [data]);

  // Active trend
  const activeTrend: HistoricalMetricTrend | undefined =
    data?.trends?.[selectedMetric] ?? (metrics[0] ? data?.trends?.[metrics[0]] : undefined);

  if (!geometry) return null;

  if (disableAutoFetch && !userRequested && !data) {
    return (
      <div className="card mb-3" data-testid="historical-10year-ondemand-card">
        <div
          className="card-header"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 8,
          }}
        >
          <span className="card-title">📅 {titleFa}</span>
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            onClick={() => setUserRequested(true)}
          >
            🛰️ استعلام مقایسه ۱۰ ساله ماهواره‌ای (GEE)
          </button>
        </div>
        <div className="card-body text-muted" style={{ fontSize: '0.82rem' }}>
          در مرور گزارش ذخیره‌شده، مقایسه ۱۰ ساله ماهواره‌ای جهت جلوگیری از اجرای ناخواسته محاسبات سنگین به صورت خودکار بارگذاری نمی‌شود. برای مشاهده مقایسه ۱۰ ساله، دکمه استعلام را فشار دهید.
        </div>
      </div>
    );
  }

  // Domain special safety gates
  const isSoilDomain = domain === 'soil';
  const isProductivityDomain = domain === 'productivity';

  return (
    <div className="card mb-4" data-testid="historical-10year-section">
      <div
        className="card-header"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 10,
        }}
      >
        <div>
          <span className="card-title" style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>
            ⏳ {titleFa}
          </span>
          <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 2 }}>
            {title} ({domain})
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {data?.same_period_label_fa && (
            <span
              className="badge badge-info"
              style={{ fontSize: '0.78rem', padding: '4px 8px' }}
            >
              دوره تقویمی یکسان: {data.same_period_label_fa}
            </span>
          )}
          <span
            className="badge badge-good"
            style={{ fontSize: '0.75rem', padding: '4px 8px' }}
          >
            Real 10-Year Satellite Observations
          </span>
        </div>
      </div>

      <div className="card-body">
        {/* Soil Safety Boundary Banner */}
        {isSoilDomain && (
          <div
            className="alert alert-warning"
            style={{ marginBottom: 14, lineHeight: 1.6 }}
          >
            ⛔ <strong>Soil historical chemical data unavailable</strong> — شواهد تاریخی شیمیایی و حاصلخیزی خاک موجود نیست: داده‌های
            تاریخی ماهواره‌ای حاوی اطلاعات شوری (EC)، نیتروژن، فسفر، پتاسیم یا pH نیستند.
            هرگونه تجویز حاصلخیزی یا کود نیازمند آزمون مستقیم آزمایشگاهی خاک است.
          </div>
        )}

        {/* Productivity Safety Boundary Banner */}
        {isProductivityDomain && (
          <div
            className="alert alert-warning"
            style={{ marginBottom: 14, lineHeight: 1.6 }}
          >
            ⛔ <strong>Uncalibrated yield trend deactivated</strong> — پیش‌بینی تناژ عملکرد محصول غیرفعال است: مدل‌های سنجش از دور
            بدون کالیبراسیون و داده‌های اعتبارسنجی میدانی قادر به پیش‌بینی تناژ قطعی محصول
            در سال‌های گذشته نیستند.
          </div>
        )}

        {/* Objective & Method Banner */}
        <div
          style={{
            padding: '10px 14px',
            marginBottom: 16,
            background: 'var(--bg-secondary, #f5f5f5)',
            border: '1px solid #e0e0e0',
            borderRadius: 8,
            fontSize: '0.82rem',
            lineHeight: 1.6,
          }}
        >
          📌 <strong>اصول روش‌شناسی علمی مقایسه ۱۰ ساله:</strong>
          <ul style={{ margin: '6px 0 0', paddingRight: 20 }}>
            <li>
              تمام سال‌های گذشته دقیقاً در <strong>همان پنجره فصلی و تقویمی دوره جاری</strong> مورد
              سنجش قرار گرفته‌اند تا اثر تفاوت فصل بر شاخص‌ها حذف شود.
            </li>
            <li>
              اگر در یک سال به علت پوشش ابری یا عدم حضور ماهواره داده‌ای موجود نبوده، صراحتاً
              به عنوان <strong>ناموجود (Unavailable)</strong> گزارش شده و هرگز با صفر یا مقدار تقریبی جایگزین نشده است.
            </li>
          </ul>
        </div>

        {/* Loading State */}
        {loading && (
          <div
            style={{
              padding: 24,
              textAlign: 'center',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <div className="spinner" style={{ width: 32, height: 32 }} />
            <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>
              در حال استخراج مشاهدات ۱۰ ساله ماهواره‌ای دوره مشابه از Google Earth Engine...
            </div>
            <div className="text-muted" style={{ fontSize: '0.8rem' }}>
              Batched 10-year seasonal median reduction across Sentinel, MODIS and ERA5
            </div>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="alert alert-danger" style={{ marginBottom: 14 }}>
            <div>خطا در دریافت مقایسه تاریخی ۱۰ ساله: {error}</div>
          </div>
        )}

        {/* Content Table & Trend Cards */}
        {data && !loading && (
          <>
            {/* 1. Historical Table */}
            <div style={{ overflowX: 'auto', marginBottom: 20 }}>
              <table
                data-testid="historical-10year-table"
                className="table"
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: '0.84rem',
                }}
              >
                <thead>
                  <tr style={{ background: '#f5f5f5', borderBottom: '2px solid #ddd' }}>
                    <th style={{ padding: '8px 10px', textAlign: 'center' }}>سال (جلالی)</th>
                    <th style={{ padding: '8px 10px', textAlign: 'center' }}>بازه تقویمی مشابه</th>
                    {metrics.map((m) => {
                      const trendMeta = data.trends?.[m];
                      return (
                        <th
                          key={m}
                          style={{
                            padding: '8px 10px',
                            textAlign: 'center',
                            cursor: 'pointer',
                            background: selectedMetric === m ? '#e3f2fd' : 'transparent',
                          }}
                          onClick={() => setSelectedMetric(m)}
                          title="کلیک برای مشاهده جزئیات روند"
                        >
                          <div>{trendMeta?.display_name_fa ?? m.toUpperCase()}</div>
                          <div className="text-muted" style={{ fontSize: '0.72rem' }}>
                            {m.toUpperCase()} ({trendMeta?.unit || '—'})
                          </div>
                        </th>
                      );
                    })}
                    <th style={{ padding: '8px 10px', textAlign: 'center' }}>وضعیت شواهد</th>
                  </tr>
                </thead>
                <tbody>
                  {data.years.map((row: HistoricalYearRecord) => {
                    const isCurrent = row.status === 'current';
                    const statusCfg = STATUS_CONFIG[row.status] ?? STATUS_CONFIG.unavailable;

                    return (
                      <tr
                        key={row.year}
                        style={{
                          borderBottom: '1px solid #eee',
                          backgroundColor: isCurrent ? '#f1f8e9' : 'transparent',
                          fontWeight: isCurrent ? 600 : 400,
                        }}
                      >
                        {/* Year (Jalali presentation derived from actual start_date) */}
                        <td
                          style={{
                            padding: '8px 10px',
                            textAlign: 'center',
                            fontSize: '0.9rem',
                            fontWeight: isCurrent ? 700 : 500,
                          }}
                        >
                          {formatPersianYear(row.start_date, row.year)}
                        </td>

                        {/* Same Period Window (Jalali presentation) */}
                        <td
                          style={{
                            padding: '8px 10px',
                            textAlign: 'center',
                            color: '#555',
                            fontSize: '0.8rem',
                          }}
                        >
                          {data.same_period_label_fa}
                          <div style={{ fontSize: '0.72rem', color: '#888', marginTop: 2 }}>
                            {formatPersianDateRange(row.start_date, row.end_date)}
                          </div>
                        </td>

                        {/* Metrics values */}
                        {metrics.map((m) => {
                          const val = row.metrics[m];
                          const isValAvailable = val !== null && val !== undefined;

                          return (
                            <td
                              key={m}
                              style={{
                                padding: '8px 10px',
                                textAlign: 'center',
                                fontFamily: isValAvailable ? 'monospace' : 'inherit',
                                color: isValAvailable ? 'inherit' : '#9e9e9e',
                                backgroundColor:
                                  selectedMetric === m
                                    ? isCurrent
                                      ? '#e8f5e9'
                                      : '#f9fbff'
                                    : 'transparent',
                              }}
                            >
                              {isValAvailable ? formatEvidenceValue(val, 3) : '—'}
                            </td>
                          );
                        })}

                        {/* Status */}
                        <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                          <span
                            className={`badge ${statusCfg.badgeClass}`}
                            style={{ fontSize: '0.74rem' }}
                          >
                            {statusCfg.labelFa}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* 2. Metric Trend & Baseline Summary Card */}
            {activeTrend && (
              <div
                className="card"
                data-testid="historical-trend-summary-card"
                style={{
                  padding: '16px 18px',
                  background: 'var(--bg-secondary, #fafafa)',
                  border: '1px solid #e0e0e0',
                  borderRadius: 8,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: 12,
                    marginBottom: 12,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <h4 style={{ margin: 0, fontSize: '0.98rem', fontWeight: 700 }}>
                      تحلیل روند ۱۰ ساله: {activeTrend.display_name_fa}
                    </h4>
                    {metrics.length > 1 && (
                      <select
                        aria-label="انتخاب شاخص روند"
                        value={selectedMetric}
                        onChange={(e) => setSelectedMetric(e.target.value)}
                        style={{
                          fontSize: '0.8rem',
                          padding: '3px 8px',
                          borderRadius: 6,
                          border: '1px solid #ccc',
                        }}
                      >
                        {metrics.map((m) => (
                          <option key={m} value={m}>
                            {data.trends?.[m]?.display_name_fa ?? m.toUpperCase()}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>

                  {/* Trend Direction Badge */}
                  <div>
                    {(() => {
                      const dirCfg =
                        TREND_DIRECTION_CONFIG[activeTrend.trend_direction] ??
                        TREND_DIRECTION_CONFIG.insufficient_evidence;
                      return (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 6,
                            padding: '4px 12px',
                            borderRadius: 16,
                            background: '#ffffff',
                            border: `1.5px solid ${dirCfg.color}`,
                            color: dirCfg.color,
                            fontSize: '0.82rem',
                            fontWeight: 600,
                          }}
                        >
                          <span>{dirCfg.icon}</span>
                          <span>{activeTrend.trend_label_fa}</span>
                        </span>
                      );
                    })()}
                  </div>
                </div>

                {/* KPI comparison grid: Current vs 10Y Median vs Delta */}
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                    gap: 12,
                    marginBottom: 14,
                  }}
                >
                  {/* Current Period Value */}
                  <div
                    style={{
                      background: '#ffffff',
                      padding: '10px 14px',
                      borderRadius: 6,
                      border: '1px solid #eee',
                    }}
                  >
                    <div className="text-muted" style={{ fontSize: '0.76rem' }}>
                      مقدار دوره جاری ({data.years[0] ? formatPersianYear(data.years[0].start_date, data.years[0].year) : ''})
                    </div>
                    <div
                      style={{
                        fontSize: '1.2rem',
                        fontWeight: 700,
                        color: '#1565c0',
                        marginTop: 4,
                      }}
                    >
                      {activeTrend.current_value !== null
                        ? formatEvidenceValue(activeTrend.current_value, 3)
                        : '—'}{' '}
                      <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>
                        {activeTrend.unit}
                      </span>
                    </div>
                  </div>

                  {/* Historical Median Baseline */}
                  <div
                    style={{
                      background: '#ffffff',
                      padding: '10px 14px',
                      borderRadius: 6,
                      border: '1px solid #eee',
                    }}
                  >
                    <div className="text-muted" style={{ fontSize: '0.76rem' }}>
                      میانه پایه ۱۰ ساله دوره مشابه
                    </div>
                    <div
                      style={{
                        fontSize: '1.2rem',
                        fontWeight: 700,
                        color: '#37474f',
                        marginTop: 4,
                      }}
                    >
                      {activeTrend.baseline_median !== null
                        ? formatEvidenceValue(activeTrend.baseline_median, 3)
                        : '—'}{' '}
                      <span style={{ fontSize: '0.8rem', fontWeight: 400 }}>
                        {activeTrend.unit}
                      </span>
                    </div>
                  </div>

                  {/* Delta from Baseline */}
                  <div
                    style={{
                      background: '#ffffff',
                      padding: '10px 14px',
                      borderRadius: 6,
                      border: '1px solid #eee',
                    }}
                  >
                    <div className="text-muted" style={{ fontSize: '0.76rem' }}>
                      انحراف از خط پایه تاریخی (Delta)
                    </div>
                    <div
                      style={{
                        fontSize: '1.2rem',
                        fontWeight: 700,
                        color:
                          activeTrend.delta_from_baseline !== null
                            ? activeTrend.delta_from_baseline > 0
                              ? '#2e7d32'
                              : activeTrend.delta_from_baseline < 0
                                ? '#c62828'
                                : '#1565c0'
                            : '#757575',
                        marginTop: 4,
                      }}
                    >
                      {activeTrend.delta_from_baseline !== null
                        ? `${activeTrend.delta_from_baseline > 0 ? '+' : ''}${formatEvidenceValue(activeTrend.delta_from_baseline, 3)}`
                        : '—'}
                    </div>
                  </div>

                  {/* Slope per year */}
                  <div
                    style={{
                      background: '#ffffff',
                      padding: '10px 14px',
                      borderRadius: 6,
                      border: '1px solid #eee',
                    }}
                  >
                    <div className="text-muted" style={{ fontSize: '0.76rem' }}>
                      شیب Theil-Sen سالانه
                    </div>
                    <div
                      style={{
                        fontSize: '1.2rem',
                        fontWeight: 700,
                        color: '#455a64',
                        marginTop: 4,
                      }}
                    >
                      {activeTrend.trend_slope_per_year !== null
                        ? formatEvidenceValue(activeTrend.trend_slope_per_year, 4)
                        : '—'}{' '}
                      <span style={{ fontSize: '0.75rem', fontWeight: 400 }}>
                        / سال
                      </span>
                    </div>
                  </div>
                </div>

                {/* Scientific Statement */}
                <div
                  style={{
                    background: '#e8eaf6',
                    padding: '8px 12px',
                    borderRadius: 6,
                    fontSize: '0.82rem',
                    color: '#1a237e',
                    lineHeight: 1.5,
                  }}
                >
                  ℹ️ <strong>خلاصه تفسیر علمی:</strong> {activeTrend.scientific_summary_fa}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
