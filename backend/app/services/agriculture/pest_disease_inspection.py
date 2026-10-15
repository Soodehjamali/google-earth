"""Pest & Disease Risk Screening and Multi-Sensor Inspection Service (Phase P1).

Scientific role: Senior Agricultural Remote-Sensing Engineer + Scientific QA Lead.

What this module does:
1. Multi-sensor risk screening (Optical: NDVI, NDRE, NDMI, MSI; Radar: S1 VH, VV, RVI; Thermal: LST, Tair).
2. Temporal change and persistence evaluation across observations.
3. Biotic vs Abiotic compatibility screening based on spatial/meteorological signatures.
4. Scientific evidence hierarchy determination (Levels 0 to 4).
5. Ground truth corroboration and linkage.
6. Deterministic, honest output generation with mandatory scientific safety disclaimers.

NON-NEGOTIABLE SCIENTIFIC SAFETY RULES:
- NO definitive pathogen or pest diagnosis (NEVER name specific pathogens like Verticillium or pests like Psylla).
- NO chemical pesticide or fungicide recommendations.
- STRICT classification into neutral remote-sensing screening patterns only.
- Clear disclaimers indicating field inspection and laboratory testing are mandatory.
- Zero mock, random, or fabricated data. Missing evidence is flagged as insufficient/unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.schemas.agriculture import (
    BioticAbioticAssessment,
    EvidenceHierarchyLevel,
    PestDiseaseInspectionResponse,
    PestDiseasePatternType,
    PestDiseaseRiskLevel,
    SensorEvidenceDetail,
)
from app.services.agriculture.ground_truth import GroundTruthObservation

logger = logging.getLogger(__name__)

# Mandatory scientific disclaimers
DISCLAIMER_FA = (
    "این سامانه صرفاً یک ابزار پایش و غربالگری ریسک مبتنی بر سنجش از دور چندسنسوری است. "
    "تشخیص قطعی نوع آفت، پاتوژن بیماری یا تجویز سموم شیمیایی از طریق ماهواره از نظر علمی ناممکن و غیرمجاز است. "
    "هرگونه اقدام کنترلی یا درمانی نیازمند بازدید میدانی کارشناس گیاه‌پزشک و آزمایشگاه تشخیصی معتبر است."
)

DISCLAIMER_EN = (
    "This system provides multi-sensor remote sensing risk screening only. "
    "Definitive pathogen or pest diagnosis and chemical pesticide prescriptions from satellite imagery "
    "are scientifically impossible and strictly prohibited. Field inspection by certified plant pathologists "
    "and laboratory testing are mandatory before treatment."
)

# Metric Persian display names
METRIC_DISPLAY_NAMES_FA: Dict[str, str] = {
    "ndvi": "شاخص پوشش گیاهی (NDVI)",
    "evi": "شاخص پوشش گیاهی تقویت‌شده (EVI)",
    "ndre": "شاخص لبه قرمز کلروفیل (NDRE)",
    "ndmi": "شاخص رطوبت سایه‌انداز (NDMI)",
    "ndwi": "شاخص تفاوت نرمال‌شده آب (NDWI)",
    "msi": "شاخص تنش رطوبتی (MSI)",
    "sar_vh": "پراکنش برگشتی رادار پلاریزاسیون متقاطع (Sentinel-1 VH)",
    "sar_vv": "پراکنش برگشتی رادار پلاریزاسیون هم‌نام (Sentinel-1 VV)",
    "rvi": "شاخص پوشش راداری (RVI)",
    "lst_day": "دمای سطح زمین روزانه (LST)",
    "lst_celsius": "دمای سطح زمین (LST)",
    "air_temperature_celsius": "دمای هوای ۲ متری (ERA5-Land)",
    "soil_moisture": "رطوبت خاک سطحی (SMAP/ERA5-Land)",
}


def _extract_metric_evidence(
    metric_key: str,
    evidence_bundles: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Find a specific metric item across evidence bundles."""
    for domain_name, bundle in evidence_bundles.items():
        if isinstance(bundle, dict):
            items = bundle.get("items") or []
        else:
            items = getattr(bundle, "items", None) or []
        for item in items:
            key = getattr(item, "metric_key", None) or (
                item.get("metric_key") if isinstance(item, dict) else None
            )
            if key == metric_key:
                val = getattr(item, "value", None) if hasattr(item, "value") else item.get("value")
                status = getattr(item, "status", "available") if hasattr(item, "status") else item.get("status", "available")
                quality = getattr(item, "quality", "good") if hasattr(item, "quality") else item.get("quality", "good")
                return {
                    "metric_key": metric_key,
                    "value": val,
                    "status": status,
                    "quality": quality,
                    "domain": domain_name,
                }
    return None


