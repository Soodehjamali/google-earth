import { Link, useSearchParams } from 'react-router-dom';
import { DOMAIN_PAGE_CONFIGS } from './domainPages';
import { domainMetaFor } from './parse';

/**
 * Analysis-domain navigation cards (Prompt 2: inter-domain navigation).
 * Links only to registered domain routes from the locked configs.
 * Preserves analysis_id query parameter when a saved report is active.
 */
export default function DomainNavCards() {
  const [searchParams] = useSearchParams();
  const analysisId = searchParams.get('analysis_id');
  const configs = Object.values(DOMAIN_PAGE_CONFIGS);

  return (
    <div className="card mb-3">
      <div className="card-header">
        <span className="card-title">🗂️ حوزه‌های تحلیل — Analysis Domains</span>
      </div>
      <div className="card-body">
        <div className="kpi-grid">
          {configs.map((config) => {
            const meta = domainMetaFor(config.metaKey);
            const targetPath = analysisId
              ? `${config.routePath}?analysis_id=${encodeURIComponent(analysisId)}`
              : config.routePath;

            return (
              <Link
                key={config.pageKey}
                to={targetPath}
                className="btn btn-secondary"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  justifyContent: 'flex-start',
                }}
              >
                <span aria-hidden="true">{meta.icon}</span>
                <span>{meta.labelFa} — {meta.label}</span>
              </Link>
            );
          })}
        </div>
        <div className="text-muted" style={{ fontSize: '0.8rem' }}>
          جابه‌جایی بین حوزه‌های تحلیل — هر حوزه شاخص‌های مربوطه را از گزارش انتخاب‌شده نمایش می‌دهد.
        </div>
      </div>
    </div>
  );
}
