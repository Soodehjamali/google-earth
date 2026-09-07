import { useState } from 'react'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import { analysesApi } from '../api/analyses'
import type { Analysis, MapVisualization } from '../types'

export default function Soil() {
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
        analysis_type: 'soil',
        temporal_resolution: 'monthly',
      })

      setAnalysis(result)

      const viz = await analysesApi.getMaps(result.id).catch(() => null)
      if (viz) setMapViz(viz)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تحلیل خاک')
    } finally {
      setSubmitting(false)
    }
  }

  const resultData = analysis?.result_data as Record<string, unknown> | null
  const soilData = (resultData?.soil as Record<string, unknown>) || {}
  const soilMoisture = (soilData.soil_moisture as Record<string, number>) || {}
  const organicCarbon = (soilData.organic_carbon as Record<string, number>) || {}
  const texture = (soilData.texture as Record<string, string>) || {}
  const ph = (soilData.ph as Record<string, number>) || {}

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">خاک</h2>
        <p className="page-subtitle">Soil — Moisture, Organic Carbon, Texture, pH</p>
      </div>

      {/* Info Banner */}
      <div className="card mb-3" style={{ borderRightColor: 'var(--color-info)' }}>
        <div className="card-body">
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
            ⚠️ <strong>توجه:</strong> ویژگی‌های خاک از داده‌های مدل‌سازی شده (ERA5-Land و SoilGrids) استخراج می‌شوند و جایگزین اندازه‌گیری‌های میدانی نیستند.
          </p>
        </div>
      </div>

      {/* Quick Analysis Form */}
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">🌍 تحلیل خاک</span>
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
              <>🔍 تحلیل خاک</>
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
              title="Soil Moisture"
              titleFa="رطوبت خاک"
              value={soilMoisture.mean}
              unit="m³/m³"
              icon="🌊"
              status={soilMoisture.mean !== undefined
                ? soilMoisture.mean > 0.2 ? 'good' : soilMoisture.mean > 0.1 ? 'warning' : 'danger'
                : 'neutral'}
              subtitle={`Modeled (ERA5-Land)`}
            />
            <KPICard
              title="Organic Carbon"
              titleFa="کربن آلی"
              value={organicCarbon.mean}
              unit="g/kg"
              icon="🌱"
              status={organicCarbon.mean !== undefined
                ? organicCarbon.mean > 15 ? 'good' : organicCarbon.mean > 5 ? 'warning' : 'danger'
                : 'neutral'}
              subtitle={`Modeled (SoilGrids)`}
            />
            <KPICard
              title="pH"
              titleFa="اسیدیته"
              value={ph.mean}
              icon="🧪"
              status={ph.mean !== undefined
                ? (ph.mean >= 6.5 && ph.mean <= 7.5) ? 'good' : (ph.mean >= 5.5 && ph.mean <= 8.0) ? 'warning' : 'danger'
                : 'neutral'}
              subtitle={`Modeled (SoilGrids)`}
            />
            <KPICard
              title="Texture"
              titleFa="بافت خاک"
              value={texture.class || 'unknown'}
              icon="🪨"
              status="neutral"
              subtitle={texture.description || 'Modeled estimate'}
            />
          </div>

          {/* Map */}
          <div className="card mb-3">
            <div className="card-header">
              <span className="card-title">🗺️ نقشه خاک</span>
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

          {/* Soil Properties Table */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">📊 خواص خاک</span>
            </div>
            <div className="card-body">
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>ویژگی</th>
                      <th>مقدار</th>
                      <th>واحد</th>
                      <th>منبع</th>
                      <th>نوع داده</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><strong>رطوبت خاک</strong></td>
                      <td>{soilMoisture.mean?.toFixed(4) ?? '—'}</td>
                      <td>m³/m³</td>
                      <td>ERA5-Land</td>
                      <td>Modeled</td>
                    </tr>
                    <tr>
                      <td><strong>کربن آلی</strong></td>
                      <td>{organicCarbon.mean?.toFixed(1) ?? '—'}</td>
                      <td>g/kg</td>
                      <td>SoilGrids</td>
                      <td>Modeled</td>
                    </tr>
                    <tr>
                      <td><strong>اسیدیته (pH)</strong></td>
                      <td>{ph.mean?.toFixed(2) ?? '—'}</td>
                      <td>pH</td>
                      <td>SoilGrids</td>
                      <td>Modeled</td>
                    </tr>
                    <tr>
                      <td><strong>بافت</strong></td>
                      <td>{texture.class ?? '—'}</td>
                      <td>—</td>
                      <td>SoilGrids</td>
                      <td>Modeled</td>
                    </tr>
                    <tr>
                      <td><strong>شن (Sand)</strong></td>
                      <td>{(soilData.sand as number)?.toFixed(1) ?? '—'}</td>
                      <td>%</td>
                      <td>SoilGrids</td>
                      <td>Modeled</td>
                    </tr>
                    <tr>
                      <td><strong>رس (Clay)</strong></td>
                      <td>{(soilData.clay as number)?.toFixed(1) ?? '—'}</td>
                      <td>%</td>
                      <td>SoilGrids</td>
                      <td>Modeled</td>
                    </tr>
                    <tr>
                      <td><strong>لوم (Silt)</strong></td>
                      <td>{(soilData.silt as number)?.toFixed(1) ?? '—'}</td>
                      <td>%</td>
                      <td>SoilGrids</td>
                      <td>Modeled</td>
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
          <div className="empty-state-icon">🌍</div>
          <div className="empty-state-title">تحلیل خاک</div>
          <div className="empty-state-desc">
            ویژگی‌های خاک شامل رطوبت، کربن آلی، بافت و اسیدیته با استفاده از ERA5-Land و SoilGrids محاسبه می‌شوند.
            <br />
            <em style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
              توجه: این داده‌ها مدل‌سازی شده هستند و جایگزین اندازه‌گیری‌های آزمایشگاهی نیستند.
            </em>
          </div>
        </div>
      )}
    </div>
  )
}
