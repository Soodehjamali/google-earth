import type {
  AgriculturalAnalysisResponse,
  CellObservationPayload,
  SpatialCellPayload,
  SpatialSectionPayload,
} from '../../types/index.ts';
import { findEvidenceItem, isFiniteNumber } from './parse.ts';

export type LandUseType = 'field_crop' | 'orchard' | 'pistachio' | 'other';

export interface FieldOverallStatus {
  vegetation: {
    state: 'suitable' | 'attention' | 'weak' | 'insufficient';
    titleFa: string;
    descriptionFa: string;
    metricSummary?: string;
  };
  uniformity: {
    state: 'uniform' | 'heterogeneous' | 'strongly_heterogeneous' | 'insufficient';
    titleFa: string;
    descriptionFa: string;
    metricSummary?: string;
  };
  stress: {
    state: 'no_stress' | 'stress_indicated' | 'candidate_zones_present' | 'insufficient';
    titleFa: string;
    descriptionFa: string;
    metricSummary?: string;
  };
  soil: {
    state: 'chemical_fertility_undetermined';
    titleFa: string;
    descriptionFa: string;
    requiredActionFa: string;
    moistureNoteFa?: string;
  };
}

export interface CandidateZone {
  cellId: string;
  zoneNameFa: string;
  statusFa: string;
  reasonFa: string;
  priority: 'high' | 'medium' | 'low' | 'unknown';
  priorityFa: string;
  centerCoordinates?: [number, number];
  bounds?: { west: number; south: number; east: number; north: number };
  anomalousMetrics: string[];
  // 4 structured dimensions (P-AGRI-DSS-1 §12)
  observationFa: string;
  interpretationFa: string;
  limitationFa: string;
  actionFa: string;
}

export type SoilPriorityStatus = 'candidate' | 'no_candidate' | 'insufficient';

export interface SoilAndNutritionAssessment {
  status: SoilPriorityStatus;
  headlineFa: string;
  statementFa: string;
  disclaimerFa: string;
  recommendedZones: string[];
}

export interface CanopyYellowingAssessment {
  status: 'normal' | 'yellowing_indicated' | 'insufficient';
  headlineFa: string;
  explanationFa: string;
  cautionFa: string;
}

export interface BranchDiebackAssessment {
  statementFa: string;
  recommendationFa: string;
}

export interface PestSurveillanceAssessment {
  alertLevel: 'candidate_inspection' | 'no_alert' | 'insufficient';
  headlineFa: string;
  statementFa: string;
  cautionFa: string;
  targetZones: string[];
}

export interface PistachioYieldModelStatus {
  isActive: boolean;
  statusLabelFa: string;
  reasonFa: string;
  prerequisitesFa: string[];
  improvementPriorityNoteFa: string;
}

export interface PistachioSpecificSummary {
  canopyCoverFa: string;
  heterogeneityFa: string;
  priorityZonesFa: string;
  stressFa: string;
  chlorophyllFa: string;
  diebackFa: string;
  yieldStatus: PistachioYieldModelStatus;
}

export interface RecommendedActionItem {
  priority: number;
  priorityTitleFa: string;
  titleFa: string;
  actionFa: string;
  rationaleFa: string;
  scopeZones?: string[];
  // Evidence Gate Properties (P-AGRI-DSS-2 §C, §D)
  evidenceDomain: string;
  evidenceAvailability: 'available' | 'unavailable';
  evidenceSufficiency: 'sufficient' | 'insufficient';
  supportingMetrics: string[];
  limitations: string[];
  confidence: 'high' | 'medium' | 'low' | 'unavailable';
  isActionable: boolean;
  gateStatus: 'passed' | 'insufficient_evidence' | 'blocked_by_missing_evidence';
  gateExplanationFa: string;
}

/**
 * Determines a human-readable compass sector for a grid cell.
 * Row 0 is northernmost; Col 0 is westernmost.
 */
export function cellCompassSector(
  row: number,
  col: number,
  gridRows = 3,
  gridCols = 3,
): string {
  if (gridRows === 1 && gridCols === 1) {
    return 'کل محدوده';
  }

  // 3x3 Standard Grid Mapping
  if (gridRows === 3 && gridCols === 3) {
    const matrix: Record<string, string> = {
      '0,0': 'شمال‌غرب',
      '0,1': 'شمال',
      '0,2': 'شمال‌شرق',
      '1,0': 'غرب',
      '1,1': 'بخش مرکزی',
      '1,2': 'شرق',
      '2,0': 'جنوب‌غرب',
      '2,1': 'جنوب',
      '2,2': 'جنوب‌شرق',
    };
    const key = `${row},${col}`;
    return matrix[key] ?? `ردیف ${row + 1} ستون ${col + 1}`;
  }

  // Generalized arbitrary grid mapping
  let latPart = 'مرکزی';
  if (row === 0) latPart = 'شمالی';
  else if (row === gridRows - 1) latPart = 'جنوبی';

  let lonPart = '';
  if (col === 0) lonPart = 'غربی';
  else if (col === gridCols - 1) lonPart = 'شرقی';

  if (!lonPart) return `بخش ${latPart}`;
  if (latPart === 'مرکزی') return `بخش ${lonPart}`;
  return `${latPart.replace('ی', '')}‌${lonPart}`;
}

/**
 * Extracts the 4 Overall Field Status cards from real response evidence.
 * Strictly adheres to non-claim scientific safety.
 */
