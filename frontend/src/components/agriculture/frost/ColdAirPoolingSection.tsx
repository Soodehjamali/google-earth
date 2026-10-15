import React, { useState } from 'react';
import type { ColdAirPoolingResponse } from '../../../types';
import FormattedNumber from '../../common/FormattedNumber';
import MapView from '../../MapView';

interface ColdAirPoolingSectionProps {
  pooling: ColdAirPoolingResponse;
  geometry?: Record<string, any>;
}

export const ColdAirPoolingSection: React.FC<ColdAirPoolingSectionProps> = ({
  pooling,
  geometry,
}) => {
  const [showMap, setShowMap] = useState<boolean>(false);

  const colorRamp = pooling.color_ramp || [
    '#f7fcf0',
    '#bae4bc',
    '#7bccc4',
    '#43a2ca',
    '#0868ac',
  ];

  return (
    <div className="card mb-3" data-testid="cold-air-pooling-section">
      <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="card-title">⛰️ ارزیابی توپوگرافی تجمع هوای سرد (Cold-Air-Pooling Proxy)</span>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => setShowMap(!showMap)}
          data-testid="toggle-pooling-map-btn"
        >
          {showMap ? 'بستن نقشه رستری ✕' : 'مشاهده نقشه رستری NASADEM 🗺️'}
        </button>
      </div>

      <div className="card-body">
        {/* KPI Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: '12px',
            marginBottom: '16px',
          }}
        >
          <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
            <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
              شاخص تجمع هوای سرد (پراکسی)
            </div>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#0369a1' }}>
              <FormattedNumber value={pooling.pooling_risk_proxy} digits={3} />
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
              وضعیت: <strong>{pooling.risk_label_fa}</strong>
            </div>
          </div>

          <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
            <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
              تراز ارتفاعی مزرعه (NASADEM)
            </div>
            <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>
              <FormattedNumber value={pooling.site_elevation_m} unit="m" />
            </div>
          </div>

          <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
            <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
              اختلاف ارتفاع محلی (Relief)
            </div>
            <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>
              <FormattedNumber value={pooling.relief_m} unit="m" />
            </div>
          </div>

          <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
            <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
              کف حوضه / کمینه تراز
            </div>
            <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>
              <FormattedNumber value={pooling.min_elevation_m} unit="m" />
            </div>
          </div>

          <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
            <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
              میانگین شیب موضعی
            </div>
            <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>
              <FormattedNumber value={pooling.mean_slope_deg} unit="°" digits={1} />
            </div>
          </div>
        </div>

        {/* Heuristic Proxy Scientific Disclaimer */}
        <div
          style={{
            backgroundColor: '#eff6ff',
            border: '1px solid #bfdbfe',
            borderRadius: '6px',
            padding: '10px 14px',
            fontSize: '0.82rem',
            color: '#1e40af',
            marginBottom: '16px',
          }}
          data-testid="pooling-disclaimer"
        >
          <strong>سلب ادعای علمی:</strong>{' '}
          {pooling.disclaimer_fa ||
            'شاخص تجمع هوای سرد صرفاً یک برآورد تقریبی توپوگرافی بر پایه مدل رقومی ارتفاعی (DEM) است و شبیه‌سازی دینامیکی جریان هوا محسوب نمی‌شود.'}
        </div>

        {/* Optional Map View */}
        {showMap && (
          <div style={{ marginTop: '16px' }} data-testid="pooling-map-container">
            <div style={{ height: '380px', borderRadius: '8px', overflow: 'hidden', border: '1px solid #cbd5e1', marginBottom: '12px' }}>
              <MapView
                geometry={geometry as GeoJSON.Geometry | undefined}
                rasterTileUrl={pooling.tile_url}
                rasterOpacity={0.8}
              />
            </div>

            {/* Color Ramp Legend */}
            <div
              style={{
                backgroundColor: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                padding: '10px 14px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#334155' }}>
                راهنمای رنگی پهنه‌بندی شاخص تجمع هوای سرد (Cold-Air-Pooling Ramp):
              </div>
              <div style={{ display: 'flex', alignItems: 'center', height: '14px', borderRadius: '4px', overflow: 'hidden' }}>
                {colorRamp.map((color, cIdx) => (
                  <div key={cIdx} style={{ flex: 1, height: '100%', backgroundColor: color }} />
                ))}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#64748b' }}>
                <span>۰.۰ (فراز و خط‌الراس / تخلیه سریع)</span>
                <span>۰.۲۵ (شیب میانی)</span>
                <span>۰.۵۰ (دشت هموار)</span>
                <span>۰.۷۵ (پای شیب)</span>
                <span>۱.۰ (گودی بسته / تجمع حاد سردی)</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ColdAirPoolingSection;
