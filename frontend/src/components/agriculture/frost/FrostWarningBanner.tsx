import React from 'react';
import FormattedNumber from '../../common/FormattedNumber';

interface FrostWarningBannerProps {
  thresholdsVerified: boolean;
  cropNameFa?: string;
  stageNameFa?: string;
  t10?: number;
  t90?: number;
}

export const FrostWarningBanner: React.FC<FrostWarningBannerProps> = ({
  thresholdsVerified,
  cropNameFa = 'پسته',
  stageNameFa = 'اوایل گلدهی',
  t10,
  t90,
}) => {
  if (thresholdsVerified) return null;

  return (
    <div
      className="frost-warning-banner"
      data-testid="thresholds-unverified-banner"
      style={{
        backgroundColor: '#fffbeb',
        border: '1px solid #f59e0b',
        borderRadius: '8px',
        padding: '12px 16px',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px',
      }}
    >
      <span style={{ fontSize: '1.5rem', lineHeight: 1 }} aria-hidden="true">
        ⚠️
      </span>
      <div style={{ flex: 1, fontSize: '0.9rem', color: '#92400e' }}>
        <div style={{ fontWeight: 700, marginBottom: '4px' }}>
          توجه مهم (آستانه‌ها تأیید نشده): داده‌های پیش‌فرض آزمایشی فعال هستند
        </div>
        <div>
          آستانه‌های دمایی حساسیت فنولوژیکی برای محصول <strong>{cropNameFa}</strong> در مرحله{' '}
          <strong>{stageNameFa}</strong> هنوز توسط کارشناس محلی تأیید نشده‌اند (Placeholder).
          {t10 !== undefined && t90 !== undefined && (
            <span style={{ marginRight: '6px' }}>
              آستانه‌های فعلی: ۱۰٪ خسارت در{' '}
              <FormattedNumber value={t10} unit="°C" /> و ۹۰٪ خسارت در{' '}
              <FormattedNumber value={t90} unit="°C" /> است.
            </span>
          )}
          این سامانه صرفاً جنبه مشورتی داشته و پیش از هرگونه اقدام میدانی باید آستانه‌های منطقه کالیبره شوند.
        </div>
      </div>
    </div>
  );
};

export default FrostWarningBanner;