export function extractOverallFieldStatus(
  result: AgriculturalAnalysisResponse | null | undefined,
): FieldOverallStatus {
  if (!result) {
    return {
      vegetation: {
        state: 'insufficient',
        titleFa: 'داده کافی نیست',
        descriptionFa: 'پاسخ تحلیلی معتبری دریافت نشده است.',
      },
      uniformity: {
        state: 'insufficient',
        titleFa: 'داده کافی نیست',
        descriptionFa: 'اطلاعات مکانی در دسترس نیست.',
      },
      stress: {
        state: 'insufficient',
        titleFa: 'داده کافی نیست',
        descriptionFa: 'شاخص‌های رطوبت یا دما ثبت نشده‌اند.',
      },
      soil: {
        state: 'chemical_fertility_undetermined',
        titleFa: 'داده معتبر خاک در این تحلیل موجود نیست',
        descriptionFa: 'این تحلیل فاقد شواهد آزمایشگاهی یا میدانی خاک است و ویژگی‌های شیمیایی، حاصلخیزی یا شوری با داده فعلی قابل تأیید نیست.',
        requiredActionFa: 'برای تعیین N، P، K، pH، EC و شوری، نمونه‌برداری و آزمون آزمایشگاهی خاک الزامی است. این تصمیم بدون داده خاک قابل تأیید نیست.',
      },
    };
  }

  const bundles = result.evidence_bundles ?? {};

  // 1. Vegetation Status
  const ndviItem = findEvidenceItem(bundles, 'ndvi')?.item;
  const hasNdvi = ndviItem && typeof ndviItem.value === 'number' && isFiniteNumber(ndviItem.value);
  const ndviVal = hasNdvi ? (ndviItem.value as number) : null;

  let vegState: FieldOverallStatus['vegetation']['state'] = 'insufficient';
  let vegTitleFa = 'داده کافی نیست';
  let vegDescFa = 'سیگنال پوشش گیاهی در بازه زمانی مورد نظر ثبت نشده است.';
  let vegSummary: string | undefined;

  if (ndviVal !== null) {
    vegSummary = `NDVI: ${ndviVal.toFixed(3)}`;
    if (ndviVal >= 0.35) {
      vegState = 'suitable';
      vegTitleFa = 'مناسب';
      vegDescFa = `سیگنال نوری کانوپی (NDVI: ${ndviVal.toFixed(2)}) نشان‌دهنده بازتاب فتوسنتزی فعال و تراکم مناسب پوشش است.`;
    } else if (ndviVal >= 0.18) {
      vegState = 'attention';
      vegTitleFa = 'نیازمند توجه';
      vegDescFa = `سیگنال پوشش گیاهی در سطح متوسط به پایین (NDVI: ${ndviVal.toFixed(2)}) قرار دارد و تراکم کانوپی محدود یا متفرق است.`;
    } else {
      vegState = 'weak';
      vegTitleFa = 'ضعیف';
      vegDescFa = `سیگنال پوشش گیاهی بسیار پایین (NDVI: ${ndviVal.toFixed(2)}) است و با بستر کم‌پوشش یا تنک مطابقت دارد.`;
    }
  } else if (result.vegetation_regime) {
    if (result.vegetation_regime === 'vegetated') {
      vegState = 'suitable';
      vegTitleFa = 'پوشش فعال';
      vegDescFa = 'بر اساس طبقه‌بندی ساختار پوشش، سیگنال فتوسنتزی در محدوده فعال است.';
    } else if (result.vegetation_regime === 'non_vegetated') {
      vegState = 'weak';
      vegTitleFa = 'ضعیف / بدون پوشش';
      vegDescFa = 'طبقه‌بندی رژیم پوشش، محدوده را فاقد پوشش متراکم ارزیابی کرده است.';
    }
  }

  // 2. Uniformity Status
  let uniState: FieldOverallStatus['uniformity']['state'] = 'insufficient';
  let uniTitleFa = 'داده کافی نیست';
  let uniDescFa = 'تحلیل بدون شبکه سلولی است؛ برای ارزیابی یکنواختی، ثبت محدوده چندضلعی (Polygon) نیاز است.';
  let uniSummary: string | undefined;

  const spatial = result.spatial;
  if (spatial && Array.isArray(spatial.cells) && spatial.cells.length > 0) {
    const totalCells = spatial.cells.length;
    const summaries = spatial.summaries ?? {};
    const ndviSummary = summaries['ndvi'];

    // Check concordance and anomalies
    const concordanceList = Array.isArray(spatial.concordance) ? spatial.concordance : [];
    const anomalousCells = concordanceList.filter(
      (c) => c && c.state !== 'NO_CONCORDANCE' && c.state !== 'INSUFFICIENT',
    ).length;
    const anomFraction =
      typeof ndviSummary?.anomalous_fraction === 'number'
        ? ndviSummary.anomalous_fraction
        : totalCells > 0
          ? anomalousCells / totalCells
          : 0;

    uniSummary = `${totalCells} سلول شبکه مکانی`;

    if (anomFraction >= 0.4 || ndviSummary?.state === 'CONCENTRATED_ANOMALY') {
      uniState = 'strongly_heterogeneous';
      uniTitleFa = 'ناهمگنی قابل توجه';
      uniDescFa = 'اختلاف محسوسی بین بخش‌های مختلف زمین وجود دارد و لکه‌هایی با انحراف منفی یا ناهماهنگ دیده می‌شود.';
    } else if (anomFraction > 0 || anomalousCells > 0) {
      uniState = 'heterogeneous';
      uniTitleFa = 'ناهمگن';
      uniDescFa = 'توزیع سیگنال در سطح زمین کاملاً یکدست نیست و برخی بخش‌ها با میانگین زمین تفاوت دارند.';
    } else {
      uniState = 'uniform';
      uniTitleFa = 'نسبتاً یکنواخت';
      uniDescFa = 'پراکندگی سیگنال در کل قطعه متعادل است و انحراف شدید موضعی مشاهده نمی‌شود.';
    }
  } else if (ndviItem?.stats?.std_dev !== undefined && ndviItem.stats.std_dev !== null) {
    const std = ndviItem.stats.std_dev;
    uniSummary = `انحراف معیار: ${std.toFixed(3)}`;
    if (std > 0.12) {
      uniState = 'strongly_heterogeneous';
      uniTitleFa = 'ناهمگنی قابل توجه';
      uniDescFa = 'انحراف معیار پیکسل‌های داخلی قطعه بالا است و نشان‌دهنده تغییرات محسوس درون‌مزرعه‌ای است.';
    } else if (std > 0.05) {
      uniState = 'heterogeneous';
      uniTitleFa = 'ناهمگن';
      uniDescFa = 'تغییرات جزئی در تراکم پوشش سطح قطعه وجود دارد.';
    } else {
      uniState = 'uniform';
      uniTitleFa = 'نسبتاً یکنواخت';
      uniDescFa = 'پیکسل‌های قطعه دارای تغییرات یکنواخت هستند.';
    }
  }

  // 3. Stress / Dryness Status
  const ndmiItem = findEvidenceItem(bundles, 'ndmi')?.item;
  const msiItem = findEvidenceItem(bundles, 'msi')?.item;
  const lstItem = findEvidenceItem(bundles, 'land_surface_temperature_day')?.item;

  const hasNdmi = ndmiItem && typeof ndmiItem.value === 'number';
  const hasLst = lstItem && typeof lstItem.value === 'number';

  let strState: FieldOverallStatus['stress']['state'] = 'insufficient';
  let strTitleFa = 'داده کافی نیست';
  let strDescFa = 'شاخص‌های رطوبت کانوپی یا بار حرارتی در دسترس نیستند.';
  let strSummary: string | undefined;

  if (hasNdmi || hasLst) {
    const ndmiVal = hasNdmi ? (ndmiItem.value as number) : null;
    const lstVal = hasLst ? (lstItem.value as number) : null;
    const msiVal = msiItem && typeof msiItem.value === 'number' ? msiItem.value : null;

    strSummary = [
      ndmiVal !== null ? `NDMI: ${ndmiVal.toFixed(2)}` : null,
      lstVal !== null ? `LST: ${lstVal.toFixed(1)}°C` : null,
    ]
      .filter(Boolean)
      .join(' · ');

    const isMoistureStressed = (ndmiVal !== null && ndmiVal < -0.1) || (msiVal !== null && msiVal > 1.4);
    const isThermalElevated = lstVal !== null && lstVal > 43.0;

    // Check if spatial cells isolate stress to specific zones
    const spatialHasAnomalous =
      spatial &&
      Array.isArray(spatial.concordance) &&
      spatial.concordance.some(
        (c) =>
          c &&
          Array.isArray(c.anomalous_metrics) &&
          c.anomalous_metrics.some((m) => m === 'ndmi' || m === 'lst_day' || m === 'msi'),
      );

    if (spatialHasAnomalous) {
      strState = 'candidate_zones_present';
      strTitleFa = 'چند ناحیه نیازمند بررسی است';
      strDescFa = 'افت شاخص رطوبت کانوپی یا بار حرارتی در برخی سلول‌های زمین ثبت شده و نیازمند بررسی رطوبت است.';
    } else if (isMoistureStressed || isThermalElevated) {
      strState = 'stress_indicated';
      strTitleFa = 'نشانه‌هایی از تنش وجود دارد';
      strDescFa =
        'شاخص طیفی رطوبت کانوپی پایین یا بار حرارتی سطحی بالا ثبت شده و با شرایط خشکی سازگار است.';
    } else {
      strState = 'no_stress';
      strTitleFa = 'نشانه قابل توجهی دیده نشد';
      strDescFa = 'شاخص رطوبت کانوپی و دمای پوسته سطح در محدوده طبیعی قرار دارند.';
    }
  }

  // 4. Soil Status (Strictly Non-Claim — Soil Evidence Unavailable)
  return {
    vegetation: {
      state: vegState,
      titleFa: vegTitleFa,
      descriptionFa: vegDescFa,
      metricSummary: vegSummary,
    },
    uniformity: {
      state: uniState,
      titleFa: uniTitleFa,
      descriptionFa: uniDescFa,
      metricSummary: uniSummary,
    },
    stress: {
      state: strState,
      titleFa: strTitleFa,
      descriptionFa: strDescFa,
      metricSummary: strSummary,
    },
    soil: {
      state: 'chemical_fertility_undetermined',
      titleFa: 'داده معتبر خاک در این تحلیل موجود نیست',
      descriptionFa: 'سنجش ماهواره‌ای قابلیت اندازه‌گیری عناصر شیمیایی، حاصلخیزی یا شوری خاک را ندارد. این تصمیم بدون داده خاک قابل تأیید نیست.',
      requiredActionFa: 'برای تعیین N، P، K، pH، EC و شوری، نمونه‌برداری و آزمون آزمایشگاهی خاک الزامی است. این تصمیم بدون داده خاک قابل تأیید نیست.',
      moistureNoteFa: undefined,
    },
  };
}

