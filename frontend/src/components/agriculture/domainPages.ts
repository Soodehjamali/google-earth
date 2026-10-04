import type { ApiDomain } from './request.ts';
import type { TemporalSeriesEntry } from './TemporalSection.tsx';

export type DomainSectionKind =
  | 'kpi'
  | 'timeline'
  | 'aspect'
  | 'temporal'
  | 'year-comparison'
  | 'landcover-shares';

export interface DomainPageSection {
  id: string;
  title: string;
  titleFa: string;
  kind: DomainSectionKind;
  /** Exact metric keys (authoritative AVAILABLE lists, never substring matching). */
  metricKeys: string[];
  /** Scalar-only labeling where the response carries no distribution. */
  note?: string;
  /** Temporal series rendered from backend monthly profiles when present. */
  temporalSeries?: TemporalSeriesEntry[];
}

export interface DomainPageConfig {
  pageKey: string;
  routePath: string;
  /** DOMAIN_META key for the page header. */
  metaKey: string;
  /** Locked `domains[]` payload this view corresponds to. */
  apiDomains: ApiDomain[];
  /** Response bundle keys to read (SynthesisDomain spelling). */
  bundleKeys: string[];
  sections: DomainPageSection[];
}

/**
 * Locked F2 domain-view configuration (Phase 0B §13 mapping).
 * Metric keys are explicit per-metric lists from the registry contract.
 */
