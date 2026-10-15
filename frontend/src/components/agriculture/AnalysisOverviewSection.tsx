import { useState } from 'react';
import type {
  AgriculturalAnalysisResponse,
  EvidenceBundleResponse,
  EvidenceConflictResponse,
} from '../../types/index.ts';
import {
  asArray,
  asRecord,
  countEvidenceItems,
  countUnavailableMetrics,
  findEvidenceItem,
  patternMetaFor,
  sufficiencyBadgeClass,
} from './parse.ts';
import { formatPersianDateRange } from './persianDate.ts';

interface AnalysisOverviewSectionProps {
  result: AgriculturalAnalysisResponse;
}

interface ConflictDetail {
  key: string;
  domainName: string;
  metricA: string;
  metricB: string;
  status: string;
  explanation: string;
  possibleExplanations: string[];
}

interface KeyFinding {
  id: string;
  icon: string;
  category: string;
  categoryFa: string;
  metricSummary: string;
  observation: string;
  interpretation: string;
  confidence: string;
  limitation: string;
  tone: 'neutral' | 'info' | 'warning';
}

interface KnownNotConcludedItem {
  id: string;
  text: string;
}

/**
 * Builds conservative, evidence-based agricultural observations strictly
 * from the returned response data following a 4-layer structure:
 * 1. Satellite Observation (مشاهده ماهواره)
 * 2. Evidence Interpretation (تفسیر شواهد)
 * 3. Confidence Level (میزان قطعیت)
 * 4. Tool Limitation (محدودیت ابزار)
 */
