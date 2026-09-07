import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { healthApi } from '../api/health'
import type { EarthEngineHealth, EarthEngineIndicatorState } from '../types'

// Configuration problems the operator must fix in backend/.env.
const CONFIG_ERROR_CODES = new Set(['not_configured', 'invalid_configuration'])

function stateFromHealth(res: EarthEngineHealth): EarthEngineIndicatorState {
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

// Maps indicator state to the tone classes used by .badge and .ee-status-dot.
const STATE_TONES: Record<EarthEngineIndicatorState, string> = {
  checking: 'info',
  connected: 'good',
  disconnected: 'danger',
  configuration_error: 'warning',
}

export default function EarthEngineIndicator() {
  const [state, setState] = useState<EarthEngineIndicatorState>('checking')
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let active = true

    healthApi
      .earthEngine()
      .then((res) => {
        if (!active) return
        setState(stateFromHealth(res))
        setMessage(res.message ?? null)
      })
      .catch(() => {
        // Health endpoint itself unreachable — do not claim Earth Engine works.
        if (!active) return
        setState('disconnected')
        setMessage('API not reachable')
      })

    return () => {
      active = false
    }
  }, [])

  const label = STATE_LABELS[state]
  const tone = STATE_TONES[state]

  return (
    <div className="card ee-status-card mb-3">
      <div className="card-body">
        <div className="ee-status-label">
          <span
            className={`ee-status-dot ee-status-dot-${tone}`}
            aria-hidden="true"
          />
          <span>🛰️</span>
          <span>
            <strong>Earth Engine</strong>
            <span className="text-muted"> — وضعیت سرویس</span>
          </span>
          <span className={`badge badge-${tone}`}>
            {label.fa} / {label.en}
          </span>
        </div>
        <div className="ee-status-actions">
          {message && <span className="ee-status-message">{message}</span>}
          <Link to="/settings" className="btn btn-sm btn-secondary">
            جزئیات / Details
          </Link>
        </div>
      </div>
    </div>
  )
}
