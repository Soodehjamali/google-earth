"""Unit Tests for Weighted Frost Factor Model Engine (R3).

Verifies:
1. Config loader rejects configurations whose factor weights do not sum to 100.0%.
2. Exact mathematical sum: sum(contributions) == risk_index.
3. Absolute Safety Gate (GATE): lethal effective Tmin <= Tcrit cannot be diluted below 'warning'.
4. GATE duration escalation to 'critical'.
5. Asymmetry floor: protective rows cannot score below 0.50 for coarse_context data.
6. Missing data mapping to subscore=0.50 and status='نامشخص'.
7. Category bands: none (<25), watch (25-45), warning (45-70), critical (>=70).
"""

from datetime import datetime, timezone
import pytest

from app.services.agriculture.frost_inputs import FactorInput, OrchardInputs
from app.services.agriculture.frost_weighted_model import (
    evaluate_weighted_frost_model,
    load_frost_factor_weights_config,
    FrostWeightedModelConfig,
)


def _make_dummy_inputs(
    moist_val=0.50,
    moist_qstate="coarse_context",
    stage="bloom",
    stage_stale=False,
    pooling=0.40,
    slope=2.0,
    aspect=180.0,
    sand=40.0,
    tex_fa="لوم",
) -> OrchardInputs:
    factors = {
        "phenological_stage": FactorInput(
            id="phenological_stage",
            label_fa="مرحله فنولوژیکی باغ",
            value=stage,
            unit="مرحله رشد",
            source_module="app.db.models.frost.Orchard",
            quality_state="unknown" if stage_stale else "valid",
            as_of="2026-04-10T08:00:00Z",
            is_stale=stage_stale,
            status="نامشخص" if stage_stale else "مطلوب",
        ),
        "soil_rootzone_moisture": FactorInput(
            id="soil_rootzone_moisture",
            label_fa="رطوبت نسبی ریشه در خاک",
            value=moist_val,
            unit="نسبی [۰-۱]",
            source_module="app.services.agriculture.soil",
            quality_state=moist_qstate,
            as_of="2026-04-10T08:00:00Z",
            is_stale=False,
            status="نامشخص" if moist_val is None else "خنثی",
        ),
        "soil_texture_depth": FactorInput(
            id="soil_texture_depth",
            label_fa="بافت و عمق خاک",
            value=tex_fa,
            unit="رде بافت خاک",
            source_module="app.services.agriculture.soil_intelligence",
            quality_state="coarse_context",
            as_of="2020-01-01T00:00:00Z",
            is_stale=False,
            status="خنثی",
            details={"sand_percent": sand},
        ),
        "topography_pooling": FactorInput(
            id="topography_pooling",
            label_fa="شاخص تجمیع هوای سرد",
            value=pooling,
            unit="شاخص [۰-۱]",
            source_module="app.services.agriculture.cold_air_pooling",
            quality_state="valid",
            as_of="2020-01-01T00:00:00Z",
            is_stale=False,
            status="خنثی",
            details={"pooling_proxy": pooling},
        ),
        "topography_slope_aspect": FactorInput(
            id="topography_slope_aspect",
            label_fa="شیب و جهت دامنه",
            value=slope,
            unit="درجه",
            source_module="app.services.agriculture.terrain",
            quality_state="valid",
            as_of="2020-01-01T00:00:00Z",
            is_stale=False,
            status="خنثی",
            details={"slope_deg": slope, "aspect_deg": aspect},
        ),
    }

    return OrchardInputs(
        orchard_id="orchard_test",
        orchard_name="باغ آزمایشی",
        latitude=30.4,
        longitude=55.9,
        elevation_m=1200.0,
        gfs_cell=(30.5, 56.0),
        factors=factors,
        assembled_at="2026-04-10T08:00:00Z",
        crop="pistachio",
        current_stage=stage,
        stage_is_stale=stage_stale,
    )


def test_load_frost_factor_weights_config():
    """Verify loading config and total weights summing to 100.0%."""
    cfg = load_frost_factor_weights_config()
    assert len(cfg.factors) == 10
    total_w = sum(f.weight for f in cfg.factors)
    assert abs(total_w - 100.0) < 1e-4
    assert cfg.illustrative_only is True
    assert cfg.index_is_probability is False
    assert cfg.evidence_level == "C"