/**
 * Extracts candidate inspection zones from spatial grid data.
 * Does NOT invent mock zones or fixate on arbitrary sectors.
 */
export function extractCandidateInspectionZones(
  result: AgriculturalAnalysisResponse | null | undefined,
): CandidateZone[] {
  if (!result || !result.spatial) return [];
  const spatial: SpatialSectionPayload = result.spatial;
  const cells: SpatialCellPayload[] = Array.isArray(spatial.cells) ? spatial.cells : [];
  if (cells.length === 0) return [];

  const rows = typeof spatial.grid_rows === 'number' && spatial.grid_rows > 0 ? spatial.grid_rows : 3;
  const cols = typeof spatial.grid_cols === 'number' && spatial.grid_cols > 0 ? spatial.grid_cols : 3;

  const obsList: CellObservationPayload[] = Array.isArray(spatial.observations)
    ? spatial.observations
    : [];
  const concordanceList = Array.isArray(spatial.concordance) ? spatial.concordance : [];

  const candidates: CandidateZone[] = [];

  for (const cell of cells) {
    if (!cell || typeof cell.cell_id !== 'string') continue;

    const sectorName = cellCompassSector(cell.row, cell.col, rows, cols);
    const zoneName = `${sectorName} (سلول ${cell.cell_id})`;

    const cellConcordance = concordanceList.find((c) => c && c.cell_id === cell.cell_id);
    const cellObs = obsList.filter((o) => o && o.cell_id === cell.cell_id);

    // Identify which metrics are anomalous
    const anomalousMetrics: string[] = [];
    if (cellConcordance && Array.isArray(cellConcordance.anomalous_metrics)) {
      for (const m of cellConcordance.anomalous_metrics) {
        if (typeof m === 'string') anomalousMetrics.push(m);
      }
    } else {
      for (const o of cellObs) {
        if (
          (typeof o.z_score === 'number' && o.z_score < -1.0) ||
          o.category === 'BELOW_BASELINE'
        ) {
          anomalousMetrics.push(o.metric_key);
        }
      }
    }

    // Determine Priority and Status based on real cell evidence
    let priority: CandidateZone['priority'] = 'low';
    let priorityFa = 'کم';
    let statusFa = 'عادی';
    let reasonFa = 'بدون انحراف منفی قابل توجه نسبت به میانگین زمین';

    const hasMultiAnomaly =
      cellConcordance?.state === 'MULTI_METRIC_ANOMALY' || anomalousMetrics.length >= 2;
    const hasSingleAnomaly =
      cellConcordance?.state === 'SINGLE_METRIC_ANOMALY' || anomalousMetrics.length === 1;

    let observationFa = 'مقادیر شاخص‌های نوری و رطوبتی نزدیک به میانگین کل قطعه ثبت شده است.';
    let interpretationFa = 'وضعیت عمومی پوشش و رطوبت در این بخش پایدار و متناسب با بافت عمومی زمین است.';
    let limitationFa = 'تطابق با میانگین ماهواره‌ای، دلیلی بر حاصلخیزی قطعی یا عدم وجود مشکلات اولیه پنهان نیست.';
    let actionFa = 'ادامه مدیریت معمول و پایش‌های ادواری مزرعه.';

    if (hasMultiAnomaly) {
      priority = 'high';
      priorityFa = 'زیاد';
      statusFa = 'ضعیف‌تر از میانگین';
      const metricNames = anomalousMetrics.length > 0 ? anomalousMetrics.join(' و ') : 'شاخص‌های پوشش و رطوبت';
      reasonFa = `افت همزمان سیگنال در ${metricNames}`;
      observationFa = `افت همزمان سیگنال در شاخص‌های ${metricNames} در این سلول نسبت به میانگین مزرعه ثبت شد.`;
      interpretationFa = 'نشان‌دهنده کاهش توأمان رشد رویشی کانوپی و میزان رطوبت بافت گیاهی در این بخش از زمین است.';
      limitationFa = 'علت دقیق افت (مانند ضعف خاک، گرفتگی قطره‌چکان‌ها، شوری موضعی، بیماری یا آفت) از داده ماهواره‌ای به تنهایی قابل تفکیک نیست.';
      actionFa = 'بازدید میدانی هدفمند، بررسی سلامت تاج و ریشه، و نمونه‌برداری خاک جهت آزمایش NPK و EC.';
    } else if (hasSingleAnomaly) {
      priority = 'medium';
      priorityFa = 'متوسط';
      statusFa = 'نیازمند توجه';
      const metricName = anomalousMetrics.length > 0 ? anomalousMetrics.join('، ') : 'شاخص پوشش';
      reasonFa = `کاهش موضعی در سیگنال ${metricName}`;
      observationFa = `کاهش موضعی در شاخص ${metricName} در این سلول ثبت شده است.`;
      interpretationFa = 'نشان‌دهنده ناهمگنی خفیف یا نوسان موضعی سیگنال نسبت به سایر نقاط قطعه است.';
      limitationFa = 'انحراف تک‌شاخصه ممکن است ناشی از پوشش تنک‌تر یا بستر بین ردیف‌ها باشد و تنش قطعی را اثبات نمی‌کند.';
      actionFa = 'بررسی وضعیت عمومی بوته‌ها/درختان در نوبت بعدی پایش میدانی مزرعه.';
    } else if (cellObs.length === 0) {
      priority = 'unknown';
      priorityFa = 'نامشخص';
      statusFa = 'داده ناکافی';
      reasonFa = 'پوشش ناکافی در این سلول';
      observationFa = 'تعداد پیکسل‌های معتبر در این سلول برای محاسبه مطمئن کافی نبوده است.';
      interpretationFa = 'پوشش ناکافی تصویر ماهواره‌ای (احتمال پوشش ابر یا حاشیه تصویر).';
      limitationFa = 'ارزیابی دقیق این سلول با تصویر این تاریخ امکان‌پذیر نیست.';
      actionFa = 'بررسی در تحلیل‌های تاریخ‌های بعدی یا پایش حضوری در مزرعه.';
    }

    // Center coordinates
    let centerCoords: [number, number] | undefined;
    if (
      isFiniteNumber(cell.west) &&
      isFiniteNumber(cell.east) &&
      isFiniteNumber(cell.south) &&
      isFiniteNumber(cell.north)
    ) {
      centerCoords = [(cell.west + cell.east) / 2, (cell.south + cell.north) / 2];
    }

    candidates.push({
      cellId: cell.cell_id,
      zoneNameFa: zoneName,
      statusFa,
      reasonFa,
      priority,
      priorityFa,
      centerCoordinates: centerCoords,
      bounds: { west: cell.west, south: cell.south, east: cell.east, north: cell.north },
      anomalousMetrics,
      observationFa,
      interpretationFa,
      limitationFa,
      actionFa,
    });
  }

  // Sort: High priority first, then Medium, then Low, then Unknown
  const priorityWeight: Record<CandidateZone['priority'], number> = {
    high: 3,
    medium: 2,
    low: 1,
    unknown: 0,
  };

  return candidates.sort((a, b) => priorityWeight[b.priority] - priorityWeight[a.priority]);
}

