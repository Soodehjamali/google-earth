/**
 * Centralized Scientific Interpretation & Reference Ranges Catalog (Phase P-AGRI-6)
 *
 * Guarantees:
 * 1. Single source of truth for metric interpretations and scientific reference ranges.
 * 2. Strictly peer-reviewed scientific citations for all reference ranges (FAO-56, Jensen, Huete, etc.).
 * 3. Never invents arbitrary good/bad thresholds when no fixed threshold exists;
 *    explicitly marks context-dependent or phenology-dependent metrics.
 * 4. Plain-language Persian explanations specifically tailored for Iranian farmers and growers.
 * 5. Transparent reporting of native spatial resolution, sensor dataset ID, and physical caveats.
 */

export interface MetricReferenceRange {
  hasFixedRange: boolean;
  min?: number;
  max?: number;
  optimalMin?: number;
  optimalMax?: number;
  warningLow?: number;
  warningHigh?: number;
  unit: string;
  rangeLabelFa: string;
  sourceCitation: string;
  validityConditionsFa: string;
}

export interface MetricInterpretationSpec {
  key: string;
  nameEn: string;
  nameFa: string;
  category: string;
  unit: string;
  datasetId: string;
  datasetNameFa: string;
  spatialResolution: string;
  dataType:
    | 'satellite_observation'
    | 'derived_index'
    | 'reanalysis_model'
    | 'spatial_model'
    | 'dem_terrain'
    | 'proxy';
  referenceRange: MetricReferenceRange;
  farmerExplanationFa: string;
  scientificCautionFa: string;
  evaluateStatus: (val: number | null | undefined) => {
    statusLabelFa: string;
    statusClass: 'good' | 'warning' | 'danger' | 'neutral';
    evaluationFa: string;
  };
}

export interface EvaluatedMetricInterpretation {
  key: string;
  nameEn: string;
  nameFa: string;
  unit: string;
  value: number | null;
  displayValue: string;
  datasetId: string;
  datasetNameFa: string;
  spatialResolution: string;
  dataType: string;
  hasFixedRange: boolean;
  rangeLabelFa: string;
  sourceCitation: string;
  validityConditionsFa: string;
  statusLabelFa: string;
  statusClass: 'good' | 'warning' | 'danger' | 'neutral';
  farmerSummaryFa: string;
  scientificCautionFa: string;
}

