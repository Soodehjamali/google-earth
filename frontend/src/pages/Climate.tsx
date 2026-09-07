import { useState } from 'react'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { analysesApi } from '../api/analyses'
import type { Analysis, MapVisualization, TimeSeriesPoint } from '../types'

export default function Climate() {
  const [latitude, setLatitude] = useState('32.4279')
  const [longitude, setLongitude] = useState('53.6880')
  const [startDate, setStartDate] = useState('2025-01-01')
  const [endDate, setEndDate] = useState('2025-09-01')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
        analysis_type: 'climate',
        temporal_resolution: 'monthly',
      })

      setAnalysis(result)

      const [viz, ts] = await Promise.allSettled([
        analysesApi.getMaps(result.id),
        analysesApi.getTimeSeries(result.id),
      ])
      if (viz.status === 'fulfilled') setMapViz(viz.value)
      if (ts.status === 'fulfilled') setTimeSeriesData(ts.value.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تحلیل اقلیم')
    } finally {
      setSubmitting(false)
    }
  }

  const resultData = analysis?.result_data as Record<string, unknown> | null
  const climateData = (resultData?.climate as Record<string, unknown>) || {}
  const temperature = (climateData.temperature as Record<string, number>) || {}
  const precipitation = (climateData.precipitation as Record<string, number>) || {}
  const evapotranspiration = (climateData.evapotranspiration as Record<string, number>) || {}

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">اقلیم</h2>
        <p className="page-subtitle">Climate — Temperature, Precipitation, Evapotranspiration</p>
      </div>

      {/* Quick Analysis Form */}
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">🌤️ تحلیل اقلیم</span>
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
              <>🔍 تحلیل اقلیم</>
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
              title="Mean Temperature"
              titleFa="دمای میانگین"
              value={temperature.mean}
              unit="°C"
              icon="🌡️"
              status={temperature.mean !== undefined
                ? temperature.mean > 35 ? 'danger' : temperature.mean > 25 ? 'warning' : 'good'
                : 'neutral'}
              subtitle={`Min: ${temperature.min?.toFixed(1) ?? '—'} | Max: ${temperature.max?.toFixed(1) ?? '—'}`}
            />
            <KPICard
              title="Total Precipitation"
              titleFa="بارش کل"
              value={precipitation.total}
              unit="mm"
              icon="🌧️"
              status={precipitation.total !== undefined
                ? precipitation.total < 10 ? 'danger' : precipitation.total < 30 ? 'warning' : 'good'
                : 'neutral'}
              subtitle={`Monthly average`}
            />
            <KPICard
              title="Evapotranspiration"
              titleFa="تبخیر-تعرق"
              value={evapotranspiration.total}
              unit="mm"
              icon="💧"
              status="neutral"
              subtitle={`Reference ET (ERA5)`}
            />
            <KPICard
              title="Data Source"
              titleFa="منبع داده"
              value="ERA5-Land"
              icon="📡"
              status="neutral"
              subtitle={`~11km resolution`}
            />
          </div>

          {/* Map + Charts */}
          <div className="grid-2">
            <div className="card">
              <div className="card-header">
                <span className="card-title">🗺️ نقشه</span>
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

            {/* Temperature Chart */}
            <div className="chart-container">
              <h3 className="chart-title">دمای هوا (Temperature)</h3>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={timeSeriesData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                  <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'rgba(255, 255, 255, 0.95)',
                      border: '1px solid #ddd',
                      borderRadius: '8px',
                    }}
                    formatter={(value: number, name: string) => [value?.toFixed(1), name]}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="temperature"
                    stroke="#e53935"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    name="دما (°C)"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Precipitation Chart */}
          <div className="chart-container mt-3">
            <h3 className="chart-title">بارش (Precipitation)</h3>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={timeSeriesData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(255, 255, 255, 0.95)',
                    border: '1px solid #ddd',
                    borderRadius: '8px',
                  }}
                  formatter={(value: number, name: string) => [value?.toFixed(1), name]}
                />
                <Bar dataKey="precipitation" fill="#1976d2" name="بارش (mm)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {/* Empty state */}
      {!analysis && !submitting && (
        <div className="empty-state">
          <div className="empty-state-icon">🌤️</div>
          <div className="empty-state-title">تحلیل اقلیم</div>
          <div className="empty-state-desc">
            دما، بارش و تبخیر-تعرق با استفاده از داده‌های ERA5-Land محاسبه می‌شوند.
          </div>
        </div>
      )}
    </div>
  )
}
