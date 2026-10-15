import type {
  EvidenceItemResponse,
} from '../../types/index.ts';
import { isFiniteNumber } from './parse.ts';
import {
  getMetricInterpretation,
  type EvaluatedMetricInterpretation,
} from './metricInterpretation.ts';

export type MetricDataState = 'available' | 'limited' | 'insufficient';

export type MetricCategoryKey =
  | 'vegetation'
  | 'moisture'
  | 'thermal'
  | 'radar'
  | 'terrain'
  | 'soil_water'
  | 'climate'
  | 'stress';

export interface MetricDefinition {
  key: string;
  name: string;
  nameFa: string;
  category: MetricCategoryKey;
  unitDefault: string;
  descriptionFa: string;
  isCoarseResolution?: boolean;
  coarseNoteFa?: string;
  precision?: number;
}

export interface CategoryGroup {
  key: MetricCategoryKey;
  title: string;
  titleFa: string;
  icon: string;
  descriptionFa: string;
  metrics: MetricDefinition[];
}

export const METRIC_CATEGORIES: CategoryGroup[] = [
  {
    key: 'vegetation',
    title: 'Vegetation Signals',
    titleFa: 'پوشش گیاهی',
    icon: '🌿',
    descriptionFa: 'شاخص‌های انعکاس طیفی نور قرمز و مادون قرمز نزدیک برای توصیف سبزی و فعالیت فتوسنتزی',
    metrics: [
      {
        key: 'ndvi',
        name: 'Normalized Difference Vegetation Index (NDVI)',
        nameFa: 'شاخص پوشش گیاهی تفاضلی نرمال‌شده (NDVI)',
        category: 'vegetation',
        unitDefault: '',
        descriptionFa: 'شاخص عمومی سبزی و تراکم کانوپی فعال بر پایه سنتینل-۲ (۱۰ متری)',
        precision: 4,
      },
      {
        key: 'savi',
        name: 'Soil-Adjusted Vegetation Index (SAVI)',
        nameFa: 'شاخص پوشش گیاهی تعدیل‌شده با خاک (SAVI)',
        category: 'vegetation',
        unitDefault: '',
        descriptionFa: 'شاخص پوشش گیاهی تعدیل‌شده با ضریب انعکاس زمینه خاک (مناسب خاک‌های کم‌پوشش)',
        precision: 4,
      },
      {
        key: 'evi',
        name: 'Enhanced Vegetation Index (EVI)',
        nameFa: 'شاخص بهبودیافته پوشش گیاهی (EVI)',
        category: 'vegetation',
        unitDefault: '',
        descriptionFa: 'شاخص بهینه‌سازی‌شده برای کاهش اثرات جوی و حساسیت بالا در کانوپی‌های متراکم',
        precision: 4,
      },
      {
        key: 'msavi',
        name: 'Modified Soil-Adjusted Vegetation Index (MSAVI)',
        nameFa: 'شاخص پوشش گیاهی تعدیل‌شده اصلاح‌شده (MSAVI)',
        category: 'vegetation',
        unitDefault: '',
        descriptionFa: 'شاخص تعدیل‌شده با خاک بدون نیاز به فاکتور تجربی L؛ مناسب باغات کم‌پوشش',
        precision: 4,
      },
      {
        key: 'ndre',
        name: 'Normalized Difference Red Edge (NDRE)',
        nameFa: 'شاخص لبه قرمز (NDRE)',
        category: 'vegetation',
        unitDefault: '',
        descriptionFa: 'حساس به غلظت کلروفیل کانوپی و تغییرات در مراحل بلوغ گیاهی',
        precision: 4,
      },
      {
        key: 'ndre_anomaly',
        name: 'NDRE Seasonal Anomaly',
        nameFa: 'آنومالی فصلی شاخص لبه قرمز (NDRE Anomaly)',
        category: 'vegetation',
        unitDefault: '',
        descriptionFa: 'انحراف شرایط لبه قرمز کانوپی نسبت به میانگین ۱۰ ساله همان پنجره زمانی فصلی (سنتینل-۲)',
        precision: 4,
      },
    ],
  },
  {
    key: 'moisture',
    title: 'Canopy / Surface Moisture Proxies',
    titleFa: 'رطوبت سطحی و کانوپی',
    icon: '💧',
    descriptionFa: 'شاخص‌های جذب امواج مادون قرمز کوتاه‌موج (SWIR) برای ارزیابی رطوبت فیزیکی برگ و سطح',
    metrics: [
      {
        key: 'ndmi',
        name: 'Normalized Difference Moisture Index (NDMI)',
        nameFa: 'شاخص رطوبت نرمال‌شده (NDMI)',
        category: 'moisture',
        unitDefault: '',
        descriptionFa: 'ارزیابی آب موجود در برگ و ساختار کانوپی با استفاده از باندهای NIR و SWIR',
        precision: 4,
      },
      {
        key: 'msi',
        name: 'Moisture Stress Index (MSI)',
        nameFa: 'شاخص تنش رطوبت (MSI)',
        category: 'moisture',
        unitDefault: '',
        descriptionFa: 'نسبت معکوس آب کانوپی؛ مقادیر بالاتر منعکس‌کننده خشکی نسبی سطح برگ است',
        precision: 4,
      },
      {
        key: 'ndwi',
        name: 'Normalized Difference Water Index (NDWI)',
        nameFa: 'شاخص تفاضلی نرمال‌شده آب (NDWI)',
        category: 'moisture',
        unitDefault: '',
        descriptionFa: 'پاسخ طیفی آب در باند سبز و فروسرخ نزدیک؛ حساس به آب باز و رطوبت اشباع',
        precision: 4,
      },
      {
        key: 'mndwi',
        name: 'Modified Normalized Difference Water Index (MNDWI)',
        nameFa: 'شاخص تفاضلی اصلاح‌شده آب (MNDWI)',
        category: 'moisture',
        unitDefault: '',
        descriptionFa: 'شاخص تفاضلی اصلاح‌شده آب با استفاده از SWIR؛ تمایز قوی‌تر آب سطحی از کانوپی خشک',
        precision: 4,
      },
      {
        key: 'ndmi_anomaly',
        name: 'NDMI Seasonal Anomaly',
        nameFa: 'آنومالی فصلی رطوبت گیاهی (NDMI Anomaly)',
        category: 'moisture',
        unitDefault: '',
        descriptionFa: 'انحراف شاخص رطوبت کانوپی نسبت به میانگین ۱۰ ساله همان بازه تقویمی (سنتینل-۲)',
        precision: 4,
      },
      {
        key: 'msi_anomaly',
        name: 'MSI Seasonal Anomaly',
        nameFa: 'آنومالی فصلی تنش رطوبت (MSI Anomaly)',
        category: 'moisture',
        unitDefault: '',
        descriptionFa: 'انحراف شاخص تنش رطوبت کانوپی نسبت به میانگین ۱۰ ساله همان بازه تقویمی (سنتینل-۲)',
        precision: 4,
      },
    ],
  },
  {
    key: 'thermal',
    title: 'Thermal & Land Surface Temperature',
    titleFa: 'دما و حرارت سطح زمین',
    icon: '🌡️',
    descriptionFa: 'دمای تابشی فیزیکی پوسته زمین (LST)؛ نه دمای فیزیولوژیک اندام داخلی گیاه',
    metrics: [
      {
        key: 'land_surface_temperature_day',
        name: 'Land Surface Temperature Day (LST Day)',
        nameFa: 'دمای روزانه سطح زمین (LST Day)',
        category: 'thermal',
        unitDefault: '°C',
        descriptionFa: 'دمای تابشی پوسته فیزیکی خاک در ساعات روز (سنجنده MODIS، وضوح ۱ کیلومتر)',
        isCoarseResolution: true,
        coarseNoteFa: 'تفکیک مکانی ۱۰۰۰ متری — نشان‌دهنده دمای کلان منطقه، نه تنش تک‌تک بوته‌ها',
        precision: 2,
      },
      {
        key: 'land_surface_temperature_night',
        name: 'Land Surface Temperature Night (LST Night)',
        nameFa: 'دمای شبانه سطح زمین (LST Night)',
        category: 'thermal',
        unitDefault: '°C',
        descriptionFa: 'دمای پوسته خاک در ساعات شب (سنجنده MODIS، وضوح ۱ کیلومتر)',
        isCoarseResolution: true,
        coarseNoteFa: 'تفکیک مکانی ۱۰۰۰ متری',
        precision: 2,
      },
      {
        key: 'landsat_surface_temperature',
        name: 'Landsat Surface Temperature',
        nameFa: 'دمای سطح زمین لندست (Landsat LST)',
        category: 'thermal',
        unitDefault: '°C',
        descriptionFa: 'دمای تابشی سطح زمین با تفکیک ۳۰ متری حرارتی لندست',
        precision: 2,
      },
      {
        key: 'surface_temperature_range',
        name: 'Surface Temperature Diurnal Range (DTR)',
        nameFa: 'دامنه نوسان شبانه‌روزی دمای سطح (DTR)',
        category: 'thermal',
        unitDefault: '°C',
        descriptionFa: 'اختلاف دمای تابشی سطح روز و شب؛ شاخص ظرفیت حرارتی و اینرسی دمایی خاک',
        isCoarseResolution: true,
        coarseNoteFa: 'تفکیک مکانی ۱۰۰۰ متری — نشان‌دهنده تغییرات کلان دمایی شبانه‌روز',
        precision: 2,
      },
    ],
  },
  {
    key: 'radar',
    title: 'Radar Structural Backscatter',
    titleFa: 'رادار و ساختار فیزیکی',
    icon: '📡',
    descriptionFa: 'سیگنال‌های مایکروویو سنتینل-۱ با قابلیت عبور از ابر و حساس به زبری و ساختار هندسی سطح',
    metrics: [
      {
        key: 'vh',
        name: 'Cross-Polarization Backscatter (VH)',
        nameFa: 'پس‌پراکنش قطبش متقاطع (VH)',
        category: 'radar',
        unitDefault: 'dB',
        descriptionFa: 'حساس به پراکنش حجمی، زبری سطح و ساختار عمودی شاخ و برگ',
        precision: 2,
      },
      {
        key: 'vv',
        name: 'Co-Polarization Backscatter (VV)',
        nameFa: 'پس‌پراکنش قطبش هم‌نام (VV)',
        category: 'radar',
        unitDefault: 'dB',
        descriptionFa: 'حساس به زبری پوسته خاک و رطوبت سطحی در زاویه تابش رادار',
        precision: 2,
      },
      {
        key: 'vh_vv',
        name: 'Polarization Ratio (VH/VV)',
        nameFa: 'نسبت قطبش‌های راداری (VH/VV)',
        category: 'radar',
        unitDefault: '',
        descriptionFa: 'شاخص نرمال‌شده برای مقایسه سهم پراکنش حجمی نسبت به پراکنش مستقیم سطحی',
        precision: 4,
      },
      {
        key: 'rvi',
        name: 'Radar Vegetation Index (RVI)',
        nameFa: 'شاخص راداری پوشش گیاهی (RVI)',
        category: 'radar',
        unitDefault: '',
        descriptionFa: 'تقریب راداری تراکم ساختاری بدون تأثیرپذیری از شرایط ابری',
        precision: 4,
      },
    ],
  },
  {
    key: 'terrain',
    title: 'Terrain & Topography',
    titleFa: 'توپوگرافی و عوارض زمین',
    icon: '⛰️',
    descriptionFa: 'ویژگی‌های هندسی و هیدرولوژیکی عوارض زمین بر پایه مدل رقومی ارتفاعی (DEM)',
    metrics: [
      {
        key: 'elevation',
        name: 'Elevation',
        nameFa: 'ارتفاع از سطح دریا',
        category: 'terrain',
        unitDefault: 'm',
        descriptionFa: 'ارتفاع مطلق عارضه نسبت به سطح آزاد آب‌های بین‌المللی',
        precision: 1,
      },
      {
        key: 'slope',
        name: 'Slope',
        nameFa: 'شیب زمین',
        category: 'terrain',
        unitDefault: '°',
        descriptionFa: 'زاویه شیب محلی زمین؛ مؤثر بر رواناب سطحی و نگهداری رطوبت',
        precision: 2,
      },
      {
        key: 'aspect',
        name: 'Aspect',
        nameFa: 'جهت شیب',
        category: 'terrain',
        unitDefault: '°',
        descriptionFa: 'جهت جغرافیایی قرارگیری شیب (زاویه نسبت به شمال جغرافیایی)',
        precision: 1,
      },
      {
        key: 'terrain_ruggedness',
        name: 'Terrain Ruggedness Index (TRI)',
        nameFa: 'شاخص ناهمواری پستی‌وبلندی (TRI)',
        category: 'terrain',
        unitDefault: '',
        descriptionFa: 'میزان تغییرات ناگهانی و ناهمواری تراز ارتفاعی در سلول‌های مجاور',
        precision: 2,
      },
    ],
  },
  {
    key: 'soil_water',
    title: 'Soil Moisture & Water Balance',
    titleFa: 'آب و خاک',
    icon: '🌾',
    descriptionFa: 'برآوردهای ماهواره‌ای و مدلی رطوبت خاک و موازنه آب در مقیاس لایه سطحی و ناحیه ریشه',
    metrics: [
      {
        key: 'soil_moisture_surface',
        name: 'Surface Soil Moisture',
        nameFa: 'رطوبت لایه سطحی خاک (۰ تا ۵ سانتی‌متر)',
        category: 'soil_water',
        unitDefault: 'm³/m³',
        descriptionFa: 'حجم آب موجود در ۵ سانتی‌متر فوقانی پوسته خاک',
        precision: 4,
      },
      {
        key: 'soil_moisture_rootzone',
        name: 'Root-Zone Soil Moisture (SMAP)',
        nameFa: 'رطوبت ناحیه ریشه — مدل ماهواره‌ای SMAP L4',
        category: 'soil_water',
        unitDefault: 'm³/m³',
        descriptionFa: 'برآورد رطوبت لایه ریشه توسط داده‌های ریزموج غیرفعال ماهواره SMAP (تفکیک ۹ کیلومتر)',
        isCoarseResolution: true,
        coarseNoteFa: 'تفکیک مکانی ۹۰۰۰ متری — برای تغییرات کلان منطقه‌ای معتبر است',
        precision: 4,
      },
      {
        key: 'soil_moisture_rootzone_era5',
        name: 'Root-Zone Soil Moisture (ERA5-Land)',
        nameFa: 'رطوبت ناحیه ریشه — بازتحلیل ERA5-Land',
        category: 'soil_water',
        unitDefault: 'm³/m³',
        descriptionFa: 'شبیه‌سازی بازتحلیل اقلیمی سطحی ERA5-Land (تفکیک ۱۱ کیلومتر)',
        isCoarseResolution: true,
        coarseNoteFa: 'تفکیک مکانی بازتحلیلی ۱۱ کیلومتری',
        precision: 4,
      },
      {
        key: 'precipitation',
        name: 'Total Precipitation',
        nameFa: 'بارندگی کل انباشته',
        category: 'soil_water',
        unitDefault: 'mm',
        descriptionFa: 'میزان کل بارش تجمع‌یافته در طول پنجره زمانی تحلیل',
        precision: 1,
      },
      {
        key: 'soil_available_water_capacity',
        name: 'Available Water Capacity (AWC)',
        nameFa: 'ظرفیت آب قابل دسترس خاک (AWC)',
        category: 'soil_water',
        unitDefault: 'mm',
        descriptionFa: 'تفاضل ظرفیت مزرعه‌ای و نقطه پژمردگی بر پایه ویژگی‌های فیزیکی خاک SoilGrids',
        precision: 2,
      },
      {
        key: 'soil_field_capacity',
        name: 'Soil Field Capacity (FC)',
        nameFa: 'ظرفیت مزرعه‌ای خاک (FC)',
        category: 'soil_water',
        unitDefault: 'm³/m³',
        descriptionFa: 'حداکثر رطوبت نگهداری‌شده پس از زهکشی ثقلی (محاسبه پدوانتقالی SoilGrids)',
        precision: 4,
      },
      {
        key: 'soil_wilting_point',
        name: 'Soil Wilting Point (WP)',
        nameFa: 'نقطه پژمردگی دائم خاک (WP)',
        category: 'soil_water',
        unitDefault: 'm³/m³',
        descriptionFa: 'حداقل رطوبت زیر پتانسیل ۱۵ بار (۱.۵ مگاپاسکال) غیرقابل جذب ریشه',
        precision: 4,
      },
    ],
  },
];

