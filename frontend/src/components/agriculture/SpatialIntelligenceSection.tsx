import { useEffect, useState } from 'react';
import MapView from '../MapView';
import { agricultureApi } from '../../api/agriculture';
import type {
  AgricultureGeometry,
  SpatialConceptType,
  SpatialLayerResponse,
  SpatialMetricType,
} from '../../types';
import { formatPersianDateRange } from './persianDate';

interface SpatialIntelligenceSectionProps {
  geometry: GeoJSON.Geometry | AgricultureGeometry | null;
  startDate: string;
  endDate: string;
  cloudMaxPercent?: number;
  disableAutoFetch?: boolean;
}

interface ConceptOption {
  key: SpatialConceptType;
  label: string;
  labelFa: string;
  icon: string;
  underlyingMetric: string;
  resolution: string;
  description: string;
}

interface MetricOption {
  key: SpatialMetricType;
  label: string;
  labelFa: string;
  icon: string;
  category: 'optical' | 'thermal' | 'radar' | 'moisture' | 'soilgrids';
  categoryFa: string;
  datasetName: string;
  resolution: string;
  unit: string;
}

const CONCEPT_OPTIONS: ConceptOption[] = [
  {
    key: 'vegetation_condition',
    label: 'Vegetation Condition (NDVI)',
    labelFa: 'وضعیت پوشش گیاهی',
    icon: '🌿',
    underlyingMetric: 'Sentinel-2 NDVI',
    resolution: '10 m',
    description: 'تراکم و سبزی نسبی کانوپی فتوسنتزی',
  },
  {
    key: 'thermal_stress',
    label: 'Thermal Stress Proxy (LST)',
    labelFa: 'نمایه تنش حرارتی',
    icon: '🌡️',
    underlyingMetric: 'MODIS LST Day',
    resolution: '1000 m (1 km)',
    description: 'بار حرارتی سطح زمین در گستره منطقه‌ای',
  },
  {
    key: 'surface_dryness',
    label: 'Surface Dryness Proxy (NDMI)',
    labelFa: 'نمایه خشکی سطح و کانوپی',
    icon: '💧',
    underlyingMetric: 'Sentinel-2 NDMI',
    resolution: '20 m',
    description: 'تغییرات مکانی رطوبت سطح و کانوپی',
  },
  {
    key: 'soil_organic_carbon',
    label: 'Soil Organic Carbon (SOC)',
    labelFa: 'کربن آلی خاک (SOC)',
    icon: '🌍',
    underlyingMetric: 'ISRIC SoilGrids 2.0 (0–30 cm)',
    resolution: '250 m',
    description: 'توزیع مکانی کربن آلی خاک',
  },
  {
    key: 'soil_acidity_ph',
    label: 'Soil pH in H2O',
    labelFa: 'اسیدیته خاک (pH)',
    icon: '🧪',
    underlyingMetric: 'ISRIC SoilGrids 2.0 (0–30 cm)',
    resolution: '250 m',
    description: 'خط مبنای اسیدیته خاک در آب',
  },
  {
    key: 'soil_texture_clay',
    label: 'Soil Clay Content',
    labelFa: 'بافت رس خاک (Clay)',
    icon: '🧱',
    underlyingMetric: 'ISRIC SoilGrids 2.0 (0–30 cm)',
    resolution: '250 m',
    description: 'درصد رس خاک در عمق ۰ تا ۳۰ سانتی‌متر',
  },
];