def _evaluate_optical_evidence(
    evidence_bundles: Mapping[str, Any],
) -> Tuple[List[SensorEvidenceDetail], Dict[str, Any]]:
    """Screen optical vegetation and moisture metrics (NDVI, NDRE, NDMI, MSI)."""
    details: List[SensorEvidenceDetail] = []
    stats: Dict[str, Any] = {
        "has_stress": False,
        "acute_drop": False,
        "available_count": 0,
        "chlorophyll_stress": False,
        "moisture_stress": False,
    }

    # 1. NDVI (Canopy vigor)
    ndvi_info = _extract_metric_evidence("ndvi", evidence_bundles)
    if ndvi_info and ndvi_info.get("value") is not None:
        stats["available_count"] += 1
        val = float(ndvi_info["value"])
        indication = "normal"
        notes = "پوشش گیاهی در محدوده فعال و طبیعی"
        if val < 0.25:
            indication = "stressed"
            notes = "افت شدید پوشش گیاهی یا تنک‌شدگی تاج درختان"
            stats["has_stress"] = True
            stats["acute_drop"] = True
        elif val < 0.38:
            indication = "declining"
            notes = "پوشش گیاهی زیر حد بهینه؛ کاهش توان فتوسنتزی"
            stats["has_stress"] = True
        details.append(
            SensorEvidenceDetail(
                sensor_family="optical",
                metric_key="ndvi",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("ndvi", "NDVI"),
                value=round(val, 4),
                status="available",
                indication=indication,
                weight_in_assessment=1.2,
                notes_fa=notes,
            )
        )
    else:
        details.append(
            SensorEvidenceDetail(
                sensor_family="optical",
                metric_key="ndvi",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("ndvi", "NDVI"),
                status="unavailable",
                indication="normal",
                notes_fa="داده معتبر اپتیکال در بازه انتخابی در دسترس نیست (احتمال پوشش ابر یا عدم عبور ماهواره)",
            )
        )

    # 2. NDRE (Red edge chlorophyll - early stress)
    ndre_info = _extract_metric_evidence("ndre", evidence_bundles)
    if ndre_info and ndre_info.get("value") is not None:
        stats["available_count"] += 1
        val = float(ndre_info["value"])
        indication = "normal"
        notes = "شاخص لبه قرمز کلروفیل در وضعیت پایدار"
        if val < 0.20:
            indication = "stressed"
            notes = "افت محسوس کلروفیل تاج درختان (شاخص حساس به کلروز و تنش زودهنگام برگ)"
            stats["has_stress"] = True
            stats["chlorophyll_stress"] = True
        details.append(
            SensorEvidenceDetail(
                sensor_family="optical",
                metric_key="ndre",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("ndre", "NDRE"),
                value=round(val, 4),
                status="available",
                indication=indication,
                weight_in_assessment=1.3,
                notes_fa=notes,
            )
        )

    # 3. NDMI (Canopy water)
    ndmi_info = _extract_metric_evidence("ndmi", evidence_bundles)
    if ndmi_info and ndmi_info.get("value") is not None:
        stats["available_count"] += 1
        val = float(ndmi_info["value"])
        indication = "normal"
        notes = "رطوبت سایه‌انداز در سطح نرمال"
        if val < 0.10:
            indication = "stressed"
            notes = "تنش دهیدراتاسیون و کاهش رطوبت سلولی برگ‌ها"
            stats["has_stress"] = True
            stats["moisture_stress"] = True
        details.append(
            SensorEvidenceDetail(
                sensor_family="optical",
                metric_key="ndmi",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("ndmi", "NDMI"),
                value=round(val, 4),
                status="available",
                indication=indication,
                weight_in_assessment=1.0,
                notes_fa=notes,
            )
        )

    # 4. MSI (Moisture Stress Index)
    msi_info = _extract_metric_evidence("msi", evidence_bundles)
    if msi_info and msi_info.get("value") is not None:
        stats["available_count"] += 1
        val = float(msi_info["value"])
        indication = "normal"
        notes = "شاخص تنش رطوبتی در محدوده طبیعی"
        if val > 1.6:
            indication = "stressed"
            notes = "افزایش معنادار تنش رطوبتی تاج گیاهی"
            stats["has_stress"] = True
            stats["moisture_stress"] = True
        details.append(
            SensorEvidenceDetail(
                sensor_family="optical",
                metric_key="msi",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("msi", "MSI"),
                value=round(val, 4),
                status="available",
                indication=indication,
                weight_in_assessment=0.9,
                notes_fa=notes,
            )
        )

    return details, stats


