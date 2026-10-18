import React from 'react';
import type { FrostNightAssessment, FrostSeverity } from '../../../types';
import FormattedNumber from '../../common/FormattedNumber';
import { toPersianDigits } from '../persianDate';

interface FrostNightCardsProps {
  nights: FrostNightAssessment[];
  criticalTemp10?: number;
  criticalT10?: number;
  criticalTemp90?: number;
  criticalT90?: number;
}

const SEVERITY_META: Record<
  FrostSeverity,
  { labelFa: string; bg: string; text: string; border: string; icon: string }
> = {
  critical: {
    labelFa: 'سرمازدگی بحرانی (خطر بالای خسارت (برآورد مشورتی))',
    bg: '#fef2f2',
    text: '#7f1d1d',
    border: '#b91c1c',
    icon: '☠️',
  },
  warning: {
    labelFa: 'هشدار سرمازدگی (احتمال بالای خسارت (برآورد مشورتی))',
    bg: '#fef2f2',
    text: '#991b1b',
    border: '#f87171',
    icon: '🚨',
  },
  watch: {
    labelFa: 'دیده‌بانی سرما',
    bg: '#fff7ed',
    text: '#c2410c',
    border: '#fb923c',
    icon: '⚠️',
  },
  advisory: {
    labelFa: 'هشدار مقدماتی',
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
  criticalT10,
  criticalTemp90,
  criticalT90,
}) => {
  const effectiveTc10 = criticalTemp10 ?? criticalT10;
  const effectiveTc90 = criticalTemp90 ?? criticalT90;
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

                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    {night.illustrative_only ? (
                      <span
                        className="badge-illustrative"
                        style={{
                          padding: '2px 8px',
                          borderRadius: '10px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          backgroundColor: '#fef3c7',
                          color: '#92400e',
                          border: '1px solid #f59e0b',
                        }}
                      >
                        مقادیر نمایشی
                      </span>
                    ) : (
                      <span
                        className="badge-source"
                        style={{
                          padding: '2px 8px',
                          borderRadius: '10px',
                          fontSize: '0.75rem',
                          fontWeight: 500,
                          backgroundColor: '#e0f2fe',
                          color: '#0369a1',
                          border: '1px solid #7dd3fc',
                        }}
                      >
                        {night.active_rule_source || '[S1/S2] Hokmabadi'}
                      </span>
                    )}

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
                        {night.is_partial_night || (night.window_coverage !== undefined && night.window_coverage < 1.0)
                          ? 'دمای کمینه مزرعه (شب ناقص)'
                          : 'دمای کمینه نهایی مزرعه'}
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: meta.text }}>
                        <FormattedNumber value={night.adjusted_min_temp_c} unit="°C" />
                      </div>
                      {(night.is_partial_night || (night.window_coverage !== undefined && night.window_coverage < 1.0)) && (
                        <div style={{ fontSize: '0.7rem', color: '#b45309', marginTop: '2px', fontWeight: 600 }}>
                          ⚠️ شب ناقص (پوشش {Math.round((night.window_coverage || 0) * 100)}٪)
                        </div>
                      )}
                    </div>

                    <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }}>
                      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                        {effectiveTc90 !== undefined && effectiveTc90 !== null
                          ? `مدت زیر آستانه ۱۰٪ (${effectiveTc10 !== undefined ? `${effectiveTc10}°` : 'Tc10'})`
                          : `مدت زیر آستانه بحرانی (${effectiveTc10 !== undefined ? `${effectiveTc10}°C` : 'Tc'})`}
                      </div>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>
                        <FormattedNumber value={night.duration_below_t10_h} unit="h" digits={1} />
                      </div>
                    </div>

                    {effectiveTc90 !== undefined && effectiveTc90 !== null && (
                      <div style={{ backgroundColor: '#f8fafc', padding: '10px', borderRadius: '6px' }} data-testid="duration-t90-card">
                        <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: '4px' }}>
                          مدت زیر آستانه ۹۰٪ ({effectiveTc90}°)
                        </div>
                        <div style={{ fontSize: '1.1rem', fontWeight: 700, color: night.duration_below_t90_h > 0 ? '#b91c1c' : '#334155' }}>
                          <FormattedNumber value={night.duration_below_t90_h} unit="h" digits={1} />
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Sourced Duration Exposure & Rule Explanation (E8) */}
                  <div
                    style={{
                      backgroundColor: '#f1f5f9',
                      borderRight: '4px solid #0284c7',
                      padding: '10px 14px',
                      borderRadius: '6px',
                      marginBottom: '14px',
                      fontSize: '0.85rem',
                    }}
                    data-testid="duration-rule-display"
                  >
                    <div style={{ fontWeight: 600, color: '#0369a1', marginBottom: '4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>⏱️ تحلیل تداوم سرما زیر آستانه خسارت:</span>
                      {night.min_temp_timestamp_local && (
                        <span style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 'normal' }}>
                          لحظه وقوع کمینه: {night.min_temp_timestamp_local} (به وقت محلی)
                        </span>
                      )}
                    </div>

                    <div style={{ fontWeight: 600, color: '#0f172a', marginBottom: '4px' }}>
                      {night.duration_below_t10_h > 0 ? (
                        <span>
                          <FormattedNumber value={night.duration_below_t10_h} /> ساعت زیر آستانه <FormattedNumber value={effectiveTc10 ?? 0} unit="°C" />
                        </span>
                      ) : (
                        <span>هیچ شب زیر آستانه نیست</span>
                      )}
                    </div>

                    <div style={{ fontSize: '0.82rem', color: '#334155', lineHeight: '1.4' }}>
                      {night.duration_rule_explanation_fa || 'برای این مرحله داده منتشرشده‌ای برای مدت ماندن زیر آستانه وجود ندارد؛ دسته‌بندی فقط بر اساس دما است'}
                    </div>

                    {night.active_rule_source && (
                      <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#64748b' }}>
                        📚 استناد علمی: {night.active_rule_source}
                      </div>
                    )}

                    {night.conflicting_published_value !== undefined && night.conflicting_published_value !== null && (
                      <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#b45309', backgroundColor: '#fef3c7', padding: '4px 8px', borderRadius: '4px' }}>
                        ⚠️ {night.conflicting_value_note_fa || `مقدار متعارض منتشرشده در سایر منابع: ${night.conflicting_published_value}°C`}
                      </div>
                    )}
                  </div>

                  {/* Frost Regime Badge & Advice (E9) */}
                  {night.regime && (
                    <div
                      data-testid="regime-badge"
                      style={{
                        marginBottom: '14px',
                        padding: '10px 14px',
                        borderRadius: '6px',
                        backgroundColor: night.regime.regime === 'radiative' ? '#eff6ff' : night.regime.regime === 'advective' ? '#fef2f2' : '#f8fafc',
                        border: `1px solid ${night.regime.regime === 'radiative' ? '#93c5fd' : night.regime.regime === 'advective' ? '#fca5a5' : '#cbd5e1'}`,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.85rem', color: night.regime.regime === 'radiative' ? '#1d4ed8' : '#b91c1c' }}>
                          رژیم یخبندان: {night.regime.regime_fa}
                        </span>
                        {night.regime.review_flag && (
                          <span style={{ fontSize: '0.72rem', color: '#b45309', backgroundColor: '#fef3c7', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
                            {night.regime.review_flag}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: '#334155', lineHeight: '1.4' }}>
                        {night.regime.advice_fa}
                      </div>
                    </div>
                  )}

                  {/* Factor Modifiers Additive Celsius Bars (E9) */}
                  {night.factor_modifiers && night.factor_modifiers.length > 0 && (
                    <div
                      style={{
                        marginBottom: '14px',
                        padding: '10px 14px',
                        backgroundColor: '#ffffff',
                        border: '1px solid #e2e8f0',
                        borderRadius: '6px',
                      }}
                      data-testid="factor-modifiers-container"
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155' }}>
                          📊 تعدیل‌کننده‌های دمای مؤثر (Factor Register):
                        </span>
                        {night.applied_protective_credit_c !== undefined && (
                          <span style={{ fontSize: '0.75rem', color: '#15803d', fontWeight: 600 }}>
                            تخفیف حفاظتی اعمال‌شده: {night.applied_protective_credit_c.toFixed(1)}°C (سقف مجاز ۱.۰°C)
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {night.factor_modifiers.map((mod) => {
                          const isAggravating = mod.direction === 'aggravating';
                          const isApplied = mod.applied;
                          const barColor = !isApplied ? '#94a3b8' : isAggravating ? '#ef4444' : '#10b981';
                          const borderStyle = !isApplied ? '1px dashed #94a3b8' : `1px solid ${isAggravating ? '#fca5a5' : '#86efac'}`;
                          const bgColor = !isApplied ? '#f8fafc' : isAggravating ? '#fef2f2' : '#f0fdf4';

                          return (
                            <div
                              key={mod.id}
                              data-testid={`factor-mod-${mod.id}`}
                              title={mod.tooltip_fa || undefined}
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                padding: '6px 10px',
                                borderRadius: '4px',
                                border: borderStyle,
                                backgroundColor: bgColor,
                                fontSize: '0.8rem',
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <span style={{ fontWeight: 600 }}>{mod.name_fa}</span>
                                <span style={{ fontSize: '0.72rem', color: '#64748b' }}>({mod.data_source})</span>
                                {!isApplied && (
                                  <span
                                    style={{
                                      fontSize: '0.68rem',
                                      backgroundColor: '#e2e8f0',
                                      color: '#475569',
                                      padding: '1px 6px',
                                      borderRadius: '3px',
                                    }}
                                  >
                                    حفاظت احتمالی (اعمال‌نشده)
                                  </span>
                                )}
                              </div>

                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontWeight: 700, color: barColor, direction: 'ltr' }}>
                                  {isAggravating ? '+' : '-'}{mod.effect_c.toFixed(1)}°C
                                </span>
                                {mod.tooltip_fa && (
                                  <span
                                    title={mod.tooltip_fa}
                                    style={{ cursor: 'help', fontSize: '0.85rem' }}
                                  >
                                    ℹ️
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      <div style={{ marginTop: '8px', fontSize: '0.75rem', color: '#64748b', fontStyle: 'italic' }}>
                        💡 بادشکن‌ها نباید مسیر تخلیه هوای سرد رو به پایین‌دست (Cold-Air Drainage) را مسدود کنند.
                      </div>
                    </div>
                  )}

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
