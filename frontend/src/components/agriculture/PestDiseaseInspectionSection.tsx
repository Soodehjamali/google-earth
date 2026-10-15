import React from 'react';
import type { PestDiseaseInspectionResponse } from '../../types';
import { toPersianDigits } from './persianDate';

interface PestDiseaseInspectionSectionProps {
  inspection: PestDiseaseInspectionResponse;
}

export const PestDiseaseInspectionSection: React.FC<PestDiseaseInspectionSectionProps> = ({
  inspection,
}) => {
  const getRiskBadge = (level: string) => {
    switch (level) {
      case 'high':
        return (
          <span className="bg-rose-500/15 text-rose-400 border border-rose-500/30 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1.5 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-rose-400"></span>
            ناهنجاری شدید رصدی (پایش فوری)
          </span>
        );
      case 'elevated':
        return (
          <span className="bg-amber-500/15 text-amber-400 border border-amber-500/30 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-400"></span>
            ناهنجاری فعال رصدی (پایش میدانی)
          </span>
        );
      case 'moderate':
        return (
          <span className="bg-yellow-500/15 text-yellow-400 border border-yellow-500/30 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-yellow-400"></span>
            ناهنجاری رصدی ملایم (علت نامشخص)
          </span>
        );
      case 'none':
      case 'low':
        return (
          <span className="bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            بدون آنومالی (وضعیت پایدار)
          </span>
        );
      case 'insufficient':
      default:
        return (
          <span className="bg-slate-500/15 text-slate-400 border border-slate-500/30 px-3 py-1 rounded-full text-xs font-bold flex items-center gap-1.5">
            شواهد ناکافی
          </span>
        );
    }
  };

  const isTestFixture = Boolean(inspection.ground_truth_corroboration?.is_test_fixture);

  const hierarchySteps = [
    { level: 0, label: 'سطح ۰: بدون شواهد' },
    { level: 1, label: 'سطح ۱: تک‌سنسوری' },
    { level: 2, label: 'سطح ۲: پایداری چندزمانه' },
    { level: 3, label: 'سطح ۳: همگرایی چندسنسوری' },
    {
      level: 4,
      label: isTestFixture
        ? 'سطح ۴ (Test Fixture — not real ground truth)'
        : 'سطح ۴: اعتبارسنجی میدانی',
    },
  ];

  return (
    <div className="space-y-6 text-slate-100">
      {/* 1. Overall Status and Pattern Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div>
            <div className="text-xs text-slate-400 font-medium">پایش و غربالگری چندسنسوری ناهنجاری‌های رصدی (فاقد تشخیص قطعی آفت/بیماری)</div>
            <h2 className="text-xl font-bold text-slate-100 mt-1">
              {inspection.pattern_title_fa}
            </h2>
          </div>
          <div>{getRiskBadge(inspection.overall_risk_level)}</div>
        </div>

        <p className="text-xs text-slate-300 bg-slate-800/60 p-3 rounded-lg border border-slate-700/60 leading-relaxed mb-4">
          {inspection.pattern_summary_fa}
        </p>

        {/* Evidence Hierarchy Tracker */}
        <div className="border-t border-slate-800 pt-4 mt-2">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="font-semibold text-slate-300">
              سطح سلسله‌مراتب شواهد علمی (Evidence Hierarchy):
            </span>
            <span className="text-emerald-400 font-bold">
              {inspection.evidence_hierarchy_title_fa}
            </span>
          </div>

          <div className="grid grid-cols-5 gap-1.5 mb-2">
            {hierarchySteps.map((step) => {
              const isActive = step.level <= inspection.evidence_hierarchy_level;
              const isCurrent = step.level === inspection.evidence_hierarchy_level;
              return (
                <div key={step.level} className="flex flex-col items-center">
                  <div
                    className={`h-2 w-full rounded-full transition-all ${
                      isActive
                        ? isCurrent
                          ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]'
                          : 'bg-emerald-600'
                        : 'bg-slate-800'
                    }`}
                  />
                  <span
                    className={`text-[10px] mt-1 text-center truncate w-full ${
                      isCurrent
                        ? 'text-emerald-300 font-bold'
                        : isActive
                        ? 'text-slate-400'
                        : 'text-slate-600'
                    }`}
                  >
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>

          <p className="text-[11px] text-slate-400 mt-1">
            {inspection.evidence_hierarchy_description_fa}
          </p>

          {isTestFixture && (
            <div className="mt-2.5 bg-amber-500/10 border border-amber-500/30 rounded-lg p-2.5 text-xs text-amber-300 flex items-center gap-2">
              <span>🧪</span>
              <span>
                <strong>توجه علمی:</strong> داده‌های زمینی ارائه‌شده از نوع <strong>Test Fixture — not real ground truth</strong> هستند و طبق اصول ایمنی علمی، عبارت «Ground Truth Validated» فقط برای مشاهدات میدانی واقعی معتبر مجاز است.
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 2. Biotic vs Abiotic Compatibility Assessment */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <h3 className="text-base font-bold text-slate-100 mb-2 flex items-center gap-2">
          <span>ارزیابی سازگاری تنش زیستی (آفت/بیماری) در برابر غیرزیستی (اقلیمی/محیطی)</span>
          <span className="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-700">
            Biotic vs Abiotic Screening
          </span>
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          تمایز الگوهای کاهش کلروفیل و ساختار تاج از نوسانات ناشی از خشکی عمومی و موج گرمای منطقه‌ای.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div className="bg-slate-800/50 border border-slate-700/60 rounded-lg p-3.5">
            <div className="flex justify-between items-center text-xs mb-1.5">
              <span className="font-semibold text-amber-400">سازگاری با تنش زیستی (آفت یا پاتوژن):</span>
              <span className="font-mono text-slate-200">
                {toPersianDigits(Math.round(inspection.biotic_abiotic_assessment.biotic_compatibility_score * 100))}٪
              </span>
            </div>
            <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 rounded-full"
                style={{
                  width: `${Math.round(inspection.biotic_abiotic_assessment.biotic_compatibility_score * 100)}%`,
                }}
              />
            </div>
            <div className="text-[11px] text-slate-400 mt-2">
              ویژگی‌ها: زوال سریع لبه قرمز (NDRE)، کاهش حجم پراکنش راداری (VH)، تمرکز لکه‌ای در تاج
            </div>
          </div>

          <div className="bg-slate-800/50 border border-slate-700/60 rounded-lg p-3.5">
            <div className="flex justify-between items-center text-xs mb-1.5">
              <span className="font-semibold text-cyan-400">سازگاری با تنش غیرزیستی (گرما / خشکی):</span>
              <span className="font-mono text-slate-200">
                {toPersianDigits(Math.round(inspection.biotic_abiotic_assessment.abiotic_compatibility_score * 100))}٪
              </span>
            </div>
            <div className="h-2 w-full bg-slate-900 rounded-full overflow-hidden">
              <div
                className="h-full bg-cyan-500 rounded-full"
                style={{
                  width: `${Math.round(inspection.biotic_abiotic_assessment.abiotic_compatibility_score * 100)}%`,
                }}
              />
            </div>
            <div className="text-[11px] text-slate-400 mt-2">
              ویژگی‌ها: همبستگی یکنواخت با دمای بالای سطح (LST) و افت رطوبت در سطح کل بلوک
            </div>
          </div>
        </div>

        <div className="text-xs text-slate-300 bg-slate-800/30 border border-slate-700/40 p-3 rounded-lg leading-relaxed">
          <span className="font-semibold text-slate-200">تحلیل علمی شواهد: </span>
          {inspection.biotic_abiotic_assessment.reasoning_fa}
        </div>
      </div>

      {/* 3. Multi-Sensor Evidence Breakdown */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <h3 className="text-base font-bold text-slate-100 mb-3 flex items-center gap-2">
          <span>شواهد تفکیکی سنجنده‌ها (اپتیکال، رادار، حرارتی)</span>
          <span className="text-xs text-slate-400 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
            Multi-Sensor Channels
          </span>
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Optical Card */}
          <div className="bg-slate-800/60 border border-slate-700/70 rounded-lg p-3.5 text-xs">
            <div className="flex items-center gap-1.5 text-emerald-400 font-bold mb-2 pb-1.5 border-b border-slate-700">
              <span>🛰️</span>
              <span>سنجنده‌های اپتیکال (Sentinel-2)</span>
            </div>
            <div className="space-y-2">
              {inspection.optical_evidence.map((item) => (
                <div key={item.metric_key} className="bg-slate-900/60 p-2 rounded border border-slate-800">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-medium text-slate-200">{item.display_name_fa}</span>
                    <span className="font-mono text-emerald-400 font-semibold">
                      {item.value !== null && item.value !== undefined ? toPersianDigits(item.value) : 'ناموجود'}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400 leading-tight">{item.notes_fa}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Radar Card */}
          <div className="bg-slate-800/60 border border-slate-700/70 rounded-lg p-3.5 text-xs">
            <div className="flex items-center gap-1.5 text-cyan-400 font-bold mb-2 pb-1.5 border-b border-slate-700">
              <span>📡</span>
              <span>رادار دیافراگم مصنوعی (Sentinel-1 SAR)</span>
            </div>
            <div className="space-y-2">
              {inspection.radar_evidence.map((item) => (
                <div key={item.metric_key} className="bg-slate-900/60 p-2 rounded border border-slate-800">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-medium text-slate-200">{item.display_name_fa}</span>
                    <span className="font-mono text-cyan-400 font-semibold">
                      {item.value !== null && item.value !== undefined ? `${toPersianDigits(item.value)} dB` : 'ناموجود'}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400 leading-tight">{item.notes_fa}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Thermal Card */}
          <div className="bg-slate-800/60 border border-slate-700/70 rounded-lg p-3.5 text-xs">
            <div className="flex items-center gap-1.5 text-amber-400 font-bold mb-2 pb-1.5 border-b border-slate-700">
              <span>🌡️</span>
              <span>کانال‌های حرارتی و اقلیمی (MODIS/ERA5)</span>
            </div>
            <div className="space-y-2">
              {inspection.thermal_evidence.map((item) => (
                <div key={item.metric_key} className="bg-slate-900/60 p-2 rounded border border-slate-800">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-medium text-slate-200">{item.display_name_fa}</span>
                    <span className="font-mono text-amber-400 font-semibold">
                      {item.value !== null && item.value !== undefined ? `${toPersianDigits(item.value)} °C` : 'ناموجود'}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-400 leading-tight">{item.notes_fa}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 4. Recommended Field Actions */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
        <h3 className="text-base font-bold text-slate-100 mb-2 flex items-center gap-2">
          <span>اقدامات میدانی پیشنهادی کارشناس (Field Actions)</span>
          <span className="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-700">
            مبتنی بر IPM
          </span>
        </h3>
        <p className="text-xs text-slate-400 mb-3">
          با توجه به عدم قطعیت ماهواره و محدودیت تفکیک سنجش از دور، انجام گام‌های زیر الزامی است:
        </p>

        <ul className="space-y-2 text-xs text-slate-300">
          {inspection.recommended_field_actions_fa.map((act, i) => (
            <li key={i} className="flex items-start gap-2 bg-slate-800/40 p-2 rounded border border-slate-700/50">
              <span className="text-emerald-400 font-bold">✓</span>
              <span>{act}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* 5. Mandatory Non-Negotiable Scientific Disclaimers */}
      <div className="bg-rose-950/20 border border-rose-900/40 rounded-xl p-5 text-xs text-rose-200 leading-relaxed shadow-lg">
        <div className="flex items-center gap-2 text-rose-400 font-bold text-sm mb-2">
          <span>⚠️</span>
          <span>سلب مسئولیت و اصول ایمنی علمی (Scientific Safety Gate)</span>
        </div>
        <p className="mb-2">
          {inspection.scientific_disclaimer_fa}
        </p>
        <p className="text-slate-400 text-[11px] font-sans direction-ltr text-left border-t border-rose-900/30 pt-2">
          {inspection.scientific_disclaimer_en}
        </p>
      </div>
    </div>
  );
};
