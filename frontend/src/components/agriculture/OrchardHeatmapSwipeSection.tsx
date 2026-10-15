import { useEffect, useRef, useState, useCallback } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { agricultureApi } from '../../api/agriculture';
import type {
  AgricultureGeometry,
  SpatialLayerResponse,
  SpatialMetricType,
} from '../../types';
import { formatPersianDateRange } from './persianDate';

interface OrchardHeatmapSwipeSectionProps {
  geometry: GeoJSON.Geometry | AgricultureGeometry | null;
  startDate: string;
  endDate: string;
  cloudMaxPercent?: number;
  initialMetric?: SpatialMetricType;
  allowedMetrics?: SpatialMetricType[];
  title?: string;
  titleFa?: string;
  disableAutoFetch?: boolean;
}

interface HeatmapOption {
  key: SpatialMetricType;
  label: string;
  labelFa: string;
  icon: string;
  resolution: string;
  datasetName: string;
  unit: string;
}

const HEATMAP_OPTIONS: HeatmapOption[] = [
  {
    key: 'ndvi',
    label: 'NDVI (Vegetation Index)',
    labelFa: 'شاخص پوشش گیاهی (NDVI)',
    icon: '🌿',
    resolution: '10 m',
    datasetName: 'Sentinel-2 Harmonized',
    unit: 'index',
  },
  {
    key: 'ndmi',
    label: 'NDMI (Canopy Moisture)',
    labelFa: 'رطوبت کانوپی (NDMI)',
    icon: '💧',
    resolution: '20 m',
    datasetName: 'Sentinel-2 Harmonized',
    unit: 'index',
  },
  {
    key: 'ndre',
    label: 'NDRE (Red Edge Chlorophyll)',
    labelFa: 'کلروفیل لبه قرمز (NDRE)',
    icon: '🍃',
    resolution: '20 m',
    datasetName: 'Sentinel-2 Harmonized',
    unit: 'index',
  },
  {
    key: 'msi',
    label: 'MSI (Moisture Stress Ratio)',
    labelFa: 'شاخص تنش رطوبتی (MSI)',
    icon: '🍂',
    resolution: '20 m',
    datasetName: 'Sentinel-2 Harmonized',
    unit: 'index',
  },
  {
    key: 'lst_day',
    label: 'LST Day (Surface Temperature)',
    labelFa: 'دمای روزانه سطح زمین (LST)',
    icon: '🌡️',
    resolution: '1000 m (1 km)',
    datasetName: 'MODIS MOD11A2',
    unit: '°C',
  },
  {
    key: 'sar_vh',
    label: 'Sentinel-1 SAR Radar (VH)',
    labelFa: 'پراکندگی راداری سنتینل-۱ (VH)',
    icon: '📡',
    resolution: '10 m',
    datasetName: 'Sentinel-1 GRD IW',
    unit: 'dB',
  },
  {
    key: 'soil_moisture',
    label: 'Root-Zone Soil Moisture (0–100 cm)',
    labelFa: 'رطوبت خاک ناحیه ریشه',
    icon: '💧',
    resolution: '11 km (ERA5-Land)',
    datasetName: 'ECMWF ERA5-Land',
    unit: 'm³/m³',
  },
  {
    key: 'soil_soc',
    label: 'Soil Organic Carbon (SOC)',
    labelFa: 'کربن آلی خاک (SOC)',
    icon: '🌱',
    resolution: '250 m',
    datasetName: 'ISRIC SoilGrids 2.0',
    unit: 'g/kg',
  },
  {
    key: 'soil_ph',
    label: 'Soil pH in H2O',
    labelFa: 'اسیدیته خاک (pH)',
    icon: '🧪',
    resolution: '250 m',
    datasetName: 'ISRIC SoilGrids 2.0',
    unit: 'pH',
  },
  {
    key: 'soil_clay',
    label: 'Clay Content (%)',
    labelFa: 'درصد رس خاک (Clay)',
    icon: '🧱',
    resolution: '250 m',
    datasetName: 'ISRIC SoilGrids 2.0',
    unit: '%',
  },
  {
    key: 'soil_sand',
    label: 'Sand Content (%)',
    labelFa: 'درصد شن و ماسه خاک (Sand)',
    icon: '🏖️',
    resolution: '250 m',
    datasetName: 'ISRIC SoilGrids 2.0',
    unit: '%',
  },
  {
    key: 'soil_cec',
    label: 'Cation Exchange Capacity (CEC)',
    labelFa: 'ظرفیت تبادل کاتیونی (CEC)',
    icon: '⚡',
    resolution: '250 m',
    datasetName: 'ISRIC SoilGrids 2.0',
    unit: 'cmol/kg',
  },
  {
    key: 'soil_nitrogen',
    label: 'Total Nitrogen (N)',
    labelFa: 'نیتروژن کل خاک (N)',
    icon: '🌿',
    resolution: '250 m',
    datasetName: 'ISRIC SoilGrids 2.0',
    unit: 'g/kg',
  },
];

