/**
 * PDF Export Engine for Agricultural Analysis Report
 *
 * Guarantees:
 * 1. Built from the single shared NormalizedReportModel.
 * 2. 100% Unicode-safe Persian RTL rendering via html2canvas + jsPDF.
 * 3. Preserves insufficient evidence and unavailable soil states honestly.
 * 4. Deterministic filename: agriculture-analysis-1404-03-01-to-1404-06-01.pdf
 * 5. Multi-page layout avoiding content clipping.
 */

import { jsPDF } from 'jspdf';
import html2canvas from 'html2canvas';
import type { NormalizedReportModel } from './reportModel.ts';
import { isoGregorianToJalali, formatJalaliAscii } from '../../utils/date/index.ts';
import { generateOrchardHeatmapSnapshot } from './mapSnapshot.ts';
import { toPersianDigits } from './persianDate.ts';

/**
 * Creates deterministic filename based on Jalali dates.
 * e.g. "agriculture-analysis-1404-03-01-to-1404-06-01.pdf"
 */
export function generatePdfReportFilename(startIso?: string, endIso?: string): string {
  const startJ = isoGregorianToJalali(startIso);
  const endJ = isoGregorianToJalali(endIso);

  const startStr = startJ ? formatJalaliAscii(startJ).replace(/\//g, '-') : 'start';
  const endStr = endJ ? formatJalaliAscii(endJ).replace(/\//g, '-') : 'end';

  return `agriculture-analysis-${startStr}-to-${endStr}.pdf`;
}

/**
 * Renders the full 10-section Persian RTL report into styled HTML.
 */
export function renderReportHtml(model: NormalizedReportModel): string {
  const {
    metadata,
    parcelSpecs,
    overallStatus,
    candidateZones,
    heatmapInfo,
    soilSection,
    yellowingAssessment,
    pestDiseaseSection,
    pistachioSummary,
    actionPlan,
    availableDomainSections,
    unavailableDomainList,
    limitations,
    scientificDisclaimerFa,
  } = model;

  return `
    <div style="
      font-family: 'Vazirmatn', Tahoma, 'Segoe UI', -apple-system, sans-serif;
      direction: rtl;
      text-align: right;
      color: #263238;
      background: #ffffff;
      padding: 30px;
      line-height: 1.6;
      box-sizing: border-box;
      max-width: 900px;
      margin: 0 auto;
    ">
      <!-- 1. Header & Title Block -->
      <div class="pdf-section-block" style="border-bottom: 3px solid #2e7d32; padding-bottom: 14px; margin-bottom: 22px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px;">
          <div>
            <h1 style="margin: 0; font-size: 1.35rem; color: #1b5e20; font-weight: 800;">
              ${metadata.platformNameFa}
            </h1>
            <h2 style="margin: 6px 0 0; font-size: 1.1rem; color: #37474f; font-weight: 700;">
              ${metadata.reportTitleFa}
            </h2>
            <div style="font-size: 0.85rem; color: #2e7d32; font-weight: 700; margin-top: 4px;">
              قطعه / باغ: <strong>${parcelSpecs.locationName}</strong>
            </div>
          </div>
          <div style="text-align: left; font-size: 0.8rem; color: #546e7a;">
            <div>تاریخ صدور: <strong>${metadata.generationDateFa}</strong></div>
            <div>زمینه زراعی: <strong>${metadata.landUseLabelFa}</strong></div>
            <div style="font-family: monospace; font-size: 0.72rem; margin-top: 2px;">
              شناسه تحلیل: ${parcelSpecs.analysisId.slice(0, 16)}...
            </div>
          </div>
        </div>
      </div>

      <!-- 2. Parcel Specifications & Analysis Metadata -->
      <div class="pdf-section-block" style="background: #f1f8e9; border: 1px solid #c5e1a5; border-radius: 8px; padding: 12px 16px; margin-bottom: 22px;">
        <div style="font-weight: 700; color: #2e7d32; margin-bottom: 8px; font-size: 0.95rem;">
          📌 ۱. مشخصات هندسی قطعه و پارامترهای تحلیل (Parcel Specifications):
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.84rem;">
          <div>• بازه زمانی تحلیل (شمسی): <strong>${metadata.timeRangeFa}</strong></div>
          <div>• وضعیت کلی شواهد: <strong>${metadata.overallSufficiencyFa}</strong></div>
          <div>• نوع هندسه: <strong>${parcelSpecs.geometryType}</strong> ${parcelSpecs.vertexCount ? `(${parcelSpecs.vertexCount} نقطه راس)` : ''}</div>
          <div>• مساحت برآوردشده: <strong>${parcelSpecs.areaHectares ? `${parcelSpecs.areaHectares} هکتار` : 'مبتنی بر محدوده'}</strong></div>
          <div>• مختصات مرکز: <span style="font-family: monospace;">${parcelSpecs.centroidCoords ? `Lat: ${parcelSpecs.centroidCoords[1].toFixed(4)}° N, Lon: ${parcelSpecs.centroidCoords[0].toFixed(4)}° E` : '—'}</span></div>
          <div>• حداکثر پوشش ابر مجاز: <strong>${metadata.cloudMaxPercent !== undefined ? `${metadata.cloudMaxPercent}%` : 'استاندارد (۲۰%)'}</strong></div>
        </div>
      </div>

      <!-- 3. Executive Summary (Four Key Status Cards) -->
      <div class="pdf-section-block" style="margin-bottom: 24px;">
        <h3 class="section-heading" style="margin: 0 0 12px; font-size: 1rem; color: #1b5e20; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px;">
          📊 ۲. خلاصه مدیریتی وضعیت زمین در یک نگاه (Executive Summary)
        </h3>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div style="background: #fafafa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px;">
            <div style="font-weight: 700; color: #33691e; font-size: 0.88rem;">🌿 پوشش گیاهی: ${overallStatus.vegetation.titleFa}</div>
            <div style="font-size: 0.8rem; color: #424242; margin-top: 4px;">${overallStatus.vegetation.descriptionFa}</div>
            ${overallStatus.vegetation.metricSummary ? `<div style="font-size: 0.75rem; color: #558b2f; margin-top: 4px; font-family: monospace;">${overallStatus.vegetation.metricSummary}</div>` : ''}
          </div>

          <div style="background: #fafafa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px;">
            <div style="font-weight: 700; color: #1b5e20; font-size: 0.88rem;">🗺️ یکنواختی زمین: ${overallStatus.uniformity.titleFa}</div>
            <div style="font-size: 0.8rem; color: #424242; margin-top: 4px;">${overallStatus.uniformity.descriptionFa}</div>
          </div>

          <div style="background: #fafafa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px;">
            <div style="font-weight: 700; color: #004d40; font-size: 0.88rem;">💧 تنش / خشکی: ${overallStatus.stress.titleFa}</div>
            <div style="font-size: 0.8rem; color: #424242; margin-top: 4px;">${overallStatus.stress.descriptionFa}</div>
          </div>

          <div style="background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px; padding: 10px;">
            <div style="font-weight: 700; color: #bf360c; font-size: 0.88rem;">🌍 وضعیت خاک: ${overallStatus.soil.titleFa}</div>
            <div style="font-size: 0.78rem; color: #5d4037; margin-top: 4px;">${overallStatus.soil.descriptionFa}</div>
            <div style="font-size: 0.75rem; color: #c62828; margin-top: 4px; font-weight: 600;">⚠️ ${overallStatus.soil.requiredActionFa}</div>
          </div>
        </div>
      </div>

      <!-- 4. Candidate Inspection Zones -->
      <div class="pdf-section-block" style="margin-bottom: 24px;">
        <h3 class="section-heading" style="margin: 0 0 10px; font-size: 1rem; color: #1b5e20; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px;">
          🎯 ۳. اولویت‌بندی مکانی و نواحی کاندید پایش حضوری (Candidate Inspection Zones)
        </h3>
        ${
          candidateZones.length > 0
            ? `
          <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem; margin-bottom: 10px;">
            <thead>
              <tr style="background: #e8f5e9; border-bottom: 2px solid #81c784;">
                <th style="padding: 6px 8px; text-align: right;">ناحیه</th>
                <th style="padding: 6px 8px; text-align: right;">وضعیت</th>
                <th style="padding: 6px 8px; text-align: right;">دلیل مشاهده ماهواره‌ای</th>
                <th style="padding: 6px 8px; text-align: center;">اولویت</th>
                <th style="padding: 6px 8px; text-align: center;">مختصات مرکز</th>
              </tr>
            </thead>
            <tbody>
              ${candidateZones
                .map(
                  (z) => `
                <tr style="border-bottom: 1px solid #e0e0e0;">
                  <td style="padding: 6px 8px; font-weight: 600;">${z.zoneNameFa}</td>
                  <td style="padding: 6px 8px; color: ${z.priority === 'high' ? '#c62828' : z.priority === 'medium' ? '#ef6c00' : '#2e7d32'}; font-weight: 600;">${z.statusFa}</td>
                  <td style="padding: 6px 8px;">${z.reasonFa}</td>
                  <td style="padding: 6px 8px; text-align: center; font-weight: 700;">${z.priorityFa}</td>
                  <td style="padding: 6px 8px; text-align: center; font-family: monospace; color: #616161;">
                    ${z.centerCoordinates ? `Lat: ${z.centerCoordinates[1].toFixed(4)}° N, Lon: ${z.centerCoordinates[0].toFixed(4)}° E` : '—'}
                  </td>
                </tr>
              `,
                )
                .join('')}
            </tbody>
          </table>
        `
            : `
          <div style="padding: 10px; background: #fafafa; border: 1px dashed #bdbdbd; border-radius: 6px; font-size: 0.8rem; color: #616161;">
            تحلیل مکانی سلولی چندضلعی برای این گزارش ثبت نشده است (تحلیل نقطه‌ای یا بدون داده شبکه چندضلعی).
          </div>
        `
        }
      </div>

      <!-- 5. Real Spatial Heatmap & Relative Heterogeneity -->
      <div class="pdf-section-block" style="background: #fcfcfc; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px 14px; margin-bottom: 24px;">
        <h3 class="section-heading" style="margin: 0 0 10px; font-size: 1rem; color: #1b5e20; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px;">
          🗺️ ۴. نقشه حرارتی شاخص‌های مکانی و تفکیک درون‌مزرعه‌ای (Spatial Heatmap)
        </h3>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 0.84rem;">
          <div>
            <strong>لایه مبنا:</strong> ${heatmapInfo.titleFa}
          </div>
          <div style="color: #546e7a;">
            منبع: <strong>${heatmapInfo.datasetName}</strong> • وضوح: <strong>${heatmapInfo.resolution}</strong>
          </div>
        </div>

        ${
          heatmapInfo.status === 'producible'
            ? `
          ${
            heatmapInfo.mapImageBase64
              ? `
          <div style="text-align: center; margin-bottom: 12px; background: #ffffff; border: 1px solid #b0bec5; border-radius: 6px; padding: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06);">
            <img src="${heatmapInfo.mapImageBase64}" alt="${heatmapInfo.titleFa}" style="width: 100%; max-width: 720px; height: auto; max-height: 420px; object-fit: contain; border-radius: 4px; display: block; margin: 0 auto;" />
            <div style="font-size: 0.72rem; color: #546e7a; margin-top: 6px; display: flex; justify-content: space-between; align-items: center; padding: 0 4px;">
              <span>🌐 <strong>تصویر ماهواره‌ای رستری GEE</strong> • همپوشانی چندضلعی مرز قطعه باغ (Sentinel-2 MSI)</span>
              <span style="direction: ltr; font-family: monospace;">Resolution: 10m Ground Sampling Distance</span>
            </div>
          </div>
          `
              : ''
          }
          <div style="background: #ffffff; border: 1px solid #cfd8dc; border-radius: 6px; padding: 12px; margin-bottom: 8px;">
            <div style="font-weight: 600; font-size: 0.82rem; color: #37474f; margin-bottom: 6px;">
              راهنمای طیف کیفی رنگ‌ها (Color Palette Legend):
            </div>
            <!-- Visual Gradient Bar -->
            <div style="
              height: 14px;
              border-radius: 4px;
              background: linear-gradient(to left, #d7191c, #fdae61, #ffffbf, #a6d96a, #1a9641);
              margin-bottom: 8px;
              border: 1px solid #b0bec5;
            "></div>
            <div style="display: flex; justify-content: space-between; font-size: 0.74rem; color: #455a64;">
              ${heatmapInfo.legendLabelsFa.map((lbl) => `<span>${lbl}</span>`).join('')}
            </div>
          </div>
          <div style="font-size: 0.78rem; color: #546e7a; line-height: 1.5;">
            📍 <strong>تفسیر اگرو-اکولوژیک:</strong> تفاوت‌های رنگی نشان‌دهنده ناهمگنی نسبی سبزی و تراکم کانوپی درختان است و به منظور شناسایی لکه‌های ضعیف‌تر و هدایت مسیر بازدید زمینی کارشناس استفاده می‌شود.
          </div>
        `
            : `
          <div style="padding: 10px 14px; background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px; font-size: 0.8rem; color: #795548;">
            ⚠️ <strong>وضعیت نقشه حرارتی:</strong> ${heatmapInfo.unavailableReasonFa || 'در این گزارش لایه رستری تولید نشده است.'}
          </div>
        `
        }
      </div>

      <!-- 6. Available Domain Metrics & Telemetry -->
      ${
        availableDomainSections.length > 0
          ? `
        <div style="margin-bottom: 24px;">
          <h3 class="section-heading" style="margin: 0 0 10px; font-size: 1rem; color: #1b5e20; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px;">
            📈 ۵. شواهد عددی و تفسیری حوزه‌های فعال در تحلیل (Domain Telemetry & Synthesis)
          </h3>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            ${availableDomainSections
              .map(
                (sec) => `
              <div class="pdf-section-block" style="background: #ffffff; border: 1px solid #cfd8dc; border-radius: 6px; padding: 10px 14px; page-break-inside: avoid;">
                <div style="font-weight: 700; font-size: 0.86rem; color: #2e7d32; margin-bottom: 4px;">
                  ${sec.titleFa}
                </div>
                ${sec.summaryTextFa ? `<div style="font-size: 0.78rem; color: #455a64; margin-bottom: 6px; line-height: 1.5;">${sec.summaryTextFa}</div>` : ''}
                <div style="display: flex; flex-wrap: wrap; gap: 10px; font-size: 0.78rem;">
                  ${sec.metrics
                    .map(
                      (m) => `
                    <div style="background: #f5f5f5; border: 1px solid #e0e0e0; padding: 6px 10px; border-radius: 4px; min-width: 140px;">
                      <div><strong>${m.name}:</strong> <span style="font-weight: 700; color: #1b5e20;">${m.value !== null ? m.value.toFixed(3) : '—'} ${m.unit}</span></div>
                      ${m.referenceRangeFa ? `<div style="font-size: 0.68rem; color: #555; margin-top: 2px;">🎯 مرجع: ${m.referenceRangeFa}</div>` : ''}
                      ${m.resolution ? `<div style="font-size: 0.66rem; color: #777;">تفکیک مکانی: ${m.resolution}</div>` : ''}
                    </div>
                  `,
                    )
                    .join('')}
                </div>
              </div>
            `,
              )
              .join('')}
          </div>
        </div>
      `
          : ''
      }

      <!-- 7. Soil Intelligence & Laboratory Gate -->
      <div class="pdf-section-block" style="background: #fffde7; border: 1px solid #fff59d; border-radius: 8px; padding: 12px 14px; margin-bottom: 24px;">
        <h3 class="section-heading" style="margin: 0 0 8px; font-size: 0.95rem; color: #e65100; border-bottom: 1px solid #ffe082; padding-bottom: 4px;">
          🧪 ۶. ارزیابی خاک و الزامات نمونه‌برداری آزمایشگاهی (Soil Intelligence & Lab Gate)
        </h3>
        <div style="font-size: 0.82rem; color: #3e2723; margin-bottom: 6px;">
          <strong>وضعیت خط مبنا:</strong> ${soilSection.baselineSummaryFa}
        </div>

        ${
          soilSection.isBaselinePresent && (soilSection.surfaceMoisture || soilSection.rootzoneMoisture || soilSection.textureClassFa)
            ? `
          <!-- Soil Moisture & Texture Overview -->
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px;">
            <div style="background: #ffffff; border: 1px solid #90caf9; border-radius: 6px; padding: 6px 10px;">
              <div style="font-size: 0.72rem; color: #1565c0; font-weight: 600;">رطوبت سطحی (SMAP 0-5cm)</div>
              <div style="font-size: 1.05rem; font-weight: 700; color: #0d47a1; margin: 2px 0;">
                ${soilSection.surfaceMoisture && soilSection.surfaceMoisture.value !== null ? `${toPersianDigits(soilSection.surfaceMoisture.value.toFixed(3))} ${soilSection.surfaceMoisture.unit}` : 'ناموجود'}
              </div>
              <div style="font-size: 0.68rem; color: #607d8b;">تفکیک: ۹ کیلومتر | محصول رادیومتر</div>
            </div>

            <div style="background: #ffffff; border: 1px solid #90caf9; border-radius: 6px; padding: 6px 10px;">
              <div style="font-size: 0.72rem; color: #1565c0; font-weight: 600;">رطوبت ناحیه ریشه (SMAP 0-100cm)</div>
              <div style="font-size: 1.05rem; font-weight: 700; color: #0d47a1; margin: 2px 0;">
                ${soilSection.rootzoneMoisture && soilSection.rootzoneMoisture.value !== null ? `${toPersianDigits(soilSection.rootzoneMoisture.value.toFixed(3))} ${soilSection.rootzoneMoisture.unit}` : 'ناموجود'}
              </div>
              <div style="font-size: 0.68rem; color: #607d8b;">تفکیک: ۹ کیلومتر | مدل بازتحلیل پیوسته</div>
            </div>

            <div style="background: #ffffff; border: 1px solid #a5d6a7; border-radius: 6px; padding: 6px 10px;">
              <div style="font-size: 0.72rem; color: #2e7d32; font-weight: 600;">کلاس بافت خاک (مثلث USDA)</div>
              <div style="font-size: 0.95rem; font-weight: 700; color: #1b5e20; margin: 2px 0;">
                ${soilSection.textureClassFa || 'تعیین نشده'}
              </div>
              <div style="font-size: 0.68rem; color: #607d8b;">
                ${soilSection.sandPercent !== null && soilSection.sandPercent !== undefined ? `ماسه: ${toPersianDigits(soilSection.sandPercent.toFixed(1))}% | رس: ${toPersianDigits((soilSection.clayPercent || 0).toFixed(1))}%` : 'تفکیک: ۲۵۰ متر'}
              </div>
            </div>
          </div>
            `
            : ''
        }

        ${
          soilSection.isBaselinePresent && soilSection.propertiesList && soilSection.propertiesList.length > 0
            ? `
          <!-- SoilGrids Properties Multi-depth Table -->
          <div style="background: #ffffff; border: 1px solid #e0e0e0; border-radius: 6px; padding: 6px 8px; margin-bottom: 10px;">
            <div style="font-size: 0.76rem; font-weight: 700; color: #4e342e; margin-bottom: 4px;">
              مقادیر مدل‌شده خط مبنای پایگاه جهانی ISRIC SoilGrids 2.0 (تفکیک مکانی ۲۵۰ متر):
            </div>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.72rem; text-align: center;">
              <thead>
                <tr style="background: #efebe9; border-bottom: 1px solid #d7ccc8; color: #3e2723;">
                  <th style="padding: 4px; text-align: right;">شاخص / پارامتر</th>
                  <th style="padding: 4px;">ناحیه ریشه (۰-۱۰۰cm)</th>
                  <th style="padding: 4px;">۰ تا ۵ cm</th>
                  <th style="padding: 4px;">۵ تا ۱۵ cm</th>
                  <th style="padding: 4px;">۱۵ تا ۳۰ cm</th>
                  <th style="padding: 4px;">۳۰ تا ۶۰ cm</th>
                  <th style="padding: 4px;">واحد</th>
                </tr>
              </thead>
              <tbody>
                ${soilSection.propertiesList
                  .map((prop) => {
                    const dMap = Object.fromEntries((prop.depths || []).map((d) => [d.depthCode, d.value]));
                    return `
                      <tr style="border-bottom: 1px solid #f5f5f5;">
                        <td style="padding: 3px 4px; text-align: right; font-weight: 600; color: #3e2723;">${prop.nameFa}</td>
                        <td style="padding: 3px 4px; font-weight: 700; color: #1565c0;">${prop.rootZoneValue !== null && prop.rootZoneValue !== undefined ? toPersianDigits(prop.rootZoneValue.toFixed(2)) : '—'}</td>
                        <td style="padding: 3px 4px;">${dMap['0-5cm'] !== undefined && dMap['0-5cm'] !== null ? toPersianDigits(Number(dMap['0-5cm']).toFixed(2)) : '—'}</td>
                        <td style="padding: 3px 4px;">${dMap['5-15cm'] !== undefined && dMap['5-15cm'] !== null ? toPersianDigits(Number(dMap['5-15cm']).toFixed(2)) : '—'}</td>
                        <td style="padding: 3px 4px;">${dMap['15-30cm'] !== undefined && dMap['15-30cm'] !== null ? toPersianDigits(Number(dMap['15-30cm']).toFixed(2)) : '—'}</td>
                        <td style="padding: 3px 4px;">${dMap['30-60cm'] !== undefined && dMap['30-60cm'] !== null ? toPersianDigits(Number(dMap['30-60cm']).toFixed(2)) : '—'}</td>
                        <td style="padding: 3px 4px; color: #78909c; direction: ltr;">${prop.unit}</td>
                      </tr>
                    `;
                  })
                  .join('')}
              </tbody>
            </table>
          </div>
            `
            : ''
        }

        <div style="font-size: 0.78rem; color: #b71c1c; font-weight: 600; margin-bottom: 8px; line-height: 1.5;">
          ⚠️ ${soilSection.laboratoryRequirementFa}
        </div>
        <div style="background: #ffffff; border: 1px solid #ffe082; border-radius: 6px; padding: 8px 10px;">
          <div style="font-size: 0.78rem; font-weight: 700; color: #bf360c; margin-bottom: 4px;">
            پارامترهای غیرقابل‌سنجش از فضا که نیازمند ارسال به آزمایشگاه آب و خاک هستند:
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 6px; font-size: 0.74rem; color: #4e342e;">
            ${soilSection.parametersNeedingLab.map((p) => `<span style="background: #fff8e1; border: 1px solid #ffe082; padding: 2px 6px; border-radius: 3px;">• ${p}</span>`).join('')}
          </div>
        </div>
      </div>

      <!-- 8. Pest & Disease Surveillance -->
      <div class="pdf-section-block" style="background: ${pestDiseaseSection.satelliteRiskLevelFa.includes('بالا') ? '#ffebee' : '#f9fbe7'}; border: 1px solid ${pestDiseaseSection.satelliteRiskLevelFa.includes('بالا') ? '#ef9a9a' : '#dce775'}; border-radius: 8px; padding: 12px 14px; margin-bottom: 24px;">
        <h3 class="section-heading" style="margin: 0 0 8px; font-size: 0.95rem; color: #1b5e20; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px;">
          🔬 ۷. پایش آفت و بیماری و غربالگری ریسک کانوپی (Pest/Disease Surveillance)
        </h3>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 0.84rem;">
          <div>
            سطح هشدار غربالگری ماهواره‌ای: <strong>${pestDiseaseSection.satelliteRiskLevelFa}</strong>
          </div>
          <div style="color: #455a64; font-size: 0.78rem;">
            اعتبارسنجی میدانی: ${pestDiseaseSection.hasFieldValidation ? `✓ ثبت‌شده (${pestDiseaseSection.fieldObservationsCount} مشاهده)` : 'فاقد مشاهده میدانی'}
          </div>
        </div>
        <div style="font-size: 0.8rem; color: #37474f; margin-bottom: 6px; line-height: 1.5;">
          ${pestDiseaseSection.satelliteObservationFa}
        </div>
        <div style="font-size: 0.76rem; color: #c62828; font-weight: 600; line-height: 1.5;">
          ⛔ تذکر قطعی: ${pestDiseaseSection.advisoryFa}
        </div>
      </div>

      <!-- 9. Pistachio Decision Support (Conditional) -->
      ${
        pistachioSummary
          ? `
        <div class="pdf-section-block" style="background: #f1f8e9; border: 1px solid #a5d6a7; border-radius: 8px; padding: 12px 14px; margin-bottom: 24px;">
          <div style="font-weight: 700; color: #1b5e20; font-size: 0.9rem; margin-bottom: 8px;">
            🥜 ۸. تحلیل تخصصی باغ پسته (Pistachio Decision Support):
          </div>
          <div style="font-size: 0.8rem; color: #37474f; line-height: 1.6; margin-bottom: 8px;">
            <div>• ${pistachioSummary.canopyCoverFa}</div>
            <div>• ${pistachioSummary.heterogeneityFa}</div>
            <div>• ${pistachioSummary.stressFa}</div>
            <div>• ${yellowingAssessment.headlineFa}: ${yellowingAssessment.explanationFa}</div>
            <div>• ${pistachioSummary.diebackFa}</div>
          </div>
          <div style="background: #ffffff; border: 1px solid #cfd8dc; border-radius: 6px; padding: 8px 10px; font-size: 0.78rem;">
            <div style="font-weight: 700; color: #c62828;">
              برآورد عملکرد پسته: ${pistachioSummary.yieldStatus.statusLabelFa}
            </div>
            <div style="color: #455a64; margin-top: 2px;">
              دلیل عدم نمایش عدد تناژ: ${pistachioSummary.yieldStatus.reasonFa}
            </div>
          </div>
        </div>
      `
          : ''
      }

      <!-- 10. Farmer Action Plan with Evidence Gate -->
      <div style="margin-bottom: 24px;">
        <h3 class="section-heading" style="margin: 0 0 10px; font-size: 1rem; color: #1b5e20; border-bottom: 1px solid #e0e0e0; padding-bottom: 6px;">
          📋 ۹. برنامه اقدام پیشنهادی کشاورز (Farmer Action Plan)
        </h3>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          ${actionPlan
            .map(
              (item) => `
            <div class="pdf-section-block" style="background: #fafafa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 10px 12px; page-break-inside: avoid;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 0.86rem; color: #1b5e20;">
                  ${item.priorityTitleFa}: ${item.titleFa}
                </span>
                <span style="
                  font-size: 0.72rem;
                  padding: 2px 6px;
                  border-radius: 4px;
                  font-weight: 600;
                  background: ${item.gateStatus === 'passed' ? '#e8f5e9' : item.gateStatus === 'blocked_by_missing_evidence' ? '#ffebee' : '#fff9c4'};
                  color: ${item.gateStatus === 'passed' ? '#2e7d32' : item.gateStatus === 'blocked_by_missing_evidence' ? '#c62828' : '#ef6c00'};
                ">
                  ${item.gateStatus === 'passed' ? `✓ معتبر (${item.evidenceDomain})` : item.gateStatus === 'blocked_by_missing_evidence' ? '⛔ مسدود (خاک)' : `⚠️ نیازمند داده (${item.evidenceDomain})`}
                </span>
              </div>
              <div style="font-size: 0.8rem; color: #37474f;">
                ${item.actionFa}
              </div>
              <div style="font-size: 0.74rem; color: #558b2f; margin-top: 3px;">
                مبنای علمی: ${item.rationaleFa}
              </div>
              <div style="font-size: 0.72rem; color: ${item.gateStatus === 'blocked_by_missing_evidence' ? '#c62828' : '#757575'}; margin-top: 2px;">
                بررسی گیت شواهد: ${item.gateExplanationFa}
              </div>
            </div>
          `,
            )
            .join('')}
        </div>
      </div>

      <!-- 11. Transparent Unavailable Indicators Table -->
      <div class="pdf-section-block" style="background: #fbe9e7; border: 1px solid #ffccbc; border-radius: 8px; padding: 12px 14px; margin-bottom: 24px; page-break-inside: avoid;">
        <h3 class="section-heading" style="margin: 0 0 8px; font-size: 0.95rem; color: #d84315; border-bottom: 1px solid #ffab91; padding-bottom: 4px;">
          🚫 ۱۰. داده‌ها و حوزه‌های فاقد شواهد در این تحلیل (Unavailable Indicators & Remedial Actions)
        </h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 0.78rem; margin-top: 6px;">
          <thead>
            <tr style="background: #ffccbc; border-bottom: 1px solid #d84315;">
              <th style="padding: 5px 8px; text-align: right; width: 28%;">حوزه / شاخص</th>
              <th style="padding: 5px 8px; text-align: right; width: 42%;">علت فنی / علمی نبود داده</th>
              <th style="padding: 5px 8px; text-align: right; width: 30%;">اقدام تکمیلی لازم</th>
            </tr>
          </thead>
          <tbody>
            ${unavailableDomainList
              .map(
                (item) => `
              <tr style="border-bottom: 1px solid #ffe0b2;">
                <td style="padding: 6px 8px; font-weight: 600; color: #4e342e;">${item.domain}</td>
                <td style="padding: 6px 8px; color: #5d4037;">${item.reasonFa}</td>
                <td style="padding: 6px 8px; color: #b71c1c; font-weight: 500;">${item.actionFa}</td>
              </tr>
            `,
              )
              .join('')}
          </tbody>
        </table>
      </div>

      <!-- 12. Technical Limitations, Methodology & Scientific Disclaimer -->
      <div class="pdf-section-block" style="background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px 14px; margin-bottom: 20px; page-break-inside: avoid;">
        <h4 style="margin: 0 0 6px; font-size: 0.88rem; color: #455a64;">
          ⚠️ ۱۱. محدودیت‌های فنی ماهواره‌ای، روش‌شناسی و سلب مسئولیت علمی (Methodology & Disclaimers):
        </h4>
        <div style="font-size: 0.76rem; color: #546e7a; line-height: 1.6; margin-bottom: 8px;">
          داده‌های این گزارش از طریق موتور پردازش ابری Google Earth Engine با استعلام مستقیم از تصاویر Sentinel-2 (تفکیک ۱۰ متر)، Sentinel-1 SAR (تفکیک ۱۰ متر)، MODIS (تفکیک ۱۰۰۰ متر) و ISRIC SoilGrids 2.0 پردازش شده‌اند.
        </div>
        ${
          limitations.length > 0
            ? `
          <ul style="margin: 0 0 8px; padding-right: 18px; font-size: 0.74rem; color: #546e7a; line-height: 1.5;">
            ${limitations.map((lim) => `<li>${lim}</li>`).join('')}
          </ul>
        `
            : ''
        }
        <div style="border-top: 1px solid #cfd8dc; padding-top: 8px; font-size: 0.74rem; color: #78909c; text-align: justify; line-height: 1.5;">
          <strong>سلب مسئولیت قانونی: </strong>${scientificDisclaimerFa}
        </div>
      </div>
    </div>
  `;
}

/**
 * Triggers client-side PDF export using html2canvas + jsPDF.
 * Renders into an off-screen container, calculates block-aware page slices
 * to prevent cards from splitting across page boundaries, and downloads.
 */
export async function exportReportToPdf(model: NormalizedReportModel): Promise<void> {
  // If map image is not yet rendered, fetch real GEE heatmap snapshot as fallback
  if (
    !model.heatmapInfo.mapImageBase64 &&
    model.heatmapInfo.status === 'producible' &&
    model.parcelSpecs.rawGeometry &&
    model.metadata.timeStartIso &&
    model.metadata.timeEndIso
  ) {
    try {
      const snapshot = await generateOrchardHeatmapSnapshot({
        geometry: model.parcelSpecs.rawGeometry,
        startDate: model.metadata.timeStartIso,
        endDate: model.metadata.timeEndIso,
        cloudMaxPercent: model.metadata.cloudMaxPercent ?? 20,
      });
      if (snapshot.success && snapshot.imageBase64) {
        model.heatmapInfo.mapImageBase64 = snapshot.imageBase64;
        if (snapshot.titleFa) model.heatmapInfo.titleFa = snapshot.titleFa;
        if (snapshot.datasetName) model.heatmapInfo.datasetName = snapshot.datasetName;
        if (snapshot.resolution) model.heatmapInfo.resolution = snapshot.resolution;
      }
    } catch (snapshotErr) {
      console.warn('Auto GEE heatmap snapshot fallback failed:', snapshotErr);
    }
  }

  const filename = generatePdfReportFilename(
    model.metadata.timeStartIso,
    model.metadata.timeEndIso,
  );

  const container = document.createElement('div');
  container.style.position = 'fixed';
  container.style.left = '-9999px';
  container.style.top = '0';
  container.style.width = '800px';
  container.style.background = '#ffffff';
  container.style.zIndex = '-999';
  container.innerHTML = renderReportHtml(model);

  document.body.appendChild(container);

  try {
    // Ensure all images are fully loaded and decoded before rendering canvas
    const imgElements = Array.from(container.querySelectorAll('img'));
    if (imgElements.length > 0) {
      await Promise.all(
        imgElements.map(
          (img) =>
            new Promise((resolve) => {
              if (img.complete && img.naturalWidth > 0) {
                resolve(true);
              } else {
                img.onload = () => resolve(true);
                img.onerror = () => resolve(false);
              }
            }),
        ),
      );
    }

    const canvas = await html2canvas(container, {
      scale: 2, // 2x DPI for crisp font rendering
      useCORS: true,
      logging: false,
      backgroundColor: '#ffffff',
    });

    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4',
    });

    const pageWidth = 210; // A4 width mm
    const pageHeight = 297; // A4 height mm
    const margin = 10;
    const contentWidth = pageWidth - margin * 2; // 190 mm
    const contentHeight = pageHeight - margin * 2; // 277 mm

    const containerWidth = container.offsetWidth || 800;
    const totalHeightCss = container.offsetHeight || (canvas.height / 2);
    const pxPerMm = containerWidth / contentWidth;
    const maxPageHeightCss = contentHeight * pxPerMm;
    const scaleFactor = canvas.width / containerWidth;

    const containerRect = container.getBoundingClientRect();
    const blockElements = Array.from(
      container.querySelectorAll('.pdf-section-block'),
    ) as HTMLElement[];

    const blocks = blockElements.map((el) => {
      const rect = el.getBoundingClientRect();
      const prevEl = el.previousElementSibling;
      const hasPrecedingHeading =
        prevEl &&
        (prevEl.tagName === 'H2' ||
          prevEl.tagName === 'H3' ||
          prevEl.tagName === 'H4' ||
          prevEl.classList.contains('section-heading'));
      const headingTop = hasPrecedingHeading
        ? prevEl.getBoundingClientRect().top - containerRect.top
        : null;

      return {
        element: el,
        top: rect.top - containerRect.top,
        bottom: rect.bottom - containerRect.top,
        headingTop,
      };
    });

    // Calculate block-aware page slices
    interface PageSlice {
      startCss: number;
      endCss: number;
    }
    const slices: PageSlice[] = [];
    let currentTop = 0;

    while (currentTop < totalHeightCss) {
      const idealEnd = currentTop + maxPageHeightCss;

      if (idealEnd >= totalHeightCss) {
        slices.push({ startCss: currentTop, endCss: totalHeightCss });
        break;
      }

      // Check if idealEnd cuts through any block
      let bestBreak = idealEnd;
      const intersectingBlock = blocks.find(
        (b) => b.top < idealEnd && b.bottom > idealEnd,
      );

      if (intersectingBlock) {
        let candidateBreak = intersectingBlock.top;
        if (
          intersectingBlock.headingTop !== null &&
          intersectingBlock.headingTop > currentTop + 50
        ) {
          candidateBreak = intersectingBlock.headingTop;
        }

        if (candidateBreak > currentTop + 60) {
          bestBreak = candidateBreak;
        } else {
          bestBreak = idealEnd;
        }
      }

      slices.push({ startCss: currentTop, endCss: bestBreak });
      currentTop = bestBreak;
    }

    // Render each slice onto its own page canvas and add to PDF
    for (let i = 0; i < slices.length; i++) {
      const slice = slices[i];
      const sliceHeightCss = slice.endCss - slice.startCss;
      if (sliceHeightCss <= 0) continue;

      const sourceY = Math.round(slice.startCss * scaleFactor);
      const sourceHeight = Math.min(
        Math.round(sliceHeightCss * scaleFactor),
        canvas.height - sourceY,
      );
      if (sourceHeight <= 0) continue;

      const sliceCanvas = document.createElement('canvas');
      sliceCanvas.width = canvas.width;
      sliceCanvas.height = sourceHeight;
      const ctx = sliceCanvas.getContext('2d');
      if (ctx) {
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, sliceCanvas.width, sliceCanvas.height);
        ctx.drawImage(
          canvas,
          0,
          sourceY,
          canvas.width,
          sourceHeight,
          0,
          0,
          canvas.width,
          sourceHeight,
        );
      }

      const sliceHeightMm = (sliceHeightCss * contentWidth) / containerWidth;

      if (i > 0) {
        pdf.addPage();
      }

      const imgData = sliceCanvas.toDataURL('image/jpeg', 0.95);
      pdf.addImage(imgData, 'JPEG', margin, margin, contentWidth, sliceHeightMm);
    }

    pdf.save(filename);
  } finally {
    document.body.removeChild(container);
  }
}

/**
 * Native Print-to-PDF helper:
 * Opens a clean printable window and triggers native browser print dialog
 * (allowing users to save as vector PDF with 100% native font rendering).
 */
export function openPrintableReport(model: NormalizedReportModel): void {
  const printWindow = window.open('', '_blank', 'width=900,height=800');
  if (!printWindow) return;

  const html = `
    <!DOCTYPE html>
    <html lang="fa" dir="rtl">
    <head>
      <meta charset="utf-8">
      <title>${generatePdfReportFilename(model.metadata.timeStartIso, model.metadata.timeEndIso)}</title>
      <style>
        @page {
          size: A4 portrait;
          margin: 15mm;
        }
        body {
          margin: 0;
          padding: 0;
          background: #ffffff;
        }
        @media print {
          body {
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
        }
      </style>
    </head>
    <body>
      ${renderReportHtml(model)}
      <script>
        window.onload = function() {
          window.print();
        };
      </script>
    </body>
    </html>
  `;

  printWindow.document.write(html);
  printWindow.document.close();
}
