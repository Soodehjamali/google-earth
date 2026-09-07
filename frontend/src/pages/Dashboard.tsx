import { useState, useEffect } from 'react'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import NDVIChart from '../components/NDVIChart'
import EarthEngineIndicator from '../components/EarthEngineIndicator'
import { analysesApi } from '../api/analyses'
import type { Analysis, MapVisualization, TimeSeriesPoint } from '../types'

export default function Dashboard() {
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [selectedAnalysis, setSelectedAnalysis] = useState<Analysis | null>(null)
  const [mapViz, setMapViz] = useState<MapVisualization | undefined>()
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadAnalyses()
  }, [])

  useEffect(() => {
    if (selectedAnalysis?.id) {
      loadAnalysisData(selectedAnalysis.id)
    }
  }, [selectedAnalysis])

  async function loadAnalyses() {
    try {
      setLoading(true)
      const data = await analysesApi.list(0, 10)
      setAnalyses(data)
      if (data.length > 0) {
        // Load the most recent completed analysis
        const completed = data.find((a) => a.status === 'completed')
        if (completed) {
          const full = await analysesApi.get(completed.id)
          setSelectedAnalysis(full)
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری تحلیل‌ها')
    } finally {
      setLoading(false)
    }
  }

  async function loadAnalysisData(analysisId: string) {
    try {
      const [viz, ts] = await Promise.allSettled([
        analysesApi.getMaps(analysisId),
        analysesApi.getTimeSeries(analysisId),
      ])

      if (viz.status === 'fulfilled') setMapViz(viz.value)
      if (ts.status === 'fulfilled') setTimeSeriesData(ts.value.data)
    } catch {
      // Silently handle — map/charts will show empty state
    }
  }

  // Extract KPI values from analysis result_data
  const resultData = selectedAnalysis?.result_data as Record<string, unknown> | null
  const stats = (resultData?.statistics as Record<string, Record<string, number>>) || {}
  const ndviStats = stats.NDVI || {}
  const eviStats = stats.EVI || {}
  const ndwiStats = stats.NDWI || {}
  const vegetationHealth = (resultData?.vegetation_health as string) || 'unknown'
  const imageCount = (resultData?.image_count as number) || 0
  const dataQuality = (resultData?.data_quality as string) || 'unknown'

  function getHealthStatus(health: string): 'good' | 'warning' | 'danger' | 'neutral' {
    if (health === 'excellent' || health === 'good') return 'good'
    if (health === 'moderate') return 'warning'
    if (health === 'poor' || health === 'bare') return 'danger'
    return 'neutral'
  }

  function getNDVIStatus(mean: number | undefined): 'good' | 'warning' | 'danger' | 'neutral' {
    if (mean === undefined || mean === null) return 'neutral'
    if (mean > 0.4) return 'good'
    if (mean > 0.2) return 'warning'
    return 'danger'
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">داشبورد</h2>
        <p className="page-subtitle">Dashboard — Agricultural Intelligence Overview</p>
      </div>

      {/* Earth Engine connection indicator */}
      <EarthEngineIndicator />

      {error && (
        <div className="error-banner">
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      )}

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <span>در حال بارگذاری...</span>
        </div>
      )}

      {!loading && analyses.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">🌾</div>
          <div className="empty-state-title">هیچ تحلیلی یافت نشد</div>
          <div className="empty-state-desc">
            برای شروع، یک مکان جدید ایجاد کنید و تحلیل را آغاز کنید.
          </div>
        </div>
      )}

      {!loading && selectedAnalysis && (
        <>
          {/* Map */}
          <div className="card mb-3">
            <div className="card-header">
              <span className="card-title">🗺️ نقشه تحلیل</span>
              <span className="badge badge-info">
                {selectedAnalysis.analysis_type}
              </span>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              <MapView
                visualization={mapViz}
                geometry={
                  (resultData?.geometry as GeoJSON.Geometry) || undefined
                }
                center={mapViz?.center || [55.0, 32.0]}
                zoom={mapViz?.zoom || 6}
              />
            </div>
          </div>

          {/* KPI Cards */}
          <div className="kpi-grid">
            <KPICard
              title="NDVI"
              titleFa="شاخص سبزینگی"
              value={ndviStats.mean}
              unit=""
              icon="🌿"
              status={getNDVIStatus(ndviStats.mean)}
              subtitle={`Min: ${ndviStats.min?.toFixed(3) ?? '—'} | Max: ${ndviStats.max?.toFixed(3) ?? '—'}`}
            />

            <KPICard
              title="Vegetation Health"
              titleFa="سلامت پوشش گیاهی"
              value={vegetationHealth}
              icon="🌱"
              status={getHealthStatus(vegetationHealth)}
              subtitle={`Dataset: Sentinel-2 SR`}
            />

            <KPICard
              title="EVI"
              titleFa="شاخص بهبودیافته"
              value={eviStats.mean}
              unit=""
              icon="📊"
              status={getNDVIStatus(eviStats.mean)}
              subtitle={`Min: ${eviStats.min?.toFixed(3) ?? '—'} | Max: ${eviStats.max?.toFixed(3) ?? '—'}`}
            />

            <KPICard
              title="NDWI"
              titleFa="شاخص آب"
              value={ndwiStats.mean}
              unit=""
              icon="💧"
              status={ndwiStats.mean !== undefined && ndwiStats.mean !== null
                ? ndwiStats.mean > 0 ? 'good' : 'warning'
                : 'neutral'}
              subtitle={`Water index`}
            />

            <KPICard
              title="Images"
              titleFa="تصاویر ماهواره‌ای"
              value={imageCount}
              unit="scenes"
              icon="🛰️"
              status="neutral"
              subtitle={`Quality: ${dataQuality}`}
            />

            <KPICard
              title="Data Quality"
              titleFa="کیفیت داده"
              value={dataQuality}
              icon="📋"
              status={dataQuality === 'good' ? 'good' : dataQuality === 'acceptable' ? 'warning' : 'danger'}
              subtitle={`Period: ${selectedAnalysis.start_date} → ${selectedAnalysis.end_date}`}
            />
          </div>

          {/* Chart */}
          <div className="grid-2">
            <NDVIChart data={timeSeriesData} />

            <div className="card">
              <div className="card-header">
                <span className="card-title">📈 اطلاعات تحلیل</span>
              </div>
              <div className="card-body">
                <table>
                  <tbody>
                    <tr>
                      <th>نوع تحلیل</th>
                      <td>{selectedAnalysis.analysis_type}</td>
                    </tr>
                    <tr>
                      <th>تاریخ شروع</th>
                      <td>{selectedAnalysis.start_date}</td>
                    </tr>
                    <tr>
                      <th>تاریخ پایان</th>
                      <td>{selectedAnalysis.end_date}</td>
                    </tr>
                    <tr>
                      <th>وضعیت</th>
                      <td>
                        <span className={`badge ${
                          selectedAnalysis.status === 'completed' ? 'badge-good' :
                          selectedAnalysis.status === 'running' ? 'badge-info' :
                          'badge-danger'
                        }`}>
                          {selectedAnalysis.status}
                        </span>
                      </td>
                    </tr>
                    <tr>
                      <th>NDVI میانگین</th>
                      <td>{ndviStats.mean?.toFixed(4) ?? '—'}</td>
                    </tr>
                    <tr>
                      <th>NDVI انحراف معیار</th>
                      <td>{ndviStats.std?.toFixed(4) ?? '—'}</td>
                    </tr>
                    <tr>
                      <th>تعداد تصاویر</th>
                      <td>{imageCount}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