const METRIC_OPTIONS: MetricOption[] = [
  // 1. Optical / Canopy
  {
    key: 'ndvi',
    category: 'optical',
    categoryFa: '🌿 پوشش گیاهی و کانوپی',
    label: 'NDVI (Vegetation Index)',
    labelFa: 'شاخص پوشش گیاهی (NDVI)',
    icon: '🌿',
    datasetName: 'Sentinel-2 Harmonized',
    resolution: '10 m',
    unit: 'index',
  },
  {
    key: 'ndmi',
    category: 'optical',
    categoryFa: '🌿 پوشش گیاهی و کانوپی',
    label: 'NDMI (Moisture Index)',
    labelFa: 'شاخص رطوبت کانوپی (NDMI)',
    icon: '💧',
    datasetName: 'Sentinel-2 Harmonized',
    resolution: '20 m',
    unit: 'index',
  },
  {
    key: 'ndre',
    category: 'optical',
    categoryFa: '🌿 پوشش گیاهی و کانوپی',
    label: 'NDRE (Red Edge Chlorophyll)',
    labelFa: 'شاخص لبه قرمز کلروفیل (NDRE)',
    icon: '🌱',
    datasetName: 'Sentinel-2 Harmonized',
    resolution: '20 m',
    unit: 'index',
  },
  {
    key: 'msi',
    category: 'optical',
    categoryFa: '🌿 پوشش گیاهی و کانوپی',
    label: 'MSI (Moisture Stress Index)',
    labelFa: 'شاخص تنش رطوبت کانوپی (MSI)',
    icon: '🍂',
    datasetName: 'Sentinel-2 Harmonized',
    resolution: '20 m',
    unit: 'index',
  },
  // 2. Thermal
  {
    key: 'lst_day',
    category: 'thermal',
    categoryFa: '🌡️ حرارتی و دما',
    label: 'LST Day (Land Surface Temp)',
    labelFa: 'دمای سطح زمین روزانه (LST)',
    icon: '🌡️',
    datasetName: 'MODIS MOD11A2',
    resolution: '1000 m (1 km)',
    unit: '°C',
  },
  // 3. Radar
  {
    key: 'sar_vh',
    category: 'radar',
    categoryFa: '📡 راداری و ساختار',
    label: 'Sentinel-1 Radar VH',
    labelFa: 'پس‌پراکنش راداری کانوپی (SAR VH)',
    icon: '📡',
    datasetName: 'Sentinel-1 GRD IW',
    resolution: '10 m',
    unit: 'dB',
  },
  // 4. Moisture / Hydrology
  {
    key: 'soil_moisture',
    category: 'moisture',
    categoryFa: '💧 رطوبت و هیدرولوژی',
    label: 'Root-Zone Soil Moisture',
    labelFa: 'رطوبت خاک ناحیه ریشه',
    icon: '💧',
    datasetName: 'SMAP L4 / ERA5-Land',
    resolution: '9000 m (9 km)',
    unit: 'm³/m³',
  },
  // 5. SoilGrids 250m
  {
    key: 'soil_soc',
    category: 'soilgrids',
    categoryFa: '🌍 خاک‌شناسی SoilGrids (250m)',
    label: 'Soil Organic Carbon (0–30 cm)',
    labelFa: 'کربن آلی خاک (SOC)',
    icon: '🌍',
    datasetName: 'ISRIC SoilGrids 2.0',
    resolution: '250 m',
    unit: 'g/kg',
  },
  {
    key: 'soil_ph',
    category: 'soilgrids',
    categoryFa: '🌍 خاک‌شناسی SoilGrids (250m)',
    label: 'Soil pH in H2O (0–30 cm)',
    labelFa: 'اسیدیته خاک (pH)',
    icon: '🧪',
    datasetName: 'ISRIC SoilGrids 2.0',
    resolution: '250 m',
    unit: 'pH',
  },
  {
    key: 'soil_clay',
    category: 'soilgrids',
    categoryFa: '🌍 خاک‌شناسی SoilGrids (250m)',
    label: 'Soil Clay Content (0–30 cm)',
    labelFa: 'رس خاک (Clay)',
    icon: '🧱',
    datasetName: 'ISRIC SoilGrids 2.0',
    resolution: '250 m',
    unit: '%',
  },
  {
    key: 'soil_sand',
    category: 'soilgrids',
    categoryFa: '🌍 خاک‌شناسی SoilGrids (250m)',
    label: 'Soil Sand Content (0–30 cm)',
    labelFa: 'ماسه خاک (Sand)',
    icon: '🏖️',
    datasetName: 'ISRIC SoilGrids 2.0',
    resolution: '250 m',
    unit: '%',
  },
  {
    key: 'soil_cec',
    category: 'soilgrids',
    categoryFa: '🌍 خاک‌شناسی SoilGrids (250m)',
    label: 'Cation Exchange Capacity (0–30 cm)',
    labelFa: 'ظرفیت تبادل کاتیونی (CEC)',
    icon: '⚡',
    datasetName: 'ISRIC SoilGrids 2.0',
    resolution: '250 m',
    unit: 'cmol(c)/kg',
  },
  {
    key: 'soil_nitrogen',
    category: 'soilgrids',
    categoryFa: '🌍 خاک‌شناسی SoilGrids (250m)',
    label: 'Total Nitrogen (0–30 cm)',
    labelFa: 'نیتروژن کل خاک (Total N)',
    icon: '🔬',
    datasetName: 'ISRIC SoilGrids 2.0',
    resolution: '250 m',
    unit: 'g/kg',
  },
];

