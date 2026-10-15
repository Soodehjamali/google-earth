/**
 * Tests for P-AGRI-HIST-10Y (10-Year Same-Period Historical Comparison)
 * and P-AGRI-MAP-SWIPE (Interactive Current Orchard ↔ Evidence Heatmap Swipe).
 * Runs with Node's built-in test runner:
 *   node --test src/components/agriculture/__tests__/hist10y_and_swipe.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { formatPersianYear, getJalaliYear } from '../persianDate.ts';

const here = dirname(fileURLToPath(import.meta.url));
const agricultureDir = dirname(here);
const srcDir = dirname(dirname(agricultureDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('P-AGRI-HIST-10Y: 10-Year Same-Period Historical Comparison', () => {
  it('1. exports all required historical comparison types and statuses', () => {
    const typesSrc = readSource('types/index.ts');
    assert.match(typesSrc, /type HistoricalYearStatus = 'current' \| 'available' \| 'partial' \| 'unavailable'/);
    assert.match(typesSrc, /interface HistoricalComparisonRequest/);
    assert.match(typesSrc, /interface HistoricalYearRecord/);
    assert.match(typesSrc, /interface HistoricalMetricTrend/);
    assert.match(typesSrc, /interface HistoricalComparisonResponse/);
  });

  it('2. provides getHistoricalComparison API method targeting correct endpoint', () => {
    const apiSrc = readSource('api/agriculture.ts');
    assert.match(apiSrc, /getHistoricalComparison/);
    assert.match(apiSrc, /\/agriculture\/historical-comparison/);
  });

  it('3. Historical10YearSection honors 4 status badges and never converts null to 0', () => {
    const compSrc = readSource('components/agriculture/Historical10YearSection.tsx');
    assert.match(compSrc, /current:\s*\{[^}]*badgeClass:\s*'badge-primary'/);
    assert.match(compSrc, /available:\s*\{[^}]*badgeClass:\s*'badge-good'/);
    assert.match(compSrc, /partial:\s*\{[^}]*badgeClass:\s*'badge-warning'/);
    assert.match(compSrc, /unavailable:\s*\{[^}]*badgeClass:\s*'badge-unavailable'/);
    // Never renders 0 for missing values
    assert.match(compSrc, /isValAvailable\s*\?\s*formatEvidenceValue\(val,\s*3\)\s*:\s*'—'/);
  });

  it('4. enforces strict non-negotiable scientific safety gates (Soil & Yield)', () => {
    const compSrc = readSource('components/agriculture/Historical10YearSection.tsx');
    // Soil chemical history blocked
    assert.match(compSrc, /Soil historical chemical data unavailable/);
    // Yield uncalibrated blocked
    assert.match(compSrc, /Uncalibrated yield trend deactivated/);
  });

  it('5. presents neutral scientific trend directions without causal claims', () => {
    const compSrc = readSource('components/agriculture/Historical10YearSection.tsx');
    assert.match(compSrc, /improving:/);
    assert.match(compSrc, /declining:/);
    assert.match(compSrc, /stable:/);
    assert.match(compSrc, /variable:/);
    assert.match(compSrc, /insufficient_evidence:/);
  });

  it('6. converts Gregorian start dates to accurate Jalali years with Persian digits (never naive year - 621)', () => {
    // 2026-06-01 -> ۱۴۰۵ (Jalali 1405)
    assert.equal(formatPersianYear('2026-06-01'), '۱۴۰۵');
    assert.equal(getJalaliYear('2026-06-01'), 1405);

    // 2025-06-01 -> ۱۴۰۴ (Jalali 1404)
    assert.equal(formatPersianYear('2025-06-01'), '۱۴۰۴');
    assert.equal(getJalaliYear('2025-06-01'), 1404);

    // 2024-06-01 -> ۱۴۰۳ (Jalali 1403)
    assert.equal(formatPersianYear('2024-06-01'), '۱۴۰۳');
    assert.equal(getJalaliYear('2024-06-01'), 1403);

    // Non-naive verification: Jan 2026 is still Jalali 1404 before Nowruz (2026 - 621 would naively give 1405!)
    assert.equal(formatPersianYear('2026-01-15'), '۱۴۰۴');
    assert.equal(getJalaliYear('2026-01-15'), 1404);
  });

  it('7. Historical10YearSection presents Jalali year and date range while preserving Gregorian API contracts', () => {
    const compSrc = readSource('components/agriculture/Historical10YearSection.tsx');
    // Header explicitly indicates Jalali
    assert.match(compSrc, /سال \(جلالی\)/);
    // Year cell derives Jalali year from row.start_date
    assert.match(compSrc, /formatPersianYear\(row\.start_date,\s*row\.year\)/);
    // Same-period window subtext formats date range in Jalali
    assert.match(compSrc, /formatPersianDateRange\(row\.start_date,\s*row\.end_date\)/);
    // Current period card uses formatPersianYear
    assert.match(compSrc, /مقدار دوره جاری \(\{data\.years\[0\] \? formatPersianYear\(data\.years\[0\]\.start_date/);

    // API contract and request remain strictly Gregorian ISO
    const typesSrc = readSource('types/index.ts');
    assert.match(typesSrc, /start_date:\s*string/);
    assert.match(typesSrc, /end_date:\s*string/);
    const apiSrc = readSource('api/agriculture.ts');
    assert.match(apiSrc, /getHistoricalComparison/);
  });
});

describe('P-AGRI-MAP-SWIPE: Interactive Current Orchard ↔ Evidence Heatmap Swipe', () => {
  it('1. OrchardHeatmapSwipeSection component exists and contains draggable divider', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    assert.match(compSrc, /dividerPercent/);
    assert.match(compSrc, /handleDragStart/);
    assert.match(compSrc, /clipPath:\s*`inset\(0\s*0\s*0\s*\$\{dividerPercent\}%\)`/);
  });

  it('2. Dual maps are synchronized in real-time (center, zoom, pitch, bearing) and have nonzero dimensions with ResizeObserver', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    assert.match(compSrc, /mapLeft/);
    assert.match(compSrc, /mapRight/);
    assert.match(compSrc, /height:\s*460/);
    assert.match(compSrc, /ResizeObserver/);
    assert.match(compSrc, /jumpTo/);
    assert.match(compSrc, /getCenter/);
    assert.match(compSrc, /getZoom/);
    assert.match(compSrc, /getBearing/);
    assert.match(compSrc, /getPitch/);
  });

  it('3. exposes all 13 real supported spatial metrics (vegetation, thermal, radar, moisture, and 6 SoilGrids layers)', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    for (const metric of [
      'ndvi',
      'ndmi',
      'ndre',
      'msi',
      'lst_day',
      'sar_vh',
      'soil_moisture',
      'soil_soc',
      'soil_ph',
      'soil_clay',
      'soil_sand',
      'soil_cec',
      'soil_nitrogen',
    ]) {
      assert.match(compSrc, new RegExp(`key:\\s*'${metric}'`));
    }
    assert.match(compSrc, /Heatmap unavailable for this indicator/);
  });

  it('4. contains zero synthetic rasters, canvas noise or fake imagery generators', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    assert.doesNotMatch(compSrc, /Math\.random/);
    assert.doesNotMatch(compSrc, /createImageData/);
    assert.doesNotMatch(compSrc, /mockTile/);
  });

  it('5. re-initializes dual maps when transitioning from on-demand card (userRequested) and includes OSM foundation underlays', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    // Must include userRequested in map initialization useEffect dependencies so clicking on-demand button mounts maps
    assert.match(compSrc, /\},\s*\[userRequested,\s*disableAutoFetch,\s*initialCenter,\s*syncGeometryOverlay\]\)/);
    // Both maps include OSM foundation base/underlay so panels are never blank white voids
    assert.match(compSrc, /id:\s*'osm-base'/);
    assert.match(compSrc, /id:\s*'osm-underlay'/);
    assert.match(compSrc, /id:\s*'satellite-base'/);
    assert.match(compSrc, /id:\s*'satellite-underlay'/);
  });

  it('6. binds and refreshes real Earth Engine raster tiles via applyHeatmapTiles with orchard bounds and mapsReady synchronization', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    assert.match(compSrc, /applyHeatmapTiles/);
    assert.match(compSrc, /ee-heatmap-source/);
    assert.match(compSrc, /ee-heatmap-layer/);
    assert.match(compSrc, /bounds:\s*data\.bounds/);
    assert.match(compSrc, /\[layerData,\s*mapsReady,\s*applyHeatmapTiles\]/);
    assert.match(compSrc, /triggerRepaint/);
  });

  it('7. displays honest synchronization status and explicit unavailable/error watermarks instead of false Real GEE Synchronized claim', () => {
    const compSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    assert.match(compSrc, /data-testid="swipe-sync-status"/);
    assert.match(compSrc, /!loading && !error && layerData\?\.status === 'available'/);
    assert.match(compSrc, /!loading && !error && layerData\?\.status === 'unavailable'/);
    assert.match(compSrc, /data-testid="swipe-heatmap-unavailable-pill"/);
  });
});

describe('Integration in Pages & Route Handlers', () => {
  it('1. DomainPage integrates Historical10YearSection and OrchardHeatmapSwipeSection', () => {
    const domainSrc = readSource('pages/agriculture/DomainPage.tsx');
    assert.match(domainSrc, /import Historical10YearSection from/);
    assert.match(domainSrc, /import OrchardHeatmapSwipeSection from/);
    assert.match(domainSrc, /<Historical10YearSection/);
    assert.match(domainSrc, /<OrchardHeatmapSwipeSection/);
  });

  it('2. Agriculture hub integrates Historical10YearSection and OrchardHeatmapSwipeSection', () => {
    const agriSrc = readSource('pages/Agriculture.tsx');
    assert.match(agriSrc, /import Historical10YearSection from/);
    assert.match(agriSrc, /import OrchardHeatmapSwipeSection from/);
    assert.match(agriSrc, /<Historical10YearSection/);
    assert.match(agriSrc, /<OrchardHeatmapSwipeSection/);
  });
});