function deriveKeyFindings(
  _result: AgriculturalAnalysisResponse,
  bundles: Record<string, EvidenceBundleResponse>,
): KeyFinding[] {
  const findings: KeyFinding[] = [];

  // 1. Vegetation Observation (NDVI, SAVI, EVI)
  const ndviItem = findEvidenceItem(bundles, 'ndvi')?.item;
  const saviItem = findEvidenceItem(bundles, 'savi')?.item;
  const eviItem = findEvidenceItem(bundles, 'evi')?.item;

  if (ndviItem && typeof ndviItem.value === 'number') {
    const ndviVal = ndviItem.value;
    const saviVal = saviItem && typeof saviItem.value === 'number' ? saviItem.value.toFixed(4) : null;
    const eviVal = eviItem && typeof eviItem.value === 'number' ? eviItem.value.toFixed(4) : null;

    if (ndviVal < 0.1) {
      findings.push({
        id: 'veg-bare',
        icon: '🌱',
        category: 'Vegetation Signal',
        categoryFa: 'سیگنال پوشش گیاهی',
        metricSummary: `NDVI: ${ndviVal.toFixed(4)}`,
        observation: `مقدار شاخص NDVI در محدوده تحلیل‌شده برابر با ${ndviVal.toFixed(4)}${
          saviVal ? ` (SAVI: ${saviVal}، EVI: ${eviVal ?? '—'})` : ''
        } در باند نوری ۱۰ متری سنتینل-۲ ثبت شد.`,
        interpretation:
          'سیگنال بازتابی بسیار ضعیف است و با پوشش گیاهی ضعیف، متفرق یا بستر کم‌پوشش در زمان سنجش سازگار است.',
        confidence: 'بالا برای بازتابش طیفی سطح زمین در تاریخ گذر ماهواره.',
        limitation:
          'سیگنال ضعیف یا تنک پوشش گیاهی اثبات‌کننده عدم فتوسنتز مطلق نبوده و طبقه‌بندی قطعی کاربری یا وضعیت فیزیولوژیک گیاه نیست.',
        tone: 'neutral',
      });
    } else if (ndviVal < 0.25) {
      findings.push({
        id: 'veg-sparse',
        icon: '🌿',
        category: 'Vegetation Signal',
        categoryFa: 'سیگنال پوشش گیاهی',
        metricSummary: `NDVI: ${ndviVal.toFixed(4)}`,
        observation: `مقدار شاخص NDVI برابر با ${ndviVal.toFixed(4)} در محدوده ثبت شد.`,
        interpretation: 'منعکس‌کننده سیگنال پوشش گیاهی ضعیف، متفرق یا مرتعی تنک در سطح است.',
        confidence: 'متوسط تا بالا در محدوده پیکسل‌های ۱۰ متری.',
        limitation: 'بدون قضاوت قطعی درباره نوع، سلامت یا بیماری گیاه.',
        tone: 'neutral',
      });
    } else {
      findings.push({
        id: 'veg-active',
        icon: '🌿',
        category: 'Vegetation Signal',
        categoryFa: 'سیگنال پوشش گیاهی',
        metricSummary: `NDVI: ${ndviVal.toFixed(4)}`,
        observation: `شاخص NDVI مقدار ${ndviVal.toFixed(4)} را ثبت کرده است.`,
        interpretation: 'حاکی از حضور بازتاب کانوپی فتوسنتزی فعال در محدوده است.',
        confidence: 'بالا در زمان عبور سنجنده.',
        limitation: 'بدون قضاوت درباره نوع، سلامت یا بیماری محصول.',
        tone: 'info',
      });
    }
  }

  // 2. Moisture / Dryness Observation (NDMI, MSI)
  const ndmiItem = findEvidenceItem(bundles, 'ndmi')?.item;
  const msiItem = findEvidenceItem(bundles, 'msi')?.item;

  if (ndmiItem && typeof ndmiItem.value === 'number') {
    const ndmiVal = ndmiItem.value;
    const msiVal = msiItem && typeof msiItem.value === 'number' ? msiItem.value.toFixed(4) : null;

    if (ndmiVal < 0) {
      findings.push({
        id: 'moisture-dry',
        icon: '💧',
        category: 'Surface Moisture',
        categoryFa: 'پروکسی رطوبت طیفی کانوپی',
        metricSummary: `NDMI: ${ndmiVal.toFixed(4)}`,
        observation: `شاخص طیفی NDMI برابر با ${ndmiVal.toFixed(4)}${
          msiVal ? ` و شاخص تنش رطوبت MSI برابر با ${msiVal}` : ''
        } بر پایه باندهای مادون‌قرمز نزدیک (NIR) و امواج کوتاه (SWIR) اندازه‌گیری شد.`,
        interpretation:
          'نسبت بازتاب مادون‌قرمز امواج کوتاه (SWIR) منطبق بر بازتاب ضعیف رطوبتی کانوپی است.',
        confidence: 'متوسط در حد پروکسی طیفی سنجنده.',
        limitation:
          'این مقادیر صرفاً پروکسی طیفی بوده و نباید به عنوان رطوبت خاک ناحیه ریشه یا تأیید قطعی تنش فیزیولوژیک بوته تعبیر شوند.',
        tone: 'neutral',
      });
    } else {
      findings.push({
        id: 'moisture-moderate',
        icon: '💧',
        category: 'Surface Moisture',
        categoryFa: 'پروکسی رطوبت طیفی کانوپی',
        metricSummary: `NDMI: ${ndmiVal.toFixed(4)}`,
        observation: `شاخص NDMI مقدار ${ndmiVal.toFixed(4)} را ثبت کرده است.`,
        interpretation: 'نشان‌دهنده بازتاب مادون‌قرمز متناسب با وجود مقادیری از رطوبت کانوپی یا سطحی است.',
        confidence: 'متوسط در مقیاس پروکسی طیفی.',
        limitation: 'پروکسی طیفی بوده و اندازه‌گیری مستقیم آب ریشه یا گیاه نیست.',
        tone: 'info',
      });
    }
  }

  // 3. Thermal Observation (Land Surface Temperature Day)
  const lstItem = findEvidenceItem(bundles, 'land_surface_temperature_day')?.item;
  if (lstItem && typeof lstItem.value === 'number') {
    const lstVal = lstItem.value;
    findings.push({
      id: 'thermal-lst',
      icon: '🌡️',
      category: 'Land Surface Temperature',
      categoryFa: 'دمای سطح زمین (LST)',
      metricSummary: `LST Day: ${lstVal.toFixed(2)} °C`,
      observation: `دمای تابشی پوسته فیزیکی خاک در ساعات روز برابر با ${lstVal.toFixed(2)} °C توسط سنجنده حرارتی مادیس (MODIS) ثبت شد.`,
      interpretation: 'بیانگر گرمای تابشی پوسته سطحی زمین در زمان گذر ماهواره است.',
      confidence: 'بالا برای دمای تابشی پوسته فیزیکی خاک در تفکیک ۱۰۰۰ متری.',
      limitation:
        'این مقدار دمای تابشی سطح زمین (LST) است و دلالتی بر دمای برگ، اندام گیاهی یا تأیید تنش گرمایی محصول ندارد.',
      tone: lstVal > 40 ? 'warning' : 'neutral',
    });
  }

  // 4. Radar Backscatter Observation (Sentinel-1 VH & VV)
  const vhItem = findEvidenceItem(bundles, 'vh')?.item;
  const vvItem = findEvidenceItem(bundles, 'vv')?.item;
  if (vhItem && typeof vhItem.value === 'number') {
    const vhVal = vhItem.value;
    const vvVal = vvItem && typeof vvItem.value === 'number' ? vvItem.value.toFixed(2) : null;
    findings.push({
      id: 'radar-vh',
      icon: '📡',
      category: 'Radar Structural Signal',
      categoryFa: 'سیگنال ساختار راداری (سنتینل-۱)',
      metricSummary: `VH: ${vhVal.toFixed(2)} dB`,
      observation: `شدت پس‌پراکنش راداری مایکروویو در قطبش متقاطع VH برابر با ${vhVal.toFixed(2)} dB${
        vvVal ? ` (قطبش هم‌نام VV: ${vvVal} dB)` : ''
      } ثبت شد.`,
      interpretation:
        'نشان‌دهنده سیگنال پس‌پراکنش نسبتاً ضعیف در محدوده است و ساختار حجمی کانوپی متراکم را منعکس نمی‌کند.',
      confidence: 'بالا برای مشخصات پراکنش راداری مایکروویو در زمان گذر سنتینل-۱.',
      limitation:
        'این مشاهده ساختار حجمی کانوپی متراکم را منعکس نمی‌کند، اما به منزله تأیید قطعی خاک لخت هموار تلقی نمی‌شود.',
      tone: 'neutral',
    });
  }

  // 5. Soil Moisture & Model Discrepancy
  const smapItem = findEvidenceItem(bundles, 'soil_moisture_rootzone')?.item;
  const era5Item = findEvidenceItem(bundles, 'soil_moisture_rootzone_era5')?.item;
  const surfaceSmItem = findEvidenceItem(bundles, 'soil_moisture_surface')?.item;

  if (smapItem && era5Item && typeof smapItem.value === 'number' && typeof era5Item.value === 'number') {
    const smapVal = smapItem.value.toFixed(4);
    const era5Val = era5Item.value.toFixed(4);
    findings.push({
      id: 'soil-conflict',
      icon: '⚠️',
      category: 'Soil Model Discrepancy',
      categoryFa: 'واگرایی مدل‌های رطوبت خاک',
      metricSummary: `SMAP: ${smapVal} vs ERA5: ${era5Val}`,
      observation: `برآورد مدل شبیه‌سازی جهانی SMAP L4 برابر با ${smapVal} m³/m³ و مدل ERA5-Land برابر با ${era5Val} m³/m³ گزارش شده است.`,
      interpretation:
        'برآوردهای شبیه‌سازی رطوبت ناحیه ریشه بین مدل‌های جهانی دارای اختلاف چشمگیر و واگرایی هستند.',
      confidence: 'پایین به دلیل وضوح مکانی درشت و تفاوت روش‌های مدلسازی.',
      limitation:
        'به دلیل تفاوت در روش محاسباتی و وضوح مکانی درشت (۹ تا ۱۱ کیلومتر)، استناد به یک عدد منفرد برای تصمیم‌گیری توصیه نمی‌شود.',
      tone: 'warning',
    });
  } else if (surfaceSmItem && typeof surfaceSmItem.value === 'number') {
    findings.push({
      id: 'soil-surface',
      icon: '🌾',
      category: 'Soil Surface Moisture',
      categoryFa: 'رطوبت لایه سطحی خاک',
      metricSummary: `Surface SM: ${surfaceSmItem.value.toFixed(4)} m³/m³`,
      observation: `رطوبت لایه بالایی خاک برابر با ${surfaceSmItem.value.toFixed(4)} m³/m³ گزارش شده است.`,
      interpretation: 'نشان‌دهنده برآورد رطوبت لایه سطحی خاک است.',
      confidence: 'متوسط در حد مدل‌های پایشی سطحی.',
      limitation: 'نشان‌دهنده وضعیت رطوبت لایه‌های عمیق ریشه نیست.',
      tone: 'neutral',
    });
  }

  return findings;
}