def _evaluate_radar_evidence(
    evidence_bundles: Mapping[str, Any],
) -> Tuple[List[SensorEvidenceDetail], Dict[str, Any]]:
    """Screen Sentinel-1 SAR backscatter for canopy structure collapse."""
    details: List[SensorEvidenceDetail] = []
    stats: Dict[str, Any] = {
        "has_structural_loss": False,
        "available_count": 0,
    }

    sar_vh = _extract_metric_evidence("sar_vh", evidence_bundles)
    if sar_vh and sar_vh.get("value") is not None:
        stats["available_count"] += 1
        val = float(sar_vh["value"])
        indication = "normal"
        notes = "پراکنش حجمی رادار بازتابنده ساختار شاخساره در وضعیت طبیعی"
        # In arid/semi-arid orchard conditions, VH is typically around -18 to -14 dB. Below -21 dB indicates severe defoliation/thinning
        if val < -21.0:
            indication = "volume_loss"
            notes = "افت معنادار پراکنش حجمی رادار؛ سازگار با تنک شدن یا ریزش شدید برگ و تاج درختان"
            stats["has_structural_loss"] = True
        elif val < -19.0:
            indication = "declining"
            notes = "کاهش حجم پراکنش راداری تاج نسبت به حد بهینه"
        details.append(
            SensorEvidenceDetail(
                sensor_family="radar",
                metric_key="sar_vh",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("sar_vh", "Sentinel-1 VH"),
                value=round(val, 2),
                status="available",
                indication=indication,
                weight_in_assessment=1.2,
                notes_fa=notes,
            )
        )
    else:
        details.append(
            SensorEvidenceDetail(
                sensor_family="radar",
                metric_key="sar_vh",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("sar_vh", "Sentinel-1 VH"),
                status="unavailable",
                indication="normal",
                notes_fa="داده رادار Sentinel-1 در این بازه زمانی موجود نیست",
            )
        )

    sar_vv = _extract_metric_evidence("sar_vv", evidence_bundles)
    if sar_vv and sar_vv.get("value") is not None:
        stats["available_count"] += 1
        val = float(sar_vv["value"])
        details.append(
            SensorEvidenceDetail(
                sensor_family="radar",
                metric_key="sar_vv",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("sar_vv", "Sentinel-1 VV"),
                value=round(val, 2),
                status="available",
                indication="normal",
                weight_in_assessment=0.8,
                notes_fa="پراکنش عمودی رادار ثبت‌شده",
            )
        )

    return details, stats


def _evaluate_thermal_evidence(
    evidence_bundles: Mapping[str, Any],
) -> Tuple[List[SensorEvidenceDetail], Dict[str, Any]]:
    """Screen surface temperature (LST) and ambient air temperature (ERA5)."""
    details: List[SensorEvidenceDetail] = []
    stats: Dict[str, Any] = {
        "has_thermal_stress": False,
        "available_count": 0,
        "lst_value": None,
        "air_value": None,
    }

    lst_info = _extract_metric_evidence("lst_day", evidence_bundles) or _extract_metric_evidence("lst_celsius", evidence_bundles)
    if lst_info and lst_info.get("value") is not None:
        stats["available_count"] += 1
        val = float(lst_info["value"])
        stats["lst_value"] = val
        indication = "normal"
        notes = "دمای سطح زمین در بازه متعارف فصلی"
        if val > 42.0:
            indication = "elevated_temp"
            notes = "دمای سطح بسیار بالا؛ مستعد بسته‌شدن روزنه‌ها و تنش گرمایی شدید"
            stats["has_thermal_stress"] = True
        elif val > 36.0:
            indication = "elevated_temp"
            notes = "افزایش دمای سطح نسبت به دمای بهینه فیزیولوژیک"
        details.append(
            SensorEvidenceDetail(
                sensor_family="thermal",
                metric_key="lst_celsius",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("lst_celsius", "دمای سطح زمین (LST)"),
                value=round(val, 2),
                status="available",
                indication=indication,
                weight_in_assessment=1.1,
                notes_fa=notes,
            )
        )
    else:
        details.append(
            SensorEvidenceDetail(
                sensor_family="thermal",
                metric_key="lst_celsius",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("lst_celsius", "دمای سطح زمین (LST)"),
                status="unavailable",
                indication="normal",
                notes_fa="داده دمای حرارتی زمین (LST) در دسترس نیست",
            )
        )

    air_info = _extract_metric_evidence("air_temperature_celsius", evidence_bundles)
    if air_info and air_info.get("value") is not None:
        stats["available_count"] += 1
        val = float(air_info["value"])
        stats["air_value"] = val
        details.append(
            SensorEvidenceDetail(
                sensor_family="thermal",
                metric_key="air_temperature_celsius",
                display_name_fa=METRIC_DISPLAY_NAMES_FA.get("air_temperature_celsius", "دمای هوای ۲ متری"),
                value=round(val, 2),
                status="available",
                indication="normal",
                weight_in_assessment=0.7,
                notes_fa="دمای محیطی هوا به عنوان مرجع اقلیمی",
            )
        )

    return details, stats


