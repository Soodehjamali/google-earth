import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MapView from '../components/MapView'
import { analysesApi } from '../api/analyses'
import type { AnalysisType, TemporalResolution } from '../types'

type InputMode = 'gps' | 'geojson'

export default function Location() {
  const navigate = useNavigate()

  // Input mode
  const [mode, setMode] = useState<InputMode>('gps')

  // GPS mode
  const [latitude, setLatitude] = useState('32.4279')
  const [longitude, setLongitude] = useState('53.6880')

  // GeoJSON mode
  const [geojsonInput, setGeojsonInput] = useState('')

  // Analysis parameters
  const [startDate, setStartDate] = useState('2025-06-01')
  const [endDate, setEndDate] = useState('2025-09-01')
  const [analysisType, setAnalysisType] = useState<AnalysisType>('complete')
  const [temporalResolution, setTemporalResolution] = useState<TemporalResolution>('monthly')

  // State
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Preview geometry
  function getPreviewGeometry(): GeoJSON.Geometry | undefined {
    if (mode === 'gps') {
      const lat = parseFloat(latitude)
      const lng = parseFloat(longitude)
      if (isNaN(lat) || isNaN(lng)) return undefined
      if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return undefined
      return { type: 'Point', coordinates: [lng, lat] }
    }

    // GeoJSON mode
    try {
      const parsed = JSON.parse(geojsonInput)
      if (parsed.type === 'Polygon' || parsed.type === 'Point') {
        return parsed
      }
      // Handle Feature wrapping
      if (parsed.type === 'Feature' && parsed.geometry) {
        return parsed.geometry
      }
      return undefined
    } catch {
      return undefined
    }
  }

  const previewGeometry = getPreviewGeometry()

  function getCenter(): [number, number] {
    if (mode === 'gps') {
      const lat = parseFloat(latitude)
      const lng = parseFloat(longitude)
      if (!isNaN(lat) && !isNaN(lng)) return [lng, lat]
    }
    return [55.0, 32.0]
  }

  async function handleSubmit() {
    setError(null)

    let geometry: GeoJSON.Geometry

    if (mode === 'gps') {
      const lat = parseFloat(latitude)
      const lng = parseFloat(longitude)

      if (isNaN(lat) || isNaN(lng)) {
        setError('مختصات نامعتبر — Invalid coordinates')
        return
      }
      if (lat < -90 || lat > 90) {
        setError('عرض جغرافیایی باید بین -90 تا 90 باشد')
        return
      }
      if (lng < -180 || lng > 180) {
        setError('طول جغرافیایی باید بین -180 تا 180 باشد')
        return
      }

      geometry = { type: 'Point', coordinates: [lng, lat] }
    } else {
      // GeoJSON mode
      if (!geojsonInput.trim()) {
        setError('GeoJSON را وارد کنید')
        return
      }
      try {
        const parsed = JSON.parse(geojsonInput)
        if (parsed.type === 'Feature' && parsed.geometry) {
          geometry = parsed.geometry
        } else if (parsed.type === 'Polygon' || parsed.type === 'Point') {
          geometry = parsed
        } else {
          setError('نوع هندسه پشتیبانی نمی‌شود — Only Point and Polygon are supported')
          return
        }
      } catch {
        setError('GeoJSON نامعتبر — Invalid JSON')
        return
      }
    }

    try {
      setSubmitting(true)
      const analysis = await analysesApi.create({
        geometry,
        start_date: startDate,
        end_date: endDate,
        analysis_type: analysisType,
        temporal_resolution: temporalResolution,
      })

      // Navigate to the analysis page
      navigate(`/analysis/${analysis.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در ایجاد تحلیل')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">مکان</h2>
        <p className="page-subtitle">Location — Enter GPS coordinates or paste a GeoJSON polygon</p>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      )}

      <div className="grid-2">
        {/* Input Form */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">📍 ورودی مکان</span>
          </div>
          <div className="card-body">
            {/* Mode selector */}
            <div className="form-group">
              <label className="form-label">نوع ورودی</label>
              <div className="flex gap-1">
                <button
                  className={`btn btn-sm ${mode === 'gps' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setMode('gps')}
                >
                  📍 مختصات GPS
                </button>
                <button
                  className={`btn btn-sm ${mode === 'geojson' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setMode('geojson')}
                >
                  📐 GeoJSON
                </button>
              </div>
            </div>

            {/* GPS Input */}
            {mode === 'gps' && (
              <>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">عرض جغرافیایی (Latitude)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={latitude}
                      onChange={(e) => setLatitude(e.target.value)}
                      step="0.0001"
                      placeholder="32.4279"
                    />
                    <div className="form-hint">بین -90 تا 90</div>
                  </div>
                  <div className="form-group">
                    <label className="form-label">طول جغرافیایی (Longitude)</label>
                    <input
                      type="number"
                      className="form-input"
                      value={longitude}
                      onChange={(e) => setLongitude(e.target.value)}
                      step="0.0001"
                      placeholder="53.6880"
                    />
                    <div className="form-hint">بین -180 تا 180</div>
                  </div>
                </div>
              </>
            )}

            {/* GeoJSON Input */}
            {mode === 'geojson' && (
              <div className="form-group">
                <label className="form-label">GeoJSON</label>
                <textarea
                  className="form-textarea"
                  value={geojsonInput}
                  onChange={(e) => setGeojsonInput(e.target.value)}
                  placeholder={`{\n  "type": "Polygon",\n  "coordinates": [[\n    [53.68, 32.42],\n    [53.69, 32.42],\n    [53.69, 32.43],\n    [53.68, 32.43],\n    [53.68, 32.42]\n  ]]\n}`}
                />
                <div className="form-hint">
                  Point یا Polygon — GeoJSON معتبر وارد کنید
                </div>
              </div>
            )}

            {/* Date Range */}
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

            {/* Analysis Type */}
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">نوع تحلیل</label>
                <select
                  className="form-select"
                  value={analysisType}
                  onChange={(e) => setAnalysisType(e.target.value as AnalysisType)}
                >
                  <option value="complete">کامل (Complete)</option>
                  <option value="vegetation">پوشش گیاهی (Vegetation)</option>
                  <option value="climate">اقلیم (Climate)</option>
                  <option value="soil">خاک (Soil)</option>
                  <option value="water">آب (Water)</option>
                  <option value="landcover">پوشش ارضی (Land Cover)</option>
                  <option value="historical">تاریخی (Historical)</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">رزولوشن زمانی</label>
                <select
                  className="form-select"
                  value={temporalResolution}
                  onChange={(e) => setTemporalResolution(e.target.value as TemporalResolution)}
                >
                  <option value="daily">روزانه (Daily)</option>
                  <option value="weekly">هفتگی (Weekly)</option>
                  <option value="monthly">ماهانه (Monthly)</option>
                  <option value="seasonal">فصلی (Seasonal)</option>
                  <option value="yearly">سالانه (Yearly)</option>
                </select>
              </div>
            </div>

            {/* Submit */}
            <button
              className="btn btn-primary w-full mt-2"
              onClick={handleSubmit}
              disabled={submitting || !previewGeometry}
            >
              {submitting ? (
                <>
                  <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                  در حال پردازش...
                </>
              ) : (
                <>🔍 شروع تحلیل</>
              )}
            </button>
          </div>
        </div>

        {/* Map Preview */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">🗺️ پیش‌نمایش</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <MapView
              geometry={previewGeometry}
              center={getCenter()}
              zoom={previewGeometry?.type === 'Point' ? 12 : 10}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
