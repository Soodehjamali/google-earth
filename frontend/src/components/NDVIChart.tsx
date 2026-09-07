import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import type { TimeSeriesPoint } from '../types'

interface NDVIChartProps {
  data: TimeSeriesPoint[]
  title?: string
  height?: number
}

export default function NDVIChart({
  data,
  title = 'روند NDVI (NDVI Trend)',
  height = 300,
}: NDVIChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="chart-container">
        <h3 className="chart-title">{title}</h3>
        <div className="chart-no-data">
          <span className="no-data-icon">📊</span>
          <p>داده کافی موجود نیست</p>
          <p className="no-data-hint">Insufficient data</p>
        </div>
      </div>
    )
  }

  const chartData = data
    .filter((point) => point.ndvi !== null)
    .map((point) => ({
      date: point.date,
      ndvi: point.ndvi,
      evi: point.evi,
      savi: point.savi,
    }))

  return (
    <div className="chart-container">
      <h3 className="chart-title">{title}</h3>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12 }}
            tickFormatter={(value) => {
              const date = new Date(value)
              return date.toLocaleDateString('fa-IR', { month: 'short', year: '2-digit' })
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
            formatter={(value: number, name: string) => [
              value?.toFixed(3),
              name.toUpperCase(),
            ]}
            labelFormatter={(label) => {
              const date = new Date(label)
              return date.toLocaleDateString('fa-IR', {
                year: 'numeric',
                month: 'long',
              })
            }}
          />
          <ReferenceLine y={0.3} stroke="#ff9800" strokeDasharray="3 3" label=" Moderate " />
          <ReferenceLine y={0.6} stroke="#4caf50" strokeDasharray="3 3" label=" Dense " />
          <Line
            type="monotone"
            dataKey="ndvi"
            stroke="#4caf50"
            strokeWidth={2}
            dot={{ r: 4, fill: '#4caf50' }}
            activeDot={{ r: 6 }}
            name="NDVI"
          />
          <Line
            type="monotone"
            dataKey="evi"
            stroke="#2196f3"
            strokeWidth={1.5}
            dot={{ r: 3, fill: '#2196f3' }}
            name="EVI"
          />
          <Line
            type="monotone"
            dataKey="savi"
            stroke="#ff9800"
            strokeWidth={1.5}
            dot={{ r: 3, fill: '#ff9800' }}
            name="SAVI"
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="chart-legend">
        <span className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#4caf50' }} />
          NDVI
        </span>
        <span className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#2196f3' }} />
          EVI
        </span>
        <span className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#ff9800' }} />
          SAVI
        </span>
      </div>
    </div>
  )
}
