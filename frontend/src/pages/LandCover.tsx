import { useState } from 'react'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import { analysesApi } from '../api/analyses'
import ComprehensiveNotice from '../components/ComprehensiveNotice'
import type { Analysis, MapVisualization } from '../types'

const LANDCOVER_CLASSES: Record<string, { label: string; labelFa: string; color: string }> = {
  '1': { label: 'Evergreen Needleleaf Forest', labelFa: 'جنگل سوزنی‌برگ همیشه‌سبز', color: '#1b5e20' },
  '2': { label: 'Evergreen Broadleaf Forest', labelFa: 'جنگل پهن‌برگ همیشه‌سبز', color: '#2e7d32' },
  '3': { label: 'Deciduous Needleleaf Forest', labelFa: 'جنگل سوزنی‌برگ خزان‌دار', color: '#43a047' },
  '4': { label: 'Deciduous Broadleaf Forest', labelFa: 'جنگل پهن‌برگ خزان‌دار', color: '#66bb6a' },
  '5': { label: 'Mixed Forest', labelFa: 'جنگل مختلط', color: '#388e3c' },
  '6': { label: 'Closed Shrublands', labelFa: 'درختچه‌زار متراکم', color: '#795548' },
  '7': { label: 'Open Shrublands', labelFa: 'درختچه‌زار باز', color: '#a1887f' },
  '8': { label: 'Woody Savannas', labelFa: 'ساوانای درختچه‌ای', color: '#689f38' },
  '9': { label: 'Savannas', labelFa: 'ساوانا', color: '#ffeb3b' },
  '10': { label: 'Grasslands', labelFa: 'علفزار و مرتع', color: '#cddc39' },
  '11': { label: 'Permanent Wetlands', labelFa: 'تالاب دائمی', color: '#00acc1' },
  '12': { label: 'Croplands', labelFa: 'زمین کشاورزی زراعی', color: '#4caf50' },
  '13': { label: 'Urban and Built-up Lands', labelFa: 'اراضی ساخته‌شده و شهری', color: '#9e9e9e' },
  '14': { label: 'Cropland/Natural Vegetation Mosaics', labelFa: 'موزاییک زراعت و پوشش طبیعی', color: '#8bc34a' },
  '15': { label: 'Permanent Snow and Ice', labelFa: 'برف و یخ دائمی', color: '#b2ebf2' },
  '16': { label: 'Barren', labelFa: 'اراضی بایر و بیابان', color: '#8d6e63' },
  '17': { label: 'Water Bodies', labelFa: 'پهنه‌های آبی', color: '#2196f3' },
  // Retained for compatibility with Dynamic World (where 0=water) and legacy payloads
  '0': { label: 'Water', labelFa: 'آب', color: '#2196f3' },
  '255': { label: 'Unclassified', labelFa: 'طبقه‌بندی‌نشده', color: '#616161' },
}

