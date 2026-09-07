import { useCallback, useEffect, useState } from 'react'
import { healthApi } from '../api/health'
import type { EarthEngineHealth, EarthEngineIndicatorState } from '../types'

const CONFIG_ERROR_CODES = new Set(['not_configured', 'invalid_configuration'])

type UiTone = 'good' | 'danger' | 'warning' | 'info'

function stateFromHealth(res: EarthEngineHealth | null): EarthEngineIndicatorState {
  if (!res) return 'checking'
  if (res.status === 'connected') return 'connected'
  if (res.code && CONFIG_ERROR_CODES.has(res.code)) return 'configuration_error'
  return 'disconnected'
}

const STATE_LABELS: Record<EarthEngineIndicatorState, { fa: string; en: string }> = {
  checking: { fa: 'در حال بررسی...', en: 'Checking...' },
  connected: { fa: 'متصل', en: 'Connected' },
  disconnected: { fa: 'قطع', en: 'Disconnected' },
  configuration_error: { fa: 'خطای پیکربندی', en: 'Configuration Error' },
}

const STATE_TONES: Record<EarthEngineIndicatorState, UiTone> = {
  checking: 'info',
  connected: 'good',
  disconnected: 'danger',
  configuration_error: 'warning',
}

export default function Settings() {
  const [health, setHealth] = useState<EarthEngineHealth | null>(null)
  const [state, setState] = useState<EarthEngineIndicatorState>('checking')
  const [lastChecked, setLastChecked] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runHealthCheck = useCallback(async () => {
    setTesting(true)
    setError(null)
    try {
      const res = await healthApi.earthEngine()
      setHealth(res)
      setState(stateFromHealth(res))
      setLastChecked(new Date().toISOString())
    } catch (err) {
      setState('disconnected')
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to reach the health endpoint'
      )
    } finally {
      setTesting(false)
    }
  }, [])

  // Fresh check every time the Settings page opens.
  useEffect(() => {
    runHealthCheck()
  }, [runHealthCheck])

  const label = STATE_LABELS[state]
  const tone = STATE_TONES[state]
  const project = health?.project ?? null
  const authenticated = health?.authenticated ?? state === 'connected'
  const message = error ?? health?.message ?? null

  const formatDate = (iso: string | null): string => {
    if (!iso) return '—'
    const date = new Date(iso)
    if (Number.isNaN(date.getTime())) return iso
    return date.toLocaleString()
  }

  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">تنظیمات</h2>
        <p className="page-subtitle">Settings — System Configuration</p>
      </div>

      {/* Earth Engine section */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">🛰️ Earth Engine</span>
        </div>
        <div className="card-body">
          <div className="table-container">
            <table>
              <tbody>
                <tr>
                  <th>
                    Connection Status{' '}
                    <span className="text-muted">/ وضعیت اتصال</span>
                  </th>
                  <td>
                    <span className={`badge badge-${tone}`}>
                      {label.en} — {label.fa}
                    </span>
                  </td>
                </tr>
                <tr>
                  <th>
                    Project ID <span className="text-muted">/ شناسه پروژه</span>
                  </th>
                  <td dir="ltr" style={{ textAlign: 'left' }}>
                    {project ? (
                      <code>{project}</code>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>
                    Authenticated{' '}
                    <span className="text-muted">/ احراز هویت</span>
                  </th>
                  <td>{authenticated ? 'Yes / بله' : 'No / خیر'}</td>
                </tr>
                <tr>
                  <th>
                    Last Health Check{' '}
                    <span className="text-muted">/ آخرین بررسی</span>
                  </th>
                  <td dir="ltr" style={{ textAlign: 'left' }}>
                    {formatDate(lastChecked)}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {message && (
            <div
              className={
                state === 'connected' ? 'info-banner' : 'error-banner'
              }
              style={{ marginTop: 16 }}
            >
              <span>{state === 'connected' ? '✅' : '⚠️'}</span>
              <span dir="ltr">{message}</span>
            </div>
          )}

          <div className="flex items-center gap-1 mt-2">
            <button
              className="btn btn-primary"
              onClick={runHealthCheck}
              disabled={testing}
            >
              {testing ? (
                <>
                  <span
                    className="spinner"
                    style={{ width: 16, height: 16, borderWidth: 2 }}
                  />
                  در حال آزمایش...
                </>
              ) : (
                <>🔌 Test Connection / آزمایش اتصال</>
              )}
            </button>
          </div>

          <p className="form-hint mt-2" style={{ lineHeight: 1.8 }}>
            Earth Engine credentials are stored and used only on the server.
            This page never shows private keys, client secrets, tokens, or
            credential files. — اعتبارنامه‌های Earth Engine فقط سمت سرور نگهداری
            و استفاده می‌شوند؛ این صفحه هرگز کلید خصوصی، توکن یا فایل اعتبارنامه
            را نمایش نمی‌دهد.
          </p>
        </div>
      </div>
    </div>
  )
}