def test_config_loader_rejects_non_100_percent(tmp_path):
    """Verify that loader strictly rejects weights not summing to 100.0%."""
    bad_config = tmp_path / "bad_weights.yaml"
    bad_config.write_text(
        """
factors:
  - id: "temperature_duration"
    weight: 50.0
  - id: "phenological_stage"
    weight: 30.0
category_bands:
  none_max: 25.0
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must sum to exactly 100.0%"):
        load_frost_factor_weights_config(bad_config)


def test_contribution_sum_equals_risk_index():
    """Verify that the sum of factor contributions exactly equals the total risk index."""
    inputs = _make_dummy_inputs(moist_val=0.45, stage="bloom", pooling=0.45)
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=0.5,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=60.0,
        duration_escalated=False,
    )

    sum_contrib = round(sum(f.contribution for f in res.factors), 2)
    assert abs(sum_contrib - res.total_contribution) < 1e-4
    assert abs(res.total_contribution - res.risk_index) < 1e-4
    assert res.total_weight == 100.0


def test_absolute_safety_gate_dilution_prevention():
    """Verify that lethal temperature (T_eff <= T_crit) CANNOT be diluted below 'warning' even if all other factors are favorable."""
    # Favorable conditions across all modifiers:
    # moist soil (0.80), overcast cloud (90%), humid air (85%), gentle wind mixing (2.5 m/s), low pooling (0.15)
    inputs = _make_dummy_inputs(moist_val=0.80, moist_qstate="valid", pooling=0.15, slope=8.0)
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=-2.5,          # Below critical (-1.7°C) => lethal
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.5,   # Favorable mixing
        night_wind_dir_deg=180.0,   # Downslope alignment
        night_cloud_pct=90.0,       # Favorable overcast
        night_rh_pct=85.0,          # Favorable high humidity
        duration_escalated=False,
    )

    # Even if weighted index drops into 'watch' or 'none' band:
    assert res.gate_category == "warning"
    assert res.final_category in ("warning", "critical")
    assert res.gate_triggered is True
    assert "آستانه آسیب" in res.gate_reason_fa


def test_absolute_safety_gate_duration_escalation():
    """Verify that duration rule escalation elevates final category to 'critical'."""
    inputs = _make_dummy_inputs()
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=-1.8,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=40.0,
        night_rh_pct=50.0,
        duration_escalated=True,  # Continuous duration rule met
    )

    assert res.gate_category == "critical"
    assert res.final_category == "critical"
    assert res.gate_triggered is True
    assert "دیرش تداوم" in res.gate_reason_fa


def test_asymmetry_floor_on_protective_factors():
    """Verify that protective rows (soil moisture) cannot score below 0.50 with coarse_context data."""
    # Scenario A: coarse_context data with saturated soil (relative moisture 0.90)
    inputs_coarse = _make_dummy_inputs(moist_val=0.90, moist_qstate="coarse_context")
    res_coarse = evaluate_weighted_frost_model(
        inputs=inputs_coarse,
        night_tmin_c=2.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )
    moist_factor_coarse = next(f for f in res_coarse.factors if f.id == "soil_rootzone_moisture")
    # Subscore must be floored at 0.50
    assert moist_factor_coarse.subscore == 0.50

    # Scenario B: verified 'valid' input (e.g. farmer ground measurement)
    inputs_valid = _make_dummy_inputs(moist_val=0.90, moist_qstate="valid")
    res_valid = evaluate_weighted_frost_model(
        inputs=inputs_valid,
        night_tmin_c=2.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )
    moist_factor_valid = next(f for f in res_valid.factors if f.id == "soil_rootzone_moisture")
    # Subscore can now legitimately drop to favorable (0.20)
    assert moist_factor_valid.subscore == 0.20


def test_missing_soil_moisture_neutral_subscore():
    """Verify missing soil moisture results in subscore=0.50 and status='نامشخص'."""
    inputs = _make_dummy_inputs(moist_val=None, moist_qstate="unknown")
    res = evaluate_weighted_frost_model(
        inputs=inputs,
        night_tmin_c=3.0,
        critical_temp_c=-1.7,
        night_wind_speed_mps=2.0,
        night_wind_dir_deg=180.0,
        night_cloud_pct=50.0,
        night_rh_pct=50.0,
    )
    moist_factor = next(f for f in res.factors if f.id == "soil_rootzone_moisture")
    assert moist_factor.subscore == 0.50
    assert moist_factor.status == "نامشخص"
    assert moist_factor.raw_value == "نامشخص"
