import React, { useState } from 'react';
import { mapErrorToPersian } from './errorMapping.ts';

export interface ErrorBannerProps {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}

/**
 * Production-ready Agricultural Error Banner.
 * Respects farmer-first design:
 * - Clear Persian message & actionable resolution advice.
 * - Stable error code badge.
 * - Raw technical exception details completely hidden behind a Developer Mode toggle.
 */
export const ErrorBanner: React.FC<ErrorBannerProps> = ({ error, onRetry, className = '' }) => {
  const [isDevMode, setIsDevMode] = useState(false);

  if (!error) return null;

  const mapping = mapErrorToPersian(error);

  return (
    <div
      className={`error-banner ${className}`}
      data-testid="error-banner"
      style={{
        background: '#fff5f5',
        border: '1px solid #fed7d7',
        borderRadius: 8,
        padding: '12px 16px',
        margin: '12px 0',
        direction: 'rtl',
        color: '#2d3748',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ fontSize: '1.4rem', lineHeight: 1 }}>⚠️</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: '0.96rem', color: '#c53030', marginBottom: 2 }}>
              {mapping.titleFa}
            </div>
            <div style={{ fontSize: '0.86rem', color: '#4a5568', lineHeight: 1.5 }}>
              {mapping.messageFa}
            </div>
            <div style={{ fontSize: '0.8rem', color: '#2b6cb0', marginTop: 4 }}>
              💡 <strong>راهکار پیشنهادی:</strong> {mapping.suggestedActionFa}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
          <span
            style={{
              fontSize: '0.72rem',
              fontFamily: 'monospace',
              padding: '2px 6px',
              borderRadius: 4,
              background: '#edf2f7',
              color: '#4a5568',
              direction: 'ltr',
            }}
          >
            {mapping.code}
          </span>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="btn btn-sm"
              style={{
                fontSize: '0.78rem',
                padding: '4px 10px',
                background: '#e53e3e',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                cursor: 'pointer',
              }}
            >
              🔄 تلاش مجدد
            </button>
          )}
        </div>
      </div>

      {/* Developer Mode Toggle */}
      <div style={{ marginTop: 10, borderTop: '1px solid #fed7d7', paddingTop: 6, display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={() => setIsDevMode(!isDevMode)}
          style={{
            background: 'none',
            border: 'none',
            color: '#718096',
            fontSize: '0.72rem',
            cursor: 'pointer',
            textDecoration: 'underline',
          }}
        >
          {isDevMode ? '✕ بستن جزئیات فنی' : '⚙️ جزئیات فنی (Developer Mode)'}
        </button>
      </div>

      {isDevMode && (
        <div
          data-testid="error-dev-details"
          style={{
            marginTop: 8,
            padding: 8,
            background: '#2d3748',
            color: '#e2e8f0',
            borderRadius: 6,
            fontSize: '0.75rem',
            fontFamily: 'monospace',
            direction: 'ltr',
            textAlign: 'left',
            maxHeight: 180,
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
          }}
        >
          <div style={{ color: '#68d391', marginBottom: 4 }}>[CODE]: {mapping.code}</div>
          {mapping.rawError && <div style={{ marginBottom: 4 }}>[ERROR]: {mapping.rawError}</div>}
          {mapping.technicalDetails && <div>[DETAILS]: {mapping.technicalDetails}</div>}
        </div>
      )}
    </div>
  );
};

export default ErrorBanner;