export default function OrchardHeatmapSwipeSection({
  geometry,
  startDate,
  endDate,
  cloudMaxPercent = 20,
  initialMetric = 'ndvi',
  allowedMetrics,
  title = 'Current Orchard ↔ Evidence Heatmap Swipe',
  titleFa = 'مقایسه کشویی: تصویر جاری باغ ↔ نقشه حرارتی ماهواره‌ای',
  disableAutoFetch = false,
}: OrchardHeatmapSwipeSectionProps) {
  // Divider position percentage (0 = 100% Heatmap, 100 = 100% Orchard Image)
  const [dividerPercent, setDividerPercent] = useState<number>(50);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [userRequested, setUserRequested] = useState<boolean>(!disableAutoFetch);

  // Heatmap layer selection
  const [selectedMetric, setSelectedMetric] = useState<SpatialMetricType>(initialMetric);
  const [layerData, setLayerData] = useState<SpatialLayerResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [mapsReady, setMapsReady] = useState<boolean>(false);

  // DOM Container references
  const containerRef = useRef<HTMLDivElement>(null);
  const leftMapContainer = useRef<HTMLDivElement>(null);
  const rightMapContainer = useRef<HTMLDivElement>(null);

  // MapLibre instances
  const mapLeft = useRef<maplibregl.Map | null>(null);
  const mapRight = useRef<maplibregl.Map | null>(null);

  // Filter available heatmap options if allowedMetrics specified
  const availableOptions = allowedMetrics
    ? HEATMAP_OPTIONS.filter((opt) => allowedMetrics.includes(opt.key))
    : HEATMAP_OPTIONS;

  // Fetch real Earth Engine spatial raster layer
  useEffect(() => {
    if (!userRequested) return;
    if (!geometry || !startDate || !endDate) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    agricultureApi
      .getSpatialLayer({
        metric: selectedMetric,
        geometry,
        start_date: startDate,
        end_date: endDate,
        cloud_max_percent: cloudMaxPercent,
      })
      .then((data) => {
        if (!isMounted) return;
        setLayerData(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        console.error('Failed to load spatial raster layer:', err);
        setError(err instanceof Error ? err.message : 'Error fetching spatial layer');
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [userRequested, geometry, startDate, endDate, selectedMetric, cloudMaxPercent]);

  // Extract center coordinates from geometry
  const initialCenter = useCallback((): [number, number] => {
    if (!geometry) return [53.688, 32.428];
    const geom = geometry as GeoJSON.Geometry;
    if (geom.type === 'Point') {
      const pt = geom as GeoJSON.Point;
      return [pt.coordinates[0], pt.coordinates[1]];
    } else if (geom.type === 'Polygon') {
      const poly = geom as GeoJSON.Polygon;
      const ring = poly.coordinates[0];
      if (ring && ring.length > 0) {
        const lons = ring.map((p) => p[0]);
        const lats = ring.map((p) => p[1]);
        return [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2];
      }
    }
    return [53.688, 32.428];
  }, [geometry]);

  // Helper to add or update field boundary geometry overlay
  const syncGeometryOverlay = useCallback(
    (m: maplibregl.Map, prefix: string) => {
      if (!geometry) return;
      const srcId = `${prefix}-geom-src`;
      const feature: GeoJSON.Feature = {
        type: 'Feature',
        geometry: geometry as GeoJSON.Geometry,
        properties: {},
      };

      const existingSrc = m.getSource(srcId) as maplibregl.GeoJSONSource | undefined;
      if (existingSrc) {
        existingSrc.setData(feature);
        return;
      }

      try {
        m.addSource(srcId, {
          type: 'geojson',
          data: feature,
        });

        if (geometry.type === 'Polygon') {
          m.addLayer({
            id: `${prefix}-geom-outline`,
            type: 'line',
            source: srcId,
            paint: {
              'line-color': '#ffff00',
              'line-width': 2.5,
            },
          });
        } else if (geometry.type === 'Point') {
          m.addLayer({
            id: `${prefix}-geom-point`,
            type: 'circle',
            source: srcId,
            paint: {
              'circle-radius': 7,
              'circle-color': '#ffff00',
              'circle-stroke-width': 2,
              'circle-stroke-color': '#000000',
            },
          });
        }
      } catch {
        // layer/source already exists or style not ready
      }
    },
    [geometry]
  );

  // Initialize both maps
  useEffect(() => {
    if (!userRequested) return;
    if (!leftMapContainer.current || !rightMapContainer.current) return;
    if (mapLeft.current && mapRight.current) return;

    const center = initialCenter();
    const zoom = geometry?.type === 'Point' ? 12 : 13;

    // 1. Initialize Map Left (Current Orchard Image: Real Satellite + OSM Foundation Base)
    const mapA = new maplibregl.Map({
      container: leftMapContainer.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
          satellite: {
            type: 'raster',
            tiles: [
              'https://mt0.google.com/vt/lyrs=s&hl=fa&x={x}&y={y}&z={z}',
              'https://mt1.google.com/vt/lyrs=s&hl=fa&x={x}&y={y}&z={z}',
            ],
            tileSize: 256,
            maxzoom: 19,
            attribution: '© Google Satellite',
          },
        },
        layers: [
          {
            id: 'osm-base',
            type: 'raster',
            source: 'osm',
            paint: { 'raster-opacity': 1.0 },
          },
          {
            id: 'satellite-base',
            type: 'raster',
            source: 'satellite',
            paint: { 'raster-opacity': 1.0 },
          },
        ],
      },
      center,
      zoom,
    });

    mapA.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-left');
    mapA.addControl(new maplibregl.ScaleControl({ maxWidth: 150, unit: 'metric' }), 'bottom-left');

    // 2. Initialize Map Right (Evidence Heatmap Layer with OSM & Satellite Underlays)
    const mapB = new maplibregl.Map({
      container: rightMapContainer.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
          },
          satellite: {
            type: 'raster',
            tiles: [
              'https://mt0.google.com/vt/lyrs=s&hl=fa&x={x}&y={y}&z={z}',
              'https://mt1.google.com/vt/lyrs=s&hl=fa&x={x}&y={y}&z={z}',
            ],
            tileSize: 256,
            maxzoom: 19,
            attribution: '© Google Satellite',
          },
        },
        layers: [
          {
            id: 'osm-underlay',
            type: 'raster',
            source: 'osm',
            paint: { 'raster-opacity': 1.0 },
          },
          {
            id: 'satellite-underlay',
            type: 'raster',
            source: 'satellite',
            paint: { 'raster-opacity': 0.85 },
          },
        ],
      },
      center,
      zoom,
      interactive: false, // Follows Map A synchronously
    });

    // 3. Synchronize Map B movement with Map A
    const syncMovement = () => {
      mapB.jumpTo({
        center: mapA.getCenter(),
        zoom: mapA.getZoom(),
        bearing: mapA.getBearing(),
        pitch: mapA.getPitch(),
      });
    };

    mapA.on('move', syncMovement);

    mapA.on('load', () => syncGeometryOverlay(mapA, 'left'));
    mapB.on('load', () => {
      syncGeometryOverlay(mapB, 'right');
      if (layerDataRef.current) {
        applyHeatmapTiles(mapB, layerDataRef.current);
      }
    });

    mapLeft.current = mapA;
    mapRight.current = mapB;
    setMapsReady(true);

    // Attach ResizeObserver to keep maps synchronized on layout changes
    let resizeObserver: ResizeObserver | null = null;
    if (containerRef.current) {
      resizeObserver = new ResizeObserver(() => {
        mapA.resize();
        mapB.resize();
      });
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      if (resizeObserver) resizeObserver.disconnect();
      setMapsReady(false);
      mapA.remove();
      mapB.remove();
      mapLeft.current = null;
      mapRight.current = null;
    };
  }, [userRequested, disableAutoFetch, initialCenter, syncGeometryOverlay]);

  // Keep ref to layerData for map event callbacks
  const layerDataRef = useRef<SpatialLayerResponse | null>(layerData);
  layerDataRef.current = layerData;

  // Dedicated tile applicator for Map B
  const applyHeatmapTiles = useCallback(
    (mB: maplibregl.Map | null, data: SpatialLayerResponse | null) => {
      if (!mB) return;

      let executed = false;
      const run = () => {
        if (executed) return;
        try {
          if (mB.getLayer('ee-heatmap-layer')) mB.removeLayer('ee-heatmap-layer');
          if (mB.getSource('ee-heatmap-source')) mB.removeSource('ee-heatmap-source');
        } catch {
          // ignore
        }

        if (!data || data.status !== 'available' || !data.tile_url_template) {
          executed = true;
          mB.triggerRepaint();
          return;
        }

        try {
          mB.addSource('ee-heatmap-source', {
            type: 'raster',
            tiles: [data.tile_url_template!],
            tileSize: 256,
            ...(data.bounds && data.bounds.length === 4
              ? { bounds: data.bounds as [number, number, number, number] }
              : {}),
          });

          const beforeId = mB.getLayer('right-geom-outline')
            ? 'right-geom-outline'
            : mB.getLayer('right-geom-point')
              ? 'right-geom-point'
              : undefined;

          mB.addLayer(
            {
              id: 'ee-heatmap-layer',
              type: 'raster',
              source: 'ee-heatmap-source',
              paint: {
                'raster-opacity': 0.9,
              },
            },
            beforeId
          );
          executed = true;
          mB.off('load', run);
          mB.off('styledata', run);
          mB.off('idle', run);
          if (mapLeft.current) {
            mB.jumpTo({
              center: mapLeft.current.getCenter(),
              zoom: mapLeft.current.getZoom(),
              bearing: mapLeft.current.getBearing(),
              pitch: mapLeft.current.getPitch(),
            });
          } else {
            mB.jumpTo({
              center: mB.getCenter(),
              zoom: mB.getZoom(),
            });
          }
          mB.triggerRepaint();
        } catch (err) {
          console.warn('[OrchardHeatmapSwipeSection] Failed to add EE heatmap layer to swipe map:', err);
        }
      };

      run();
      if (!executed) {
        mB.once('load', run);
        mB.once('styledata', run);
        mB.once('idle', run);
      }
    },
    []
  );

  // Update Heatmap raster tiles on Map B when layerData or mapsReady updates
  useEffect(() => {
    if (mapRight.current) {
      applyHeatmapTiles(mapRight.current, layerData);
    }
  }, [layerData, mapsReady, applyHeatmapTiles]);

  // Sync geometry and fit bounds when geometry or mapsReady update
  useEffect(() => {
    const mA = mapLeft.current;
    const mB = mapRight.current;
    if (mA) syncGeometryOverlay(mA, 'left');
    if (mB) syncGeometryOverlay(mB, 'right');

    if (!mA || !geometry) return;

    try {
      if (geometry.type === 'Polygon') {
        const poly = geometry as GeoJSON.Polygon;
        if (poly.coordinates && poly.coordinates[0] && poly.coordinates[0].length > 0) {
          const b = new maplibregl.LngLatBounds();
          poly.coordinates[0].forEach((pt) => b.extend(pt as [number, number]));
          mA.fitBounds(b, { padding: 40, maxZoom: 14.5, animate: false });
        }
      }
    } catch {
      // ignore
    }
  }, [geometry, mapsReady, syncGeometryOverlay]);

  // Mouse & Touch Drag handling for the swipe divider
  const handleDragStart = useCallback((e?: React.MouseEvent | React.TouchEvent) => {
    if (e && 'preventDefault' in e) {
      e.stopPropagation();
    }
    setIsDragging(true);
  }, []);

  const handleResetDivider = useCallback(() => {
    setDividerPercent(50);
  }, []);

  const updateDividerPos = useCallback((clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(100, (x / rect.width) * 100));
    setDividerPercent(pct);
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const onMouseMove = (e: MouseEvent) => {
      updateDividerPos(e.clientX);
    };

    const onTouchMove = (e: TouchEvent) => {
      if (e.touches && e.touches[0]) {
        updateDividerPos(e.touches[0].clientX);
      }
    };

    const onDragEnd = () => {
      setIsDragging(false);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onDragEnd);
    window.addEventListener('touchmove', onTouchMove);
    window.addEventListener('touchend', onDragEnd);

    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onDragEnd);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onDragEnd);
    };
  }, [isDragging, updateDividerPos]);

  if (!geometry) return null;

  if (disableAutoFetch && !userRequested && !layerData) {
    return (
      <div className="card mb-4" data-testid="orchard-heatmap-swipe-ondemand-card">
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
              🔎 {titleFa}
            </span>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 2 }}>
              {title}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            onClick={() => setUserRequested(true)}
          >
            🛰️ بارگذاری مقایسه کشویی ماهواره‌ای (GEE)
          </button>
        </div>
        <div className="card-body text-muted" style={{ fontSize: '0.82rem' }}>
          در مرور گزارش ذخیره‌شده، لایه‌های رستری مقایسه کشویی جهت تسریع ناوبری و کاهش بار پردازشی به صورت خودکار بارگذاری نمی‌شوند. برای مشاهده نقشه حرارتی، دکمه بالا را فشار دهید.
        </div>
      </div>
    );
  }

  const activeOption =
    availableOptions.find((opt) => opt.key === selectedMetric) ??
    availableOptions[0] ??
    HEATMAP_OPTIONS[0];

  // Palette gradient CSS
  const paletteGradient =
    layerData?.palette && layerData.palette.length > 0
      ? `linear-gradient(to right, ${layerData.palette.join(', ')})`
      : 'linear-gradient(to right, #d7191c, #fdae61, #ffffbf, #a6d96a, #1a9641)';

  return (
    <div className="card mb-4" data-testid="orchard-heatmap-swipe-section">
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
            🔎 {titleFa}
          </span>
          <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 2 }}>
            {title}
          </div>
        </div>

        {/* Reset Divider Button */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            type="button"
            className="btn btn-outline"
            style={{ fontSize: '0.78rem', padding: '4px 10px', borderRadius: 6 }}
            onClick={handleResetDivider}
            title="بازنشانی خط برش به ۵۰٪"
          >
            🔄 تنظیم مجدد (۵۰٪)
          </button>
          {/* Real Synchronization Status Badge */}
          {loading && (
            <span
              className="badge"
              data-testid="swipe-sync-status"
              style={{ fontSize: '0.75rem', padding: '4px 8px', background: '#2563eb', color: '#fff' }}
            >
              ⏳ در حال استعلام GEE...
            </span>
          )}
          {!loading && error && (
            <span
              className="badge badge-danger"
              data-testid="swipe-sync-status"
              style={{ fontSize: '0.75rem', padding: '4px 8px', background: '#dc2626', color: '#fff' }}
            >
              ⚠️ خطای دریافت لایه
            </span>
          )}
          {!loading && !error && layerData?.status === 'unavailable' && (
            <span
              className="badge badge-warning"
              data-testid="swipe-sync-status"
              style={{ fontSize: '0.75rem', padding: '4px 8px', background: '#d97706', color: '#fff' }}
            >
              ⚠️ لایه در این بازه در دسترس نیست
            </span>
          )}
          {!loading && !error && layerData?.status === 'available' && (
            <span
              className="badge badge-good"
              data-testid="swipe-sync-status"
              style={{ fontSize: '0.75rem', padding: '4px 8px' }}
            >
              ✓ Real GEE Synchronized
            </span>
          )}
        </div>
      </div>

      <div className="card-body">
        {/* Layer Selector */}
        <div style={{ marginBottom: 14 }}>
          <div className="text-muted" style={{ fontSize: '0.82rem', marginBottom: 6 }}>
            انتخاب لایه شواهد ماهواره‌ای — Select Evidence Heatmap Layer:
          </div>
          <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
            {availableOptions.map((opt) => {
              const isActive = selectedMetric === opt.key;
              return (
                <button
                  key={opt.key}
                  type="button"
                  data-testid={`swipe-metric-btn-${opt.key}`}
                  className={`btn ${isActive ? 'btn-primary' : 'btn-outline'}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '5px 12px',
                    fontSize: '0.82rem',
                    borderRadius: 6,
                  }}
                  onClick={() => setSelectedMetric(opt.key)}
                >
                  <span>{opt.icon}</span>
                  <span style={{ fontWeight: isActive ? 600 : 400 }}>{opt.labelFa}</span>
                  <span className="badge" style={{ fontSize: '0.68rem', padding: '1px 5px' }}>
                    {opt.resolution}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Swipe Map Wrapper */}
        <div
          ref={containerRef}
          style={{
            position: 'relative',
            height: 460,
            borderRadius: 8,
            overflow: 'hidden',
            border: '2px solid var(--border-color, #e0e0e0)',
            userSelect: isDragging ? 'none' : 'auto',
          }}
        >
          {/* Map Left: Current Orchard (Base Satellite) */}
          <div
            ref={leftMapContainer}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
            }}
          />

          {/* Map Right: Heatmap (Clipped based on divider percentage) */}
          <div
            ref={rightMapContainer}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              pointerEvents: 'none',
              clipPath: `inset(0 0 0 ${dividerPercent}%)`,
              WebkitClipPath: `inset(0 0 0 ${dividerPercent}%)`,
            }}
          />

          {/* Draggable Vertical Divider Bar & Handle */}
          <div
            data-testid="swipe-divider-handle"
            role="slider"
            aria-valuenow={Math.round(dividerPercent)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Current orchard vs heatmap swipe divider"
            tabIndex={0}
            onMouseDown={handleDragStart}
            onTouchStart={handleDragStart}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft') setDividerPercent((p) => Math.max(0, p - 5));
              if (e.key === 'ArrowRight') setDividerPercent((p) => Math.min(100, p + 5));
            }}
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: `${dividerPercent}%`,
              width: 4,
              marginLeft: -2,
              background: '#ffffff',
              boxShadow: '0 0 8px rgba(0,0,0,0.65)',
              cursor: 'ew-resize',
              zIndex: 30,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {/* Center Thumb Handle */}
            <div
              style={{
                width: 42,
                height: 42,
                borderRadius: '50%',
                background: '#ffffff',
                border: '2px solid #1565c0',
                boxShadow: '0 2px 10px rgba(0,0,0,0.4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#1565c0',
                fontSize: '0.85rem',
                fontWeight: 'bold',
                cursor: 'ew-resize',
                userSelect: 'none',
              }}
            >
              ◄►
            </div>
          </div>

          {/* Top Floating Side Badges */}
          <div
            style={{
              position: 'absolute',
              top: 10,
              left: 55,
              background: 'rgba(0, 0, 0, 0.75)',
              color: '#ffffff',
              padding: '5px 10px',
              borderRadius: 6,
              fontSize: '0.76rem',
              fontWeight: 600,
              zIndex: 25,
              pointerEvents: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>🌳 تصویر جاری باغ (طبیعی)</span>
            <span style={{ opacity: 0.7, fontSize: '0.7rem' }}>
              ({Math.round(dividerPercent)}%)
            </span>
          </div>

          <div
            style={{
              position: 'absolute',
              top: 10,
              right: 12,
              background: 'rgba(0, 0, 0, 0.75)',
              color: '#ffffff',
              padding: '5px 10px',
              borderRadius: 6,
              fontSize: '0.76rem',
              fontWeight: 600,
              zIndex: 25,
              pointerEvents: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>🔥 نقشه حرارتی {activeOption.labelFa}</span>
            <span style={{ opacity: 0.7, fontSize: '0.7rem' }}>
              ({Math.round(100 - dividerPercent)}%)
            </span>
          </div>

          {/* Loading Indicator */}
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
                zIndex: 35,
              }}
            >
              <div className="spinner" style={{ width: 36, height: 36 }} />
              <div style={{ marginTop: 10, fontWeight: 600, fontSize: '0.88rem' }}>
                در حال دریافت کاشی‌های نقشه حرارتی {activeOption.labelFa}...
              </div>
              <div className="text-muted" style={{ fontSize: '0.78rem' }}>
                Querying Google Earth Engine raster tiles
              </div>
            </div>
          )}

          {/* In-map unavailable watermark on heatmap side */}
          {layerData && layerData.status === 'unavailable' && (
            <div
              data-testid="swipe-heatmap-unavailable-pill"
              style={{
                position: 'absolute',
                bottom: 12,
                right: 12,
                zIndex: 25,
                background: 'rgba(254, 242, 242, 0.95)',
                border: '1px solid #f87171',
                borderRadius: 6,
                padding: '6px 12px',
                color: '#991b1b',
                fontSize: '0.78rem',
                boxShadow: '0 2px 6px rgba(0,0,0,0.18)',
                pointerEvents: 'none',
              }}
            >
              ⚠️ <strong>نقشه حرارتی {activeOption.labelFa} ناموجود است:</strong>{' '}
              {layerData.unavailable_reason || 'پوشش تصویری سنجنده برای این محدوده در دسترس نیست.'}
            </div>
          )}
        </div>

        {/* Unavailable or Error Banner */}
        {error && (
          <div className="alert alert-danger" style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 600 }}>خطا در بارگذاری نقشه حرارتی — Unable to load heatmap</div>
            <div style={{ fontSize: '0.85rem' }}>{error}</div>
          </div>
        )}

        {layerData && layerData.status === 'unavailable' && (
          <div className="alert alert-warning" style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 600 }}>
              نقشه حرارتی برای این شاخص در دسترس نیست — Heatmap unavailable for this indicator
            </div>
            <div style={{ fontSize: '0.85rem' }}>
              {layerData.unavailable_reason ?? 'No matching satellite coverage available for this geometry.'}
            </div>
          </div>
        )}

        {/* Heatmap Legend & Metadata Section */}
        {layerData && layerData.status === 'available' && (
          <div
            className="card"
            style={{
              marginTop: 14,
              padding: '12px 16px',
              background: 'var(--bg-secondary, #fafafa)',
              border: '1px solid #e0e0e0',
              borderRadius: 8,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 12,
              }}
            >
              {/* Legend title and date */}
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>
                  {activeOption.icon} راهنمای طیف رنگی: {layerData.display_name}
                </div>
                <div className="text-muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>
                  دوره: {formatPersianDateRange(layerData.start_date, layerData.end_date)} ({layerData.source_dataset} · {layerData.spatial_resolution})
                </div>
              </div>

              {/* Color Bar */}
              <div style={{ minWidth: 260, maxWidth: 380, flex: 1 }}>
                <div
                  style={{
                    height: 14,
                    borderRadius: 7,
                    background: paletteGradient,
                    boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.2)',
                  }}
                />
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '0.75rem',
                    color: '#666',
                    marginTop: 4,
                  }}
                >
                  <span>
                    کمترین: {layerData.min_val} {layerData.unit}
                  </span>
                  <span>
                    بیشترین: {layerData.max_val} {layerData.unit}
                  </span>
                </div>
              </div>
            </div>

            {/* Scientific Caution */}
            <div
              className="text-muted"
              style={{
                fontSize: '0.78rem',
                marginTop: 10,
                borderTop: '1px dashed #e0e0e0',
                paddingTop: 8,
                lineHeight: 1.5,
              }}
            >
              ⚠️ <strong>یادداشت علمی:</strong> مقایسه مکانی نشان‌دهنده تفاوت نسبی سیگنال رویشی یا دمایی در پهنه باغ است و به‌تنهایی تشخیص بیماری، نوع آفت یا کمبود عنصری را اثبات نمی‌کند.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
