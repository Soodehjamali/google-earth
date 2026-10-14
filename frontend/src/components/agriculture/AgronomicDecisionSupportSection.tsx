import { useMemo, useState } from 'react';
import type { AgriculturalAnalysisResponse, LandUseType } from '../../types/index.ts';
import {
  deriveFarmerActionPlan,
  derivePistachioSpecificSummary,
  evaluateCanopyYellowing,
  evaluatePestAndDiseaseSurveillance,
  evaluateSoilAndNutritionPriority,
  extractCandidateInspectionZones,
  extractOverallFieldStatus,
} from './decisionSupport.ts';
import { buildNormalizedReportModel } from './reportModel.ts';
import { exportReportToPdf, openPrintableReport } from './pdfReport.ts';
import { generateOrchardHeatmapSnapshot } from './mapSnapshot.ts';
import { agricultureApi } from '../../api/agriculture.ts';

interface AgronomicDecisionSupportSectionProps {
  result: AgriculturalAnalysisResponse;
  landUseType?: LandUseType;
  onLandUseChange?: (type: LandUseType) => void;
}

export default function AgronomicDecisionSupportSection({
  result,
  landUseType = 'field_crop',
  onLandUseChange,
}: AgronomicDecisionSupportSectionProps) {
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);

  // Derive pure DSS structures strictly from real response evidence
  const overallStatus = useMemo(() => extractOverallFieldStatus(result), [result]);
  const candidateZones = useMemo(() => extractCandidateInspectionZones(result), [result]);
  const soilAssessment = useMemo(
    () => evaluateSoilAndNutritionPriority(result, candidateZones),
    [result, candidateZones],
  );
  const yellowingAssessment = useMemo(
    () => evaluateCanopyYellowing(result, candidateZones),
    [result, candidateZones],
  );
  const pestAssessment = useMemo(
    () => evaluatePestAndDiseaseSurveillance(result, candidateZones),
    [result, candidateZones],
  );
  const pistachioSummary = useMemo(
    () => derivePistachioSpecificSummary(result, candidateZones),
    [result, candidateZones],
  );
  const actionPlan = useMemo(
    () => deriveFarmerActionPlan(result, candidateZones, landUseType),
    [result, candidateZones, landUseType],
  );

  const [pdfStatus, setPdfStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [pdfError, setPdfError] = useState<string | null>(null);

  const reportModel = useMemo(
    () => buildNormalizedReportModel(result, { landUseType }),
    [result, landUseType],
  );

  const handleDownloadPdf = async () => {
    try {
      setPdfStatus('loading');
      setPdfError(null);
      let activeModel = reportModel;
      if (!result.soil_intelligence && result.geometry && result.time_start && result.time_end) {
        try {
          const soilData = await agricultureApi.getSoilIntelligence({
            geometry: result.geometry,
            start_date: result.time_start,
            end_date: result.time_end,
          });
          if (soilData) {
            result.soil_intelligence = soilData;
            activeModel = buildNormalizedReportModel(result, {
              landUseType,
              heatmapSnapshot: activeModel.heatmapInfo.mapImageBase64
                ? {
                    imageBase64: activeModel.heatmapInfo.mapImageBase64,
                    datasetName: activeModel.heatmapInfo.datasetName,
                    resolution: activeModel.heatmapInfo.resolution,
                    titleFa: activeModel.heatmapInfo.titleFa,
                  }
                : undefined,
            });
          }
        } catch (soilErr) {
          console.warn('Soil intelligence fetch error before export:', soilErr);
        }
      }

      if (
        !activeModel.heatmapInfo.mapImageBase64 &&
        result.geometry &&
        result.time_start &&
        result.time_end
      ) {
        try {
          const snapshot = await generateOrchardHeatmapSnapshot({
            geometry: result.geometry,
            startDate: result.time_start,
            endDate: result.time_end,
            metric: 'ndvi',
            cloudMaxPercent: 20,
          });
          if (snapshot.success && snapshot.imageBase64) {
            activeModel = buildNormalizedReportModel(result, {
              landUseType,
              heatmapSnapshot: snapshot,
            });
          }
        } catch (snapErr) {
          console.warn('Map snapshot generation error before export:', snapErr);
        }
      }
      await exportReportToPdf(activeModel);
      setPdfStatus('idle');
    } catch (err) {
      setPdfStatus('error');
      setPdfError(err instanceof Error ? err.message : 'خطا در تولید فایل PDF');
    }
  };

  const handlePrintReport = async () => {
    let activeModel = reportModel;
    if (!result.soil_intelligence && result.geometry && result.time_start && result.time_end) {
      try {
        const soilData = await agricultureApi.getSoilIntelligence({
          geometry: result.geometry,
          start_date: result.time_start,
          end_date: result.time_end,
        });
        if (soilData) {
          result.soil_intelligence = soilData;
          activeModel = buildNormalizedReportModel(result, {
            landUseType,
            heatmapSnapshot: activeModel.heatmapInfo.mapImageBase64
              ? {
                  imageBase64: activeModel.heatmapInfo.mapImageBase64,
                  datasetName: activeModel.heatmapInfo.datasetName,
                  resolution: activeModel.heatmapInfo.resolution,
                  titleFa: activeModel.heatmapInfo.titleFa,
                }
              : undefined,
          });
        }
      } catch (soilErr) {
        console.warn('Soil intelligence fetch error before print:', soilErr);
      }
    }

    if (
      !activeModel.heatmapInfo.mapImageBase64 &&
      result.geometry &&
      result.time_start &&
      result.time_end
    ) {
      try {
        const snapshot = await generateOrchardHeatmapSnapshot({
          geometry: result.geometry,
          startDate: result.time_start,
          endDate: result.time_end,
          metric: 'ndvi',
          cloudMaxPercent: 20,
        });
        if (snapshot.success && snapshot.imageBase64) {
          activeModel = buildNormalizedReportModel(result, {
            landUseType,
            heatmapSnapshot: snapshot,
          });
        }
      } catch (snapErr) {
        console.warn('Map snapshot generation error before print:', snapErr);
      }
    }
    openPrintableReport(activeModel);
  };

  const selectedZone = candidateZones.find((z) => z.cellId === selectedZoneId) ?? null;

  return (
    <section
      aria-label="Agronomic Decision Support Layer"
      data-testid="agronomic-decision-support-section"
      className="card mb-4"
      style={{
        border: '2px solid #2e7d32',
        borderRadius: 12,
        boxShadow: '0 4px 14px rgba(46, 125, 50, 0.08)',
        background: '#ffffff',
      }}
    >
      {/* 1. Header Banner */}
      <div
        className="card-header"
        style={{
          background: 'linear-gradient(135deg, #1b5e20 0%, #2e7d32 100%)',
          color: '#ffffff',
          borderRadius: '10px 10px 0 0',
          padding: '16px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '1.5rem' }}>🌱</span>
            <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#ffffff' }}>
              سامانه پشتیبانی تصمیم کشاورزی — Farmer Decision Support Layer
            </h3>
          </div>
          <p
            style={{
              margin: '6px 0 0',
              fontSize: '0.85rem',
              color: '#e8f5e9',
              lineHeight: 1.5,
            }}
          >
            پاسخ‌های تصمیم‌محور و ملموس زراعی بر پایه شواهد واقعی ماهواره‌ای، بدون عددسازی و با حفظ شفافیت علمی
          </p>
        </div>

        {/* Land Use Context Pill */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: '0.8rem', color: '#c8e6c9' }}>زمینه کاربری:</span>
          {onLandUseChange ? (
            <select
              aria-label="انتخاب زمینه کاربری زمین"
              value={landUseType}
              onChange={(e) => onLandUseChange(e.target.value as LandUseType)}
              className="form-select"
              style={{
                fontSize: '0.85rem',
                fontWeight: 600,
                padding: '4px 10px',
                background: '#ffffff',
                color: '#1b5e20',
                border: 'none',
                borderRadius: 6,
              }}
            >
              <option value="field_crop">🌾 زمین زراعی (Field Crop)</option>
              <option value="orchard">🌳 باغ عمومی (General Orchard)</option>
              <option value="pistachio">🥜 باغ پسته (Pistachio Orchard)</option>
              <option value="other">🗺️ سایر / نامشخص (Other)</option>
            </select>
          ) : (
            <span
              className="badge"
              style={{
                background: '#ffffff',
                color: '#1b5e20',
                fontWeight: 700,
                fontSize: '0.85rem',
                padding: '4px 10px',
              }}
            >
              {landUseType === 'pistachio'
                ? '🥜 باغ پسته'
                : landUseType === 'orchard'
                  ? '🌳 باغ'
                  : landUseType === 'field_crop'
                    ? '🌾 زمین زراعی'
                    : '🗺️ نامشخص'}
            </span>
          )}
        </div>

        {/* PDF Export & Print Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-sm"
            data-testid="download-pdf-button"
            onClick={handleDownloadPdf}
            disabled={!result || pdfStatus === 'loading'}
            style={{
              background: pdfStatus === 'error' ? '#d32f2f' : '#ffffff',
              color: pdfStatus === 'error' ? '#ffffff' : '#1b5e20',
              fontWeight: 700,
              fontSize: '0.85rem',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              border: 'none',
              padding: '6px 14px',
              borderRadius: 6,
              cursor: pdfStatus === 'loading' ? 'wait' : 'pointer',
              boxShadow: '0 2px 6px rgba(0,0,0,0.1)',
            }}
          >
            <span>{pdfStatus === 'loading' ? '⏳' : pdfStatus === 'error' ? '⚠️' : '📄'}</span>
            <span>
              {pdfStatus === 'loading'
                ? 'در حال آماده‌سازی گزارش...'
                : pdfStatus === 'error'
                  ? 'خطا در تولید PDF — تلاش مجدد'
                  : 'دانلود گزارش PDF'}
            </span>
          </button>

          <button
            type="button"
            className="btn btn-sm"
            data-testid="print-report-button"
            onClick={handlePrintReport}
            title="مشاهده نمای چاپ و ذخیره با پرینتر مرورگر"
            style={{
              background: 'rgba(255, 255, 255, 0.2)',
              color: '#ffffff',
              border: '1px solid rgba(255, 255, 255, 0.4)',
              fontWeight: 600,
              fontSize: '0.82rem',
              padding: '5px 10px',
              borderRadius: 6,
              cursor: 'pointer',
            }}
          >
            🖨️ چاپ مستقیم / مرورگر
          </button>
        </div>

        {pdfError && (
          <div
            data-testid="pdf-error-notice"
            style={{
              background: '#ffebee',
              color: '#c62828',
              padding: '6px 12px',
              borderRadius: 6,
              fontSize: '0.78rem',
              width: '100%',
              marginTop: 6,
            }}
          >
            ⚠️ {pdfError} (امکان استفاده از دکمه «چاپ مستقیم / مرورگر» نیز فراهم است)
          </div>
        )}
      </div>

      <div className="card-body" style={{ padding: '20px' }}>
        {/* 2. Overall Field Status (Four Cards) */}
        <div style={{ marginBottom: 28 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 12,
            }}
          >
            <h4
              style={{
                margin: 0,
                fontSize: '1.05rem',
                fontWeight: 700,
                color: '#1b5e20',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <span>📊</span>
              <span>وضعیت کلی زمین در یک نگاه</span>
            </h4>
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>
              استخراج‌شده از داده‌های واقعی باند نوری، حرارتی و راداری
            </span>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))',
              gap: 14,
            }}
          >
            {/* Card 1: Vegetation */}
            <div
              data-testid="dss-card-vegetation"
              style={{
                background: '#f1f8e9',
                border: '1px solid #c5e1a5',
                borderRadius: 10,
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.88rem', color: '#33691e' }}>
                    🌿 پوشش گیاهی
                  </span>
                  <span
                    className={`badge ${
                      overallStatus.vegetation.state === 'suitable'
                        ? 'badge-good'
                        : overallStatus.vegetation.state === 'attention'
                          ? 'badge-warning'
                          : overallStatus.vegetation.state === 'weak'
                            ? 'badge-danger'
                            : 'badge-secondary'
                    }`}
                    style={{ fontSize: '0.78rem' }}
                  >
                    {overallStatus.vegetation.titleFa}
                  </span>
                </div>
                <p style={{ margin: '10px 0 0', fontSize: '0.82rem', lineHeight: 1.55, color: '#37474f' }}>
                  {overallStatus.vegetation.descriptionFa}
                </p>
              </div>
              {overallStatus.vegetation.metricSummary && (
                <div
                  style={{
                    marginTop: 10,
                    fontSize: '0.75rem',
                    color: '#558b2f',
                    fontFamily: 'monospace',
                    fontWeight: 600,
                  }}
                >
                  {overallStatus.vegetation.metricSummary}
                </div>
              )}
            </div>

            {/* Card 2: Uniformity */}
            <div
              data-testid="dss-card-uniformity"
              style={{
                background: '#e8f5e9',
                border: '1px solid #a5d6a7',
                borderRadius: 10,
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.88rem', color: '#1b5e20' }}>
                    🗺️ یکنواختی زمین
                  </span>
                  <span
                    className={`badge ${
                      overallStatus.uniformity.state === 'uniform'
                        ? 'badge-good'
                        : overallStatus.uniformity.state === 'heterogeneous'
                          ? 'badge-warning'
                          : overallStatus.uniformity.state === 'strongly_heterogeneous'
                            ? 'badge-danger'
                            : 'badge-secondary'
                    }`}
                    style={{ fontSize: '0.78rem' }}
                  >
                    {overallStatus.uniformity.titleFa}
                  </span>
                </div>
                <p style={{ margin: '10px 0 0', fontSize: '0.82rem', lineHeight: 1.55, color: '#37474f' }}>
                  {overallStatus.uniformity.descriptionFa}
                </p>
              </div>
              {overallStatus.uniformity.metricSummary && (
                <div
                  style={{
                    marginTop: 10,
                    fontSize: '0.75rem',
                    color: '#2e7d32',
                    fontWeight: 600,
                  }}
                >
                  {overallStatus.uniformity.metricSummary}
                </div>
              )}
            </div>

            {/* Card 3: Stress / Dryness */}
            <div
              data-testid="dss-card-stress"
              style={{
                background: '#e0f2f1',
                border: '1px solid #80cbc4',
                borderRadius: 10,
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.88rem', color: '#004d40' }}>
                    💧 تنش / خشکی
                  </span>
                  <span
                    className={`badge ${
                      overallStatus.stress.state === 'no_stress'
                        ? 'badge-good'
                        : overallStatus.stress.state === 'candidate_zones_present'
                          ? 'badge-warning'
                          : overallStatus.stress.state === 'stress_indicated'
                            ? 'badge-warning'
                            : 'badge-secondary'
                    }`}
                    style={{ fontSize: '0.78rem' }}
                  >
                    {overallStatus.stress.titleFa}
                  </span>
                </div>
                <p style={{ margin: '10px 0 0', fontSize: '0.82rem', lineHeight: 1.55, color: '#37474f' }}>
                  {overallStatus.stress.descriptionFa}
                </p>
              </div>
              {overallStatus.stress.metricSummary && (
                <div
                  style={{
                    marginTop: 10,
                    fontSize: '0.75rem',
                    color: '#00695c',
                    fontFamily: 'monospace',
                    fontWeight: 600,
                  }}
                >
                  {overallStatus.stress.metricSummary}
                </div>
              )}
            </div>

            {/* Card 4: Soil Fertility (Strictly Non-Claim) */}
            <div
              data-testid="dss-card-soil"
              style={{
                background: '#fff8e1',
                border: '1px solid #ffe082',
                borderRadius: 10,
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.88rem', color: '#f57f17' }}>
                    🌍 وضعیت شیمیایی خاک
                  </span>
                  <span className="badge badge-warning" style={{ fontSize: '0.72rem' }}>
                    نیازمند آزمون خاک
                  </span>
                </div>
                <div
                  style={{
                    margin: '8px 0 4px',
                    fontWeight: 700,
                    fontSize: '0.82rem',
                    color: '#e65100',
                  }}
                >
                  {overallStatus.soil.titleFa}
                </div>
                <p style={{ margin: '4px 0 0', fontSize: '0.78rem', lineHeight: 1.5, color: '#5d4037' }}>
                  {overallStatus.soil.descriptionFa}
                </p>
              </div>
              <div
                style={{
                  marginTop: 10,
                  padding: '6px 8px',
                  background: '#ffffff',
                  borderRadius: 6,
                  border: '1px solid #ffd54f',
                  fontSize: '0.75rem',
                  color: '#bf360c',
                  lineHeight: 1.4,
                }}
              >
                🔬 {overallStatus.soil.requiredActionFa}
                {overallStatus.soil.moistureNoteFa && (
                  <div style={{ marginTop: 4, color: '#6d4c41', fontSize: '0.72rem' }}>
                    {overallStatus.soil.moistureNoteFa}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* 3. Candidate Inspection Zones (Table) */}
        <div style={{ marginBottom: 28 }} data-testid="dss-candidate-zones-section">
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 10,
              flexWrap: 'wrap',
              gap: 8,
            }}
          >
            <div>
              <h4
                style={{
                  margin: 0,
                  fontSize: '1.05rem',
                  fontWeight: 700,
                  color: '#1b5e20',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <span>🎯</span>
                <span>نواحی کاندید پایش و بازدید میدانی — Candidate Inspection Zones</span>
              </h4>
              <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 3 }}>
                اولویت‌بندی نقاط زمین بر اساس تحلیل مکانی چندشاخصه جهت بازدید حضوری و نمونه‌برداری
              </div>
            </div>

            {candidateZones.length > 0 && (
              <span className="badge badge-info" style={{ fontSize: '0.8rem' }}>
                {candidateZones.length} سلول مکانی تفکیک‌شده
              </span>
            )}
          </div>

          {candidateZones.length > 0 ? (
            <div className="table-container" style={{ borderRadius: 8, border: '1px solid #e0e0e0' }}>
              <table aria-label="Candidate Inspection Zones" style={{ width: '100%', margin: 0 }}>
                <thead>
                  <tr style={{ background: '#f5f5f5', textAlign: 'right' }}>
                    <th style={{ padding: '10px 12px', fontSize: '0.85rem' }}>ناحیه زمین</th>
                    <th style={{ padding: '10px 12px', fontSize: '0.85rem' }}>وضعیت نسبت به میانگین</th>
                    <th style={{ padding: '10px 12px', fontSize: '0.85rem' }}>دلیل و شواهد ماهواره‌ای</th>
                    <th style={{ padding: '10px 12px', fontSize: '0.85rem', textAlign: 'center' }}>
                      اولویت بازدید
                    </th>
                    <th style={{ padding: '10px 12px', fontSize: '0.85rem', textAlign: 'center' }}>
                      مختصات مرکز
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {candidateZones.map((zone) => {
                    const isSelected = selectedZoneId === zone.cellId;
                    return (
                      <tr
                        key={zone.cellId}
                        data-testid={`candidate-zone-row-${zone.cellId}`}
                        style={{
                          background: isSelected
                            ? '#e8f5e9'
                            : zone.priority === 'high'
                              ? '#fffde7'
                              : zone.priority === 'medium'
                                ? '#fafafa'
                                : '#ffffff',
                          cursor: 'pointer',
                          borderBottom: '1px solid #eeeeee',
                        }}
                        onClick={() => setSelectedZoneId(isSelected ? null : zone.cellId)}
                      >
                        <td style={{ padding: '10px 12px', fontWeight: 600, fontSize: '0.85rem' }}>
                          <span style={{ marginLeft: 6 }}>
                            {zone.priority === 'high' ? '🔴' : zone.priority === 'medium' ? '🟡' : '🟢'}
                          </span>
                          {zone.zoneNameFa}
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: '0.83rem' }}>
                          <span
                            style={{
                              color:
                                zone.priority === 'high'
                                  ? '#c62828'
                                  : zone.priority === 'medium'
                                    ? '#ef6c00'
                                    : '#2e7d32',
                              fontWeight: 600,
                            }}
                          >
                            {zone.statusFa}
                          </span>
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: '0.82rem', color: '#424242' }}>
                          {zone.reasonFa}
                        </td>
                        <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                          <span
                            className={`badge ${
                              zone.priority === 'high'
                                ? 'badge-danger'
                                : zone.priority === 'medium'
                                  ? 'badge-warning'
                                  : 'badge-good'
                            }`}
                            style={{ fontSize: '0.78rem', padding: '3px 8px' }}
                          >
                            {zone.priorityFa}
                          </span>
                        </td>
                        <td
                          style={{
                            padding: '10px 12px',
                            textAlign: 'center',
                            fontSize: '0.78rem',
                            fontFamily: 'monospace',
                            color: '#616161',
                          }}
                        >
                          {zone.centerCoordinates
                            ? `Lat: ${zone.centerCoordinates[1].toFixed(4)}° N, Lon: ${zone.centerCoordinates[0].toFixed(4)}° E`
                            : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div
              data-testid="no-spatial-candidate-zones"
              style={{
                padding: '14px 18px',
                borderRadius: 8,
                background: '#f9f9f9',
                border: '1px dashed #bdbdbd',
                color: '#616161',
                fontSize: '0.85rem',
                lineHeight: 1.6,
              }}
            >
              ℹ️ <strong>شبکه سلولی مکانی برای این تحلیل محاسبه نشده است:</strong>
              <div>
                تحلیل بر روی مختصات نقطه‌ای یا بدون داده سلولی انجام شده است. برای مشاهده جدول اولویت‌بندی بخش‌های مختلف زمین، رسم محدوده چندضلعی (Polygon) در فرم بالا توصیه می‌شود.
              </div>
            </div>
          )}

          {selectedZone && (
            <div
              data-testid="selected-zone-detail"
              style={{
                marginTop: 12,
                padding: '14px 16px',
                background: '#f9fbe7',
                borderRadius: 8,
                border: '1px solid #c0ca33',
                fontSize: '0.82rem',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  borderBottom: '1px solid #dce775',
                  paddingBottom: 8,
                  marginBottom: 12,
                }}
              >
                <div>
                  <strong style={{ fontSize: '0.9rem', color: '#1b5e20' }}>
                    🔍 بررسی تفصیلی ناحیه: {selectedZone.zoneNameFa}
                  </strong>
                  <span
                    className={`badge ${
                      selectedZone.priority === 'high'
                        ? 'badge-danger'
                        : selectedZone.priority === 'medium'
                          ? 'badge-warning'
                          : 'badge-good'
                    }`}
                    style={{ marginRight: 8, fontSize: '0.78rem' }}
                  >
                    اولویت: {selectedZone.priorityFa} ({selectedZone.statusFa})
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  style={{ fontSize: '0.75rem', padding: '2px 8px' }}
                  onClick={() => setSelectedZoneId(null)}
                >
                  بستن انتخاب ✕
                </button>
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: 10,
                }}
              >
                <div
                  style={{
                    background: '#ffffff',
                    padding: '10px 12px',
                    borderRadius: 6,
                    border: '1px solid #e0e0e0',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#2e7d32', marginBottom: 4 }}>
                    👁️ ۱. چه دیدیم؟ (مشاهده ماهواره‌ای):
                  </div>
                  <div style={{ color: '#424242', lineHeight: 1.5 }}>
                    {selectedZone.observationFa}
                  </div>
                </div>

                <div
                  style={{
                    background: '#ffffff',
                    padding: '10px 12px',
                    borderRadius: 6,
                    border: '1px solid #e0e0e0',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#f57f17', marginBottom: 4 }}>
                    💡 ۲. معنی احتمالی چیست؟ (تفسیر اگرونومیک):
                  </div>
                  <div style={{ color: '#424242', lineHeight: 1.5 }}>
                    {selectedZone.interpretationFa}
                  </div>
                </div>

                <div
                  style={{
                    background: '#ffffff',
                    padding: '10px 12px',
                    borderRadius: 6,
                    border: '1px solid #e0e0e0',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#c62828', marginBottom: 4 }}>
                    ⚠️ ۳. چه چیزی نمی‌دانیم؟ (محدودیت شواهد):
                  </div>
                  <div style={{ color: '#424242', lineHeight: 1.5 }}>
                    {selectedZone.limitationFa}
                  </div>
                </div>

                <div
                  style={{
                    background: '#ffffff',
                    padding: '10px 12px',
                    borderRadius: 6,
                    border: '1px solid #e0e0e0',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#1565c0', marginBottom: 4 }}>
                    🚶‍♂️ ۴. اقدام پیشنهادی چیست؟ (گام میدانی):
                  </div>
                  <div style={{ color: '#424242', lineHeight: 1.5 }}>
                    {selectedZone.actionFa}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 4. Soil & Nutrition Inspection Priority (Section 5) */}
        <div
          data-testid="dss-soil-priority-section"
          style={{
            marginBottom: 28,
            padding: '16px 18px',
            borderRadius: 10,
            background:
              soilAssessment.status === 'candidate'
                ? '#fff9c4'
                : soilAssessment.status === 'no_candidate'
                  ? '#f1f8e9'
                  : '#f5f5f5',
            border: `1px solid ${
              soilAssessment.status === 'candidate'
                ? '#fbc02d'
                : soilAssessment.status === 'no_candidate'
                  ? '#aed581'
                  : '#e0e0e0'
            }`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: '1.2rem' }}>🧪</span>
            <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#3e2723' }}>
              اولویت بررسی خاک و تغذیه — Soil & Nutrition Priority
            </h4>
            <span
              className={`badge ${
                soilAssessment.status === 'candidate'
                  ? 'badge-warning'
                  : soilAssessment.status === 'no_candidate'
                    ? 'badge-good'
                    : 'badge-secondary'
              }`}
              style={{ fontSize: '0.78rem' }}
            >
              {soilAssessment.status === 'candidate'
                ? 'وضعیت A — کاندید بازدید'
                : soilAssessment.status === 'no_candidate'
                  ? 'وضعیت B — بدون کاندید بارز'
                  : 'وضعیت C — شواهد ناکافی'}
            </span>
          </div>

          <div style={{ fontWeight: 600, fontSize: '0.88rem', color: '#bf360c', marginBottom: 6 }}>
            {soilAssessment.headlineFa}
          </div>
          <p style={{ margin: '0 0 10px', fontSize: '0.83rem', lineHeight: 1.6, color: '#37474f' }}>
            {soilAssessment.statementFa}
          </p>

          <div
            style={{
              padding: '8px 12px',
              background: '#ffffff',
              borderRadius: 6,
              border: '1px solid #ffe082',
              fontSize: '0.78rem',
              color: '#d84315',
              lineHeight: 1.5,
            }}
          >
            {soilAssessment.disclaimerFa}
          </div>
        </div>

        {/* 5. Conditional: Pistachio Orchard Assessment (Section 6) */}
        {landUseType === 'pistachio' && (
          <div
            data-testid="dss-pistachio-section"
            style={{
              marginBottom: 28,
              padding: '18px 20px',
              borderRadius: 10,
              background: '#fafafa',
              border: '2px solid #66bb6a',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <span style={{ fontSize: '1.3rem' }}>🥜</span>
              <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#1b5e20' }}>
                تحلیل تخصصی وضعیت باغ پسته — Pistachio Orchard Decision Support
              </h4>
              <span className="badge badge-good" style={{ fontSize: '0.75rem' }}>
                Context: Pistachio
              </span>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                gap: 12,
                marginBottom: 16,
              }}
            >
              <div
                style={{
                  background: '#ffffff',
                  padding: '12px 14px',
                  borderRadius: 8,
                  border: '1px solid #e0e0e0',
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '0.84rem', color: '#2e7d32', marginBottom: 4 }}>
                  🌳 پوشش کانوپی و درختان:
                </div>
                <div style={{ fontSize: '0.8rem', color: '#424242', lineHeight: 1.5 }}>
                  {pistachioSummary.canopyCoverFa}
                </div>
              </div>

              <div
                style={{
                  background: '#ffffff',
                  padding: '12px 14px',
                  borderRadius: 8,
                  border: '1px solid #e0e0e0',
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '0.84rem', color: '#2e7d32', marginBottom: 4 }}>
                  🗺️ ناهمگنی باغ:
                </div>
                <div style={{ fontSize: '0.8rem', color: '#424242', lineHeight: 1.5 }}>
                  {pistachioSummary.heterogeneityFa}
                </div>
              </div>

              <div
                style={{
                  background: '#ffffff',
                  padding: '12px 14px',
                  borderRadius: 8,
                  border: '1px solid #e0e0e0',
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '0.84rem', color: '#c62828', marginBottom: 4 }}>
                  🎯 نواحی نیازمند بررسی:
                </div>
                <div style={{ fontSize: '0.8rem', color: '#424242', lineHeight: 1.5 }}>
                  {pistachioSummary.priorityZonesFa}
                </div>
              </div>

              <div
                style={{
                  background: '#ffffff',
                  padding: '12px 14px',
                  borderRadius: 8,
                  border: '1px solid #e0e0e0',
                }}
              >
                <div style={{ fontWeight: 600, fontSize: '0.84rem', color: '#00695c', marginBottom: 4 }}>
                  💧 تنش و رطوبت:
                </div>
                <div style={{ fontSize: '0.8rem', color: '#424242', lineHeight: 1.5 }}>
                  {pistachioSummary.stressFa}
                </div>
              </div>
            </div>

            {/* Canopy yellowing & chlorophyll assessment (Section 7) */}
            <div
              style={{
                background: '#ffffff',
                padding: '12px 14px',
                borderRadius: 8,
                border: '1px solid #e0e0e0',
                marginBottom: 12,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.84rem', color: '#f57f17', marginBottom: 4 }}>
                🍂 وضعیت سبزی و کلروفیل تاج:
              </div>
              <div style={{ fontSize: '0.81rem', color: '#424242', lineHeight: 1.5 }}>
                {yellowingAssessment.headlineFa}: {yellowingAssessment.explanationFa}
              </div>
              <div style={{ marginTop: 4, fontSize: '0.78rem', color: '#757575', lineHeight: 1.4 }}>
                {yellowingAssessment.cautionFa}
              </div>
            </div>

            {/* Branch dieback limitation boundary (Section 8) */}
            <div
              style={{
                background: '#fff3e0',
                padding: '12px 14px',
                borderRadius: 8,
                border: '1px solid #ffe0b2',
                marginBottom: 14,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.84rem', color: '#e65100', marginBottom: 4 }}>
                ⚠️ هشدار محدودیت علمی: پایش خشکیدگی سرشاخه
              </div>
              <div style={{ fontSize: '0.8rem', color: '#5d4037', lineHeight: 1.5 }}>
                {pistachioSummary.diebackFa}
              </div>
            </div>

            {/* Pistachio Yield Model Disclosure (Section 10 & 11) */}
            <div
              data-testid="pistachio-yield-model-panel"
              style={{
                background: '#f5f5f5',
                padding: '14px 16px',
                borderRadius: 8,
                border: '1px solid #bdbdbd',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 8,
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#37474f' }}>
                  📈 برآورد عملکرد پسته (Yield Estimation)
                </div>
                <span className="badge badge-secondary" style={{ fontSize: '0.75rem' }}>
                  {pistachioSummary.yieldStatus.statusLabelFa}
                </span>
              </div>
              <div style={{ fontSize: '0.81rem', color: '#c62828', fontWeight: 600, marginBottom: 6 }}>
                دلیل عدم نمایش عدد تناژ: {pistachioSummary.yieldStatus.reasonFa}
              </div>
              <div style={{ fontSize: '0.8rem', color: '#455a64', lineHeight: 1.5, marginBottom: 8 }}>
                {pistachioSummary.yieldStatus.improvementPriorityNoteFa}
              </div>

              <details style={{ marginTop: 6 }}>
                <summary style={{ cursor: 'pointer', fontSize: '0.78rem', color: '#1565c0' }}>
                  📋 داده‌های الزامی جهت کالیبراسیون و فعال‌سازی مدل عملکرد در آینده (کلیک کنید)
                </summary>
                <ul style={{ margin: '8px 0 0', paddingRight: 20, fontSize: '0.78rem', color: '#616161' }}>
                  {pistachioSummary.yieldStatus.prerequisitesFa.map((req, idx) => (
                    <li key={idx} style={{ marginBottom: 4 }}>
                      {req}
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          </div>
        )}

        {/* 6. Pest & Disease Surveillance Alert (Section 9) */}
        <div
          data-testid="dss-pest-surveillance-section"
          style={{
            marginBottom: 28,
            padding: '16px 18px',
            borderRadius: 10,
            background: pestAssessment.alertLevel === 'candidate_inspection' ? '#ffebee' : '#f5f5f5',
            border: `1px solid ${
              pestAssessment.alertLevel === 'candidate_inspection' ? '#ef9a9a' : '#e0e0e0'
            }`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: '1.2rem' }}>🐛</span>
            <h4 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#b71c1c' }}>
              هشدار پایش آفت و بیماری — Pest & Disease Surveillance
            </h4>
            <span
              className={`badge ${
                pestAssessment.alertLevel === 'candidate_inspection' ? 'badge-danger' : 'badge-good'
              }`}
              style={{ fontSize: '0.78rem' }}
            >
              {pestAssessment.alertLevel === 'candidate_inspection'
                ? 'کاندید بازدید فوری'
                : 'بدون هشدار غیرعادی'}
            </span>
          </div>

          <div style={{ fontWeight: 600, fontSize: '0.86rem', color: '#c62828', marginBottom: 6 }}>
            {pestAssessment.headlineFa}
          </div>
          <p style={{ margin: '0 0 8px', fontSize: '0.83rem', lineHeight: 1.55, color: '#37474f' }}>
            {pestAssessment.statementFa}
          </p>
          <div style={{ fontSize: '0.78rem', color: '#d32f2f', fontWeight: 500 }}>
            {pestAssessment.cautionFa}
          </div>
        </div>

        {/* 7. Recommended Action Plan (Section 12) */}
        <div style={{ marginBottom: 28 }} data-testid="dss-action-plan-section">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: '1.2rem' }}>📋</span>
            <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#1b5e20' }}>
              پیشنهاد اقدام بعدی کشاورز — Action Plan
            </h4>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {actionPlan.map((item) => (
              <div
                key={item.priority}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                  padding: '12px 14px',
                  background: '#f9fbe7',
                  borderRadius: 8,
                  border: '1px solid #dce775',
                }}
              >
                <span
                  className="badge"
                  style={{
                    background: '#33691e',
                    color: '#ffffff',
                    fontWeight: 700,
                    fontSize: '0.78rem',
                    padding: '4px 8px',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {item.priorityTitleFa}
                </span>
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: 6,
                      marginBottom: 4,
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: '0.88rem', color: '#1b5e20' }}>
                      {item.titleFa}
                    </div>
                    <div>
                      {item.gateStatus === 'passed' ? (
                        <span
                          className="badge badge-good"
                          style={{ fontSize: '0.72rem' }}
                          data-testid={`gate-status-${item.priority}`}
                        >
                          ✓ گیت شواهد: معتبر ({item.evidenceDomain})
                        </span>
                      ) : item.gateStatus === 'blocked_by_missing_evidence' ? (
                        <span
                          className="badge badge-danger"
                          style={{ fontSize: '0.72rem' }}
                          data-testid={`gate-status-${item.priority}`}
                        >
                          ⛔ گیت شواهد: مسدود (داده معتبر خاک موجود نیست)
                        </span>
                      ) : (
                        <span
                          className="badge badge-warning"
                          style={{ fontSize: '0.72rem' }}
                          data-testid={`gate-status-${item.priority}`}
                        >
                          ⚠️ گیت شواهد: نیازمند داده بیشتر ({item.evidenceDomain})
                        </span>
                      )}
                    </div>
                  </div>

                  <div style={{ fontSize: '0.82rem', color: '#37474f', lineHeight: 1.5 }}>
                    {item.actionFa}
                  </div>

                  <div
                    style={{
                      fontSize: '0.76rem',
                      color:
                        item.gateStatus === 'blocked_by_missing_evidence'
                          ? '#c62828'
                          : item.gateStatus === 'insufficient_evidence'
                            ? '#d84315'
                            : '#2e7d32',
                      marginTop: 4,
                      fontWeight: 600,
                    }}
                  >
                    🛡️ بررسی گیت: {item.gateExplanationFa}
                  </div>

                  <div className="text-muted" style={{ fontSize: '0.74rem', marginTop: 3 }}>
                    مبنای علمی: {item.rationaleFa}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 8. System Limitations Disclosure (Non-Claim Boundaries) */}
        <div
          style={{
            padding: '12px 16px',
            background: '#fafafa',
            borderRadius: 8,
            border: '1px solid #e0e0e0',
          }}
        >
          <div style={{ fontWeight: 600, fontSize: '0.82rem', color: '#616161', marginBottom: 6 }}>
            🛡️ آنچه این سامانه بر اساس اصول سنجش‌ازدور «نمی‌تواند» تشخیص دهد:
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: 6,
              fontSize: '0.76rem',
              color: '#757575',
              lineHeight: 1.4,
            }}
          >
            <div>• تشخیص کمبود دقیق N، P، K یا صدور نسخه کودی بدون آزمون خاک</div>
            <div>• تشخیص قطعی نوع آفت (پسیل، چوبخوار و ...) بدون نمونه‌برداری میدانی</div>
            <div>• تشخیص خشکیدگی سرشاخه تک‌درختان با تفکیک ماهواره‌ای ۱۰ متری</div>
            <div>• برآورد تناژ عملکرد بدون اطلاعات رقم، سن و کالیبراسیون برداشت</div>
          </div>
        </div>
      </div>
    </section>
  );
}
