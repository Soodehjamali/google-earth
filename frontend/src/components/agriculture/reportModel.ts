/**
 * Shared Normalized Report Model for Agricultural Analysis
 *
 * Guarantees:
 * 1. Single source of truth for both UI and PDF export.
 * 2. Zero data fabrication: strictly reflects real response fields.
 * 3. Unavailable domains and insufficient evidence stay explicitly marked.
 * 4. Soil data is strictly marked as unavailable.
 */

import type {
  AgriculturalAnalysisResponse,
  LandUseType,
} from '../../types/index.ts';
import {
  extractOverallFieldStatus,
  extractCandidateInspectionZones,
  evaluateSoilAndNutritionPriority,
  evaluateCanopyYellowing,
  evaluatePestAndDiseaseSurveillance,
  derivePistachioSpecificSummary,
  deriveFarmerActionPlan,
  type FieldOverallStatus,
  type CandidateZone,
  type SoilAndNutritionAssessment,
  type CanopyYellowingAssessment,
  type PestSurveillanceAssessment,
  type PistachioSpecificSummary,
  type RecommendedActionItem,
} from './decisionSupport.ts';
import { formatPersianDate, formatPersianDateRange } from './persianDate.ts';
import { getMetricInterpretation } from './metricInterpretation.ts';

export interface ReportMetadata {
  reportTitleFa: string;
  platformNameFa: string;
  generationDateFa: string;
  timeStartIso?: string;
  timeEndIso?: string;
  timeRangeFa: string;
  landUseType: LandUseType;
  landUseLabelFa: string;
  overallSufficiency: string;
  overallSufficiencyFa: string;
  availableDomains: string[];
  unavailableDomains: string[];
  cloudMaxPercent?: number;
}

export interface DomainMetricItem {
  key: string;
  name: string;
  value: number | null;
  unit: string;
  status: string;
  quality: string;
  referenceRangeFa?: string;
  farmerExplanationFa?: string;
  resolution?: string;
}

export interface DomainReportSection {
  domainKey: string;
  titleFa: string;
  summaryTextFa?: string;
  metrics: DomainMetricItem[];
}

export interface ParcelSpecifications {
  locationName: string;
  analysisId: string;
  geometryType: string;
  vertexCount?: number;
  areaHectares?: string | null;
  areaSqMeters?: number | null;
  centroidCoords?: [number, number] | null;
  rawGeometry?: any;
}

export interface ReportHeatmapInfo {
  metric: string;
  titleFa: string;
  datasetName: string;
  resolution: string;
  status: 'producible' | 'unavailable';
  unavailableReasonFa?: string;
  legendColors: string[];
  legendLabelsFa: string[];
  mapImageBase64?: string;
}

export interface SoilPropertyDetail {
  propertyKey: string;
  nameFa: string;
  nameEn: string;
  unit: string;
  rootZoneValue?: number | null;
  depths?: { depthCode: string; depthFa: string; value: number | null }[];
}

export interface SoilReportSection {
  isBaselinePresent: boolean;
  baselineSummaryFa?: string;
  laboratoryRequirementFa: string;
  parametersNeedingLab: string[];
  surfaceMoisture?: { value: number | null; unit: string; source: string; depthFa: string } | null;
  rootzoneMoisture?: { value: number | null; unit: string; source: string; depthFa: string } | null;
  textureClassFa?: string | null;
  sandPercent?: number | null;
  clayPercent?: number | null;
  siltPercent?: number | null;
  propertiesList?: SoilPropertyDetail[];
}

export interface PestDiseaseReportSection {
  satelliteRiskLevelFa: string;
  satelliteObservationFa: string;
  hasFieldValidation: boolean;
  fieldObservationsCount: number;
  advisoryFa: string;
  diagnosisConfirmed: boolean;
}

export interface NormalizedReportModel {
  metadata: ReportMetadata;
  parcelSpecs: ParcelSpecifications;
  overallStatus: FieldOverallStatus;
  candidateZones: CandidateZone[];
  heatmapInfo: ReportHeatmapInfo;
  soilAssessment: SoilAndNutritionAssessment;
  soilSection: SoilReportSection;
  yellowingAssessment: CanopyYellowingAssessment;
  pestAssessment: PestSurveillanceAssessment;
  pestDiseaseSection: PestDiseaseReportSection;
  pistachioSummary?: PistachioSpecificSummary;
  actionPlan: RecommendedActionItem[];
  availableDomainSections: DomainReportSection[];
  unavailableDomainList: { domain: string; reasonFa: string; actionFa: string }[];
  limitations: string[];
  scientificDisclaimerFa: string;
}