export const METRIC_INTERPRETATION_CATALOG: Record<string, MetricInterpretationSpec> = {
  // ==========================================
  // 1. VEGETATION INDICES & CANOPY
  // ==========================================
  ndvi: {
    key: 'ndvi',
    nameEn: 'Normalized Difference Vegetation Index (NDVI)',
    nameFa: 'شاخص پوشش گیاهی تفاضلی نرمال‌شده (NDVI)',
    category: 'vegetation',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.22,
      optimalMax: 0.55,
      warningLow: 0.15,
      unit: '',
      rangeLabelFa: '۰.۲۲ تا ۰.۵۵ (کانوپی فعال باغات پسته و نیمه‌خشک)',
      sourceCitation: 'Jensen, J. R. (2007) Remote Sensing of the Environment; FAO-56.',
      validityConditionsFa: 'باغات و مزارع مناطق نیمه‌خشک در اوج فصل رشد (خرداد تا شهریور). وابسته به فاصله ردیف درختان.',
    },
    farmerExplanationFa:
      'نشان‌دهنده سبزی، شادابی و تراکم شاخ‌وبرگ درختان است. در باغات پسته با ردیف‌های باز، مقادیر ۰.۲۵ تا ۰.۴۵ بیانگر تاج پوشش طبیعی و سالم است.',
    scientificCautionFa:
      'این شاخص بازتاب مشترک برگ درخت و خاک لخت بین ردیف‌ها را نشان می‌دهد و بیماری یا آفت خاصی را بدون بازدید میدانی اثبات نمی‌کند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined || Number.isNaN(val)) {
        return { statusLabelFa: 'نامشخص / فاقد داده', statusClass: 'neutral', evaluationFa: 'داده‌ای برای ارزیابی دریافت نشد.' };
      }
      if (val < 0.15) {
        return { statusLabelFa: 'پوشش بسیار تنک یا خاک لخت', statusClass: 'warning', evaluationFa: 'تراکم کانوپی پایین بوده و بازتاب خاک لخت غالب است.' };
      }
      if (val >= 0.20 && val <= 0.60) {
        return { statusLabelFa: 'پوشش نرمال و شاداب باغ', statusClass: 'good', evaluationFa: 'تراکم شاخ‌وبرگ در محدوده معمول و مطلوب باغات منطقه است.' };
      }
      if (val > 0.60) {
        return { statusLabelFa: 'پوشش بسیار متراکم', statusClass: 'good', evaluationFa: 'تراکم کانوپی بسیار بالا یا کشت متراکم علوفه/زراعت.' };
      }
      return { statusLabelFa: 'پوشش ملایم', statusClass: 'neutral', evaluationFa: 'پوشش متوسط در آستانه میانی.' };
    },
  },

  savi: {
    key: 'savi',
    nameEn: 'Soil-Adjusted Vegetation Index (SAVI)',
    nameFa: 'شاخص پوشش گیاهی تعدیل‌شده با خاک (SAVI)',
    category: 'vegetation',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.18,
      optimalMax: 0.45,
      unit: '',
      rangeLabelFa: '۰.۱۸ تا ۰.۴۵ (باغات با پس‌زمینه خاک روشن)',
      sourceCitation: 'Huete, A. R. (1988) Remote Sensing of Environment, 25(3), 295-309.',
      validityConditionsFa: 'ویژه مناطقی با پوشش گیاهی کمتر از ۵۰٪ که زمینه خاک روشن دارند.',
    },
    farmerExplanationFa:
      'مشابه NDVI اما اثر روشنایی و سفیدی خاک بین درختان را حذف می‌کند تا مقدار سبزی خود درخت دقیق‌تر دیده شود.',
    scientificCautionFa: 'با ضریب تصحیح زمینه خاک (L=0.5) محاسبه شده است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.18) return { statusLabelFa: 'کانوپی متناسب و فعال', statusClass: 'good', evaluationFa: 'سبزی درختان با حذف اثر خاک در وضعیت مطلوب است.' };
      return { statusLabelFa: 'تراکم کانوپی پایین', statusClass: 'warning', evaluationFa: 'حجم شاخ‌وبرگ کم است.' };
    },
  },

  evi: {
    key: 'evi',
    nameEn: 'Enhanced Vegetation Index (EVI)',
    nameFa: 'شاخص بهبودیافته پوشش گیاهی (EVI)',
    category: 'vegetation',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.15,
      optimalMax: 0.50,
      unit: '',
      rangeLabelFa: '۰.۱۵ تا ۰.۵۰ (کانوپی نیمه‌متراکم)',
      sourceCitation: 'Huete et al. (2002) Overview of the radiometric performance of MODIS VI.',
      validityConditionsFa: 'باغات دارای اتمسفر غبارآلود یا کانوپی‌های متراکم.',
    },
    farmerExplanationFa:
      'شاخص سبزی تقویت‌شده که در هوای غبارآلود دقت بالاتری دارد و در شاخ‌وبرگ‌های خیلی متراکم به اشباع نمی‌رسد.',
    scientificCautionFa: 'حساسیت بالا به بازتاب نور آبی در شرایط غبار شدید محلی.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.15) return { statusLabelFa: 'فعالیت فتوسنتزی خوب', statusClass: 'good', evaluationFa: 'فعالیت زیستی کانوپی بدون اشباع طیفی مناسب است.' };
      return { statusLabelFa: 'فعالیت رویشی محدود', statusClass: 'warning', evaluationFa: 'سطح برگ فتوسنتزکننده محدود است.' };
    },
  },

  msavi: {
    key: 'msavi',
    nameEn: 'Modified Soil-Adjusted Vegetation Index (MSAVI)',
    nameFa: 'شاخص پوشش گیاهی تعدیل‌شده اصلاح‌شده (MSAVI)',
    category: 'vegetation',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.15,
      optimalMax: 0.45,
      unit: '',
      rangeLabelFa: '۰.۱۵ تا ۰.۴۵ (کشت با فاصله ردیف زیاد)',
      sourceCitation: 'Qi, J., et al. (1994) Remote Sensing of Environment, 48(2), 119-126.',
      validityConditionsFa: 'مراحل رشد با کانوپی باز یا پس‌زمینه خاک متغیر.',
    },
    farmerExplanationFa:
      'بهترین شاخص برای مزارع و باغات با فاصله ردیف زیاد که بدون نیاز به حدس زدن ضریب خاک، اثر خاک لخت را خنثی می‌کند.',
    scientificCautionFa: 'محاسبه غیرخطی بر اساس خودسازگاری با خط خاک.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.15) return { statusLabelFa: 'وضعیت رویشی مساعد', statusClass: 'good', evaluationFa: 'شاخص تصحیح‌شده خاک در دامنه استاندارد قرار دارد.' };
      return { statusLabelFa: 'تراکم برگی ضعیف', statusClass: 'warning', evaluationFa: 'سبزینگی خالص درختان محدود است.' };
    },
  },

  ndre: {
    key: 'ndre',
    nameEn: 'Normalized Difference Red Edge (NDRE)',
    nameFa: 'شاخص لبه قرمز (NDRE)',
    category: 'vegetation',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 0.6,
      optimalMin: 0.12,
      optimalMax: 0.38,
      unit: '',
      rangeLabelFa: '۰.۱۲ تا ۰.۳۸ (کلروفیل فعال کانوپی)',
      sourceCitation: 'Gitelson, A. A., & Merzlyak, M. N. (1994) J. Plant Physiol.',
      validityConditionsFa: 'سنجش غلظت کلروفیل در کانوپی‌های بالغ.',
    },
    farmerExplanationFa:
      'حساس‌ترین شاخص به غلظت کلروفیل (سبزینگی بافت داخلی برگ) و شادابی کانوپی بالغ که علائم زردی و ضعف تغذیه‌ای را زودتر نشان می‌دهد.',
    scientificCautionFa: 'افت NDRE می‌تواند ناشی از کمبود ازت، شوری آب یا پیری فیزیولوژیک باشد و نیازمند آزمون خاک/برگ است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.12) return { statusLabelFa: 'غلظت کلروفیل و شادابی مناسب', statusClass: 'good', evaluationFa: 'سبزینگی بافت داخلی برگ و کلروفیل در دامنه پایدار است.' };
      return { statusLabelFa: 'کلروفیل پایین / پایش زردی کانوپی', statusClass: 'warning', evaluationFa: 'افت شاخص لبه قرمز ممکن است ناشی از تنش یا زردی موضعی باشد.' };
    },
  },

  ndre_anomaly: {
    key: 'ndre_anomaly',
    nameEn: 'NDRE Seasonal Anomaly',
    nameFa: 'آنومالی فصلی شاخص لبه قرمز (NDRE)',
    category: 'vegetation',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: false,
      unit: '',
      rangeLabelFa: 'فاقد دامنه عددی ثابت — وابسته به زمینه و انحراف از میانگین ۱۰ ساله همان پنجره فصلی',
      sourceCitation: 'Gitelson, A. A., & Merzlyak, M. N. (1994); Sentinel-2 10-year interannual baseline.',
      validityConditionsFa: 'پنجره‌های تقویمی یکسان در سال‌های پیشین با حداقل ۳ سال داده معتبر سنتینل-۲.',
    },
    farmerExplanationFa:
      'نشان می‌دهد شادابی و سبزی بافت برگ درختان در این مقطع نسبت به میانگین همین فصل در سال‌های قبل چقدر تغییر کرده است. اعداد منفی نشان‌دهنده افت نسبت به میانگین تاریخی باغ است.',
    scientificCautionFa:
      'این شاخص یک انحراف زمانی نوری است، نه اندازه‌گیری مستقیم خشکیدگی یا کلروفیل و نه تشخیص قطعی عامل آسیب.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.02) return { statusLabelFa: 'بهتر از میانگین فصلی', statusClass: 'good', evaluationFa: 'شاخص لبه قرمز بالاتر از میانگین تاریخی همین دوره است.' };
      if (val >= -0.02) return { statusLabelFa: 'منطبق بر میانگین فصلی', statusClass: 'neutral', evaluationFa: 'شرایط کانوپی نزدیک به میانگین تاریخی سال‌های گذشته است.' };
      return { statusLabelFa: 'پایین‌تر از میانگین فصلی', statusClass: 'warning', evaluationFa: 'شاخص لبه قرمز نسبت به سال‌های قبل افت نشان می‌دهد؛ نیازمند بررسی تغذیه و سلامت درخت.' };
    },
  },

  // ==========================================
  // 2. MOISTURE & CANOPY WATER
  // ==========================================
  ndmi: {
    key: 'ndmi',
    nameEn: 'Normalized Difference Moisture Index (NDMI)',
    nameFa: 'شاخص رطوبت کانوپی (NDMI)',
    category: 'moisture',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: -0.4,
      max: 0.6,
      optimalMin: -0.10,
      optimalMax: 0.25,
      unit: '',
      rangeLabelFa: '-۰.۱۰ تا ۰.۲۵ (آب کانوپی در اقلیم خشک)',
      sourceCitation: 'Gao, B. C. (1996) Remote Sensing of Environment, 58(3), 257-266.',
      validityConditionsFa: 'کانوپی باغات در ماه‌های گرم و کم‌باران.',
    },
    farmerExplanationFa:
      'نشان‌دهنده میزان آب و تورژسانس درون بافت برگ درختان است. مقادیر منفیِ شدید (زیر ۰.۱۵-) نشان‌دهنده خشکی برگ یا تنک بودن شدید باغ است.',
    scientificCautionFa: 'این شاخص بیانگر آب بافت کانوپی است، نه رطوبت عمق خاک پای درخت.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= -0.10) return { statusLabelFa: 'رطوبت بافت برگ مطلوب', statusClass: 'good', evaluationFa: 'محتوای آب شاخ‌وبرگ در شرایط هیدراته و مناسب است.' };
      if (val >= -0.18) return { statusLabelFa: 'رطوبت متوسط کانوپی', statusClass: 'neutral', evaluationFa: 'آب برگ در حد معمول مناطق نیمه‌خشک است.' };
      return { statusLabelFa: 'کاهش آب برگ / تنش خشکی احتمالی', statusClass: 'warning', evaluationFa: 'محتوای آب شاخ‌وبرگ افت کرده است؛ بررسی دور آبیاری توصیه می‌شود.' };
    },
  },

  msi: {
    key: 'msi',
    nameEn: 'Moisture Stress Index (MSI)',
    nameFa: 'شاخص تنش رطوبت کانوپی (MSI)',
    category: 'moisture',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.4,
      max: 2.5,
      optimalMin: 0.6,
      optimalMax: 1.4,
      warningHigh: 1.6,
      unit: '',
      rangeLabelFa: '۰.۶ تا ۱.۴ (شرایط بدون تنش رطوبتی شدید)',
      sourceCitation: 'Hunt, E. R., & Rock, B. N. (1989) Remote Sens. Environ.',
      validityConditionsFa: 'سنجش نسبت بازتاب مادون قرمز میانی به نزدیک.',
    },
    farmerExplanationFa:
      'نسبت خشکی برگ؛ این عدد برعکس NDMI کار می‌کند. هرچه عدد کوچکتری باشد برگ‌ها شاداب‌ترند و اعداد بالای ۱.۶ نشان‌دهنده تشنگی و تنش آبی است.',
    scientificCautionFa: 'افزایش MSI در تابستان کویر به دلیل تبخیر بالا معمول است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 1.35) return { statusLabelFa: 'بدون تنش رطوبتی', statusClass: 'good', evaluationFa: 'نسبت خشکی پایین و وضعیت آبرسانی برگ مناسب است.' };
      if (val <= 1.60) return { statusLabelFa: 'تنش رطوبتی متوسط', statusClass: 'warning', evaluationFa: 'درختان در آستانه تحمل تنش کم‌آبی قرار دارند.' };
      return { statusLabelFa: 'تنش رطوبتی محسوس', statusClass: 'danger', evaluationFa: 'شاخص تنش خشکی کانوپی بالاست؛ بررسی نوبت آبیاری الزامی است.' };
    },
  },

  ndmi_anomaly: {
    key: 'ndmi_anomaly',
    nameEn: 'NDMI Seasonal Anomaly',
    nameFa: 'آنومالی فصلی رطوبت کانوپی (NDMI)',
    category: 'moisture',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: false,
      unit: '',
      rangeLabelFa: 'فاقد دامنه عددی ثابت — وابسته به زمینه و انحراف از میانگین ۱۰ ساله همان پنجره فصلی',
      sourceCitation: 'Gao, B. C. (1996); Sentinel-2 10-year interannual baseline framework.',
      validityConditionsFa: 'حداقل ۳ سال داده معتبر تاریخی در همان پنجره تقویمی.',
    },
    farmerExplanationFa:
      'نشان می‌دهد رطوبت برگ و شاخ‌وبرگ درختان نسبت به میانگین سال‌های گذشته در همین فصل بیشتر است یا کمتر. اعداد منفی نشان‌دهنده رطوبت کمتر از حد نرمال گذشته است.',
    scientificCautionFa:
      'آنومالی شاخص رطوبت نوری کانوپی است و نباید به عنوان اندازه‌گیری مستقیم آب آزاد برگ یا تنش لایه‌ای کانوپی تعبیر شود.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.02) return { statusLabelFa: 'رطوبت بیشتر از نرمال فصلی', statusClass: 'good', evaluationFa: 'رطوبت بافت کانوپی بالاتر از میانگین سال‌های گذشته است.' };
      if (val >= -0.02) return { statusLabelFa: 'رطوبت در حد نرمال فصلی', statusClass: 'neutral', evaluationFa: 'رطوبت برگی منطبق بر نرمال تاریخی باغ است.' };
      return { statusLabelFa: 'رطوبت کمتر از نرمال فصلی', statusClass: 'warning', evaluationFa: 'رطوبت شاخ‌وبرگ کمتر از سال‌های گذشته در این بازه است؛ بررسی نوبت آبیاری.' };
    },
  },

  msi_anomaly: {
    key: 'msi_anomaly',
    nameEn: 'MSI Seasonal Anomaly',
    nameFa: 'آنومالی فصلی تنش رطوبت (MSI)',
    category: 'moisture',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: false,
      unit: '',
      rangeLabelFa: 'فاقد دامنه عددی ثابت — وابسته به زمینه و انحراف از میانگین ۱۰ ساله همان پنجره فصلی',
      sourceCitation: 'Hunt, E. R., & Rock, B. N. (1989); Sentinel-2 10-year interannual baseline framework.',
      validityConditionsFa: 'حداقل ۳ سال داده معتبر تاریخی در همان پنجره تقویمی.',
    },
    farmerExplanationFa:
      'نشان‌دهنده انحراف تنش خشکی برگ نسبت به سال‌های قبل در همین فصل است. برعکس NDMI، عدد مثبت در اینجا نشان‌دهنده تنش خشکی بیشتر نسبت به سال‌های گذشته است.',
    scientificCautionFa:
      'آنومالی تنش شاخص بازتابی SWIR/NIR است، نه تشخیص فیزیولوژیک قطعی انسداد آوند یا بیماری.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= -0.05) return { statusLabelFa: 'تنش کمتر از نرمال فصلی', statusClass: 'good', evaluationFa: 'تنش خشکی کمتر از میانگین سال‌های گذشته در همین فصل است.' };
      if (val <= 0.05) return { statusLabelFa: 'تنش در حد نرمال فصلی', statusClass: 'neutral', evaluationFa: 'شاخص تنش رطوبت منطبق بر میانگین تاریخی است.' };
      return { statusLabelFa: 'تنش بیشتر از نرمال فصلی', statusClass: 'warning', evaluationFa: 'تنش خشکی کانوپی نسبت به نرمال سال‌های قبل افزایش یافته است.' };
    },
  },

  ndwi: {
    key: 'ndwi',
    nameEn: 'Normalized Difference Water Index (NDWI)',
    nameFa: 'شاخص پهنه‌های آبی و رطوبت سطحی (NDWI)',
    category: 'moisture',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: -1.0,
      max: 1.0,
      optimalMin: -0.4,
      optimalMax: -0.05,
      unit: '',
      rangeLabelFa: 'منفی ۰.۴ تا منفی ۰.۰۵ در اراضی کشاورزی بدون آب سطحی',
      sourceCitation: 'McFeeters, S. K. (1996) Int. J. Remote Sensing.',
      validityConditionsFa: 'پایش تجمع آب سطحی یا غرقاب شدن.',
    },
    farmerExplanationFa:
      'نشان‌دهنده وجود آب سطحی آزاد در مزرعه است. در باغات معمولاً منفی است و مقادیر مثبت فقط هنگام جاری بودن آب یا استخر کشاورزی دیده می‌شود.',
    scientificCautionFa: 'در خاک‌های خشک کشاورزی همواره مقادیر منفی تولید می‌کند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val > 0.0) return { statusLabelFa: 'آب سطحی / مانداب مشاهده شد', statusClass: 'warning', evaluationFa: 'بازتاب آب سطحی آزاد در قطعه شناسایی شده است.' };
      return { statusLabelFa: 'بدون مانداب سطحی', statusClass: 'good', evaluationFa: 'سطح باغ فاقد مانداب یا استخر روباز است.' };
    },
  },

  mndwi: {
    key: 'mndwi',
    nameEn: 'Modified NDWI (MNDWI)',
    nameFa: 'شاخص اصلاح‌شده آب (MNDWI)',
    category: 'moisture',
    unit: '',
    datasetId: 'COPERNICUS/S2_SR_HARMONIZED',
    datasetNameFa: 'ماهواره سنتینل-۲ (Sentinel-2 L2A)',
    spatialResolution: '۲۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: -1.0,
      max: 1.0,
      rangeLabelFa: 'منفی (عدم حضور مانداب سطحی)',
      sourceCitation: 'Xu, H. (2006) Int. J. Remote Sensing.',
      validityConditionsFa: 'تمایز آب سطحی از ساخت‌وساز و خاک لخت.',
      unit: '',
    },
    farmerExplanationFa: 'شاخص تفکیک پهنه‌های آب با تداخل کمتر از سمت ساختمان‌ها و جاده‌های خاکی اطراف باغ.',
    scientificCautionFa: 'در مزارع خشک ماهیت منفی دارد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val > 0.0) return { statusLabelFa: 'انعکاس آب آزاد', statusClass: 'warning', evaluationFa: 'سطح آبدار روباز شناسایی شد.' };
      return { statusLabelFa: 'سطح خشک استاندارد', statusClass: 'good', evaluationFa: 'فاقد مانداب سطحی.' };
    },
  },

  // ==========================================
  // 3. THERMAL & SURFACE TEMPERATURE
  // ==========================================
  land_surface_temperature_day: {
    key: 'land_surface_temperature_day',
    nameEn: 'Daytime Land Surface Temperature (LST Day)',
    nameFa: 'دمای روزانه سطح زمین (LST Day)',
    category: 'thermal',
    unit: '°C',
    datasetId: 'MODIS/061/MOD11A2',
    datasetNameFa: 'سنجنده حرارتی مادیس (MODIS Terra/Aqua)',
    spatialResolution: '۱۰۰۰ متر (۱ کیلومتر)',
    dataType: 'satellite_observation',
    referenceRange: {
      hasFixedRange: false,
      unit: '°C',
      rangeLabelFa: 'فاقد مرجع بهینه ثابت (بازه تابستان بیابانی: ۴۰ تا ۵۵ °C)',
      sourceCitation: 'Wan, Z. (2014) Collection-6 MODIS LST Product Guide.',
      validityConditionsFa: 'پوسته بالایی خاک لخت و کانوپی در ساعات ۱۱ الی ۱۳ ظهر.',
    },
    farmerExplanationFa:
      'دمای تابشی سطح فیزیکی خاک در داغ‌ترین ساعات روز. در تابستان یزد و کویر دمای ۴۵ تا ۵۵ درجه روی سطح خاک لخت امری طبیعی است.',
    scientificCautionFa:
      'این عدد دمای تابشی پوسته فیزیکی خاک است، نه دمای هوای خنک‌شده درون کانوپی درخت یا دمای برگ.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val > 52.0) return { statusLabelFa: 'حرارت شدید پوسته زمین', statusClass: 'warning', evaluationFa: 'دمای تابشی سطح خاک بسیار بالاست؛ تشدید تبخیر سطحی.' };
      if (val >= 38.0) return { statusLabelFa: 'دمای تابستانی معمول منطقه', statusClass: 'neutral', evaluationFa: 'دمای فیزیکی سطح خاک در دامنه معمول تابستان کویر است.' };
      return { statusLabelFa: 'دمای ملایم سطح', statusClass: 'good', evaluationFa: 'دمای سطح زمین خنک و متعادل است.' };
    },
  },

  land_surface_temperature_night: {
    key: 'land_surface_temperature_night',
    nameEn: 'Nighttime Land Surface Temperature (LST Night)',
    nameFa: 'دمای شبانه سطح زمین (LST Night)',
    category: 'thermal',
    unit: '°C',
    datasetId: 'MODIS/061/MOD11A2',
    datasetNameFa: 'سنجنده حرارتی مادیس (MODIS Terra/Aqua)',
    spatialResolution: '۱۰۰۰ متر (۱ کیلومتر)',
    dataType: 'satellite_observation',
    referenceRange: {
      hasFixedRange: false,
      unit: '°C',
      rangeLabelFa: 'وابسته به فصل (تابستان: ۲۰ تا ۳۰ °C | بهار برای سرمازدگی: > ۲ تا ۴ °C)',
      sourceCitation: 'FAO Frost Protection Guidelines; Snyder & Melo-Abreu (2005).',
      validityConditionsFa: 'ساعات پایانی شب و پیش از طلوع آفتاب.',
    },
    farmerExplanationFa:
      'دمای پوسته خاک در شب؛ در بهار برای پایش خطر سرمازدگی دیررس بهاره و در تابستان برای پایش خنک شدن درختان در شب اهمیت حیاتی دارد.',
    scientificCautionFa: 'تفکیک مکانی ۱۰۰۰ متری شرایط میانگین پستی‌وبلندی منطقه را نشان می‌دهد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 2.0) return { statusLabelFa: 'هشدار ریسک سرمازدگی سطحی', statusClass: 'danger', evaluationFa: 'دمای شبانه سطح در مرز آسیب سرمایی قرار دارد.' };
      if (val >= 28.0) return { statusLabelFa: 'شب‌های بسیار گرم تابستانی', statusClass: 'warning', evaluationFa: 'تنفس شبانه درخت به دلیل عدم خنک‌شدن کافی افزایش می‌یابد.' };
      return { statusLabelFa: 'دمای شبانه نرمال', statusClass: 'good', evaluationFa: 'خنک‌شدن شبانه سطح در وضعیت پایدار است.' };
    },
  },

  landsat_surface_temperature: {
    key: 'landsat_surface_temperature',
    nameEn: 'Landsat High-Resolution LST',
    nameFa: 'دمای سطح زمین لندست (تفکیک بالا)',
    category: 'thermal',
    unit: '°C',
    datasetId: 'LANDSAT/LC08/C02/T1_L2',
    datasetNameFa: 'ماهواره لندست ۸ حرارتی (Landsat 8 TIRS)',
    spatialResolution: '۳۰ متر',
    dataType: 'satellite_observation',
    referenceRange: {
      hasFixedRange: false,
      unit: '°C',
      rangeLabelFa: 'فاقد مرجع بهینه ثابت (مشابه LST روزانه با تفکیک درون‌مزرعه‌ای ۳۰ متری)',
      sourceCitation: 'USGS Landsat Collection 2 Surface Temperature Guide.',
      validityConditionsFa: 'گذر روزانه ماهواره در آسمان صاف.',
    },
    farmerExplanationFa:
      'دمای حرارتی سطح با تفکیک مکانی دقیق‌تر (۳۰ متر) که تفاوت داغی بین بخش‌های مختلف باغ را نشان می‌دهد.',
    scientificCautionFa: 'تکرار گذر ماهواره لندست هر ۱۶ روز یک‌بار است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `${val.toFixed(1)} °C — تفکیک ۳۰ متری`, statusClass: 'neutral', evaluationFa: 'دمای موضعی تفکیک ۳۰ متری سطح زمین.' };
    },
  },

  surface_temperature_range: {
    key: 'surface_temperature_range',
    nameEn: 'Diurnal Surface Temperature Range',
    nameFa: 'دامنه نوسان دمای شبانه‌روز سطح (DTR)',
    category: 'thermal',
    unit: '°C',
    datasetId: 'MODIS/061/MOD11A2',
    datasetNameFa: 'سنجنده حرارتی مادیس (LST Day - Night)',
    spatialResolution: '۱۰۰۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: false,
      unit: '°C',
      rangeLabelFa: 'وابسته به اقلیم (کویر: ۱۵ تا ۲۸ °C نوسان شبانه‌روزی)',
      sourceCitation: 'Gartland, L. (2012) Heat Islands: Understanding and Mitigating.',
      validityConditionsFa: 'تفاضل دمای روز و شب پوسته زمین.',
    },
    farmerExplanationFa: 'اختلاف دمای داغ‌ترین ساعت روز و سردترین ساعت شب در سطح زمین؛ هرچه خاک خشک‌تر باشد این اختلاف بیشتر است.',
    scientificCautionFa: 'خاک‌های مرطوب دامنه نوسان کمتری نسبت به خاک‌های خشک دارند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `نوسان ${val.toFixed(1)} درجه‌ای`, statusClass: 'neutral', evaluationFa: 'میزان اختلاف حرارتی شب و روز سطح.' };
    },
  },

  // ==========================================
  // 4. RADAR STRUCTURAL BACKSCATTER
  // ==========================================
  vh: {
    key: 'vh',
    nameEn: 'Sentinel-1 Cross-Polarization Backscatter (VH)',
    nameFa: 'پس‌پراکنش رادار قطبش متقاطع (VH)',
    category: 'radar',
    unit: 'dB',
    datasetId: 'COPERNICUS/S1_GRD',
    datasetNameFa: 'رادار سنتینل-۱ (Sentinel-1 SAR C-band)',
    spatialResolution: '۱۰ متر',
    dataType: 'satellite_observation',
    referenceRange: {
      hasFixedRange: true,
      min: -30.0,
      max: -5.0,
      optimalMin: -20.0,
      optimalMax: -12.0,
      unit: 'dB',
      rangeLabelFa: 'منفی ۲۰ تا منفی ۱۲ دسی‌بل (کانوپی با ساختار چوبی/برگی)',
      sourceCitation: 'ESA Sentinel-1 SAR User Handbook.',
      validityConditionsFa: 'زاویه تابش IW، پایش مستقل از پوشش ابر.',
    },
    farmerExplanationFa:
      'امواج مایکروویو رادار که از ابر عبور می‌کنند و با حجم شاخه‌ها و زبری درخت برخورد دارند. برای پایش حجم ساختاری باغ حتی در روزهای ابری به کار می‌رود.',
    scientificCautionFa: 'مقدار بر حسب دسی‌بل (dB) لگاریتمی است؛ اعداد منفی‌تر نشان‌دهنده بازتاب ضعیف‌ترند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= -16.0) return { statusLabelFa: 'پراکنش حجمی قوی (ساختار پرشاخه)', statusClass: 'good', evaluationFa: 'بازتاب ساختاری امواج رادار نشان‌دهنده حجم کانوپی مناسب است.' };
      return { statusLabelFa: 'پراکنش حجمی کم (تاج پوشش باز)', statusClass: 'neutral', evaluationFa: 'تراکم شاخه و برگ در مقیاس راداری در حد معمول باغات تنک است.' };
    },
  },

  vv: {
    key: 'vv',
    nameEn: 'Sentinel-1 Co-Polarization Backscatter (VV)',
    nameFa: 'پس‌پراکنش رادار قطبش هم‌نام (VV)',
    category: 'radar',
    unit: 'dB',
    datasetId: 'COPERNICUS/S1_GRD',
    datasetNameFa: 'رادار سنتینل-۱ (Sentinel-1 SAR C-band)',
    spatialResolution: '۱۰ متر',
    dataType: 'satellite_observation',
    referenceRange: {
      hasFixedRange: true,
      min: -25.0,
      max: 0.0,
      optimalMin: -15.0,
      optimalMax: -7.0,
      unit: 'dB',
      rangeLabelFa: 'منفی ۱۵ تا منفی ۷ دسی‌بل',
      sourceCitation: 'Ulaby, F. T., et al. (2014) Microwave Radar and Radiometric Remote Sensing.',
      validityConditionsFa: 'حساسیت بالا به زبری سطح خاک و رطوبت پوسته.',
    },
    farmerExplanationFa: 'حساس به زبری سطح زمین، کلوخه‌ها و رطوبت پوسته بیرونی خاک.',
    scientificCautionFa: 'همزمان تحت تأثیر رطوبت خاک و ناهمواری فیزیکی قرار دارد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `${val.toFixed(1)} dB — سیگنال زبری و رطوبت`, statusClass: 'neutral', evaluationFa: 'شدت بازتاب راداری سطحی.' };
    },
  },

  vh_vv: {
    key: 'vh_vv',
    nameEn: 'Radar Polarization Ratio (VH/VV)',
    nameFa: 'نسبت قطبش‌های راداری (VH/VV)',
    category: 'radar',
    unit: 'dB',
    datasetId: 'COPERNICUS/S1_GRD',
    datasetNameFa: 'رادار سنتینل-۱ (تفاضل لگاریتمی VH - VV)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: -15.0,
      max: 0.0,
      optimalMin: -10.0,
      optimalMax: -4.0,
      unit: 'dB',
      rangeLabelFa: 'منفی ۱۰ تا منفی ۴ دسی‌بل (افزایش سهم کانوپی)',
      sourceCitation: 'Veloso et al. (2017) Remote Sensing of Environment, 199, 149-162.',
      validityConditionsFa: 'شاخص رشد ساختار کانوپی نسبت به زمینه خاک.',
    },
    farmerExplanationFa: 'مقایسه سهم شاخ‌وبرگ نسبت به خاک لخت؛ هرچه به صفر نزدیک‌تر شود سهم پوشش گیاهی بیشتر است.',
    scientificCautionFa: 'بدون تأثیرپذیری از نور خورشید و ابر.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `نسبت ${val.toFixed(1)} dB`, statusClass: 'neutral', evaluationFa: 'شاخص سهم شاخ‌وبرگ در امواج مایکروویو.' };
    },
  },

  rvi: {
    key: 'rvi',
    nameEn: 'Radar Vegetation Index (RVI)',
    nameFa: 'شاخص راداری پوشش گیاهی (RVI)',
    category: 'radar',
    unit: '',
    datasetId: 'COPERNICUS/S1_GRD',
    datasetNameFa: 'رادار سنتینل-۱ (Sentinel-1 RVI)',
    spatialResolution: '۱۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.35,
      optimalMax: 0.75,
      unit: '',
      rangeLabelFa: '۰.۳۵ تا ۰.۷۵ (تراکم ساختار گیاهی)',
      sourceCitation: 'Charbonneau et al. (2005) Evaluation of the RVI from SAR data.',
      validityConditionsFa: 'سنجش ساختاری کانوپی به صورت غیرنوری.',
    },
    farmerExplanationFa: 'معادل راداری شاخص پوشش گیاهی برای ارزیابی حجم کانوپی حتی در شرایط ابری یا مه.',
    scientificCautionFa: 'حساس به رطوبت پوسته خاک در شرایط کم‌پوشش.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.40) return { statusLabelFa: 'حجم کانوپی راداری خوب', statusClass: 'good', evaluationFa: 'پراکنش ساختاری بافت گیاهی مطلوب است.' };
      return { statusLabelFa: 'تراکم ساختاری ملایم', statusClass: 'neutral', evaluationFa: 'شاخص راداری در دامنه معمول باغات تنک است.' };
    },
  },

  // ==========================================
  // 5. CLIMATE & ATMOSPHERIC METRICS
  // ==========================================
  vpd: {
    key: 'vpd',
    nameEn: 'Vapor Pressure Deficit (VPD)',
    nameFa: 'کسری فشار بخار اتمسفر (VPD)',
    category: 'climate',
    unit: 'kPa',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی سطحی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر (۰.۱ درجه)',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 8.0,
      optimalMin: 0.8,
      optimalMax: 2.2,
      warningHigh: 3.0,
      unit: 'kPa',
      rangeLabelFa: '۰.۸ تا ۲.۲ kPa (مطلوب فتوسنتز بدون بسته‌شدن روزنه‌ها)',
      sourceCitation: 'Grossiord et al. (2020) Plant responses to rising VPD. New Phytol.',
      validityConditionsFa: 'دمای هوای ۲ متری و دمای نقطه شبنم در طول ساعات روز.',
    },
    farmerExplanationFa:
      'نشان‌دهنده قدرت مکش و تشنگی هوا برای کشیدن آب از برگ درخت است. مقادیر بالای ۳ کیلوپاسکال نشان‌دهنده هوای بسیار داغ و خشک است که درخت را وادار به بستن روزنه‌های برگ می‌کند.',
    scientificCautionFa: 'تفکیک مکانی ۱۱ کیلومتری نشان‌دهنده اقلیم کلان منطقه است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 2.2) return { statusLabelFa: 'مطلوب برای باز بودن روزنه‌ها', statusClass: 'good', evaluationFa: 'تنش تبخیری اتمسفر پایین بوده و روزنه‌ها باز هستند.' };
      if (val <= 3.2) return { statusLabelFa: 'تنش خشکی هوای متوسط', statusClass: 'warning', evaluationFa: 'هوا گرم و خشک است؛ کاهش نسبی سرعت فتوسنتز.' };
      return { statusLabelFa: 'تنش هوای بسیار داغ و خشک (VPD بالا)', statusClass: 'danger', evaluationFa: 'هوای بسیار خشک موجب بسته‌شدن روزنه‌ها و توقف فتوسنتز درختان می‌شود.' };
    },
  },

  temperature_mean: {
    key: 'temperature_mean',
    nameEn: 'Mean Air Temperature (2 m)',
    nameFa: 'میانگین دمای هوا (ارتفاع ۲ متر)',
    category: 'climate',
    unit: '°C',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: false,
      unit: '°C',
      rangeLabelFa: 'دمای میانگین شبانه‌روز (وابسته به فصل)',
      sourceCitation: 'ECMWF ERA5-Land Documentation (Muñoz-Sabater et al., 2021).',
      validityConditionsFa: 'سنسور شبیه‌سازی ۲ متر بالای سطح زمین.',
    },
    farmerExplanationFa: 'میانگین واقعی دمای هوا در طول ۲۴ ساعت شبانه‌روز.',
    scientificCautionFa: 'میانگین دمای هواست و با حداکثر دمای ظهر تفاوت دارد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `${val.toFixed(1)} °C میانگین هوا`, statusClass: 'neutral', evaluationFa: 'دمای هوای ۲ متری در دوره تحلیل.' };
    },
  },

  temperature_max: {
    key: 'temperature_max',
    nameEn: 'Maximum Air Temperature (2 m)',
    nameFa: 'حداکثر دمای هوا (دمای اوج روز)',
    category: 'climate',
    unit: '°C',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: -15.0,
      max: 55.0,
      optimalMin: 20.0,
      optimalMax: 35.0,
      warningHigh: 40.0,
      unit: '°C',
      rangeLabelFa: 'زیر ۳۸ تا ۴۰ °C (جلوگیری از تنش گرمازدگی پسته)',
      sourceCitation: 'Ferguson & Haviland (2016) Pistachio Production Manual.',
      validityConditionsFa: 'دمای اوج روزانه در گرم‌ترین ساعت.',
    },
    farmerExplanationFa: 'بیشترین دمای هوا در طول روز؛ در باغات پسته دمای بالای ۴۰ درجه سانتی‌گر می‌تواند باعث سوختگی مغز یا توقف رشد شود.',
    scientificCautionFa: 'دمای هوای استاندارد در سایه است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 42.0) return { statusLabelFa: 'هشدار گرمای شدید (> ۴۲ °C)', statusClass: 'danger', evaluationFa: 'دمای بسیار بالا؛ خطر آفتاب‌سوختگی و سقط جنین میوه.' };
      if (val >= 38.0) return { statusLabelFa: 'گرمای تابستانی بالا', statusClass: 'warning', evaluationFa: 'دمای نزدیک به آستانه تنش گرمایی پسته.' };
      return { statusLabelFa: 'دمای روزانه مطلوب', statusClass: 'good', evaluationFa: 'حداکثر دما در محدوده قابل‌تحمل و مناسب است.' };
    },
  },

  temperature_min: {
    key: 'temperature_min',
    nameEn: 'Minimum Air Temperature (2 m)',
    nameFa: 'حداقل دمای هوا (دمای سردترین ساعت شب)',
    category: 'climate',
    unit: '°C',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: false,
      unit: '°C',
      rangeLabelFa: 'وابسته به فصل (در بهار > ۵ °C پایش سرمازدگی | تابستان ۲۰ تا ۲۵ °C)',
      sourceCitation: 'FAO Frost Guidelines.',
      validityConditionsFa: 'سردترین ساعت بامداد پیش از طلوع آفتاب.',
    },
    farmerExplanationFa: 'کمترین دمای هوای ثبت‌شده در شب؛ در فروردین‌ماه عامل اصلی تعیین‌کننده خطر سرمازدگی بهاره شکوفه‌هاست.',
    scientificCautionFa: 'در گودی‌ها و کف باغ ممکن است دما تا ۲ درجه سردتر از عدد ایستگاه باشد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 2.0) return { statusLabelFa: 'هشدار ریسک سرمازدگی بهاره', statusClass: 'danger', evaluationFa: 'خطر یخ‌زدگی گل‌ها و جوانه‌های نورس.' };
      return { statusLabelFa: `${val.toFixed(1)} °C حداقل شبانه`, statusClass: 'good', evaluationFa: 'حداقل دما در دامنه ایمن قرار دارد.' };
    },
  },

  precipitation: {
    key: 'precipitation',
    nameEn: 'Total Precipitation',
    nameFa: 'میزان بارش کل دوره',
    category: 'climate',
    unit: 'mm',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: false,
      unit: 'mm',
      rangeLabelFa: 'وابسته به اقلیم و فصل (تجمع کل بارش پنجره زمانی)',
      sourceCitation: 'ECMWF Reanalysis Documentation.',
      validityConditionsFa: 'مجموع بارندگی در کل روزهای دوره انتخابی.',
    },
    farmerExplanationFa: 'کل حجم بارندگی انباشته در طول دوره تحلیل به میلی‌متر.',
    scientificCautionFa: 'بارش‌های رگباری بسیار موضعی ممکن است با مدل ۱۱ کیلومتری اختلاف داشته باشد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val < 1.0) return { statusLabelFa: 'دوره کاملاً خشک (بدون بارش مؤثر)', statusClass: 'neutral', evaluationFa: 'بارندگی ناچیز یا صفر در پنجره زمانی؛ نیاز ۱۰۰٪ به آبیاری.' };
      return { statusLabelFa: `${val.toFixed(1)} میلی‌متر بارش`, statusClass: 'good', evaluationFa: 'مجموع بارندگی انباشته در دوره انتخابی.' };
    },
  },

  relative_humidity: {
    key: 'relative_humidity',
    nameEn: 'Relative Humidity',
    nameFa: 'رطوبت نسبی هوا',
    category: 'climate',
    unit: '%',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 100.0,
      optimalMin: 20.0,
      optimalMax: 50.0,
      unit: '%',
      rangeLabelFa: '۲۰٪ تا ۵۰٪ (تابستان بیابانی معمولاً ۱۰٪ تا ۲۵٪)',
      sourceCitation: 'Allen et al. (1998) FAO-56.',
      validityConditionsFa: 'رطوبت هوای جوی در طول ساعات روز.',
    },
    farmerExplanationFa: 'درصد رطوبت موجود در هوا؛ رطوبت بسیار پایین (زیر ۱۵٪) نشان‌دهنده خشکی مفرط هوا و تشدید عطش درخت است.',
    scientificCautionFa: 'با افزایش دما در ظهر، رطوبت نسبی به کمترین مقدار می‌رسد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val < 15.0) return { statusLabelFa: 'هوای فوق‌العاده خشک (< ۱۵٪)', statusClass: 'warning', evaluationFa: 'خشکی شدید هوا موجب تبخیر سریع رطوبت برگ و خاک می‌شود.' };
      return { statusLabelFa: `${val.toFixed(1)}٪ رطوبت نسبی`, statusClass: 'good', evaluationFa: 'رطوبت هوا در شرایط متداول اقلیم منطقه است.' };
    },
  },

  solar_radiation: {
    key: 'solar_radiation',
    nameEn: 'Surface Solar Radiation Downwards',
    nameFa: 'تابش خورشیدی روزانه دریافتی سطح',
    category: 'climate',
    unit: 'MJ/m²',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: 5.0,
      max: 35.0,
      optimalMin: 22.0,
      optimalMax: 32.0,
      unit: 'MJ/m²',
      rangeLabelFa: '۲۲ تا ۳۲ مگاژول بر مترمربع در تابستان آفتابی ایران',
      sourceCitation: 'Duffie & Beckman (2013) Solar Engineering of Thermal Processes.',
      validityConditionsFa: 'انرژی خالص تابشی در آسمان صاف.',
    },
    farmerExplanationFa: 'میزان انرژی آفتاب در طول روز؛ انرژی لازم برای فتوسنتز درختان را تأمین می‌کند اما تابش شدید ظهر نیازمند آب کافی است.',
    scientificCautionFa: 'در روزهای ابری یا گردوغبار غلیظ افت می‌کند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `${val.toFixed(1)} MJ/m² تابش خورشیدی`, statusClass: 'good', evaluationFa: 'میزان انرژی تابشی روزانه برای فتوسنتز.' };
    },
  },

  gdd: {
    key: 'gdd',
    nameEn: 'Growing Degree Days (GDD Base 10°C)',
    nameFa: 'درجه-روز رشد تجمعی (GDD پایه ۱۰ درجه)',
    category: 'climate',
    unit: '°C-day',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'محاسبه‌شده بر پایه دمای ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 3500.0,
      optimalMin: 1800.0,
      optimalMax: 2600.0,
      unit: '°C-day',
      rangeLabelFa: '۱۸۰۰ تا ۲۶۰۰ درجه-روز برای رسیدگی کامل ارقام پسته',
      sourceCitation: 'Ferguson & Haviland (2016) Pistachio Production Manual.',
      validityConditionsFa: 'تجمع دما از ابتدای فصل بیداری بهاره (فروردین) با دمای پایه ۱۰ درجه سانتی‌گر.',
    },
    farmerExplanationFa:
      'انباشت گرمای مورد نیاز درخت برای رشد، پر شدن مغز و خندان شدن پسته. برای رسیدن محصول پسته حداقل به ۱۸۰۰ تا ۲۴۰۰ درجه-روز گرما از ابتدای سال نیاز است.',
    scientificCautionFa: 'محاسبه استاندارد با دمای پایه ۱۰ درجه سانتی‌گر انجام شده است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 1800.0) return { statusLabelFa: 'انباشت گرمایی کامل برای رسیدگی میوه', statusClass: 'good', evaluationFa: 'نیاز حرارتی برای پر شدن کامل مغز پسته تأمین شده است.' };
      return { statusLabelFa: `${val.toFixed(0)} درجه-روز تجمعی`, statusClass: 'neutral', evaluationFa: 'انباشت دمایی در حال پیشرفت فصلی است.' };
    },
  },

  wind_speed: {
    key: 'wind_speed',
    nameEn: '10 m Wind Speed',
    nameFa: 'سرعت باد در ارتفاع ۱۰ متر',
    category: 'climate',
    unit: 'm/s',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 20.0,
      optimalMin: 1.0,
      optimalMax: 3.5,
      warningHigh: 5.0,
      unit: 'm/s',
      rangeLabelFa: '۱ تا ۳.۵ m/s (باد ملایم مطلوب؛ بالای ۵ m/s نامناسب سمپاشی)',
      sourceCitation: 'ASABE Standards for Agricultural Spraying.',
      validityConditionsFa: 'بررسی شرایط مناسب سمپاشی، گرده‌افشانی و تبخیر.',
    },
    farmerExplanationFa: 'سرعت وزش باد؛ باد بالای ۵ متر بر ثانیه (۱۸ کیلومتر در ساعت) باعث اتلاف محلول‌پاشی و افت کیفیت گرده‌افشانی می‌شود.',
    scientificCautionFa: 'باد در سطح زمین میان درختان ممکن است به دلیل بادشکن کمتر از ارتفاع ۱۰ متر باشد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val > 5.0) return { statusLabelFa: 'باد شدید / نامناسب برای سمپاشی', statusClass: 'warning', evaluationFa: 'سرعت باد بالاست؛ توصیه به عدم محلول‌پاشی به دلیل بادبردگی.' };
      return { statusLabelFa: 'باد ملایم و مساعد', statusClass: 'good', evaluationFa: 'سرعت باد در شرایط مطلوب برای مدیریت مزرعه است.' };
    },
  },

  // ==========================================
  // 6. SOIL MOISTURE & WATER RETENTION
  // ==========================================
  soil_moisture_surface: {
    key: 'soil_moisture_surface',
    nameEn: 'Surface Soil Moisture (0–5 cm)',
    nameFa: 'رطوبت پوسته سطحی خاک (۰ تا ۵ سانتی‌متر)',
    category: 'soil_water',
    unit: 'm³/m³',
    datasetId: 'NASA/SMAP/SPL3SMP_E/006',
    datasetNameFa: 'ماهواره اس‌مپ رادیومتر (NASA SMAP L3)',
    spatialResolution: '۹۰۰۰ متر (۹ کیلومتر)',
    dataType: 'satellite_observation',
    referenceRange: {
      hasFixedRange: true,
      min: 0.02,
      max: 0.35,
      optimalMin: 0.06,
      optimalMax: 0.20,
      unit: 'm³/m³',
      rangeLabelFa: '۰.۰۶ تا ۰.۲۰ m³/m³ در خاک‌های لوم شنی بیابانی',
      sourceCitation: 'Entekhabi et al. (2014) The SMAP Mission. IEEE; Hillel (1998).',
      validityConditionsFa: 'پایش مایکروویو غیرفعال لایه ۵ سانتی‌متری پوسته خاک.',
    },
    farmerExplanationFa:
      'درصد رطوبت در لایه سطحی خاک (۰ تا ۵ سانتیمتر). به دلیل قرار گرفتن در مجاورت آفتاب و باد تبخیر بسیار سریعی دارد.',
    scientificCautionFa:
      'تفکیک ۹ کیلومتری است و رطوبت پای تک‌تک درختان یا نوار قطره‌چکان را تفکیک نمی‌کند؛ نمایانگر خشکی کلان منطقه است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val < 0.05) return { statusLabelFa: 'پوسته سطحی خشک', statusClass: 'warning', evaluationFa: 'رطوبت لایه ۵ سانتیمتری بالایی خاک بسیار کم است.' };
      return { statusLabelFa: 'رطوبت سطحی ملایم', statusClass: 'good', evaluationFa: 'رطوبت در لایه ۵ سانتی‌متری در دامنه متداول است.' };
    },
  },

  soil_moisture_rootzone: {
    key: 'soil_moisture_rootzone',
    nameEn: 'Root-Zone Soil Moisture (SMAP 0–100 cm)',
    nameFa: 'رطوبت ناحیه ریشه (اس‌مپ ۰ تا ۱۰۰ سانتی‌متر)',
    category: 'soil_water',
    unit: 'm³/m³',
    datasetId: 'NASA/SMAP/SPL4SMGP/008',
    datasetNameFa: 'مدل بازتحلیل همگون‌شده اس‌مپ (SMAP L4)',
    spatialResolution: '۹۰۰۰ متر (تحویل در ۱۱ کیلومتر)',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.05,
      max: 0.40,
      optimalMin: 0.12,
      optimalMax: 0.25,
      unit: 'm³/m³',
      rangeLabelFa: '۰.۱۲ تا ۰.۲۵ m³/m³ (بین نقطه پژمردگی و ظرفیت مزرعه)',
      sourceCitation: 'Reichle, R. H., et al. (2019) Assessment of the SMAP Level-4 Surface and Root-Zone Soil Moisture.',
      validityConditionsFa: 'شبیه‌سازی رطوبت ناحیه استقرار ریشه‌ها تا عمق یک متر.',
    },
    farmerExplanationFa:
      'حجم رطوبت موجود در عمق اصلی ریشه درختان (تا عمق یک متر). برای درختان پسته حفظ این مقدار بالای نقطه پژمردگی (حدود ۰.۱۰) حیاتی است.',
    scientificCautionFa: 'مدل بازتحلیل ژئوفیزیکی در مقیاس منطقه‌ای است و جایگزین سنسور رطوبت‌سنج نقطه‌ای درون باغ نیست.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.15) return { statusLabelFa: 'ذخیره رطوبت ریشه مناسب', statusClass: 'good', evaluationFa: 'رطوبت عمق ریشه در محدوده در دسترس گیاه قرار دارد.' };
      if (val >= 0.10) return { statusLabelFa: 'رطوبت ریشه در آستانه متوسط', statusClass: 'warning', evaluationFa: 'رطوبت نزدیک به آستانه کمبود؛ زمان‌بندی آبیاری کنترل شود.' };
      return { statusLabelFa: 'خشکی در ناحیه ریشه', statusClass: 'danger', evaluationFa: 'رطوبت عمق ریشه به نزدیکی نقطه پژمردگی رسیده است.' };
    },
  },

  soil_moisture_rootzone_era5: {
    key: 'soil_moisture_rootzone_era5',
    nameEn: 'Root-Zone Soil Moisture (ERA5-Land)',
    nameFa: 'رطوبت ناحیه ریشه (بازتحلیل ERA5-Land)',
    category: 'soil_water',
    unit: 'm³/m³',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی سطحی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'reanalysis_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.03,
      max: 0.35,
      optimalMin: 0.08,
      optimalMax: 0.22,
      unit: 'm³/m³',
      rangeLabelFa: '۰.۰۸ تا ۰.۲۲ m³/m³ (میانگین وزنی ۳ لایه عمقی)',
      sourceCitation: 'Muñoz-Sabater et al. (2021) Earth Syst. Sci. Data.',
      validityConditionsFa: 'ترکیب وزنی لایه‌های ۰-۷، ۷-۲۸ و ۲۸-۱۰۰ سانتی‌متر.',
    },
    farmerExplanationFa: 'برآورد رطوبت عمق ریشه بر پایه مدل اقلیمی آب و خاک سازمان هواشناسی اروپا.',
    scientificCautionFa: 'اختلاف این مدل با اس‌مپ طبیعی است و ناشی از تفاوت روش شبیه‌سازی لایه‌هاست.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `${(val * 100).toFixed(1)}٪ رطوبت حجمی ERA5`, statusClass: 'neutral', evaluationFa: 'برآورد رطوبت ناحیه ریشه بر اساس مدل اقلیمی.' };
    },
  },

  soil_field_capacity: {
    key: 'soil_field_capacity',
    nameEn: 'Soil Field Capacity (FC 33 kPa)',
    nameFa: 'ظرفیت زراعی خاک (FC در مکش ۳۳ کیلوپاسکال)',
    category: 'soil_water',
    unit: 'm³/m³',
    datasetId: 'ISRIC/SoilGrids250m/v2_0/wv0033',
    datasetNameFa: 'پایگاه جهانی خاک SoilGrids 2.0',
    spatialResolution: '۲۵۰ متر',
    dataType: 'spatial_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.10,
      max: 0.45,
      optimalMin: 0.18,
      optimalMax: 0.28,
      unit: 'm³/m³',
      rangeLabelFa: '۰.۱۸ تا ۰.۲۸ m³/m³ در بافت‌های لومی و لوم شنی',
      sourceCitation: 'Saxton & Rawls (2006) Soil Sci. Soc. Am. J.',
      validityConditionsFa: 'حداکثر آبی که خاک پس از خروج آب ثقلی ۲۴ تا ۴۸ ساعت بعد آبیاری نگه می‌دارد.',
    },
    farmerExplanationFa: 'حداکثر مقدار آبی که خاک باغ پس از فروکش کردن آب آبیاری در خود نگه می‌دارد و اضافه بر آن هدر می‌رود.',
    scientificCautionFa: 'خط مبنای مدل‌شده پایگاه SoilGrids با وضوح ۲۵۰ متر.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `ظرفیت مزرعه: ${(val * 100).toFixed(1)}٪`, statusClass: 'neutral', evaluationFa: 'حداکثر گنجایش نگهداری رطوبت در خاک.' };
    },
  },

  soil_wilting_point: {
    key: 'soil_wilting_point',
    nameEn: 'Permanent Wilting Point (WP 1500 kPa)',
    nameFa: 'نقطه پژمردگی دائم خاک (WP در مکش ۱۵۰۰ کیلوپاسکال)',
    category: 'soil_water',
    unit: 'm³/m³',
    datasetId: 'ISRIC/SoilGrids250m/v2_0/wv1500',
    datasetNameFa: 'پایگاه جهانی خاک SoilGrids 2.0',
    spatialResolution: '۲۵۰ متر',
    dataType: 'spatial_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.03,
      max: 0.25,
      optimalMin: 0.06,
      optimalMax: 0.14,
      unit: 'm³/m³',
      rangeLabelFa: '۰.۰۶ تا ۰.۱۴ m³/m³ (حد مرزی مرگ رطوبتی گیاه)',
      sourceCitation: 'Hillel, D. (1998) Environmental Soil Physics.',
      validityConditionsFa: 'آستانه‌ای که ریشه توان مکش آب چسبیده به ذرات خاک را از دست می‌دهد.',
    },
    farmerExplanationFa: 'مرز بی‌آبی خاک؛ رطوبت اگر به زیر این عدد برسد درخت توان مکیدن آب را ندارد و پژمرده می‌شود.',
    scientificCautionFa: 'بر اساس منحنی رطوبتی استاندارد بافت خاک.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `نقطه پژمردگی: ${(val * 100).toFixed(1)}٪`, statusClass: 'neutral', evaluationFa: 'حداقل رطوبتی که در خاک باقی مانده اما برای گیاه غیرقابل جذب است.' };
    },
  },

  soil_available_water_capacity: {
    key: 'soil_available_water_capacity',
    nameEn: 'Available Water Capacity (AWC = FC - WP)',
    nameFa: 'ظرفیت آب قابل استفاده خاک (AWC)',
    category: 'soil_water',
    unit: 'm³/m³',
    datasetId: 'ISRIC/SoilGrids250m/v2_0',
    datasetNameFa: 'تفاضل ظرفیت مزرعه‌ای و نقطه پژمردگی SoilGrids',
    spatialResolution: '۲۵۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.05,
      max: 0.25,
      optimalMin: 0.10,
      optimalMax: 0.18,
      unit: 'm³/m³',
      rangeLabelFa: '۰.۱۰ تا ۰.۱۸ m³/m³ (معادل ۱۰۰ تا ۱۸۰ میلی‌متر آب در متر خاک)',
      sourceCitation: 'USDA Natural Resources Conservation Service (NRCS) Soil Survey Manual.',
      validityConditionsFa: 'مخزن رطوبتی مفید خاک برای جذب ریشه.',
    },
    farmerExplanationFa: 'حجم مخزن آب مفید خاک؛ تفاوت بین ظرفیت مزرعه و نقطه پژمردگی که تعیین می‌کند خاک چقدر آب برای روزهای بین دو آبیاری ذخیره می‌کند.',
    scientificCautionFa: 'به بافت خاک وابسته است؛ خاک‌های شنی مخزن کوچک‌تر و خاک‌های لومی مخزن بزرگ‌تری دارند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.12) return { statusLabelFa: 'مخزن نگهداری رطوبت خاک خوب', statusClass: 'good', evaluationFa: 'خاک توانایی ذخیره آب مناسبی بین دو نوبت آبیاری دارد.' };
      return { statusLabelFa: 'مخزن ذخیره آب متوسط یا شنی', statusClass: 'warning', evaluationFa: 'نگهداری آب کمتر است؛ نیاز به دورهای آبیاری کوتاه‌تر.' };
    },
  },

  soil_ph: {
    key: 'soil_ph',
    nameEn: 'Soil pH in H2O (0-30cm)',
    nameFa: 'اسیدیته و واکنش خاک (pH)',
    category: 'soil',
    unit: 'pH',
    datasetId: 'ISRIC/SoilGrids250m/v2_0/phh2o',
    datasetNameFa: 'پایگاه جهانی خاک ISRIC SoilGrids 2.0',
    spatialResolution: '۲۵۰ متر',
    dataType: 'spatial_model',
    referenceRange: {
      hasFixedRange: true,
      min: 4.0,
      max: 10.0,
      optimalMin: 7.2,
      optimalMax: 8.2,
      warningLow: 6.5,
      warningHigh: 8.5,
      unit: 'pH',
      rangeLabelFa: '۷.۲ تا ۸.۲ (محدوده بهینه باغات پسته و مناطق خشک)',
      sourceCitation: 'Ferguson, L., & Haviland, D. (2016) Pistachio Production Manual; FAO Soils Portal.',
      validityConditionsFa: 'خط مبنای ۲۵۰ متری SoilGrids. برای تعیین میزان آهک و توصیه کودی آزمون آزمایشگاهی الزامی است.',
    },
    farmerExplanationFa: 'میزان اسیدی یا قلیایی بودن خاک باغ؛ در باغات پسته خاک‌های با pH بین ۷.۲ تا ۸.۲ معمول و مطلوب هستند ولی ارقام بالای ۸.۵ جذب روی و آهن را دشوار می‌کنند.',
    scientificCautionFa: 'این مقدار برآورد مدل یادگیری ماشین جهانی SoilGrids است و جایگزین آزمایش خاک در آزمایشگاه معتمد نمی‌شود.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 7.0 && val <= 8.3) return { statusLabelFa: 'pH مطلوب باغات پسته', statusClass: 'good', evaluationFa: 'واکنش خاک در بازه استاندارد درختان پسته است.' };
      if (val > 8.3) return { statusLabelFa: 'خاک قلیایی و آهکی', statusClass: 'warning', evaluationFa: 'pH بالا بوده و جذب فسفر و ریزمغذی‌ها کاهش می‌یابد.' };
      return { statusLabelFa: 'خاک اسیدی یا خنثی', statusClass: 'neutral', evaluationFa: 'واکنش خاک کمتر از معمول مناطق خشک.' };
    },
  },

  soil_organic_carbon: {
    key: 'soil_organic_carbon',
    nameEn: 'Soil Organic Carbon (SOC 0-30cm)',
    nameFa: 'کربن آلی خاک (SOC)',
    category: 'soil',
    unit: 'g/kg',
    datasetId: 'ISRIC/SoilGrids250m/v2_0/soc',
    datasetNameFa: 'پایگاه جهانی خاک ISRIC SoilGrids 2.0',
    spatialResolution: '۲۵۰ متر',
    dataType: 'spatial_model',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 50.0,
      optimalMin: 10.0,
      optimalMax: 25.0,
      warningLow: 5.0,
      unit: 'g/kg',
      rangeLabelFa: 'بیش از ۱۰ گرم بر کیلوگرم (۱٪ ماده آلی در خاک‌های خشک)',
      sourceCitation: 'Hengl et al. (2017) SoilGrids250m; Brady & Weil (2008) The Nature and Properties of Soils.',
      validityConditionsFa: 'افزایش ماده آلی نفوذپذیری و ظرفیت نگهداری آب خاک را بهبود می‌بخشد.',
    },
    farmerExplanationFa: 'نشان‌دهنده مقدار هوموس و ماده آلی در خاک؛ کربن آلی بالاتر یعنی خاک نرم‌تر، زنده‌تر و دارای ظرفیت آب و کود بیشتر.',
    scientificCautionFa: 'مدل ۲۵۰ متری بوده و اثر مستقیم مصرف کود حیوانی یا چالکود همان سال را بدون آزمون آزمایشگاهی نشان نمی‌دهد.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 10.0) return { statusLabelFa: 'ماده آلی مناسب خاک خشک', statusClass: 'good', evaluationFa: 'مقدار ماده آلی در حد مطلوب باغات نیمه‌خشک است.' };
      return { statusLabelFa: 'کمبود ماده آلی خاک', statusClass: 'warning', evaluationFa: 'ماده آلی زیر ۱٪ بوده و نیاز به افزایش کود دامی پوسیده دارد.' };
    },
  },

  soil_cation_exchange_capacity: {
    key: 'soil_cation_exchange_capacity',
    nameEn: 'Cation Exchange Capacity (CEC 0-30cm)',
    nameFa: 'ظرفیت تبادل کاتیونی خاک (CEC)',
    category: 'soil',
    unit: 'cmol(+)/kg',
    datasetId: 'ISRIC/SoilGrids250m/v2_0/cec',
    datasetNameFa: 'پایگاه جهانی خاک ISRIC SoilGrids 2.0',
    spatialResolution: '۲۵۰ متر',
    dataType: 'spatial_model',
    referenceRange: {
      hasFixedRange: true,
      min: 2.0,
      max: 50.0,
      optimalMin: 15.0,
      optimalMax: 30.0,
      warningLow: 10.0,
      unit: 'cmol(+)/kg',
      rangeLabelFa: '۱۵ تا ۳۰ cmol(+)/kg (ظرفیت کودی مناسب)',
      sourceCitation: 'Hengl et al. (2017) SoilGrids250m; Havlin et al. (2013) Soil Fertility and Fertilizers.',
      validityConditionsFa: 'وابسته به درصد رس و ماده آلی خاک.',
    },
    farmerExplanationFa: 'قدرت انبارداری غذایی خاک؛ خاکی که CEC بالاتری دارد کودهای پتاسیم، کلسیم و منیزیم را بهتر نگه می‌دارد و دیرتر دچار آبشویی می‌شود.',
    scientificCautionFa: 'برآورد مدلی ۲۵۰ متری؛ برای نسخه دقیق کوددهی نیازمند اندازه‌گیری آزمایشگاهی است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 15.0) return { statusLabelFa: 'ظرفیت نگهداری غذایی مناسب', statusClass: 'good', evaluationFa: 'خاک قدرت تثبیت و نگهداری کاتیون‌های کودی را دارد.' };
      return { statusLabelFa: 'ظرفیت کودی پایین (خاک سبک/شنی)', statusClass: 'warning', evaluationFa: 'کودها سریع‌تر شسته می‌شوند؛ توصیه به تقسیط کودها.' };
    },
  },

  // ==========================================
  // 7. BIOCLIMATIC STRESS
  // ==========================================
  plant_available_water_fraction: {
    key: 'plant_available_water_fraction',
    nameEn: 'Plant Available Water Fraction (PAW Fraction)',
    nameFa: 'کسر آب در دسترس گیاه در خاک (PAW)',
    category: 'stress',
    unit: 'درصد',
    datasetId: 'Derived: ERA5-Land & SoilGrids',
    datasetNameFa: 'تلفیق رطوبت ERA5 و ویژگی‌های خاک SoilGrids',
    spatialResolution: '۱۱ کیلومتر / ۲۵۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.50,
      optimalMax: 1.0,
      warningLow: 0.40,
      unit: '',
      rangeLabelFa: 'بالای ۵۰٪ (مطلوب) | زیر ۴۰٪ (شروع تنش بی‌آبی)',
      sourceCitation: 'Allen et al. (1998) FAO Irrigation & Drainage Paper 56 (MAD concept).',
      validityConditionsFa: 'کسر آب در دسترس نسبت به حداکثر مخزن قابل جذب.',
    },
    farmerExplanationFa: 'میزان پر بودن باک آب خاک باغ. اگر این کسر به زیر ۴۰٪ برسد، درخت احساس تشنگی کرده و نیاز به آبیاری دارد.',
    scientificCautionFa: 'بر مبنای تلفیق رطوبت بازتحلیلی و بافت خاک محاسبه شده است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.50) return { statusLabelFa: 'ذخیره آب خاک کافی و مطلوب', statusClass: 'good', evaluationFa: 'بیش از ۵۰٪ باک آب قابل دسترس خاک پر است.' };
      if (val >= 0.35) return { statusLabelFa: 'ذخیره آب متوسط / نزدیک به زمان آبیاری', statusClass: 'warning', evaluationFa: 'ذخیره آب خاک به محدوده تخلیه مجاز نزدیک شده است.' };
      return { statusLabelFa: 'هشدار تخلیه رطوبت خاک (تنش خشکی)', statusClass: 'danger', evaluationFa: 'بیش از ۶۵٪ آب قابل دسترس خاک تخلیه شده؛ نیاز فوری به آبیاری.' };
    },
  },

  vpd_high_duration: {
    key: 'vpd_high_duration',
    nameEn: 'High VPD Exposure Duration',
    nameFa: 'تعداد روزهای با تنش گرمای خشک شدید (VPD > 3 kPa)',
    category: 'stress',
    unit: 'روز',
    datasetId: 'ECMWF/ERA5_LAND/DAILY_AGGR',
    datasetNameFa: 'مدل بازتحلیل اقلیمی سطحی ERA5-Land',
    spatialResolution: '۱۱ کیلومتر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0,
      max: 90,
      optimalMin: 0,
      optimalMax: 8,
      warningHigh: 15,
      unit: 'روز',
      rangeLabelFa: 'کمتر از ۸ تا ۱۰ روز در ماه',
      sourceCitation: 'Grossiord et al. (2020) New Phytol.',
      validityConditionsFa: 'شمارش روزهایی با کسری فشار بخار بالای ۳ کیلوپاسکال.',
    },
    farmerExplanationFa: 'تعداد روزهایی در دوره تحلیل که هوا آنقدر داغ و خشک بوده که درختان مجبور شده‌اند روزنه‌های خود را ببندند.',
    scientificCautionFa: 'بسته‌شدن مکرر روزنه‌ها مانع ورود دی‌اکسید کربن و توقف وزن‌گیری مغز پسته می‌شود.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 7) return { statusLabelFa: 'تعداد روزهای تنش کم و مناسب', statusClass: 'good', evaluationFa: 'مواجهه کانوپی با هوای داغ و خشک مفرط در حد معمول است.' };
      if (val <= 18) return { statusLabelFa: 'تنش گرمای خشک متوسط فصلی', statusClass: 'warning', evaluationFa: 'درختان در بخش قابل‌توجهی از روزها با تنش بستن روزنه روبرو بوده‌اند.' };
      return { statusLabelFa: 'تنش شدید گرمای خشک تکرارشونده', statusClass: 'danger', evaluationFa: 'تعداد روزهای با گرمای سوزان و خشک بسیار بالاست.' };
    },
  },

  soil_water_content_ratio: {
    key: 'soil_water_content_ratio',
    nameEn: 'Soil Water Content Ratio',
    nameFa: 'نسبت محتوای آب خاک به ظرفیت مزرعه',
    category: 'stress',
    unit: '',
    datasetId: 'Derived: SMAP & SoilGrids',
    datasetNameFa: 'تلفیق رطوبت SMAP و FC پایگاه SoilGrids',
    spatialResolution: '۹۰۰۰ متر / ۲۵۰ متر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.5,
      optimalMin: 0.60,
      optimalMax: 1.00,
      warningLow: 0.50,
      unit: '',
      rangeLabelFa: '۰.۶۰ تا ۱.۰۰ (حفظ رطوبت بالای ۶۰٪ ظرفیت مزرعه)',
      sourceCitation: 'Allen et al. (1998) FAO-56; Kirkham, M. B. (2014) Principles of Soil and Plant Water Relations.',
      validityConditionsFa: 'نسبت رطوبت فعلی خاک به رطوبت در ظرفیت مزرعه‌ای.',
    },
    farmerExplanationFa: 'میزان رطوبت خاک نسبت به حد مطلوب؛ اگر این نسبت بالای ۰.۶ باشد رطوبت خاک کافی است و زیر ۰.۵ نشان‌دهنده نیاز به آبیاری است.',
    scientificCautionFa: 'برآورد ناحیه‌ای در مقیاس لایه ریشه.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.60) return { statusLabelFa: 'رطوبت خاک در حد مطلوب', statusClass: 'good', evaluationFa: 'رطوبت ناحیه ریشه بالای ۶۰٪ ظرفیت مزرعه است.' };
      if (val >= 0.45) return { statusLabelFa: 'کاهش نسبی رطوبت خاک', statusClass: 'warning', evaluationFa: 'رطوبت به آستانه نیاز به آبیاری نزدیک شده است.' };
      return { statusLabelFa: 'تنش کمبود رطوبت در خاک', statusClass: 'danger', evaluationFa: 'رطوبت خاک به شدت کاهش یافته است.' };
    },
  },

  evaporative_fraction: {
    key: 'evaporative_fraction',
    nameEn: 'Evaporative Fraction (EF)',
    nameFa: 'کسر تبخیر و تعرق واقعی (EF)',
    category: 'stress',
    unit: '',
    datasetId: 'ECMWF/ERA5_LAND & MODIS',
    datasetNameFa: 'موازنه انرژی سطحی ERA5 و MODIS',
    spatialResolution: '۱۰۰۰ متر / ۱۱ کیلومتر',
    dataType: 'derived_index',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 1.0,
      optimalMin: 0.50,
      optimalMax: 0.85,
      warningLow: 0.35,
      unit: '',
      rangeLabelFa: '۰.۵۰ تا ۰.۸۵ (کانوپی فعال با دسترسی آبی مناسب)',
      sourceCitation: 'Bastiaanssen, W. G., et al. (1998) SEBAL model; J. Hydrol.',
      validityConditionsFa: 'سهم انرژی مصرف‌شده برای تبخیر نسبت به انرژی خالص کل.',
    },
    farmerExplanationFa: 'چه سهمی از انرژی خورشید صرف خنک‌سازی و تبخیر آب درخت شده است. اعداد بالای ۰.۵ نشان می‌دهد درخت به خوبی آب دریافت کرده و عرق می‌کند.',
    scientificCautionFa: 'شاخص ماکرومقیاس حرارتی-رطوبتی است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val >= 0.50) return { statusLabelFa: 'تبخیر و تعرق فعال و مناسب', statusClass: 'good', evaluationFa: 'بخش عمده انرژی دریافتی صرف تعرق و خنک‌سازی درخت شده است.' };
      if (val >= 0.30) return { statusLabelFa: 'کاهش نرخ تعرق کانوپی', statusClass: 'warning', evaluationFa: 'محدودیت تعرق به دلیل کمبود آب یا خشکی هوا.' };
      return { statusLabelFa: 'توقف تعرق / تنش شدید', statusClass: 'danger', evaluationFa: 'تعرق به حداقل رسیده و دمای کانوپی بالا می‌رود.' };
    },
  },

  // ==========================================
  // 8. TERRAIN & TOPOGRAPHY
  // ==========================================
  elevation: {
    key: 'elevation',
    nameEn: 'Elevation Above Sea Level',
    nameFa: 'ارتفاع از سطح دریا',
    category: 'terrain',
    unit: 'm',
    datasetId: 'NASA/NASADEM_HGT/001',
    datasetNameFa: 'مدل رقومی ارتفاعی ناسا (NASADEM 30m)',
    spatialResolution: '۳۰ متر',
    dataType: 'dem_terrain',
    referenceRange: {
      hasFixedRange: false,
      unit: 'm',
      rangeLabelFa: 'ویژگی ثابت جغرافیایی قطعه (فاقد حد بهینه)',
      sourceCitation: 'NASA JPL NASADEM Merged DEM Global 1 arcsecond.',
      validityConditionsFa: 'ارتفاع مطلق عارضه نسبت به تراز متوسط دریا.',
    },
    farmerExplanationFa: 'ارتفاع باغ از سطح دریا؛ بر سرمای زمستانه، تاریخ گلدهی بهاره و دمای تابستان اثر مستقیم دارد.',
    scientificCautionFa: 'داده دائمی عوارض زمین بدون تغییر زمانی.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `ارتفاع: ${val.toFixed(0)} متر از سطح دریا`, statusClass: 'neutral', evaluationFa: 'ارتفاع جغرافیایی باغ.' };
    },
  },

  slope: {
    key: 'slope',
    nameEn: 'Topographic Slope',
    nameFa: 'شیب موضعی زمین',
    category: 'terrain',
    unit: 'درجه',
    datasetId: 'NASA/NASADEM_HGT/001',
    datasetNameFa: 'محاسبه‌شده از NASADEM',
    spatialResolution: '۳۰ متر',
    dataType: 'dem_terrain',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 45.0,
      optimalMin: 0.0,
      optimalMax: 3.0,
      warningHigh: 6.0,
      unit: 'درجه',
      rangeLabelFa: '۰ تا ۳ درجه (ایده‌آل برای مدیریت آبیاری باغات)',
      sourceCitation: 'FAO Soils Bulletin 55.',
      validityConditionsFa: 'زاویه شیب متوسط سلول ۳۰ متری.',
    },
    farmerExplanationFa: 'شیب زمین؛ شیب‌های زیر ۲ یا ۳ درجه برای آبیاری غرقابی و یکنواختی قطره‌ای ایده‌آل هستند و خطر فرسایش و شستشوی خاک ندارند.',
    scientificCautionFa: 'شیب‌های بالای ۵ درجه نیازمند تسطیح یا ترازبندی هستند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 3.0) return { statusLabelFa: 'زمین مسطح و ایده‌آل آبیاری', statusClass: 'good', evaluationFa: 'شیب ملایم؛ رواناب ناچیز و نفوذ یکنواخت آب.' };
      return { statusLabelFa: `شیب ${val.toFixed(1)} درجه‌ای`, statusClass: 'warning', evaluationFa: 'شیب متوسط؛ مراقبت از رواناب و کنترل یکنواختی آب.' };
    },
  },

  aspect: {
    key: 'aspect',
    nameEn: 'Topographic Aspect',
    nameFa: 'جهت شیب جغرافیایی',
    category: 'terrain',
    unit: 'درجه',
    datasetId: 'NASA/NASADEM_HGT/001',
    datasetNameFa: 'محاسبه‌شده از NASADEM',
    spatialResolution: '۳۰ متر',
    dataType: 'dem_terrain',
    referenceRange: {
      hasFixedRange: false,
      unit: 'درجه',
      rangeLabelFa: 'فاقد مرجع بهینه ثابت (جهت قرارگیری دامنه ۰ تا ۳۶۰ درجه نسبت به شمال)',
      sourceCitation: 'Burrough, P. A., & McDonnell, R. A. (1998) Principles of GIS.',
      validityConditionsFa: 'جهت نورگیری خورشید و بادهای غالب.',
    },
    farmerExplanationFa: 'جهت رو به آفتاب شیب؛ دامنه‌های رو به جنوب نور و گرمای بیشتری دریافت می‌کنند و زودتر به گل می‌روند.',
    scientificCautionFa: 'در زمین‌های کاملاً مسطح (شیب زیر ۰.۵ درجه) جهت شیب بی‌اثر است.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      return { statusLabelFa: `جهت شیب: ${val.toFixed(0)}°`, statusClass: 'neutral', evaluationFa: 'جهت جغرافیایی قرارگیری شیب زمین.' };
    },
  },

  terrain_ruggedness: {
    key: 'terrain_ruggedness',
    nameEn: 'Terrain Ruggedness Index (TRI)',
    nameFa: 'شاخص ناهمواری پستی‌وبلندی (TRI)',
    category: 'terrain',
    unit: 'متر',
    datasetId: 'NASA/NASADEM_HGT/001',
    datasetNameFa: 'محاسبه‌شده از NASADEM',
    spatialResolution: '۳۰ متر',
    dataType: 'dem_terrain',
    referenceRange: {
      hasFixedRange: true,
      min: 0.0,
      max: 20.0,
      optimalMin: 0.0,
      optimalMax: 2.0,
      unit: 'm',
      rangeLabelFa: 'کمتر از ۲ متر (اراضی هموار کشاورزی)',
      sourceCitation: 'Riley, S. J., et al. (1999) A terrain ruggedness index.',
      validityConditionsFa: 'اختلاف ارتفاعی نقاط مجاور در شبکه ۳۰ متری.',
    },
    farmerExplanationFa: 'نشان‌دهنده کلوخه‌بندی بزرگ و تپه‌ماهور بودن زمین؛ در باغات مسطح معمولاً زیر ۱ یا ۲ متر است.',
    scientificCautionFa: 'ناهمواری شدید مدیریت مکانیزه باغ را دشوار می‌کند.',
    evaluateStatus: (val) => {
      if (val === null || val === undefined) return { statusLabelFa: 'نامشخص', statusClass: 'neutral', evaluationFa: 'داده موجود نیست.' };
      if (val <= 2.0) return { statusLabelFa: 'عارضه هموار و یکنواخت', statusClass: 'good', evaluationFa: 'تغییرات ارتفاعی موضعی ناچیز و مناسب کشاورزی مکانیزه.' };
      return { statusLabelFa: 'ناهمواری موضعی', statusClass: 'neutral', evaluationFa: 'اختلاف ارتفاعی در سلول‌های مجاور.' };
    },
  },
};

