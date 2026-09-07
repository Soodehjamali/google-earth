import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import MapView from '../components/MapView'
import KPICard from '../components/KPICard'
import NDVIChart from '../components/NDVIChart'
import { analysesApi } from '../api/analyses'
import type { Analysis as AnalysisType, MapVisualization, TimeSeriesPoint } from '../types'

export default function Analysis() {
  const { id } = useParams<{ id: string }>()

  const [analysis, setAnalysis] = useState<AnalysisType | null>(null)
  const [mapViz, setMapViz] = useState<MapVisualization | undefined>()
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [polling, setPolling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (id) loadAnalysis(id)
  }, [id])

  // Poll for running analyses
  useEffect(() => {
    if (!id || !analysis) return
    if (analysis.status !== 'running' && analysis.status !== 'pending') return

    setPolling(true)
    const interval = setInterval(() => loadAnalysis(id), 3000)
    return () => {
      clearInterval(interval)
      setPolling(false)
    }
  }, [analysis?.status, id])

  async function loadAnalysis(analysisId: string) {
    try {
      const data = await analysesApi.get(analysisId)
      setAnalysis(data)

      if (data.status === 'completed' && data.result_data) {
        // Load map and timeseries in parallel
        const [viz, ts] = await Promise.allSettled([
          analysesApi.getMaps(analysisId),
          analysesApi.getTimeSeries(analysisId),
        ])
        if (viz.status === 'fulfilled') setMapViz(viz.value)
        if (ts.status === 'fulfilled') setTimeSeriesData(ts.value.data)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری تحلیل')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner" />
        <span>در حال بارگذاری تحلیل...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <div className="page-header">
          <h2 className="page-title">خطا</h2>
        </div>
        <div className="error-banner">
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      </div>
    )
  }

  if (!analysis) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">❌</div>
        <div className="empty-state-title">تحلیل یافت نشد</div>
      </div>
    )
  }

  const resultData = analysis.result_data as Record<string, unknown> | null
  const stats = (resultData?.statistics as Record<string, Record<string, number>>) || {}
  const ndviStats = stats.NDVI || {}
  const eviStats = stats.EVI || {}
  const saviStats = stats.SAVI || {}
  const ndwiStats = stats.NDWI || {}
  const vegetationHealth = (resultData?.vegetation_health as string) || 'unknown'
  const imageCount = (resultData?.image_count as number) || 0
  const dataQuality = (resultData?.data_quality as string) || 'unknown'
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
      <div className="page-header flex justify-between items-center">
        <div>
          <h2 className="page-title">نتایج تحلیل</h2>
          <p className="page-subtitle">
            Analysis {analysis.id.slice(0, 8)} — {analysis.start_date} → {analysis.end_date}
          </p>
        </div>
        <div className="flex gap-1">
          <span className={`badge ${
            analysis.status === 'completed' ? 'badge-good' :
            analysis.status === 'running' ? 'badge-info' :
            analysis.status === 'pending' ? 'badge-info' :
            'badge-danger'
          }`}>
            {polling && '⏳ '}
            {analysis.status}
          </span>
        </div>
      </div>

      {analysis.status === 'running' && (
        <div className="card mb-3" style={{ padding: 20, textAlign: 'center' }}>
          <div className="spinner" style={{ margin: '0 auto 12px' }} />
          <span>تحلیل در حال اجراست... لطفاً صبر کنید</span>
        </div>
      )}

      {analysis.status === 'failed' && (
        <div className="error-banner">
          <span>❌</span>
          <span>{analysis.error_message || 'تحلیل با خطا مواجه شد'}</span>
        </div>
      )}

      {analysis.status === 'completed' && (
        <>
          {/* Map */}
          <div className="card mb-3">
            <div className="card-header">
              <span className="card-title">🗺️ نقشه</span>
            </div>
            <div className="card-body" style={{ padding: 0 }}>
              <MapView
                visualization={mapViz}
                center={mapViz?.center || [55.0, 32.0]}
                zoom={mapViz?.zoom || 6}
              />
            </div>
          </div>

          {/* KPI Grid */}
          <div className="kpi-grid">
            <KPICard
              title="NDVI"
              titleFa="شاخص سبزینگی"
              value={ndviStats.mean}
              icon="🌿"
              status={getValStatus(ndviStats.mean)}
              subtitle={`σ = ${ndviStats.std?.toFixed(3) ?? '—'}`}
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
            <KPICard
              title="Images"
              titleFa="تصاویر"
              value={imageCount}
              unit="scenes"
              icon="🛰️"
              status="neutral"
            />
            <KPICard
              title="Quality"
              titleFa="کیفیت"
              value={dataQuality}
              icon="📋"
              status={dataQuality === 'good' ? 'good' : dataQuality === 'acceptable' ? 'warning' : 'danger'}
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

          {/* Charts + Stats Table */}
          <div className="grid-2">
            <NDVIChart data={timeSeriesData} />

            <div className="card">
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
                        <th>انحراف</th>
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
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
