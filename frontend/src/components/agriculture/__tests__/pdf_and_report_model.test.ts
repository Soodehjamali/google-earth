/**
 * Dedicated Test Suite for PDF Export & Report Model (Phase P-AGRI-DSS-2)
 *
 * Verifies:
 * 1. Normalized Report Model derivation from real analysis response (zero fabrication).
 * 2. Honest preservation of insufficient analysis and unavailable domains (Soil always unavailable).
 * 3. Traceability between UI decision support and PDF report model.
 * 4. Deterministic filename generation matching Jalali dates.
 * 5. Full HTML report structure covering all 10 required sections.
 * 6. Visual Persian RTL and Unicode safety in rendered HTML.
 * 7. Multi-page layout avoiding text clipping (page-break-inside: avoid).
 * 8. UI integration: Download PDF and Print buttons in AgronomicDecisionSupportSection.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildNormalizedReportModel } from '../reportModel.ts';
import { generatePdfReportFilename, renderReportHtml } from '../pdfReport.ts';
import type { AgriculturalAnalysisResponse } from '../../../types/index.ts';

const here = dirname(fileURLToPath(import.meta.url));
const componentsDir = dirname(here);
const srcDir = dirname(dirname(componentsDir));

function readSource(relativePath: string): string {
  return readFileSync(join(srcDir, relativePath), 'utf-8');
}

function createSampleResponse(overrides: Partial<AgriculturalAnalysisResponse> = {}): AgriculturalAnalysisResponse {
  return {
    available_domains: ['vegetation', 'water'],
    unavailable_domains: ['soil', 'thermal'],
    overall_sufficiency: 'sufficient',
    time_start: '2025-06-01',
    time_end: '2025-09-01',
    domain_summaries: {
      vegetation: {
        domain: 'vegetation',
        summary_fa: 'پوشش گیاهی در وضعیت فعال قرار دارد.',
        metrics: {},
      },
    },
    cross_domain_statements: [],
    limitations: ['تفکیک مکانی ۱۰ متر برای سنجنده سنتینل ۲', 'پوشش ابر در بازه زمانی کمتر از ۱۵ درصد بود'],
    metadata: {},
    evidence_bundles: {
      vegetation: {
        name: 'vegetation',
        items: [
          {
            metric_key: 'ndvi',
            value: 0.48,
            unit: 'index',
            status: 'available',
            quality: 'nominal',
            display_name: 'NDVI',
            is_usable: true,
            is_proxy: false,
          },
        ],
        available: ['ndvi'],
        unavailable: [],
        source_datasets: ['COPERNICUS/S2_SR_HARMONIZED'],
        conflicts: [],
        limitations: [],
      },
      water: {
        name: 'water',
        items: [
          {
            metric_key: 'ndmi',
            value: 0.15,
            unit: 'index',
            status: 'available',
            quality: 'nominal',
            display_name: 'NDMI',
            is_usable: true,
            is_proxy: false,
          },
        ],
        available: ['ndmi'],
        unavailable: [],
        source_datasets: ['COPERNICUS/S2_SR_HARMONIZED'],
        conflicts: [],
        limitations: [],
      },
    },
    ...overrides,
  };
}

describe('P-AGRI-DSS-2: PDF Export & Report Model Architecture', () => {
  it('1. buildNormalizedReportModel creates a clean normalized model without data fabrication', () => {
    const resp = createSampleResponse();
    const model = buildNormalizedReportModel(resp, { landUseType: 'pistachio', cloudMaxPercent: 15 });

    assert.equal(model.metadata.landUseType, 'pistachio');
    assert.match(model.metadata.landUseLabelFa, /باغ پسته/);
    assert.equal(model.metadata.timeRangeFa, '۱۴۰۴/۰۳/۱۱ تا ۱۴۰۴/۰۶/۱۰');
    assert.equal(model.metadata.overallSufficiency, 'sufficient');
    assert.equal(model.metadata.cloudMaxPercent, 15);

    // Active domain sections
    assert.equal(model.availableDomainSections.length, 2);
    assert.ok(model.availableDomainSections.some((s) => s.domainKey === 'vegetation'));
    assert.ok(model.availableDomainSections.some((s) => s.domainKey === 'water'));

    // Soil is strictly unavailable
    assert.ok(model.unavailableDomainList.some((d) => d.domain.includes('خاک') && d.reasonFa.includes('داده معتبر خاک')));
  });

  it('2. preserves insufficient state honestly when overall_sufficiency is insufficient', () => {
    const insufficientResp = createSampleResponse({
      overall_sufficiency: 'insufficient',
      available_domains: [],
      unavailable_domains: ['vegetation', 'water', 'soil'],
      evidence_bundles: {},
    });

    const model = buildNormalizedReportModel(insufficientResp);
    assert.equal(model.metadata.overallSufficiency, 'insufficient');
    assert.match(model.metadata.overallSufficiencyFa, /ناکافی/);
    assert.equal(model.overallStatus.vegetation.state, 'insufficient');

    const html = renderReportHtml(model);
    assert.match(html, /ناکافی/);
    assert.match(html, /داده معتبر خاک در این تحلیل موجود نیست/);
  });

  it('3. generates deterministic filename from Jalali dates', () => {
    const filename = generatePdfReportFilename('2025-06-01', '2025-09-01');
    assert.equal(filename, 'agriculture-analysis-1404-03-11-to-1404-06-10.pdf');
  });

  it('4. renderReportHtml generates complete 10-section Persian RTL report', () => {
    const resp = createSampleResponse();
    const model = buildNormalizedReportModel(resp, { landUseType: 'pistachio' });
    const html = renderReportHtml(model);

    // RTL & Font
    assert.match(html, /direction:\s*rtl/);
    assert.match(html, /Vazirmatn/);

    // 1. Header
    assert.match(html, /سامانه پایش هوشمند کشاورزی/);
    assert.match(html, /گزارش جامع پایش اگرو-اکولوژیک/);

    // 2. Parameters
    assert.match(html, /۱۴۰۴\/۰۳\/۱۱ تا ۱۴۰۴\/۰۶\/۱۰/);

    // 3. Status cards
    assert.match(html, /پوشش گیاهی/);
    assert.match(html, /یکنواختی زمین/);
    assert.match(html, /تنش \/ خشکی/);
    assert.match(html, /وضعیت خاک.*داده معتبر خاک در این تحلیل موجود نیست/);

    // 4. Pistachio section
    assert.match(html, /تحلیل تخصصی باغ پسته/);
    assert.match(html, /برآورد عملکرد پسته.*در حال حاضر فعال نیست/);

    // 5. Action Plan with Evidence Gate
    assert.match(html, /برنامه اقدام پیشنهادی کشاورز/);
    assert.match(html, /گیت شواهد/);
    assert.match(html, /مسدود \(خاک\)/);

    // 6. Unavailable domains
    assert.match(html, /داده‌ها و حوزه‌های فاقد شواهد در این تحلیل/);

    // 7. Limitations & Disclaimer
    assert.match(html, /محدودیت‌های فنی ماهواره‌ای/);
    assert.match(html, /سلب مسئولیت علمی/);
    assert.match(html, /page-break-inside:\s*avoid/);
  });

  it('5. UI integration: AgronomicDecisionSupportSection renders PDF download and print buttons', () => {
    const code = readSource('components/agriculture/AgronomicDecisionSupportSection.tsx');
    assert.match(code, /data-testid="download-pdf-button"/);
    assert.match(code, /data-testid="print-report-button"/);
    assert.match(code, /handleDownloadPdf/);
    assert.match(code, /handlePrintReport/);
    assert.match(code, /exportReportToPdf/);
    assert.match(code, /buildNormalizedReportModel/);
    assert.match(code, /generateOrchardHeatmapSnapshot/);
  });

  it('6. P-AGRI-PDF-HEATMAP: integrates real GEE raster map image into NormalizedReportModel and rendered HTML', () => {
    const resp = createSampleResponse();
    const fakeBase64 = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    const model = buildNormalizedReportModel(resp, {
      landUseType: 'pistachio',
      heatmapSnapshot: {
        imageBase64: fakeBase64,
        datasetName: 'COPERNICUS/S2_SR_HARMONIZED (Sentinel-2 MSI)',
        resolution: '۱۰ متر (10 m)',
        titleFa: 'نقشه حرارتی تراکم و شادابی کانوپی (Sentinel-2 NDVI)',
      },
    });

    assert.equal(model.heatmapInfo.mapImageBase64, fakeBase64);
    assert.equal(model.heatmapInfo.status, 'producible');
    assert.equal(model.heatmapInfo.resolution, '۱۰ متر (10 m)');

    const html = renderReportHtml(model);
    assert.match(html, /<img\s+src="data:image\/png;base64/);
    assert.match(html, /تصویر ماهواره‌ای رستری GEE/);
    assert.match(html, /همپوشانی چندضلعی مرز قطعه باغ/);

    const pdfCode = readSource('components/agriculture/pdfReport.ts');
    assert.match(pdfCode, /generateOrchardHeatmapSnapshot/);
  });
});
