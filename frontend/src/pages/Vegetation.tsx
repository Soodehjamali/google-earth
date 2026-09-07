import { useState } from 'react'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import NDVIChart from '../components/NDVIChart'
import { analysesApi } from '../api/analyses'
import type { Analysis, MapVisualization, TimeSeriesPoint } from '../types'

export default function Vegetation() {
  // Quick analysis form
  const [latitude, setLatitude] = useState('32.4279')
  const [longitude, setLongitude] = useState('53.6880')
  const [startDate, setStartDate] = useState('2025-06-01')
  const [endDate, setEndDate] = useState('2025-09-01')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Results
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [mapViz, setMapViz] = useState<MapVisualization | undefined>()
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesPoint[]>([])

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
        analysis_type: 'vegetation',
        temporal_resolution: 'monthly',
      })

      setAnalysis(result)

      // Load map and timeseries
      const [viz, ts] = await Promise.allSettled([
        analysesApi.getMaps(result.id),
        analysesApi.getTimeSeries(result.id),
      ])
      if (viz.status === 'fulfilled') setMapViz(viz.value)
      if (ts.status === 'fulfilled') setTimeSeriesData(ts.value.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تحلیل پوشش گیاهی')
    } finally {
      setSubmitting(false)
    }
  }

  const resultData = analysis?.result_data as Record<string, unknown> | null
  const stats = (resultData?.statistics as Record<string, Record<string, number>>) || {}
  const ndviStats = stats.NDVI || {}
  const eviStats = stats.EVI || {}
  const saviStats = stats.SAVI || {}
  const ndwiStats = stats.NDWI || {}
  const vegetationHealth = (resultData?.vegetation_health as string) || 'unknown'
  const interpretation = (resultData?.interpretation as string) || ''

  function getHealthStatus(health: string): 'good' | 'warning' | 'danger' | 'neutral' {
    if (health === 'excellent' || health === 'good') return 'good'
    if (health === 'moderate') return 'warning'
    if (health === 'poor' || health === 'bare') return 'danger'
    return 'neutral'
  }

  function getValStatus(val: number | undefined): 'good' | 'warning' | 'danger' | 'neutral' {
    if (val === undefined || val === null) return 'neutral'
    if (val > 0.4) return 'good'
    if (val > 0.2) return 'warning'
    return 'danger'
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">پوشش گیاهی</h2>
        <p className="page-subtitle">Vegetation — NDVI, EVI, SAVI, NDWI Analysis</p>
      </div>

      {/* Quick Analysis Form */}
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">🌿 تحلیل سریع پوشش گیاهی</span>
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
              <>🔍 تحلیل پوشش گیاهی</>
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
              title="NDVI"
              titleFa="شاخص سبزینگی"
              value={ndviStats.mean}
              icon="🌿"
              status={getValStatus(ndviStats.mean)}
              subtitle={`Min: ${ndviStats.min?.toFixed(3) ?? '—'} | Max: ${ndviStats.max?.toFixed(3) ?? '—'}`}
            />
            <KPICard
              title="Health"
              titleFa="سلامت"
              value={vegetationHealth}
              icon="🌱"
              status={getHealthStatus(vegetationHealth)}
            />
            <KPICard
              title="EVI"
              titleFa="شاخص بهبودیافته"
              value={eviStats.mean}
              icon="📊"
              status={getValStatus(eviStats.mean)}
            />
            <KPICard
              title="SAVI"
              titleFa="شاخص خاک"
              value={saviStats.mean}
              icon="🌾"
              status={getValStatus(saviStats.mean)}
            />
            <KPICard
              title="NDWI"
              titleFa="شاخص آب"
              value={ndwiStats.mean}
              icon="💧"
              status={ndwiStats.mean !== undefined && ndwiStats.mean !== null
                ? ndwiStats.mean > 0 ? 'good' : 'warning'
                : 'neutral'}
            />
          </div>

          {/* Interpretation */}
          {interpretation && (
            <div className="card mb-3">
              <div className="card-header">
                <span className="card-title">📝 تفسیر</span>
              </div>
              <div className="card-body">
                <p style={{ fontSize: '0.9rem', lineHeight: 1.8 }}>{interpretation}</p>
              </div>
            </div>
          )}

          {/* Map + Chart */}
          <div className="grid-2">
            <div className="card">
              <div className="card-header">
                <span className="card-title">🗺️ نقشه پوشش گیاهی</span>
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

            <NDVIChart data={timeSeriesData} title="روند شاخص‌های پوشش گیاهی" />
          </div>

          {/* Detailed Stats */}
          <div className="card mt-3">
            <div className="card-header">
              <span className="card-title">📊 آمار تفصیلی</span>
            </div>
            <div className="card-body">
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>شاخص</th>
                      <th>میانگین</th>
                      <th>میانه</th>
                      <th>حداقل</th>
                      <th>حداکثر</th>
                      <th>انحراف معیار</th>
                      <th>P10</th>
                      <th>P25</th>
                      <th>P75</th>
                      <th>P90</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(stats).map(([name, s]) => (
                      <tr key={name}>
                        <td><strong>{name}</strong></td>
                        <td>{s.mean?.toFixed(4) ?? '—'}</td>
                        <td>{s.median?.toFixed(4) ?? '—'}</td>
                        <td>{s.min?.toFixed(4) ?? '—'}</td>
                        <td>{s.max?.toFixed(4) ?? '—'}</td>
                        <td>{s.std?.toFixed(4) ?? '—'}</td>
                        <td>{s.percentile_10?.toFixed(4) ?? '—'}</td>
                        <td>{s.percentile_25?.toFixed(4) ?? '—'}</td>
                        <td>{s.percentile_75?.toFixed(4) ?? '—'}</td>
                        <td>{s.percentile_90?.toFixed(4) ?? '—'}</td>
                      </tr>
                    ))}
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
          <div className="empty-state-icon">🌿</div>
          <div className="empty-state-title">تحلیل پوشش گیاهی</div>
          <div className="empty-state-desc">
            مختصات مکان و بازه زمانی را وارد کنید تا شاخص‌های NDVI، EVI، SAVI و NDWI محاسبه شوند.
          </div>
        </div>
      )}
    </div>
  )
}
