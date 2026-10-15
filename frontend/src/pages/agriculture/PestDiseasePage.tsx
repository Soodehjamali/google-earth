import { useState, useCallback } from 'react';
import { agricultureApi } from '../../api/agriculture';
import type {
  AgriculturalAnalysisResponse,
  AgricultureGeometry,
  GroundTruthObservation,
  PestDiseaseInspectionResponse,
} from '../../types';
import { GroundTruthForm } from '../../components/agriculture/GroundTruthForm';
import { GroundTruthValidationTable } from '../../components/agriculture/GroundTruthValidationTable';
import { PestDiseaseInspectionSection } from '../../components/agriculture/PestDiseaseInspectionSection';
import Historical10YearSection from '../../components/agriculture/Historical10YearSection';
import OrchardHeatmapSwipeSection from '../../components/agriculture/OrchardHeatmapSwipeSection';
import JalaliDatePicker from '../../components/agriculture/JalaliDatePicker';
import { formatPersianDateRange, toPersianDigits } from '../../components/agriculture/persianDate';
import { useAgricultureContext } from '../../components/agriculture/AgricultureLayout';

interface PestDiseasePageProps {
  initialTab?: 'inspection' | 'validation' | 'history' | 'swipe';
}

export const PestDiseasePage = ({ initialTab = 'inspection' }: PestDiseasePageProps) => {
  let parentContext: ReturnType<typeof useAgricultureContext> | null = null;
  try {
    parentContext = useAgricultureContext();
  } catch {
    parentContext = null;
  }

  const isSavedReport = Boolean(parentContext?.savedAnalysisId);
  const contextResult = parentContext?.result ?? null;
  const isContextLoading = Boolean(parentContext?.loading);
  const activeError = parentContext?.error || null;

  // Active view tab
  const [activeTab, setActiveTab] = useState<'inspection' | 'validation' | 'history' | 'swipe'>(initialTab);
  const [showManualControls, setShowManualControls] = useState<boolean>(!isSavedReport);

  // Coordinates for Ardakan Pistachio Orchard (verified test site)
  const [lat, setLat] = useState<number>(32.4279);
  const [lon, setLon] = useState<number>(53.688);
  const [startDate, setStartDate] = useState<string>('2024-05-01');
  const [startJalali, setStartJalali] = useState<string>('1403/02/12');
  const [endDate, setEndDate] = useState<string>('2024-08-31');
  const [endJalali, setEndJalali] = useState<string>('1403/06/10');
  const [cloudMax, setCloudMax] = useState<number>(20);

  // Ground truth collection
  const [groundTruth, setGroundTruth] = useState<GroundTruthObservation[]>([]);

  // API states
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [analysisResponse, setAnalysisResponse] = useState<AgriculturalAnalysisResponse | null>(null);
  const [inspectionResult, setInspectionResult] = useState<PestDiseaseInspectionResponse | null>(null);

  const activeInspection = isSavedReport
    ? (contextResult?.pest_disease_inspection ?? null)
    : (inspectionResult ?? contextResult?.pest_disease_inspection ?? null);

  const activeValidation = isSavedReport
    ? (contextResult?.validation ?? null)
    : (analysisResponse?.validation ?? contextResult?.validation ?? null);

  const effectiveStartDate = (isSavedReport && contextResult?.time_start) ? contextResult.time_start : startDate;
  const effectiveEndDate = (isSavedReport && contextResult?.time_end) ? contextResult.time_end : endDate;

  const currentGeometry: AgricultureGeometry = (isSavedReport && parentContext?.lastRequest?.geometry)
    ? parentContext.lastRequest.geometry
    : {
        type: 'Point',
        coordinates: [lon, lat],
      };

  const handleLoadSampleGroundTruth = () => {
    const sampleObs: GroundTruthObservation = {
      observation_id: 'gt-ardakan-01',
      variable: 'ndvi',
      metric_key: 'ndvi',
      value: 0.26,
      unit: 'index',
      state: 'stressed',
      observed_on: '2024-05-20',
      source: 'test_fixture',
      method: 'field_inspection',
      quality: 'test',
      crop_type: 'پسته کله‌قوچی اردکان',
      growth_stage: 'پر شدن مغز و تکامل میوه',
      observed_stress: 'زردی حاشیه برگ و تنک‌شدگی تاج در ردیف‌های میانی',
      pest_observation: 'مشاهده پوره پسیل روی برگ‌های آفتاب‌رو (شدت متوسط)',
      disease_observation: 'عدم مشاهده علائم لکه‌برگی قارچی یا پوسیدگی طوقه',
      irrigation_status: 'آبیاری غرقابی هر ۲۴ روز با آب شور (EC=4.2 dS/m)',
      notes: 'داده آزمایشی شبیه‌سازی‌شده برای تست رابط کاربری (synthetic/test fixture — not real ground truth)',
      is_derived: false,
      is_test_fixture: true,
      status: 'available',
    };
    setGroundTruth([sampleObs]);
  };

  const handleAddObservation = (obs: GroundTruthObservation) => {
    setGroundTruth((prev) => [obs, ...prev]);
  };

  const handleRemoveObservation = (id: string) => {
    setGroundTruth((prev) => prev.filter((o) => o.observation_id !== id));
  };

  const runInspection = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Step 1: Execute full agricultural analysis with ground truth attached
      const analysisReq = {
        geometry: currentGeometry,
        start_date: startDate,
        end_date: endDate,
        domains: ['vegetation', 'water', 'thermal', 'stress', 'climate', 'soil', 'pest_disease'],
        cloud_max_percent: cloudMax,
        ground_truth: groundTruth.length > 0 ? groundTruth : undefined,
      };

      const analysisResp = await agricultureApi.analyze(analysisReq);
      setAnalysisResponse(analysisResp);

      // Step 2: If pest_disease_inspection is attached, use it; otherwise run dedicated inspection endpoint
      if (analysisResp.pest_disease_inspection) {
        setInspectionResult(analysisResp.pest_disease_inspection);
      } else {
        const inspectReq = {
          geometry: currentGeometry,
          start_date: startDate,
          end_date: endDate,
          ground_truth: groundTruth.length > 0 ? groundTruth : undefined,
          cloud_max_percent: cloudMax,
        };
        const inspectResp = await agricultureApi.inspectPestDisease(inspectReq);
        setInspectionResult(inspectResp);
      }
    } catch (err: any) {
      setError(err?.message || 'خطا در ارتباط با سرور یا پردازش داده‌های ماهواره‌ای');
    } finally {
      setLoading(false);
    }
  }, [currentGeometry, startDate, endDate, cloudMax, groundTruth]);

  const hasPestDiseaseData = Boolean(activeInspection || activeValidation);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-8" dir="rtl">
      {/* Page Header */}
      <div className="mb-6 border-b border-slate-800 pb-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-2xl">🔬</span>
              <h1 className="text-2xl font-black text-slate-100">
                پایش آفت و بیماری و اعتبارسنجی زمینی (Pest/Disease & Ground Truth)
              </h1>
            </div>
            <p className="text-xs md:text-sm text-slate-400 max-w-4xl leading-relaxed">
              غربالگری ریسک چندسنسوری (اپتیکال Sentinel-2، رادار Sentinel-1، حرارتی LST) و اعتبارسنجی هم‌مکانی با داده‌های واقعی میدانی (سطوح ۰ تا ۴).
              <span className="text-amber-400 font-medium mr-1">
                صرفاً پایش ریسک و آنومالی؛ بدون تشخیص قطعی بیماری و بدون تجویز سم.
              </span>
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="bg-slate-900 border border-slate-800 text-slate-300 text-xs px-3 py-1.5 rounded-lg font-mono">
              بازه تقویمی: {formatPersianDateRange(effectiveStartDate, effectiveEndDate)}
            </span>
          </div>
        </div>
      </div>

      {/* Persistent History Banner */}
      {isSavedReport && contextResult && (
        <div
          data-testid="retrieved-from-history-banner"
          className="mb-6 bg-slate-900/90 border border-emerald-500/40 rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 text-xs shadow-md"
        >
          <div className="flex items-center gap-2.5">
            <span className="text-emerald-400 text-xl">💾</span>
            <div>
              <div className="font-bold text-slate-200">
                داده‌های پایش آفت/بیماری از گزارش ذخیره‌شده بازیابی شد (شناسه: {toPersianDigits(parentContext?.savedAnalysisId || '')})
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5">
                بدون فراخوانی مجدد موتور گوگل ارث (GEE) • بازه تحلیل: {formatPersianDateRange(effectiveStartDate, effectiveEndDate)}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="bg-emerald-950/80 border border-emerald-700/60 text-emerald-300 text-[11px] px-2.5 py-1 rounded">
              گزارش ماندگار
            </span>
            <button
              type="button"
              onClick={() => setShowManualControls((prev) => !prev)}
              className="text-xs text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-lg border border-slate-700 transition cursor-pointer"
            >
              {showManualControls ? 'بستن فرم اجرای مجدد ▲' : 'تنظیمات و اجرای مجدد دستی ▼'}
            </button>
          </div>
        </div>
      )}

      {/* Orchard Parcel Context Card (Preserving polygon boundary & coordinates without re-entry) */}
      <div
        data-testid="pest-orchard-context-card"
        className="mb-6 bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs shadow-md"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <div className="flex items-center gap-2">
            <span className="text-emerald-400 text-lg">🏡</span>
            <span className="font-bold text-slate-100 text-sm">
              محدوده جغرافیایی و مشخصات باغ مورد تحلیل
            </span>
            <span className="bg-slate-800 text-emerald-400 px-2 py-0.5 rounded text-[11px] font-medium border border-slate-700">
              {currentGeometry.type === 'Polygon' ? 'چندضلعی اختصاصی باغ (Polygon)' : 'نقطه مکانی (GPS Point)'}
            </span>
          </div>
          {isSavedReport && (
            <span className="text-slate-400 text-[11px]">
              محدوده مستقیماً از context تحلیل جاری دریافت شد — بدون نیاز به ورود مجدد مختصات
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-slate-300 bg-slate-950/60 p-3 rounded-lg border border-slate-800/80">
          <div>
            <span className="text-slate-400">نام قطعه / باغ: </span>
            <strong className="text-slate-100">
              {parentContext?.lastRequest?.name || contextResult?.location_name || 'باغ انتخاب‌شده'}
            </strong>
          </div>
          <div>
            <span className="text-slate-400">نوع هندسه: </span>
            <strong className="text-slate-100">
              {currentGeometry.type === 'Polygon'
                ? `چندضلعی (${toPersianDigits(
                    Array.isArray(currentGeometry.coordinates?.[0])
                      ? (currentGeometry.coordinates[0] as unknown[]).length
                      : 0
                  )} نقطه راس)`
                : 'نقطه GPS مرکز'}
            </strong>
          </div>
          <div>
            <span className="text-slate-400">مساحت تقریبی: </span>
            <strong className="text-slate-100">
              {contextResult?.area_sq_meters
                ? `${toPersianDigits((contextResult.area_sq_meters / 10000).toFixed(2))} هکتار`
                : 'محاسبه‌شده بر روی هندسه'}
            </strong>
          </div>
        </div>

        {/* Scientific Non-Claim Advisory */}
        <div className="mt-3 p-3 bg-amber-950/30 border border-amber-700/40 rounded-lg text-amber-300 text-[11px] leading-relaxed flex items-start gap-2">
          <span className="text-base mt-[-2px]">⚠️</span>
          <div>
            <strong>تذکر علمی و قانونی سنجش از دور:</strong> شواهد ماهواره‌ای (افت شادابی، خشکی کانوپی یا ناهنجاری دمایی) صرفاً غربالگری تنش و هدایت اولویت‌های سرکشی هستند. تفکیک قطعی نوع آفت یا عامل بیماری‌زا (پسیل، نماتد، لکه‌برگی، فوزاریوم و غیره) بدون نمونه‌برداری میدانی کارشناس و آزمایشگاه گیاه‌پزشکی فاقد قطعیت علمی است.
          </div>
        </div>
      </div>

      {/* Loading State */}
      {isContextLoading && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 mb-6 text-center text-slate-400 text-xs shadow-md">
          <div className="inline-block w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-3"></div>
          <div>در حال بارگذاری اطلاعات گزارش ذخیره‌شده...</div>
        </div>
      )}

      {/* Error Banner */}
      {(activeError || error) && (
        <div className="bg-rose-950/40 border border-rose-800/60 rounded-xl p-4 text-xs text-rose-300 mb-6 flex items-center gap-2">
          <span>❌</span>
          <span>{activeError || error}</span>
        </div>
      )}

      {/* Control Panel: Coordinates & Parameters (Collapsible when viewing saved report) */}
      {showManualControls && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-6 shadow-md">
          <div className="text-xs font-bold text-slate-300 mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span>📍</span>
              <span>مختصات جغرافیایی و تنظیمات تحلیل دستی</span>
            </div>
            {isSavedReport && (
              <span className="text-[11px] text-amber-400 font-normal">
                (اجرای این فرم گزارش جدید ایجاد خواهد کرد)
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 mb-4 text-xs">
            <div>
              <label className="block text-slate-400 mb-1">عرض جغرافیایی (Latitude):</label>
              <input
                type="number"
                step="0.0001"
                value={lat}
                onChange={(e) => setLat(parseFloat(e.target.value) || 0)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">طول جغرافیایی (Longitude):</label>
              <input
                type="number"
                step="0.0001"
                value={lon}
                onChange={(e) => setLon(parseFloat(e.target.value) || 0)}
                className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-100 font-mono focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <JalaliDatePicker
                label="شروع بازه (تقویم جلالی)"
                valueJalali={startJalali}
                onChange={(jAscii, isoGreg) => {
                  setStartJalali(jAscii);
                  setStartDate(isoGreg);
                }}
              />
            </div>
            <div>
              <JalaliDatePicker
                label="پایان بازه (تقویم جلالی)"
                valueJalali={endJalali}
                onChange={(jAscii, isoGreg) => {
                  setEndJalali(jAscii);
                  setEndDate(isoGreg);
                }}
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">حداکثر ابر ({toPersianDigits(cloudMax)}٪):</label>
              <input
                type="range"
                min="0"
                max="50"
                value={cloudMax}
                onChange={(e) => setCloudMax(parseInt(e.target.value, 10))}
                className="w-full mt-2 accent-emerald-500 cursor-pointer"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-800/80">
            <div className="text-[11px] text-slate-400 flex items-center gap-2">
              <span>مزرعه پیش‌فرض:</span>
              <button
                type="button"
                onClick={() => {
                  setLat(32.4279);
                  setLon(53.688);
                  setStartDate('2024-05-01');
                  setStartJalali('1403/02/12');
                  setEndDate('2024-08-31');
                  setEndJalali('1403/06/10');
                }}
                className="text-emerald-400 hover:underline"
              >
                باغ پسته اردکان، یزد ({toPersianDigits('32.4279')}, {toPersianDigits('53.6880')})
              </button>
            </div>

            <button
              type="button"
              onClick={runInspection}
              disabled={loading}
              className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white font-bold text-xs rounded-xl shadow-lg transition-all flex items-center gap-2 cursor-pointer"
            >
              {loading ? (
                <>
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                  <span>در حال دریافت و تحلیل داده‌های چندسنسوری...</span>
                </>
              ) : (
                <>
                  <span>🛰️</span>
                  <span>اجرای پایش چندسنسوری آفت و بیماری و اعتبارسنجی زمینی</span>
                </>
              )}
            </button>
          </div>

          {/* Ground Truth Observations Section inside manual controls */}
          <div className="mt-4 pt-4 border-t border-slate-800">
            <GroundTruthForm
              observations={groundTruth}
              onAddObservation={handleAddObservation}
              onRemoveObservation={handleRemoveObservation}
              onLoadSampleData={handleLoadSampleGroundTruth}
            />
          </div>
        </div>
      )}

      {/* Honest Unavailable State when viewing saved report without pest/disease data */}
      {isSavedReport && !isContextLoading && contextResult && !hasPestDiseaseData && (
        <div
          data-testid="pest-disease-unavailable-card"
          className="bg-slate-900 border border-amber-600/30 rounded-xl p-6 text-center text-slate-300 shadow-md mb-6"
        >
          <div className="text-3xl mb-2">📋</div>
          <h3 className="font-bold text-slate-100 text-sm mb-2">
            داده‌های پایش آفت، بیماری یا اعتبارسنجی زمینی در این گزارش ثبت نشده است
          </h3>
          <p className="text-xs text-slate-400 max-w-xl mx-auto leading-relaxed mb-4">
            در تحلیل ذخیره‌شده جاری، حوزه پایش آفت/بیماری انتخاب نشده یا مشاهدات میدانی برای اعتبارسنجی ثبت نگردیده بود.
            سیستم از نمایش مقادیر پیش‌فرض یا صفر مصنوعی خودداری می‌کند.
          </p>
          <button
            type="button"
            onClick={() => setShowManualControls(true)}
            className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-lg border border-slate-700 transition cursor-pointer"
          >
            تنظیم و اجرای تحلیل جدید برای این قطعه زمین
          </button>
        </div>
      )}

      {/* No analysis selected state */}
      {!isSavedReport && !contextResult && !inspectionResult && !loading && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center text-slate-400 text-xs shadow-md">
          <div className="text-3xl mb-2">🔍</div>
          <div className="font-medium text-slate-300 mb-1">هیچ تحلیلی انتخاب یا اجرا نشده است</div>
          <div className="text-[11px] text-slate-500">
            می‌توانید از فرم بالا تحلیلی جدید اجرا کنید یا از منوی تاریخچه، یکی از گزارش‌های قبلی را برگزینید.
          </div>
        </div>
      )}

      {/* Main Analysis Output with Tabs */}
      {hasPestDiseaseData && (
        <div className="space-y-4">
          {/* Navigation Tabs */}
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-2">
            {activeInspection && (
              <button
                type="button"
                onClick={() => setActiveTab('inspection')}
                className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors flex items-center gap-1.5 ${
                  activeTab === 'inspection'
                    ? 'bg-emerald-600 text-white shadow'
                    : 'bg-slate-900 text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>🔬</span>
                <span>پایش آفت و بیماری (غربالگری ریسک)</span>
              </button>
            )}

            {activeValidation && (
              <button
                type="button"
                onClick={() => setActiveTab('validation')}
                className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors flex items-center gap-1.5 ${
                  activeTab === 'validation'
                    ? 'bg-emerald-600 text-white shadow'
                    : 'bg-slate-900 text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>📊</span>
                <span>جدول اعتبارسنجی علمی زمینی</span>
              </button>
            )}

            <button
              type="button"
              onClick={() => setActiveTab('history')}
              className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors flex items-center gap-1.5 ${
                activeTab === 'history'
                  ? 'bg-emerald-600 text-white shadow'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200'
              }`}
            >
              <span>📅</span>
              <span>مقایسه تاریخی ۱۰ ساله (تقویم جلالی)</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab('swipe')}
              className={`px-4 py-2 text-xs font-bold rounded-lg transition-colors flex items-center gap-1.5 ${
                activeTab === 'swipe'
                  ? 'bg-emerald-600 text-white shadow'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200'
              }`}
            >
              <span>🗺️</span>
              <span>مقایسه کشویی باغ ↔ نقشه‌های حرارتی</span>
            </button>
          </div>

          {/* Tab 1: Pest & Disease Inspection */}
          {activeTab === 'inspection' && activeInspection && (
            <PestDiseaseInspectionSection inspection={activeInspection} />
          )}

          {/* Tab 2: Ground Truth Validation Table */}
          {activeTab === 'validation' && activeValidation && (
            <GroundTruthValidationTable validation={activeValidation} />
          )}

          {/* Tab 3: Historical 10-Year Comparison */}
          {activeTab === 'history' && (
            <Historical10YearSection
              geometry={currentGeometry}
              startDate={effectiveStartDate}
              endDate={effectiveEndDate}
              cloudMaxPercent={cloudMax}
              disableAutoFetch={isSavedReport}
              titleFa="مقایسه ۱۰ ساله دوره مشابه: پایش روند تاریخی تنش و شادابی باغ"
            />
          )}

          {/* Tab 4: Interactive Heatmap Swipe */}
          {activeTab === 'swipe' && (
            <OrchardHeatmapSwipeSection
              geometry={currentGeometry}
              startDate={effectiveStartDate}
              endDate={effectiveEndDate}
              cloudMaxPercent={cloudMax}
              initialMetric="ndvi"
              allowedMetrics={['ndvi', 'ndre', 'ndmi', 'msi', 'lst_day', 'sar_vh']}
              disableAutoFetch={isSavedReport}
              titleFa="مقایسه کشویی: تصویر ماهواره‌ای باغ ↔ لایه‌های رستری تنش (NDVI/NDRE/LST/SAR)"
            />
          )}
        </div>
      )}
    </div>
  );
};

export default PestDiseasePage;
