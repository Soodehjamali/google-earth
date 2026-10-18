"""Unit tests for Frost-risk assessment, phenological thresholds loader, and night aggregator.

Verifies:
1. Threshold parser validation: loads valid config, rejects missing provenance,
   rejects placeholder with source, rejects inverted critical temperatures.
2. Night aggregator: groups hours crossing UTC midnight correctly into local night windows.
3. Topography pooling temperature bump with wind damping.
4. Risk level classification across temperature spectrum (none, advisory, watch, warning).
5. Full assessment pipeline with FakeForecastProvider, ensuring thresholds_verified=False
   and generic non-chemical recommendations.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
import yaml

from app.services.agriculture.forecast import FakeForecastProvider, ForecastTimestep
from app.services.agriculture.frost_risk import (
    DEFAULT_LOCAL_UTC_OFFSET_HOURS,
    RISK_LEVEL_ADVISORY,
    RISK_LEVEL_NONE,
    RISK_LEVEL_WARNING,
    RISK_LEVEL_WATCH,
    CropThresholdConfig,
    aggregate_forecast_by_local_night,
    assess_frost_risk,
    calculate_pooling_cooling_bump,
    classify_nightly_risk,
    load_frost_thresholds_config,
)


def test_frost_thresholds_loader_valid_production_config():
    """Verify that root config/frost_thresholds.yaml is valid and strictly unverified."""
    configs = load_frost_thresholds_config()
    assert "pistachio" in configs
    pst = configs["pistachio"]
    assert pst.status == "placeholder"
    assert pst.source is None
    assert pst.verified is False
    assert len(pst.verification_warning_fa) > 10

    # Required stages
    expected_stages = ["dormant", "bud_burst", "early_bloom", "full_bloom", "fruit_set"]
    for s in expected_stages:
        assert s in pst.stages
        st = pst.stages[s]
        assert st.status == "placeholder"
        assert st.source is None
        # Strict thermodynamic check: 90% kill must be colder than 10% kill
        assert st.t_critical_90_c < st.t_critical_10_c


def test_frost_thresholds_loader_rejects_missing_provenance():
    """Verify loader rejects config with missing status or non-null source on placeholder."""
    # Case 1: Missing status
    bad_cfg_1 = {
        "crops": {
            "almond": {
                "common_name_fa": "بادام",
                "stages": {
                    "bloom": {
                        "t_critical_10_c": -2.0,
                        "t_critical_90_c": -4.0,
                        "status": "placeholder",
                    }
                },
            }
        }
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(bad_cfg_1, f)
        p1 = Path(f.name)

    try:
        with pytest.raises(ValueError, match="must disclose 'status'"):
            load_frost_thresholds_config(p1)
    finally:
        p1.unlink(missing_ok=True)

    # Case 2: Status is placeholder but source is falsely claimed
    bad_cfg_2 = {
        "crops": {
            "pistachio": {
                "status": "placeholder",
                "source": "Local University",
                "stages": {
                    "bloom": {
                        "t_critical_10_c": -2.0,
                        "t_critical_90_c": -4.0,
                        "status": "placeholder",
                    }
                },
            }
        }
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(bad_cfg_2, f)
        p2 = Path(f.name)

    try:
        with pytest.raises(ValueError, match="non-null source"):
            load_frost_thresholds_config(p2)
    finally:
        p2.unlink(missing_ok=True)


def test_frost_thresholds_loader_rejects_inverted_temperatures():
    """Verify loader rejects config where t_critical_90 is warmer than t_critical_10."""
    bad_cfg = {
        "crops": {
            "pistachio": {
                "status": "placeholder",
                "source": None,
                "verified": False,
                "stages": {
                    "bloom": {
                        "name_fa": "گلدهی",
                        "t_critical_10_c": -4.0,
                        "t_critical_90_c": -2.0,  # Physically absurd: 90% kill at -2C while 10% kill at -4C!
                        "status": "placeholder",
                        "source": None,
                    }
                },
            }
        }
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.dump(bad_cfg, f)
        p = Path(f.name)

    try:
        with pytest.raises(ValueError, match="thermodynamic violation"):
            load_frost_thresholds_config(p)
    finally:
        p.unlink(missing_ok=True)


def test_night_aggregator_crossing_utc_midnight():
    """Verify that hourly series crossing UTC midnight groups into the correct local night."""
    # Iran is UTC+3.5.
    # Night of 2026-03-20:
    # 18:00 local (14:30 UTC on 2026-03-20) through 09:00 local (05:30 UTC on 2026-03-21).
    # All these hours must belong to night_date = '2026-03-20'.
    series: list[ForecastTimestep] = []
    base_utc = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)

    for h in range(30):
        ts = base_utc + timedelta(hours=h)
        step = ForecastTimestep(
            timestamp_utc=ts.isoformat(),
            lead_hours=float(h),
            temperature_2m_c=5.0,
            temperature_2m_c_raw=5.0,
            elevation_delta_m=0.0,
            elevation_correction_c=0.0,
            elevation_uncertainty_c=0.5,
            lead_time_uncertainty_c=1.0,
            total_uncertainty_c=1.12,
            lower_bound_c=3.88,
            upper_bound_c=6.12,
            temperature_min_c=3.88,
            temperature_max_c=6.12,
            is_interpolated=False,
            wind_speed_10m_mps=1.5,
        )
        series.append(step)

    nights = aggregate_forecast_by_local_night(
        series,
        local_utc_offset_hours=3.5,
        night_start_local_hour=18,
        night_end_local_hour=9,
    )

    assert "2026-03-20" in nights
    n20 = nights["2026-03-20"]
    # Check that steps inside n20 cross midnight:
    # 2026-03-20T15:00:00+00:00 (18:30 local) is present
    # 2026-03-20T23:00:00+00:00 (02:30 local) is present
    # 2026-03-21T01:00:00+00:00 (04:30 local) is present
    timestamps = [s.timestamp_utc for s in n20]
    has_pre_midnight = any("2026-03-20T2" in ts for ts in timestamps)
    has_post_midnight = any("2026-03-21T0" in ts for ts in timestamps)
    assert has_pre_midnight and has_post_midnight, (
        f"Night window did not span across UTC midnight properly: {timestamps}"
    )


def test_cold_air_pooling_bump_and_wind_damping():
    """Verify pooling temperature bump calculation and turbulent wind damping."""
    # Flat / hilltop (proxy <= 0.40) -> 0 bump
    assert calculate_pooling_cooling_bump(0.30, wind_speed_mps=1.0) == 0.0
    assert calculate_pooling_cooling_bump(0.40, wind_speed_mps=1.0) == 0.0

    # Deep valley / basin (proxy = 0.85) under calm winds (1.0 m/s) -> significant cooling bump
    bump_calm = calculate_pooling_cooling_bump(0.85, wind_speed_mps=1.0)
    assert 1.5 <= bump_calm <= 2.2

    # Same valley under high winds (4.5 m/s) -> turbulent mixing breaks inversion, bump = 0
    bump_windy = calculate_pooling_cooling_bump(0.85, wind_speed_mps=4.5)
    assert bump_windy == 0.0


def test_risk_level_classification():
    """Verify frost classification transitions across critical temperature thresholds."""
    tc10 = -2.0
    tc90 = -4.5

    # Safe: well above critical
    level, _ = classify_nightly_risk(
        t_min_adjusted_c=3.0,
        t_min_lower_c=1.5,
        hours_below_tc10=0.0,
        tc10_c=tc10,
        tc90_c=tc90,
    )
    assert level == RISK_LEVEL_NONE

    # Advisory: approaching critical (+1.0°C)
    level, _ = classify_nightly_risk(
        t_min_adjusted_c=-0.5,
        t_min_lower_c=-1.8,
        hours_below_tc10=0.0,
        tc10_c=tc10,
        tc90_c=tc90,
    )
    assert level == RISK_LEVEL_ADVISORY

    # Watch: dropped below 10% threshold
    level, _ = classify_nightly_risk(
        t_min_adjusted_c=-2.2,
        t_min_lower_c=-3.5,
        hours_below_tc10=1.0,
        tc10_c=tc10,
        tc90_c=tc90,
    )
    assert level == RISK_LEVEL_WATCH

    # Warning: dropped below 90% lethal threshold
    level, _ = classify_nightly_risk(
        t_min_adjusted_c=-5.0,
        t_min_lower_c=-6.5,
        hours_below_tc10=4.0,
        tc10_c=tc10,
        tc90_c=tc90,
    )
    assert level == RISK_LEVEL_WARNING


@pytest.mark.asyncio
async def test_end_to_end_frost_risk_assessment():
    """Verify full pipeline: fake forecast provider -> frost risk evaluation."""
    provider = FakeForecastProvider(base_tmin_c=-3.0, base_tmax_c=12.0)
    forecast = await provider.get_hourly_forecast(None, horizon_h=48)

    assessment = assess_frost_risk(
        forecast=forecast,
        crop="pistachio",
        phenological_stage="early_bloom",
        pooling_risk_proxy=0.75,
    )

    assert assessment.crop == "pistachio"
    assert assessment.crop_fa == "پسته"
    assert assessment.stage_fa == "اوایل گلدهی"
    assert assessment.thresholds_status == "placeholder"
    assert assessment.thresholds_verified is False
    assert len(assessment.thresholds_warning_fa) > 0
    assert len(assessment.nightly_risks) >= 2

    # High risk should trigger generic recommendations
    if assessment.overall_risk_level != RISK_LEVEL_NONE:
        for night in assessment.nightly_risks:
            if night.risk_level != RISK_LEVEL_NONE:
                assert len(night.recommendations_fa) >= 3
                assert night.recommendations_review_required is True

    # STRICT CHECK: Ensure NO chemical or hormonal treatments are advised
    all_recs_text = " ".join(
        rec for n in assessment.nightly_risks for rec in n.recommendations_fa
    )
    forbidden_terms = ["هورمون", "محلول‌پاشی شیمیایی", "ضدیخ شیمیایی", "کود فسفیت", "جیبرلین"]
    for term in forbidden_terms:
        assert term not in all_recs_text, f"Forbidden chemical recommendation found: {term}"


def test_lapse_rate_explicit_signs_higher_site_colder():
    """Verify physical lapse-rate sign: higher elevation strictly yields colder temperature."""
    from app.services.agriculture.quality_gating import correct_temperature_for_elevation

    # 1. Higher site than cell mean: z_site > z_cell -> delta_c < 0, corrected < raw
    corr_high = correct_temperature_for_elevation(
        t_cell=10.0,
        z_cell=1000.0,
        z_site=1500.0,  # +500m elevation gain
    )
    assert corr_high.delta_c == -3.25  # -6.5 * 0.5 km = -3.25 °C
    assert corr_high.corrected_value == 6.75
    assert corr_high.corrected_value < corr_high.raw_value

    # 2. Lower site than cell mean: z_site < z_cell -> delta_c > 0, corrected > raw
    corr_low = correct_temperature_for_elevation(
        t_cell=10.0,
        z_cell=1000.0,
        z_site=800.0,  # -200m elevation drop
    )
    assert corr_low.delta_c == +1.30  # -6.5 * -0.2 km = +1.30 °C
    assert corr_low.corrected_value == 11.30
    assert corr_low.corrected_value > corr_low.raw_value

    # 3. Equal elevation: delta_c == 0.0
    corr_equal = correct_temperature_for_elevation(
        t_cell=10.0,
        z_cell=1000.0,
        z_site=1000.0,
    )
    assert corr_equal.delta_c == 0.0
    assert corr_equal.corrected_value == 10.0


def test_cold_air_pooling_never_warms_and_clips_at_zero():
    """Verify pooling adjustment term NEVER warms (strictly clipped at >= 0.0)."""
    # Ridges, negative proxies, or baseline terrain must NEVER produce negative cooling bump
    test_proxies = [-1.0, -0.5, 0.0, 0.1, 0.25, 0.39, 0.40]
    for p in test_proxies:
        bump = calculate_pooling_cooling_bump(p, wind_speed_mps=1.0)
        assert bump == 0.0, f"Expected 0.0 bump for proxy {p}, got {bump}"
        t_raw = 5.0
        t_adjusted = t_raw - bump
        assert t_adjusted <= t_raw, f"Adjustment caused warming: {t_adjusted} > {t_raw}"

    # Over the entire valid range [0.0, 1.0], bump must be non-negative
    for step in range(101):
        proxy_val = step / 100.0
        for wind_val in [0.0, 1.0, 2.5, 4.0, 6.0]:
            b = calculate_pooling_cooling_bump(proxy_val, wind_speed_mps=wind_val)
            assert b >= 0.0, f"Negative cooling bump ({b}) for proxy={proxy_val}, wind={wind_val}"


def test_cold_air_pooling_config_driven_values():
    """Verify ColdAirPoolingAdjustmentConfig parameters drive the computation."""
    from app.services.agriculture.frost_risk import (
        ColdAirPoolingAdjustmentConfig,
        load_cold_air_pooling_config,
    )

    # 1. Custom config override
    custom_cfg = ColdAirPoolingAdjustmentConfig(
        status="placeholder",
        notes="Custom test calibration",
        min_pooling_proxy_threshold=0.50,
        max_cooling_bump_c=3.5,
        wind_speed_calm_mps=2.0,
        wind_speed_drain_mps=5.0,
    )

    # Below custom threshold 0.50 -> 0 bump
    assert calculate_pooling_cooling_bump(0.45, config=custom_cfg) == 0.0

    # Above custom threshold 0.50: proxy=0.75 -> (0.75 - 0.50) / 0.50 * 3.5 = 1.75
    bump = calculate_pooling_cooling_bump(0.75, wind_speed_mps=1.5, config=custom_cfg)
    assert bump == 1.75

    # 2. Production YAML loader loads cold_air_pooling section
    prod_cfg = load_cold_air_pooling_config()
    assert prod_cfg.status == "placeholder"
    assert prod_cfg.min_pooling_proxy_threshold == 0.40
    assert prod_cfg.max_cooling_bump_c == 2.5
    assert prod_cfg.wind_speed_calm_mps == 1.5
    assert prod_cfg.wind_speed_drain_mps == 4.0


@pytest.mark.asyncio
async def test_frost_assessment_evidence_level_and_unknown_stage():
    """Verify evidence_level is C when thresholds_verified=False, B when verified, and conservative fallback for unknown stage."""
    from unittest.mock import patch

    provider = FakeForecastProvider(base_tmin_c=-2.0, base_tmax_c=10.0)
    forecast = await provider.get_hourly_forecast(None, horizon_h=48)

    # Case 1: Unverified crop (pistachio) -> thresholds_verified=False -> evidence_level == "C"
    assessment_unverified = assess_frost_risk(
        forecast=forecast,
        crop="pistachio",
        phenological_stage="unknown",
        pooling_risk_proxy=0.70,
    )
    assert assessment_unverified.thresholds_verified is False
    assert assessment_unverified.evidence_level == "C"
    assert "مرحله فنولوژیکی نامشخص است" in assessment_unverified.thresholds_warning_fa
    # Most sensitive stage for pistachio has the warmest tc10 (e.g. fruit_set at -1.0C)
    assert assessment_unverified.t_critical_10_c == -1.0
    assert assessment_unverified.phenological_stage == "fruit_set"

    # Case 2: Verified crop -> thresholds_verified=True -> evidence_level == "B"
    real_configs = load_frost_thresholds_config()
    pst_cfg = real_configs["pistachio"]
    verified_pst = CropThresholdConfig(
        crop_key=pst_cfg.crop_key,
        common_name_fa=pst_cfg.common_name_fa,
        scientific_name=pst_cfg.scientific_name,
        status="verified",
        source="Agricultural Research Station Calibration",
        verified=True,
        verification_warning_fa="",
        stages=pst_cfg.stages,
    )
    mocked_configs = dict(real_configs)
    mocked_configs["pistachio"] = verified_pst

    with patch("app.services.agriculture.frost_risk.load_frost_thresholds_config", return_value=mocked_configs):
        assessment_verified = assess_frost_risk(
            forecast=forecast,
            crop="pistachio",
            phenological_stage="early_bloom",
            pooling_risk_proxy=0.70,
        )
        assert assessment_verified.thresholds_verified is True
        assert assessment_verified.evidence_level == "B"


def test_lead_time_uncertainty_table_monotonic_growth():
    """Verify lead-time uncertainty table is strictly monotonic and grows with lead time up to 240h."""
    from app.services.agriculture.forecast import (
        DEFAULT_LEAD_TIME_UNCERTAINTY_TABLE,
        get_lead_time_uncertainty,
    )

    prev_h = 0.0
    prev_unc = 0.0
    for max_h, unc in DEFAULT_LEAD_TIME_UNCERTAINTY_TABLE:
        assert unc > prev_unc, f"Uncertainty must strictly grow with lead time: {unc} <= {prev_unc}"
        assert max_h > prev_h, f"Lead hours must strictly increase: {max_h} <= {prev_h}"
        prev_h = max_h
        prev_unc = unc

    # Verify lookups
    assert get_lead_time_uncertainty(12.0) == 1.0    # 0-24h
    assert get_lead_time_uncertainty(36.0) == 1.5    # 24-48h
    assert get_lead_time_uncertainty(60.0) == 2.0    # 48-72h
    assert get_lead_time_uncertainty(100.0) == 2.5   # 72-120h
    assert get_lead_time_uncertainty(180.0) == 3.5   # 120-240h
    assert get_lead_time_uncertainty(300.0) == 4.5   # > 240h


def test_hard_cap_horizon_returns_no_nightly_risk_beyond_cap():
    """Verify that beyond the hard cap (default 240h), no nightly risk is returned."""
    from app.services.agriculture.forecast import ForecastResult, ForecastTimestep

    base_utc = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    series: list[ForecastTimestep] = []

    # Generate 300 hours of forecast (spanning ~12 local nights)
    for h in range(300):
        ts = base_utc + timedelta(hours=h)
        series.append(
            ForecastTimestep(
                timestamp_utc=ts.isoformat(),
                lead_hours=float(h),
                temperature_2m_c=-2.0,  # Freezing throughout
                temperature_2m_c_raw=-2.0,
                elevation_delta_m=0.0,
                elevation_correction_c=0.0,
                elevation_uncertainty_c=0.5,
                lead_time_uncertainty_c=1.5,
                total_uncertainty_c=1.58,
                lower_bound_c=-3.58,
                upper_bound_c=-0.42,
                temperature_min_c=-3.58,
                temperature_max_c=-0.42,
                is_interpolated=False,
                wind_speed_10m_mps=1.5,
            )
        )

    forecast = ForecastResult(
        series=series,
        source="test",
        issue_time_utc=base_utc.isoformat(),
        native_spatial_resolution_m=27830.0,
        native_temporal_resolution_h=1,
        quality_state="coarse_context",
        site_elevation_m=1200.0,
        cell_elevation_m=1200.0,
        horizon_hours=300,
        disclaimer_fa="test",
    )

    # Assess with hard cap = 240h
    assessment_capped = assess_frost_risk(
        forecast=forecast,
        crop="pistachio",
        phenological_stage="early_bloom",
        hard_cap_horizon_h=240,
    )

    # Every returned nightly risk must only cover steps within the 240h horizon
    for nr in assessment_capped.nightly_risks:
        end_dt = datetime.fromisoformat(nr.end_time_utc)
        start_lead_h = (datetime.fromisoformat(nr.start_time_utc) - base_utc).total_seconds() / 3600.0
        assert start_lead_h <= 240.0, f"Night {nr.night_date} starts at lead_h={start_lead_h} > 240h"

    # Beyond 240h (hours 241 to 300) spans nights 10..12. They must NOT be in nightly_risks!
    night_dates = [nr.night_date for nr in assessment_capped.nightly_risks]
    # Day 0 is 2026-03-20. 240h is 10 days = 2026-03-30.
    # Night of 2026-03-31 (hour ~264) must NOT be present
    assert "2026-03-31" not in night_dates
    assert "2026-04-01" not in night_dates


def _make_synthetic_steps(
    temps: list[float],
    start_iso: str = "2026-03-20T18:00:00+00:00",
    step_hours: float = 1.0,
    uncertainty: float = 1.0,
) -> list[ForecastTimestep]:
    """Helper to build synthetic ForecastTimestep series."""
    from app.services.agriculture.forecast import ForecastTimestep
    base_dt = datetime.fromisoformat(start_iso)
    steps = []
    for i, t in enumerate(temps):
        dt = base_dt + timedelta(hours=i * step_hours)
        steps.append(
            ForecastTimestep(
                timestamp_utc=dt.isoformat(),
                lead_hours=float(i * step_hours),
                temperature_2m_c=t,
                temperature_2m_c_raw=t,
                elevation_delta_m=0.0,
                elevation_correction_c=0.0,
                elevation_uncertainty_c=0.0,
                lead_time_uncertainty_c=uncertainty,
                total_uncertainty_c=uncertainty,
                lower_bound_c=t - uncertainty,
                upper_bound_c=t + uncertainty,
                temperature_min_c=t - uncertainty,
                temperature_max_c=t + uncertainty,
                is_interpolated=False,
                wind_speed_10m_mps=1.0,
            )
        )
    return steps


def test_duration_rule_boundaries_and_escalation():
    """Verify exact duration boundaries at 0.9, 1.0, 1.9, 2.0, 2.1, 5.9, 6.0 hours (E8)."""
    from app.services.agriculture.frost_risk import (
        DurationRule,
        calculate_interval_duration_run,
        evaluate_duration_rule_category,
        RISK_LEVEL_WATCH,
        RISK_LEVEL_WARNING,
        RISK_LEVEL_CRITICAL,
    )

    rules = [
        DurationRule(
            reference_temperature_c=-4.0,
            min_hours=2.0,
            category="critical",
            source="Hokmabadi H. (2010), Options Méditerranéennes A94, p. 72 [S1]",
        ),
        DurationRule(
            reference_temperature_c=-4.0,
            min_hours=6.0,
            category="critical",
            source="Hokmabadi H. (2010), Options Méditerranéennes A94, p. 72 [S1]",
        ),
    ]

    # Boundary 0.9h: less than 1.0h -> short dip stays 'watch'
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.2,
        min_temp_pessimistic_c=-5.2,
        reference_temp_c=-4.0,
        continuous_hours_nominal=0.9,
        continuous_hours_pessimistic=0.9,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_WATCH
    assert short_dip is True
    assert escalated is False

    # Boundary 1.0h: 1 step at 1h -> 'warning' (not yet 2h critical)
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.2,
        min_temp_pessimistic_c=-5.2,
        reference_temp_c=-4.0,
        continuous_hours_nominal=1.0,
        continuous_hours_pessimistic=1.0,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_WARNING
    assert short_dip is False
    assert escalated is False

    # Boundary 1.9h: below 2.0h -> 'warning'
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.2,
        min_temp_pessimistic_c=-5.2,
        reference_temp_c=-4.0,
        continuous_hours_nominal=1.9,
        continuous_hours_pessimistic=1.9,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_WARNING
    assert escalated is False

    # Boundary 2.0h: exactly 2.0h -> escalates to 'critical' (S1 p. 72)
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.2,
        min_temp_pessimistic_c=-5.2,
        reference_temp_c=-4.0,
        continuous_hours_nominal=2.0,
        continuous_hours_pessimistic=2.0,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_CRITICAL
    assert escalated is True

    # Boundary 2.1h: above 2.0h -> 'critical'
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.2,
        min_temp_pessimistic_c=-5.2,
        reference_temp_c=-4.0,
        continuous_hours_nominal=2.1,
        continuous_hours_pessimistic=2.1,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_CRITICAL
    assert escalated is True

    # Boundary 5.9h: still in 2-6h critical tier
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.5,
        min_temp_pessimistic_c=-5.5,
        reference_temp_c=-4.0,
        continuous_hours_nominal=5.9,
        continuous_hours_pessimistic=5.9,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_CRITICAL
    assert escalated is True

    # Boundary 6.0h: severe necrosis tier (S1 p. 72)
    cat, _, short_dip, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-5.0,
        min_temp_pessimistic_c=-6.0,
        reference_temp_c=-4.0,
        continuous_hours_nominal=6.0,
        continuous_hours_pessimistic=6.0,
        duration_rules=rules,
    )
    assert cat == RISK_LEVEL_CRITICAL
    assert escalated is True


def test_discontinuous_runs_do_not_escalate_to_critical():
    """Verify that multiple separated dips below threshold sum in total but do not satisfy continuous duration."""
    from app.services.agriculture.frost_risk import (
        DurationRule,
        calculate_interval_duration_run,
        evaluate_duration_rule_category,
        RISK_LEVEL_WARNING,
        RISK_LEVEL_CRITICAL,
    )

    rules = [
        DurationRule(
            reference_temperature_c=-4.0,
            min_hours=2.0,
            category="critical",
            source="Hokmabadi H. (2010), Options Méditerranéennes A94, p. 72 [S1]",
        ),
    ]

    # Pattern: 1h below, 1h above, 1h below (total = 2h below, but longest continuous = 1.0h)
    temps = [0.0, -4.5, 0.0, -4.5, 0.0]
    steps = _make_synthetic_steps(temps, step_hours=1.0)

    total_h, longest_h, start_loc, end_loc, resolvable = calculate_interval_duration_run(
        steps=steps,
        reference_temp_c=-4.0,
        cooling_bump_c=0.0,
        use_pessimistic=False,
    )

    assert total_h == 2.0
    assert longest_h == 1.0
    assert resolvable is True

    cat, _, _, escalated, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.5,
        min_temp_pessimistic_c=-5.5,
        reference_temp_c=-4.0,
        continuous_hours_nominal=longest_h,
        continuous_hours_pessimistic=longest_h,
        duration_rules=rules,
    )
    # Longest continuous is only 1.0h (< 2.0h), so it remains WARNING, NOT CRITICAL!
    assert cat == RISK_LEVEL_WARNING
    assert escalated is False


def test_pessimistic_only_escalation_limited_to_watch():
    """Verify asymmetric rule: pessimistic run (T_eff - sigma) may ONLY raise risk to 'watch'."""
    from app.services.agriculture.frost_risk import (
        DurationRule,
        evaluate_duration_rule_category,
        RISK_LEVEL_WATCH,
        RISK_LEVEL_NONE,
    )

    rules = [
        DurationRule(
            reference_temperature_c=-4.0,
            min_hours=2.0,
            category="critical",
            source="Hokmabadi H. (2010), Options Méditerranéennes A94, p. 72 [S1]",
        ),
    ]

    # Nominal minimum is -3.5°C (ABOVE reference -4.0°C)
    # Pessimistic minimum is -4.5°C (BELOW reference -4.0°C) with 5.0h continuous pessimistic run
    cat, _, short_dip, escalated, expl = evaluate_duration_rule_category(
        min_temp_adjusted_c=-3.5,
        min_temp_pessimistic_c=-4.5,
        reference_temp_c=-4.0,
        continuous_hours_nominal=0.0,
        continuous_hours_pessimistic=5.0,
        duration_rules=rules,
    )
    # MUST be WATCH only, never escalated to WARNING or CRITICAL despite 5h pessimistic exposure
    assert cat == RISK_LEVEL_WATCH
    assert escalated is False
    assert "دیده‌بانی" in expl

    # If both nominal and pessimistic are above reference -> NONE
    cat_none, _, _, _, _ = evaluate_duration_rule_category(
        min_temp_adjusted_c=-2.0,
        min_temp_pessimistic_c=-3.0,
        reference_temp_c=-4.0,
        continuous_hours_nominal=0.0,
        continuous_hours_pessimistic=0.0,
        duration_rules=rules,
    )
    assert cat_none == RISK_LEVEL_NONE


def test_three_hourly_cadence_duration_not_resolvable():
    """Verify that beyond 120h (3-hourly data), duration is flagged not resolvable and category is from temp only."""
    from app.services.agriculture.frost_risk import (
        calculate_interval_duration_run,
        evaluate_duration_rule_category,
        RISK_LEVEL_WARNING,
        RISK_LEVEL_CRITICAL,
    )

    # 3-hourly steps (step_hours = 3.0 > 1.5)
    temps = [-4.5, -4.5, -4.5]
    steps_3h = _make_synthetic_steps(temps, step_hours=3.0)

    total_h, longest_h, _, _, resolvable = calculate_interval_duration_run(
        steps=steps_3h,
        reference_temp_c=-4.0,
        cooling_bump_c=0.0,
    )
    assert resolvable is False
    assert total_h == 0.0
    assert longest_h == 0.0

    # Decision table handling of unresolvable duration
    cat, _, _, _, expl = evaluate_duration_rule_category(
        min_temp_adjusted_c=-4.5,
        min_temp_pessimistic_c=-5.5,
        reference_temp_c=-4.0,
        continuous_hours_nominal=0.0,
        continuous_hours_pessimistic=0.0,
        duration_rules=[],
        duration_resolvable=False,
    )
    assert cat == RISK_LEVEL_WARNING
    assert "۱۲۰ ساعت" in expl
    assert "۳-ساعته" in expl


def test_partial_night_steps():
    """Verify partial night window with only 3 steps calculates interval duration correctly."""
    from app.services.agriculture.frost_risk import calculate_interval_duration_run

    # 3 steps: 2h below, 1h above
    temps = [-4.2, -4.5, -1.0]
    steps = _make_synthetic_steps(temps, step_hours=1.0)

    total_h, longest_h, start_loc, end_loc, resolvable = calculate_interval_duration_run(
        steps=steps,
        reference_temp_c=-4.0,
        cooling_bump_c=0.0,
    )
    assert resolvable is True
    assert total_h == 2.0
    assert longest_h == 2.0
    assert start_loc is not None
    assert end_loc is not None


@pytest.mark.asyncio
async def test_factor_register_asymmetric_conservatism():
    """Verify Factor Register v2 asymmetric conservatism (E9).

    - Protective factor ignored (applied=False, effect=0) when input is coarse_context.
    - Protective factor applied (applied=True, effect=1.0) when input is valid (user entered).
    - Aggravating factor applied even on coarse/proxy data.
    - Total protective credit is capped at 1.0°C.
    """
    provider = FakeForecastProvider(base_tmin_c=-3.0, base_tmax_c=10.0)
    forecast = await provider.get_hourly_forecast(None, horizon_h=48)

    # 1. Coarse context only (no user attributes): protective credit MUST be 0.0, tooltip present
    assessment_coarse = assess_frost_risk(
        forecast=forecast,
        crop="pistachio",
        phenological_stage="bloom",
        threshold_set="published_v1",
        pooling_risk_proxy=0.70,
        user_management_flags=None,
    )
    first_night_coarse = assessment_coarse.nightly_risks[0]
    assert first_night_coarse.applied_protective_credit_c == 0.0

    soil_factor_coarse = next(m for m in first_night_coarse.factor_modifiers if m.id == "soil_moisture_management")
    assert soil_factor_coarse.applied is False
    assert soil_factor_coarse.effect_c == 0.0
    assert soil_factor_coarse.quality_state == "coarse_context"
    assert "نیازمند تایید کاربر است" in (soil_factor_coarse.tooltip_fa or "")

    # Aggravating factor is applied regardless
    topo_factor = next(m for m in first_night_coarse.factor_modifiers if m.id == "topography_cold_air_pooling")
    assert topo_factor.applied is True
    assert topo_factor.effect_c < 0.0  # Cooling bump worsens temperature

    # 2. Valid user management attributes: protective credit applied and capped at 1.0°C
    assessment_valid = assess_frost_risk(
        forecast=forecast,
        crop="pistachio",
        phenological_stage="bloom",
        threshold_set="published_v1",
        pooling_risk_proxy=0.70,
        user_management_flags={"firm_moist_weed_free_soil": True, "irrigated_before_frost": True},
    )
    first_night_valid = assessment_valid.nightly_risks[0]
    assert first_night_valid.applied_protective_credit_c == 1.0

    soil_factor_valid = next(m for m in first_night_valid.factor_modifiers if m.id == "soil_moisture_management")
    assert soil_factor_valid.applied is True
    assert soil_factor_valid.effect_c == 1.0
    assert soil_factor_valid.quality_state == "valid"
    assert soil_factor_valid.tooltip_fa is None

    # Verify effective temperature difference matches exactly the 1.0°C protective credit
    # t_adjusted_min with valid soil is 1.0°C warmer than coarse
    diff = round(first_night_valid.tmin_adjusted_c - first_night_coarse.tmin_adjusted_c, 2)
    assert diff == 1.0


@pytest.mark.asyncio
async def test_regime_classification():
    """Verify frost regime classification per Hokmabadi (2011) [S2] (E9)."""
    provider = FakeForecastProvider(base_tmin_c=-2.0, base_tmax_c=10.0)
    forecast = await provider.get_hourly_forecast(None, horizon_h=48)

    # 1. Radiative regime: calm wind (<= 2 m/s) and clear sky (<= 25% cloud)
    for step in forecast.series:
        step.wind_speed_10m_mps = 1.0
        step.total_cloud_cover_percent = 10.0

    assessment_rad = assess_frost_risk(forecast=forecast, threshold_set="published_v1")
    regime_rad = assessment_rad.nightly_risks[0].regime
    assert regime_rad is not None
    assert regime_rad.regime == "radiative"
    assert "تشعشعی" in regime_rad.regime_fa
    assert "بخاری" in regime_rad.advice_fa

    # 2. Advective regime: strong cold wind (>= 3.5 m/s)
    for step in forecast.series:
        step.wind_speed_10m_mps = 5.0
        step.total_cloud_cover_percent = 70.0

    assessment_adv = assess_frost_risk(forecast=forecast, threshold_set="published_v1")
    regime_adv = assessment_adv.nightly_risks[0].regime
    assert regime_adv is not None
    assert regime_adv.regime == "advective"
    assert "انتقالی" in regime_adv.regime_fa
    # Must carry advective caveat warning against open heaters in strong wind
    all_recs = " ".join(assessment_adv.nightly_risks[0].recommendations_fa)
    assert "هشدار رژیم انتقالی" in all_recs


def test_published_v1_threshold_set_loading():
    """Verify published_v1 loads sourced thresholds with conflicting values and missing durations disclosed (E9)."""
    from app.services.agriculture.frost_risk import load_frost_threshold_set

    cfg = load_frost_threshold_set(set_name="published_v1", crop="pistachio")
    assert cfg.status == "published"
    assert cfg.verified is False  # Evidence level C pending microclimate network calibration

    stages = cfg.stages
    assert "unopened_bud" in stages
    assert stages["unopened_bud"].t_critical_c == -4.0
    assert stages["unopened_bud"].duration_rules is not None

    assert "opening_bud" in stages
    assert stages["opening_bud"].t_critical_c == -2.0

    assert "bloom" in stages
    assert stages["bloom"].t_critical_c == -1.7
    assert stages["bloom"].conflicting_published_value == 2.0
    assert stages["bloom"].duration_rules is None

    assert "fruit" in stages
    assert stages["fruit"].t_critical_c == -2.0

    assert "swelling_bud" in stages
    assert stages["swelling_bud"].t_critical_c is None  # S2 did not provide a number


@pytest.mark.asyncio
async def test_windbreak_drainage_caveat_advice():
    """Verify that when topography pooling proxy is elevated, windbreak drainage advice is added (E9)."""
    provider = FakeForecastProvider(base_tmin_c=-2.0, base_tmax_c=10.0)
    forecast = await provider.get_hourly_forecast(None, horizon_h=48)

    assessment = assess_frost_risk(
        forecast=forecast,
        crop="pistachio",
        phenological_stage="bloom",
        pooling_risk_proxy=0.85,
    )

    first_night = assessment.nightly_risks[0]
    all_recs = " ".join(first_night.recommendations_fa)
    assert "بادشکن‌ها نباید مسیر خروج و زه‌کشی هوای سرد شیب‌رو به پایین را مسدود کنند" in all_recs


