import React from 'react';
import type { ValidationResult, ValidationSection } from '../../types';
import { toPersianDigits } from './persianDate';

interface GroundTruthValidationTableProps {
  validation?: ValidationSection | null;
  results?: ValidationResult[];
}

export const GroundTruthValidationTable: React.FC<GroundTruthValidationTableProps> = ({
  validation,
  results: propResults,
}) => {
  const items: ValidationResult[] = propResults || validation?.results || [];

  const getStatusBadge = (status: string, statusCode?: string | null) => {
    const code = statusCode || status;
    switch (code) {
      case 'validated':
      case 'MATCHED_REFERENCE':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
            اعتبارسنجی‌شده (تطابق کامل)
          </span>
        );
      case 'partially_validated':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
            تا حدی اعتبارسنجی‌شده
          </span>
        );
      case 'divergent':
      case 'MISMATCHED_REFERENCE':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400"></span>
            انحراف از داده زمینی
          </span>
        );
      case 'unavailable':
      case 'UNAVAILABLE':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
            ناموجود در تصویر ماهواره
          </span>
        );
      case 'insufficient_evidence':
      case 'INSUFFICIENT_REFERENCE':
      case 'INSUFFICIENT_ANALYSIS':
      case 'NOT_VALIDATED':
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-500/10 text-slate-400 border border-slate-500/20">
            شواهد ناکافی جهت ارزیابی
          </span>
        );
    }
  };

  const getMetricNameFa = (key: string): string => {
    const map: Record<string, string> = {
      ndvi: 'شاخص پوشش گیاهی (NDVI)',
      evi: 'شاخص پوشش تقویت‌شده (EVI)',
      ndre: 'شاخص لبه قرمز کلروفیل (NDRE)',
      ndmi: 'شاخص رطوبت سایه‌انداز (NDMI)',
      ndwi: 'شاخص تفاوت آب (NDWI)',
      msi: 'شاخص تنش رطوبتی (MSI)',
      sar_vh: 'پراکنش رادار (Sentinel-1 VH)',
      sar_vv: 'پراکنش رادار (Sentinel-1 VV)',
      rvi: 'شاخص پوشش راداری (RVI)',
      lst_celsius: 'دمای سطح زمین (LST)',
      soil_moisture: 'رطوبت خاک',
      observed_stress: 'تنش عمومی مشاهده‌شده',
    };
    return map[key] || key;
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-slate-100 mb-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <span>جدول اعتبارسنجی علمی مشاهدات زمینی و ماهواره‌ای</span>
            <span className="text-xs font-normal text-slate-400 bg-slate-800 px-2.5 py-0.5 rounded-md border border-slate-700">
              Deterministic Ground-Truth Validation
            </span>
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            مقایسه داده‌های واقعی ثبت‌شده در مزرعه با اندازه‌گیری‌های ماهواره‌ای بر اساس هم‌مکانی و هم‌زمانی دقیق.
          </p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="bg-slate-800/40 border border-dashed border-slate-700 rounded-lg p-6 text-center text-slate-400 text-xs">
          هیچ نتیجه تطبیقی یافت نشد. با افزودن مشاهده زمینی و اجرای پایش، جدول مقایسه عددی ماهواره و زمین در اینجا ترسیم می‌شود.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 bg-slate-800/40">
                <th className="py-2.5 px-3 font-semibold">شاخص / متغیر</th>
                <th className="py-2.5 px-3 font-semibold">مشاهده زمینی (Ground Truth)</th>
                <th className="py-2.5 px-3 font-semibold">برآورد ماهواره‌ای</th>
                <th className="py-2.5 px-3 font-semibold">اختلاف قدرمطلق (Δ)</th>
                <th className="py-2.5 px-3 font-semibold">درصد اختلاف نسبی</th>
                <th className="py-2.5 px-3 font-semibold">تعداد نمونه</th>
                <th className="py-2.5 px-3 font-semibold">وضعیت اعتبارسنجی علمی</th>
                <th className="py-2.5 px-3 font-semibold">پیوند و توضیحات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {items.map((res, idx) => {
                const diff =
                  res.difference !== undefined && res.difference !== null
                    ? res.difference
                    : res.analysis_value !== null &&
                      res.analysis_value !== undefined &&
                      res.reference_value !== null &&
                      res.reference_value !== undefined
                    ? Math.round((res.analysis_value - res.reference_value) * 10000) / 10000
                    : null;

                const relDiff =
                  res.relative_difference_percent !== undefined &&
                  res.relative_difference_percent !== null
                    ? res.relative_difference_percent
                    : diff !== null && res.reference_value && Math.abs(res.reference_value) > 1e-6
                    ? Math.round((Math.abs(diff) / Math.abs(res.reference_value)) * 10000) / 100
                    : null;

                return (
                  <tr key={res.validation_id || idx} className="hover:bg-slate-800/30 transition-colors">
                    <td className="py-2.5 px-3 font-medium text-slate-200">
                      {getMetricNameFa(res.metric_key || res.reference_variable)}
                    </td>
                    <td className="py-2.5 px-3 font-mono text-emerald-400">
                      {res.reference_value !== null && res.reference_value !== undefined
                        ? toPersianDigits(res.reference_value)
                        : res.reference_state || '—'}{' '}
                      <span className="text-[10px] text-slate-400 font-sans">{res.reference_unit}</span>
                    </td>
                    <td className="py-2.5 px-3 font-mono text-cyan-400">
                      {res.analysis_value !== null && res.analysis_value !== undefined
                        ? toPersianDigits(res.analysis_value)
                        : res.analysis_state || '—'}{' '}
                      <span className="text-[10px] text-slate-400 font-sans">{res.analysis_unit}</span>
                    </td>
                    <td className="py-2.5 px-3 font-mono text-slate-300">
                      {diff !== null ? toPersianDigits(diff) : '—'}
                    </td>
                    <td className="py-2.5 px-3 font-mono text-slate-300">
                      {relDiff !== null ? `${toPersianDigits(relDiff)}٪` : '—'}
                    </td>
                    <td className="py-2.5 px-3 font-mono text-slate-300">
                      {toPersianDigits(res.sample_count ?? 1)}
                    </td>
                    <td className="py-2.5 px-3">
                      {getStatusBadge(res.status, res.validation_status_code)}
                    </td>
                    <td className="py-2.5 px-3 text-slate-400 text-[11px] max-w-[220px] truncate" title={res.linkage_reason}>
                      {res.linkage_reason || 'پیوند زمانی و مکانی مستقیم'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