def _evaluate_temporal_persistence(
    temporal_section: Any,
) -> Dict[str, Any]:
    """Inspect temporal profiles to check whether the anomaly is sustained or transient."""
    persistence_info: Dict[str, Any] = {
        "multi_temporal_verified": False,
        "consecutive_anomalous_months": 0,
        "direction": "stable",
        "description_fa": "داده چندزمانه برای بررسی پایداری تنش در دسترس نیست",
    }
    if not temporal_section:
        return persistence_info

    changes = getattr(temporal_section, "changes", None)
    if isinstance(changes, dict) and "ndvi" in changes:
        ndvi_change = changes["ndvi"]
        pers = getattr(ndvi_change, "persistence", None)
        if pers:
            longest_below = getattr(pers, "longest_run_below", 0)
            n_anom = getattr(pers, "n_anomalous", 0)
            persistence_info["consecutive_anomalous_months"] = longest_below
            if longest_below >= 2 or n_anom >= 2:
                persistence_info["multi_temporal_verified"] = True
                persistence_info["description_fa"] = (
                    f"تنش در {longest_below} ماه متوالی پایدار بوده است (عدم بازگشت سریع به شرایط نرمال)"
                )
            else:
                persistence_info["description_fa"] = "تغییرات مشاهده‌شده ماهانه کوتاه‌مدت یا گذرا بوده‌اند"

    return persistence_info


def is_observation_real_ground_truth(obs: Any) -> bool:
    """Return True only if the observation is genuine field data, not synthetic/test fixture."""
    if obs is None:
        return False
    if hasattr(obs, "is_real_ground_truth"):
        return obs.is_real_ground_truth
    if isinstance(obs, dict):
        if obs.get("is_test_fixture") or obs.get("is_derived"):
            return False
        source = str(obs.get("source", "")).lower()
        if any(k in source for k in ("fixture", "synthetic", "mock", "demo", "simulat", "test")):
            return False
        quality = str(obs.get("quality", "")).lower()
        if any(k in quality for k in ("test", "synthetic", "mock", "demo", "simulat")):
            return False
        notes = str(obs.get("notes", "")).lower()
        if any(k in notes for k in ("fixture", "synthetic", "mock", "demo", "simulat", "not real", "test data")):
            return False
        obs_id = str(obs.get("observation_id", "")).lower()
        if any(k in obs_id for k in ("mock", "fixture", "synthetic", "sample", "test_gt", "gt-test", "gt-sample")):
            return False
        prov = obs.get("provenance", {}) or {}
        if prov.get("is_test_fixture") or prov.get("synthetic") or prov.get("is_mock") or prov.get("is_demo"):
            return False
        return True
    return False


def _corroborate_ground_truth(
    ground_truth: Sequence[Any],
) -> Dict[str, Any]:
    """Evaluate independently supplied field records for biological or damage symptoms.

    Distinguishes certified real field ground truth from synthetic/test fixtures.
    Synthetic test fixtures are retained for programmatic testing but NEVER produce
    scientific Evidence Level 4.
    """
    corroboration: Dict[str, Any] = {
        "has_ground_truth": False,
        "has_real_ground_truth": False,
        "is_test_fixture": False,
        "sample_count": len(ground_truth),
        "real_sample_count": 0,
        "test_fixture_sample_count": 0,
        "observed_symptoms": [],
        "pest_reports": [],
        "disease_reports": [],
        "confirms_stress": False,
        "summary_fa": "هیچ مشاهده زمینی معتبری برای اعتبارسنجی ارائه نشده است",
    }

    if not ground_truth:
        return corroboration

    corroboration["has_ground_truth"] = True
    symptoms = []
    pests = []
    diseases = []
    real_count = 0
    test_fixture_count = 0

    for item in ground_truth:
        obs = item if isinstance(item, GroundTruthObservation) else (
            GroundTruthObservation.from_dict(item) if isinstance(item, dict) else None
        )
        if not obs or not obs.is_usable:
            continue

        if is_observation_real_ground_truth(obs):
            real_count += 1
        else:
            test_fixture_count += 1

        if obs.observed_stress:
            symptoms.append(obs.observed_stress)
        if obs.pest_observation:
            pests.append(obs.pest_observation)
        if obs.disease_observation:
            diseases.append(obs.disease_observation)
        if obs.state in ("stressed", "present") or (obs.value is not None and obs.value < 0.35 and obs.variable == "ndvi"):
            corroboration["confirms_stress"] = True

    corroboration["real_sample_count"] = real_count
    corroboration["test_fixture_sample_count"] = test_fixture_count
    corroboration["has_real_ground_truth"] = (real_count > 0)
    corroboration["is_test_fixture"] = (test_fixture_count > 0 and real_count == 0)

    corroboration["observed_symptoms"] = symptoms
    corroboration["pest_reports"] = pests
    corroboration["disease_reports"] = diseases

    if corroboration["is_test_fixture"]:
        base_desc = []
        if pests:
            base_desc.append(f"گزارش آفت: {', '.join(pests)}")
        if diseases:
            base_desc.append(f"گزارش بیماری: {', '.join(diseases)}")
        if symptoms:
            base_desc.append(f"علائم: {', '.join(symptoms)}")
        desc_str = f" ({'؛ '.join(base_desc)})" if base_desc else ""
        corroboration["summary_fa"] = (
            f"داده آزمایشی (Test Fixture — not real ground truth){desc_str}؛ "
            "صرفاً جهت تست نرم‌افزاری بوده و فاقد ارزش اعتبارسنجی میدانی برای ارتقا به سطح ۴ است."
        )
    elif pests or diseases or symptoms:
        corroboration["confirms_stress"] = True
        parts = []
        if pests:
            parts.append(f"گزارش آفت میدانی: {', '.join(pests)}")
        if diseases:
            parts.append(f"گزارش بیماری میدانی: {', '.join(diseases)}")
        if symptoms:
            parts.append(f"علائم ظاهری: {', '.join(symptoms)}")
        corroboration["summary_fa"] = "؛ ".join(parts)
    elif corroboration["confirms_stress"]:
        corroboration["summary_fa"] = "مشاهده زمینی وجود تنش در مزرعه را تأیید می‌کند"
    else:
        corroboration["summary_fa"] = "مشاهده زمینی در دسترس است اما تنش حادی ثبت نکرده است"

    return corroboration