/**
 * Evaluates Soil and Nutrition Inspection Priority.
 * Status A (Candidate), Status B (No clear candidate), Status C (Insufficient).
 * STRICTLY blocks fertilizer prescription.
 */
export function evaluateSoilAndNutritionPriority(
  result: AgriculturalAnalysisResponse | null | undefined,
  candidates: CandidateZone[],
): SoilAndNutritionAssessment {
  const disclaimerFa =
    '⚠️ داده معتبر خاک در این تحلیل موجود نیست. این تصمیم بدون داده خاک قابل تأیید نیست. بر اساس قوانین علمی سامانه، تعیین کمبود قطعی نیتروژن، فسفر، پتاسیم، شوری یا نسخه کودی (kg/ha) با داده ماهواره‌ای به هیچ وجه امکان‌پذیر نیست و نیازمند آزمون آزمایشگاهی خاک است.';

  if (!result || !result.spatial || candidates.length === 0) {
    return {
      status: 'insufficient',
      headlineFa: 'داده معتبر خاک در این تحلیل موجود نیست (داده کافی برای اولویت‌بندی مکانی وجود ندارد)',
      statementFa:
        'شواهد آزمایشگاهی یا میدانی خاک در دسترس نیست و به دلیل عدم وجود شبکه مکانی تفکیک‌شده، اولویت‌بندی مکانی نیز قابل تعیین نیست. این تصمیم بدون داده خاک قابل تأیید نیست.',
      disclaimerFa,
      recommendedZones: [],
    };
  }

  const prioritized = candidates.filter((c) => c.priority === 'high' || c.priority === 'medium');

  if (prioritized.length > 0) {
    const zoneLabels = prioritized.map((c) => c.zoneNameFa);
    return {
      status: 'candidate',
      headlineFa: 'داده معتبر خاک در این تحلیل موجود نیست (نواحی کاندید بر مبنای افت پوشش سطحی)',
      statementFa: `شواهد شیمیایی یا فیزیکی خاک در این تحلیل موجود نیست. نواحی ${zoneLabels.join(' و ')} صرفاً به دلیل افت شاخص‌های نوری کانوپی جهت بررسی وضعیت فیزیکی ریشه و نمونه‌برداری خاک پیشنهاد می‌شوند. این تصمیم بدون داده خاک قابل تأیید نیست.`,
      disclaimerFa,
      recommendedZones: zoneLabels,
    };
  }

  return {
    status: 'no_candidate',
    headlineFa: 'داده معتبر خاک در این تحلیل موجود نیست',
    statementFa:
      'شواهد آزمایشگاهی خاک در این تحلیل موجود نیست. داده‌های نوری ماهواره‌ای نیز ناهنجاری موضعی بارزی در سطح زمین نشان نمی‌دهند. این تصمیم بدون داده خاک قابل تأیید نیست.',
    disclaimerFa,
    recommendedZones: [],
  };
}

