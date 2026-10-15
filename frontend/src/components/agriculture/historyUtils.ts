/**
 * Pure helper utilities for Agriculture Persistent History (Phase P0-HISTORY).
 *
 * Presentation-layer formatting, status and sufficiency mapping.
 * Pure TypeScript without JSX, compatible with Node test runner.
 */

export function formatPersianTimestamp(isoTimestamp: string | null | undefined): string {
  if (!isoTimestamp) return '—';
  try {
    const d = new Date(isoTimestamp);
    if (Number.isNaN(d.getTime())) return isoTimestamp;
    const datePart = d.toLocaleDateString('fa-IR-u-ca-persian', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
    const timePart = d.toLocaleTimeString('fa-IR-u-ca-persian', {
      hour: '2-digit',
      minute: '2-digit',
    });
    return `${datePart} - ساعت ${timePart}`;
  } catch {
    return isoTimestamp;
  }
}

export function translateSufficiencyFa(level: string | null | undefined): { text: string; badgeClass: string } {
  switch (level?.toLowerCase()) {
    case 'sufficient':
      return { text: 'شواهد کافی', badgeClass: 'badge-good' };
    case 'moderate':
      return { text: 'شواهد متوسط', badgeClass: 'badge-warning' };
    case 'insufficient':
      return { text: 'شواهد ناکافی', badgeClass: 'badge-danger' };
    default:
      return { text: 'نامشخص', badgeClass: 'badge-secondary' };
  }
}

export function translateStatusFa(status: string | null | undefined): { text: string; badgeClass: string } {
  switch (status?.toLowerCase()) {
    case 'completed':
      return { text: 'تکمیل‌شده', badgeClass: 'badge-good' };
    case 'running':
      return { text: 'در حال پردازش', badgeClass: 'badge-info' };
    case 'failed':
      return { text: 'ناموفق', badgeClass: 'badge-danger' };
    default:
      return { text: status || 'نامشخص', badgeClass: 'badge-secondary' };
  }
}
