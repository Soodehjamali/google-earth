import React from 'react';
import type { FrostNightAssessment, FrostSeverity } from '../../../types';
import FormattedNumber from '../../common/FormattedNumber';
import { toPersianDigits } from '../persianDate';

interface FrostNightCardsProps {
  nights: FrostNightAssessment[];
  criticalTemp10?: number;
  criticalTemp90?: number;
}

const SEVERITY_META: Record<
  FrostSeverity,
  { labelFa: string; bg: string; text: string; border: string; icon: string }
> = {
  warning: {
    labelFa: 'اخطار سرمازدگی (Warning)',
    bg: '#fef2f2',
    text: '#991b1b',
    border: '#f87171',
    icon: '🚨',
  },
  watch: {
    labelFa: 'دیده‌بانی سرما (Watch)',
    bg: '#fff7ed',
    text: '#c2410c',
    border: '#fb923c',
    icon: '⚠️',
  },
  advisory: {
    labelFa: 'هشدار مقدماتی (Advisory)',
    bg: '#fefce8',
    text: '#854d0e',
    border: '#facc15',
    icon: 'ℹ️',
  },
  none: {
    labelFa: 'عادی (بدون خطر)',
    bg: '#f0fdf4',
    text: '#166534',
    border: '#86efac',
    icon: '✅',
  },
};

export const FrostNightCards: React.FC<FrostNightCardsProps> = ({
  nights,
  criticalTemp10,
  criticalTemp90,
}) => {
  if (!nights || nights.length === 0) {
    return (
      <div className="card mb-3 p-3 text-muted text-center">
        اطلاعات ارزیابی شب‌های آتی در دسترس نیست.
      </div>
    );
  }

  return (
    <div className="card mb-3" data-testid="frost-night-cards-section">
      <div className="card-header">
        <span className="card-title">🌙 ارزیابی ریسک و توصیه‌های فنی شب‌های آتی</span>
      </div>
      <div className="card-body">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {nights.map((night, idx) => {
            const meta = SEVERITY_META[night.severity] || SEVERITY_META.none;

            return (
              <div
                key={night.night_date}
                className="frost-night-card"
                data-testid={`frost-night-card-${night.night_date}`}
                style={{
                  border: `1px solid ${meta.border}`,
                  borderRadius: '8px',
                  backgroundColor: '#ffffff',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                  overflow: 'hidden',
                }}
              >
                {/* Night Header */}
                <div
                  style={{
                    backgroundColor: meta.bg,
                    borderBottom: `1px solid ${meta.border}`,
                    padding: '10px 16px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '8px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '1.2rem' }}>{meta.icon}</span>
                    <span style={{ fontWeight: 700, color: meta.text, fontSize: '0.95rem' }}>
                      شب {toPersianDigits(idx + 1)} — تاریخ {night.night_date}
                    </span>
                    <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                      ({night.window_start_local.slice(11, 16)} تا {night.window_end_local.slice(11, 16)} روز بعد)
                    </span>
                  </div>

                  <span
                    style={{
                      padding: '3px 10px',
                      borderRadius: '12px',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      backgroundColor: '#ffffff',
                      color: meta.text,
                      border: `1px solid ${meta.border}`,
                    }}
                  >
                    {meta.labelFa}
                  </span>
                </div>

                {/* Night Body */}
                <div style={{ padding: '16px' }}>
                  {/* KPI Row */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                      gap: '12px',
                      marginBottom: '16px',
                    }}
                  >
                    <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                        کمینه دمای سینوپتیک
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>
                        <FormattedNumber value={night.min_temp_c} unit="°C" />
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                        افت تجمع سردی (ΔT)
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: night.pooling_cooling_bump_c > 0 ? '#b91c1c' : '#334155' }}>
                        <FormattedNumber value={night.pooling_cooling_bump_c} unit="°C" />
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                        دمای کمینه نهایی مزرعه
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: meta.text }}>
                        <FormattedNumber value={night.adjusted_min_temp_c} unit="°C" />
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                        مدت زیر آستانه ۱۰٪ ({criticalTemp10 !== undefined ? `${criticalTemp10}°` : 'Tc10'})
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>
                        <FormattedNumber value={night.duration_below_t10_h} unit="h" digits={1} />
                      </div>
                    </div>

                    <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                        مدت زیر آستانه ۹۰٪ ({criticalTemp90 !== undefined ? `${criticalTemp90}°` : 'Tc90'})
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: night.duration_below_t90_h > 0 ? '#b91c1c' : '#334155' }}>
                        <FormattedNumber value={night.duration_below_t90_h} unit="h" digits={1} />
                      </div>
                    </div>
                  </div>

                  {/* Reasons */}
                  {night.reasons && night.reasons.length > 0 && (
                    <div style={{ marginBottom: '14px' }}>
                      <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '6px', color: '#475569' }}>
                        عوامل فعال‌کننده ریسک:
                      </div>
                      <ul style={{ margin: 0, paddingRight: '20px', fontSize: '0.85rem', color: '#334155' }}>
                        {night.reasons.map((reason, rIdx) => (
                          <li key={rIdx}>{reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Recommendations */}
                  {night.recommendations_fa && night.recommendations_fa.length > 0 && (
                    <div
                      style={{
                        backgroundColor: '#f1f5f9',
                        padding: '12px 14px',
                        borderRadius: '6px',
                        borderRight: '4px solid #3b82f6',
                      }}
                    >
                      <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: '6px', color: '#1e3a8a' }}>
                        توصیه‌های فنی و عملیات فیزیکی حفاظتی (غیرشیمیایی):
                      </div>
                      <ul style={{ margin: 0, paddingRight: '20px', fontSize: '0.85rem', color: '#1e293b' }}>
                        {night.recommendations_fa.map((rec, recIdx) => (
                          <li key={recIdx} style={{ marginBottom: '4px' }}>
                            {rec}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default FrostNightCards;