export default function SpatialIntelligenceSection({
  geometry,
  startDate,
  endDate,
  cloudMaxPercent = 20,
  disableAutoFetch = false,
}: SpatialIntelligenceSectionProps) {
  const [userRequested, setUserRequested] = useState<boolean>(!disableAutoFetch);
  const [viewMode, setViewMode] = useState<'interpretation' | 'raw'>('interpretation');
  const [selectedConcept, setSelectedConcept] = useState<SpatialConceptType>('vegetation_condition');
  const [isSarLayerActive, setIsSarLayerActive] = useState<boolean>(false);
  const [selectedMetric, setSelectedMetric] = useState<SpatialMetricType>('ndvi');
  const [selectedCategory, setSelectedCategory] = useState<
    'all' | 'optical' | 'thermal' | 'radar' | 'moisture' | 'soilgrids'
  >('all');
  const [retryKey, setRetryKey] = useState<number>(0);
  const [layerData, setLayerData] = useState<SpatialLayerResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [opacity, setOpacity] = useState<number>(0.85);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState<boolean>(false);

  useEffect(() => {
    if (!userRequested) return;
    if (!geometry || !startDate || !endDate) return;

    let isMounted = true;
    setLoading(true);
    setError(null);
    setLayerData(null);

    const requestPayload =
      viewMode === 'interpretation' && !isSarLayerActive
        ? {
            concept: selectedConcept,
            geometry,
            start_date: startDate,
            end_date: endDate,
            cloud_max_percent: cloudMaxPercent,
          }
        : {
            metric: isSarLayerActive ? 'sar_vh' : selectedMetric,
            geometry,
            start_date: startDate,
            end_date: endDate,
            cloud_max_percent: cloudMaxPercent,
          };

    agricultureApi
      .getSpatialLayer(requestPayload)
      .then((data) => {
        if (!isMounted) return;
        setLayerData(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        console.error('Failed to load spatial layer:', err);
        setError(err instanceof Error ? err.message : 'Error fetching spatial raster layer');
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [userRequested, geometry, startDate, endDate, viewMode, selectedConcept, isSarLayerActive, selectedMetric, cloudMaxPercent, retryKey]);

  if (!geometry) return null;

  if (disableAutoFetch && !userRequested && !layerData) {
    return (
      <div className="card mb-4" data-testid="spatial-intelligence-section">
        <div
          className="card-header"
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 10,
          }}
        >
          <div>
            <span className="card-title" style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>
              🗺️ نقشه‌های حرارتی تفسیری کشاورزی و شواهد خام ماهواره‌ای
            </span>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 2 }}>
              Agricultural Interpretation Heatmaps & Raw RS Evidence
            </div>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            onClick={() => setUserRequested(true)}
          >
            🛰️ بارگذاری نقشه حرارتی فضایی ماهواره‌ای (GEE)
          </button>
        </div>
        <div className="card-body text-muted" style={{ fontSize: '0.82rem' }}>
          در مرور گزارش ذخیره‌شده، لایه‌های رستری فضایی جهت تسریع ناوبری و کاهش بار پردازشی به صورت خودکار بارگذاری نمی‌شوند. برای مشاهده نقشه حرارتی، دکمه بالا را فشار دهید.
        </div>
      </div>
    );
  }

  const activeConcept =
    CONCEPT_OPTIONS.find((opt) => opt.key === selectedConcept) ?? CONCEPT_OPTIONS[0];
  const activeMetric =
    METRIC_OPTIONS.find((opt) => opt.key === selectedMetric) ?? METRIC_OPTIONS[0];

  const currentTitleFa =
    viewMode === 'interpretation'
      ? isSarLayerActive
        ? 'ساختار کانوپی و بیومس راداری (SAR VH)'
        : layerData?.concept_name_fa || activeConcept.labelFa
      : activeMetric.labelFa;
  const currentTitleEn =
    viewMode === 'interpretation'
      ? isSarLayerActive
        ? 'Canopy Structure & Radar Biomass (SAR VH)'
        : layerData?.concept_name || activeConcept.label
      : activeMetric.label;

  // Palette gradient CSS
  const paletteGradient =
    layerData?.palette && layerData.palette.length > 0
      ? `linear-gradient(to right, ${layerData.palette.join(', ')})`
      : 'linear-gradient(to right, #4CAF50, #FFEB3B, #F44336)';

  return (
    <div className="card mb-3" data-testid="spatial-intelligence-section">
      <div
        className="card-header"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="card-title" style={{ margin: 0 }}>🗺️ نقشه و هوش مکانی — Spatial Intelligence</span>
          <span className="badge badge-good" style={{ fontSize: '0.75rem' }}>
            Real GEE Rasters Only
          </span>
        </div>

        {/* View Mode Toggle: Agricultural Interpretation vs Raw Satellite Layers */}
        <div className="flex gap-1" style={{ background: 'var(--bg-secondary, #eee)', padding: 3, borderRadius: 6 }}>
          <button
            type="button"
            data-testid="spatial-mode-interpretation"
            className={`btn ${viewMode === 'interpretation' ? 'btn-primary' : 'btn-outline'}`}
            style={{ padding: '4px 10px', fontSize: '0.8rem', border: 'none' }}
            onClick={() => setViewMode('interpretation')}
          >
            🌱 تفسیر کشاورزی (Interpretation)
          </button>
          <button
            type="button"
            data-testid="spatial-mode-raw"
            className={`btn ${viewMode === 'raw' ? 'btn-primary' : 'btn-outline'}`}
            style={{ padding: '4px 10px', fontSize: '0.8rem', border: 'none' }}
            onClick={() => {
              setViewMode('raw');
              setIsSarLayerActive(false);
            }}
          >
            🛰️ لایه‌های خام سنجش‌ازدور (Raw RS)
          </button>
        </div>
      </div>

      <div className="card-body">
        {/* Agricultural UI Objective Banner (P-AGRI-DSS-1 §4) */}
        <div
          data-testid="spatial-dss-goal-banner"
          style={{
            padding: '10px 14px',
            marginBottom: 14,
            background: '#f1f8e9',
            border: '1px solid #c5e1a5',
            borderRadius: 8,
            fontSize: '0.82rem',
            color: '#2e7d32',
            lineHeight: 1.55,
          }}
        >
          📍 <strong>هدف نقشه حرارتی ماهواره‌ای:</strong> نمایش تفاوت‌های نسبی بین بخش‌های مختلف زمین جهت شناسایی نقاط ضعیف‌تر و هدایت اولویت‌های بررسی میدانی (بدون ادعای تجویز کود یا قضاوت شیمیایی).
        </div>

        {/* Layer Selector Bar */}
        <div style={{ marginBottom: 16 }}>
          {viewMode === 'interpretation' ? (
            <div>
              <div className="text-muted" style={{ fontSize: '0.85rem', marginBottom: 6 }}>
                انتخاب مفهوم تفسیر کشاورزی — Select Agricultural Concept Heatmap:
              </div>
              <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
                {CONCEPT_OPTIONS.map((opt) => {
                  const isActive = !isSarLayerActive && selectedConcept === opt.key;
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      data-testid={`spatial-concept-btn-${opt.key}`}
                      className={`btn ${isActive ? 'btn-primary' : 'btn-outline'}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '6px 14px',
                        fontSize: '0.85rem',
                      }}
                      onClick={() => {
                        setIsSarLayerActive(false);
                        setSelectedConcept(opt.key);
                      }}
                    >
                      <span>{opt.icon}</span>
                      <span style={{ fontWeight: isActive ? 600 : 400 }}>{opt.labelFa}</span>
                      <span className="badge" style={{ fontSize: '0.7rem', padding: '2px 5px' }}>
                        {opt.resolution}
                      </span>
                    </button>
                  );
                })}
                <button
                  type="button"
                  data-testid="spatial-concept-btn-sar_structure"
                  className={`btn ${isSarLayerActive ? 'btn-primary' : 'btn-outline'}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '6px 14px',
                    fontSize: '0.85rem',
                  }}
                  onClick={() => setIsSarLayerActive(true)}
                >
                  <span>📡</span>
                  <span style={{ fontWeight: isSarLayerActive ? 600 : 400 }}>SAR / ساختار پوشش</span>
                  <span className="badge" style={{ fontSize: '0.7rem', padding: '2px 5px' }}>
                    10 m
                  </span>
                </button>
              </div>
            </div>
          ) : (
            <div>
              {/* Category Filter Pills */}
              <div className="flex gap-1 mb-2" style={{ flexWrap: 'wrap', borderBottom: '1px solid #e0e0e0', paddingBottom: 6 }}>
                {[
                  { key: 'all' as const, label: 'همه شاخص‌ها (۱۳)' },
                  { key: 'optical' as const, label: '🌿 پوشش گیاهی و کانوپی (۴)' },
                  { key: 'thermal' as const, label: '🌡️ حرارتی و دما (۱)' },
                  { key: 'radar' as const, label: '📡 راداری ساختار (۱)' },
                  { key: 'moisture' as const, label: '💧 رطوبت هیدرولوژی (۱)' },
                  { key: 'soilgrids' as const, label: '🌍 خاک‌شناسی SoilGrids (۶)' },
                ].map((cat) => (
                  <button
                    key={cat.key}
                    type="button"
                    className={`btn btn-sm ${selectedCategory === cat.key ? 'btn-secondary' : 'btn-outline'}`}
                    style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                    onClick={() => setSelectedCategory(cat.key)}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>

              <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
                {METRIC_OPTIONS.filter((opt) => selectedCategory === 'all' || opt.category === selectedCategory).map((opt) => {
                  const isActive = selectedMetric === opt.key;
                  return (
                    <button
                      key={opt.key}
                      type="button"
                      data-testid={`spatial-metric-btn-${opt.key}`}
                      className={`btn ${isActive ? 'btn-primary' : 'btn-outline'}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '6px 12px',
                        fontSize: '0.85rem',
                      }}
                      onClick={() => setSelectedMetric(opt.key)}
                    >
                      <span>{opt.icon}</span>
                      <span style={{ fontWeight: isActive ? 600 : 400 }}>{opt.labelFa}</span>
                      <span className="badge" style={{ fontSize: '0.7rem', padding: '1px 4px' }}>
                        {opt.resolution}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Map and Controls Container */}
        <div
          style={{
            position: 'relative',
            borderRadius: 8,
            overflow: 'hidden',
            border: '1px solid var(--border-color, #e0e0e0)',
          }}
        >
          {/* Map */}
          <div style={{ height: 420 }}>
            <MapView
              geometry={geometry as GeoJSON.Geometry}
              rasterTileUrl={layerData?.status === 'available' ? layerData.tile_url_template : null}
              rasterOpacity={opacity}
              bounds={layerData?.bounds}
            />
          </div>

          {/* Loading Overlay */}
          {loading && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: 'rgba(255, 255, 255, 0.75)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                zIndex: 10,
              }}
            >
              <div className="spinner" style={{ width: 36, height: 36 }} />
              <div style={{ marginTop: 12, fontWeight: 500, fontSize: '0.9rem' }}>
                در حال بارگذاری لایه {currentTitleFa}...
              </div>
              <div className="text-muted" style={{ fontSize: '0.8rem' }}>
                Fetching real GEE raster tiles for {currentTitleEn}
              </div>
            </div>
          )}

          {/* Opacity Control Overlay */}
          <div
            style={{
              position: 'absolute',
              top: 10,
              left: 10,
              background: 'rgba(255, 255, 255, 0.92)',
              padding: '4px 10px',
              borderRadius: 6,
              boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              zIndex: 5,
            }}
          >
            <span>شفافیت — Opacity:</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={opacity}
              onChange={(e) => setOpacity(parseFloat(e.target.value))}
              style={{ width: 80, cursor: 'pointer' }}
            />
            <span>{Math.round(opacity * 100)}%</span>
          </div>
        </div>

        {/* Unavailable or Error State with explicit Retry action */}
        {error && (
          <div className="alert alert-danger" style={{ marginTop: 12 }} data-testid="spatial-error-alert">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <div>
                <div style={{ fontWeight: 600 }}>خطای سیستمی / شبکه در بارگذاری لایه مکانی — Unable to load spatial layer</div>
                <div style={{ fontSize: '0.85rem', marginTop: 2 }}>{error}</div>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-outline-danger"
                data-testid="spatial-retry-btn"
                onClick={() => setRetryKey((k) => k + 1)}
              >
                🔄 تلاش مجدد
              </button>
            </div>
          </div>
        )}

        {layerData && layerData.status === 'unavailable' && (
          <div className="alert alert-warning" style={{ marginTop: 12 }} data-testid="spatial-unavailable-alert">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
              <div>
                <div style={{ fontWeight: 600 }}>داده ماهواره‌ای در این تاریخ/محدوده در دسترس نیست — No spatial data available</div>
                <div style={{ fontSize: '0.85rem', marginTop: 2 }}>
                  {layerData.unavailable_reason ?? 'در بازه زمانی درخواستی، تصویر معتبر بدون ابر یا گذر سنجنده یافت نشد.'}
                </div>
                {layerData.limitations.map((lim, i) => (
                  <div key={i} className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
                    • {lim}
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary"
                data-testid="spatial-retry-btn"
                onClick={() => setRetryKey((k) => k + 1)}
              >
                🔄 بازخوانی مجدد
              </button>
            </div>
          </div>
        )}

        {/* Interpretation & Scientific Caution Panel (Phase P-AGRI-4 & P-AGRI-DSS-1) */}
        {layerData && layerData.status === 'available' && (layerData.interpretation || isSarLayerActive) && (
          <div
            className="card"
            data-testid="spatial-interpretation-card"
            style={{
              marginTop: 16,
              padding: '14px 16px',
              background: 'var(--bg-secondary, #f8fbfd)',
              borderLeft: '4px solid #1976d2',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 600, fontSize: '0.95rem', color: '#1565c0' }}>
                💡 تفسیر کشاورزی: {isSarLayerActive ? 'ساختار کانوپی و بیومس راداری (Sentinel-1 SAR VH)' : (layerData.concept_name_fa || layerData.concept_name)}
              </span>
              <span className="badge" style={{ fontSize: '0.75rem' }}>
                سنجنده: {layerData.source_dataset || 'COPERNICUS/S1_GRD'}
              </span>
            </div>
            {(layerData.interpretation_fa || isSarLayerActive) && (
              <p style={{ margin: '4px 0 6px 0', fontSize: '0.88rem', lineHeight: 1.6 }}>
                {isSarLayerActive
                  ? 'سیگنال پس‌پراکنش راداری مایکروویو در قطبش متقاطع؛ نشان‌دهنده ناهمواری سطحی و ساختار حجمی کانوپی گیاهی.'
                  : layerData.interpretation_fa}
              </p>
            )}
            <p className="text-muted" style={{ margin: 0, fontSize: '0.82rem', lineHeight: 1.4 }}>
              {isSarLayerActive
                ? 'Sentinel-1 cross-polarized C-band radar backscatter; indicates volumetric canopy structure and surface roughness.'
                : layerData.interpretation}
            </p>

            {/* Strict Scientific Caution Callout */}
            {(layerData.scientific_caution || isSarLayerActive) && (
              <div
                data-testid="spatial-scientific-caution"
                style={{
                  marginTop: 10,
                  padding: '10px 14px',
                  borderRadius: 6,
                  background: '#fff9c4',
                  border: '1px solid #fbc02d',
                  fontSize: '0.82rem',
                  color: '#5d4037',
                  lineHeight: 1.5,
                }}
              >
                <div style={{ fontWeight: 700, marginBottom: 2 }}>
                  ⚠️ تذکر و احتیاط تفسیری (Scientific Caution & Non-Claim Boundaries):
                </div>
                <div style={{ marginBottom: 4 }}>
                  {isSarLayerActive
                    ? 'این لایه شدت پس‌پراکنش ساختار راداری را منعکس می‌کند و به هیچ عنوان تشخیصی از کمبود کودی، بیماری یا آفت نیست.'
                    : layerData.scientific_caution_fa}
                </div>
                <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                  {isSarLayerActive
                    ? 'Radar backscatter reflects structural canopy volume and roughness; not a chemical or disease diagnosis.'
                    : layerData.scientific_caution}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Heatmap Legend */}
        {layerData && layerData.status === 'available' && (
          <div
            style={{
              marginTop: 14,
              padding: '12px 16px',
              background: 'var(--bg-secondary, #f8f9fa)',
              borderRadius: 8,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                راهنمای لایه — {layerData.concept_name_fa || layerData.display_name} Legend
              </span>
              <span className="badge" style={{ fontSize: '0.8rem' }}>
                واحد: {layerData.unit}
              </span>
            </div>

            {/* Gradient Bar */}
            <div
              style={{
                height: 14,
                borderRadius: 4,
                background: paletteGradient,
                border: '1px solid rgba(0,0,0,0.15)',
                margin: '6px 0',
              }}
            />

            {/* Qualitative or Metric Ticks */}
            {(layerData.qualitative_legend && layerData.qualitative_legend.length > 0) || isSarLayerActive ? (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '0.75rem',
                  color: '#424242',
                  marginTop: 4,
                  flexWrap: 'wrap',
                  gap: 4,
                }}
              >
                {(
                  layerData.qualitative_legend ?? [
                    'پوشش/ناهمواری بسیار کم',
                    'پوشش کم',
                    'پوشش متوسط',
                    'پوشش متراکم',
                  ]
                ).map((step, idx) => (
                  <span key={idx} style={{ fontWeight: 500 }}>
                    {step}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
                <div>
                  <span style={{ fontWeight: 600 }}>{layerData.min_val}</span>{' '}
                  <span className="text-muted">
                    {layerData.unit && `(${layerData.unit}) `}
                    (حداقل / Min)
                  </span>
                </div>
                <div className="text-muted">
                  {((layerData.min_val + layerData.max_val) / 2).toFixed(2)} {layerData.unit}
                </div>
                <div>
                  <span style={{ fontWeight: 600 }}>{layerData.max_val}</span>{' '}
                  <span className="text-muted">
                    {layerData.unit && `(${layerData.unit}) `}
                    (حداکثر / Max)
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Reorganized Spatial Coverage & Deep Technical Telemetry */}
        {layerData && (
          <div style={{ marginTop: 16 }}>
            {/* 1. Spatial Coverage Summary */}
            <div className="card mb-2" style={{ padding: '12px 14px', background: 'var(--bg-secondary, #fafafa)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontWeight: 700, fontSize: '0.88rem' }}>
                  🗺️ پوشش و تفکیک مکانی — Spatial Coverage
                </span>
                <span className={`badge ${layerData.status === 'available' ? 'badge-good' : 'badge-danger'}`} style={{ fontSize: '0.72rem' }}>
                  {layerData.status === 'available' ? '🟢 پوشش مکانی فعال' : '🔴 عدم دسترسی مکانی'}
                </span>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                  gap: 8,
                  fontSize: '0.8rem',
                }}
              >
                <div>
                  <span className="text-muted">تفکیک مکانی: </span>
                  <strong>{layerData.spatial_resolution}</strong>
                </div>
                <div>
                  <span className="text-muted">بازه زمانی: </span>
                  <strong data-testid="spatial-layer-period" title={`${layerData.start_date} → ${layerData.end_date}`}>
                    {formatPersianDateRange(layerData.start_date, layerData.end_date)}
                  </strong>
                </div>
                <div>
                  <span className="text-muted">هندسه بررسی: </span>
                  <strong>{layerData.geometry_type ?? 'ناحیه انتخابی'}</strong>
                </div>
              </div>

              {/* Coarse Resolution Alert */}
              {layerData.native_resolution_m >= 1000 && (
                <div
                  style={{
                    marginTop: 8,
                    padding: '6px 10px',
                    borderRadius: 4,
                    background: '#fff8e1',
                    border: '1px solid #ffe082',
                    fontSize: '0.78rem',
                    color: '#795548',
                  }}
                >
                  ⚠️ <strong>تذکر تفکیک مکانی:</strong> وضوح سنسور <strong>{layerData.spatial_resolution}</strong> است؛ برای تصمیم‌گیری‌های خرد مزرعه‌ای باید تفکیک مکانی سنسور در نظر گرفته شود.
                </div>
              )}
            </div>

            {/* 2. Deeper Technical Details (Collapsible Progressive Disclosure) */}
            <div>
              <button
                type="button"
                className="button button-sm button-outline"
                style={{ fontSize: '0.76rem', display: 'flex', alignItems: 'center', gap: 4 }}
                onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
                aria-expanded={showTechnicalDetails}
              >
                <span>⚙️ {showTechnicalDetails ? 'بستن جزئیات فنی شواهد مکانی' : 'نمایش جزئیات فنی شواهد مکانی'}</span>
                <span>{showTechnicalDetails ? '▲' : '▼'}</span>
              </button>

              {showTechnicalDetails && (
                <div
                  className="card mt-2"
                  style={{
                    padding: '12px 14px',
                    background: 'var(--bg-secondary, #f8f9fa)',
                    border: '1px dashed var(--border-color, #ccc)',
                  }}
                  data-testid="spatial-technical-details"
                >
                  <div className="text-muted" style={{ fontSize: '0.76rem', fontWeight: 600, marginBottom: 8 }}>
                    مشخصات فنی و تلمتری لایه رستری (Technical Telemetry):
                  </div>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                      gap: 8,
                      fontSize: '0.78rem',
                    }}
                  >
                    <div>
                      <span className="text-muted">شناسه دیتاست سنجنده: </span>
                      <code style={{ fontSize: '0.74rem' }}>{layerData.source_dataset}</code>
                    </div>
                    <div>
                      <span className="text-muted">تفکیک بومی سلول‌ها: </span>
                      <strong>{layerData.native_resolution_m} متر</strong>
                    </div>
                    <div>
                      <span className="text-muted">مساحت محدوده محاسباتی: </span>
                      <strong>
                        {((layerData.support_area_sq_m ?? 0) / 1e6).toFixed(3)} کیلومتر مربع ({layerData.support_area_sq_m?.toLocaleString() ?? 0} m²)
                      </strong>
                    </div>
                    {layerData.support_radius_m && (
                      <div>
                        <span className="text-muted">شعاع پشتیبان نقطه: </span>
                        <strong>{layerData.support_radius_m} متر</strong>
                      </div>
                    )}
                  </div>

                  {layerData.limitations.length > 0 && (
                    <div style={{ marginTop: 8, borderTop: '1px solid #e0e0e0', paddingTop: 6 }}>
                      <div className="text-muted" style={{ fontSize: '0.74rem', marginBottom: 2 }}>
                        محدودیت‌های فنی گزارش‌شده توسط سرور:
                      </div>
                      {layerData.limitations.map((note, idx) => (
                        <div key={idx} style={{ fontSize: '0.74rem', color: '#616161' }}>
                          ℹ️ {note}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