/**
 * Derives data-driven items for the Two-Column Known vs Not Concluded area.
 */
function deriveKnownAndUncertainItems(
  result: AgriculturalAnalysisResponse,
  bundles: Record<string, EvidenceBundleResponse>,
): { known: KnownNotConcludedItem[]; notConcluded: KnownNotConcludedItem[] } {
  const known: KnownNotConcludedItem[] = [];
  const notConcluded: KnownNotConcludedItem[] = [];

  const ndviItem = findEvidenceItem(bundles, 'ndvi')?.item;
  if (ndviItem && typeof ndviItem.value === 'number') {
    known.push({
      id: 'k-ndvi',
      text: `سیگنال نوری بازتابی پوشش گیاهی (NDVI: ${ndviItem.value.toFixed(4)}) در تفکیک ۱۰ متری دریافت شد و منطبق بر پوشش ضعیف یا تنک سطحی در تاریخ گذر ماهواره است.`,
    });
  }

  const vhItem = findEvidenceItem(bundles, 'vh')?.item;
  if (vhItem && typeof vhItem.value === 'number') {
    known.push({
      id: 'k-radar',
      text: `سیگنال ریزموج راداری سنتینل-۱ (VH: ${vhItem.value.toFixed(2)} dB) دریافت شد و بازتاب کانوپی متراکم یا بیومس ساختاری حجمی را نشان نمی‌دهد.`,
    });
  }

  const lstItem = findEvidenceItem(bundles, 'land_surface_temperature_day')?.item;
  if (lstItem && typeof lstItem.value === 'number') {
    known.push({
      id: 'k-lst',
      text: `دمای تابشی فیزیکی پوسته خاک (LST: ${lstItem.value.toFixed(1)} °C) در گذر روزانه سنجنده حرارتی مادیس ثبت گردید.`,
    });
  }

  const ndmiItem = findEvidenceItem(bundles, 'ndmi')?.item;
  if (ndmiItem && typeof ndmiItem.value === 'number') {
    known.push({
      id: 'k-ndmi',
      text: `پروکسی طیفی رطوبت کانوپی (NDMI: ${ndmiItem.value.toFixed(4)}) حاکی از بازتابش ضعیف رطوبت در باندهای مادون‌قرمز است.`,
    });
  }

  if (known.length === 0) {
    known.push({
      id: 'k-empty',
      text: 'شواهد پایه ماهواره‌ای در بازه زمانی انتخابی دریافت و پردازش شدند.',
    });
  }

  // Not yet concluded items (limitations & boundaries)
  notConcluded.push({
    id: 'nc-cause',
    text: 'علت کم‌پوشش بودن زمین (آیش فصلی، خشکی اقلیمی، شوری، جنس خاک یا عدم کاشت) صرفاً با داده‌های تک‌تصویر سنجش‌ازدور قابل تفکیک نیست.',
  });
  notConcluded.push({
    id: 'nc-soil',
    text: 'رطوبت دقیق خاک در سطح مزرعه (به دلیل وضوح درشت ۹ تا ۱۱ کیلومتری مدل‌های جهانی و واگرایی شبیه‌سازی‌های SMAP و ERA5).',
  });
  notConcluded.push({
    id: 'nc-diag',
    text: 'هرگونه تشخیص سلامت بیولوژیک، تشخیص آفت یا نسخه کودی/آبیاری بدون اعتبارسنجی زمینی و پایش چندساله فاقد پشتوانه علمی است.',
  });

  const rawLimits = asArray(result.limitations).filter(
    (entry): entry is string => typeof entry === 'string' && entry.trim().length > 0,
  );
  for (let i = 0; i < Math.min(rawLimits.length, 2); i++) {
    notConcluded.push({
      id: `nc-raw-${i}`,
      text: rawLimits[i],
    });
  }

  return { known, notConcluded };
}

/**
 * Extracts and aggregates all conflicts across evidence bundles.
 */
