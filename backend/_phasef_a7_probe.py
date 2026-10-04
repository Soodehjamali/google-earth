"""Phase F-A7 minimal validation probe.

Runs the required checks and prints, for each: success/error,
usable/unavailable, exact first error, attempt count, dataset ID, metric
name. No fake data, no fallbacks.
"""

from __future__ import annotations

import json
import logging
import time

logging.basicConfig(level=logging.WARNING)

REPORT = []


def record(name, dataset, status, usable, first_error, attempts):
    REPORT.append(
        {
            "probe": name,
            "dataset": dataset,
            "status": status,
            "usable": usable,
            "first_error": first_error,
            "attempts": attempts,
        }
    )
    print(
        f"[{name}] dataset={dataset} status={status} usable={usable} "
        f"attempts={attempts} first_error={first_error}"
    )


def attempt_count_for(metric_key):
    """Read the attempt count the executor logged for this metric."""
    import re

    from app.core import logging as core_logging

    # Simplest reliable channel: re-parse nothing; the executor logs
    # attempts. We instead count by wrapping compute below.
    return None


class AttemptCounter:
    """Wrap metric.compute to count real attempts made by the executor."""

    def __init__(self, metric):
        self.metric = metric
        self.count = 0
        self.compute_calls = 0

    def compute(self, context):
        self.compute_calls += 1
        return self.metric.compute(context)

    def __getattr__(self, name):
        return getattr(self.metric, name)


def main():
    # ------------------------------------------------------------------
    # A. EE connectivity
    # ------------------------------------------------------------------
    from app.services.earth_engine.authentication import (
        initialize_earth_engine,
    )

    init_attempts = 0
    init_error = None
    t0 = time.perf_counter()
    try:
        initialize_earth_engine()
        init_ok = True
    except Exception as exc:  # noqa: BLE001
        init_ok = False
        init_error = f"{type(exc).__name__}: {str(exc)[:220]}"
    init_elapsed = time.perf_counter() - t0

    record(
        "A. EE init/connectivity",
        "earthengine.googleapis.com",
        "ok" if init_ok else "error",
        init_ok,
        init_error or "(connected)",
        "init retry only on transport-class; not counted here",
    )
    print(f"    init elapsed: {init_elapsed:.2f}s")

    if not init_ok:
        print(
            "\nENVIRONMENT BLOCKER: Earth Engine unreachable "
            "(transport blocked). Metrics B-E cannot compute real values; "
            "reporting their executor-level outcome honestly.\n"
        )

    # Register all metrics regardless, so FCOVER's unavailable path works.
    from app.services.agriculture import ensure_registered
    from app.services.agriculture.base import MetricContext
    from app.services.agriculture.catalog import get_metric, has_metric
    from app.services.agriculture.executor import execute_metric
    from app.services.agriculture.types import STATUS_OK, STATUS_PARTIAL
    from app.utils.geometry import create_ee_geometry

    ensure_registered()

    with open("_acc_req1.json", "r", encoding="utf-8") as fh:
        req = json.load(fh)

    ee_geometry = create_ee_geometry(req["geometry"]) if init_ok else None

    def run_metric(metric_key, label):
        metric = get_metric(metric_key)
        counter = AttemptCounter(metric)
        dataset_id = (
            metric.dataset_ids[0] if metric.dataset_ids else "(none declared)"
        )
        if not init_ok:
            record(
                label,
                dataset_id,
                "error",
                False,
                "EE not initialized (network blocker): compute not attempted",
                0,
            )
            return None
        context = MetricContext(
            geometry=ee_geometry,
            start_date=req["start_date"],
            end_date=req["end_date"],
            geometry_key=json.dumps(req["geometry"], sort_keys=True)[:64],
            cloud_max_percent=20.0,
        )
        counter.compute_calls = 0
        outcome = execute_metric(metric, context)
        result = outcome.result
        usable = result.status in (STATUS_OK, STATUS_PARTIAL) and getattr(
            result, "is_usable", False
        )
        first_error = None
        if outcome.error_type:
            first_error = result.message
        record(
            label,
            dataset_id,
            result.status,
            usable,
            first_error or "(none)",
            counter.compute_calls,
        )
        return result

    # B-E. Metric probes. FCOVER is fully offline by design, so it runs
    # regardless of EE state; the EE-dependent metrics are attempted only
    # when EE initialized, and are honestly reported as blocked otherwise.
    fcover = get_metric("fcover")
    fcover_ctx = MetricContext(
        geometry=None,
        start_date=req.get("start_date", "2024-07-01"),
        end_date=req.get("end_date", "2024-07-31"),
        geometry_key="fcover-probe",
    )
    _fc_outcome = execute_metric(fcover, fcover_ctx)
    _fc = _fc_outcome.result
    # The executor's capability gate uses its generic refusal message; the
    # metric's own compute() carries the full structural reason. Show both.
    _fc_direct = fcover.compute(fcover_ctx)
    record(
        "E. FCOVER",
        "(none declared — no EE-hosted source)",
        _fc.status,
        bool(getattr(_fc, "is_usable", False)),
        (
            "unavailable by design (see message)"
            if _fc.status == "unavailable"
            else _fc.message
        ),
        1,
    )
    print("    fcover executor-path message:", (_fc.message or "")[:120])
    print("    fcover full reason:", (_fc_direct.message or "")[:220])

    if init_ok:
        for key, label in (
            ("ndvi", "B. S2 NDVI"),
            ("vv", "C. S1 VV"),
            ("evapotranspiration", "D. MOD16 ET"),
        ):
            run_metric(key, label)
    else:
        for key, label in (
            ("ndvi", "B. S2 NDVI"),
            ("vv", "C. S1 VV"),
            ("evapotranspiration", "D. MOD16 ET"),
        ):
            metric = get_metric(key)
            dataset_id = (
                metric.dataset_ids[0]
                if metric.dataset_ids
                else "(none declared)"
            )
            record(
                label,
                dataset_id,
                "error",
                False,
                "EE not initialized (network blocker): compute not attempted",
                0,
            )

    # ------------------------------------------------------------------
    # F. One real analysis through the existing backend service
    # ------------------------------------------------------------------
    if init_ok:
        import asyncio

        from app.services.analysis_service import analysis_service

        class _FakeDB:
            pass

        envelope = asyncio.run(
            analysis_service.create_analysis(
                db=None,
                geometry=req["geometry"],
                start_date=req["start_date"],
                end_date=req["end_date"],
                analysis_type="vegetation",
            )
        )
        status = envelope.get("status")
        record(
            "F. Real analysis (vegetation)",
            "analysis_service",
            status,
            status == "completed",
            envelope.get("error_message") or "(none)",
            1,
        )
    else:
        record(
            "F. Real analysis (vegetation)",
            "analysis_service",
            "not_attempted",
            False,
            "EE not initialized (network blocker)",
            0,
        )

    print("\n--- JSON REPORT ---")
    print(json.dumps(REPORT, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
