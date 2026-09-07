import { useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { analysesApi } from '../api/analyses'
import type { Analysis, TimeSeriesPoint } from '../types'

const YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

export default function Historical() {
  const [latitude, setLatitude] = useState('32.4279')
  const [longitude, setLongitude] = useState('53.6880')
  const [selectedYears, setSelectedYears] = useState<number[]>([2024, 2025])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [results, setResults] = useState<Record<number, { analysis: Analysis; timeSeries: TimeSeriesPoint[] }>>({})

  async function handleCompare() {
    setError(null)

    const lat = parseFloat(latitude)
    const lng = parseFloat(longitude)

    if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setError('مختصات نامعتبر — Invalid coordinates')
      return
    }

    if (selectedYears.length === 0) {
      setError('حداقل یک سال انتخاب کنید')
      return
    }

    try {
      setSubmitting(true)
      const geometry: GeoJSON.Geometry = { type: 'Point', coordinates: [lng, lat] }
      const newResults: Record<number, { analysis: Analysis; timeSeries: TimeSeriesPoint[] }> = {}

      // Run analyses for each year
      for (const year of selectedYears) {
        const startDate = `${year}-01-01`
        const endDate = `${year}-12-31`

        const result = await analysesApi.create({
          geometry,
          start_date: startDate,
          end_date: endDate,
          analysis_type: 'vegetation',
          temporal_resolution: 'monthly',
        })

        const ts = await analysesApi.getTimeSeries(result.id).catch(() => ({ data: [] }))
        newResults[year] = {
          analysis: result,
          timeSeries: ts.data || [],
        }
      }

      setResults(newResults)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تحلیل تاریخی')
    } finally {
      setSubmitting(false)
    }
  }

  // Merge time series data for comparison chart
  function getComparisonData(): Array<Record<string, string | number | null>> {
    const allDates = new Set<string>()
    const yearData: Record<number, Map<string, number | null>> = {}

    for (const [yearStr, result] of Object.entries(results)) {
      const year = parseInt(yearStr)
      yearData[year] = new Map()
      for (const point of result.timeSeries) {
        allDates.add(point.date)
        yearData[year].set(point.date, point.ndvi)
      }
    }

    return Array.from(allDates)
      .sort()
      .map((date) => {
        const entry: Record<string, string | number | null> = { date }
        for (const [yearStr, dataMap] of Object.entries(yearData)) {
          const year = parseInt(yearStr)
          entry[`ndvi_${year}`] = dataMap.get(date) ?? null
        }
        return entry
      })
  }

  const comparisonData = getComparisonData()

  const COLORS = ['#4caf50', '#2196f3', '#ff9800', '#e91e63', '#9c27b0', '#00bcd4', '#795548']

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">تاریخی</h2>
        <p className="page-subtitle">Historical — Multi-Year NDVI Comparison</p>
      </div>

      {/* Comparison Form */}
      <div className="card mb-3">
        <div className="card-header">
          <span className="card-title">📈 مقایسه سالانه</span>
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

          {/* Year Selector */}
          <div className="form-group">
            <label className="form-label">سال‌های مورد نظر</label>
            <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
              {YEARS.map((year) => (
                <button
                  key={year}
                  className={`btn btn-sm ${selectedYears.includes(year) ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => {
                    if (selectedYears.includes(year)) {
                      setSelectedYears(selectedYears.filter((y) => y !== year))
                    } else {
                      setSelectedYears([...selectedYears, year])
                    }
                  }}
                >
                  {year}
                </button>
              ))}
            </div>
            <div className="form-hint">
              {selectedYears.length} سال انتخاب شده
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
            onClick={handleCompare}
            disabled={submitting || selectedYears.length === 0}
          >
            {submitting ? (
              <>
                <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                در حال مقایسه...
              </>
            ) : (
              <>🔍 مقایسه سالانه</>
            )}
          </button>
        </div>
      </div>

      {/* Results */}
      {Object.keys(results).length > 0 && (
        <>
          {/* Comparison Chart */}
          <div className="chart-container mb-3">
            <h3 className="chart-title">مقایسه NDVI سالانه</h3>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={comparisonData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => {
                    const date = new Date(value)
                    return `${date.getMonth() + 1}/${date.getFullYear()}`
                  }}
                />
                <YAxis
                  domain={[0, 1]}
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => value.toFixed(1)}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'rgba(255, 255, 255, 0.95)',
                    border: '1px solid #ddd',
                    borderRadius: '8px',
                  }}
                  formatter={(value: number, name: string) => [value?.toFixed(3), name]}
                  labelFormatter={(label) => {
                    const date = new Date(label)
                    return date.toLocaleDateString('fa-IR', { year: 'numeric', month: 'long' })
                  }}
                />
                <Legend />
                {selectedYears.map((year, i) => (
                  <Line
                    key={year}
                    type="monotone"
                    dataKey={`ndvi_${year}`}
                    stroke={COLORS[i % COLORS.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    name={`${year}`}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Summary Table */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">📊 خلاصه سالانه</span>
            </div>
            <div className="card-body">
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>سال</th>
                      <th>NDVI میانگین</th>
                      <th>وضعیت</th>
                      <th>کیفیت داده</th>
                      <th>تعداد تصاویر</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedYears.map((year) => {
                      const result = results[year]
                      if (!result) return null

                      const resultData = result.analysis.result_data as Record<string, unknown> | null
                      const stats = (resultData?.statistics as Record<string, Record<string, number>>) || {}
                      const ndviStats = stats.NDVI || {}
                      const health = (resultData?.vegetation_health as string) || 'unknown'
                      const quality = (resultData?.data_quality as string) || 'unknown'
                      const imageCount = (resultData?.image_count as number) || 0

                      return (
                        <tr key={year}>
                          <td><strong>{year}</strong></td>
                          <td>{ndviStats.mean?.toFixed(4) ?? '—'}</td>
                          <td>
                            <span className={`badge ${
                              health === 'excellent' || health === 'good' ? 'badge-good' :
                              health === 'moderate' ? 'badge-warning' :
                              'badge-danger'
                            }`}>
                              {health}
                            </span>
                          </td>
                          <td>{quality}</td>
                          <td>{imageCount}</td>
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
      {Object.keys(results).length === 0 && !submitting && (
        <div className="empty-state">
          <div className="empty-state-icon">📈</div>
          <div className="empty-state-title">مقایسه تاریخی</div>
          <div className="empty-state-desc">
            NDVI چندین سال را مقایسه کنید تا روند تغییرات پوشش گیاهی مشخص شود.
            <br />
            <em style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
              توجه: Sentinel-2 از مارس 2017 در دسترس است.
            </em>
          </div>
        </div>
      )}
    </div>
  )
}
