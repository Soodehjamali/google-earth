import { useState, useMemo } from 'react';
import type { AgriculturalAnalysisResponse, EvidenceItemResponse } from '../../types/index.ts';

import {
  RAW_BANDS_CATALOG,
  type SensorFamily,
} from './rawBandsCatalog.ts';

const SENSOR_TABS: { id: SensorFamily; labelFa: string; labelEn: string; icon: string }[] = [
  { id: 'all', labelFa: 'همه باندها و حسگرها', labelEn: 'All Sources', icon: '🌐' },
  { id: 'sentinel2', labelFa: 'سنتینل-۲ (MSI)', labelEn: 'Sentinel-2', icon: '🛰️' },
  { id: 'landsat8', labelFa: 'لندست ۸ (OLI/TIRS)', labelEn: 'Landsat 8', icon: '🛰️' },
  { id: 'sentinel1', labelFa: 'سنتینل-۱ (SAR رادار)', labelEn: 'Sentinel-1 SAR', icon: '📡' },
  { id: 'modis', labelFa: 'مودیس (MODIS)', labelEn: 'MODIS Suites', icon: '🌍' },
  { id: 'dynamicworld', labelFa: 'داینامیک ورد (DW)', labelEn: 'Dynamic World', icon: '🌱' },
  { id: 'smap', labelFa: 'رطوبت‌سنج SMAP', labelEn: 'NASA SMAP', icon: '💧' },
  { id: 'era5', labelFa: 'هواشناسی ERA5-Land', labelEn: 'ERA5-Land', icon: '🌦️' },
  { id: 'soilgrids', labelFa: 'پروفایل خاک SoilGrids', labelEn: 'SoilGrids 2.0', icon: '🏜️' },
  { id: 'dem', labelFa: 'ارتفاع‌سنجی DEM', labelEn: 'SRTM / DEM', icon: '🏔️' },
];

interface RawBandsInspectionSectionProps {
  result: AgriculturalAnalysisResponse;
}

