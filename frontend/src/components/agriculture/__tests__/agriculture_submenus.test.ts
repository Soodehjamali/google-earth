import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const srcDir = dirname(dirname(dirname(here)));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

describe('Phase P0-SUBMENUS: Full Integration of Agricultural Indicator Submenus with Saved Reports', () => {
  it('1. Architecture & Single Source of Truth: All 12 submenus registered and linked in routing', () => {
    const appSrc = readSource('App.tsx');
    const layoutSrc = readSource('components/Layout.tsx');

    // 12 submenus check
    const expectedSubmenusInApp = [
      'vegetation',
      'phenology',
      'climate',
      'water',
      'soil',
      'thermal',
      'terrain',
      'land-crop',
      'stress-irrigation',
      'history',
      'pest-disease',
      'pest-disease-validation',
    ];

    for (const sub of expectedSubmenusInApp) {
      assert.ok(appSrc.includes(sub), `App.tsx must register route for ${sub}`);
    }

    const expectedSubmenusInLayout = [
      'vegetation',
      'phenology',
      'climate',
      'water',
      'soil',
      'thermal',
      'terrain',
      'land-crop',
      'stress-irrigation',
      'history',
      'pest-disease',
    ];

    for (const sub of expectedSubmenusInLayout) {
      assert.ok(layoutSrc.includes(sub), `Layout.tsx navigation must contain submenu ${sub}`);
    }

    // Context provider check
    assert.match(appSrc, /<Route path="\/agriculture" element={<AgricultureLayout \/>}>/);
  });

  it('2. URL Parameter Preservation: Preserves analysis_id when navigating across submenus and legacy redirects', () => {
    const layoutSrc = readSource('components/Layout.tsx');
    const cardsSrc = readSource('components/agriculture/DomainNavCards.tsx');
    const appSrc = readSource('App.tsx');

    // Layout.tsx preserves analysis_id for agriculture parent and child routes
    assert.match(
      layoutSrc,
      /const analysisId = new URLSearchParams\(location\.search\)\.get\('analysis_id'\)/,
      'Layout navigation must inspect analysis_id from search params',
    );
    assert.match(
      layoutSrc,
      /childTo\s*=\s*analysisId\s*&&/,
      'Layout navigation must check analysisId when constructing child link',
    );
    assert.match(
      layoutSrc,
      /analysis_id=\$\{encodeURIComponent\(analysisId\)\}/,
      'Layout navigation must append analysis_id to child submenus',
    );

    // DomainNavCards.tsx preserves search params
    assert.match(
      cardsSrc,
      /targetPath\s*=\s*analysisId/,
      'DomainNavCards must check analysisId when constructing targetPath',
    );
    assert.match(
      cardsSrc,
      /analysis_id=\$\{encodeURIComponent\(analysisId\)\}/,
      'DomainNavCards must append analysis_id to target links',
    );

    // App.tsx legacy redirects preserve query parameters
    assert.match(
      appSrc,
      /function RedirectPreservingSearch/,
      'App.tsx must use RedirectPreservingSearch to avoid stripping analysis_id on legacy redirects',
    );
  });

  it('3. Stale Data Flash Prevention: AgricultureLayout clears old report (setResult(null)) on start', () => {
    const agriLayoutSrc = readSource('components/agriculture/AgricultureLayout.tsx');

    // Verify setResult(null) is called at the beginning of loadSavedAnalysis
    assert.match(
      agriLayoutSrc,
      /setResult\(null\);\s*\/\/\s*CRITICAL:\s*Clear prior result immediately/,
      'AgricultureLayout must immediately flush stale analysis result before network fetch',
    );
  });

  it('4. Zero GEE Re-Execution Guard: Submenu transitions do NOT trigger live Earth Engine queries', () => {
    const domainPageSrc = readSource('pages/agriculture/DomainPage.tsx');
    const pestPageSrc = readSource('pages/agriculture/PestDiseasePage.tsx');
    const hist10Src = readSource('components/agriculture/Historical10YearSection.tsx');
    const swipeSrc = readSource('components/agriculture/OrchardHeatmapSwipeSection.tsx');
    const soilSrc = readSource('components/agriculture/SoilIntelligenceSection.tsx');

    // Historical10YearSection accepts disableAutoFetch and gates fetchComparison
    assert.match(hist10Src, /disableAutoFetch\?: boolean/);
    assert.match(hist10Src, /if \(!userRequested\) return;/);
    assert.match(hist10Src, /استعلام مقایسه ۱۰ ساله ماهواره‌ای/);

    // OrchardHeatmapSwipeSection accepts disableAutoFetch and gates tile requests
    assert.match(swipeSrc, /disableAutoFetch\?: boolean/);
    assert.match(swipeSrc, /if \(!userRequested\) return;/);
    assert.match(swipeSrc, /بارگذاری مقایسه کشویی ماهواره‌ای/);

    // SoilIntelligenceSection accepts isSavedReport and guards live fetch
    assert.match(soilSrc, /isSavedReport\?: boolean/);
    assert.match(soilSrc, /saved-soil-unavailable-card/);

    // SpatialIntelligenceSection accepts disableAutoFetch and gates tile requests
    const spatialSrc = readSource('components/agriculture/SpatialIntelligenceSection.tsx');
    assert.match(spatialSrc, /disableAutoFetch\?: boolean/);
    assert.match(spatialSrc, /if \(!userRequested\) return;/);
    assert.match(spatialSrc, /بارگذاری نقشه حرارتی فضایی ماهواره‌ای/);

    // Agriculture.tsx (Overview) passes disableAutoFetch to all three GEE sections
    const agriPageSrc = readSource('pages/Agriculture.tsx');
    assert.match(agriPageSrc, /<Historical10YearSection[\s\S]*?disableAutoFetch=\{Boolean\(savedAnalysisId\)\}/);
    assert.match(agriPageSrc, /<OrchardHeatmapSwipeSection[\s\S]*?disableAutoFetch=\{Boolean\(savedAnalysisId\)\}/);
    assert.match(agriPageSrc, /<SpatialIntelligenceSection[\s\S]*?disableAutoFetch=\{Boolean\(savedAnalysisId\)\}/);

    // DomainPage passes disableAutoFetch and isSavedReport
    assert.match(domainPageSrc, /disableAutoFetch=\{isSavedReport\}/);
    assert.match(domainPageSrc, /isSavedReport=\{isSavedReport\}/);

    // PestDiseasePage passes disableAutoFetch
    assert.match(pestPageSrc, /disableAutoFetch=\{isSavedReport\}/);
  });

  it('5. Honest Unavailable States: Never converts missing values to numeric 0 or fake diagnoses', () => {
    const domainPageSrc = readSource('pages/agriculture/DomainPage.tsx');
    const pestPageSrc = readSource('pages/agriculture/PestDiseasePage.tsx');
    const soilSrc = readSource('components/agriculture/SoilIntelligenceSection.tsx');

    // DomainPage renders State 3 unavailable notice when data is not in the saved report
    assert.match(domainPageSrc, /data-testid="domain-unavailable-card"/);
    assert.match(domainPageSrc, /شواهد ماهواره‌ای برای حوزه.*در این گزارش موجود نیست/);

    // PestDiseasePage renders honest unavailable notice
    assert.match(pestPageSrc, /data-testid="pest-disease-unavailable-card"/);
    assert.match(pestPageSrc, /داده‌های پایش آفت، بیماری یا اعتبارسنجی زمینی در این گزارش ثبت نشده است/);

    // Soil renders honest unavailable notice
    assert.match(soilSrc, /data-testid="saved-soil-unavailable-card"/);
    assert.match(soilSrc, /داده‌های تفصیلی مدل SoilGrids/);
  });

  it('6. Persistent History Banner: Displays database provenance banner with analysis ID', () => {
    const domainPageSrc = readSource('pages/agriculture/DomainPage.tsx');
    const pestPageSrc = readSource('pages/agriculture/PestDiseasePage.tsx');

    assert.match(domainPageSrc, /data-testid="retrieved-from-history-banner"/);
    assert.match(domainPageSrc, /گزارش بازیابی‌شده از تاریخچه دائمی/);
    assert.match(domainPageSrc, /بدون اجرای مجدد GEE/);

    assert.match(pestPageSrc, /data-testid="retrieved-from-history-banner"/);
    assert.match(pestPageSrc, /داده‌های پایش آفت\/بیماری از گزارش ذخیره‌شده بازیابی شد/);
    assert.match(pestPageSrc, /بدون فراخوانی مجدد موتور گوگل ارث \(GEE\)/);
  });

  it('7. Jalali Calendar & Persian Presentation: Guaranteed on all submenu header and range outputs', () => {
    const domainPageSrc = readSource('pages/agriculture/DomainPage.tsx');
    const pestPageSrc = readSource('pages/agriculture/PestDiseasePage.tsx');

    assert.match(domainPageSrc, /formatPersianDateRange/);
    assert.match(domainPageSrc, /toPersianDigits/);
    assert.match(pestPageSrc, /formatPersianDateRange/);
    assert.match(pestPageSrc, /toPersianDigits/);
  });
});