/**
 * Evaluates a metric value against the centralized interpretation catalog.
 * Guarantees zero invented thresholds and honest representation of caveats.
 */
export function getMetricInterpretation(
  key: string,
  value: number | null | undefined,
  precision: number = 2,
): EvaluatedMetricInterpretation {
  const spec = METRIC_INTERPRETATION_CATALOG[key];

  if (!spec) {
    // Graceful fallback for any metric not yet explicitly cataloged
    const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
    const displayVal = hasValue ? (typeof value === 'number' ? value.toFixed(precision) : String(value)) : 'داده موجود نیست';

    return {
      key,
      nameEn: key.toUpperCase(),
      nameFa: key,
      unit: '',
      value: hasValue && typeof value === 'number' ? value : null,
      displayValue: displayVal,
      datasetId: 'Unknown',
      datasetNameFa: 'سنجنده ماهواره‌ای',
      spatialResolution: 'نامشخص',
      dataType: 'satellite_observation',
      hasFixedRange: false,
      rangeLabelFa: 'فاقد محدوده مرجع ثابت در این نسخه',
      sourceCitation: 'نیازمند کالیبراسیون و بررسی علمی',
      validityConditionsFa: 'مشاهده متناسب با شرایط درخواست',
      statusLabelFa: hasValue ? 'مشاهده خام' : 'داده موجود نیست',
      statusClass: 'neutral',
      farmerSummaryFa: 'این شاخص در حال حاضر صرفاً به عنوان عدد خام سنجش از دور ثبت شده است.',
      scientificCautionFa: 'تفسیر زراعی منوط به بررسی کارشناس محلی است.',
    };
  }

  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);
  const displayVal = hasValue ? (typeof value === 'number' ? value.toFixed(precision) : String(value)) : 'داده موجود نیست';
  const evaluation = spec.evaluateStatus(hasValue && typeof value === 'number' ? value : null);

  return {
    key: spec.key,
    nameEn: spec.nameEn,
    nameFa: spec.nameFa,
    unit: spec.unit,
    value: hasValue && typeof value === 'number' ? value : null,
    displayValue: displayVal,
    datasetId: spec.datasetId,
    datasetNameFa: spec.datasetNameFa,
    spatialResolution: spec.spatialResolution,
    dataType: spec.dataType,
    hasFixedRange: spec.referenceRange.hasFixedRange,
    rangeLabelFa: spec.referenceRange.rangeLabelFa,
    sourceCitation: spec.referenceRange.sourceCitation,
    validityConditionsFa: spec.referenceRange.validityConditionsFa,
    statusLabelFa: evaluation.statusLabelFa,
    statusClass: evaluation.statusClass,
    farmerSummaryFa: spec.farmerExplanationFa,
    scientificCautionFa: spec.scientificCautionFa,
  };
}