/**
 * Evaluates canopy yellowing / chlorophyll reduction (NDRE / NDVI).
 * Strictly non-diagnostic: no iron/nitrogen deficiency attribution.
 */
export function evaluateCanopyYellowing(
  result: AgriculturalAnalysisResponse | null | undefined,
  candidates: CandidateZone[],
): CanopyYellowingAssessment {
  const cautionFa =
    'علت کاهش سبزی تاج (کمبود عناصر غذایی مانند آهن یا ازت، شوری آب و خاک، خفگی ریشه یا نماتد) از داده ماهواره‌ای به‌تنهایی قابل تعیین نیست و نیازمند بررسی میدانی است.';

  if (!result) {
    return {
      status: 'insufficient',
      headlineFa: 'داده طیفی کافی نیست',
      explanationFa: 'پاسخ تحلیلی برای بررسی سبزی تاج موجود نیست.',
      cautionFa,
    };
  }

  const bundles = result.evidence_bundles ?? {};
  const ndreItem = findEvidenceItem(bundles, 'ndre')?.item;
  const ndviItem = findEvidenceItem(bundles, 'ndvi')?.item;

  const highCandidates = candidates.filter((c) => c.priority === 'high');

  if (
    highCandidates.length > 0 ||
    (ndreItem && typeof ndreItem.value === 'number' && ndreItem.value < 0.15) ||
    (ndviItem && typeof ndviItem.value === 'number' && ndviItem.value < 0.2 && ndviItem.value >= 0.1)
  ) {
    const zonesStr =
      highCandidates.length > 0
        ? ` در نواحی ${highCandidates.map((c) => c.zoneNameFa).join('، ')}`
        : '';
    return {
      status: 'yellowing_indicated',
      headlineFa: 'نشانه کاهش سبزی/کلروفیل تاج',
      explanationFa: `الگوی طیفی${zonesStr} نسبت به سایر بخش‌ها ضعیف‌تر است. این وضعیت می‌تواند با کاهش سبزی تاج و فعالیت کلروفیل سازگار باشد.`,
      cautionFa,
    };
  }

  return {
    status: 'normal',
    headlineFa: 'کاهش غیرعادی در سبزی تاج مشاهده نشد',
    explanationFa:
      'شاخص‌های طیفی بازتاب پایدار کانوپی را در زمان سنجش نشان می‌دهند و الگوی بارزی از زردی منتشر ثبت نشده است.',
    cautionFa,
  };
}

