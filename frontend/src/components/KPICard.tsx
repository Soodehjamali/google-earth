import React from 'react';
import FormattedNumber from './common/FormattedNumber';

interface KPICardProps {
  title: string
  titleFa: string
  value: number | string | null
  unit?: string
  icon: string
  status?: 'good' | 'warning' | 'danger' | 'neutral'
  subtitle?: string
  digits?: number
  /** Extra always-visible content under the subtitle (e.g. support badge). */
  footer?: React.ReactNode
  referenceRange?: string
  farmerNote?: string
  resolution?: string
  statusLabelFa?: string
}

export default function KPICard({
  title,
  titleFa,
  value,
  unit = '',
  icon,
  status = 'neutral',
  subtitle,
  digits,
  footer,
  referenceRange,
  farmerNote,
  resolution,
  statusLabelFa,
}: KPICardProps) {
  const statusClass = `kpi-status-${status}`

  return (
    <div className={`kpi-card ${statusClass}`}>
      <div className="kpi-header">
        <span className="kpi-icon">{icon}</span>
        <div className="kpi-titles">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4 }}>
            <h3 className="kpi-title-fa" style={{ margin: 0 }}>{titleFa}</h3>
            {statusLabelFa && (
              <span style={{ fontSize: '0.65rem', padding: '1px 4px', borderRadius: 3, background: 'rgba(0,0,0,0.06)' }}>
                {statusLabelFa}
              </span>
            )}
          </div>
          <span className="kpi-title-en">{title}</span>
        </div>
      </div>
      <div className="kpi-value">
        {value !== null && value !== undefined ? (
          <FormattedNumber
            value={value}
            unit={unit}
            digits={digits !== undefined ? digits : (typeof value === 'number' && Math.abs(value) < 1.5 ? 4 : typeof value === 'number' && Math.abs(value) >= 1000 ? 0 : 2)}
          />
        ) : (
          <span className="kpi-no-data">داده موجود نیست</span>
        )}
      </div>
      {referenceRange && (
        <div style={{ fontSize: '0.72rem', background: 'rgba(0,0,0,0.04)', padding: '2px 6px', borderRadius: 4, margin: '4px 0', color: '#2e7d32' }}>
          🎯 مرجع: <strong>{referenceRange}</strong>
        </div>
      )}
      {farmerNote && (
        <div style={{ fontSize: '0.72rem', color: '#455a64', margin: '4px 0', lineHeight: 1.35 }}>
          🌱 {farmerNote}
        </div>
      )}
      {subtitle && <div className="kpi-subtitle">{subtitle}{resolution ? ` • ${resolution}` : ''}</div>}
      {footer}
    </div>
  )
}