export default function LandCover() {
  const [latitude, setLatitude] = useState('32.4279')
  const [longitude, setLongitude] = useState('53.6880')
  const [startDate, setStartDate] = useState('2025-01-01')
  const [endDate, setEndDate] = useState('2025-12-31')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [mapViz, setMapViz] = useState<MapVisualization | undefined>()

  async function handleAnalyze() {
    setError(null)

    const lat = parseFloat(latitude)
    const lng = parseFloat(longitude)

    if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setError('مختصات نامعتبر — Invalid coordinates')
      return
    }

    try {
      setSubmitting(true)
      const geometry: GeoJSON.Geometry = { type: 'Point', coordinates: [lng, lat] }

      const result = await analysesApi.create({
        geometry,
        start_date: startDate,
        end_date: endDate,
        analysis_type: 'landcover',
        temporal_resolution: 'yearly',
      })

      setAnalysis(result)

      const viz = await analysesApi.getMaps(result.id).catch(() => null)
      if (viz) setMapViz(viz)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تحلیل پوشش ارضی')
    } finally {
      setSubmitting(false)
    }
  }

  const resultData = analysis?.result_data as Record<string, unknown> | null
  const landcoverData = (resultData?.landcover as Record<string, unknown>) || {}
  const classes = (landcoverData.classes as Record<string, number>) || {}
  const dominantClass = (landcoverData.dominant_class as string) || 'unknown'
  const totalArea = (landcoverData.total_area_sq_meters as number) || 0

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">پوشش ارضی</h2>
        <p className="page-subtitle">Land Cover — MODIS Classification (500m)</p>
      </div>

      {/* Info Banner */}
      <div className="card mb-3" style={{ borderRightColor: 'var(--color-info)' }}>
        <div className="card-body">
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
            📡 <strong>منبع داده:</strong> MODIS MCD12Q1 (Collection 6.1) — رزولوشن 500 متر — محصول سالانه
          </p>
        </div>
      </div>

      {/* Quick Analysis Form */}
      <ComprehensiveNotice to="/agriculture/land-crop" linkLabelFa="مشاهده تحلیل جامع" linkLabelEn="View comprehensive analysis" />
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">🗺️ تحلیل پوشش ارضی</span>
        </div>
        <div className="card-body">
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">عرض جغرافیایی (Latitude)</label>
              <input
                type="number"
                className="form-input"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
                step="0.0001"
              />
            </div>
            <div className="form-group">
              <label className="form-label">طول جغرافیایی (Longitude)</label>
              <input
                type="number"
                className="form-input"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
                step="0.0001"
              />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">تاریخ شروع</label>
              <input
                type="date"
                className="form-input"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">تاریخ پایان</label>
              <input
                type="date"
                className="form-input"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>

          {error && (
            <div className="error-banner">
              <span>⚠️</span>
              <span>{error}</span>
            </div>
          )}

          <button
            className="btn btn-primary"
            onClick={handleAnalyze}
            disabled={submitting}
          >
            {submitting ? (
              <>
                <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                در حال تحلیل...
              </>
            ) : (
              <>🔍 تحلیل پوشش ارضی</>
            )}
          </button>
        </div>
      </div>

      {/* Results */}
      {analysis && analysis.status === 'completed' && (
        <>
          {/* KPI Cards */}
          <div className="kpi-grid">
            <KPICard
              title="Dominant Class"
              titleFa="کلاس غالب"
              value={LANDCOVER_CLASSES[dominantClass]?.labelFa || dominantClass}
              icon="🗺️"
              status="neutral"
              subtitle={LANDCOVER_CLASSES[dominantClass]?.label || ''}
            />
            <KPICard
              title="Total Area"
              titleFa="مساحت کل"
              value={totalArea > 0 ? (totalArea / 1000000).toFixed(2) : null}
              unit="km²"
              icon="📐"
              status="neutral"
            />
          </div>

          {/* Map + Land Cover Classes */}
          <div className="grid-2">
            <div className="card">
              <div className="card-header">
                <span className="card-title">🗺️ نقشه پوشش ارضی</span>
              </div>
              <div className="card-body" style={{ padding: 0 }}>
                <MapView
                  visualization={mapViz}
                  geometry={analysis.result_data?.geometry as GeoJSON.Geometry}
                  center={mapViz?.center || [parseFloat(longitude), parseFloat(latitude)]}
                  zoom={mapViz?.zoom || 10}
                />
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <span className="card-title">📊 توزیع پوشش ارضی</span>
              </div>
              <div className="card-body">
                {Object.keys(classes).length > 0 ? (
                  <div>
                    {Object.entries(classes)
                      .sort(([, a], [, b]) => (b as number) - (a as number))
                      .map(([classCode, percentage]) => {
                        const classInfo = LANDCOVER_CLASSES[classCode] || {
                          label: `Class ${classCode}`,
                          labelFa: `کلاس ${classCode}`,
                          color: '#9e9e9e',
                        }
                        const pct = (percentage as number)
                        return (
                          <div key={classCode} style={{ marginBottom: 12 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                              <span style={{ fontSize: '0.85rem' }}>
                                <span
                                  style={{
                                    display: 'inline-block',
                                    width: 12,
                                    height: 12,
                                    backgroundColor: classInfo.color,
                                    borderRadius: 2,
                                    marginRight: 8,
                                    verticalAlign: 'middle',
                                  }}
                                />
                                {classInfo.labelFa} ({classInfo.label})
                              </span>
                              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                                {pct.toFixed(1)}%
                              </span>
                            </div>
                            <div style={{ width: '100%', height: 8, backgroundColor: '#e0e0e0', borderRadius: 4 }}>
                              <div
                                style={{
                                  width: `${pct}%`,
                                  height: '100%',
                                  backgroundColor: classInfo.color,
                                  borderRadius: 4,
                                }}
                              />
                            </div>
                          </div>
                        )
                      })}
                  </div>
                ) : (
                  <div className="empty-state" style={{ padding: 20 }}>
                    <p>داده پوشش ارضی موجود نیست</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Details Table */}
          <div className="card mt-3">
            <div className="card-header">
              <span className="card-title">📋 جزئیات</span>
            </div>
            <div className="card-body">
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>کلاس</th>
                      <th>نام فارسی</th>
                      <th>نام انگلیسی</th>
                      <th>درصد</th>
                      <th>مساحت (km²)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(classes)
                      .sort(([, a], [, b]) => (b as number) - (a as number))
                      .map(([classCode, percentage]) => {
                        const classInfo = LANDCOVER_CLASSES[classCode] || {
                          label: `Class ${classCode}`,
                          labelFa: `کلاس ${classCode}`,
                          color: '#9e9e9e',
                        }
                        const pct = percentage as number
                        const areaKm2 = totalArea > 0 ? (totalArea * pct / 100 / 1000000).toFixed(2) : '—'
                        return (
                          <tr key={classCode}>
                            <td>
                              <span
                                style={{
                                  display: 'inline-block',
                                  width: 12,
                                  height: 12,
                                  backgroundColor: classInfo.color,
                                  borderRadius: 2,
                                  marginRight: 6,
                                  verticalAlign: 'middle',
                                }}
                              />
                              {classCode}
                            </td>
                            <td>{classInfo.labelFa}</td>
                            <td>{classInfo.label}</td>
                            <td>{pct.toFixed(1)}%</td>
                            <td>{areaKm2}</td>
                          </tr>
                        )
                      })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Empty state */}
      {!analysis && !submitting && (
        <div className="empty-state">
          <div className="empty-state-icon">🗺️</div>
          <div className="empty-state-title">تحلیل پوشش ارضی</div>
          <div className="empty-state-desc">
            پوشش ارضی با استفاده از محصول MODIS MCD12Q1 با رزولوشن 500 متر و بازه زمانی سالانه طبقه‌بندی می‌شود.
          </div>
        </div>
      )}
    </div>
  )
}