def _assess_biotic_vs_abiotic(
    optical_stats: Dict[str, Any],
    radar_stats: Dict[str, Any],
    thermal_stats: Dict[str, Any],
    ground_truth_stats: Dict[str, Any],
) -> BioticAbioticAssessment:
    """Screen compatibility with biotic versus abiotic causes based on physical signatures."""
    biotic_score = 0.0
    abiotic_score = 0.0
    spatial_uniformity = "unknown"
    weather_corr = "unknown"
    canopy_decay = "not_detected"

    # Abiotic signatures (heatwave, widespread drought):
    # - High thermal stress + moisture stress
    if thermal_stats.get("has_thermal_stress") and optical_stats.get("moisture_stress"):
        abiotic_score += 0.65
        weather_corr = "correlated_with_drought_heat"
        spatial_uniformity = "uniform"

    # Biotic signatures:
    # - Specific chlorophyll drop (NDRE) without matching acute weather catastrophe
    # - Structural collapse (Radar VH drop) while soil moisture/air temp wasn't extreme
    if optical_stats.get("chlorophyll_stress"):
        biotic_score += 0.4
    if radar_stats.get("has_structural_loss"):
        canopy_decay = "detected"
        biotic_score += 0.35
        abiotic_score += 0.25

    # Ground truth confirmation (ONLY real ground truth boosts score):
    if ground_truth_stats.get("has_real_ground_truth") and (
        ground_truth_stats.get("pest_reports") or ground_truth_stats.get("disease_reports")
    ):
        biotic_score += 0.5
        abiotic_score = max(0.0, abiotic_score - 0.2)

    biotic_score = min(1.0, round(biotic_score, 2))
    abiotic_score = min(1.0, round(abiotic_score, 2))

    if biotic_score > 0.55 and biotic_score > abiotic_score:
        compatible_type = "biotic"
        reasoning_fa = (
            "الگوی افت فتوسنتزی و ساختار تاج بدون همبستگی انحصاری با خشکسالی منطقه‌ای، "
            "با احتمال تنش زیستی (آلودگی آفت یا بیماری برگی/ریشه‌ای) سازگارتر است."
        )
        reasoning_en = (
            "Canopy photosynthetic and structural decline without exclusive correlation to regional weather "
            "is more compatible with biotic stress factors (pests or plant pathology)."
        )
    elif abiotic_score > 0.55 and abiotic_score >= biotic_score:
        compatible_type = "abiotic"
        reasoning_fa = (
            "همزمانی تنش دمایی بالا، افت رطوبت و کاهش پوشش گیاهی در کل منطقه، "
            "بیشتر بازتابنده تنش غیرزیستی (خشکی، تنش گرمایی یا کم‌آبیابیاری) است."
        )
        reasoning_en = (
            "Concurrent high surface temperature, moisture deficit, and broad vegetation decline "
            "reflects abiotic stress (drought, extreme heat, or water deficit)."
        )
    elif biotic_score > 0.3 or abiotic_score > 0.3:
        compatible_type = "mixed"
        reasoning_fa = (
            "شواهد سنسوری نشان‌دهنده اثرات متقابل است؛ ممکن است تنش کم‌آبی زمینه را برای هجوم آفت یا شیوع بیماری فراهم کرده باشد."
        )
        reasoning_en = (
            "Sensory evidence indicates intersecting factors; water deficit may have predisposed trees to pest or pathogen susceptibility."
        )
    else:
        compatible_type = "none"
        reasoning_fa = "هیچ آنومالی بارزی حاکی از تنش زیستی یا غیرزیستی شدید شناسایی نشد."
        reasoning_en = "No significant anomaly indicating severe biotic or abiotic stress was detected."

    return BioticAbioticAssessment(
        compatible_stress_type=compatible_type,
        biotic_compatibility_score=biotic_score,
        abiotic_compatibility_score=abiotic_score,
        spatial_uniformity=spatial_uniformity,
        weather_correlation=weather_corr,
        canopy_structural_decay=canopy_decay,
        reasoning_fa=reasoning_fa,
        reasoning_en=reasoning_en,
    )


