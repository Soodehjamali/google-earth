import { useCallback, useEffect, useState } from 'react';
import { agricultureApi } from '../../api/agriculture';
import type { AgricultureHealthResponse } from '../../types';
import { normalizeHealth } from './parse';

/**
 * System status for the Comprehensive subsystem (F1 §16).
 * Displays actual health fields — never a score. Fetches on mount
 * and on explicit refresh only (no aggressive polling).
 */
export default function AgricultureHealthCard() {
  const [health, setHealth] = useState<AgricultureHealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const loadHealth = useCallback(async () => {
    setChecking(true);
    setError(null);
    try {
      const raw: unknown = await agricultureApi.health();
      const normalized = normalizeHealth(raw);
      if (!normalized) {
        setError('پاسخ سلامت نامعتبر — Invalid health response');
        setHealth(null);
        return;
      }
      setHealth(normalized);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در دریافت وضعیت سامانه');
      setHealth(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  const tone =
    health?.status === 'ok'
      ? 'good'
      : health
        ? 'warning'
        : 'danger';

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">⚙️ وضعیت سامانه — System Status</span>
        <span className={`badge badge-${tone}`}>
          {checking ? 'checking…' : (health?.status ?? 'unknown')}
        </span>
      </div>
      <div className="card-body">
        {error && (
          <div className="error-banner">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}
        {health && (
          <div className="form-row" style={{ flexWrap: 'wrap', gap: '16px' }}>
            <div>
              <span className="text-muted">شاخص‌های ثبت‌شده: </span>
              <strong>{health.metrics_registered}</strong>
            </div>
            <div>
              <span className="text-muted">لایه شواهد: </span>
              <strong>{health.evidence_layer}</strong>
            </div>
            <div>
              <span className="text-muted">لایه ترکیب: </span>
              <strong>{health.synthesis_layer}</strong>
            </div>
            {health.message && (
              <div>
                <span className="text-muted">پیام: </span>
                <strong>{health.message}</strong>
              </div>
            )}
          </div>
        )}
        <button
          className="btn btn-sm btn-secondary mt-2"
          onClick={() => void loadHealth()}
          disabled={checking}
        >
          {checking ? 'در حال بررسی…' : '↻ به‌روزرسانی وضعیت'}
        </button>
      </div>
    </div>
  );
}
