interface LimitationsBannerProps {
  limitations: readonly unknown[];
  title?: string;
}

/**
 * Shared limitations renderer (F1). Limitations are always shown —
 * never hidden to make the UI look cleaner.
 */
export default function LimitationsBanner({
  limitations,
  title = 'محدودیت‌ها',
}: LimitationsBannerProps) {
  const items = limitations.filter(
    (entry): entry is string => typeof entry === 'string' && entry.length > 0,
  );
  if (items.length === 0) return null;
  return (
    <div className="info-banner mt-2">
      <span>ℹ️</span>
      <div>
        <strong>{title}:</strong>
        <ul style={{ margin: '4px 0 0 0', paddingRight: '16px' }}>
          {items.map((lim, i) => (
            <li key={i}>{lim}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * Static dataset-scope notes (Phase 0B §10). Fixed explanatory text —
 * never presented as a runtime measurement from the API.
 */
export function ScopeBanner() {
  return (
    <div className="info-banner mt-2">
      <span>🛰️</span>
      <div>
        <strong>دامنه ثابت مجموعه‌داده‌ها — Fixed dataset scope:</strong>
        <ul style={{ margin: '4px 0 0 0', paddingRight: '16px' }}>
          <li>Crop context is a fixed-scope 2021 product snapshot.</li>
          <li>Terrain and soil retention surfaces are static products.</li>
          <li>Land cover is an annual product; the requested year follows the analysis dates.</li>
        </ul>
      </div>
    </div>
  );
}
