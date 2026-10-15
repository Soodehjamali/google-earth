import React, { useState } from 'react';
import type { GroundTruthObservation } from '../../types';
import { toPersianDigits, formatPersianDate } from './persianDate';
import JalaliDatePicker from './JalaliDatePicker';

interface GroundTruthFormProps {
  observations: GroundTruthObservation[];
  onAddObservation: (obs: GroundTruthObservation) => void;
  onRemoveObservation: (id: string) => void;
  onLoadSampleData: () => void;
}

export const GroundTruthForm: React.FC<GroundTruthFormProps> = ({
  observations,
  onAddObservation,
  onRemoveObservation,
  onLoadSampleData,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [variable, setVariable] = useState('ndvi');
  const [value, setValue] = useState('0.25');
  const [unit, setUnit] = useState('index');
  const [state, setState] = useState('stressed');
  const [observedOn, setObservedOn] = useState('2024-05-15');
  const [observedOnJalali, setObservedOnJalali] = useState('1403/02/26');
  const [cropType, setCropType] = useState('پسته (Pistachio)');
  const [growthStage, setGrowthStage] = useState('پر شدن مغز و رشد میوه');
  const [observedStress, setObservedStress] = useState('زردی و سوختگی حاشیه برگ و تنک‌شدگی تاج');
  const [pestObservation, setPestObservation] = useState('مشاهده پوره پسیل روی برگ‌های آفتاب‌گیر');
  const [diseaseObservation, setDiseaseObservation] = useState('عدم مشاهده علائم لکه‌برگی یا پوسیدگی طوقه');
  const [irrigationStatus, setIrrigationStatus] = useState('آبیاری منظم غرقابی هر ۲۴ روز');
  const [source, setSource] = useState('agronomist_observation');
  const [quality, setQuality] = useState('good');
  const [notes, setNotes] = useState('بازدید مستقیم کارشناس با رصد چشمی شاخساره');
  const [sampleLat, setSampleLat] = useState<string>('');
  const [sampleLon, setSampleLon] = useState<string>('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newObs: GroundTruthObservation = {
      observation_id: `gt-${Date.now().toString().slice(-5)}`,
      variable,
      metric_key: variable,
      value: value ? parseFloat(value) : null,
      unit,
      state: state || null,
      observed_on: observedOn,
      latitude: sampleLat ? parseFloat(sampleLat) : null,
      longitude: sampleLon ? parseFloat(sampleLon) : null,
      source,
      method: 'field_inspection',
      quality,
      crop_type: cropType,
      growth_stage: growthStage,
      observed_stress: observedStress || undefined,
      pest_observation: pestObservation || undefined,
      disease_observation: diseaseObservation || undefined,
      irrigation_status: irrigationStatus || undefined,
      notes: notes || undefined,
      is_derived: false,
      status: 'available',
    };
    onAddObservation(newObs);
    setIsOpen(false);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 text-slate-100 mb-6">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold text-emerald-400">
              مشاهدات و داده‌های واقعی زمینی (Ground Truth)
            </h3>
            <span className="bg-emerald-500/10 text-emerald-400 text-xs px-2.5 py-0.5 rounded-full border border-emerald-500/20 font-medium">
              مشاهده میدانی واقعی (غیرمشتق ماهواره‌ای)
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            ثبت و اعتبارسنجی داده‌های پایش چشمی باغ، سنسورهای محلی، نمونه‌برداری آفات و آزمایش‌های تشخیصی.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onLoadSampleData}
            className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition-colors flex items-center gap-1.5"
          >
            <span>🧪</span>
            <span>بارگذاری داده آزمایشی (Test Fixture)</span>
          </button>
          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className="px-3.5 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg transition-colors flex items-center gap-1.5"
          >
            <span>{isOpen ? 'بستن فرم' : '+ افزودن مشاهده جدید'}</span>
          </button>
        </div>
      </div>

      {isOpen && (
        <form onSubmit={handleSubmit} className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-4 mb-5 text-xs">
          <div className="font-semibold text-slate-200 mb-3 border-b border-slate-700 pb-2">
            فرم ثبت مشاهده زمینی کارشناس / باغدار
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <div>
              <JalaliDatePicker
                label="تاریخ مشاهده زمینی (تقویم جلالی)"
                valueJalali={observedOnJalali}
                onChange={(jalaliAscii, isoGregorian) => {
                  setObservedOnJalali(jalaliAscii);
                  setObservedOn(isoGregorian);
                }}
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">نوع محصول:</label>
              <input
                type="text"
                value={cropType}
                onChange={(e) => setCropType(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">مرحله رشدی (فنولوژی):</label>
              <input
                type="text"
                value={growthStage}
                onChange={(e) => setGrowthStage(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
            <div>
              <label className="block text-slate-400 mb-1">متغیر سنجش:</label>
              <select
                value={variable}
                onChange={(e) => setVariable(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              >
                <option value="ndvi">NDVI (شادابی پوشش گیاهی)</option>
                <option value="ndre">NDRE (کلروفیل لبه قرمز)</option>
                <option value="ndmi">NDMI (رطوبت سایه‌انداز)</option>
                <option value="soil_moisture">رطوبت خاک</option>
                <option value="observed_stress">تنش مشاهده‌شده عمومی</option>
              </select>
            </div>
            <div>
              <label className="block text-slate-400 mb-1">مقدار اندازه‌گیری‌شده:</label>
              <input
                type="number"
                step="0.01"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">واحد:</label>
              <input
                type="text"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">وضعیت کیفی:</label>
              <select
                value={state}
                onChange={(e) => setState(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              >
                <option value="healthy">سالم (healthy)</option>
                <option value="stressed">تحت تنش (stressed)</option>
                <option value="present">مشاهده شد (present)</option>
                <option value="absent">عدم مشاهده (absent)</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-slate-400 mb-1">علائم تنش مشاهده‌شده (برگ/طوقه/تاج):</label>
              <input
                type="text"
                value={observedStress}
                onChange={(e) => setObservedStress(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">مشاهده آفت میدانی:</label>
              <input
                type="text"
                value={pestObservation}
                onChange={(e) => setPestObservation(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
            <div>
              <label className="block text-slate-400 mb-1">مشاهده بیماری قارچی/باکتریایی:</label>
              <input
                type="text"
                value={diseaseObservation}
                onChange={(e) => setDiseaseObservation(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">وضعیت آبیاری:</label>
              <input
                type="text"
                value={irrigationStatus}
                onChange={(e) => setIrrigationStatus(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">منبع مشاهده:</label>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              >
                <option value="agronomist_observation">کارشناس گیاه‌پزشک / زراعی</option>
                <option value="farmer_observation">مشاهده مستقیم باغدار</option>
                <option value="field_sensor">سنسور پرتابل داخل مزرعه</option>
                <option value="laboratory_result">برگه نتیجه آزمایشگاه</option>
              </select>
            </div>
          </div>

          {/* Optional Sample Point GPS Location */}
          <div className="bg-slate-900/80 border border-slate-700/80 rounded-lg p-3 mb-3">
            <div className="text-slate-300 font-semibold mb-2 flex items-center gap-1.5">
              <span>📍</span>
              <span>موقعیت GPS نقطه نمونه‌برداری میدانی (اختیاری جهت رصد نقطه‌ای در داخل باغ)</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-slate-400 mb-1">عرض جغرافیایی نمونه (Latitude):</label>
                <input
                  type="number"
                  step="0.000001"
                  placeholder="مثال: 32.4279"
                  value={sampleLat}
                  onChange={(e) => setSampleLat(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">طول جغرافیایی نمونه (Longitude):</label>
                <input
                  type="number"
                  step="0.000001"
                  placeholder="مثال: 53.6880"
                  value={sampleLon}
                  onChange={(e) => setSampleLon(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
              </div>
            </div>
            <div className="text-[11px] text-slate-400 mt-1.5">
              این مختصات صرفاً جهت ثبت موقعیت درخت یا ردیف مورد نمونه‌برداری میدانی است و محدوده کل باغ (چندضلعی) را تغییر نمی‌دهد.
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-slate-400 mb-1">کیفیت داده ثبت‌شده:</label>
              <select
                value={quality}
                onChange={(e) => setQuality(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              >
                <option value="good">معتبر و استاندارد (Good)</option>
                <option value="excellent">عالی و آزمایشگاهی (Excellent)</option>
                <option value="moderate">متوسط (Moderate)</option>
              </select>
            </div>
            <div>
              <label className="block text-slate-400 mb-1">توضیحات و یادداشت تکمیلی:</label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="یادداشت کارشناس یا سنسور..."
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-slate-100 focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300"
            >
              انصراف
            </button>
            <button
              type="submit"
              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 rounded text-white font-medium"
            >
              ذخیره مشاهده زمینی
            </button>
          </div>
        </form>
      )}

      {observations.length === 0 ? (
        <div className="bg-slate-800/40 border border-dashed border-slate-700 rounded-lg p-6 text-center text-slate-400 text-xs">
          هیچ مشاهده زمینی ثبتی موجود نیست. برای اعتبارسنجی علمی ماهواره یا ارتقای پایش به سطح ۴، مشاهده جدیدی اضافه کنید یا از نمونه بارگذاری کنید.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {observations.map((obs) => (
            <div
              key={obs.observation_id}
              className="bg-slate-800/70 border border-slate-700/80 rounded-lg p-3 text-xs relative hover:border-slate-600 transition-colors"
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <span className="font-semibold text-emerald-400">
                  {obs.crop_type || 'محصول مزرعه'}
                </span>
                <button
                  type="button"
                  onClick={() => onRemoveObservation(obs.observation_id)}
                  className="text-slate-500 hover:text-rose-400 p-0.5 text-xs transition-colors"
                  title="حذف مشاهده"
                >
                  ✕
                </button>
              </div>

              <div className="text-slate-300 space-y-1">
                <div className="flex justify-between">
                  <span className="text-slate-400">متغیر / شاخص:</span>
                  <span className="font-mono text-slate-200">
                    {obs.variable} = {obs.value !== null && obs.value !== undefined ? toPersianDigits(obs.value) : '—'} {obs.unit}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">تاریخ مشاهده (جلالی):</span>
                  <span>{obs.observed_on ? formatPersianDate(obs.observed_on) : '—'}</span>
                </div>
                {obs.pest_observation && (
                  <div className="flex justify-between text-amber-300/90">
                    <span className="text-slate-400">آفت:</span>
                    <span className="truncate max-w-[170px]" title={obs.pest_observation}>
                      {obs.pest_observation}
                    </span>
                  </div>
                )}
                {obs.observed_stress && (
                  <div className="flex justify-between text-slate-300">
                    <span className="text-slate-400">علائم:</span>
                    <span className="truncate max-w-[170px]" title={obs.observed_stress}>
                      {obs.observed_stress}
                    </span>
                  </div>
                )}
                <div className="flex justify-between items-center text-[11px] text-slate-400 pt-1 border-t border-slate-700/50 mt-1.5">
                  <span>منبع: {obs.source}</span>
                  {obs.is_test_fixture || obs.source === 'test_fixture' || (obs.notes && obs.notes.includes('fixture')) ? (
                    <span className="bg-amber-950/70 text-amber-300 px-1.5 py-0.5 rounded border border-amber-800/50 text-[10px] font-medium" title="Test Fixture — not real ground truth">
                      داده آزمایشی (Test Fixture)
                    </span>
                  ) : (
                    <span className="bg-emerald-950/60 text-emerald-400 px-1.5 py-0.5 rounded border border-emerald-800/40 text-[10px] font-medium">
                      میدانی واقعی
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
