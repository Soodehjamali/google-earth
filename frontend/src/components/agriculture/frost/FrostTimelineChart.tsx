import React, { useMemo } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  Legend,
} from 'recharts';
import type { FrostPoint, FrostNightAssessment } from '../../../types';
import FormattedNumber from '../../common/FormattedNumber';
import { toPersianDigits } from '../persianDate';

interface FrostTimelineChartProps {
  points: FrostPoint[];
  nights?: FrostNightAssessment[];
  criticalTemp10?: number;
  criticalTemp90?: number;
  height?: number;
}

export const FrostTimelineChart: React.FC<FrostTimelineChartProps> = ({
  points,
  nights = [],
  criticalTemp10,
  criticalTemp90,
  height = 360,
}) => {
  const chartData = useMemo(() => {
    if (!points || !Array.isArray(points)) return [];
    return points.map((p) => {
      // Format local hour for x-axis
      const d = new Date(p.time_utc);
      const hours = d.getHours().toString().padStart(2, '0');
      const day = d.getDate().toString();
      const month = (d.getMonth() + 1).toString();
      const displayTime = `${hours}:00 (${month}/${day})`;

      return {
        time_utc: p.time_utc,
        displayTime,
        lead_time_h: p.lead_time_h,
        corrected_temperature_c: p.corrected_temperature_c,
        raw_temperature_c: p.raw_temperature_c,
        temperature_min_c: p.temperature_min_c,
        temperature_max_c: p.temperature_max_c,
        tempRange: [p.temperature_min_c, p.temperature_max_c],
        uncertainty_c: p.uncertainty_c,
        dewpoint_2m_c: p.dewpoint_2m_c,
        relative_humidity_percent: p.relative_humidity_percent,
        wind_speed_10m_mps: p.wind_speed_10m_mps,
        is_interpolated: p.is_interpolated,
      };
    });
  }, [points]);

  const yDomain = useMemo(() => {
    let minVal = -5;
    let maxVal = 25;
    points.forEach((p) => {
      if (p.temperature_min_c < minVal) minVal = p.temperature_min_c;
      if (p.temperature_max_c > maxVal) maxVal = p.temperature_max_c;
    });
    if (criticalTemp10 !== undefined && criticalTemp10 < minVal) minVal = criticalTemp10;
    if (criticalTemp90 !== undefined && criticalTemp90 < minVal) minVal = criticalTemp90;
    return [Math.floor(minVal - 2), Math.ceil(maxVal + 2)];
  }, [points, criticalTemp10, criticalTemp90]);

  const customTooltip = (tooltipProps: unknown) => {
    const props = tooltipProps as {
      active?: boolean;
      payload?: Array<{ payload?: (typeof chartData)[0] }>;
    };
    if (!props.active || !props.payload || !props.payload.length) return null;
    const p = props.payload[0]?.payload;
    if (!p) return null;

    return (
      <div
        className="card"
        style={{
          backgroundColor: 'rgba(255, 255, 255, 0.96)',
          border: '1px solid #cbd5e1',
          borderRadius: 8,
          padding: '10px 14px',
          fontSize: '0.82rem',
          direction: 'rtl',
          boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)',
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 4, color: '#1e293b' }}>
          زمان: {p.displayTime} (افق: {toPersianDigits(p.lead_time_h)} ساعت)
        </div>
        <div style={{ color: '#64748b', fontSize: '0.75rem', marginBottom: 6, direction: 'ltr' }}>
          UTC: {p.time_utc}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
          <span>دمای تصحیح‌شده (DEM):</span>
          <FormattedNumber value={p.corrected_temperature_c} unit="°C" />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
          <span>بازه عدم‌قطعیت (±σ):</span>
          <span dir="ltr">
            [<FormattedNumber value={p.temperature_min_c} digits={1} /> ..{' '}
            <FormattedNumber value={p.temperature_max_c} digits={1} /> °C]
          </span>
        </div>
        {p.dewpoint_2m_c !== null && p.dewpoint_2m_c !== undefined && (
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
            <span>نقطه شبنم (Dewpoint):</span>
            <FormattedNumber value={p.dewpoint_2m_c} unit="°C" />
          </div>
        )}
        {p.wind_speed_10m_mps !== null && p.wind_speed_10m_mps !== undefined && (
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
            <span>سرعت باد (۱۰ متری):</span>
            <FormattedNumber value={p.wind_speed_10m_mps} unit="m/s" digits={1} />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="card mb-3" data-testid="frost-timeline-card">
      <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="card-title">📈 پیش‌بینی ساعتی دما و باندهای عدم‌قطعیت (NOAA GFS + NASADEM)</span>
        <span className="text-muted" style={{ fontSize: '0.8rem' }}>
          بخش‌های سایه‌دار خاکستری: پنجره شب‌های محلی (۱۸:۰۰ الی ۰۹:۰۰ روز بعد)
        </span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={chartData} margin={{ top: 20, right: 20, left: 10, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="time_utc"
              tickFormatter={(_, index) => {
                const item = chartData[index];
                return item ? item.displayTime : '';
              }}
              interval={Math.max(1, Math.floor(chartData.length / 8))}
              fontSize={11}
              stroke="#64748b"
            />
            <YAxis
              domain={yDomain}
              unit="°C"
              fontSize={11}
              stroke="#64748b"
              tickFormatter={(val) => `${val}°`}
            />
            <Tooltip content={customTooltip} />
            <Legend
              wrapperStyle={{ fontSize: '0.8rem', paddingTop: '10px' }}
              formatter={(value) => <span style={{ color: '#334155' }}>{value}</span>}
            />

            {/* Shaded nocturnal windows crossing midnight */}
            {nights.map((night, idx) => (
              <ReferenceArea
                key={night.night_date}
                x1={night.window_start_utc}
                x2={night.window_end_utc}
                fill="#334155"
                fillOpacity={0.08}
                label={{
                  value: `شب ${toPersianDigits(idx + 1)}`,
                  fill: '#64748b',
                  position: 'insideTop',
                  fontSize: 11,
                }}
              />
            ))}

            {/* Freezing Reference Line (0°C) */}
            <ReferenceLine
              y={0}
              stroke="#94a3b8"
              strokeDasharray="2 2"
              strokeWidth={1}
              label={{ value: '0°C (نقطه انجماد)', fill: '#64748b', position: 'insideRight', fontSize: 11 }}
            />

            {/* Phenological Critical Threshold Lines */}
            {criticalTemp10 !== undefined && (
              <ReferenceLine
                y={criticalTemp10}
                stroke="#d97706"
                strokeDasharray="4 4"
                strokeWidth={2}
                label={{
                  value: `Tc10: ${criticalTemp10}°C (آستانه ۱۰٪)`,
                  fill: '#b45309',
                  position: 'insideTopLeft',
                  fontSize: 11,
                }}
              />
            )}
            {criticalTemp90 !== undefined && (
              <ReferenceLine
                y={criticalTemp90}
                stroke="#dc2626"
                strokeDasharray="4 4"
                strokeWidth={2}
                label={{
                  value: `Tc90: ${criticalTemp90}°C (خسارت ۹۰٪)`,
                  fill: '#b91c1c',
                  position: 'insideBottomLeft',
                  fontSize: 11,
                }}
              />
            )}

            {/* Uncertainty band & temperature bounds */}
            <Area
              type="monotone"
              dataKey="tempRange"
              name="باند عدم‌قطعیت پیش‌بینی (دمای تصحیح‌شده ± عدم‌قطعیت)"
              fill="#bfdbfe"
              fillOpacity={0.3}
              stroke="none"
            />
            <Line
              type="monotone"
              dataKey="temperature_max_c"
              name="حد بالای عدم‌قطعیت (+σ)"
              stroke="#93c5fd"
              strokeDasharray="3 3"
              strokeWidth={1}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="temperature_min_c"
              name="حد پایین عدم‌قطعیت (−σ)"
              stroke="#93c5fd"
              strokeDasharray="3 3"
              strokeWidth={1}
              dot={false}
            />

            {/* Corrected temperature main forecast line */}
            <Line
              type="monotone"
              dataKey="corrected_temperature_c"
              name="دمای پیش‌بینی‌شده (تصحیح تراز ارتفاع)"
              stroke="#2563eb"
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 5, fill: '#1d4ed8' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default FrostTimelineChart;
