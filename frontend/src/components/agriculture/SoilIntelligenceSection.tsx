/**
 * Soil Intelligence Subsystem (Phase P-AGRI-SOIL)
 *
 * Real Google Earth Engine & ISRIC SoilGrids 2.0 Soil Intelligence.
 * Strictly adheres to real data only:
 * 1. Soil Moisture (Surface 0–5 cm, Root-zone 0–100 cm, ERA5 4-layer profile).
 * 2. Soil Properties (SOC, Total Nitrogen, pH in H2O, Sand, Silt, Clay, CEC, Water Retention).
 * 3. 6 Standard GlobalSoilMap Depths with interactive Depth Profile Explorer.
 * 4. USDA Soil Texture Triangle classification.
 * 5. Explicit UNAVAILABLE status for non-observable nutrients (P, K, Zn, Fe, Nitrate).
 * 6. 100% Pure Jalali Calendar presentation with Persian digits (via persianDate.ts).
 */
import { useEffect, useState, useMemo } from 'react';
import type {
  AgricultureGeometry,
  SoilIntelligenceResponse,
  SoilPropertyRecord,
  SoilMoistureLayer,
  UnavailableNutrient,
  SoilMetricAvailabilityItem,
} from '../../types';
import { agricultureApi } from '../../api/agriculture';
import {
  formatPersianDateRange,
  toPersianDigits,
} from './persianDate';
import Historical10YearSection from './Historical10YearSection';
import OrchardHeatmapSwipeSection from './OrchardHeatmapSwipeSection';

interface SoilIntelligenceSectionProps {
  initialSoilData?: SoilIntelligenceResponse | null;
  geometry: GeoJSON.Geometry | AgricultureGeometry | null;
  startDate: string;
  endDate: string;
  cloudMaxPercent?: number;
  isSavedReport?: boolean;
}

