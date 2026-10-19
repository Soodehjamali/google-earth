"""Unit tests for local night partitioning and temperature minimum grouping (X1 regression test)."""

from datetime import datetime, timedelta, timezone
import pytest

from app.services.agriculture.frost_risk import (
    aggregate_forecast_by_local_night,
    ForecastTimestep,
)


def _make_step(timestamp_utc: str, temp_c: float, lead_hours: float = 0.0) -> ForecastTimestep:
    return ForecastTimestep(
        timestamp_utc=timestamp_utc,
        lead_hours=lead_hours,
        temperature_2m_c=temp_c,
        temperature_2m_c_raw=temp_c,
        elevation_delta_m=0.0,
        elevation_correction_c=0.0,
        elevation_uncertainty_c=0.1,
        lead_time_uncertainty_c=0.2,
        total_uncertainty_c=0.3,
        lower_bound_c=temp_c - 0.5,
        upper_bound_c=temp_c + 0.5,
        is_interpolated=False,
        relative_humidity_percent=30.0,
        wind_speed_10m_mps=2.5,
        wind_direction_10m_deg=180.0,
        total_cloud_cover_percent=10.0,
        dewpoint_2m_c=5.0,
    )


def test_aggregate_forecast_by_local_night_24h_separation():
    """Verify that hourly forecast steps spanning 72 hours across midnight

    are partitioned into distinct 24-hour night cycles (18:00 to 09:00 local IRST UTC+3.5),
    and that consecutive morning minima (e.g., 06:30 on 21 Oct vs 06:30 on 22 Oct)
    belong strictly to consecutive nights (Night of 20 Oct vs Night of 21 Oct).
    """
    tz_local = timezone(timedelta(hours=3.5))
    series = []

    # Generate 72 hours of timesteps starting 2026-10-19 12:00 UTC (15:30 IRST)
    base_utc = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    for hour_offset in range(72):
        step_dt_utc = base_utc + timedelta(hours=hour_offset)
        step_dt_local = step_dt_utc.astimezone(tz_local)

        # Synthetic diurnal temperature cycle:
        # minimum at 06:30 local time each morning, max at 15:30
        hour_local = step_dt_local.hour + step_dt_local.minute / 60.0
        t_air = 20.0 - 5.0 * ((hour_local - 6.5) % 24 < 12) + (hour_offset * 0.1)

        series.append(
            _make_step(
                timestamp_utc=step_dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                temp_c=round(t_air, 2),
                lead_hours=float(hour_offset),
            )
        )

    nights = aggregate_forecast_by_local_night(series, local_utc_offset_hours=3.5)

    # 72 hours covers 3 nights: 2026-10-19, 2026-10-20, 2026-10-21
    assert "2026-10-19" in nights
    assert "2026-10-20" in nights
    assert "2026-10-21" in nights

    # Verify that steps in 2026-10-20 night are exclusively between
    # 2026-10-20 18:00 local and 2026-10-21 09:00 local
    night_20_steps = nights["2026-10-20"]
    for step in night_20_steps:
        dt_local = datetime.fromisoformat(step.timestamp_utc.replace("Z", "+00:00")).astimezone(tz_local)
        assert (
            (dt_local.date() == datetime(2026, 10, 20).date() and dt_local.hour >= 18)
            or (dt_local.date() == datetime(2026, 10, 21).date() and dt_local.hour < 9)
        ), f"Step {dt_local} incorrectly grouped into night of 2026-10-20"

    # Verify that 06:30 on 2026-10-21 is in night of 2026-10-20 (شب ۲۸ مهر)
    # and 06:30 on 2026-10-22 is in night of 2026-10-21 (شب ۲۹ مهر)
    step_oct21_0630 = [
        s for s in night_20_steps
        if datetime.fromisoformat(s.timestamp_utc.replace("Z", "+00:00")).astimezone(tz_local).strftime("%Y-%m-%d %H:%M") == "2026-10-21 06:30"
    ]
    assert len(step_oct21_0630) == 1, "Expected 06:30 on Oct 21 in night of 2026-10-20"

    night_21_steps = nights["2026-10-21"]
    step_oct22_0630 = [
        s for s in night_21_steps
        if datetime.fromisoformat(s.timestamp_utc.replace("Z", "+00:00")).astimezone(tz_local).strftime("%Y-%m-%d %H:%M") == "2026-10-22 06:30"
    ]
    assert len(step_oct22_0630) == 1, "Expected 06:30 on Oct 22 in night of 2026-10-21"

    # Confirm the two minima are exactly 24 hours apart, NOT on the same night
    dt_min1 = datetime.fromisoformat(step_oct21_0630[0].timestamp_utc.replace("Z", "+00:00"))
    dt_min2 = datetime.fromisoformat(step_oct22_0630[0].timestamp_utc.replace("Z", "+00:00"))
    assert (dt_min2 - dt_min1).total_seconds() == 24 * 3600


def test_daytime_hours_excluded_from_nights():
    """Verify that midday hours (e.g., 12:00, 14:00 local) are omitted from night buckets."""
    tz_local = timezone(timedelta(hours=3.5))
    noon_local = datetime(2026, 10, 20, 12, 0, tzinfo=tz_local)
    noon_utc = noon_local.astimezone(timezone.utc)

    step = _make_step(
        timestamp_utc=noon_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        temp_c=25.0,
    )

    nights = aggregate_forecast_by_local_night([step], local_utc_offset_hours=3.5)
    assert len(nights) == 0, "Daytime hour 12:00 should not be assigned to any night bucket"
