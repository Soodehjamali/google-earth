import { useEffect, useState } from 'react';
import type {
  AgricultureAnalysisRequest,
  AgricultureGeometry,
  GroundTruthObservationInput,
} from '../../types';
import { DOMAIN_META } from '../../types';
import {
  API_DOMAINS,
  CLOUD_DEFAULT,
  CLOUD_MAX,
  CLOUD_MIN,
  REFERENCE_SOURCES,
  REFERENCE_STATES,
  REFERENCE_VARIABLES,
  blankGroundTruthDraft,
  buildAgricultureRequest,
  clampCloudPercent,
  normalizeSelectedDomains,
  parseGeoJsonInput,
  parseGpsInput,
  toGroundTruthRecord,
  validateAnalysisInputs,
  validateGroundTruthDraft,
  type ApiDomain,
  type DomainGroupOption,
} from './request';

export type GeometryInputMode = 'gps' | 'geojson';

interface AnalysisRequestFormProps {
  loading?: boolean;
  showDomainSelection?: boolean;
  fixedDomains?: readonly ApiDomain[];
  /**
   * Workspace domain groups (Prompt 3). When provided — and no
   * fixedDomains — the domain toggle UI renders these groups instead of
   * the raw API domain list. Each group maps to locked `domains[]`
   * values; `metrics` lists are informational only.
   */
  domainGroups?: readonly DomainGroupOption[];
  initialStartDate?: string;
  initialEndDate?: string;
  onSubmit: (request: AgricultureAnalysisRequest) => void;
  onPreviewChange?: (
    geometry: AgricultureGeometry | undefined,
    center: [number, number],
  ) => void;
  onError?: (message: string | null) => void;
}

/**
 * Reusable Comprehensive analysis request form (F1 shared infrastructure).
 * Owns geometry/date/domain/cloud inputs and emits a contract-safe
 * `AgricultureAnalysisRequest` — never `domains: []`.
 */