export default function RawBandsInspectionSection({ result }: RawBandsInspectionSectionProps) {
  const [selectedSensor, setSelectedSensor] = useState<SensorFamily>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Extract any live values observed in current response
  const liveValuesMap = useMemo(() => {
    const map = new Map<string, { value: number | string; unit?: string; status: string }>();

    // Check evidence bundles
    if (result.evidence_bundles) {
      Object.values(result.evidence_bundles).forEach((bundle) => {
        bundle.items?.forEach((item: EvidenceItemResponse) => {
          if (item.value !== null && item.value !== undefined) {
            map.set(item.metric_key, {
              value: item.value,
              unit: item.unit,
              status: item.status,
            });
          }
          if (item.band_means) {
            Object.entries(item.band_means).forEach(([bandKey, val]) => {
              if (val !== null && val !== undefined) {
                map.set(bandKey, {
                  value: val,
                  unit: 'fraction (0–1)',
                  status: 'observed',
                });
              }
            });
          }
        });
      });
    }

    // Check soil intelligence if attached
    if (result.soil_intelligence) {
      const si = result.soil_intelligence;
      if (si.moisture?.surface?.value !== null && si.moisture?.surface?.value !== undefined) {
        map.set('surface_soil_moisture', {
          value: si.moisture.surface.value,
          unit: si.moisture.surface.unit || 'm³/m³',
          status: 'observed',
        });
      }
      if (si.moisture?.rootzone?.value !== null && si.moisture?.rootzone?.value !== undefined) {
        map.set('rootzone_soil_moisture', {
          value: si.moisture.rootzone.value,
          unit: si.moisture.rootzone.unit || 'm³/m³',
          status: 'observed',
        });
      }
      if (si.properties) {
        const props = si.properties;
        if (props.soc?.root_zone_value !== null && props.soc?.root_zone_value !== undefined) {
          map.set('soc', {
            value: props.soc.root_zone_value,
            unit: props.soc.unit || 'g/kg',
            status: 'observed',
          });
        }
        if (props.phh2o?.root_zone_value !== null && props.phh2o?.root_zone_value !== undefined) {
          map.set('phh2o', {
            value: props.phh2o.root_zone_value,
            unit: 'pH',
            status: 'observed',
          });
        }
        if (props.sand?.root_zone_value !== null && props.sand?.root_zone_value !== undefined) {
          map.set('sand', {
            value: props.sand.root_zone_value,
            unit: '%',
            status: 'observed',
          });
        }
        if (props.clay?.root_zone_value !== null && props.clay?.root_zone_value !== undefined) {
          map.set('clay', {
            value: props.clay.root_zone_value,
            unit: '%',
            status: 'observed',
          });
        }
        if (props.nitrogen?.root_zone_value !== null && props.nitrogen?.root_zone_value !== undefined) {
          map.set('nitrogen', {
            value: props.nitrogen.root_zone_value,
            unit: props.nitrogen.unit || 'g/kg',
            status: 'observed',
          });
        }
      }
    }

    return map;
  }, [result]);

  const filteredBands = useMemo(() => {
    return RAW_BANDS_CATALOG.filter((band) => {
      const matchSensor = selectedSensor === 'all' || band.sensorId === selectedSensor;
      if (!matchSensor) return false;

      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase().trim();
      return (
        band.key.toLowerCase().includes(q) ||
        band.nameEn.toLowerCase().includes(q) ||
        band.nameFa.includes(q) ||
        band.sensorNameEn.toLowerCase().includes(q) ||
        band.derivedUsageEn.toLowerCase().includes(q) ||
        (band.wavelength && band.wavelength.toLowerCase().includes(q))
      );
    });
  }, [selectedSensor, searchQuery]);

  return (
    <div className="card mb-4" style={{ marginTop: 20 }} data-testid="raw-bands-inspection-section">
      <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span className="card-title" style={{ fontSize: '0.95rem', fontWeight: 700 }}>
            🛰️ کاوشگر باندهای خام ماهواره‌ای و منابع فنی — Satellite Raw Bands & Source Technical Inspection
          </span>
          <div className="text-muted" style={{ fontSize: '0.78rem', marginTop: 2 }}>
            فهرست کامل و مستقل باندهای خام طیفی، فرکانسی و شبکه‌ای سنجنده‌های متصل به موتور پردازش
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span className="badge badge-info" style={{ fontSize: '0.75rem' }}>
            {RAW_BANDS_CATALOG.length} باند خام در کاتالوگ
          </span>
          <span className="badge badge-good" style={{ fontSize: '0.75rem' }}>
            ۹ خانواده سنجنده واقعی
          </span>
        </div>
      </div>

      <div className="card-body">
        {/* Sensor Filter Pills */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            marginBottom: 14,
            paddingBottom: 10,
            borderBottom: '1px solid var(--color-border)',
          }}
        >
          {SENSOR_TABS.map((tab) => {
            const count =
              tab.id === 'all'
                ? RAW_BANDS_CATALOG.length
                : RAW_BANDS_CATALOG.filter((b) => b.sensorId === tab.id).length;
            const isActive = selectedSensor === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setSelectedSensor(tab.id)}
                className={`button button-sm ${isActive ? 'button-primary' : 'button-outline'}`}
                style={{
                  fontSize: '0.78rem',
                  padding: '4px 10px',
                  borderRadius: 16,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <span>{tab.icon}</span>
                <span>{tab.labelFa}</span>
                <span
                  style={{
                    fontSize: '0.7rem',
                    opacity: 0.8,
                    backgroundColor: isActive ? 'rgba(255,255,255,0.2)' : 'var(--color-bg-subtle, rgba(0,0,0,0.06))',
                    padding: '1px 5px',
                    borderRadius: 10,
                  }}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Search Bar */}
        <div style={{ marginBottom: 14, display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="جستجو بر اساس نام باند، کد باند (مثلاً B8، ST_B10، VH)، طول موج یا شاخص مرتبط..."
              className="form-control"
              style={{
                fontSize: '0.82rem',
                padding: '6px 12px',
                width: '100%',
                borderRadius: 6,
              }}
            />
          </div>
          {searchQuery && (
            <button
              type="button"
              className="button button-sm button-outline"
              onClick={() => setSearchQuery('')}
              style={{ fontSize: '0.75rem' }}
            >
              پاک‌کردن
            </button>
          )}
          <span className="text-muted" style={{ fontSize: '0.78rem', whiteSpace: 'nowrap' }}>
            نمایش {filteredBands.length} از {RAW_BANDS_CATALOG.length}
          </span>
        </div>

        {/* Bands Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 12,
          }}
        >
          {filteredBands.map((band) => {
            const live = liveValuesMap.get(band.key) || liveValuesMap.get(band.key.toLowerCase());
            return (
              <div
                key={band.key}
                style={{
                  border: '1px solid var(--color-border)',
                  borderRadius: 8,
                  padding: 12,
                  backgroundColor: 'var(--color-bg-card, #ffffff)',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                }}
              >
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <code
                          style={{
                            fontWeight: 700,
                            fontSize: '0.85rem',
                            color: 'var(--color-primary, #0d9488)',
                            backgroundColor: 'var(--color-bg-subtle, #f0fdfa)',
                            padding: '1px 6px',
                            borderRadius: 4,
                          }}
                        >
                          {band.key}
                        </code>
                        <strong style={{ fontSize: '0.88rem' }}>{band.nameFa}</strong>
                      </div>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: 2 }}>
                        {band.nameEn} {band.wavelength ? `(${band.wavelength})` : ''}
                      </div>
                    </div>
                    <span
                      className="badge"
                      style={{
                        fontSize: '0.7rem',
                        backgroundColor:
                          band.category === 'optical'
                            ? '#e0f2fe'
                            : band.category === 'thermal'
                            ? '#ffedd5'
                            : band.category === 'radar'
                            ? '#f3e8ff'
                            : band.category === 'soil'
                            ? '#fef3c7'
                            : '#ecfdf5',
                        color:
                          band.category === 'optical'
                            ? '#0369a1'
                            : band.category === 'thermal'
                            ? '#c2410c'
                            : band.category === 'radar'
                            ? '#7e22ce'
                            : band.category === 'soil'
                            ? '#b45309'
                            : '#047857',
                      }}
                    >
                      {band.spatialResolution}
                    </span>
                  </div>

                  {/* Metadata Specs Table */}
                  <div
                    style={{
                      fontSize: '0.76rem',
                      display: 'grid',
                      gridTemplateColumns: '1fr',
                      gap: 4,
                      marginTop: 8,
                      padding: '6px 8px',
                      backgroundColor: 'var(--color-bg-subtle, #f9fafb)',
                      borderRadius: 6,
                    }}
                  >
                    <div>
                      <span className="text-muted">منبع سنجنده:</span>{' '}
                      <span style={{ fontWeight: 600 }}>{band.sensorNameFa}</span>
                    </div>
                    <div style={{ wordBreak: 'break-all' }}>
                      <span className="text-muted">شناسه دیتاست:</span>{' '}
                      <code style={{ fontSize: '0.72rem' }}>{band.datasetId}</code>
                    </div>
                    <div>
                      <span className="text-muted">واحد فیزیکی:</span>{' '}
                      <span>{band.physicalUnit}</span>
                    </div>
                    <div>
                      <span className="text-muted">ضریب مقیاس:</span>{' '}
                      <code>{band.scaleFactor}</code>
                    </div>
                  </div>

                  {/* Derived Usage */}
                  <div style={{ marginTop: 8, fontSize: '0.76rem' }}>
                    <div className="text-muted" style={{ fontSize: '0.72rem', fontWeight: 600 }}>
                      کاربرد در شاخص‌ها و محاسبات:
                    </div>
                    <div style={{ color: 'var(--color-text-main, #334155)', marginTop: 2 }}>
                      {band.derivedUsageFa}
                    </div>
                    <div className="text-muted" style={{ fontSize: '0.7rem', marginTop: 1 }} dir="ltr">
                      {band.derivedUsageEn}
                    </div>
                  </div>
                </div>

                {/* Status Bar / Observed Value */}
                <div
                  style={{
                    marginTop: 10,
                    paddingTop: 8,
                    borderTop: '1px dashed var(--color-border)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: '0.75rem',
                  }}
                >
                  <span className="text-muted">وضعیت استخراج در تحلیل جاری:</span>
                  {live ? (
                    <span
                      style={{
                        fontWeight: 700,
                        color: 'var(--color-good, #15803d)',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <span>✓ مقدار:</span>
                      <code>
                        {typeof live.value === 'number'
                          ? live.value.toFixed(4)
                          : String(live.value)}
                      </code>
                      {live.unit && <span style={{ fontSize: '0.7rem' }}>{live.unit}</span>}
                    </span>
                  ) : (
                    <span
                      className="badge badge-neutral"
                      style={{ fontSize: '0.7rem', opacity: 0.85 }}
                      title="این باند خام در خط لوله پردازش متصل است و در فرمول‌های شاخص‌های مربوطه استخراج می‌شود"
                    >
                      آماده استخراج در ترکیب شاخص‌ها
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