function extractAllConflicts(
  bundles: Record<string, EvidenceBundleResponse>,
): ConflictDetail[] {
  const result: ConflictDetail[] = [];
  for (const [bundleName, bundle] of Object.entries(bundles)) {
    if (!bundle || !Array.isArray(bundle.conflicts)) continue;
    for (const c of bundle.conflicts) {
      if (!c || typeof c !== 'object') continue;
      const conf = c as EvidenceConflictResponse;
      if (conf.status === 'conflicting' || conf.status === 'partially_consistent') {
        result.push({
          key: `${bundleName}-${conf.metric_a}-${conf.metric_b}`,
          domainName: bundleName,
          metricA: conf.metric_a,
          metricB: conf.metric_b,
          status: conf.status,
          explanation: conf.explanation || 'اختلاف میان مقادیر دو حسگر',
          possibleExplanations: asArray(conf.possible_explanations).filter(
            (entry): entry is string => typeof entry === 'string',
          ),
        });
      }
    }
  }
  return result;
}

export default function AnalysisOverviewSection({
  result,
}: AnalysisOverviewSectionProps) {
  const [showAllLimitations, setShowAllLimitations] = useState(false);
  const [showAllConflicts, setShowAllConflicts] = useState(false);
  const [showTechnicalConsistency, setShowTechnicalConsistency] = useState(false);

  const overall = result.overall_sufficiency;
  const meta = patternMetaFor(overall);
  const evidenceCount = countEvidenceItems(result);
  const unavailableCount = countUnavailableMetrics(result);
  const limitations = asArray(result.limitations).filter(
    (entry): entry is string => typeof entry === 'string' && entry.length > 0,
  );

  const bundles = asRecord(result.evidence_bundles) as Record<string, EvidenceBundleResponse> || {};
  const conflicts = extractAllConflicts(bundles);
  const findings = deriveKeyFindings(result, bundles);
  const { known: knownItems, notConcluded: notConcludedItems } = deriveKnownAndUncertainItems(result, bundles);

  // Dynamic context sentence strictly derived from response state
  const isInsufficient = overall === 'insufficient';
  const isLimited = overall === 'limited';
  const isSufficient = overall === 'sufficient';

  let contextSentence = '';
  if (isInsufficient) {
    contextSentence =
      'داده‌های ماهواره‌ای معتبر از سنجنده‌های نوری و راداری دریافت شده‌اند، اما شواهد موجود صرفاً برای توصیف سیگنال‌های پایه کافی است و برای نتیجه‌گیری جامع زراعی یا طبقه‌بندی قطعی وضعیت زمین کفایت نمی‌کند.';
  } else if (isLimited) {
    contextSentence =
      'شواهد ماهواره‌ای موجود دارای محدودیت‌های تفکیک مکانی یا زمانی است و نیازمند احتیاط در تفسیر می‌باشد.';
  } else if (isSufficient) {
    contextSentence =
      'شواهد ماهواره‌ای چندمنبعی کافی برای توصیف وضعیت سطحی زمین در دسترس است.';
  } else {
    contextSentence =
      'سیگنال‌های دریافتی نامطمئن بوده و امکان نتیجه‌گیری قطعی وجود ندارد.';
  }

  // Interpretation status
  let interpretationStatus = '';
  if (isInsufficient) {
    interpretationStatus =
      result.vegetation_regime === 'non_vegetated'
        ? 'سیگنال سازگار با پوشش ضعیف/تنک (عدم قطعیت در طبقه‌بندی قطعی)'
        : 'سیگنال‌های مشاهده‌شده ناکافی برای طبقه‌بندی قطعی';
  } else if (result.vegetation_regime === 'non_vegetated') {
    interpretationStatus = 'تفسیر وضعیت خاک لخت / بدون کانوپی';
  } else if (result.vegetation_regime === 'vegetated') {
    interpretationStatus = 'تفسیر سطح دارای پوشش گیاهی';
  } else {
    interpretationStatus = 'تفسیر محتاطانه بر پایه شواهد موجود';
  }

  const primaryLimitations = limitations.slice(0, 3);

  return (
    <section
      aria-label="Analysis interpretation overview"
      className="analysis-overview-container mb-4"
      data-testid="analysis-overview-section"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}
    >
      {/* 1. FIRST SCREEN: EXECUTIVE SUMMARY CARD */}
      <div
        className="card"
        data-testid="overall-status-card"
        style={{
          border: '1px solid #d0d7de',
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
        }}
      >
        <div
          className="card-header"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '8px',
            background: isInsufficient ? 'rgba(254, 252, 232, 0.7)' : 'inherit',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '1.25rem' }}>📋</span>
            <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 700 }}>
              خلاصه اجرایی وضعیت زمین — Executive Summary
            </span>
            <span
              className="badge"
              style={{ fontSize: '0.82rem', background: '#e8f5e9', color: '#1b5e20', fontWeight: 600 }}
              data-testid="synthesis-header-location-name"
            >
              📍 {result.location_name?.trim() || 'لوکیشن بدون نام'}
            </span>
            {result.time_start && (
              <span
                className="badge"
                style={{ fontSize: '0.8rem', background: '#e0f2fe', color: '#0369a1', fontWeight: 600 }}
                data-testid="overview-header-period"
                title={`${result.time_start} → ${result.time_end}`}
              >
                🗓 {formatPersianDateRange(result.time_start, result.time_end)}
              </span>
            )}
          </div>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            {result.vegetation_regime && (
              <span
                className={`badge ${
                  result.vegetation_regime === 'vegetated'
                    ? 'badge-success'
                    : result.vegetation_regime === 'non_vegetated'
                    ? 'badge-secondary'
                    : 'badge-warning'
                }`}
                title={result.vegetation_regime_explanation ?? undefined}
                data-testid="vegetation-regime-badge"
              >
                {isInsufficient && result.vegetation_regime === 'non_vegetated'
                  ? 'رژیم سازگار با پوشش ضعیف / تنک (شواهد ناکافی برای قطعیت)'
                  : result.vegetation_regime === 'non_vegetated'
                  ? 'خاک لخت / بدون پوشش (Non-vegetated)'
                  : result.vegetation_regime === 'vegetated'
                  ? 'دارای پوشش گیاهی (Vegetated)'
                  : 'رژیم نامشخص (Uncertain regime)'}
              </span>
            )}

            <span
              className={`badge ${sufficiencyBadgeClass(overall)}`}
              data-testid="overall-sufficiency-badge"
              style={{ fontSize: '0.85rem', padding: '4px 8px' }}
            >
              کفایت شواهد: {meta.labelFa} / {meta.label}
            </span>
          </div>
        </div>

        <div className="card-body">
          {/* Executive Q&A User-Facing Summary Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: '12px',
              marginBottom: '14px',
            }}
          >
            <div
              style={{
                background: '#f8fafc',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
              }}
            >
              <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, marginBottom: '4px' }}>
                ۱. دریافت داده‌های ماهواره‌ای:
              </div>
              <div style={{ fontSize: '0.88rem', color: '#0f172a', fontWeight: 600 }}>
                🟢 داده‌های ماهواره‌ای با موفقیت دریافت و پردازش شدند
              </div>
            </div>

            <div
              style={{
                background: '#f8fafc',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
              }}
            >
              <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, marginBottom: '4px' }}>
                ۲. وضعیت سیگنال مشاهده‌شده:
              </div>
              <div style={{ fontSize: '0.88rem', color: '#0f172a', fontWeight: 600 }}>
                {interpretationStatus}
              </div>
            </div>

            <div
              style={{
                background: '#f8fafc',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
              }}
            >
              <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, marginBottom: '4px' }}>
                ۳. کفایت برای نتیجه‌گیری جامع:
              </div>
              <div style={{ fontSize: '0.88rem', color: isInsufficient ? '#b45309' : '#15803d', fontWeight: 600 }}>
                {isInsufficient ? '🟡 شواهد ناکافی (محدود به مشاهدات پایه)' : isLimited ? '🟡 شواهد با محدودیت' : '🟢 شواهد کافی'}
              </div>
            </div>

            <div
              style={{
                background: '#f8fafc',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
              }}
            >
              <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, marginBottom: '4px' }}>
                ۴. ادعای کاربری یا نسخه زراعی:
              </div>
              <div style={{ fontSize: '0.88rem', color: '#64748b', fontWeight: 600 }}>
                ⛔ فاقد شواهد کافی (بدون ادعای تشخیصی یا نسخه)
              </div>
            </div>
          </div>

          {/* Context Explanatory Banner */}
          <div
            data-testid="analysis-context-sentence"
            style={{
              padding: '12px 14px',
              borderRadius: '6px',
              fontSize: '0.88rem',
              lineHeight: 1.6,
              background: isInsufficient ? '#fffbeb' : '#f0fdf4',
              color: isInsufficient ? '#92400e' : '#166534',
              border: `1px solid ${isInsufficient ? '#fef3c7' : '#bbf7d0'}`,
              marginBottom: result.vegetation_regime_explanation ? '10px' : 0,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 4 }}>
              {isInsufficient ? 'ℹ️ راهنمای تفسیر شواهد (کفایت داده‌ها):' : 'ℹ️ ارزیابی شواهد:'}
            </div>
            <div>{contextSentence}</div>
          </div>

          {/* Vegetation Regime Detailed Explanation (Backend Truth) */}
          {result.vegetation_regime_explanation && (
            <div
              className="text-muted"
              data-testid="regime-explanation"
              style={{
                fontSize: '0.82rem',
                lineHeight: 1.5,
                background: '#fafafa',
                padding: '8px 12px',
                borderRadius: '4px',
                border: '1px solid #eee',
              }}
            >
              <strong>مبنای علمی رژیم پوشش: </strong>
              <span>{result.vegetation_regime_explanation}</span>
            </div>
          )}
        </div>
      </div>

      {/* 2. TWO-COLUMN: KNOWN VS NOT CONCLUDED */}
      <div
        className="card"
        data-testid="known-vs-unknown-section"
        style={{ border: '1px solid #d0d7de' }}
      >
        <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '1.2rem' }}>⚖️</span>
          <span className="card-title" style={{ fontSize: '1rem', fontWeight: 700 }}>
            تفکیک شواهد — چه چیزهایی مشخص است و چه چیزهایی هنوز قابل نتیجه‌گیری نیست؟
          </span>
        </div>

        <div className="card-body">
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
              gap: '16px',
            }}
          >
            {/* Column 1: چه چیزهایی با اطمینان مشاهده شد؟ */}
            <div
              data-testid="known-evidence-column"
              style={{
                background: '#f0fdf4',
                border: '1px solid #bbf7d0',
                borderRadius: '6px',
                padding: '14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 700, color: '#166534', marginBottom: '10px' }}>
                <span>🟢</span>
                <span>چه چیزهایی با اطمینان مشاهده شد؟ (شواهد موجود)</span>
              </div>
              <ul style={{ margin: 0, paddingRight: '20px', fontSize: '0.84rem', lineHeight: 1.6, color: '#14532d' }}>
                {knownItems.map((item) => (
                  <li key={item.id} style={{ marginBottom: '6px' }}>
                    {item.text}
                  </li>
                ))}
              </ul>
            </div>

            {/* Column 2: چه چیزهایی هنوز قابل نتیجه‌گیری نیست؟ */}
            <div
              data-testid="not-concluded-column"
              style={{
                background: '#fefce8',
                border: '1px solid #fef08a',
                borderRadius: '6px',
                padding: '14px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 700, color: '#854d0e', marginBottom: '10px' }}>
                <span>🟡</span>
                <span>چه چیزهایی هنوز قابل نتیجه‌گیری نیست؟ (محدودیت‌ها)</span>
              </div>
              <ul style={{ margin: 0, paddingRight: '20px', fontSize: '0.84rem', lineHeight: 1.6, color: '#713f12' }}>
                {notConcludedItems.map((item) => (
                  <li key={item.id} style={{ marginBottom: '6px' }}>
                    {item.text}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* 3. THREE-LEVEL SCIENTIFIC COMMUNICATION GUIDE */}
      <div
        className="card"
        data-testid="scientific-levels-guide"
        style={{
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          padding: '10px 14px',
          borderRadius: '6px',
        }}
      >
        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#475569', marginBottom: '6px' }}>
          ℹ️ سطوح علمی استنتاج در تحلیل ماهواره‌ای (چارچوب تمایز ادراکی):
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '8px',
            fontSize: '0.78rem',
            lineHeight: 1.5,
          }}
        >
          <div style={{ background: '#fff', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}>
            <strong style={{ color: '#0369a1' }}>سطح A — مشاهده فیزیکی سنجنده:</strong>
            <div>اندازه‌گیری مستقیم یا بازتاب امواج نوری، راداری و حرارتی ماهواره (ارائه‌شده ✅).</div>
          </div>
          <div style={{ background: '#fff', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}>
            <strong style={{ color: '#0f766e' }}>سطح B — تفسیر شواهد:</strong>
            <div>برداشت محتاطانه از الگوهای سازگار با داده‌ها بدون ادعای قطعی میدانی (ارائه‌شده ✅).</div>
          </div>
          <div style={{ background: '#fff', padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}>
            <strong style={{ color: '#b45309' }}>سطح C — تشخیص زراعی:</strong>
            <div>تعیین بیماری، آفت، نیاز قطعی آبیاری یا نوع محصول (در داده‌های فعلی غیرقابل نتیجه‌گیری ⛔).</div>
          </div>
        </div>
      </div>

      {/* 4. KEY FINDINGS SECTION (4-LAYER PROGRESSIVE STRUCTURE) */}
      <div className="card" data-testid="key-findings-section">
        <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '1.2rem' }}>🔍</span>
          <span className="card-title" style={{ fontSize: '1.02rem', fontWeight: 700 }}>
            یافته‌های کلیدی — Key Findings
          </span>
          <span className="badge badge-info" style={{ fontSize: '0.72rem', marginRight: 'auto' }}>
            مشاهدات فیزیکی سنجش‌ازدور (بدون ادعای تشخیصی)
          </span>
        </div>

        <div className="card-body">
          <div className="text-muted" style={{ fontSize: '0.8rem', marginBottom: '14px' }}>
            مشاهدات زیر ترجمه علمی داده‌های برگشتی از ماهواره‌ها بر اساس ساختار ۴ سطحی (مشاهده، تفسیر شواهد، قطعیت و محدودیت ابزار) است.
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
              gap: '14px',
            }}
          >
            {findings.map((item) => (
              <div
                key={item.id}
                data-testid={`finding-card-${item.id}`}
                style={{
                  padding: '14px',
                  borderRadius: '8px',
                  border: '1px solid #e2e8f0',
                  background: '#ffffff',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '10px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 700, fontSize: '0.9rem' }}>
                    <span>{item.icon}</span>
                    <span>{item.categoryFa}</span>
                  </div>
                  <span
                    style={{
                      fontSize: '0.75rem',
                      fontFamily: 'monospace',
                      background: '#f1f5f9',
                      color: '#0f172a',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontWeight: 600,
                    }}
                  >
                    {item.metricSummary}
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem', lineHeight: 1.5 }}>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <strong style={{ minWidth: '95px', color: '#0369a1' }}>۱. مشاهده ماهواره:</strong>
                    <span style={{ color: '#1e293b' }}>{item.observation}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <strong style={{ minWidth: '95px', color: '#0f766e' }}>۲. تفسیر شواهد:</strong>
                    <span style={{ color: '#1e293b' }}>{item.interpretation}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <strong style={{ minWidth: '95px', color: '#475569' }}>۳. میزان قطعیت:</strong>
                    <span style={{ color: '#334155' }}>{item.confidence}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <strong style={{ minWidth: '95px', color: '#b45309' }}>۴. محدودیت ابزار:</strong>
                    <span style={{ color: '#451a03' }}>{item.limitation}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Soil Intelligence Summary (Phase P-AGRI-SOIL-2 §14) */}
      <div className="card" data-testid="soil-intelligence-overview-card" style={{ border: '1px solid #795548' }}>
        <div
          className="card-header d-flex justify-content-between align-items-center"
          style={{ background: '#efebe9' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.2rem' }}>🌱</span>
            <span className="card-title" style={{ fontSize: '1rem', fontWeight: 700, color: '#3e2723' }}>
              خلاصه وضعیت هوش خاک — Soil Intelligence Summary
            </span>
          </div>
          <span className="badge" style={{ backgroundColor: '#5d4037', color: '#fff', fontSize: '0.75rem' }}>
            وضعیت: Baseline — نیازمند راستی‌آزمایی آزمایشگاهی
          </span>
        </div>
        <div className="card-body">
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '10px',
              fontSize: '0.85rem',
              marginBottom: '12px',
            }}
          >
            <div style={{ padding: '8px 12px', background: '#f5f5f5', borderRadius: '6px', border: '1px solid #e0e0e0' }}>
              <span className="text-muted">رطوبت خاک (Soil Moisture): </span>
              <strong style={{ color: '#1565c0' }}>دردسترس (Available)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#f5f5f5', borderRadius: '6px', border: '1px solid #e0e0e0' }}>
              <span className="text-muted">کربن آلی (SOC): </span>
              <strong style={{ color: '#2e7d32' }}>خط مبنای مدل‌شده (Modelled baseline)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#f5f5f5', borderRadius: '6px', border: '1px solid #e0e0e0' }}>
              <span className="text-muted">اسیدیته (pH): </span>
              <strong style={{ color: '#6a1b9a' }}>خط مبنای مدل‌شده (Modelled baseline)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#f5f5f5', borderRadius: '6px', border: '1px solid #e0e0e0' }}>
              <span className="text-muted">نیتروژن کل (Total N): </span>
              <strong style={{ color: '#00695c' }}>خط مبنای مدل‌شده (Modelled baseline)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#fff5f5', borderRadius: '6px', border: '1px solid #ffcdd2' }}>
              <span className="text-muted">فسفر قابل جذب (Available P): </span>
              <strong style={{ color: '#c62828' }}>نیازمند آزمایش (Requires lab validation)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#fff5f5', borderRadius: '6px', border: '1px solid #ffcdd2' }}>
              <span className="text-muted">پتاسیم تبادلی (Exchangeable K): </span>
              <strong style={{ color: '#c62828' }}>نیازمند آزمایش (Requires lab validation)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#fff5f5', borderRadius: '6px', border: '1px solid #ffcdd2' }}>
              <span className="text-muted">نیترات خاک (Nitrate): </span>
              <strong style={{ color: '#c62828' }}>نیازمند آزمایش (Requires lab validation)</strong>
            </div>
            <div style={{ padding: '8px 12px', background: '#fff8e1', borderRadius: '6px', border: '1px solid #ffe082' }}>
              <span className="text-muted">اعتبارسنجی (Validation): </span>
              <strong style={{ color: '#e65100' }}>راستی‌آزمایی آزمایشگاهی الزامی</strong>
            </div>
          </div>
          <div className="d-flex justify-content-between align-items-center flex-wrap gap-2" style={{ fontSize: '0.82rem' }}>
            <span className="text-muted">
              * جزئیات لایه‌های عمقی و بافت خاک در صفحه تخصصی خاک در دسترس است.
            </span>
            <a href="/agriculture/soil" className="btn btn-sm btn-outline-primary" style={{ fontSize: '0.8rem' }}>
              مشاهده جزئیات کامل و پروفیل عمقی خاک ←
            </a>
          </div>
        </div>
      </div>

      {/* 5. EVIDENCE SUFFICIENCY (کفایت شواهد) */}
      <div className="card" data-testid="evidence-sufficiency-section">
        <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '1.2rem' }}>⚖️</span>
          <span className="card-title" style={{ fontSize: '1rem', fontWeight: 700 }}>
            کفایت شواهد — Evidence Sufficiency
          </span>
          <span className={`badge ${sufficiencyBadgeClass(overall)}`} style={{ marginRight: 'auto' }}>
            {meta.labelFa}
          </span>
        </div>

        <div className="card-body">
          <div style={{ fontSize: '0.85rem', lineHeight: 1.6, color: '#334155' }}>
            {isInsufficient ? (
              <div>
                <strong>شواهد در دسترس برای تفسیر جامع کافی نیست: </strong>
                با وجود دریافت سیگنال‌های معتبر برای شاخص‌های پایه (پوشش گیاهی و رادار سطحی)، به دلیل فقدان یا کیفیت پایین برخی شاخص‌های حیاتی (مانند داده‌های مستقیم تبخیر-تعرق، وضوح درشت ۹ کیلومتری رطوبت خاک، یا نبود مشاهدات سری زمانی چندساله)، امکان ارائه تفسیری جامع و مستحکم وجود ندارد.
              </div>
            ) : isLimited ? (
              <div>
                <strong>شواهد در دسترس دارای محدودیت است: </strong>
                حجم شواهد برای توصیف اولیه کافی است، اما محدودیت‌هایی مانند وضوح مکانی درشت در برخی لایه‌ها تفسیر را نیازمند احتیاط می‌سازد.
              </div>
            ) : (
              <div>
                <strong>شواهد کافی در دسترس است: </strong>
                تعداد و کیفیت داده‌های ماهواره‌ای چندمنبعی برای تشریح وضعیت عمومی سطح زمین کفایت می‌کند.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 6. ANALYSIS LIMITATIONS (محدودیت‌های تحلیل — افشای تدریجی) */}
      {limitations.length > 0 && (
        <div className="card" data-testid="important-limitations-section">
          <div className="card-header" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.2rem' }}>ℹ️</span>
            <span className="card-title" style={{ fontSize: '1rem', fontWeight: 700 }}>
              محدودیت‌های تحلیل — Analysis Limitations ({limitations.length} مورد)
            </span>
          </div>

          <div className="card-body">
            <ul style={{ margin: 0, paddingRight: '20px', fontSize: '0.83rem', lineHeight: 1.5, color: '#475569' }}>
              {(showAllLimitations ? limitations : primaryLimitations).map((lim, index) => (
                <li key={index} style={{ marginBottom: '4px' }}>
                  {lim}
                </li>
              ))}
            </ul>

            {limitations.length > 3 && (
              <button
                type="button"
                className="btn btn-sm btn-outline mt-2"
                onClick={() => setShowAllLimitations(!showAllLimitations)}
                style={{ fontSize: '0.78rem' }}
                data-testid="toggle-limitations-btn"
              >
                {showAllLimitations
                  ? 'نمایش خلاصه محدودیت‌ها'
                  : `نمایش تمام جزئیات فنی محدودیت‌ها (${limitations.length} مورد)`}
              </button>
            )}
          </div>
        </div>
      )}

      {/* 7. TECHNICAL SYSTEM CONSISTENCY & TELEMETRY (COLLAPSED BY DEFAULT AT BOTTOM) */}
      <div
        className="card"
        data-testid="technical-system-consistency-section"
        style={{
          border: '1px solid #cbd5e1',
          background: '#f8fafc',
          marginTop: '8px',
        }}
      >
        <div
          className="card-header"
          onClick={() => setShowTechnicalConsistency(!showTechnicalConsistency)}
          style={{
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '8px',
            background: '#f1f5f9',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.2rem' }}>🛠️</span>
            <span className="card-title" style={{ fontSize: '0.98rem', fontWeight: 700, color: '#334155' }}>
              تلمتری و بررسی‌های فنی سیستم — Technical System Consistency
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="badge badge-secondary" style={{ fontSize: '0.75rem' }}>
              {showTechnicalConsistency
                ? 'بستن تلمتری فنی 🔼'
                : `نمایش تلمتری و بررسی‌های فنی (${conflicts.length} بررسی کنترلی) 🔽`}
            </span>
          </div>
        </div>

        {/* Kept in DOM with conditional display for DOM audit compatibility & clean default collapse */}
        <div
          className="card-body"
          style={{ display: showTechnicalConsistency ? 'block' : 'none' }}
        >
          {/* Technical Counters Pill Strip */}
          <div
            style={{
              display: 'flex',
              gap: '12px',
              flexWrap: 'wrap',
              marginBottom: '14px',
              padding: '10px 12px',
              background: '#ffffff',
              borderRadius: '6px',
              border: '1px solid #e2e8f0',
              fontSize: '0.82rem',
            }}
          >
            <div>
              <span className="text-muted">ورودی‌های شواهد در دامین‌ها: </span>
              <strong style={{ color: '#16a34a' }}>{evidenceCount} قلم</strong>
            </div>
            <span style={{ color: '#cbd5e1' }}>|</span>
            <div>
              <span className="text-muted">بررسی‌های ناسازگار جفت‌شاخص: </span>
              <strong style={{ color: conflicts.length > 0 ? '#b45309' : '#64748b' }}>
                {conflicts.length} مورد
              </strong>
            </div>
            {unavailableCount > 0 && (
              <>
                <span style={{ color: '#cbd5e1' }}>|</span>
                <div>
                  <span className="text-muted">شاخص‌های ناموجود ثبت‌شده: </span>
                  <strong style={{ color: '#64748b' }}>{unavailableCount} مورد</strong>
                </div>
              </>
            )}
          </div>

          <div style={{ fontSize: '0.82rem', color: '#475569', lineHeight: 1.6, marginBottom: '14px' }}>
            <strong>توضیح تلمتری: </strong>
            این بخش اطلاعات عیب‌یابی و بررسی‌های کنترل سازگاری داخلی سیستم را نشان می‌دهد. مقایسه خودکار جفت‌شاخص‌ها (Pairwise Consistency Checks) شامل ارزیابی ابعادی متغیرهای درون هر دامین است؛ ناسازگاری واحدهای فیزیکی (مانند درجه سانتی‌گراد در مقابل درصد یا کسر بدون بعد) یک بررسی ساختاری مهندسی نرم‌افزار است و به معنی مشکل در زمین کشاورزی یا شکست تحلیل نیست.
          </div>

          {/* Conflicting Signals Section (Pairwise Consistency Checks) */}
          {conflicts.length > 0 && (
            <div
              className="card"
              data-testid="conflicts-section"
              style={{ border: '1px solid #fed7aa', marginBottom: '12px' }}
            >
              <div
                className="card-header"
                style={{
                  background: '#fff7ed',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '1.1rem' }}>⚠️</span>
                  <span className="card-title" style={{ fontSize: '0.92rem', fontWeight: 700, color: '#c2410c' }}>
                    تعارض شواهد و بررسی‌های جفت‌شاخص — Pairwise Consistency Checks ({conflicts.length} مورد)
                  </span>
                </div>
                <span className="badge badge-warning" style={{ fontSize: '0.72rem' }}>
                  عدم انطباق ابعادی واحدها و واگرایی مدل‌ها
                </span>
              </div>

              <div className="card-body">
                <div style={{ fontSize: '0.82rem', color: '#9a3412', marginBottom: '10px', lineHeight: 1.5 }}>
                  سنجنده‌ها و مدل‌های ماهواره‌ای بر اساس بررسی‌های زوجی درون هر دامین ارزیابی شده‌اند (تعارض شواهد فنی). از {conflicts.length} مورد جفت‌شاخص ثبت‌شده، عمده موارد ناشی از مقایسه شاخص‌های با ابعاد یا واحدهای ناسازگار (مانند دما در مقابل کسر بی‌بعد) بوده و شامل واگرایی فیزیکی مدل‌های جهانی رطوبت خاک (SMAP در مقابل ERA5) نیز می‌باشد. سیستم از نتیجه‌گیری ساختگی خودداری کرده و این تفاوت‌ها را افشا می‌کند:
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {(showAllConflicts ? conflicts : conflicts.slice(0, 4)).map((c) => (
                    <div
                      key={c.key}
                      style={{
                        padding: '8px 12px',
                        borderRadius: '6px',
                        background: '#fffbeb',
                        border: '1px solid #fef3c7',
                        fontSize: '0.8rem',
                        lineHeight: 1.4,
                      }}
                    >
                      <div style={{ fontWeight: 600, color: '#b45309', marginBottom: '2px' }}>
                        اختلاف میان <code>{c.metricA}</code> و <code>{c.metricB}</code> ({c.domainName})
                      </div>
                      <div style={{ color: '#78350f' }}>{c.explanation}</div>
                      {c.possibleExplanations.length > 0 && (
                        <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#92400e' }}>
                          علل احتمالی: {c.possibleExplanations.join(' • ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {conflicts.length > 4 && (
                  <button
                    type="button"
                    className="btn btn-sm btn-outline mt-2"
                    onClick={() => setShowAllConflicts(!showAllConflicts)}
                    style={{ fontSize: '0.75rem' }}
                  >
                    {showAllConflicts
                      ? 'بستن فهرست تعارض‌ها'
                      : `نمایش تمام تعارض‌ها (${conflicts.length} مورد)`}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
