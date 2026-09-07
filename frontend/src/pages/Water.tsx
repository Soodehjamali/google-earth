import { useState } from 'react'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import { analysesApi } from '../api/analyses'
import type { Analysis, MapVisualization } from '../types'

export default function Water() {
  const [latitude, setLatitude] = useState('32.4279')
  const [longitude, setLongitude] = useState('53.6880')
  const [startDate, setStartDate] = useState('2025-06-01')
  const [endDate, setEndDate] = useState('2025-09-01')
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
        analysis_type: 'water',
        temporal_resolution: 'monthly',
      })

      setAnalysis(result)

      const viz = await analysesApi.getMaps(result.id).catch(() => null)
      if (viz) setMapViz(viz)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تحلیل آب')
    } finally {
      setSubmitting(false)
    }
  }

  const resultData = analysis?.result_data as Record<string, unknown> | null
  const waterData = (resultData?.water as Record<string, unknown>) || {}
  const ndwi = (waterData.ndwi as Record<string, number>) || {}
  const soilMoisture = (waterData.soil_moisture as Record<string, number>) || {}
  const precipitation = (waterData.precipitation as Record<string, number>) || {}
  const stressLevel = (waterData.stress_level as string) || 'unknown'

  function getStressStatus(stress: string): 'good' | 'warning' | 'danger' | 'neutral' {
    if (stress === 'low' || stress === 'none') return 'good'
    if (stress === 'moderate') return 'warning'
    if (stress === 'high' || stress === 'severe') return 'danger'
    return 'neutral'
  }

  function getNdwiStatus(val: number | undefined): 'good' | 'warning' | 'danger' | 'neutral' {
    if (val === undefined || val === null) return 'neutral'
    if (val > 0) return 'good'
    if (val > -0.3) return 'warning'
    return 'danger'
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">آب</h2>
        <p className="page-subtitle">Water — NDWI, Soil Moisture, Precipitation Analysis</p>
      </div>

      {/* Quick Analysis Form */}
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">💧 تحلیل آب</span>
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
              <>🔍 تحلیل آب</>
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
              title="NDWI"
              titleFa="شاخص آب"
              value={ndwi.mean}
              icon="💧"
              status={getNdwiStatus(ndwi.mean)}
              subtitle={`Water index`}
            />
            <KPICard
              title="Soil Moisture"
              titleFa="رطوبت خاک"
              value={soilMoisture.mean}
              unit="m³/m³"
              icon="🌊"
              status={soilMoisture.mean !== undefined
                ? soilMoisture.mean > 0.2 ? 'good' : soilMoisture.mean > 0.1 ? 'warning' : 'danger'
                : 'neutral'}
              subtitle={`ERA5-Land (0-7cm)`}
            />
            <KPICard
              title="Precipitation"
              titleFa="بارش"
              value={precipitation.total}
              unit="mm"
              icon="🌧️"
              status={precipitation.total !== undefined
                ? precipitation.total > 30 ? 'good' : precipitation.total > 10 ? 'warning' : 'danger'
                : 'neutral'}
              subtitle={`Total during period`}
            />
            <KPICard
              title="Water Stress"
              titleFa="تنش آبی"
              value={stressLevel}
              icon="⚠️"
              status={getStressStatus(stressLevel)}
              subtitle={`Overall assessment`}
            />
          </div>

          {/* Map */}
          <div className="card mb-3">
            <div className="card-header">
              <span className="card-title">🗺️ نقشه منابع آب</span>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              <MapView
                visualization={mapViz}
                geometry={analysis.result_data?.geometry as GeoJSON.Geometry}
                center={mapViz?.center || [parseFloat(longitude), parseFloat(latitude)]}
                zoom={mapViz?.zoom || 12}
              />
            </div>
          </div>

          {/* Details */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">📊 جزئیات آبی</span>
            </div>
            <div className="card-body">
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>متغیر</th>
                      <th>میانگین</th>
                      <th>حداقل</th>
                      <th>حداکثر</th>
                      <th>واحد</th>
                      <th>منبع</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><strong>NDWI</strong></td>
                      <td>{ndwi.mean?.toFixed(4) ?? '—'}</td>
                      <td>{ndwi.min?.toFixed(4) ?? '—'}</td>
                      <td>{ndwi.max?.toFixed(4) ?? '—'}</td>
                      <td>dimensionless</td>
                      <td>Sentinel-2</td>
                    </tr>
                    <tr>
                      <td><strong>رطوبت خاک</strong></td>
                      <td>{soilMoisture.mean?.toFixed(4) ?? '—'}</td>
                      <td>{soilMoisture.min?.toFixed(4) ?? '—'}</td>
                      <td>{soilMoisture.max?.toFixed(4) ?? '—'}</td>
                      <td>m³/m³</td>
                      <td>ERA5-Land</td>
                    </tr>
                    <tr>
                      <td><strong>بارش</strong></td>
                      <td>{precipitation.total?.toFixed(1) ?? '—'}</td>
                      <td>—</td>
                      <td>—</td>
                      <td>mm</td>
                      <td>ERA5-Land</td>
                    </tr>
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
          <div className="empty-state-icon">💧</div>
          <div className="empty-state-title">تحلیل منابع آب</div>
          <div className="empty-state-desc">
            شاخص آب (NDWI)، رطوبت خاک و بارش با استفاده از Sentinel-2 و ERA5-Land محاسبه می‌شوند.
          </div>
        </div>
      )}
    </div>
  )
}