export const EXTENDED_METRIC_CATEGORIES: CategoryGroup[] = [
  {
    key: 'climate',
    title: 'Climate & Atmospheric Conditions',
    titleFa: 'اقلیم و شرایط جوّی',
    icon: '☀️',
    descriptionFa: 'داده‌های بازتحلیل ساعتی و روزانه اقلیم و پارامترهای بیوفیزیکی هواشناسی (ERA5-Land)',
    metrics: [
      {
        key: 'vpd',
        name: 'Vapor Pressure Deficit (VPD)',
        nameFa: 'کسری فشار بخار جو (VPD)',
        category: 'climate',
        unitDefault: 'kPa',
        descriptionFa: 'اختلاف فشار بخار اشباع و واقعی هوا؛ پیشران اصلی تعرق و بسته شدن روزنه‌ها',
        precision: 2,
      },
      {
        key: 'temperature_mean',
        name: 'Mean Air Temperature (2m)',
        nameFa: 'میانگین دمای هوا (۲ متری)',
        category: 'climate',
        unitDefault: '°C',
        descriptionFa: 'میانگین دمای هوای ایستگاهی/بازتحلیلی در ارتفاع ۲ متری سطح زمین',
        precision: 1,
      },
      {
        key: 'temperature_max',
        name: 'Maximum Air Temperature',
        nameFa: 'حداکثر دمای هوا',
        category: 'climate',
        unitDefault: '°C',
        descriptionFa: 'بیشینه دمای هوا در پنجره زمانی تحلیل',
        precision: 1,
      },
      {
        key: 'temperature_min',
        name: 'Minimum Air Temperature',
        nameFa: 'حداقل دمای هوا',
        category: 'climate',
        unitDefault: '°C',
        descriptionFa: 'کمینه دمای هوا؛ شاخص پایش سرمازدگی دیررس بهاره',
        precision: 1,
      },
      {
        key: 'relative_humidity',
        name: 'Relative Humidity',
        nameFa: 'رطوبت نسبی هوا',
        category: 'climate',
        unitDefault: '%',
        descriptionFa: 'درصد اشباع رطوبتی جو مجاور کانوپی',
        precision: 1,
      },
      {
        key: 'solar_radiation',
        name: 'Surface Solar Radiation',
        nameFa: 'تابش کل خورشیدی سطح',
        category: 'climate',
        unitDefault: 'MJ/m²',
        descriptionFa: 'کل انرژی تشعشعی موج کوتاه فرودی به سطح زمین',
        precision: 2,
      },
      {
        key: 'gdd',
        name: 'Growing Degree Days (GDD)',
        nameFa: 'درجه-روز رشد انباشته (GDD)',
        category: 'climate',
        unitDefault: '°C·day',
        descriptionFa: 'واحدهای حرارتی انباشته مورد نیاز برای تکمیل مراحل فنولوژی محصول',
        precision: 1,
      },
      {
        key: 'wind_speed',
        name: '10m Wind Speed',
        nameFa: 'سرعت باد در ارتفاع ۱۰ متری',
        category: 'climate',
        unitDefault: 'm/s',
        descriptionFa: 'سرعت افقی باد؛ اثرگذار بر تلفات تبخیر، سم‌پاشی و گردوغبار',
        precision: 1,
      },
    ],
  },
  {
    key: 'stress',
    title: 'Bioclimatic & Hydrologic Stress Indicators',
    titleFa: 'شاخص‌های تنش زیست‌اقلیمی و هیدرولوژیک',
    icon: '⚡',
    descriptionFa: 'شاخص‌های تفکیکی تنش‌های آب، تبخیر و جوی بدون نمره‌سازی ساختگی',
    metrics: [
      {
        key: 'plant_available_water_fraction',
        name: 'Plant Available Water Fraction (PAWF)',
        nameFa: 'کسر آب قابل استفاده گیاه (PAWF)',
        category: 'stress',
        unitDefault: '',
        descriptionFa: 'نسبت آب فعلی موجود در خاک بین نقطه پژمردگی و ظرفیت مزرعه‌ای',
        precision: 3,
      },
      {
        key: 'soil_water_content_ratio',
        name: 'Soil Water Content Ratio',
        nameFa: 'نسبت محتوای آب خاک',
        category: 'stress',
        unitDefault: '',
        descriptionFa: 'نسبت رطوبت اندازه ریشه به ظرفیت نگهداری خاک',
        precision: 3,
      },
      {
        key: 'vpd_high_duration',
        name: 'High VPD Duration Hours',
        nameFa: 'ساعات ماندگاری VPD بحرانی',
        category: 'stress',
        unitDefault: 'h',
        descriptionFa: 'مدت ساعاتی که کسری فشار بخار بالای ۳.۰ کیلوپاسکال بوده و تنش روزنه‌ای ایجاد کرده است',
        precision: 1,
      },
      {
        key: 'evaporative_fraction',
        name: 'Evaporative Fraction (EF)',
        nameFa: 'کسر تبخیر واقعی به انرژی در دسترس',
        category: 'stress',
        unitDefault: '',
        descriptionFa: 'نسبت شار حرارت نهان تبخیر به مجموع شارهای خالص سطحی',
        precision: 3,
      },
    ],
  },
];