def inspect_pest_disease_risk(
    start_date: str,
    end_date: str,
    evidence_bundles: Mapping[str, Any],
    temporal_section: Optional[Any] = None,
    ground_truth_records: Optional[Sequence[Any]] = None,
    request_id: Optional[str] = None,
) -> PestDiseaseInspectionResponse:
    """Run full multi-sensor risk screening, pattern classification, and evidence hierarchy determination."""
    optical_details, optical_stats = _evaluate_optical_evidence(evidence_bundles)
    radar_details, radar_stats = _evaluate_radar_evidence(evidence_bundles)
    thermal_details, thermal_stats = _evaluate_thermal_evidence(evidence_bundles)
    temporal_persistence = _evaluate_temporal_persistence(temporal_section)
    ground_truth_stats = _corroboration = _corroborate_ground_truth(ground_truth_records or [])

    biotic_abiotic = _assess_biotic_vs_abiotic(
        optical_stats, radar_stats, thermal_stats, ground_truth_stats
    )

    total_available_sensors = (
        optical_stats["available_count"]
        + radar_stats["available_count"]
        + thermal_stats["available_count"]
    )

    # 1. Determine Evidence Hierarchy Level (0 to 4)
    # Level 4: Remote sensing + genuine, certified Ground Truth validated (NEVER test fixture)
    # Level 3: Multi-sensor concordance (Optical + Radar + Thermal)
    # Level 2: Multi-temporal evidence
    # Level 1: Single sensor indication
    # Level 0: No evidence
    hierarchy_level = 0
    hierarchy_title_fa = "سطح ۰: بدون شواهد"
    hierarchy_desc_fa = "داده‌های ماهواره‌ای معتبر به دلیل پوشش ابر یا عدم رصد در دسترس نیست."

    # First evaluate the sensory/temporal evidence hierarchy (Levels 0, 1, 2, 3)
    if total_available_sensors == 0:
        hierarchy_level = 0
        hierarchy_title_fa = "سطح ۰: بدون شواهد"
        hierarchy_desc_fa = "داده‌های ماهواره‌ای معتبر به دلیل پوشش ابر یا عدم رصد در دسترس نیست."
    elif (
        optical_stats["has_stress"]
        and (radar_stats["has_structural_loss"] or thermal_stats["has_thermal_stress"])
        and total_available_sensors >= 3
    ):
        hierarchy_level = 3
        hierarchy_title_fa = "سطح ۳: همگرایی چندسنسوری (Multi-Sensor Concordance)"
        hierarchy_desc_fa = (
            "سنسورهای اپتیکال (NDVI/NDRE)، رادار (Sentinel-1 SAR) و حرارتی (LST) همگی بر وجود تنش ساختاری و فیزیولوژیک همگرا هستند."
        )
    elif temporal_persistence.get("multi_temporal_verified"):
        hierarchy_level = 2
        hierarchy_title_fa = "سطح ۲: پایداری چندزمانه (Multi-Temporal Persistence)"
        hierarchy_desc_fa = (
            "افت شاخص‌ها در بیش از یک بازه زمانی متوالی مشاهده شده و نشان‌دهنده یک پدیده پایدار است، نه نویز موقت."
        )
    elif total_available_sensors >= 1:
        hierarchy_level = 1
        hierarchy_title_fa = "سطح ۱: شواهد تک‌سنسوری (Single-Sensor Indication)"
        hierarchy_desc_fa = (
            "شواهد صرفاً از یک سیستم سنجنده‌ای (عمدتاً اپتیکال) به دست آمده و تأییدیه چندسنسوری یا میدانی ندارد."
        )

    # Level 4 is EXCLUSIVELY granted when GENUINE, NON-FIXTURE ground truth is present
    if ground_truth_stats.get("has_real_ground_truth") and (
        optical_stats["has_stress"] or ground_truth_stats["confirms_stress"]
    ):
        hierarchy_level = 4
        hierarchy_title_fa = "سطح ۴: اعتبارسنجی تلفیقی با داده‌های میدانی (Ground Truth Validated)"
        hierarchy_desc_fa = (
            "شواهد سنجش از دور با مشاهدات ثبتی مستقیم کارشناس در زمین مطابقت داده شده و اعتبارسنجی گردیده است."
        )
    elif ground_truth_stats.get("is_test_fixture"):
        logger.info(
            "Test fixture ground truth detected: Evidence level 4 suppressed per scientific safety gate."
        )

    # 2. Determine Pattern Type and Risk Level
    overall_risk = PestDiseaseRiskLevel.INSUFFICIENT
    risk_fa = "شواهد ناکافی"
    pattern = PestDiseasePatternType.INSUFFICIENT_EVIDENCE
    pattern_title_fa = "شواهد ناکافی برای غربالگری"
    pattern_summary_fa = "داده‌های سنسوری لازم برای قضاوت تحلیلی در این بازه کافی نیست."

    if total_available_sensors == 0:
        overall_risk = PestDiseaseRiskLevel.INSUFFICIENT
        risk_fa = "شواهد ناکافی"
        pattern = PestDiseasePatternType.INSUFFICIENT_EVIDENCE
        pattern_title_fa = "شواهد ناکافی برای ارزیابی"
        pattern_summary_fa = "به دلیل عدم وجود تصاویر باکیفیت ماهواره‌ای، غربالگری ریسک امکان‌پذیر نیست."
    elif not optical_stats["has_stress"] and not radar_stats["has_structural_loss"] and not thermal_stats["has_thermal_stress"]:
        overall_risk = PestDiseaseRiskLevel.NONE
        risk_fa = "بدون آنومالی (ریسک پایین)"
        pattern = PestDiseasePatternType.NO_ANOMALY
        pattern_title_fa = "عدم مشاهده آنومالی معنادار در تاج پوشش"
        pattern_summary_fa = "شاخص‌های پوشش گیاهی، ساختار راداری و دمای سطح همگی در بازه بهینه و پایدار قرار دارند."
    else:
        # We have some stress detected
        has_real_gt = ground_truth_stats.get("has_real_ground_truth", False)

        if biotic_abiotic.compatible_stress_type == "biotic":
            if has_real_gt:
                pattern = PestDiseasePatternType.POSSIBLE_BIOTIC_STRESS
                pattern_title_fa = "الگوی تنش زیستی (تأییدشده با مشاهدات میدانی)"
                pattern_summary_fa = (
                    "افت بارز شاخص‌های کلروفیل یا ساختار تاج با مشاهدات میدانی ثبت‌شده همخوانی دارد."
                )
                overall_risk = (
                    PestDiseaseRiskLevel.HIGH
                    if hierarchy_level >= 3
                    else PestDiseaseRiskLevel.ELEVATED
                )
                risk_fa = "ریسک تنش زیستی (تأیید میدانی آفت/بیماری)"
            else:
                # STRICT SCIENTIFIC RULE: Never diagnose pest or disease without ground truth evidence!
                pattern = PestDiseasePatternType.POSSIBLE_BIOTIC_STRESS
                pattern_title_fa = "ناهنجاری سنجش از دور؛ علت نامشخص"
                pattern_summary_fa = (
                    "افت شاخص‌های کلروفیل یا ساختار تاج بدون همبستگی انحصاری با خشکسالی عمومی مشاهده شده است. "
                    "با توجه به فقدان داده‌های زمینی و آزمایشگاهی، انتساب این ناهنجاری به آفت یا بیماری غیرمجاز است "
                    "و علت آن از منظر سنجش از دور «نامشخص» تلقی می‌گردد (نیازمند بازدید گیاه‌پزشک)."
                )
                overall_risk = (
                    PestDiseaseRiskLevel.MODERATE
                    if hierarchy_level < 3
                    else PestDiseaseRiskLevel.ELEVATED
                )
                risk_fa = "ناهنجاری رصدی سنجش از دور (فاقد شواهد تشخیصی آفت یا بیماری)"
        elif biotic_abiotic.compatible_stress_type == "abiotic":
            pattern = PestDiseasePatternType.POSSIBLE_ABIOTIC_STRESS
            pattern_title_fa = "ناهنجاری سنجش از دور؛ همبسته با تنش‌های محیطی و اقلیمی"
            pattern_summary_fa = (
                "الگوی افت با خشکی عمومی خاک و دمای بالای محیطی همبسته است و ناشی از عوامل اقلیمی و آبیاری ارزیابی می‌شود، نه لزوماً عوامل بیماری‌زا."
            )
            overall_risk = PestDiseaseRiskLevel.MODERATE
            risk_fa = "تنش محیطی و اقلیمی (فاقد شواهد آفت یا بیماری)"
        elif biotic_abiotic.compatible_stress_type == "mixed":
            pattern = PestDiseasePatternType.MIXED_CONFLICTING
            pattern_title_fa = "ناهنجاری سنجش از دور؛ شواهد متناقض یا چندگانه"
            pattern_summary_fa = (
                "شواهد سنسوری نشان‌دهنده همپوشانی عوامل محیطی و زوال پوشش گیاهی است؛ تعیین دقیق علت منوط به ارزیابی میدانی است."
            )
            overall_risk = PestDiseaseRiskLevel.MODERATE
            risk_fa = "ناهنجاری رصدی (شواهد مرکب محیطی)"
        elif temporal_persistence["multi_temporal_verified"]:
            pattern = PestDiseasePatternType.PERSISTENT_DECLINE
            pattern_title_fa = "ناهنجاری سنجش از دور؛ زوال مداوم و مستمر پوشش گیاهی"
            pattern_summary_fa = "روند افت شاخص‌ها در طول زمان تداوم داشته و نیازمند بررسی ریشه‌ای و پایش میدانی است."
            overall_risk = PestDiseaseRiskLevel.ELEVATED
            risk_fa = "ناهنجاری رصدی مداوم (پایش میدانی)"
        elif optical_stats.get("moisture_stress"):
            pattern = PestDiseasePatternType.MOISTURE_STRESS
            pattern_title_fa = "ناهنجاری سنجش از دور؛ افت رطوبت تاجی گیاه"
            pattern_summary_fa = "شاخص‌های رطوبتی تاج (NDMI/MSI) نشان‌دهنده کمبود آب سلولی هستند."
            overall_risk = PestDiseaseRiskLevel.MODERATE
            risk_fa = "تنش رطوبتی گیاه (محیطی/آبیاری)"
        else:
            pattern = PestDiseasePatternType.VEGETATION_STRESS
            pattern_title_fa = "ناهنجاری سنجش از دور؛ کاهش شادابی پوشش گیاهی"
            pattern_summary_fa = "کاهش موضعی در شادابی و سبزیینگی تاج ثبت شده است؛ بدون شواهد اختصاصی نوع آفت یا بیماری قابل تعیین نیست."
            overall_risk = PestDiseaseRiskLevel.MODERATE
            risk_fa = "ناهنجاری رصدی پوشش گیاهی (علت نامشخص)"

    recommended_actions_fa = [
        "بازدید میدانی و بازرسی چشمی از زیر برگ‌ها، طوقه و تنه درختان توسط کارشناس گیاه‌پزشک",
        "در صورت مشاهده علائم زردی موضعی یا سوختگی حاشیه، ارسال نمونه برگ و خاک به آزمایشگاه تخصصی گیاه‌پزشکی",
        "بررسی سلامت سیستم آبرسانی و توزیع یکنواخت آب در کرت‌ها یا قطره‌چکان‌ها جهت رد فرضیه کم‌آبیابیاری",
        "عدم هرگونه سم‌پاشی شیمیایی بدون شناسایی دقیق آزمایشگاهی و توصیه کارشناس ذی‌صلاح",
    ]

    limitations = [
        "سنجش از دور ماهواره‌ای قادر به تشخیص گونه خاص آفت (مانند پسیل یا چوبخوار) یا پاتوژن قارچی/باکتریایی نیست.",
        "علائم در مراحل اولیه آلودگی (پیش از ایجاد تغییر در شاخص‌های تاج درخت) ممکن است در تفکیک مکانی ماهواره آشکار نشوند.",
        "داده‌های سنجش از دور جایگزین روش‌های استاندارد کنترل آفات (IPM) و آزمایش‌های کلینیکی نیستند.",
    ]
    if ground_truth_stats.get("is_test_fixture"):
        limitations.append(
            "مشاهدات زمینی ارائه شده از نوع داده آزمایشی (Test Fixture — not real ground truth) هستند و طبق اصول ایمنی علمی، ارتقای سطح شواهد به سطح ۴ انجام نشد."
        )

    return PestDiseaseInspectionResponse(
        request_id=request_id,
        start_date=start_date,
        end_date=end_date,
        overall_risk_level=overall_risk,
        risk_level_fa=risk_fa,
        pattern_type=pattern,
        pattern_title_fa=pattern_title_fa,
        pattern_summary_fa=pattern_summary_fa,
        evidence_hierarchy_level=hierarchy_level,
        evidence_hierarchy_title_fa=hierarchy_title_fa,
        evidence_hierarchy_description_fa=hierarchy_desc_fa,
        optical_evidence=optical_details,
        radar_evidence=radar_details,
        thermal_evidence=thermal_details,
        biotic_abiotic_assessment=biotic_abiotic,
        ground_truth_corroboration=ground_truth_stats,
        temporal_persistence=temporal_persistence,
        scientific_disclaimer_fa=DISCLAIMER_FA,
        scientific_disclaimer_en=DISCLAIMER_EN,
        recommended_field_actions_fa=recommended_actions_fa,
        limitations=limitations,
    )
