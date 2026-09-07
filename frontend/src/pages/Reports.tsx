import { useState, useEffect } from 'react'
import { analysesApi } from '../api/analyses'
import type { Analysis } from '../types'

export default function Reports() {
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [generatingReport, setGeneratingReport] = useState<string | null>(null)

  useEffect(() => {
    loadAnalyses()
  }, [])

  async function loadAnalyses() {
    try {
      setLoading(true)
      const data = await analysesApi.list(0, 50)
      setAnalyses(data.filter((a) => a.status === 'completed'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری تحلیل‌ها')
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerateReport(analysisId: string) {
    try {
      setGeneratingReport(analysisId)
      // TODO: Implement report generation endpoint
      // await apiPost(`/reports/${analysisId}`, {})
      alert('گزارش با موفقیت ایجاد شد — Report generation is being implemented')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'خطا در ایجاد گزارش')
    } finally {
      setGeneratingReport(null)
    }
  }

  function formatDate(dateStr: string) {
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString('fa-IR', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    } catch {
      return dateStr
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">گزارش‌ها</h2>
        <p className="page-subtitle">Reports — Generate and download analysis reports</p>
      </div>

      {loading && (
        <div className="loading">
          <div className="spinner" />
          <span>در حال بارگذاری...</span>
        </div>
      )}

      {error && (
        <div className="error-banner">
          <span>⚠️</span>
          <span>{error}</span>
        </div>
      )}

      {!loading && analyses.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">📋</div>
          <div className="empty-state-title">هیچ تحلیل تکمیل شده‌ای یافت نشد</div>
          <div className="empty-state-desc">
            ابتدا یک تحلیل جدید ایجاد کنید تا بتوانید گزارش تولید کنید.
          </div>
        </div>
      )}

      {!loading && analyses.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">📊 تحلیل‌های تکمیل شده</span>
            <span className="badge badge-info">{analyses.length} تحلیل</span>
          </div>
          <div className="card-body">
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>شناسه</th>
                    <th>نوع تحلیل</th>
                    <th>تاریخ شروع</th>
                    <th>تاریخ پایان</th>
                    <th>وضعیت</th>
                    <th>تاریخ ایجاد</th>
                    <th>عملیات</th>
                  </tr>
                </thead>
                <tbody>
                  {analyses.map((analysis) => (
                    <tr key={analysis.id}>
                      <td>
                        <code style={{ fontSize: '0.8rem' }}>{analysis.id.slice(0, 8)}</code>
                      </td>
                      <td>{analysis.analysis_type}</td>
                      <td>{analysis.start_date}</td>
                      <td>{analysis.end_date}</td>
                      <td>
                        <span className="badge badge-good">{analysis.status}</span>
                      </td>
                      <td>{formatDate(analysis.created_at)}</td>
                      <td>
                        <div className="flex gap-1">
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => handleGenerateReport(analysis.id)}
                            disabled={generatingReport === analysis.id}
                          >
                            {generatingReport === analysis.id ? (
                              <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />
                            ) : (
                              <>📄 ایجاد گزارش</>
                            )}
                          </button>
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={() => window.location.href = `/analysis/${analysis.id}`}
                          >
                            👁️ مشاهده
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Report Info */}
      <div className="card mt-3">
        <div className="card-header">
          <span className="card-title">ℹ️ درباره گزارش‌ها</span>
        </div>
        <div className="card-body">
          <div style={{ fontSize: '0.85rem', lineHeight: 1.8, color: 'var(--color-text-secondary)' }}>
            <p><strong>گزارش شامل اطلاعات زیر است:</strong></p>
            <ul style={{ paddingRight: 20, marginTop: 8 }}>
              <li>موقعیت مکانی و نقشه میدان</li>
              <li>بازه زمانی تحلیل</li>
              <li>تصاویر ماهواره‌ای</li>
              <li>شاخص‌های پوشش گیاهی (NDVI، EVI، SAVI، NDWI)</li>
              <li>داده‌های اقلیمی (دما، بارش، تبخیر-تعرق)</li>
              <li>تحلیل خاک</li>
              <li>پوشش ارضی</li>
              <li>نقشه تنش</li>
              <li>امتیاز ریسک</li>
              <li>نمودارهای سری زمانی</li>
              <li>منابع داده و روش‌شناسی</li>
              <li>محدودیت‌ها</li>
            </ul>

            <p style={{ marginTop: 12 }}>
              <em style={{ color: 'var(--color-text-muted)' }}>
                توجه: گزارش‌ها شامل منابع داده و محدودیت‌های هر متغیر هستند.
              </em>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
