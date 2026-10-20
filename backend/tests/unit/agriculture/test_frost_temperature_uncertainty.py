"""Unit tests for temperature uncertainty (Z7).

Requirements:
- temperature_uncertainty_c: 5.0 (label: "برآورد از مقایسه با Open-Meteo و ERA5-Land، کالیبره‌نشده")
- margin' = Tmin_eff - T_crit - U in multiplier m
- Two-level gate:
  - Tmin_eff <= T_crit -> critical (بحرانی و GATE)
  - Tmin_eff - U <= T_crit -> at least watch (حداقل دیده‌بانی سرما)
- Scenarios:
  - Tmin = 4.0 (stage bloom) -> at least watch
  - Tmin = 12.0 -> none (عادی)
  - Tmin <= -1.7 -> critical & GATE
- Config verification for values 5.0 and 4.0 / 10.0
"""

import pytest

from app.services.agriculture.frost_inputs import FactorInput, OrchardInputs
from app.services.agriculture.frost_weighted_model import (
    evaluate_weighted_frost_model,
    load_frost_factor_weights_config,
)


def _make_dummy_inputs(
    moist_val=0.45,
    moist_qstate="coarse_context",
    stage="bloom",
    pooling=0.45,
    slope=2.0,
) -> OrchardInputs:
    factors = {
        "phenological_stage": FactorInput(
            id="phenological_stage",
            label_fa="مرحله فنولوژیکی باغ",
            value=stage,
            unit="مرحله رشد",
            source_module="app.db.models.frost.Orchard",
            quality_state="valid",
            as_of="2026-10-20T00:00:00Z",
            is_stale=False,
            status="مطلوب",
        ),
            "soil_rootzone_moisture": FactorInput(
                id="soil_rootzone_moisture",
                label_fa="رطوبت نسبی ریشه در خاک",
                value=moist_val,
                unit="نسبی",
                quality_state=moist_qstate,
                source_module="app.services.agriculture.soil",
                as_of="2026-10-20T00:00:00Z",
                is_stale=False,
            ),
            "soil_texture_depth": FactorInput(
                id="soil_texture_depth",
                label_fa="بافت و عمق خاک",
                value="لوم شنی",
                unit="class",
                quality_state="coarse_context",
                source_module="SoilGrids",
                as_of="2026-10-20T00:00:00Z",
                is_stale=False,
                static=True,
                details={"sand_percent": 60.0},
            ),
            "topography_pooling": FactorInput(
                id="topography_pooling",
                label_fa="شاخص تجمیع هوای سرد",
                value=pooling,
                unit="index",
                quality_state="valid",
                source_module="NASADEM",
                as_of="2026-10-20T00:00:00Z",
                is_stale=False,
                static=True,
            ),
            "topography_slope_aspect": FactorInput(
                id="topography_slope_aspect",
                label_fa="شیب و جهت دامنه",
                value=slope,
                unit="deg",
                quality_state="valid",
                source_module="NASADEM",
                as_of="2026-10-20T00:00:00Z",
                is_stale=False,
                static=True,
                details={"slope_deg": slope, "aspect_deg": 180.0},
            ),
        }
    return OrchardInputs(
        orchard_id="orchard_test_z7",
        orchard_name="باغ آزمایشی عدم‌قطعیت",
        latitude=30.4,
        longitude=55.9,
        elevation_m=1200.0,
        gfs_cell=(30.5, 56.0),
        factors=factors,
        assembled_at="2026-10-20T00:00:00Z",
        crop="pistachio",
        current_stage=stage,
        stage_is_stale=False,
    )


def test_config_reads_temperature_uncertainty_and_margins():
    """Verify that config loads temperature_uncertainty_c (5.0) and margin thresholds (4.0 / 10.0)."""
    cfg = load_frost_factor_weights_config()
    assert cfg.temperature_uncertainty_c == 5.0
    assert "Open-Meteo" in cfg.temperature_uncertainty_label_fa
    assert "ERA5-Land" in cfg.temperature_uncertainty_label_fa
    assert "کالیبره‌نشده" in cfg.temperature_uncertainty_label_fa

    # Margins from temperature_necessity_attenuation
    assert cfg.temperature_necessity["margin_safe_c"] == 4.0
    assert cfg.temperature_necessity["margin_warm_c"] == 10.0
    assert cfg.temperature_necessity["m_min"] == 0.10