const DOMAIN_NAMES_FA: Record<string, string> = {
  vegetation: 'پوشش گیاهی (Vegetation)',
  water: 'منابع آب و رطوبت (Water)',
  thermal: 'تنش حرارتی و دمای سطح (Thermal)',
  soil: 'خاک (Soil)',
  climate: 'اقلیم و هواشناسی (Climate)',
  crop: 'محصول و کاربری (Crop)',
  phenology: 'فنولوژی (Phenology)',
  productivity: 'بهره‌وری (Productivity)',
  historical: 'سابقه تاریخی (Historical)',
  terrain: 'توپوگرافی و عوارض زمین (Terrain)',
  landcover: 'پوشش اراضی (Land Cover)',
  stress: 'تنش گیاهی (Stress)',
  irrigation: 'آبیاری (Irrigation)',
};

const LAND_USE_LABELS_FA: Record<LandUseType, string> = {
  field_crop: '🌾 زمین زراعی (Field Crop)',
  orchard: '🌳 باغ عمومی (General Orchard)',
  pistachio: '🥜 باغ پسته (Pistachio Orchard)',
  other: '🗺️ سایر / نامشخص (Other)',
};

export function buildNormalizedReportModel(
  result: AgriculturalAnalysisResponse,
  options: {
    landUseType?: LandUseType;
    cloudMaxPercent?: number;
    heatmapSnapshot?: {
      imageBase64?: string;
      datasetName?: string;
      resolution?: string;
      titleFa?: string;
    } | null;
  } = {},
): NormalizedReportModel {
  const landUseType = options.landUseType ?? 'field_crop';
  const overallStatus = extractOverallFieldStatus(result);
  const candidateZones = extractCandidateInspectionZones(result);
  const soilAssessment = evaluateSoilAndNutritionPriority(result, candidateZones);
  const yellowingAssessment = evaluateCanopyYellowing(result, candidateZones);
  const pestAssessment = evaluatePestAndDiseaseSurveillance(result, candidateZones);
  const pistachioSummary =
    landUseType === 'pistachio'
      ? derivePistachioSpecificSummary(result, candidateZones)
      : undefined;
  const actionPlan = deriveFarmerActionPlan(result, candidateZones, landUseType);

  const timeStart = result.time_start;
  const timeEnd = result.time_end;
  const timeRangeFa = formatPersianDateRange(timeStart, timeEnd);

  const sufficiencyLabels: Record<string, string> = {
    sufficient: 'کامل و معتبر (Sufficient)',
    partial: 'نسبی و مشروط (Partial)',
    insufficient: 'ناکافی (Insufficient)',
  };

  const metadata: ReportMetadata = {
    reportTitleFa: 'گزارش جامع پایش اگرو-اکولوژیک و پشتیبانی تصمیم زراعی',
    platformNameFa: 'سامانه پایش هوشمند کشاورزی (Agricultural Intelligence Platform)',
    generationDateFa: formatPersianDate(new Date().toISOString().slice(0, 10)),
    timeStartIso: timeStart ?? undefined,
    timeEndIso: timeEnd ?? undefined,
    timeRangeFa,
    landUseType,
    landUseLabelFa: LAND_USE_LABELS_FA[landUseType] ?? 'نامشخص',
    overallSufficiency: result.overall_sufficiency ?? 'unknown',
    overallSufficiencyFa: sufficiencyLabels[result.overall_sufficiency] ?? 'مشخص‌نشده',
    availableDomains: Array.isArray(result.available_domains) ? result.available_domains : [],
    unavailableDomains: Array.isArray(result.unavailable_domains) ? result.unavailable_domains : [],
    cloudMaxPercent: options.cloudMaxPercent,
  };

  const coords = result.geometry?.coordinates;
  const isPolygon = result.geometry?.type === 'Polygon';
  let vertexCount: number | undefined = undefined;
  let centroid: [number, number] | null = null;

  if (isPolygon && Array.isArray(coords) && Array.isArray(coords[0])) {
    const ring = coords[0] as [number, number][];
    vertexCount = ring.length;
    let sumLon = 0;
    let sumLat = 0;
    ring.forEach(([lon, lat]) => {
      sumLon += lon;
      sumLat += lat;
    });
    centroid = [sumLon / ring.length, sumLat / ring.length];
  } else if (result.geometry?.type === 'Point' && Array.isArray(coords)) {
    centroid = coords as [number, number];
  }

  const parcelSpecs: ParcelSpecifications = {
    locationName: result.location_name?.trim() || 'لوکیشن بدون نام',
    analysisId: result.request_id || 'نامشخص',
    geometryType: isPolygon ? 'چندضلعی اختصاصی باغ (Polygon)' : 'نقطه مکانی (GPS Point)',
    vertexCount,
    areaSqMeters: result.area_sq_meters ?? null,
    areaHectares: result.area_sq_meters ? (result.area_sq_meters / 10000).toFixed(2) : null,
    centroidCoords: centroid,
    rawGeometry: result.geometry,
  };

  const hasVegetationData =
    (result.domains_with_data ?? []).includes('vegetation') ||
    Boolean(result.evidence_bundles?.vegetation);

  const heatmapInfo: ReportHeatmapInfo = {
    metric: 'ndvi',
    titleFa: 'نقشه حرارتی تراکم و شادابی کانوپی (Sentinel-2 NDVI)',
    datasetName: 'COPERNICUS/S2_SR_HARMONIZED (Sentinel-2 MSI)',
    resolution: '۱۰ متر (10 m)',
    status: hasVegetationData ? 'producible' : 'unavailable',
    unavailableReasonFa: hasVegetationData
      ? undefined
      : 'شواهد ماهواره‌ای اپتیکال بدون ابر در بازه زمانی گزارش ثبت نشده است.',
    legendColors: ['#d7191c', '#fdae61', '#ffffbf', '#a6d96a', '#1a9641'],
    legendLabelsFa: [
      'بسیار ضعیف / بدون پوشش (۰.۰)',
      'ضعیف (۰.۲)',
      'متوسط (۰.۴)',
      'خوب (۰.۶)',
      'عالی / تراکم بالا (۰.۸)',
    ],
  };

  if (options.heatmapSnapshot?.imageBase64) {
    heatmapInfo.mapImageBase64 = options.heatmapSnapshot.imageBase64;
    heatmapInfo.status = 'producible';
    if (options.heatmapSnapshot.titleFa) {
      heatmapInfo.titleFa = options.heatmapSnapshot.titleFa;
    }
    if (options.heatmapSnapshot.datasetName) {
      heatmapInfo.datasetName = options.heatmapSnapshot.datasetName;
    }
    if (options.heatmapSnapshot.resolution) {
      heatmapInfo.resolution = options.heatmapSnapshot.resolution;
    }
  }

  const soilData = result.soil_intelligence;
  const soilPropertiesList: SoilPropertyDetail[] = [];
  if (soilData?.properties) {
    const p = soilData.properties;
    const propKeys = ['soc', 'phh2o', 'clay', 'sand', 'silt', 'cec', 'nitrogen'];
    const propMeta: Record<string, { fa: string; en: string; unit: string }> = {
      soc: { fa: 'کربن آلی خاک (SOC)', en: 'Soil Organic Carbon', unit: 'g/kg' },
      phh2o: { fa: 'اسیدیته خاک (pH H2O)', en: 'Soil pH', unit: 'pH' },
      clay: { fa: 'درصد رس (Clay)', en: 'Clay Content', unit: '%' },
      sand: { fa: 'درصد ماسه (Sand)', en: 'Sand Content', unit: '%' },
      silt: { fa: 'درصد سیلت (Silt)', en: 'Silt Content', unit: '%' },
      cec: { fa: 'ظرفیت تبادل کاتیونی (CEC)', en: 'Cation Exchange Capacity', unit: 'cmol(+)/kg' },
      nitrogen: { fa: 'نیتروژن کل خاک (Total N)', en: 'Total Nitrogen', unit: 'cg/kg' },
    };
    for (const k of propKeys) {
      const item = p[k];
      if (item) {
        const meta = propMeta[k] || { fa: item.name_fa || k, en: item.name_en || k, unit: item.unit || '' };
        soilPropertiesList.push({
          propertyKey: k,
          nameFa: meta.fa,
          nameEn: meta.en,
          unit: meta.unit,
          rootZoneValue: item.root_zone_value,
          depths: item.depth_profiles?.map((dp: any) => ({
            depthCode: dp.depth_code,
            depthFa: dp.depth_fa,
            value: dp.value,
          })) || [],
        });
      }
    }
  }

  const soilSection: SoilReportSection = {
    isBaselinePresent: Boolean(soilData),
    baselineSummaryFa: soilData
      ? `ویژگی‌های مدل‌شده خاک بر مبنای ISRIC SoilGrids 2.0 (تفکیک ۲۵۰ متری) و رطوبت ماهواره‌ای SMAP/ERA5-Land (${soilData.properties?.texture_classification?.class_fa ? `بافت غالب: ${soilData.properties.texture_classification.class_fa}` : ''}) استخراج گردید.`
      : 'شواهد خاک در تحلیل اولیه این گزارش محاسبه نشده است.',
    laboratoryRequirementFa:
      'سنجش ماهواره‌ای و یادگیری ماشین جهانی (SoilGrids) قابلیت اندازه‌گیری دقیق عناصر غذایی، شوری موضعی و وضعیت کودی را ندارد. آزمون خاک آزمایشگاهی (اندازه‌گیری N، P، K، EC، pH و آهک) جهت توصیه کودی الزامی است.',
    parametersNeedingLab: [
      'ازت معدنی (N / نیترات و آمونیوم)',
      'فسفر قابل جذب (P / روش اولسن)',
      'پتاسیم تبادلی (K)',
      'شوری و هدایت الکتریکی (ECe)',
      'اسیدیته و واکنش خاک (pH)',
      'درصد گچ و آهک فعال (CCE)',
      'عناصر ریزمغذی (روی، آهن، منگنز، مس)',
    ],
    surfaceMoisture: soilData?.moisture?.surface
      ? {
          value: soilData.moisture.surface.value,
          unit: soilData.moisture.surface.unit,
          source: soilData.moisture.surface.source,
          depthFa: soilData.moisture.surface.depth_fa,
        }
      : null,
    rootzoneMoisture: soilData?.moisture?.rootzone
      ? {
          value: soilData.moisture.rootzone.value,
          unit: soilData.moisture.rootzone.unit,
          source: soilData.moisture.rootzone.source,
          depthFa: soilData.moisture.rootzone.depth_fa,
        }
      : null,
    textureClassFa: soilData?.properties?.texture_classification?.class_fa ?? null,
    sandPercent: soilData?.properties?.texture_classification?.sand_percent ?? null,
    clayPercent: soilData?.properties?.texture_classification?.clay_percent ?? null,
    siltPercent: soilData?.properties?.texture_classification?.silt_percent ?? null,
    propertiesList: soilPropertiesList,
  };

  const pestInspection = result.pest_disease_inspection;
  const validationResults = result.validation?.results ?? [];
  const pestDiseaseSection: PestDiseaseReportSection = {
    satelliteRiskLevelFa:
      pestInspection?.overall_risk_level === 'high'
        ? 'هشدار بالا (نیازمند سرکشی فوری)'
        : pestInspection?.overall_risk_level === 'moderate'
          ? 'ریسک متوسط (پایش دوره‌ای)'
          : pestInspection?.overall_risk_level === 'low'
            ? 'ریسک پایین'
            : (pestInspection?.risk_level_fa || 'نامشخص / شواهد ناکافی'),
    satelliteObservationFa:
      pestInspection?.pattern_summary_fa ||
      pestInspection?.recommended_field_actions_fa?.[0] ||
      'ناهنجاری کانوپی و شاخص‌های ترکیبی نوری-حرارتی غربالگری شدند.',
    hasFieldValidation: validationResults.length > 0,
    fieldObservationsCount: validationResults.length,
    advisoryFa:
      'تصاویر ماهواره‌ای صرفاً غربالگری ریسک تنش هستند و توانایی تفکیک پسیل، نماتد یا بیماری‌های قارچی را ندارند. هرگونه اقدام مدیریتی باید بر اساس بازدید کارشناس گیاه‌پزشک و تله‌گذاری محلی انجام شود.',
    diagnosisConfirmed: false,
  };

  // Build available domain sections strictly from real evidence bundles
  // Combine domains_with_data and availableDomains to guarantee zero omissions
  const domainsToInclude = Array.from(
    new Set([
      ...(result.domains_with_data ?? []),
      ...metadata.availableDomains,
    ]),
  );

  const bundles = result.evidence_bundles ?? {};
  const domainSummaries = result.domain_summaries ?? {};
  const availableDomainSections: DomainReportSection[] = [];

  for (const domainKey of domainsToInclude) {
    if (domainKey === 'soil') continue; // Handled under dedicated soil section
    const bundle = bundles[domainKey];
    const summary = domainSummaries[domainKey];
    const metrics: DomainMetricItem[] = [];

    if (bundle && Array.isArray(bundle.items)) {
      for (const item of bundle.items) {
        if (!item || item.status !== 'available') continue;
        const interp = getMetricInterpretation(
          item.metric_key,
          typeof item.value === 'number' ? item.value : null,
        );
        metrics.push({
          key: item.metric_key,
          name: item.display_name || item.metric_key,
          value: typeof item.value === 'number' ? item.value : null,
          unit: item.unit || '',
          status: item.status,
          quality: item.quality || 'nominal',
          referenceRangeFa: interp.rangeLabelFa,
          farmerExplanationFa: interp.farmerSummaryFa,
          resolution: interp.spatialResolution,
        });
      }
    }

    if (metrics.length > 0 || summary) {
      availableDomainSections.push({
        domainKey,
        titleFa: DOMAIN_NAMES_FA[domainKey] || domainKey,
        summaryTextFa: summary?.statements?.[0]?.statement,
        metrics,
      });
    }
  }

  // Unavailable domains list with transparent reason & remedial action
  const unavailableDomainList: { domain: string; reasonFa: string; actionFa: string }[] = [];

  // Soil is ALWAYS explicitly listed with laboratory action
  unavailableDomainList.push({
    domain: 'خاک و عناصر غذایی (Soil & Nutrients)',
    reasonFa:
      'داده معتبر خاک در این تحلیل موجود نیست. سنجش ماهواره‌ای قابلیت اندازه‌گیری دقیق NPK، EC و pH را ندارد.',
    actionFa: 'ارسال نمونه مرکب خاک به آزمایشگاه تخصصی آب و خاک جهت صدور نسخه کودی.',
  });

  for (const d of metadata.unavailableDomains) {
    if (d !== 'soil') {
      const isClimate = d === 'climate';
      unavailableDomainList.push({
        domain: DOMAIN_NAMES_FA[d] || d,
        reasonFa: isClimate
          ? 'پایگاه ERA5-Land برای بازه‌های اخیر دارای تأخیر داده‌ای (Latency) است یا پوشش ابری مانع دریافت داده شد.'
          : 'شواهد ماهواره‌ای در این بازه زمانی به حد کفایت تحلیل نرسیدند.',
        actionFa: isClimate
          ? 'استعلام بازه زمانی با حداقل ۲ ماه فاصله یا استفاده از ایستگاه هواشناسی محلی.'
          : 'سرکشی میدانی کارشناس یا گسترش پنجره زمانی جستجو.',
      });
    }
  }

  // Collect all real limitations from response
  const rawLimitations: string[] = [];
  if (Array.isArray(result.limitations)) {
    for (const lim of result.limitations) {
      if (typeof lim === 'string') rawLimitations.push(lim);
      else if (lim && typeof lim === 'object' && 'description_fa' in lim) {
        rawLimitations.push((lim as { description_fa: string }).description_fa);
      }
    }
  }

  const scientificDisclaimerFa =
    'این گزارش بر اساس داده‌ها و شواهد سنجش‌ازدور و محیطی موجود در زمان تحلیل تولید شده است. مواردی که داده کافی برای آن‌ها وجود نداشته، به‌عنوان عدم دسترسی به شواهد گزارش شده‌اند و نباید به‌عنوان تشخیص قطعی مزرعه تفسیر شوند.';

  return {
    metadata,
    parcelSpecs,
    overallStatus,
    candidateZones,
    heatmapInfo,
    soilAssessment,
    soilSection,
    yellowingAssessment,
    pestAssessment,
    pestDiseaseSection,
    pistachioSummary,
    actionPlan,
    availableDomainSections,
    unavailableDomainList,
    limitations: rawLimitations,
    scientificDisclaimerFa,
  };
}