/**
 * Branch dieback limitation boundary statement.
 */
export function evaluateBranchDiebackScope(
  candidates: CandidateZone[],
): BranchDiebackAssessment {
  const hasWeakerZones = candidates.some((c) => c.priority === 'high' || c.priority === 'medium');

  if (hasWeakerZones) {
    return {
      statementFa:
        'خشکیدگی سرشاخه در مقیاس ماهواره‌ای فعلی (پیکسل‌های ۱۰ تا ۲۰ متری) به‌صورت مستقیم قابل تشخیص نیست.',
      recommendationFa:
        'با توجه به افت سیگنال در برخی نواحی کاندید، برای بررسی احتمال خشکیدگی سرشاخه یا عارضه زوال، بازدید نزدیک از درختان یا تصویربرداری با تفکیک بالاتر (پهپاد) توصیه می‌شود.',
    };
  }

  return {
    statementFa:
      'خشکیدگی سرشاخه در مقیاس ماهواره‌ای فعلی به‌صورت مستقیم قابل تشخیص نیست.',
    recommendationFa:
      'سیگنال کانوپی در سطح قطعه پایدار است، اما این امر عدم وجود عارضه سرخشکیدگی روی تک‌درختان پراکنده را نفی نمی‌کند.',
  };
}

/**
 * Pest & Disease Surveillance Alert.
 * Strictly non-diagnostic; candidate inspection alert only.
 */
export function evaluatePestAndDiseaseSurveillance(
  result: AgriculturalAnalysisResponse | null | undefined,
  candidates: CandidateZone[],
): PestSurveillanceAssessment {
  const cautionFa =
    '⚠️ این هشدار صرفاً یک اولویت‌بندی برای بازدید میدانی است و به هیچ عنوان به معنی تشخیص قطعی آفت، قارچ یا بیماری خاص نیست.';

  if (!result) {
    return {
      alertLevel: 'insufficient',
      headlineFa: 'داده کافی برای پایش آفت وجود ندارد',
      statementFa: 'پاسخ تحلیلی برای پایش سلامت موجود نیست.',
      cautionFa,
      targetZones: [],
    };
  }

  // Look for multi-metric anomaly or severe drop in candidate zones
  const highDropZones = candidates.filter((c) => c.priority === 'high');

  if (highDropZones.length > 0) {
    const zoneNames = highDropZones.map((c) => c.zoneNameFa);
    return {
      alertLevel: 'candidate_inspection',
      headlineFa: 'اولویت بازدید و بررسی آفت / بیماری',
      statementFa: `نواحی ${zoneNames.join(' و ')} دارای الگوی افت غیرعادی و چندشاخصه هستند و برای بررسی حضوری از نظر طغیان آفت یا بیماری در اولویت قرار می‌گیرند.`,
      cautionFa,
      targetZones: zoneNames,
    };
  }

  return {
    alertLevel: 'no_alert',
    headlineFa: 'الگوی ماهواره‌ای فعلی شواهد کافی برای اولویت‌بندی آفت/بیماری نشان نمی‌دهد',
    statementFa:
      'هیچ کانون ناهنجاری شدید، افت ناگهانی چندشاخصه یا الگوی متمرکز دال بر طغیان آفت در تصاویر ماهواره‌ای ثبت نشده است.',
    cautionFa,
    targetZones: [],
  };
}

/**
 * Pistachio Yield Model Status & calibration requirements.
 * Strictly NO fake kg/ha numbers.
 */