export const DOMAIN_PAGE_CONFIGS: Record<string, DomainPageConfig> = {
  vegetation: {
    pageKey: 'vegetation',
    routePath: '/agriculture/vegetation',
    metaKey: 'vegetation',
    apiDomains: ['vegetation'],
    bundleKeys: ['vegetation'],
    sections: [
      {
        id: 'overview',
        title: 'Vegetation Overview',
        titleFa: 'نمای پوشش گیاهی',
        kind: 'kpi',
        metricKeys: ['ndvi', 'evi', 'savi', 'msavi', 'ndre'],
      },
      {
        id: 'canopy',
        title: 'Canopy Structure',
        titleFa: 'ساختار کانوپی',
        kind: 'kpi',
        metricKeys: ['lai', 'fapar', 'fcover'],
      },
      {
        id: 'dryness-proxy',
        title: 'Middle-Canopy Dryness (proxy)',
        titleFa: 'خشکی میانی کانوپی (پراکسی)',
        kind: 'kpi',
        metricKeys: ['middle_canopy_dryness_proxy'],
        note: 'Evidence proxy with categorical states — never a direct leaf measurement.',
      },
      {
        id: 'temporal-optical',
        title: 'Optical Temporal Intelligence',
        titleFa: 'هوش زمانی نوری',
        kind: 'temporal',
        metricKeys: ['ndvi', 'ndre'],
        temporalSeries: [
          { metricKey: 'ndvi', label: 'NDVI', labelFa: 'NDVI', unit: 'index' },
          { metricKey: 'ndre', label: 'NDRE', labelFa: 'NDRE', unit: 'index' },
        ],
      },
      {
        id: 'temporal-radar',
        title: 'Radar Temporal Intelligence',
        titleFa: 'هوش زمانی راداری',
        kind: 'temporal',
        metricKeys: ['vv', 'vh', 'vh_vv', 'rvi'],
        temporalSeries: [
          { metricKey: 'vv', label: 'VV', labelFa: 'VV', unit: 'dB' },
          { metricKey: 'vh', label: 'VH', labelFa: 'VH', unit: 'dB' },
          { metricKey: 'vh_vv', label: 'VH/VV', labelFa: 'VH/VV', unit: 'dB' },
          { metricKey: 'rvi', label: 'RVI', labelFa: 'RVI', unit: 'ratio' },
        ],
      },
    ],
  },
  phenology: {
    pageKey: 'phenology',
    routePath: '/agriculture/phenology',
    metaKey: 'phenology',
    apiDomains: ['phenology', 'productivity'],
    bundleKeys: ['phenology', 'productivity'],
    sections: [
      {
        id: 'timeline',
        title: 'Season Timeline',
        titleFa: 'خط زمانی فصل',
        kind: 'timeline',
        metricKeys: [
          'vegetation_season_onset',
          'vegetation_activity_peak',
          'vegetation_season_end',
        ],
      },
      {
        id: 'characteristics',
        title: 'Season Characteristics',
        titleFa: 'ویژگی‌های فصل',
        kind: 'kpi',
        metricKeys: ['vegetation_season_length', 'vegetation_season_amplitude'],
      },
      {
        id: 'productivity',
        title: 'Productivity Context (proxies only)',
        titleFa: 'بهره‌وری (شاخص تقریبی)',
        kind: 'kpi',
        metricKeys: [
          'seasonal_vegetation_productivity_indicator',
          'seasonal_evapotranspiration_context',
          'crop_area_normalised_productivity_indicator',
        ],
        note: 'Proxy indicators — never a yield estimate.',
      },
    ],
  },
  climate: {
    pageKey: 'climate',
    routePath: '/agriculture/climate',
    metaKey: 'climate',
    // P4: `thermal` is required for the air-temperature temporal profile
    // (`temporal.thermal_profiles.temperature_mean`) this page renders.
    apiDomains: ['climate', 'thermal'],
    bundleKeys: ['climate'],
    sections: [
      {
        id: 'temperature',
        title: 'Temperature',
        titleFa: 'دما',
        kind: 'kpi',
        metricKeys: ['temperature_max', 'temperature_min', 'temperature_mean'],
      },
      {
        id: 'atmospheric',
        title: 'Atmospheric',
        titleFa: 'جوّی',
        kind: 'kpi',
        metricKeys: ['vpd', 'relative_humidity', 'wind_speed'],
      },
      {
        id: 'radiation',
        title: 'Radiation',
        titleFa: 'تابش',
        kind: 'kpi',
        metricKeys: ['solar_radiation', 'par'],
      },
      {
        id: 'growing',
        title: 'Precipitation / Growing Conditions',
        titleFa: 'بارش و شرایط رشد',
        kind: 'kpi',
        metricKeys: ['precipitation', 'gdd'],
      },
      {
        id: 'temporal-air-temperature',
        title: 'Air Temperature Temporal Intelligence',
        titleFa: 'هوش زمانی دمای هوا',
        kind: 'temporal',
        metricKeys: ['temperature_mean'],
        temporalSeries: [
          {
            metricKey: 'temperature_mean',
            label: 'Mean Air Temperature',
            labelFa: 'میانگین دمای هوا',
            unit: 'degC',
            sourceNote: 'ERA5-Land · Modelled 2 m Air Temperature',
            thermalKind: 'AIR_TEMPERATURE_PROFILE',
          },
        ],
      },
    ],
  },
  water: {
    pageKey: 'water',
    routePath: '/agriculture/water',
    metaKey: 'water',
    apiDomains: ['water'],
    bundleKeys: ['water'],
    sections: [
      {
        id: 'indices',
        title: 'Spectral Water Indices',
        titleFa: 'شاخص‌های طیفی آب',
        kind: 'kpi',
        metricKeys: ['ndwi', 'ndmi', 'mndwi'],
      },
      {
        id: 'et',
        title: 'Evapotranspiration',
        titleFa: 'تبخیر-تعرق',
        kind: 'kpi',
        metricKeys: [
          'evapotranspiration',
          'potential_evapotranspiration',
          'evapotranspiration_cumulative',
          'era5_evaporation',
        ],
      },
      {
        id: 'temporal-moisture',
        title: 'Moisture Temporal Intelligence',
        titleFa: 'هوش زمانی رطوبت',
        kind: 'temporal',
        metricKeys: ['ndmi', 'msi'],
        temporalSeries: [
          { metricKey: 'ndmi', label: 'NDMI', labelFa: 'NDMI', unit: 'index' },
          { metricKey: 'msi', label: 'MSI', labelFa: 'MSI', unit: 'index' },
        ],
      },
    ],
  },
  soil: {
    pageKey: 'soil',
    routePath: '/agriculture/soil',
    metaKey: 'soil',
    apiDomains: ['soil'],
    bundleKeys: ['soil'],
    sections: [
      {
        id: 'moisture',
        title: 'Moisture',
        titleFa: 'رطوبت',
        kind: 'kpi',
        metricKeys: [
          'soil_moisture_surface',
          'soil_moisture_surface_evening',
          'soil_moisture_rootzone',
          'soil_moisture_rootzone_era5',
          'soil_moisture_wetness',
          'root_zone_soil_moisture_gldas',
        ],
      },
      {
        id: 'properties',
        title: 'Properties & Temperature',
        titleFa: 'ویژگی‌ها و دما',
        kind: 'kpi',
        metricKeys: [
          'soil_field_capacity',
          'soil_wilting_point',
          'soil_available_water_capacity',
          'soil_temperature_0_7cm',
          'soil_temperature_7_28cm',
        ],
      },
      {
        id: 'composition',
        title: 'Composition (reference layers)',
        titleFa: 'ترکیب (لایه‌های مرجع)',
        kind: 'kpi',
        metricKeys: [
          'soil_organic_carbon',
          'soil_texture_class',
          'soil_ph',
        ],
        note: 'Registered reference metrics with no Earth Engine layer; they render as unavailable, never as values.',
      },
    ],
  },
  thermal: {
    pageKey: 'thermal',
    routePath: '/agriculture/thermal',
    metaKey: 'thermal',
    apiDomains: ['thermal'],
    bundleKeys: ['thermal'],
    sections: [
      {
        id: 'lst',
        title: 'Land Surface Temperature',
        titleFa: 'دمای سطح زمین',
        kind: 'kpi',
        metricKeys: [
          'land_surface_temperature_day',
          'land_surface_temperature_night',
          'land_surface_temperature_mean',
        ],
      },
      {
        id: 'context',
        title: 'Range & Context',
        titleFa: 'دامنه و بافت',
        kind: 'kpi',
        metricKeys: ['surface_temperature_range', 'landsat_surface_temperature'],
      },
      {
        id: 'temporal-lst',
        title: 'Land Surface Temperature Intelligence',
        titleFa: 'هوش زمانی دمای سطح زمین',
        kind: 'temporal',
        metricKeys: ['land_surface_temperature_day'],
        temporalSeries: [
          {
            metricKey: 'land_surface_temperature_day',
            label: 'Daytime Land Surface Temperature',
            labelFa: 'دمای سطح زمین در روز',
            unit: 'degC',
            sourceNote: 'MODIS · Land Surface Temperature',
            thermalKind: 'LST_PROFILE',
          },
        ],
      },
    ],
  },
  terrain: {
    pageKey: 'terrain',
    routePath: '/agriculture/terrain',
    metaKey: 'terrain',
    apiDomains: ['terrain'],
    bundleKeys: ['terrain'],
    sections: [
      {
        id: 'relief',
        title: 'Elevation, Slope & Ruggedness',
        titleFa: 'ارتفاع، شیب و ناهمواری',
        kind: 'kpi',
        metricKeys: ['elevation', 'slope', 'terrain_ruggedness'],
      },
      {
        id: 'aspect',
        title: 'Aspect',
        titleFa: 'جهت شیب',
        kind: 'aspect',
        metricKeys: ['aspect'],
      },
    ],
  },
  'land-crop': {
    pageKey: 'land-crop',
    routePath: '/agriculture/land-crop',
    metaKey: 'landcover',
    apiDomains: ['landcover', 'crop'],
    bundleKeys: ['landcover', 'crop'],
    sections: [
      {
        id: 'landcover',
        title: 'Land Cover (scalar summary)',
        titleFa: 'پوشش اراضی (خلاصه عددی)',
        kind: 'kpi',
        metricKeys: [
          'land_cover_class',
          'land_cover_quality',
          'land_cover_probability',
        ],
        note: 'Scalar summary with structured detail — category distribution and band probabilities where the response carries them.',
      },
      {
        id: 'landcover-shares',
        title: 'Land Cover Class Shares',
        titleFa: 'ترکیب کلاس‌های پوشش ارضی',
        kind: 'landcover-shares',
        metricKeys: ['land_cover_class'],
        note: 'درصدها و نام کلاس‌ها عیناً از پاسخ خوانده می‌شوند؛ مساحت (کیلومتر مربع) در این پاسخ ارائه نشده است.',
      },
      {
        id: 'crop',
        title: 'Crop Context',
        titleFa: 'بافت زراعی',
        kind: 'kpi',
        metricKeys: [
          'temporary_crop_context',
          'maize_context',
          'cereal_context',
          'temporary_crop_area',
        ],
        note: 'Context indicators — not definitive crop classification.',
      },
    ],
  },
  'stress-irrigation': {
    pageKey: 'stress-irrigation',
    routePath: '/agriculture/stress-irrigation',
    metaKey: 'stress',
    apiDomains: ['stress', 'irrigation'],
    bundleKeys: ['stress', 'irrigation'],
    sections: [
      {
        id: 'stress',
        title: 'Stress Indicators',
        titleFa: 'شاخص‌های تنش',
        kind: 'kpi',
        metricKeys: [
          'evaporative_fraction',
          'soil_water_content_ratio',
          'plant_available_water_fraction',
          'vpd_anomaly',
          'vpd_high_duration',
          'lst_day_anomaly',
          'lst_day_percentile',
        ],
        note: 'Individual indicators — never combined into an overall score.',
      },
      {
        id: 'irrigation',
        title: 'Irrigation Context',
        titleFa: 'بافت آبیاری',
        kind: 'kpi',
        metricKeys: [
          'precipitation_cumulative',
          'et_precipitation_deficit',
          'precipitation_anomaly',
          'evapotranspiration_anomaly',
          'soil_moisture_rootzone_anomaly',
        ],
      },
    ],
  },
  history: {
    pageKey: 'history',
    routePath: '/agriculture/history',
    metaKey: 'historical',
    apiDomains: ['historical'],
    bundleKeys: ['historical'],
    sections: [
      {
        id: 'anomalies',
        title: 'NDVI Anomalies',
        titleFa: 'ناهنجاری‌های NDVI',
        kind: 'kpi',
        metricKeys: [
          'ndvi_anomaly_absolute',
          'ndvi_anomaly_relative',
          'ndvi_anomaly_standardized',
          'ndvi_percentile_context',
        ],
      },
      {
        id: 'change',
        title: 'NDVI Change',
        titleFa: 'تغییرات NDVI',
        kind: 'kpi',
        metricKeys: [
          'ndvi_trend',
          'ndvi_anomaly_persistence',
          'ndvi_change_shift',
        ],
      },
      {
        id: 'climate-season',
        title: 'Climate / Season',
        titleFa: 'اقلیم و فصل',
        kind: 'kpi',
        metricKeys: ['climate_trend', 'season_timing_history'],
      },
      {
        id: 'year-comparison',
        title: 'Year-over-Year NDVI Comparison',
        titleFa: 'مقایسه سال‌به‌سال NDVI',
        kind: 'year-comparison',
        metricKeys: ['ndvi'],
      },
    ],
  },
};

/** All metric keys surfaced as primary grouped evidence across F2 pages. */
export function allConfiguredMetricKeys(): string[] {
  const keys = new Set<string>();
  for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
    for (const section of config.sections) {
      for (const key of section.metricKeys) keys.add(key);
    }
  }
  return [...keys].sort();
}

/**
 * Route path of the domain page covering a response bundle key,
 * or null when no domain page exists for it. Derived from the
 * locked configs — never hardcoded twice.
 */
export function routePathForDomain(domainKey: string): string | null {
  for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
    if (config.bundleKeys.includes(domainKey)) return config.routePath;
  }
  return null;
}
