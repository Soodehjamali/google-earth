/**
 * Agriculture History Subsystem (Phase P0-HISTORY).
 *
 * Displays permanently persisted agricultural analysis runs stored in PostgreSQL.
 * Enables zero-GEE report retrieval, explicit deletion confirmation,
 * and pure Jalali date presentation with Persian numerals.
 */
import { useEffect, useState, useMemo, useCallback } from 'react';
import type { AgricultureHistoryItemSummary } from '../../types';
import { agricultureApi } from '../../api/agriculture';
import {
  formatPersianDateRange,
  toPersianDigits,
} from './persianDate';
import {
  formatPersianTimestamp,
  translateSufficiencyFa,
  translateStatusFa,
} from './historyUtils';

interface AgricultureHistorySectionProps {
  onSelectAnalysis: (analysisId: string) => void;
  activeAnalysisId?: string | null;
  className?: string;
}


export default function AgricultureHistorySection({
  onSelectAnalysis,
  activeAnalysisId,
  className = '',
}: AgricultureHistorySectionProps) {
  const [items, setItems] = useState<AgricultureHistoryItemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [itemToDelete, setItemToDelete] = useState<AgricultureHistoryItemSummary | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await agricultureApi.listHistory(0, 50);
      setItems(res.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در بارگذاری تاریخچه تحلیل‌ها');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleDeleteConfirm = async () => {
    if (!itemToDelete) return;
    const targetId = itemToDelete.id;
    setDeletingId(targetId);
    try {
      await agricultureApi.deleteHistoryItem(targetId);
      setItems((prev) => prev.filter((item) => item.id !== targetId));
      setItemToDelete(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'خطا در حذف تحلیل');
    } finally {
      setDeletingId(null);
    }
  };

  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return items;
    const q = searchQuery.trim().toLowerCase();
    return items.filter((item) => {
      const nameMatch = item.location_name?.toLowerCase().includes(q);
      const idMatch = item.id.toLowerCase().includes(q);
      return Boolean(nameMatch || idMatch);
    });
  }, [items, searchQuery]);

  return (
    <div className={`card ${className}`} data-testid="agriculture-history-section">
      <div className="card-header d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2">
          <span style={{ fontSize: '1.2rem' }}>📜</span>
          <span className="card-title" style={{ fontSize: '1.05rem', fontWeight: 600 }}>
            تاریخچه دائمی تحلیل‌های باغ و اراضی (Persistent Analysis History)
          </span>
          <span className="badge badge-info" style={{ fontSize: '0.8rem' }}>
            {toPersianDigits(items.length.toString())} تحلیل ذخیره‌شده
          </span>
        </div>
        <div className="d-flex align-items-center gap-2">
          <input
            type="text"
            className="form-control form-control-sm"
            placeholder="جستجو بر اساس نام باغ یا شناسه..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{ minWidth: '220px', fontSize: '0.85rem' }}
          />
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={fetchHistory}
            disabled={loading}
            title="بروزرسانی فهرست"
          >
            🔄 {loading ? '...' : 'بروزرسانی'}
          </button>
        </div>
      </div>

      <div className="card-body">
        {loading && (
          <div className="text-center p-4">
            <div className="spinner-border text-primary" role="status" />
            <p className="mt-2 text-muted" style={{ fontSize: '0.9rem' }}>
              در حال بارگذاری تاریخچه تحلیل‌های ذخیره‌شده از پایگاه داده...
            </p>
          </div>
        )}

        {error && (
          <div className="alert alert-danger d-flex justify-content-between align-items-center">
            <span>⚠️ {error}</span>
            <button
              type="button"
              className="btn btn-sm btn-outline-danger"
              onClick={fetchHistory}
            >
              تلاش مجدد
            </button>
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="empty-state text-center p-4" style={{ backgroundColor: '#fcfcfc', borderRadius: '8px' }}>
            <div style={{ fontSize: '2.2rem', marginBottom: '8px' }}>📋</div>
            <div style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}>
              هنوز هیچ تحلیلی در تاریخچه ذخیره نشده است
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
              به محض اجرای اولین تحلیل روی یک قطعه زمین یا باغ، نتیجه کامل آن به صورت دائمی در دیتابیس ثبت شده و از این بخش قابل بازخوانی سریع خواهد بود.
            </div>
          </div>
        )}

        {!loading && !error && items.length > 0 && filteredItems.length === 0 && (
          <div className="text-center p-3 text-muted" style={{ fontSize: '0.9rem' }}>
            هیچ موردی با عبارت جستجو یافت نشد.
          </div>
        )}

        {!loading && !error && filteredItems.length > 0 && (
          <div className="table-responsive">
            <table className="table table-hover table-striped mb-0" style={{ fontSize: '0.88rem' }}>
              <thead>
                <tr style={{ backgroundColor: 'var(--color-bg-secondary)' }}>
                  <th style={{ width: '4%' }}>#</th>
                  <th style={{ width: '22%' }}>باغ / موقعیت جغرافیایی</th>
                  <th style={{ width: '20%' }}>بازه تحلیل (شمسی)</th>
                  <th style={{ width: '18%' }}>زمان اجرا</th>
                  <th style={{ width: '12%' }}>وضعیت</th>
                  <th style={{ width: '12%' }}>کفایت شواهد</th>
                  <th style={{ width: '12%', textAlign: 'center' }}>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item, index) => {
                  const statusInfo = translateStatusFa(item.status);
                  const suffInfo = translateSufficiencyFa(item.overall_sufficiency);
                  const isCurrent = activeAnalysisId === item.id;

                  return (
                    <tr
                      key={item.id}
                      style={{
                        backgroundColor: isCurrent ? 'rgba(46, 125, 50, 0.08)' : undefined,
                        fontWeight: isCurrent ? 600 : undefined,
                      }}
                    >
                      <td>{toPersianDigits((index + 1).toString())}</td>
                      <td>
                        <div style={{ fontWeight: 600, color: '#2e7d32' }}>
                          {item.location_name?.trim() || 'لوکیشن بدون نام'}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: '#757575', marginTop: '2px' }}>
                          <span>نوع: {item.geometry_type === 'Polygon' ? 'چندضلعی' : 'نقطه'}</span>
                          {item.area_sq_meters && (
                            <span style={{ marginRight: '8px' }}>
                              | مساحت: {toPersianDigits((item.area_sq_meters / 10000).toFixed(2))} هکتار
                            </span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div>{formatPersianDateRange(item.start_date, item.end_date)}</div>
                        <div style={{ fontSize: '0.72rem', color: '#9e9e9e', direction: 'ltr', textAlign: 'right' }}>
                          {item.start_date} → {item.end_date}
                        </div>
                      </td>
                      <td>
                        <div style={{ fontSize: '0.82rem' }}>{formatPersianTimestamp(item.created_at)}</div>
                      </td>
                      <td>
                        <span className={`badge ${statusInfo.badgeClass}`}>
                          {statusInfo.text}
                        </span>
                        {item.error_message && (
                          <div style={{ fontSize: '0.72rem', color: '#d32f2f', marginTop: '2px' }} title={item.error_message}>
                            {item.error_message.slice(0, 30)}...
                          </div>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${suffInfo.badgeClass}`}>
                          {suffInfo.text}
                        </span>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <div className="btn-group btn-group-sm" role="group">
                          <button
                            type="button"
                            className={`btn btn-sm ${isCurrent ? 'btn-success' : 'btn-primary'}`}
                            onClick={() => onSelectAnalysis(item.id)}
                            disabled={item.status !== 'completed'}
                            title="مشاهده گزارش کامل (بدون اجرای مجدد GEE)"
                          >
                            {isCurrent ? '✓ فعال' : '👁️ مشاهده'}
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-outline-danger"
                            onClick={() => setItemToDelete(item)}
                            disabled={deletingId === item.id}
                            title="حذف از تاریخچه"
                          >
                            🗑️
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {itemToDelete && (
        <div
          className="modal-backdrop-custom"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1050,
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '460px',
              width: '90%',
              backgroundColor: '#fff',
              boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
            }}
          >
            <div className="card-header bg-danger text-white d-flex justify-content-between align-items-center">
              <span style={{ fontWeight: 600 }}>⚠️ تأیید حذف تحلیل از تاریخچه</span>
              <button
                type="button"
                className="btn-close btn-close-white"
                onClick={() => setItemToDelete(null)}
              />
            </div>
            <div className="card-body">
              <p style={{ lineHeight: 1.7, fontSize: '0.9rem' }}>
                آیا از حذف دائم تحلیل برای{' '}
                <strong>{itemToDelete.location_name || 'این قطعه'}</strong> مربوط به بازه زمانی{' '}
                <strong>{formatPersianDateRange(itemToDelete.start_date, itemToDelete.end_date)}</strong>{' '}
                اطمینان دارید؟
              </p>
              <div
                style={{
                  backgroundColor: '#fff3e0',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '0.8rem',
                  color: '#e65100',
                  marginTop: '10px',
                }}
              >
                توجه: این اقدام صرفاً رکورد انتخاب‌شده را حذف می‌کند و غیرقابل بازگشت است.
              </div>
            </div>
            <div className="card-footer d-flex justify-content-end gap-2">
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setItemToDelete(null)}
                disabled={deletingId === itemToDelete.id}
              >
                انصراف
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={handleDeleteConfirm}
                disabled={deletingId === itemToDelete.id}
              >
                {deletingId === itemToDelete.id ? 'در حال حذف...' : 'تأیید و حذف'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
