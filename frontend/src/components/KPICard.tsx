interface KPICardProps {
  title: string
  titleFa: string
  value: number | string | null
  unit?: string
  icon: string
  status?: 'good' | 'warning' | 'danger' | 'neutral'
  subtitle?: string
}

export default function KPICard({
  title,
  titleFa,
  value,
  unit = '',
  icon,
  status = 'neutral',
  subtitle,
}: KPICardProps) {
  const statusClass = `kpi-status-${status}`

  return (
    <div className={`kpi-card ${statusClass}`}>
      <div className="kpi-header">
        <span className="kpi-icon">{icon}</span>
        <div className="kpi-titles">
          <h3 className="kpi-title-fa">{titleFa}</h3>
          <span className="kpi-title-en">{title}</span>
        </div>
      </div>
      <div className="kpi-value">
        {value !== null && value !== undefined ? (
          <>
            <span className="kpi-number">{typeof value === 'number' ? value.toFixed(3) : value}</span>
            {unit && <span className="kpi-unit">{unit}</span>}
          </>
        ) : (
          <span className="kpi-no-data">داده موجود نیست</span>
        )}
      </div>
      {subtitle && <div className="kpi-subtitle">{subtitle}</div>}
    </div>
  )
}