def test_tmin_4_bloom_stage_at_least_watch():
    """Verify Z7: Tmin = 4.0 °C in bloom stage (-1.7 °C critical) yields at least 'watch'.

    Physics: margin' = 4.0 - (-1.7) - 5.0 = 0.7 °C <= 4.0 °C => m = 1.0 (no false attenuation).
    Bloom stage vulnerability (25% weight) ensures risk_index >= 25% => 'watch'.
    """
    inputs = _make_dummy_inputs(stage="bloom")
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=4.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )

    # Multiplier must not attenuate the danger
    assert res.necessity_margin_c == pytest.approx(5.7, abs=0.01)
    assert res.necessity_margin_prime_c == pytest.approx(0.7, abs=0.01)
    assert res.necessity_multiplier == 1.0

    # Final category is at least 'watch'
    assert res.final_category in ("watch", "warning", "critical")
    assert res.final_category != "none"


def test_tmin_12_normal_none_category():
    """Verify Z7: Tmin = 12.0 °C yields 'none' (عادی) with attenuation."""
    inputs = _make_dummy_inputs(stage="bloom")
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=12.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )

    # Margin' = 12.0 - (-1.7) - 5.0 = 8.7 °C => heavy attenuation
    assert res.necessity_margin_prime_c == pytest.approx(8.7, abs=0.01)
    assert res.necessity_multiplier < 0.50

    # Normal category and gate inactive
    assert res.final_category == "none"
    assert res.final_category_fa == "عادی (بدون خطر)"
    assert res.gate_triggered is False
    assert res.gate_category == "none"


def test_tmin_below_critical_triggers_critical_gate():
    """Verify Z7: Tmin <= -1.7 °C triggers Level 1 GATE at 'critical'."""
    inputs = _make_dummy_inputs(stage="bloom")
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=-1.7,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )

    assert res.gate_category == "critical"
    assert res.final_category == "critical"
    assert res.gate_triggered is True
    assert "آستانه آسیب" in res.gate_reason_fa
    assert "بحرانی" in res.gate_reason_fa

    # Also test strictly below critical (-2.0 °C)
    res_sub = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=-2.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )
    assert res_sub.gate_category == "critical"
    assert res_sub.final_category == "critical"
    assert res_sub.gate_triggered is True


def test_two_level_gate_dormant_stage_threshold_minus_4():
    """Verify scenario: Tmin = 3.0 °C in dormant stage with its own threshold (-4.0 °C).

    Physics:
    - Tmin = 3.0 °C, U = 5.0 °C, Tcrit = -4.0 °C (dormant / unopened_bud threshold).
    - Tmin - U = 3.0 - 5.0 = -2.0 °C > -4.0 °C => Level 2 GATE is NOT triggered.
    - Low base vulnerability in dormant stage (subscore 0.10) keeps risk_index in 'none' (< 25%).
    - Final category remains 'none' (عادی / بدون خطر).
    """
    inputs = _make_dummy_inputs(
        stage="dormant",
        moist_val=0.90,
        moist_qstate="valid",
        pooling=0.10,
        slope=8.0,
    )
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=3.0,
        critical_temp_c=-4.0,
        night_wind_speed_mps=2.5,
        night_wind_dir_deg=180.0,
        night_cloud_pct=90.0,
        night_rh_pct=85.0,
    )

    # Gate is inactive because Tmin - U (-2.0 °C) > Tcrit (-4.0 °C)
    assert res.gate_triggered is False
    assert res.gate_category == "none"
    assert res.gate_reason_fa is None
    assert res.final_category == "none"
    assert res.final_category_fa == "عادی (بدون خطر)"


def test_two_level_gate_bloom_stage_threshold_minus_1_point_7():
    """Verify scenario: Tmin = 3.0 °C in bloom stage with its threshold (-1.7 °C).

    Physics:
    - Tmin = 3.0 °C, U = 5.0 °C, Tcrit = -1.7 °C (bloom stage threshold Hokmabadi 2010 CIHEAM).
    - Tmin - U = 3.0 - 5.0 = -2.0 °C <= -1.7 °C => Level 2 GATE is triggered!
    - Gate unconditionally forces category to at least 'watch' (دیده‌بانی سرما).
    """
    inputs = _make_dummy_inputs(
        stage="bloom",
        moist_val=0.90,
        moist_qstate="valid",
        pooling=0.10,
        slope=8.0,
    )
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=3.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.5,
        night_wind_dir_deg=180.0,
        night_cloud_pct=90.0,
        night_rh_pct=85.0,
    )

    assert res.gate_triggered is True
    assert res.gate_category == "watch"
    assert res.final_category in ("watch", "warning", "critical")
    assert "عدم‌قطعیت" in res.gate_reason_fa
    assert "دیده‌بانی سرما" in res.gate_reason_fa

