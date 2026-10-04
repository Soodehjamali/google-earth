import { Link } from 'react-router-dom';

interface ComprehensiveNoticeProps {
  /** Comprehensive route, e.g. '/agriculture/soil'. */
  to: string;
  /** Link label, e.g. 'مشاهده تحلیل جامع'. */
  linkLabelFa: string;
  linkLabelEn?: string;
  /** Optional override of the neutral lead-in text. */
  noteFa?: string;
  noteEn?: string;
}

/**
 * Small neutral pointer from a legacy analysis page to its
 * comprehensive counterpart. Informational only: no redirects,
 * no API calls, no removed functionality.
 */
export default function ComprehensiveNotice({
  to,
  linkLabelFa,
  linkLabelEn,
  noteFa = 'نسخه جامع تحلیل کشاورزی در دسترس است.',
  noteEn = 'A comprehensive analysis version is available.',
}: ComprehensiveNoticeProps) {
  return (
    <div className="card mb-3" style={{ borderRightColor: 'var(--color-info)' }}>
      <div className="card-body">
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)' }}>
          📡 <strong>{noteFa}</strong>{' '}
          <span className="text-muted">{noteEn}</span>{' '}
          <Link to={to}>
            {linkLabelFa}
            {linkLabelEn ? ` — ${linkLabelEn}` : ''} ←
          </Link>
        </p>
      </div>
    </div>
  );
}