export interface EvaluatedMetricState {
  state: MetricDataState;
  displayValue: string;
  unit: string;
  reasonFa: string;
  badgeLabel: string;
  badgeClass: string;
  interpretation?: EvaluatedMetricInterpretation;
}

/**
 * Determine the 3 distinct data states strictly per requirement 5.
 * Never converts missing data or 0 valid pixels into numeric 0.
 */
export function evaluateMetricState(
  item: EvidenceItemResponse | null | undefined,
  metricDef: MetricDefinition,
): EvaluatedMetricState {
  const prec = metricDef.precision ?? 4;
  const numVal = item && isFiniteNumber(item.value) ? item.value : null;
  const interpretation = getMetricInterpretation(metricDef.key, numVal, prec);

  if (!item) {
    return {
      state: 'insufficient',
      displayValue: 'داده قابل استفاده موجود نیست',
      unit: '',
      reasonFa: 'این شاخص در بسته شواهد بازگشتی موجود نیست',
      badgeLabel: '🔴 ناکافی / No data',
      badgeClass: 'badge-danger',
      interpretation,
    };
  }

  // Check 0 valid pixels or un-usable flags
  const stats = item.stats;
  const zeroPixels =
    stats &&
    typeof stats.valid_pixel_count === 'number' &&
    stats.valid_pixel_count === 0;

  if (
    item.status === 'unavailable' ||
    !item.is_usable ||
    item.value === null ||
    item.value === undefined ||
    zeroPixels ||
    !isFiniteNumber(item.value)
  ) {
    let reason = 'داده معتبر در این محدوده مکانی یا زمانی ثبت نشد';
    if (zeroPixels) {
      reason = '۰ پیکسل معتبر در محدوده انتخابی یافت نشد (0 valid pixels)';
    } else if (item.unavailable_reason) {
      reason = item.unavailable_reason;
    } else if (item.unavailable_message) {
      reason = item.unavailable_message;
    }

    return {
      state: 'insufficient',
      displayValue: 'داده قابل استفاده موجود نیست',
      unit: '',
      reasonFa: reason,
      badgeLabel: '🔴 ناکافی / Insufficient',
      badgeClass: 'badge-danger',
      interpretation,
    };
  }

  // Real finite numeric value
  const formattedVal = numVal !== null ? numVal.toFixed(prec) : 'داده قابل استفاده موجود نیست';
  const unit = item.unit || metricDef.unitDefault;

  // Evaluate if state is Limited (coarse resolution, proxy, or quality caveats)
  const isCoarse =
    metricDef.isCoarseResolution === true ||
    (item.provenance &&
      typeof item.provenance.source_dataset_id === 'string' &&
      (item.provenance.source_dataset_id.includes('MODIS') ||
        item.provenance.source_dataset_id.includes('SMAP') ||
        item.provenance.source_dataset_id.includes('ERA5')));

  const isProxy = item.is_proxy === true;
  const isLimitedQuality =
    item.quality === 'limited' || item.quality === 'uncertain' || item.quality === 'poor';

  if (isCoarse || isProxy || isLimitedQuality) {
    let limitationNote = metricDef.coarseNoteFa ?? 'دارای محدودیت در تفکیک مکانی یا ماهیت نیابتی';
    if (isProxy && !metricDef.coarseNoteFa) {
      limitationNote = 'شاخص غیرمستقیم (نیابتی / Proxy)';
    }

    return {
      state: 'limited',
      displayValue: formattedVal,
      unit,
      reasonFa: limitationNote,
      badgeLabel: '🟡 محدود / Limited',
      badgeClass: 'badge-warning',
      interpretation,
    };
  }

  return {
    state: 'available',
    displayValue: formattedVal,
    unit,
    reasonFa: 'داده مستقیم ماهواره‌ای با کیفیت مناسب',
    badgeLabel: '🟢 در دسترس / Available',
    badgeClass: 'badge-good',
    interpretation,
  };
}