export function getPistachioYieldModelStatus(): PistachioYieldModelStatus {
  return {
    isActive: false,
    statusLabelFa: 'در حال حاضر فعال نیست',
    reasonFa:
      'مدل برآورد عملکرد پسته هنوز با داده‌های واقعی برداشت و شرایط اختصاصی باغ کالیبره نشده است.',
    prerequisitesFa: [
      'سابقه ثبت برداشت چندساله در قطعه (تناژ تر و خشک)',
      'رقم دقیق پسته (اکبری، کله‌قوچی، احمدآقایی، اوحدی/فندقی)',
      'سن باغ و سن پیوند درختان',
      'تراکم کاشت و فاصله بین ردیف‌ها و درختان',
      'روش آبیاری، دور آبیاری و شوری آب (EC)',
      'آنالیزهای ادواری خاک و برگ',
      'سابقه سال‌آوری (سال آور On-year / سال ناآور Off-year)',
    ],
    improvementPriorityNoteFa:
      'سامانه در این فاز پاسخ می‌دهد: «کدام نواحی باغ برای بررسی و بهسازی در اولویت هستند؟» نه اینکه «چند کیلوگرم عملکرد افزایش می‌یابد؟». تولید اعداد عملکرد بدون مدل کالیبره‌شده، گمراه‌کننده و غیرعلمی است.',
  };
}

/**
 * Builds Pistachio-specific assessment when landUseType === 'pistachio'.
 */
export function derivePistachioSpecificSummary(
  result: AgriculturalAnalysisResponse | null | undefined,
  candidates: CandidateZone[],
): PistachioSpecificSummary {
  const status = extractOverallFieldStatus(result);
  const dieback = evaluateBranchDiebackScope(candidates);
  const yellowing = evaluateCanopyYellowing(result, candidates);
  const yieldStatus = getPistachioYieldModelStatus();

  const priorityZones = candidates.filter((c) => c.priority === 'high' || c.priority === 'medium');

  return {
    canopyCoverFa: `وضعیت کانوپی باغ: ${status.vegetation.titleFa}. ${status.vegetation.descriptionFa}`,
    heterogeneityFa: `یکنواختی قطعه باغ: ${status.uniformity.titleFa}. ${status.uniformity.descriptionFa}`,
    priorityZonesFa:
      priorityZones.length > 0
        ? `${priorityZones.length} ناحیه (${priorityZones.map((c) => c.zoneNameFa).join('، ')}) برای بررسی در اولویت قرار دارند.`
        : 'الگوی تمرکز ضعف مکانی در باغ مشاهده نشد.',
    stressFa: `تنش رطوبتی/حرارتی: ${status.stress.titleFa}. ${status.stress.descriptionFa}`,
    chlorophyllFa: `${yellowing.headlineFa}: ${yellowing.explanationFa}`,
    diebackFa: `${dieback.statementFa} ${dieback.recommendationFa}`,
    yieldStatus,
  };
}

/**
 * Derives a prioritized Farmer Action Plan derived strictly from real evidence.
 */
