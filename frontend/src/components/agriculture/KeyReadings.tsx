import type { EvidenceBundleResponse } from '../../types';
import MetricKpiGrid from './MetricKpiGrid';

interface ReadingGroup {
  title: string;
  titleFa: string;
  metricKeys: string[];
}

/**
 * Headline readings, grouped the way an agronomist reads them. Every key
 * is an existing metric key resolved from the response by MetricKpiGrid:
 * values come straight from the backend, unavailable keys show their
 * real reason, and nothing here is computed or interpreted.
 */
export const KEY_READING_GROUPS: readonly ReadingGroup[] = [
  {
    title: 'Optical vegetation & moisture (Sentinel-2)',
    titleFa: 'پوشش گیاهی و رطوبت — اپتیکال',
    metricKeys: ['ndvi', 'ndmi', 'ndre', 'msi', 'evi', 'savi'],
  },
  {
    title: 'Radar backscatter (Sentinel-1)',
    titleFa: 'پس‌پراکنش رادار',
    metricKeys: ['vv', 'vh', 'vh_vv', 'rvi'],
  },
  {
    title: 'Surface temperature',
    titleFa: 'دمای سطح زمین',
    metricKeys: [
      'land_surface_temperature_day',
      'land_surface_temperature_night',
      'landsat_surface_temperature',
    ],
  },
  {
    title: 'Land cover (Dynamic World)',
    titleFa: 'پوشش زمین',
    metricKeys: ['land_cover_probability'],
  },
  {
    title: 'Terrain',
    titleFa: 'توپوگرافی',
    metricKeys: ['elevation', 'slope', 'aspect', 'terrain_ruggedness'],
  },
  {
    title: 'Soil water properties (SoilGrids)',
    titleFa: 'ویژگی‌های آبی خاک',
    metricKeys: [
      'soil_field_capacity',
      'soil_wilting_point',
      'soil_available_water_capacity',
    ],
  },
  {
    title: 'Soil moisture',
    titleFa: 'رطوبت خاک',
    metricKeys: [
      'soil_moisture_rootzone',
      'soil_moisture_rootzone_era5',
      'soil_moisture_surface',
      'root_zone_soil_moisture_gldas',
    ],
  },
  {
    title: 'Climate (ERA5-Land)',
    titleFa: 'اقلیم',
    metricKeys: [
      'temperature_mean',
      'temperature_max',
      'temperature_min',
      'precipitation',
      'relative_humidity',
      'vpd',
    ],
  },
  {
    title: 'Evapotranspiration & canopy (MODIS)',
    titleFa: 'تبخیر-تعرق و تاج پوشش',
    metricKeys: ['evapotranspiration', 'lai', 'fapar'],
  },
];

export default function KeyReadings({
  bundles,
}: {
  bundles: Record<string, EvidenceBundleResponse>;
}) {
  return (
    <section aria-label="Key readings" className="key-readings mb-3" data-testid="key-readings">
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">
            📌 مقادیر کلیدی برای موقعیت انتخابی — Key readings for the selected location
          </span>
        </div>
        <div className="card-body">
          <div className="text-muted" style={{ fontSize: '0.85rem' }}>
            Each value says what it describes: the <strong>area around the selected
            point</strong> (a support window sized to that dataset&apos;s own grid),
            or the <strong>single large grid cell</strong> that contains the point.
            A metric the data cannot support shows the reason instead of a number.
          </div>
        </div>
      </div>
      {KEY_READING_GROUPS.map((group) => (
        <MetricKpiGrid
          key={group.title}
          title={group.title}
          titleFa={group.titleFa}
          metricKeys={group.metricKeys}
          bundles={bundles}
        />
      ))}
    </section>
  );
}