export default function AnalysisRequestForm({
  loading = false,
  showDomainSelection = true,
  fixedDomains,
  domainGroups,
  initialStartDate = '2025-06-01',
  initialEndDate = '2025-09-01',
  onSubmit,
  onPreviewChange,
  onError,
}: AnalysisRequestFormProps) {
  const [mode, setMode] = useState<GeometryInputMode>('gps');
  const [latitude, setLatitude] = useState('32.4279');
  const [longitude, setLongitude] = useState('53.6880');
  const [geojsonInput, setGeojsonInput] = useState('');
  const [startDate, setStartDate] = useState(initialStartDate);
  const [endDate, setEndDate] = useState(initialEndDate);
  const [selectedDomains, setSelectedDomains] = useState<ReadonlySet<string>>(
    () => new Set<string>(fixedDomains ?? API_DOMAINS),
  );
  const [cloudInput, setCloudInput] = useState(String(CLOUD_DEFAULT));
  const [formError, setFormError] = useState<string | null>(null);
  const [gtOpen, setGtOpen] = useState(false);
  const [gtDraft, setGtDraft] =
    useState<GroundTruthObservationInput>(blankGroundTruthDraft);
  const [gtRecords, setGtRecords] = useState<GroundTruthObservationInput[]>([]);
  const [gtError, setGtError] = useState<string | null>(null);

  function resolveGeometry(): AgricultureGeometry | undefined {
    if (mode === 'gps') {
      const parsed = parseGpsInput(latitude, longitude);
      return 'geometry' in parsed ? parsed.geometry : undefined;
    }
    const parsed = parseGeoJsonInput(geojsonInput);
    return 'geometry' in parsed ? parsed.geometry : undefined;
  }

  const previewGeometry = resolveGeometry();

  function previewCenter(): [number, number] {
    if (mode === 'gps') {
      const lat = parseFloat(latitude);
      const lng = parseFloat(longitude);
      if (!Number.isNaN(lat) && !Number.isNaN(lng)) return [lng, lat];
    }
    return [55.0, 32.0];
  }

  function reportError(message: string | null) {
    setFormError(message);
    onError?.(message);
  }

  // Display-only map preview for the parent. Runs in an effect (never during
  // render); the parent skips state updates when the payload is unchanged.
  useEffect(() => {
    onPreviewChange?.(previewGeometry, previewCenter());
    // Intentionally keyed on raw inputs, not the derived objects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, latitude, longitude, geojsonInput]);

  function toggleDomain(domain: ApiDomain) {
    if (fixedDomains) return;
    setSelectedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain);
      else next.add(domain);
      return next;
    });
  }

  function toggleAllDomains() {
    if (fixedDomains) return;
    setSelectedDomains((prev) =>
      prev.size === API_DOMAINS.length ? new Set<string>() : new Set<string>(API_DOMAINS),
    );
  }

  function toggleGroup(group: DomainGroupOption) {
    if (fixedDomains) return;
    setSelectedDomains((prev) => {
      const next = new Set(prev);
      const hasAll = group.domains.every((domain) => next.has(domain));
      if (hasAll) {
        for (const domain of group.domains) next.delete(domain);
      } else {
        for (const domain of group.domains) next.add(domain);
      }
      return next;
    });
  }

  function isGroupActive(group: DomainGroupOption): boolean {
    return group.domains.every((domain) => selectedDomains.has(domain));
  }

  function setDraftField<K extends keyof GroundTruthObservationInput>(
    key: K,
    value: GroundTruthObservationInput[K],
  ) {
    setGtDraft((prev) => ({ ...prev, [key]: value }));
  }

  function parseOptionalNumber(raw: string): number | null {
    const trimmed = raw.trim();
    if (trimmed.length === 0) return null;
    const parsed = parseFloat(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function handleAddReference() {
    const problem = validateGroundTruthDraft(gtDraft);
    if (problem) {
      setGtError(problem);
      return;
    }
    setGtError(null);
    setGtRecords((prev) => [
      ...prev,
      toGroundTruthRecord(gtDraft, `ref-${prev.length + 1}`),
    ]);
    setGtDraft(blankGroundTruthDraft());
  }

  function handleRemoveReference(index: number) {
    setGtRecords((prev) => prev.filter((_, i) => i !== index));
  }

  function handleSubmit() {
    reportError(null);

    let geometry: AgricultureGeometry;
    if (mode === 'gps') {
      const parsed = parseGpsInput(latitude, longitude);
      if (!('geometry' in parsed)) {
        reportError(parsed.error);
        return;
      }
      geometry = parsed.geometry;
    } else {
      const parsed = parseGeoJsonInput(geojsonInput);
      if (!('geometry' in parsed)) {
        reportError(parsed.error);
        return;
      }
      geometry = parsed.geometry;
    }

    const validationError = validateAnalysisInputs(geometry, startDate, endDate);
    if (validationError) {
      reportError(validationError);
      return;
    }

    const effectiveDomains = fixedDomains
      ? [...fixedDomains]
      : normalizeSelectedDomains([...selectedDomains]);

    onSubmit(
      buildAgricultureRequest({
        geometry,
        start_date: startDate,
        end_date: endDate,
        selectedDomains: effectiveDomains,
        cloud_max_percent: cloudInput,
        groundTruth: gtRecords,
      }),
    );
  }

  const allSelected = selectedDomains.size === API_DOMAINS.length;
  const cloudValue = clampCloudPercent(cloudInput);

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">📍 پارامترهای تحلیل</span>
      </div>
      <div className="card-body">
        {formError && (
          <div className="error-banner">
            <span>⚠️</span>
            <span>{formError}</span>
          </div>
        )}

        <div className="form-group">
          <label className="form-label">نوع ورودی</label>
          <div className="flex gap-1">
            <button
              className={`btn btn-sm ${mode === 'gps' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setMode('gps')}
            >
              📍 مختصات GPS
            </button>
            <button
              className={`btn btn-sm ${mode === 'geojson' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setMode('geojson')}
            >
              📐 GeoJSON
            </button>
          </div>
        </div>

        {mode === 'gps' && (
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">عرض جغرافیایی (Latitude)</label>
              <input
                type="number"
                className="form-input"
                value={latitude}
                onChange={(e) => setLatitude(e.target.value)}
                step="0.0001"
                placeholder="32.4279"
              />
            </div>
            <div className="form-group">
              <label className="form-label">طول جغرافیایی (Longitude)</label>
              <input
                type="number"
                className="form-input"
                value={longitude}
                onChange={(e) => setLongitude(e.target.value)}
                step="0.0001"
                placeholder="53.6880"
              />
            </div>
          </div>
        )}

        {mode === 'geojson' && (
          <div className="form-group">
            <label className="form-label">GeoJSON</label>
            <textarea
              className="form-textarea"
              value={geojsonInput}
              onChange={(e) => setGeojsonInput(e.target.value)}
              placeholder={`{\n  "type": "Polygon",\n  "coordinates": [[\n    [53.68, 32.42],\n    [53.69, 32.42],\n    [53.69, 32.43],\n    [53.68, 32.43],\n    [53.68, 32.42]\n  ]]\n}`}
            />
          </div>
        )}

        <div className="form-row">
          <div className="form-group">
            <label className="form-label">تاریخ شروع</label>
            <input
              type="date"
              className="form-input"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">تاریخ پایان</label>
            <input
              type="date"
              className="form-input"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
        </div>

        {showDomainSelection && !fixedDomains && domainGroups && (
          <div className="form-group">
            <label className="form-label">حوزه‌ها — Domains (multi-select)</label>
            <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
              <button
                className={`btn btn-sm ${allSelected ? 'btn-primary' : 'btn-secondary'}`}
                onClick={toggleAllDomains}
              >
                {allSelected ? '✓ همه حوزه‌ها' : 'همه حوزه‌ها'}
              </button>
              {domainGroups.map((group) => {
                const active = isGroupActive(group);
                return (
                  <button
                    key={group.key}
                    className={`btn btn-sm ${active ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => toggleGroup(group)}
                    title={`domains: ${group.domains.join(', ')}`}
                  >
                    {group.icon} {group.labelFa}
                  </button>
                );
              })}
            </div>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
              {allSelected
                ? 'همه حوزه‌ها انتخاب شده — domains ارسال نمی‌شود (تحلیل کامل)'
                : `${selectedDomains.size} دامنه انتخاب شده — domains[] به Backend ارسال می‌شود`}
            </div>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
              تحلیل بر اساس Domain انجام می‌شود — انتخاب تک‌شاخص (metric) به Backend ارسال نمی‌شود.
              Analysis runs per domain; individual metric selection is not sent.
            </div>
            {domainGroups.map((group) => (
              <details key={`${group.key}-indicators`} style={{ marginTop: 6 }}>
                <summary style={{ cursor: 'pointer', fontSize: '0.8rem' }}>
                  {group.icon} {group.labelFa} — شاخص‌های موجود ({group.metrics.length})
                </summary>
                <div className="flex gap-1" style={{ flexWrap: 'wrap', marginTop: 4 }}>
                  {group.metrics.map((metric) => (
                    <span key={metric} className="badge" dir="ltr">
                      {metric}
                    </span>
                  ))}
                </div>
              </details>
            ))}
          </div>
        )}

        {showDomainSelection && !fixedDomains && !domainGroups && (
          <div className="form-group">
            <label className="form-label">حوزه‌ها — Domains</label>
            <div className="flex gap-1" style={{ flexWrap: 'wrap' }}>
              <button
                className={`btn btn-sm ${allSelected ? 'btn-primary' : 'btn-secondary'}`}
                onClick={toggleAllDomains}
              >
                {allSelected ? '✓ همه حوزه‌ها' : 'همه حوزه‌ها'}
              </button>
              {API_DOMAINS.map((domain) => {
                const meta = DOMAIN_META[domain];
                const active = selectedDomains.has(domain);
                return (
                  <button
                    key={domain}
                    className={`btn btn-sm ${active ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => toggleDomain(domain)}
                  >
                    {meta?.icon ?? ''} {meta?.labelFa ?? domain}
                  </button>
                );
              })}
            </div>
            <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
              {allSelected
                ? 'همه حوزه‌ها انتخاب شده — domains ارسال نمی‌شود (تحلیل کامل)'
                : `${selectedDomains.size} حوزه انتخاب شده`}
            </div>
          </div>
        )}

        <div className="form-group">
          <label className="form-label">
            حداکثر ابر مجاز — Cloud tolerance ({cloudValue}٪)
          </label>
          <input
            type="range"
            min={CLOUD_MIN}
            max={CLOUD_MAX}
            step={1}
            value={cloudValue}
            onChange={(e) => setCloudInput(e.target.value)}
            className="opacity-slider"
          />
        </div>

        <button
          className="btn btn-primary w-full mt-2"
          onClick={handleSubmit}
          disabled={loading || !previewGeometry}
        >
          {loading ? (
            <>
              <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
              در حال تحلیل...
            </>
          ) : (
            <>🔍 تحلیل کشاورزی</>
          )}
        </button>

        <div className="form-group mt-2">
          <button
            type="button"
            className="btn btn-sm btn-secondary w-full"
            onClick={() => setGtOpen((prev) => !prev)}
            aria-expanded={gtOpen}
          >
            {gtOpen ? '▼' : '▶'} 📋 مشاهده مرجع / Ground Truth (اختیاری)
            {gtRecords.length > 0 && ` — ${gtRecords.length} مورد`}
          </button>
          <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: 4 }}>
            فقط برای اعتبارسنجی مرجع لازم است — تحلیل بدون آن هم کار می‌کند.
            Only needed for reference validation; analysis works without it.
          </div>
        </div>

        {gtOpen && (
          <div className="card" style={{ marginTop: 8 }}>
            <div className="card-body" style={{ padding: 12 }}>
              {gtError && (
                <div className="error-banner">
                  <span>⚠️</span>
                  <span>{gtError}</span>
                </div>
              )}

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">متغیر — Variable *</label>
                  <select
                    className="form-select"
                    value={gtDraft.variable ?? ''}
                    onChange={(e) => setDraftField('variable', e.target.value)}
                  >
                    {REFERENCE_VARIABLES.map((variable) => (
                      <option key={variable} value={variable}>
                        {variable}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">تاریخ مشاهده — Observed on *</label>
                  <input
                    type="date"
                    className="form-input"
                    value={gtDraft.observed_on ?? ''}
                    onChange={(e) => setDraftField('observed_on', e.target.value)}
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">مقدار — Value (optional)</label>
                  <input
                    type="number"
                    className="form-input"
                    value={
                      typeof gtDraft.value === 'number' ? String(gtDraft.value) : ''
                    }
                    onChange={(e) =>
                      setDraftField('value', parseOptionalNumber(e.target.value))
                    }
                    placeholder="e.g. 2.0"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">واحد — Unit</label>
                  <input
                    type="text"
                    className="form-input"
                    value={gtDraft.unit ?? ''}
                    onChange={(e) => setDraftField('unit', e.target.value)}
                    placeholder="e.g. index"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">وضعیت — State (optional)</label>
                  <select
                    className="form-select"
                    value={gtDraft.state ?? ''}
                    onChange={(e) =>
                      setDraftField(
                        'state',
                        e.target.value.length > 0 ? e.target.value : null,
                      )
                    }
                  >
                    <option value="">—</option>
                    {REFERENCE_STATES.map((state) => (
                      <option key={state} value={state}>
                        {state}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">منبع — Source *</label>
                  <select
                    className="form-select"
                    value={gtDraft.source ?? ''}
                    onChange={(e) => setDraftField('source', e.target.value)}
                  >
                    {REFERENCE_SOURCES.map((source) => (
                      <option key={source} value={source}>
                        {source}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">روش — Method *</label>
                  <input
                    type="text"
                    className="form-input"
                    value={gtDraft.method ?? ''}
                    onChange={(e) => setDraftField('method', e.target.value)}
                    placeholder="e.g. visual inspection"
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">متریک — Metric key (optional)</label>
                  <input
                    type="text"
                    className="form-input"
                    value={gtDraft.metric_key ?? ''}
                    onChange={(e) =>
                      setDraftField(
                        'metric_key',
                        e.target.value.length > 0 ? e.target.value : null,
                      )
                    }
                    placeholder="e.g. ndvi"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">شناسه مشاهده (optional)</label>
                  <input
                    type="text"
                    className="form-input"
                    value={gtDraft.observation_id ?? ''}
                    onChange={(e) => setDraftField('observation_id', e.target.value)}
                    placeholder="auto: ref-N"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">سلول — Cell (optional)</label>
                  <input
                    type="text"
                    className="form-input"
                    value={gtDraft.cell_id ?? ''}
                    onChange={(e) =>
                      setDraftField(
                        'cell_id',
                        e.target.value.length > 0 ? e.target.value : null,
                      )
                    }
                    placeholder="e.g. r1c1"
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">شروع پنجره (optional)</label>
                  <input
                    type="date"
                    className="form-input"
                    value={gtDraft.window_start ?? ''}
                    onChange={(e) =>
                      setDraftField(
                        'window_start',
                        e.target.value.length > 0 ? e.target.value : null,
                      )
                    }
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">پایان پنجره (optional)</label>
                  <input
                    type="date"
                    className="form-input"
                    value={gtDraft.window_end ?? ''}
                    onChange={(e) =>
                      setDraftField(
                        'window_end',
                        e.target.value.length > 0 ? e.target.value : null,
                      )
                    }
                  />
                </div>
              </div>

              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={handleAddReference}
              >
                + افزودن مشاهده مرجع — Add reference
              </button>

              {gtRecords.length > 0 && (
                <ul style={{ marginTop: 8, paddingInlineStart: 18 }}>
                  {gtRecords.map((record, index) => (
                    <li key={`${record.observation_id}-${index}`} style={{ fontSize: '0.8rem' }}>
                      <code>{record.observation_id}</code> · {record.variable} ·{' '}
                      {record.observed_on} · {record.source}{' '}
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        style={{ marginInlineStart: 8 }}
                        onClick={() => handleRemoveReference(index)}
                        aria-label={`Remove reference ${record.observation_id}`}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