export function deriveFarmerActionPlan(
  result: AgriculturalAnalysisResponse | null | undefined,
  candidates: CandidateZone[],
  landUseType: LandUseType,
): RecommendedActionItem[] {
  const plan: RecommendedActionItem[] = [];
  const highCandidates = candidates.filter((c) => c.priority === 'high');
  const mediumCandidates = candidates.filter((c) => c.priority === 'medium');
  const allPrioritized = [...highCandidates, ...mediumCandidates];

  const cropNoun = landUseType === 'pistachio' ? 'درختان پسته' : landUseType === 'orchard' ? 'درختان باغ' : 'محصول و بوته‌ها';
  const bundles = result?.evidence_bundles ?? {};

  // Action 1: Field inspection of identified zones (Domain: spatial / vegetation)
  if (allPrioritized.length > 0) {
    const targetZones = allPrioritized.map((c) => c.zoneNameFa);
    plan.push({
      priority: 1,
      priorityTitleFa: 'اولویت ۱',
      titleFa: `بازدید میدانی از نواحی دارای سیگنال ضعیف‌تر (${targetZones.slice(0, 3).join('، ')})`,
      actionFa: `مراجعه به بخش‌های ${targetZones.join(' و ')} و بررسی وضعیت فیزیکی و ظاهری ${cropNoun}.`,
      rationaleFa: 'این نواحی دارای افت شاخص‌های نوری یا رطوبتی نسبت به میانگین قطعه هستند.',
      scopeZones: targetZones,
      evidenceDomain: 'spatial',
      evidenceAvailability: 'available',
      evidenceSufficiency: 'sufficient',
      supportingMetrics: ['ndvi', 'spatial_concordance'],
      limitations: ['تفکیک مکانی ۱۰ متری، ضرورت تأیید عارضه با مشاهده حضوری'],
      confidence: 'high',
      isActionable: true,
      gateStatus: 'passed',
      gateExplanationFa: 'شواهد چندشاخصه مکانی افت معنادار را در این نواحی تأیید می‌کند.',
    });
  } else {
    plan.push({
      priority: 1,
      priorityTitleFa: 'اولویت ۱',
      titleFa: 'پایش عمومی و منظم قطعه',
      actionFa: 'ادامه بازدید‌های دوره‌ای معمول بدون نیاز به تفکیک موضعی اضطراری.',
      rationaleFa: 'سیگنال‌های ماهواره‌ای توزیع متعادلی را در سطح زمین نشان می‌دهند.',
      evidenceDomain: 'spatial',
      evidenceAvailability: 'available',
      evidenceSufficiency: 'sufficient',
      supportingMetrics: ['ndvi'],
      limitations: ['احتمال وجود مشکلات اولیه در سطح محدود تک‌بوته'],
      confidence: 'medium',
      isActionable: true,
      gateStatus: 'passed',
      gateExplanationFa: 'الگوی یکنواخت در سطح قطعه تأیید شده است.',
    });
  }

  // Action 2: Soil & Nutrition (Domain: soil — STRICTLY BLOCKED / NON-CLAIM)
  plan.push({
    priority: 2,
    priorityTitleFa: 'اولویت ۲',
    titleFa: 'آزمون آزمایشگاهی خاک (داده معتبر خاک در این تحلیل موجود نیست)',
    actionFa:
      'ارسال نمونه خاک لایه‌های ۰-۳۰ و ۳۰-۶۰ سانتی‌متر به آزمایشگاه معتبر آب و خاک جهت صدور نسخه تغذیه. هرگونه توصیه کودی تا پیش از دریافت برگه آزمایشگاه مسدود است.',
    rationaleFa:
      'داده معتبر خاک در این تحلیل موجود نیست. این تصمیم بدون داده خاک قابل تأیید نیست.',
    evidenceDomain: 'soil',
    evidenceAvailability: 'unavailable',
    evidenceSufficiency: 'insufficient',
    supportingMetrics: [],
    limitations: ['فقدان داده آزمایشگاهی N, P, K, EC, pH در سنجش ماهواره‌ای'],
    confidence: 'unavailable',
    isActionable: false,
    gateStatus: 'blocked_by_missing_evidence',
    gateExplanationFa:
      'داده معتبر خاک در این تحلیل موجود نیست. این تصمیم بدون داده خاک قابل تأیید نیست.',
  });

  // Action 3: Canopy and irrigation inspection (Domain: water)
  const ndmiItem = findEvidenceItem(bundles, 'ndmi')?.item;
  const msiItem = findEvidenceItem(bundles, 'msi')?.item;
  const hasWaterEvidence =
    (ndmiItem && typeof ndmiItem.value === 'number' && isFiniteNumber(ndmiItem.value)) ||
    (msiItem && typeof msiItem.value === 'number' && isFiniteNumber(msiItem.value));

  if (hasWaterEvidence) {
    const waterMetrics = [ndmiItem ? 'ndmi' : '', msiItem ? 'msi' : ''].filter(Boolean);
    plan.push({
      priority: 3,
      priorityTitleFa: 'اولویت ۳',
      titleFa: 'بررسی وضعیت کانوپی و سیستم آبیاری',
      actionFa:
        'بررسی قطره‌چکان‌ها، فشار شبکه آبیاری، وضعیت رطوبت پای درخت/بوته و بررسی علائم زردی در برگ‌ها.',
      rationaleFa:
        'نوسان در شاخص‌های طیفی معمولاً با گرفتگی نازل‌ها، ناهمگنی نفوذ آب یا نوسان آبیاری مرتبط است.',
      evidenceDomain: 'water',
      evidenceAvailability: 'available',
      evidenceSufficiency: 'sufficient',
      supportingMetrics: waterMetrics,
      limitations: ['عدم تفکیک مستقیم دور آبیاری از بارندگی در داده‌های ماهواره‌ای'],
      confidence: 'medium',
      isActionable: true,
      gateStatus: 'passed',
      gateExplanationFa: 'شواهد طیفی رطوبت کانوپی (NDMI/MSI) جهت بررسی آبیاری موجود است.',
    });
  } else {
    plan.push({
      priority: 3,
      priorityTitleFa: 'اولویت ۳',
      titleFa: 'پایش رطوبت و آبیاری (نیازمند داده بیشتر)',
      actionFa: 'برای توصیه آبیاری، شواهد کافی از وضعیت آب/تنش گیاه در این تحلیل موجود نیست.',
      rationaleFa: 'داده‌های نوری/راداری رطوبت کانوپی در این تحلیل به حد کفایت نرسیده‌اند.',
      evidenceDomain: 'water',
      evidenceAvailability: 'unavailable',
      evidenceSufficiency: 'insufficient',
      supportingMetrics: [],
      limitations: ['شواهد کافی از وضعیت آب/تنش گیاه در این تحلیل موجود نیست.'],
      confidence: 'unavailable',
      isActionable: false,
      gateStatus: 'insufficient_evidence',
      gateExplanationFa: 'برای توصیه آبیاری، شواهد کافی از وضعیت آب/تنش گیاه در این تحلیل موجود نیست.',
    });
  }

  // Action 4: Pest surveillance if high drop exists
  if (highCandidates.length > 0) {
    plan.push({
      priority: 4,
      priorityTitleFa: 'اولویت ۴',
      titleFa: 'بررسی علائم اولیه آفت یا بیماری‌های طوقه و ریشه',
      actionFa:
        'بررسی طوقه و تنه درختان، وجود ترشحات صمغ، لکه‌برگی یا آثار تغذیه حشرات در کانون‌های افت سیگنال.',
      rationaleFa:
        'وجود افت همزمان چندشاخصه می‌تواند با آسیب‌های بیولوژیک موضعی سازگار باشد.',
      scopeZones: highCandidates.map((c) => c.zoneNameFa),
      evidenceDomain: 'vegetation',
      evidenceAvailability: 'available',
      evidenceSufficiency: 'sufficient',
      supportingMetrics: ['ndvi', 'spatial_concordance'],
      limitations: ['ماهواره تنها افت زیست‌توده را نشان می‌دهد و نوع آفت یا بیماری را تشخیص نمی‌دهد'],
      confidence: 'medium',
      isActionable: true,
      gateStatus: 'passed',
      gateExplanationFa: 'افت شدید زیست‌توده در کانون‌های مشخص، بازدید چشمی برای رد آفت را توجیه می‌کند.',
    });
  }

  return plan;
}