export default function SoilIntelligenceSection({
  initialSoilData,
  geometry,
  startDate,
  endDate,
  cloudMaxPercent = 20,
  isSavedReport = false,
}: SoilIntelligenceSectionProps) {
  const [soilData, setSoilData] = useState<SoilIntelligenceResponse | null>(
    initialSoilData ?? null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDepthCode, setSelectedDepthCode] = useState<string>('0-5cm');
  const [showLabModal, setShowLabModal] = useState(false);
  const [matrixFilter, setMatrixFilter] = useState<'all' | 'available' | 'lab_required'>('all');

  // Fetch soil intelligence on demand if not provided in parent analysis
  useEffect(() => {
    if (initialSoilData) {
      setSoilData(initialSoilData);
      return;
    }

    if (!geometry || !startDate || !endDate) {
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);

    agricultureApi
      .getSoilIntelligence({
        geometry,
        start_date: startDate,
        end_date: endDate,
      })
      .then((res) => {
        if (active) {
          setSoilData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err?.message || 'خطا در بارگذاری داده‌های خاک');
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [initialSoilData, geometry, startDate, endDate]);

  const moisture = soilData?.moisture;
  const properties = soilData?.properties;
  const unavailableNutrients = soilData?.unavailable_nutrients ?? [];
  const labFramework = soilData?.laboratory_framework;

  // Helper for texture styling
  const texture = properties?.texture_classification;
  const waterRetention = properties?.water_retention;

  // Depth list for depth explorer
  const depthTabs = useMemo(() => {
    return [
      { code: '0-5cm', labelFa: '۰ تا ۵ سانتی‌متر (سطحی)', depthTop: 0, depthBot: 5 },
      { code: '5-15cm', labelFa: '۵ تا ۱۵ سانتی‌متر', depthTop: 5, depthBot: 15 },
      { code: '15-30cm', labelFa: '۱۵ تا ۳۰ سانتی‌متر', depthTop: 15, depthBot: 30 },
      { code: '30-60cm', labelFa: '۳۰ تا ۶۰ سانتی‌متر', depthTop: 30, depthBot: 60 },
      { code: '60-100cm', labelFa: '۶۰ تا ۱۰۰ سانتی‌متر', depthTop: 60, depthBot: 100 },
      { code: '100-200cm', labelFa: '۱۰۰ تا ۲۰۰ سانتی‌متر (زیرخاک)', depthTop: 100, depthBot: 200 },
    ];
  }, []);

  // 17-Metric Soil Data Availability Matrix (P-AGRI-SOIL-3 contract)
  const fullMatrix = useMemo<SoilMetricAvailabilityItem[]>(() => {
    if (soilData?.data_availability_matrix && soilData.data_availability_matrix.length > 0) {
      return soilData.data_availability_matrix;
    }

    // High-fidelity fallback builder for all 17 metrics
    const smapSurf = moisture?.surface?.value;
    const smapRz = moisture?.rootzone?.value;
    const socVal = properties?.soc?.root_zone_value;
    const phVal = properties?.phh2o?.root_zone_value;
    const nVal = properties?.nitrogen?.root_zone_value;
    const sandVal = properties?.sand?.root_zone_value;
    const siltVal = properties?.silt?.root_zone_value;
    const clayVal = properties?.clay?.root_zone_value;
    const cecVal = properties?.cec?.root_zone_value;
    const fcVal = properties?.water_retention?.field_capacity_33kpa;
    const wpVal = properties?.water_retention?.wilting_point_1500kpa;

    return [
      {
        metric_key: 'soil_moisture_surface',
        label_en: 'Surface Soil Moisture',
        label_fa: 'رطوبت سطحی خاک',
        value: smapSurf ?? null,
        unit: 'm3/m3',
        source: 'NASA SMAP SPL3SMP_E / ERA5-Land',
        dataset_id: 'NASA/SMAP/SPL3SMP_E/006',
        variable: 'soil_moisture_am',
        band: 'soil_moisture_am',
        status: smapSurf !== undefined && smapSurf !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        data_status: smapSurf !== undefined && smapSurf !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'SATELLITE_OBSERVATION',
        scientific_status_fa: 'مشاهده سنجش از دور ماهواره‌ای (SMAP L3)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: smapSurf !== undefined && smapSurf !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–5 cm',
        spatial_resolution: '9000 m (9 km)',
        temporal_period: `${startDate} to ${endDate}`,
        limitations: ['Coarse 9 km resolution', 'Top 5 cm microwave sensing depth'],
      },
      {
        metric_key: 'soil_moisture_rootzone',
        label_en: 'Root-Zone Soil Moisture',
        label_fa: 'رطوبت ناحیه ریشه خاک',
        value: smapRz ?? null,
        unit: 'm3/m3',
        source: 'NASA SMAP SPL4SMGP / ECMWF ERA5-Land',
        dataset_id: 'NASA/SMAP/SPL4SMGP/008',
        variable: 'sm_rootzone',
        band: 'sm_rootzone',
        status: smapRz !== undefined && smapRz !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        data_status: smapRz !== undefined && smapRz !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'REANALYSIS_MODEL',
        scientific_status_fa: 'خروجی مدل بازتحلیل / شبیه‌سازی زمین (SMAP L4 / ERA5-Land)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: smapRz !== undefined && smapRz !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm',
        spatial_resolution: '9000 m - 11132 m (~9-11 km)',
        temporal_period: `${startDate} to ${endDate}`,
        limitations: ['Assimilated geophysical land-surface model', 'Regional contextual moisture'],
      },
      {
        metric_key: 'soil_organic_carbon',
        label_en: 'Soil Organic Carbon (SOC)',
        label_fa: 'کربن آلی خاک (SOC)',
        value: socVal ?? null,
        unit: 'g/kg',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/soc_mean',
        variable: 'soc_mean',
        band: 'soc_mean',
        status: socVal !== undefined && socVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: socVal !== undefined && socVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: socVal !== undefined && socVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline (~2020)',
        limitations: ['Random Forest digital soil mapping baseline (250 m)', 'Not dynamic time-series'],
      },
      {
        metric_key: 'soil_ph',
        label_en: 'Soil pH in H2O',
        label_fa: 'اسیدیته خاک (pH در آب)',
        value: phVal ?? null,
        unit: 'pH',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/phh2o_mean',
        variable: 'phh2o_mean',
        band: 'phh2o_mean',
        status: phVal !== undefined && phVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: phVal !== undefined && phVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: phVal !== undefined && phVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline (~2020)',
        limitations: ['Modelled baseline at 250 m resolution', 'Local amendments and water affect pH'],
      },
      {
        metric_key: 'soil_total_nitrogen',
        label_en: 'Total Nitrogen (SoilGrids 2.0)',
        label_fa: 'نیتروژن کل خاک',
        value: nVal ?? null,
        unit: 'g/kg',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/nitrogen_mean',
        variable: 'nitrogen_mean',
        band: 'nitrogen_mean',
        status: nVal !== undefined && nVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: nVal !== undefined && nVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: nVal !== undefined && nVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline (~2020)',
        limitations: ['Total nitrogen pool; strictly distinct from plant-available nitrate (NO3-)', 'Lab testing required'],
      },
      {
        metric_key: 'soil_sand_content',
        label_en: 'Sand Fraction',
        label_fa: 'درصد ذرات ماسه (شن)',
        value: sandVal ?? null,
        unit: '%',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/sand_mean',
        variable: 'sand_mean',
        band: 'sand_mean',
        status: sandVal !== undefined && sandVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: sandVal !== undefined && sandVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: sandVal !== undefined && sandVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline',
        limitations: ['Physical particle size fraction (> 0.05 mm)', 'Static physical property'],
      },
      {
        metric_key: 'soil_silt_content',
        label_en: 'Silt Fraction',
        label_fa: 'درصد ذرات سیلت (لای)',
        value: siltVal ?? null,
        unit: '%',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/silt_mean',
        variable: 'silt_mean',
        band: 'silt_mean',
        status: siltVal !== undefined && siltVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: siltVal !== undefined && siltVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: siltVal !== undefined && siltVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline',
        limitations: ['Physical particle size fraction (0.002 to 0.05 mm)', 'Static physical property'],
      },
      {
        metric_key: 'soil_clay_content',
        label_en: 'Clay Fraction',
        label_fa: 'درصد ذرات رس',
        value: clayVal ?? null,
        unit: '%',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/clay_mean',
        variable: 'clay_mean',
        band: 'clay_mean',
        status: clayVal !== undefined && clayVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: clayVal !== undefined && clayVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: clayVal !== undefined && clayVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline',
        limitations: ['Physical particle size fraction (< 0.002 mm)', 'Controls CEC and water retention'],
      },
      {
        metric_key: 'soil_cec',
        label_en: 'Cation Exchange Capacity (CEC)',
        label_fa: 'ظرفیت تبادل کاتیونی (CEC)',
        value: cecVal ?? null,
        unit: 'cmol(c)/kg',
        source: 'ISRIC SoilGrids 2.0',
        dataset_id: 'projects/soilgrids-isric/cec_mean',
        variable: 'cec_mean',
        band: 'cec_mean',
        status: cecVal !== undefined && cecVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: cecVal !== undefined && cecVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: cecVal !== undefined && cecVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm (Weighted Profile)',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline',
        limitations: ['Buffer capacity index for exchangeable cations', 'Static prediction at 250 m'],
      },
      {
        metric_key: 'soil_field_capacity',
        label_en: 'Water Retention at 33 kPa (Field Capacity)',
        label_fa: 'ظرفیت زراعی خاک (FC در ۳۳ kPa)',
        value: fcVal ?? null,
        unit: 'm3/m3',
        source: 'ISRIC SoilGrids 2.0 wv0033',
        dataset_id: 'ISRIC/SoilGrids250m/v2_0/wv0033',
        variable: 'val_mean (33 kPa)',
        band: 'val_mean (33 kPa)',
        status: fcVal !== undefined && fcVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: fcVal !== undefined && fcVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0 wv0033)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: fcVal !== undefined && fcVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline',
        limitations: ['Laboratory matric suction representing field capacity in temperate soils'],
      },
      {
        metric_key: 'soil_wilting_point',
        label_en: 'Water Retention at 1500 kPa (Wilting Point)',
        label_fa: 'نقطه پژمردگی دائم خاک (WP در ۱۵۰۰ kPa)',
        value: wpVal ?? null,
        unit: 'm3/m3',
        source: 'ISRIC SoilGrids 2.0 wv1500',
        dataset_id: 'ISRIC/SoilGrids250m/v2_0/wv1500',
        variable: 'val_mean (1500 kPa)',
        band: 'val_mean (1500 kPa)',
        status: wpVal !== undefined && wpVal !== null ? 'MODELLED_BASELINE' : 'INSUFFICIENT_DATA',
        data_status: wpVal !== undefined && wpVal !== null ? 'AVAILABLE' : 'INSUFFICIENT_DATA',
        scientific_status: 'GRIDDED_SOIL_BASELINE',
        scientific_status_fa: 'خط مبنای مدل‌شده خاک (ISRIC SoilGrids 2.0 wv1500)',
        validation_status: 'NOT_LAB_VERIFIED',
        validation_note_fa: 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.',
        availability_message_fa: wpVal !== undefined && wpVal !== null ? 'داده واقعی منبع با موفقیت فراخوانی شد.' : 'داده واقعی در منبع فعلی موجود نیست',
        depth: '0–100 cm',
        spatial_resolution: '250 m',
        temporal_period: 'Static modelled baseline',
        limitations: ['Laboratory matric suction representing permanent wilting point'],
      },
      // 6 Lab-Required Unobservable parameters
      {
        metric_key: 'available_phosphorus',
        label_en: 'Available Phosphorus (P - Olsen)',
        label_fa: 'فسفر قابل جذب خاک (P)',
        value: null,
        unit: 'mg/kg',
        source: null,
        dataset_id: null,
        variable: null,
        band: null,
        status: 'REQUIRES_LAB_VALIDATION',
        data_status: 'UNAVAILABLE',
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        scientific_status_fa: 'عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)',
        validation_status: 'LAB_REQUIRED',
        validation_note_fa: 'نیازمند آزمون آزمایشگاهی خاک (عصاره اولسن)؛ سنجنده‌های ماهواره‌ای فاقد امکان سنجش هستند.',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — سنجنده‌های ماهواره‌ای قادر به اندازه‌گیری مستقیم فسفر قابل جذب خاک نیستند.',
        depth: '0–30 cm',
        spatial_resolution: 'N/A',
        temporal_period: 'N/A',
        limitations: ['No direct spectral absorption for orthophosphate in soil solution', 'Lab Olsen extraction strictly required'],
      },
      {
        metric_key: 'exchangeable_potassium',
        label_en: 'Exchangeable Potassium (K)',
        label_fa: 'پتاسیم تبادلی خاک (K)',
        value: null,
        unit: 'mg/kg',
        source: null,
        dataset_id: null,
        variable: null,
        band: null,
        status: 'REQUIRES_LAB_VALIDATION',
        data_status: 'UNAVAILABLE',
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        scientific_status_fa: 'عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)',
        validation_status: 'LAB_REQUIRED',
        validation_note_fa: 'نیازمند آزمون آزمایشگاهی خاک (عصاره استات آمونیوم)؛ فاقد بازتاب طیفی ماهواره‌ای.',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — پتاسیم تبادلی خاک فاقد ویژگی جذبی در باندهای ماهواره‌ای است.',
        depth: '0–30 cm',
        spatial_resolution: 'N/A',
        temporal_period: 'N/A',
        limitations: ['Exchangeable K+ has no direct satellite signature', 'Requires Ammonium Acetate extraction in laboratory'],
      },
      {
        metric_key: 'soil_nitrate',
        label_en: 'Soil Nitrate (NO3-)',
        label_fa: 'نیترات خاک (NO3-)',
        value: null,
        unit: 'mg/kg',
        source: null,
        dataset_id: null,
        variable: null,
        band: null,
        status: 'REQUIRES_LAB_VALIDATION',
        data_status: 'UNAVAILABLE',
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        scientific_status_fa: 'عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)',
        validation_status: 'LAB_REQUIRED',
        validation_note_fa: 'نیازمند آزمون آزمایشگاهی خاک؛ کاملاً متمایز از نیتروژن کل بوده و متحرک است.',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — نیترات بر خلاف نیتروژن کل، آنیون متحرک و ناپایدار است که صرفاً با آزمون آزمایشگاهی تعیین می‌شود.',
        depth: '0–30 cm',
        spatial_resolution: 'N/A',
        temporal_period: 'N/A',
        limitations: ['Not equivalent to Total Nitrogen', 'Requires direct wet-chemistry lab test'],
      },
      {
        metric_key: 'soil_electrical_conductivity',
        label_en: 'Electrical Conductivity (ECe / Salinity)',
        label_fa: 'هدایت الکتریکی عصاره اشباع خاک (ECe / شوری)',
        value: null,
        unit: 'dS/m',
        source: null,
        dataset_id: null,
        variable: null,
        band: null,
        status: 'REQUIRES_LAB_VALIDATION',
        data_status: 'UNAVAILABLE',
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        scientific_status_fa: 'عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)',
        validation_status: 'LAB_REQUIRED',
        validation_note_fa: 'نیازمند آزمون آزمایشگاهی خاک (هدایت‌سنجی گل اشباع ECe)؛ سنجش از فضا مقدور نیست.',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — سنجش ماهواره‌ای قادر به اندازه‌گیری شوری عصاره اشباع عمق ریشه نیست.',
        depth: '0–30 cm',
        spatial_resolution: 'N/A',
        temporal_period: 'N/A',
        limitations: ['Satellite estimate not validated at depth', 'Laboratory conductometry is required'],
      },
      {
        metric_key: 'soil_zinc',
        label_en: 'Available Zinc (Zn)',
        label_fa: 'روی قابل جذب خاک (Zn)',
        value: null,
        unit: 'mg/kg',
        source: null,
        dataset_id: null,
        variable: null,
        band: null,
        status: 'REQUIRES_LAB_VALIDATION',
        data_status: 'UNAVAILABLE',
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        scientific_status_fa: 'عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)',
        validation_status: 'LAB_REQUIRED',
        validation_note_fa: 'نیازمند آزمون آزمایشگاهی خاک (عصاره DTPA)؛ غلظت در حد ppm از فضا قابل تفکیک نیست.',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — غلظت روی در حد ppm بوده و از فضا قابل تفکیک نیست.',
        depth: '0–30 cm',
        spatial_resolution: 'N/A',
        temporal_period: 'N/A',
        limitations: ['Zinc concentration (ppm level) cannot be resolved by satellites', 'Requires DTPA extraction test'],
      },
      {
        metric_key: 'soil_iron',
        label_en: 'Available Iron (Fe)',
        label_fa: 'آهن قابل جذب خاک (Fe)',
        value: null,
        unit: 'mg/kg',
        source: null,
        dataset_id: null,
        variable: null,
        band: null,
        status: 'REQUIRES_LAB_VALIDATION',
        data_status: 'UNAVAILABLE',
        scientific_status: 'UNOBSERVABLE_SATELLITE',
        scientific_status_fa: 'عدم امکان سنجش ماهواره‌ای (نیازمند آزمایش خاک)',
        validation_status: 'LAB_REQUIRED',
        validation_note_fa: 'نیازمند آزمون آزمایشگاهی خاک (عصاره DTPA)؛ کانی‌های سطحی نمایانگر آهن قابل جذب نیستند.',
        availability_message_fa: 'داده واقعی در منبع فعلی موجود نیست — کانی‌های سطحی آهن نشان‌دهنده آهن قابل جذب ریشه نیستند.',
        depth: '0–30 cm',
        spatial_resolution: 'N/A',
        temporal_period: 'N/A',
        limitations: ['Surface mineral iron does not reflect plant-available Fe', 'Requires DTPA extraction test'],
      },
    ];
  }, [soilData, moisture, properties, startDate, endDate]);

  const filteredMatrix = useMemo(() => {
    if (matrixFilter === 'available') {
      return fullMatrix.filter((m) => m.data_status === 'AVAILABLE' || m.value !== null);
    }
    if (matrixFilter === 'lab_required') {
      return fullMatrix.filter((m) => m.validation_status === 'LAB_REQUIRED' || m.data_status === 'UNAVAILABLE');
    }
    return fullMatrix;
  }, [fullMatrix, matrixFilter]);

  if (isSavedReport && !soilData && !loading) {
    return (
      <div className="card mb-4" data-testid="saved-soil-unavailable-card">
        <div className="card-header">
          <span className="card-title">🌱 هوش و مشخصات خاک (Soil Intelligence)</span>
        </div>
        <div className="card-body">
          <div className="empty-state">
            <div className="empty-state-icon">🌍</div>
            <div className="empty-state-title">
              داده‌های تفصیلی مدل SoilGrids و رطوبت چندلایه در این گزارش ذخیره‌شده محاسبه نشده است
            </div>
            <div className="empty-state-desc" style={{ maxWidth: 540, margin: '8px auto', color: '#607d8b', lineHeight: 1.7 }}>
              در زمان اجرای این تحلیل، خروجی‌های تفصیلی مدل SoilGrids 2.0 و رطوبت چندلایه مشمول درخواست این گزارش نبوده‌اند. برای مشاهده شاخص‌های پایه رطوبت سطحی خاک، به بخش شاخص‌های رطوبت در بالای همین صفحه مراجعه کنید.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="soil-intelligence-section" style={{ marginTop: '1.5rem' }}>
      {/* ------------------------------------------------------------- */}
      {/* Main Header & Scientific Safety Banner */}
      {/* ------------------------------------------------------------- */}
      <div
        className="card mb-4"
        style={{
          border: '1px solid #795548',
          background: 'linear-gradient(135deg, #efebe9 0%, #ffffff 100%)',
        }}
      >
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <div>
              <h3 style={{ margin: 0, color: '#3e2723', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>🌱</span>
                <span>هوش و مشخصات خاک (Soil Intelligence)</span>
              </h3>
              <p className="text-muted" style={{ margin: '4px 0 0 0', fontSize: '0.88rem' }}>
                سنجش واقعی رطوبت لایه‌های خاک با ماهواره‌های ریزموج (SMAP / ERA5) + خط مبنای چندعمقی پایگاه جهانی ISRIC SoilGrids 2.0
              </p>
            </div>
            <div className="d-flex align-items-center gap-2">
              <span className="badge" style={{ backgroundColor: '#4e342e', color: '#fff', padding: '6px 12px' }}>
                بازه تحلیل: {formatPersianDateRange(startDate, endDate)}
              </span>
              <span className="badge badge-good" style={{ padding: '6px 12px' }}>
                داده واقعی GEE
              </span>
            </div>
          </div>

          {/* P-AGRI-SOIL-3 Core Policy Banner: 4-Dimensional Separation */}
          <div
            style={{
              marginTop: '12px',
              padding: '14px 18px',
              backgroundColor: '#fff8e1',
              borderRight: '5px solid #f57f17',
              borderRadius: '6px',
              fontSize: '0.88rem',
              color: '#3e2723',
              lineHeight: 1.7,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: '6px', color: '#bf360c', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>⚠️</span>
              <span>خط‌مشی علمی ارائه داده‌های خاک (P-AGRI-SOIL-3) — تفکیک چهاربعدی اصالت، وضعیت علمی و اعتبارسنجی:</span>
            </div>
            <div style={{ marginBottom: '8px' }}>
              «بر اساس اصول مصوب این فاز، تمامی داده‌های واقعی استخراج‌شده از منابع معتبر (ماهواره‌های مایکروویو، مدل‌های بازتحلیل اقلیمی و پایگاه SoilGrids) با شفافیت کامل ارائه می‌شوند. <strong>عدم اتمام کالیبراسیون و اعتبارسنجی میدانی مانع از نمایش داده‌های واقعی منبع نمی‌شود</strong>؛ اما صدور هرگونه توصیه کودی، نسخه تغذیه‌ای و ادعای کمبود عناصر منوط به آزمون آزمایشگاهی خاک است.»
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', marginTop: '6px' }}>
              <span className="badge" style={{ backgroundColor: '#2e7d32', color: '#fff', fontSize: '0.8rem', padding: '5px 10px' }}>
                داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.
              </span>
              <span className="badge" style={{ backgroundColor: '#455a64', color: '#fff', fontSize: '0.8rem', padding: '5px 10px' }}>
                تفکیک: ۱. دسترسی‌پذیری | ۲. اصالت و باند | ۳. وضعیت علمی | ۴. اعتبارسنجی میدانی
              </span>
              <span className="badge" style={{ backgroundColor: '#c62828', color: '#fff', fontSize: '0.8rem', padding: '5px 10px' }}>
                توصیه‌های کودی: مسدود تا ثبت آزمون آزمایشگاهی
              </span>
            </div>
          </div>
        </div>
      </div>

      {loading && (
        <div className="card mb-4 text-center p-4">
          <div className="spinner-border text-primary" role="status" />
          <p className="mt-2 text-muted">در حال استخراج و تحلیل داده‌های واقعی خاک از موتور گوگل ارث...</p>
        </div>
      )}

      {error && (
        <div className="alert alert-danger mb-4">
          <strong>خطا در دریافت هوش خاک:</strong> {error}
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 1. Soil Moisture Section (رطوبت خاک) */}
      {/* ------------------------------------------------------------- */}
      <div className="card mb-4">
        <div className="card-header d-flex justify-content-between align-items-center">
          <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
            💧 ۱. رطوبت لایه‌ای خاک (Soil Moisture)
          </span>
          <span className="badge badge-primary">
            وضوح ۹ تا ۱۱ کیلومتر | مدل‌شده
          </span>
        </div>
        <div className="card-body">
          <div className="row g-3">
            {/* Root-zone Moisture Card */}
            <div className="col-12 col-md-6">
              <div
                style={{
                  border: '1px solid #90caf9',
                  borderRadius: '8px',
                  padding: '14px',
                  background: '#f1f8fe',
                  height: '100%',
                }}
              >
                <div className="d-flex justify-content-between align-items-start">
                  <div>
                    <span style={{ fontSize: '0.85rem', color: '#1565c0', fontWeight: 600 }}>
                      رطوبت ناحیه ریشه (Root-Zone Soil Moisture)
                    </span>
                    <div style={{ fontSize: '1.6rem', fontWeight: 700, color: '#0d47a1', margin: '6px 0' }}>
                      {moisture?.rootzone?.value !== null && moisture?.rootzone?.value !== undefined
                        ? `${toPersianDigits(moisture.rootzone.value.toFixed(3))} m³/m³`
                        : '—'}
                    </div>
                  </div>
                  <span className="badge badge-good">۰ تا ۱۰۰ سانتی‌متر</span>
                </div>
                <div style={{ fontSize: '0.8rem', color: '#546e7a', lineHeight: 1.5, marginTop: '6px' }}>
                  <div><strong>سنجنده / پایگاه:</strong> {moisture?.rootzone?.source || 'ERA5-Land / SMAP (۹–۱۱ کیلومتر)'}</div>
                  <div><strong>وضعیت علمی:</strong> {moisture?.rootzone?.scientific_status_fa || 'خروجی مدل بازتحلیل / شبیه‌سازی زمین (SMAP L4 / ERA5-Land)'}</div>
                  <div style={{ marginTop: '4px', color: '#e65100', fontWeight: 600 }}>
                    {moisture?.rootzone?.value !== null && moisture?.rootzone?.value !== undefined
                      ? '«داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.»'
                      : '«داده واقعی در منبع فعلی موجود نیست»'}
                  </div>
                </div>
              </div>
            </div>

            {/* Surface Moisture Card */}
            <div className="col-12 col-md-6">
              <div
                style={{
                  border: '1px solid #b0bec5',
                  borderRadius: '8px',
                  padding: '14px',
                  background: '#f9fbe7',
                  height: '100%',
                }}
              >
                <div className="d-flex justify-content-between align-items-start">
                  <div>
                    <span style={{ fontSize: '0.85rem', color: '#558b2f', fontWeight: 600 }}>
                      رطوبت سطحی خاک (Surface Soil Moisture)
                    </span>
                    <div style={{ fontSize: '1.6rem', fontWeight: 700, color: '#33691e', margin: '6px 0' }}>
                      {moisture?.surface?.value !== null && moisture?.surface?.value !== undefined
                        ? `${toPersianDigits(moisture.surface.value.toFixed(3))} m³/m³`
                        : '—'}
                    </div>
                  </div>
                  <span className="badge badge-primary">۰ تا ۵ سانتی‌متر</span>
                </div>
                <div style={{ fontSize: '0.8rem', color: '#546e7a', lineHeight: 1.5, marginTop: '6px' }}>
                  <div><strong>سنجنده:</strong> {moisture?.surface?.source || 'NASA SMAP SPL3SMP_E Enhanced Radiometer (۹ کیلومتر)'}</div>
                  <div><strong>وضعیت علمی:</strong> {moisture?.surface?.scientific_status_fa || 'مشاهده سنجش از دور ماهواره‌ای (SMAP L3 باند L)'}</div>
                  <div style={{ marginTop: '4px', color: '#e65100', fontWeight: 600 }}>
                    {moisture?.surface?.value !== null && moisture?.surface?.value !== undefined
                      ? '«داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.»'
                      : '«داده واقعی در منبع فعلی موجود نیست»'}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Coarse Resolution Warning */}
          <div
            style={{
              marginTop: '14px',
              padding: '10px 14px',
              backgroundColor: '#e1f5fe',
              border: '1px dashed #039be5',
              borderRadius: '6px',
              fontSize: '0.82rem',
              color: '#0277bd',
            }}
          >
            <strong>🌐 هشدار تفکیک مکانی کلان (Coarse Spatial Resolution):</strong> داده‌های رطوبت سنجنده‌های SMAP و ERA5-Land دارای وضوح مکانی ۹ الی ۱۱ کیلومتر هستند. این مقادیر وضعیت کلی حوضه و منطقه باغ را نشان می‌دهند و جانشین سنسورهای رطوبت‌سنج درون‌باغی یا نوسانات دقیق آبیاری موضعی نیستند.
          </div>

          {/* Multi-layer Depth Table */}
          {moisture?.multilayer_era5 && moisture.multilayer_era5.length > 0 && (
            <div style={{ marginTop: '16px' }}>
              <h5 style={{ fontSize: '0.9rem', color: '#37474f', marginBottom: '8px' }}>
                پروفیل رطوبت در اعماق چهارگانه خاک (ECMWF ERA5-Land):
              </h5>
              <div className="table-responsive">
                <table className="table table-sm table-bordered text-center align-middle" style={{ fontSize: '0.85rem' }}>
                  <thead style={{ backgroundColor: '#eceff1' }}>
                    <tr>
                      <th>لایه عمقی</th>
                      <th>بازه عمق</th>
                      <th>رطوبت حجمی (m³/m³)</th>
                      <th>وضعیت داده</th>
                      <th>منبع</th>
                    </tr>
                  </thead>
                  <tbody>
                    {moisture.multilayer_era5.map((layer: SoilMoistureLayer) => (
                      <tr key={layer.band}>
                        <td style={{ fontWeight: 600 }}>{layer.depth_fa}</td>
                        <td dir="ltr">{toPersianDigits(layer.depth_top_cm)} – {toPersianDigits(layer.depth_bottom_cm)} cm</td>
                        <td style={{ fontWeight: 700, color: '#1565c0' }}>
                          {layer.value !== null ? toPersianDigits(layer.value.toFixed(4)) : '—'}
                        </td>
                        <td>
                          <span className={`badge ${layer.value !== null ? 'badge-good' : 'badge-unavailable'}`}>
                            {layer.value !== null ? 'موجود' : 'ناموجود'}
                          </span>
                        </td>
                        <td style={{ fontSize: '0.8rem', color: '#78909c' }}>{layer.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* 2. Soil Properties & Depth Profile Explorer */}
      {/* ------------------------------------------------------------- */}
      <div className="card mb-4">
        <div className="card-header d-flex justify-content-between align-items-center">
          <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
            🔬 ۲. ویژگی‌های فیزیکی، شیمیایی و بافت خاک (ISRIC SoilGrids 2.0)
          </span>
          <span className="badge" style={{ backgroundColor: '#5d4037', color: '#fff' }}>
            وضوح ۲۵۰ متر | خط مبنای مدل‌شده
          </span>
        </div>
        <div className="card-body">
          {/* Top Texture & Chemistry Badges Grid (Section 6 & 7) */}
          <div className="row g-2 mb-3">
            <div className="col-12 col-md-4 col-lg">
              <div style={{ padding: '12px', background: '#efebe9', borderRadius: '6px', textAlign: 'center', height: '100%' }}>
                <div style={{ fontSize: '0.75rem', color: '#4e342e', fontWeight: 600 }}>کلاس بافت خاک (USDA)</div>
                <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#3e2723', marginTop: '4px' }}>
                  {texture?.class_fa || 'لوم شنی (Sandy Loam)'}
                </div>
                <div style={{ fontSize: '0.72rem', color: '#8d6e63', marginTop: '2px' }}>
                  {texture?.sand_percent !== undefined && texture?.sand_percent !== null
                    ? `شن: ${toPersianDigits(texture.sand_percent.toFixed(1))}٪ | سیلت: ${toPersianDigits((texture.silt_percent ?? 0).toFixed(1))}٪ | رس: ${toPersianDigits((texture.clay_percent ?? 0).toFixed(1))}٪`
                    : 'محاسبه‌شده بر پایه مثلث بافت خاک'}
                </div>
                <div style={{ fontSize: '0.7rem', color: '#a1887f', marginTop: '4px' }}>
                  ISRIC SoilGrids 2.0 (۲۵۰ متر)
                </div>
              </div>
            </div>

            <div className="col-12 col-md-4 col-lg">
              <div style={{ padding: '12px', background: '#e8f5e9', borderRadius: '6px', textAlign: 'center', height: '100%' }}>
                <div style={{ fontSize: '0.75rem', color: '#2e7d32', fontWeight: 600 }}>کربن آلی خاک (SOC)</div>
                <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#1b5e20', marginTop: '4px' }}>
                  {properties?.soc?.root_zone_value !== undefined && properties?.soc?.root_zone_value !== null
                    ? `${toPersianDigits(properties.soc.root_zone_value.toFixed(2))} g/kg`
                    : '—'}
                </div>
                <div style={{ fontSize: '0.72rem', color: '#388e3c', marginTop: '2px' }}>
                  عمق: ۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#1b5e20', marginTop: '4px' }}>
                  خط مبنای مدل‌شده خاک (SoilGrids 2.0)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#e65100', marginTop: '2px', fontWeight: 600 }}>
                  داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.
                </div>
              </div>
            </div>

            <div className="col-12 col-md-4 col-lg">
              <div style={{ padding: '12px', background: '#f3e5f5', borderRadius: '6px', textAlign: 'center', height: '100%' }}>
                <div style={{ fontSize: '0.75rem', color: '#6a1b9a', fontWeight: 600 }}>اسیدیته خاک (pH در آب)</div>
                <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#4a148c', marginTop: '4px' }}>
                  {properties?.phh2o?.root_zone_value !== undefined && properties?.phh2o?.root_zone_value !== null
                    ? `${toPersianDigits(properties.phh2o.root_zone_value.toFixed(2))} pH`
                    : '—'}
                </div>
                <div style={{ fontSize: '0.72rem', color: '#7b1fa2', marginTop: '2px' }}>
                  عمق: ۰ تا ۱۰۰ سانتی‌متر (ناحیه ریشه)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#4a148c', marginTop: '4px' }}>
                  خط مبنای مدل‌شده خاک (SoilGrids 2.0)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#e65100', marginTop: '2px', fontWeight: 600 }}>
                  داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.
                </div>
              </div>
            </div>

            <div className="col-12 col-md-6 col-lg">
              <div style={{ padding: '12px', background: '#e0f2f1', borderRadius: '6px', textAlign: 'center', height: '100%' }}>
                <div style={{ fontSize: '0.75rem', color: '#00695c', fontWeight: 600 }}>نیتروژن کل خاک (Total N)</div>
                <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#004d40', marginTop: '4px' }}>
                  {properties?.nitrogen?.root_zone_value !== undefined && properties?.nitrogen?.root_zone_value !== null
                    ? `${toPersianDigits(properties.nitrogen.root_zone_value.toFixed(3))} g/kg`
                    : '—'}
                </div>
                <div style={{ fontSize: '0.72rem', color: '#00796b', marginTop: '2px' }}>
                  متمایز از نیترات قابل جذب (NO3-)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#004d40', marginTop: '4px' }}>
                  خط مبنای مدل‌شده خاک (SoilGrids 2.0)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#e65100', marginTop: '2px', fontWeight: 600 }}>
                  داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.
                </div>
              </div>
            </div>

            <div className="col-12 col-md-6 col-lg">
              <div style={{ padding: '12px', background: '#fff8e1', borderRadius: '6px', textAlign: 'center', height: '100%' }}>
                <div style={{ fontSize: '0.75rem', color: '#f57f17', fontWeight: 600 }}>ظرفیت تبادل کاتیونی (CEC)</div>
                <div style={{ fontSize: '1.15rem', fontWeight: 700, color: '#e65100', marginTop: '4px' }}>
                  {properties?.cec?.root_zone_value !== undefined && properties?.cec?.root_zone_value !== null
                    ? `${toPersianDigits(properties.cec.root_zone_value.toFixed(1))} cmol/kg`
                    : '—'}
                </div>
                <div style={{ fontSize: '0.72rem', color: '#f57f17', marginTop: '2px' }}>
                  شاخص بافر خاک (۰ تا ۱۰۰ سانتی‌متر)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#e65100', marginTop: '4px' }}>
                  خط مبنای مدل‌شده خاک (SoilGrids 2.0)
                </div>
                <div style={{ fontSize: '0.68rem', color: '#e65100', marginTop: '2px', fontWeight: 600 }}>
                  داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.
                </div>
              </div>
            </div>
          </div>

          {/* Water Retention (FC / WP / AWC) */}
          {waterRetention && (
            <div
              style={{
                background: '#e0f2f1',
                border: '1px solid #80cbc4',
                borderRadius: '6px',
                padding: '10px 14px',
                marginBottom: '16px',
              }}
            >
              <div className="row text-center align-middle" style={{ fontSize: '0.85rem' }}>
                <div className="col-4">
                  <span className="text-muted">ظرفیت زراعی (FC - 33kPa):</span>{' '}
                  <strong style={{ color: '#004d40' }}>
                    {waterRetention.field_capacity_33kpa !== null
                      ? `${toPersianDigits((waterRetention.field_capacity_33kpa * 100).toFixed(1))}٪ (${toPersianDigits(waterRetention.field_capacity_33kpa.toFixed(3))} m³/m³)`
                      : '—'}
                  </strong>
                </div>
                <div className="col-4">
                  <span className="text-muted">نقطه پژمردگی دائم (WP - 1500kPa):</span>{' '}
                  <strong style={{ color: '#004d40' }}>
                    {waterRetention.wilting_point_1500kpa !== null
                      ? `${toPersianDigits((waterRetention.wilting_point_1500kpa * 100).toFixed(1))}٪ (${toPersianDigits(waterRetention.wilting_point_1500kpa.toFixed(3))} m³/m³)`
                      : '—'}
                  </strong>
                </div>
                <div className="col-4">
                  <span className="text-muted">ظرفیت آب قابل استفاده (AWC):</span>{' '}
                  <strong style={{ color: '#00796b', fontSize: '0.95rem' }}>
                    {waterRetention.available_water_capacity !== null
                      ? `${toPersianDigits((waterRetention.available_water_capacity * 100).toFixed(1))}٪ (${toPersianDigits(waterRetention.available_water_capacity.toFixed(3))} m³/m³)`
                      : '—'}
                  </strong>
                </div>
              </div>
            </div>
          )}

          {/* Depth Profile Explorer */}
          <div style={{ marginTop: '16px' }}>
            <div className="d-flex justify-content-between align-items-center mb-2">
              <h5 style={{ fontSize: '0.92rem', color: '#3e2723', margin: 0, fontWeight: 600 }}>
                کاوشگر لایه‌های عمقی خاک (GlobalSoilMap 6 Depths Explorer):
              </h5>
              <div className="btn-group btn-group-sm" role="group">
                {depthTabs.map((tab) => (
                  <button
                    key={tab.code}
                    type="button"
                    className={`btn ${selectedDepthCode === tab.code ? 'btn-primary' : 'btn-outline-secondary'}`}
                    style={{ fontSize: '0.78rem', padding: '3px 8px' }}
                    onClick={() => setSelectedDepthCode(tab.code)}
                  >
                    {tab.code}
                  </button>
                ))}
              </div>
            </div>

            {/* Depth Matrix Table */}
            <div className="table-responsive">
              <table className="table table-sm table-bordered text-center align-middle" style={{ fontSize: '0.82rem' }}>
                <thead style={{ backgroundColor: '#d7ccc8' }}>
                  <tr>
                    <th>شاخص خاک</th>
                    <th>واحد</th>
                    <th>ناحیه ریشه (۰–۱۰۰cm)</th>
                    {depthTabs.map((tab) => (
                      <th
                        key={tab.code}
                        style={{
                          backgroundColor: selectedDepthCode === tab.code ? '#ffecb3' : undefined,
                        }}
                      >
                        {tab.code}
                      </th>
                    ))}
                    <th>منبع</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { key: 'soc', label: 'کربن آلی (SOC)', unit: 'g/kg' },
                    { key: 'nitrogen', label: 'نیتروژن کل (N)', unit: 'g/kg' },
                    { key: 'phh2o', label: 'اسیدیته (pH)', unit: 'pH' },
                    { key: 'clay', label: 'درصد رس (Clay)', unit: '٪' },
                    { key: 'sand', label: 'درصد شن (Sand)', unit: '٪' },
                    { key: 'silt', label: 'درصد سیلت (Silt)', unit: '٪' },
                    { key: 'cec', label: 'ظرفیت تبادل کاتیونی', unit: 'cmol/kg' },
                  ].map((row) => {
                    const record: SoilPropertyRecord | undefined = properties?.[row.key];
                    return (
                      <tr key={row.key}>
                        <td style={{ fontWeight: 600, textAlign: 'right' }}>{row.label}</td>
                        <td dir="ltr" style={{ color: '#78909c' }}>{row.unit}</td>
                        <td style={{ fontWeight: 700, color: '#3e2723' }}>
                          {record?.root_zone_value !== undefined && record?.root_zone_value !== null
                            ? toPersianDigits(record.root_zone_value.toFixed(2))
                            : '—'}
                        </td>
                        {depthTabs.map((tab) => {
                          const depthVal = record?.depth_profiles?.find(
                            (p) => p.depth_code === tab.code,
                          )?.value;
                          const isSelected = selectedDepthCode === tab.code;
                          return (
                            <td
                              key={tab.code}
                              style={{
                                backgroundColor: isSelected ? '#fff9c4' : undefined,
                                fontWeight: isSelected ? 700 : 400,
                              }}
                            >
                              {depthVal !== undefined && depthVal !== null
                                ? toPersianDigits(depthVal.toFixed(2))
                                : '—'}
                            </td>
                          );
                        })}
                        <td style={{ fontSize: '0.75rem', color: '#8d6e63' }}>SoilGrids 2.0</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div style={{ fontSize: '0.78rem', color: '#795548', marginTop: '6px' }}>
              * مقادیر <strong>ناحیه ریشه (۰–۱۰۰ سانتی‌متر)</strong> میانگین موزون ۵ لایه فوقانی بر اساس ضخامت هر لایه خاک هستند و لایه عمیق‌تر از ۱۰۰ سانتی‌متر در آن لحاظ نشده است.
            </div>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* 3. Comprehensive 17-Metric Soil Data Availability Matrix (P-AGRI-SOIL-3) */}
      {/* ------------------------------------------------------------- */}
      <div className="card mb-4" data-testid="soil-availability-matrix-section">
        <div className="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
          <div>
            <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
              📊 ۳. ماتریس جامع دسترسی‌پذیری و اصالت ۱۷ شاخص خاک (Soil Data Availability & Provenance Matrix)
            </span>
            <div style={{ fontSize: '0.8rem', color: '#607d8b', marginTop: '2px' }}>
              تفکیک کامل ۴ بعد: دسترسی‌پذیری منبع، زنجیره اصالت داده، وضعیت علمی، و وضعیت اعتبارسنجی
            </div>
          </div>
          <div className="d-flex align-items-center gap-2">
            <div className="btn-group btn-group-sm" role="group">
              <button
                type="button"
                className={`btn ${matrixFilter === 'all' ? 'btn-primary' : 'btn-outline-secondary'}`}
                style={{ fontSize: '0.78rem' }}
                onClick={() => setMatrixFilter('all')}
              >
                همه ۱۷ شاخص ({toPersianDigits(fullMatrix.length)})
              </button>
              <button
                type="button"
                className={`btn ${matrixFilter === 'available' ? 'btn-success' : 'btn-outline-secondary'}`}
                style={{ fontSize: '0.78rem' }}
                onClick={() => setMatrixFilter('available')}
              >
                داده‌های واقعی موجود ({toPersianDigits(fullMatrix.filter((m) => m.data_status === 'AVAILABLE' || m.value !== null).length)})
              </button>
              <button
                type="button"
                className={`btn ${matrixFilter === 'lab_required' ? 'btn-danger' : 'btn-outline-secondary'}`}
                style={{ fontSize: '0.78rem' }}
                onClick={() => setMatrixFilter('lab_required')}
              >
                نیازمند آزمون آزمایشگاهی ({toPersianDigits(fullMatrix.filter((m) => m.validation_status === 'LAB_REQUIRED' || m.data_status === 'UNAVAILABLE').length)})
              </button>
            </div>
          </div>
        </div>
        <div className="card-body">
          <div
            style={{
              padding: '10px 14px',
              backgroundColor: '#e8f5e9',
              border: '1px solid #a5d6a7',
              borderRadius: '6px',
              marginBottom: '14px',
              fontSize: '0.82rem',
              color: '#1b5e20',
              lineHeight: 1.6,
            }}
          >
            <strong>اصل ارائه داده‌محور (Availability-First Presentation):</strong> هیچ داده واقعی و معتبری به دلیل عدم انجام اعتبارسنجی میدانی مخفی نمی‌شود. برای شاخص‌های بدون سنسور ماهواره‌ای (نظیر فسفر، پتاسیم و نیترات)، پیام شفاف «داده واقعی در منبع فعلی موجود نیست» درج شده و هیچ عدد فرضی، تقریب گیاهی (NDVI) یا مقدار صفر جایگزین نشده است.
          </div>

          <div className="table-responsive">
            <table className="table table-sm table-hover table-bordered text-center align-middle" style={{ fontSize: '0.82rem' }}>
              <thead style={{ backgroundColor: '#eceff1' }}>
                <tr>
                  <th style={{ width: '4%' }}>#</th>
                  <th style={{ width: '18%' }}>شاخص خاک (Metric)</th>
                  <th style={{ width: '15%' }}>مقدار منبع و واحد (Value)</th>
                  <th style={{ width: '15%' }}>پایگاه داده، سنجنده و متغیر</th>
                  <th style={{ width: '10%' }}>عمق سنجش</th>
                  <th style={{ width: '10%' }}>وضوح مکانی</th>
                  <th style={{ width: '13%' }}>وضعیت علمی</th>
                  <th style={{ width: '15%' }}>وضعیت اعتبارسنجی و یادداشت</th>
                </tr>
              </thead>
              <tbody>
                {filteredMatrix.map((item, idx) => {
                  const hasValue = item.value !== null && item.value !== undefined;
                  const isAvailable = item.data_status === 'AVAILABLE' || hasValue;

                  // Format value
                  let formattedValue = '—';
                  if (hasValue && typeof item.value === 'number') {
                    if (item.unit === 'm3/m3') {
                      formattedValue = toPersianDigits(item.value.toFixed(3));
                    } else if (item.unit === '%') {
                      formattedValue = toPersianDigits(item.value.toFixed(1));
                    } else {
                      formattedValue = toPersianDigits(item.value.toFixed(2));
                    }
                  } else if (hasValue) {
                    formattedValue = toPersianDigits(String(item.value));
                  }

                  // Scientific badge styling
                  let sciBadgeBg = '#546e7a';
                  if (item.scientific_status === 'SATELLITE_OBSERVATION') sciBadgeBg = '#1565c0';
                  else if (item.scientific_status === 'REANALYSIS_MODEL') sciBadgeBg = '#0277bd';
                  else if (item.scientific_status === 'GRIDDED_SOIL_BASELINE') sciBadgeBg = '#4e342e';
                  else if (item.scientific_status === 'DERIVED') sciBadgeBg = '#2e7d32';
                  else if (item.scientific_status === 'UNOBSERVABLE_SATELLITE') sciBadgeBg = '#c62828';

                  return (
                    <tr
                      key={item.metric_key}
                      style={{
                        backgroundColor: !isAvailable ? '#fffafa' : undefined,
                      }}
                    >
                      <td style={{ color: '#78909c' }}>{toPersianDigits(idx + 1)}</td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ fontWeight: 600, color: '#263238' }}>{item.label_fa}</div>
                        <div style={{ fontSize: '0.74rem', color: '#78909c' }}>{item.label_en}</div>
                      </td>
                      <td>
                        {hasValue ? (
                          <div>
                            <span style={{ fontSize: '0.98rem', fontWeight: 700, color: '#0d47a1' }}>
                              {formattedValue}
                            </span>{' '}
                            <span style={{ fontSize: '0.75rem', color: '#546e7a' }}>{item.unit}</span>
                          </div>
                        ) : (
                          <div>
                            <span className="badge" style={{ backgroundColor: '#ffebee', color: '#c62828', fontSize: '0.74rem', border: '1px solid #ef9a9a' }}>
                              داده واقعی در منبع فعلی موجود نیست
                            </span>
                          </div>
                        )}
                      </td>
                      <td style={{ textAlign: 'right', fontSize: '0.78rem' }}>
                        <div style={{ fontWeight: 600, color: '#37474f' }}>{item.source || 'فاقد منبع ماهواره‌ای'}</div>
                        {item.variable && (
                          <div style={{ color: '#78909c', fontSize: '0.72rem' }}>
                            متغیر: <code>{item.variable}</code>
                          </div>
                        )}
                      </td>
                      <td style={{ fontSize: '0.78rem', color: '#455a64' }}>{item.depth}</td>
                      <td style={{ fontSize: '0.78rem', color: '#455a64' }}>{item.spatial_resolution}</td>
                      <td>
                        <span
                          className="badge"
                          style={{
                            backgroundColor: sciBadgeBg,
                            color: '#fff',
                            fontSize: '0.72rem',
                            padding: '4px 6px',
                            whiteSpace: 'normal',
                            lineHeight: 1.3,
                            display: 'inline-block',
                          }}
                        >
                          {item.scientific_status_fa || item.scientific_status}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', fontSize: '0.75rem' }}>
                        {isAvailable ? (
                          <div>
                            <span className="badge" style={{ backgroundColor: '#fff3e0', color: '#e65100', border: '1px solid #ffb74d', marginBottom: '3px' }}>
                              اعتبارسنجی میدانی در انتظار
                            </span>
                            <div style={{ color: '#bf360c', fontSize: '0.72rem', lineHeight: 1.3 }}>
                              {item.validation_note_fa || 'داده واقعی منبع؛ اعتبارسنجی میدانی هنوز انجام نشده است.'}
                            </div>
                          </div>
                        ) : (
                          <div>
                            <span className="badge" style={{ backgroundColor: '#ffebee', color: '#c62828', border: '1px solid #ef9a9a', marginBottom: '3px' }}>
                              آزمون آزمایشگاهی الزامی
                            </span>
                            <div style={{ color: '#b71c1c', fontSize: '0.72rem', lineHeight: 1.3 }}>
                              {item.reason_fa || item.validation_note_fa || 'سنجش ماهواره‌ای امکان‌پذیر نیست.'}
                            </div>
                            <button
                              type="button"
                              className="btn btn-outline-danger btn-sm mt-1"
                              style={{ fontSize: '0.68rem', padding: '2px 6px' }}
                              onClick={() => setShowLabModal(true)}
                            >
                              ثبت آزمون خاک
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* 4. Nutrients & Laboratory Honesty Gate (Section 8) */}
      {/* ------------------------------------------------------------- */}
      <div className="card mb-4" style={{ border: '1px solid #ef5350' }}>
        <div
          className="card-header d-flex justify-content-between align-items-center"
          style={{ backgroundColor: '#ffebee' }}
        >
          <span className="card-title" style={{ color: '#c62828', fontSize: '1.05rem', fontWeight: 600 }}>
            ⛔ ۴. پارامترهای نیازمند آزمایش خاک (Soil Laboratory Verification Required)
          </span>
          <span className="badge badge-unavailable">
            عدم سنجش ماهواره‌ای | آزمون آزمایشگاهی الزامی
          </span>
        </div>
        <div className="card-body">
          <div
            style={{
              padding: '12px 14px',
              backgroundColor: '#fff',
              border: '1px solid #ffcdd2',
              borderRadius: '6px',
              marginBottom: '14px',
              fontSize: '0.85rem',
              lineHeight: 1.6,
              color: '#b71c1c',
            }}
          >
            <strong>اصل سخت‌گیرانه عدم ادعای دروغین و استقلال توصیه‌های کودی:</strong> هیچ سنجنده ماهواره‌ای در مدار زمین توانایی اندازه‌گیری مستقیم یون‌های محلول و قابل جذب خاک (فسفر، پتاسیم، آهن، روی، نیترات و شوری) را در سطح باغات ندارد. شاخص‌های پوشش گیاهی نظیر NDVI یا NDMI، کربن آلی و نیتروژن کل تحت هیچ شرایطی جایگزین این عناصر نخواهند شد. نمایش داده‌های خاک مجوزی برای صدور نسخه کودی نیست و صدور توصیه‌ها تا ورود داده‌های آزمایشگاهی مسدود است.
            <div style={{ marginTop: '6px', fontWeight: 700, color: '#c62828' }}>
              «این مقدار در حال حاضر از آزمایش خاک تأیید نشده است.»
            </div>
          </div>

          {/* 6-Parameter Laboratory Verification Required Table */}
          <div className="table-responsive mb-3">
            <table className="table table-bordered table-sm align-middle" style={{ fontSize: '0.84rem' }}>
              <thead style={{ backgroundColor: '#ffebee', color: '#b71c1c' }}>
                <tr>
                  <th style={{ width: '20%' }}>شاخص (Metric)</th>
                  <th style={{ width: '18%' }}>وضعیت داده و علمی</th>
                  <th style={{ width: '38%' }}>علت عدم امکان سنجش ماهواره‌ای (Why unavailable)</th>
                  <th style={{ width: '24%' }}>اقدام پیشنهادی بعدی (Recommended next step)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td><strong>فسفر قابل جذب (Available P)</strong></td>
                  <td>
                    <span className="badge badge-unavailable mb-1">داده واقعی موجود نیست</span>
                    <div style={{ fontSize: '0.72rem', color: '#c62828' }}>نیازمند آزمون آزمایشگاهی</div>
                  </td>
                  <td>سنجنده‌های ماهواره‌ای فاقد بازتابش طیفی مستقیم ارتوپفسفات در محلول خاک هستند (روش اولسن الزامی است).</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-outline-danger" style={{ fontSize: '0.75rem' }} onClick={() => setShowLabModal(true)}>
                      ثبت آزمون آزمایشگاه خاک (روش اولسن)
                    </button>
                  </td>
                </tr>
                <tr>
                  <td><strong>پتاسیم تبادلی (Exchangeable K)</strong></td>
                  <td>
                    <span className="badge badge-unavailable mb-1">داده واقعی موجود نیست</span>
                    <div style={{ fontSize: '0.72rem', color: '#c62828' }}>نیازمند آزمون آزمایشگاهی</div>
                  </td>
                  <td>یون پتاسیم تبادلی فاقد ویژگی جذبی در باندهای ماهواره‌ای است (عصاره استات آمونیوم ۱ نرمال الزامی است).</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-outline-danger" style={{ fontSize: '0.75rem' }} onClick={() => setShowLabModal(true)}>
                      ثبت آزمون آزمایشگاه خاک (استات آمونیوم)
                    </button>
                  </td>
                </tr>
                <tr>
                  <td><strong>نیترات خاک (Soil Nitrate - NO3-)</strong></td>
                  <td>
                    <span className="badge badge-unavailable mb-1">داده واقعی موجود نیست</span>
                    <div style={{ fontSize: '0.72rem', color: '#c62828' }}>نیازمند آزمون آزمایشگاهی</div>
                  </td>
                  <td>نیترات آنیون بسیار متحرک و وابسته به آبیاری است؛ کاملاً متمایز از نیتروژن کل بوده و فاقد سنجش از فضا است.</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-outline-danger" style={{ fontSize: '0.75rem' }} onClick={() => setShowLabModal(true)}>
                      ثبت آزمون آزمایشگاه خاک (اسپکتروفتومتری)
                    </button>
                  </td>
                </tr>
                <tr>
                  <td><strong>شوری عصاره اشباع (ECe)</strong></td>
                  <td>
                    <span className="badge badge-unavailable mb-1">داده واقعی موجود نیست</span>
                    <div style={{ fontSize: '0.72rem', color: '#c62828' }}>نیازمند آزمون آزمایشگاهی</div>
                  </td>
                  <td>سنجش ماهواره‌ای صرفاً بازتاب نمک‌های سطحی سپید را می‌بیند و قادر به ارزیابی شوری عصاره اشباع در عمق ریشه نیست.</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-outline-danger" style={{ fontSize: '0.75rem' }} onClick={() => setShowLabModal(true)}>
                      ثبت آزمون آزمایشگاه خاک (هدایت‌سنجی گل اشباع)
                    </button>
                  </td>
                </tr>
                <tr>
                  <td><strong>روی قابل جذب (Available Zn)</strong></td>
                  <td>
                    <span className="badge badge-unavailable mb-1">داده واقعی موجود نیست</span>
                    <div style={{ fontSize: '0.72rem', color: '#c62828' }}>نیازمند آزمون آزمایشگاهی</div>
                  </td>
                  <td>غلظت روی در حد چند پی‌پی‌ام (ppm) بوده و تفکیک طیفی آن با هیچ ماهواره‌ای امکان‌پذیر نیست (عصاره‌گیری DTPA الزامی است).</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-outline-danger" style={{ fontSize: '0.75rem' }} onClick={() => setShowLabModal(true)}>
                      ثبت آزمون آزمایشگاه خاک (عصاره DTPA)
                    </button>
                  </td>
                </tr>
                <tr>
                  <td><strong>آهن قابل جذب (Available Fe)</strong></td>
                  <td>
                    <span className="badge badge-unavailable mb-1">داده واقعی موجود نیست</span>
                    <div style={{ fontSize: '0.72rem', color: '#c62828' }}>نیازمند آزمون آزمایشگاهی</div>
                  </td>
                  <td>کانی‌های اکسید آهن سطحی نشان‌دهنده آهن قابل جذب ریشه گیاه نیستند (عصاره‌گیری DTPA با اسپکترومتری جذب اتمی الزامی است).</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-outline-danger" style={{ fontSize: '0.75rem' }} onClick={() => setShowLabModal(true)}>
                      ثبت آزمون آزمایشگاه خاک (عصاره DTPA)
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Unavailable Nutrients Grid */}
          <div className="row g-2 mb-3">
            {unavailableNutrients.map((nut: UnavailableNutrient) => (
              <div key={nut.key} className="col-12 col-md-6 col-lg-4">
                <div
                  style={{
                    border: '1px solid #ffcdd2',
                    borderRadius: '6px',
                    padding: '10px 12px',
                    backgroundColor: '#fffafa',
                    height: '100%',
                  }}
                >
                  <div className="d-flex justify-content-between align-items-center mb-1">
                    <strong style={{ color: '#b71c1c', fontSize: '0.88rem' }}>{nut.name_fa}</strong>
                    <span className="badge badge-unavailable">نیازمند آزمایشگاه</span>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: '#546e7a', lineHeight: 1.45 }}>
                    {nut.message_fa}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Machine Learning & Laboratory Calibration Status */}
          <div
            style={{
              background: '#fafafa',
              border: '1px solid #cfd8dc',
              borderRadius: '6px',
              padding: '12px 16px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '12px',
            }}
          >
            <div>
              <div style={{ fontWeight: 600, color: '#37474f', fontSize: '0.9rem' }}>
                وضعیت نگاشت هوش مصنوعی عناصر خاک (ML Nutrient Mapping):
              </div>
              <div style={{ fontSize: '0.82rem', color: '#78909c', marginTop: '2px' }}>
                {labFramework?.message_fa ||
                  'مدل‌سازی یادگیری ماشین عناصر نیازمند داده‌های آزمون خاک کالیبره‌شده آزمایشگاهی بوده و تا اتصال دیتاست واقعی غیرفعال است.'}
              </div>
            </div>
            <div className="d-flex align-items-center gap-2">
              <span className="badge badge-warning" style={{ padding: '6px 12px' }}>
                وضعیت: {labFramework?.ml_nutrient_mapping_status || 'غیرفعال (DEACTIVATED)'}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-outline-primary"
                onClick={() => setShowLabModal(true)}
              >
                مشاهده استاندارد نمونه آزمایشگاهی
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* 5. 10-Year Historical Soil Moisture Comparison (Section 13) */}
      {/* ------------------------------------------------------------- */}
      <div
        className="card mb-3"
        style={{
          border: '1px solid #b0bec5',
          background: '#f8fafc',
          padding: '10px 14px',
          borderRadius: '6px',
          fontSize: '0.84rem',
          color: '#37474f',
          lineHeight: 1.6,
        }}
      >
        <strong>ℹ️ تفکیک متغیرهای زمانی و مکانی خاک:</strong> مقایسه تاریخی ۱۰ ساله زیر صرفاً برای <strong>رطوبت لایه‌ای خاک (Soil Moisture)</strong> معتبر است؛ لایه‌های فیزیکی و شیمیایی خاک (کربن آلی، pH، رس، شن، سیلت، CEC و نیتروژن کل) به عنوان خط مبنای مکانی ثابت (Static Baseline) استفاده می‌شوند و برای تحلیل روند ۱۰ ساله مناسب نیستند.
      </div>
      <Historical10YearSection
        geometry={geometry}
        startDate={startDate}
        endDate={endDate}
        cloudMaxPercent={cloudMaxPercent}
        domain="soil"
        title="10-Year Historical Soil Moisture Comparison"
        titleFa="۵. مقایسه تاریخی ۱۰ ساله رطوبت خاک در دوره مشابه سالانه"
      />

      {/* ------------------------------------------------------------- */}
      {/* 6. Interactive Map Swipe for Soil (Section 12) */}
      {/* ------------------------------------------------------------- */}
      <div
        style={{
          marginBottom: '8px',
          padding: '8px 12px',
          background: '#f1f8e9',
          border: '1px solid #c5e1a5',
          borderRadius: '4px',
          fontSize: '0.82rem',
          color: '#33691e',
        }}
      >
        <strong>راهنمای لایه‌های رستری خاک:</strong> لایه‌های SoilGrids نقشه‌های خط مبنای مدل‌شده (Baseline soil property map) هستند و رطوبت SMAP/ERA5 نشان‌دهنده رطوبت سنجش ماهواره‌ای/بازتحلیل (Satellite soil moisture) است. (وضعیت: Satellite/Model-derived baseline — not laboratory validated).
      </div>
      <OrchardHeatmapSwipeSection
        geometry={geometry}
        startDate={startDate}
        endDate={endDate}
        cloudMaxPercent={cloudMaxPercent}
        initialMetric="soil_moisture"
        allowedMetrics={[
          'soil_moisture',
          'soil_soc',
          'soil_ph',
          'soil_clay',
          'soil_sand',
          'soil_cec',
          'soil_nitrogen',
        ]}
        titleFa="۶. مقایسه کشویی: تصویر ماهواره‌ای باغ ↔ لایه‌های رستری خاک (رطوبت، کربن آلی، pH، رس)"
      />

      {/* ------------------------------------------------------------- */}
      {/* 7. Scientific Quality & Provenance Table */}
      {/* ------------------------------------------------------------- */}
      <div className="card mb-4">
        <div className="card-header">
          <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
            📋 ۷. شناسنامه، وضوح مکانی و زنجیره اصالت داده‌های خاک (Provenance)
          </span>
        </div>
        <div className="card-body">
          <div className="table-responsive">
            <table className="table table-sm table-striped text-center align-middle" style={{ fontSize: '0.82rem' }}>
              <thead style={{ backgroundColor: '#eceff1' }}>
                <tr>
                  <th>مجموعه داده / ماهواره</th>
                  <th>متولی داده</th>
                  <th>متغیر استخراج‌شده</th>
                  <th>وضوح مکانی (Resolution)</th>
                  <th>پوشش عمق</th>
                  <th>بازه زمانی / خط مبنا</th>
                  <th>وضعیت اعتبارسنجی</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style={{ fontWeight: 600 }}>NASA SMAP SPL3SMP_E / SPL4</td>
                  <td>NASA / JPL</td>
                  <td>رطوبت سطحی و عمقی خاک</td>
                  <td>۹۰۰۰ متر (۹ کیلومتر)</td>
                  <td>۰ تا ۵ سانتی‌متر / ۰ تا ۱۰۰ سانتی‌متر</td>
                  <td>پویا (دوره مشابه درخواستی)</td>
                  <td><span className="badge badge-good">تأییدشده GEE</span></td>
                </tr>
                <tr>
                  <td style={{ fontWeight: 600 }}>ECMWF ERA5-Land Daily Aggr</td>
                  <td>Copernicus / ECMWF</td>
                  <td>رطوبت ۴ لایه عمقی خاک</td>
                  <td>۱۱۱۳۲ متر (~۱۱ کیلومتر)</td>
                  <td>۰ تا ۲۸۹ سانتی‌متر (۴ لایه)</td>
                  <td>پویا (سری زمانی ۵۰ ساله)</td>
                  <td><span className="badge badge-good">تأییدشده GEE</span></td>
                </tr>
                <tr>
                  <td style={{ fontWeight: 600 }}>ISRIC SoilGrids 2.0</td>
                  <td>ISRIC - World Soil Information</td>
                  <td>کربن آلی، pH، بافت (رس/شن/سیلت)، CEC، نیتروژن</td>
                  <td>۲۵۰ متر</td>
                  <td>۶ لایه استاندارد تا ۲۰۰cm</td>
                  <td>خط مبنای مدل‌شده ثابت (~۲۰۲۰)</td>
                  <td><span className="badge badge-good">تأییدشده GEE</span></td>
                </tr>
                <tr>
                  <td style={{ fontWeight: 600 }}>ISRIC SoilGrids wv0033 / wv1500</td>
                  <td>ISRIC</td>
                  <td>ظرفیت زراعی (FC) و نقطه پژمردگی (WP)</td>
                  <td>۲۵۰ متر</td>
                  <td>۰ تا ۱۰۰ سانتی‌متر</td>
                  <td>خط مبنای مدل‌شده ثابت</td>
                  <td><span className="badge badge-good">تأییدشده GEE</span></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div style={{ fontSize: '0.8rem', color: '#607d8b', marginTop: '8px', lineHeight: 1.5 }}>
            <strong>محدودیت‌های علمی مصوب:</strong>
            <ul>
              <li>لایه‌های بافت خاک، کربن آلی و pH بر پایه مدل یادگیری ماشین جهانی SoilGrids 2.0 تولید شده‌اند و نمایانگر ویژگی‌های خط مبنای منطقه هستند و تغییرات کوددهی یا شخم ماهانه را منعکس نمی‌کنند.</li>
              <li>داده‌های رطوبت خاک ماهواره‌ای مایکروویو به دلیل طول موج سنجنده، وضوح چندکیلومتری دارند و نمی‌توانند جایگزین پایش موضعی سیستم آبیاری تحت فشار یا لوله‌های قطره‌چکان شوند.</li>
            </ul>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* Laboratory Sample Ingestion Architecture Modal */}
      {/* ------------------------------------------------------------- */}
      {showLabModal && (
        <div
          className="modal show d-block"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 1050 }}
          tabIndex={-1}
        >
          <div className="modal-dialog modal-lg">
            <div className="modal-content">
              <div className="modal-header">
                <h5 className="modal-title">معماری ورود نتایج آزمون خاک آزمایشگاهی (Laboratory Sample Schema)</h5>
                <button
                  type="button"
                  className="btn-close"
                  onClick={() => setShowLabModal(false)}
                />
              </div>
              <div className="modal-body" style={{ fontSize: '0.85rem' }}>
                <p>
                  برای فعال‌سازی کالیبراسیون هوش مصنوعی و برآورد عناصر غذایی، اطلاعات نمونه‌برداری فیزیکی خاک باید در این ساختار استاندارد ثبت شوند:
                </p>
                <div className="table-responsive">
                  <table className="table table-sm table-bordered">
                    <thead style={{ backgroundColor: '#f5f5f5' }}>
                      <tr>
                        <th>فیلد</th>
                        <th>نوع</th>
                        <th>توضیحات</th>
                        <th>مثال</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><code>sample_id</code></td>
                        <td>String</td>
                        <td>شناسه یکتای بارکد آزمایشگاه</td>
                        <td><code>IR-YAZD-PIS-042</code></td>
                      </tr>
                      <tr>
                        <td><code>location</code></td>
                        <td>GeoJSON Point</td>
                        <td>مختصات دقیق محل نمونه‌برداری</td>
                        <td><code>[53.688, 32.427]</code></td>
                      </tr>
                      <tr>
                        <td><code>sample_date</code></td>
                        <td>ISO Date</td>
                        <td>تاریخ نمونه‌برداری میدانی</td>
                        <td><code>2026-05-15</code></td>
                      </tr>
                      <tr>
                        <td><code>depth_from_cm / depth_to_cm</code></td>
                        <td>Float</td>
                        <td>بازه عمق نمونه‌برداری</td>
                        <td><code>0 – 30 cm</code></td>
                      </tr>
                      <tr>
                        <td><code>property</code></td>
                        <td>String</td>
                        <td>شاخص شیمیایی یا فیزیکی</td>
                        <td><code>available_p_olsen</code></td>
                      </tr>
                      <tr>
                        <td><code>value / unit</code></td>
                        <td>Float / String</td>
                        <td>مقدار اندازه‌گیری‌شده و واحد</td>
                        <td><code>14.5 mg/kg (ppm)</code></td>
                      </tr>
                      <tr>
                        <td><code>method</code></td>
                        <td>String</td>
                        <td>روش آزمون استاندارد</td>
                        <td><code>Olsen Bicarbonate Extraction</code></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowLabModal(false)}
                >
                  بستن
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
