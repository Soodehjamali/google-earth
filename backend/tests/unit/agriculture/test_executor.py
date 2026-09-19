"""Tests for the executor and its per-metric error isolation.

The specification requires that one failing metric must not take down a
whole analysis. That guarantee is the primary subject here, along with
the requirement that error messages returned to clients are sanitised.

No network and no Earth Engine are required.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.services.agriculture import executor as executor_module
from app.services.agriculture.base import Metric, MetricContext, MetricDomain
from app.services.agriculture.catalog import (
    clear_registry,
    register_metric,
)
from app.services.agriculture.executor import (
    ExecutionOutcome,
    execute_metric,
    execute_metrics,
    sanitise_error_message,
)
from app.services.agriculture.types import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    MeasurementBasis,
    MetricResult,
    QualityLevel,
)


# --------------------------------------------------------------------------
# Test metrics
# --------------------------------------------------------------------------


def _make_context(**overrides) -> MetricContext:
    defaults = dict(
        geometry={"type": "Polygon", "coordinates": []},
        start_date="2026-05-01",
        end_date="2026-05-31",
        geometry_key="test-geometry",
    )
    defaults.update(overrides)
    return MetricContext(**defaults)


class _GoodMetric(Metric):
    key = "good"
    display_name = "Good"
    display_name_fa = "خوب"
    domain = MetricDomain.VEGETATION
    unit = "index"
    dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)
    measurement_basis = MeasurementBasis.DIRECT
    limitations = ()

    def compute(self, context: MetricContext) -> MetricResult:
        provenance = self.build_provenance(
            context=context,
            dataset=self.primary_dataset(),
            bands=["B8", "B4"],
            formula="(B8-B4)/(B8+B4)",
            quality=QualityLevel.GOOD,
            image_count=8,
        )
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=0.55,
            unit=self.unit,
            provenance=provenance,
        )


class _ExplodingMetric(Metric):
    key = "exploding"
    display_name = "Exploding"
    display_name_fa = "منفجر"
    domain = MetricDomain.SOIL
    unit = "index"
    dataset_ids = ("ISRIC/SOILGRIDS/V2",)
    measurement_basis = MeasurementBasis.MODELLED

    def compute(self, context: MetricContext) -> MetricResult:
        raise RuntimeError("upstream service returned 502 Bad Gateway")


class _ReturnsWrongTypeMetric(Metric):
    key = "wrongtype"
    display_name = "Wrong Type"
    display_name_fa = "نوع نادرست"
    domain = MetricDomain.CLIMATE
    unit = "mm"
    dataset_ids = ("ECMWF/ERA5_LAND/DAILY_AGGR",)

    def compute(self, context: MetricContext):
        return 42  # not a MetricResult


class _UnavailableMetric(Metric):
    key = "absent"
    display_name = "Absent"
    display_name_fa = "غایب"
    domain = MetricDomain.THERMAL
    unit = "K"
    dataset_ids = ("MODIS/061/MOD11A2",)

    def compute(self, context: MetricContext) -> MetricResult:
        return MetricResult.unavailable(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            message="No scenes in the requested period.",
            unit=self.unit,
        )


class _SlowMetric(Metric):
    key = "slow"
    display_name = "Slow"
    display_name_fa = "کند"
    domain = MetricDomain.WATER
    unit = "index"
    dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)

    def compute(self, context: MetricContext) -> MetricResult:
        time.sleep(0.05)
        provenance = self.build_provenance(
            context=context,
            dataset=self.primary_dataset(),
            bands=["B3"],
            formula="f",
            quality=QualityLevel.GOOD,
        )
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=0.1,
            unit=self.unit,
            provenance=provenance,
        )


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


# --------------------------------------------------------------------------
# Single metric execution
# --------------------------------------------------------------------------


def test_execute_good_metric():
    outcome = execute_metric(_GoodMetric(), _make_context())
    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.metric_key == "good"
    assert outcome.result.status == STATUS_OK
    assert outcome.result.value == pytest.approx(0.55)
    assert outcome.succeeded is True
    assert outcome.duration_ms >= 0


def test_execute_metric_never_raises_on_exception():
    """The core guarantee: a failing metric yields a result, not an error."""
    outcome = execute_metric(_ExplodingMetric(), _make_context())
    assert outcome.result.status == STATUS_ERROR
    assert outcome.result.value is None
    assert outcome.succeeded is False
    assert outcome.error_type == "RuntimeError"


def test_execute_metric_detects_wrong_return_type():
    """A metric returning a bare number is a bug, and must be surfaced."""
    outcome = execute_metric(_ReturnsWrongTypeMetric(), _make_context())
    assert outcome.result.status == STATUS_ERROR
    assert outcome.error_type == "TypeError"
    assert "MetricResult" in (outcome.result.message or "")


def test_execute_metric_passes_through_unavailable():
    outcome = execute_metric(_UnavailableMetric(), _make_context())
    assert outcome.result.status == STATUS_UNAVAILABLE
    assert outcome.succeeded is False


def test_execute_metric_reports_out_of_coverage_without_computing():
    """A pre-launch request must short-circuit to unavailable."""
    context = _make_context(start_date="2010-01-01", end_date="2010-12-31")
    outcome = execute_metric(_GoodMetric(), context)
    assert outcome.result.status == STATUS_UNAVAILABLE
    # It must not have been reported as an error.
    assert outcome.result.status != STATUS_ERROR


def test_execute_metric_can_skip_the_capability_check():
    context = _make_context(start_date="2010-01-01", end_date="2010-12-31")
    outcome = execute_metric(_GoodMetric(), context, check_capability=False)
    assert outcome.result.status == STATUS_OK


# --------------------------------------------------------------------------
# Error sanitisation
# --------------------------------------------------------------------------


def test_sanitise_error_redacts_windows_paths():
    exc = RuntimeError(r"failed to read C:\Users\Somebody\secret\gee-key.json")
    message = sanitise_error_message(exc)
    assert "gee-key.json" not in message
    assert "redacted" in message


def test_sanitise_error_redacts_posix_paths():
    exc = RuntimeError("cannot open /home/user/credentials/key.json")
    message = sanitise_error_message(exc)
    assert "key.json" not in message
    assert "redacted" in message


def test_sanitise_error_redacts_email_accounts():
    exc = RuntimeError(
        "permission denied for service account robot@my-project.iam.gserviceaccount.com"
    )
    message = sanitise_error_message(exc)
    assert "gserviceaccount.com" not in message
    assert "redacted" in message


def test_sanitise_error_redacts_pem_keys():
    exc = RuntimeError(
        "bad key -----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"
    )
    message = sanitise_error_message(exc)
    assert "MIIEvQIBADANBg" not in message
    assert "redacted" in message


def test_sanitise_error_truncates_long_messages():
    exc = RuntimeError("x" * 2000)
    message = sanitise_error_message(exc)
    assert len(message) <= 400
    assert message.endswith("...")


def test_sanitise_error_keeps_short_clean_messages():
    exc = RuntimeError("collection is empty for this period")
    message = sanitise_error_message(exc)
    assert "collection is empty" in message


def test_execute_metric_returns_sanitised_message():
    """The client-facing message must go through the same filter."""

    class _LeakyMetric(Metric):
        key = "leaky"
        display_name = "Leaky"
        display_name_fa = "نشت‌کننده"
        domain = MetricDomain.SOIL
        unit = "index"
        dataset_ids = ("ISRIC/SOILGRIDS/V2",)

        def compute(self, context: MetricContext) -> MetricResult:
            raise RuntimeError(
                r"auth failed for C:\Users\Jamali\credentials\gee-key.json"
            )

    outcome = execute_metric(_LeakyMetric(), _make_context())
    message = outcome.result.message or ""
    assert "gee-key.json" not in message
    assert "redacted" in message


# --------------------------------------------------------------------------
# Multi-metric execution and isolation
# --------------------------------------------------------------------------


def test_execute_metrics_isolates_failures():
    """One exploding metric must not prevent the others from returning."""
    for metric in (
        _GoodMetric(), _ExplodingMetric(), _UnavailableMetric(), _SlowMetric()
    ):
        register_metric(metric)

    outcomes, unknown = execute_metrics(
        ["good", "exploding", "absent", "slow"], _make_context()
    )

    assert unknown == []
    assert len(outcomes) == 4
    assert outcomes["good"].result.status == STATUS_OK
    assert outcomes["exploding"].result.status == STATUS_ERROR
    assert outcomes["absent"].result.status == STATUS_UNAVAILABLE
    assert outcomes["slow"].result.status == STATUS_OK


def test_execute_metrics_reports_unknown_keys_without_failing():
    register_metric(_GoodMetric())
    outcomes, unknown = execute_metrics(
        ["good", "does-not-exist"], _make_context()
    )
    assert outcomes["good"].result.status == STATUS_OK
    assert unknown == ["does-not-exist"]


def test_execute_metrics_all_unknown_returns_empty():
    outcomes, unknown = execute_metrics(["nope", "nada"], _make_context())
    assert outcomes == {}
    assert sorted(unknown) == ["nada", "nope"]


def test_execute_metrics_empty_request():
    outcomes, unknown = execute_metrics([], _make_context())
    assert outcomes == {}
    assert unknown == []


def test_execute_metrics_handles_duplicate_keys():
    register_metric(_GoodMetric())
    outcomes, unknown = execute_metrics(["good", "good"], _make_context())
    assert len(outcomes) == 1
    assert unknown == []


def test_execute_metrics_actually_runs_concurrently():
    """Several slow metrics should finish in about the time of one."""
    for key, delay in (("slow", 0.05),):
        pass

    class _Delayed(Metric):
        def __init__(self, key: str) -> None:
            self.key = key
            self.display_name = key
            self.display_name_fa = key
            self.domain = MetricDomain.WATER
            self.unit = "index"
            self.dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)
            super().__init__()

        def compute(self, context: MetricContext) -> MetricResult:
            time.sleep(0.15)
            provenance = self.build_provenance(
                context=context,
                dataset=self.primary_dataset(),
                bands=["B3"],
                formula="f",
                quality=QualityLevel.GOOD,
            )
            return MetricResult(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                value=0.1,
                unit=self.unit,
                provenance=provenance,
            )

    for key in ("d1", "d2", "d3", "d4"):
        register_metric(_Delayed(key))

    started = time.perf_counter()
    outcomes, _ = execute_metrics(
        ["d1", "d2", "d3", "d4"], _make_context(), max_workers=4
    )
    elapsed = time.perf_counter() - started

    assert len(outcomes) == 4
    # Serial execution would take about 0.6s. Concurrency should beat that
    # comfortably; allow generous headroom for slow CI machines.
    assert elapsed < 0.45, f"expected concurrency, took {elapsed:.3f}s"


def test_execute_metrics_respects_max_workers_of_one():
    register_metric(_SlowMetric())
    outcomes, _ = execute_metrics(["slow"], _make_context(), max_workers=1)
    assert outcomes["slow"].result.status == STATUS_OK


def test_execute_metrics_thread_safety_under_load():
    """Concurrent writes to the outcome dict must not lose entries."""

    class _Fast(Metric):
        def __init__(self, key: str) -> None:
            self.key = key
            self.display_name = key
            self.display_name_fa = key
            self.domain = MetricDomain.VEGETATION
            self.unit = "index"
            self.dataset_ids = ("COPERNICUS/S2_SR_HARMONIZED",)
            super().__init__()

        def compute(self, context: MetricContext) -> MetricResult:
            provenance = self.build_provenance(
                context=context,
                dataset=self.primary_dataset(),
                bands=["B8"],
                formula="f",
                quality=QualityLevel.GOOD,
            )
            return MetricResult(
                metric_key=self.key,
                display_name=self.display_name,
                display_name_fa=self.display_name_fa,
                value=0.5,
                unit=self.unit,
                provenance=provenance,
            )

    keys = [f"m{i}" for i in range(12)]
    for key in keys:
        register_metric(_Fast(key))

    outcomes, unknown = execute_metrics(keys, _make_context(), max_workers=6)
    assert len(outcomes) == 12
    assert unknown == []
    assert all(o.result.status == STATUS_OK for o in outcomes.values())


def test_executor_default_workers_is_conservative():
    """Earth Engine enforces quotas, so parallelism must be bounded."""
    assert 1 <= executor_module.DEFAULT_MAX_WORKERS <= 8


def test_get_logger_returns_a_stdlib_logger():
    """Regression guard for a real bug.

    The project's ``get_logger`` returns a standard library logger, not a
    structlog one. The stdlib ``Logger.info`` signature is positional, so
    ``logger.info("msg", key=value)`` only fails once a record is actually
    emitted, which made the mistake easy to miss in development (INFO is
    frequently below the effective level) and reliably fatal in production
    on error paths.

    Note: asserting that a keyword call raises is not reliable here,
    because stdlib logging short-circuits before validating arguments when
    nothing would be emitted. The contract is therefore pinned by checking
    the logger's type and by scanning call sites, which is what the
    companion test below does.
    """
    import logging

    from app.core.logging import get_logger

    logger = get_logger("test.logger")
    assert isinstance(logger, logging.Logger)
    # A structlog logger would be a structlog type and would accept kwargs.
    assert not type(logger).__module__.startswith("structlog")


def test_executor_module_logging_uses_positional_formatting():
    """No logger call in the executor may pass keyword arguments."""
    import re
    from pathlib import Path

    source = Path(executor_module.__file__).read_text(encoding="utf-8")
    # Find logger.<level>( ... ) calls and check for '=' style kwargs.
    calls = re.findall(
        r"logger\.(?:debug|info|warning|error|critical)\((.*?)\)\n",
        source,
        flags=re.DOTALL,
    )
    for call in calls:
        # A keyword argument looks like a bare identifier followed by '='.
        assert not re.search(r"\b[a-z_]+=", call), (
            f"logger call uses a keyword argument, which the stdlib logger "
            f"rejects: {call.strip()[:120]}"
        )


# --------------------------------------------------------------------------
# Catalog integration
# --------------------------------------------------------------------------


def test_catalog_lists_registered_metrics():
    from app.services.agriculture.catalog import catalog

    register_metric(_GoodMetric())
    payload = catalog()
    keys = [m["key"] for m in payload["metrics"]]
    assert "good" in keys
    assert "datasets" in payload
    assert "external_datasets" in payload
    assert "domains" in payload


def test_catalog_dataset_entries_carry_band_metadata():
    from app.services.agriculture.catalog import catalog

    payload = catalog()
    s2 = next(
        d for d in payload["datasets"]
        if d["id"] == "COPERNICUS/S2_SR_HARMONIZED"
    )
    assert s2["verified"] is True
    red = next(b for b in s2["bands"] if b["name"] == "B4")
    assert red["scale_factor"] == 0.0001
    assert red["unit"] == "reflectance"


def test_catalog_marks_soilgrids_as_unverified():
    from app.services.agriculture.catalog import catalog

    payload = catalog()
    soil = next(
        d for d in payload["external_datasets"]
        if d["id"] == "ISRIC/SOILGRIDS/V2"
    )
    assert soil["verified"] is False


def test_register_metric_rejects_duplicate_key_from_other_class():
    from app.services.agriculture.catalog import register_metric as reg

    class _Other(Metric):
        key = "good"
        display_name = "Other"
        display_name_fa = "دیگر"
        domain = MetricDomain.SOIL
        unit = "index"
        dataset_ids = ("ISRIC/SOILGRIDS/V2",)

        def compute(self, context):  # pragma: no cover
            raise NotImplementedError

    register_metric(_GoodMetric())
    with pytest.raises(ValueError, match="already registered"):
        reg(_Other())


def test_register_metric_rejects_non_metric():
    from app.services.agriculture.catalog import register_metric as reg

    with pytest.raises(TypeError, match="Metric instance"):
        reg("not a metric")  # type: ignore[arg-type]


def test_get_metric_unknown_raises_with_available_list():
    from app.services.agriculture.catalog import get_metric

    register_metric(_GoodMetric())
    with pytest.raises(KeyError) as exc:
        get_metric("nope")
    assert "good" in str(exc.value)


# --------------------------------------------------------------------------
# The executor must honour the temporal contract
# --------------------------------------------------------------------------
# A static dataset request that the shared gate now admits must reach
# compute, and an observation request outside coverage must still be
# short-circuited. If the executor re-implemented its own idea of
# coverage, the fix in can_attempt would be silently void.


class _StaticGoodMetric(Metric):
    """Computes over NASADEM regardless of the requested period."""

    key = "static_good"
    display_name = "Static Good"
    display_name_fa = "ایستا خوب"
    domain = MetricDomain.TERRAIN
    unit = "m"
    dataset_ids = ("NASA/NASADEM_HGT/001",)
    measurement_basis = MeasurementBasis.PRODUCT
    limitations = ()

    def compute(self, context: MetricContext) -> MetricResult:
        provenance = self.build_provenance(
            context=context,
            dataset=self.primary_dataset(),
            bands=["elevation"],
            formula="test",
            quality=QualityLevel.GOOD,
            image_count=1,
        )
        return MetricResult(
            metric_key=self.key,
            display_name=self.display_name,
            display_name_fa=self.display_name_fa,
            value=1200.0,
            unit=self.unit,
            provenance=provenance,
        )


def test_executor_computes_a_static_metric_for_a_2024_request():
    """The whole point of the temporal fix, exercised end to end."""
    metric = _StaticGoodMetric()
    context = _make_context(start_date="2024-04-01", end_date="2024-04-30")
    outcome = execute_metric(metric, context)
    assert outcome.result.status == STATUS_OK
    assert outcome.result.value == 1200.0


def test_executor_short_circuits_an_observation_metric_out_of_coverage():
    metric = _GoodMetric()
    context = _make_context(start_date="2010-01-01", end_date="2010-12-31")
    outcome = execute_metric(metric, context)
    assert outcome.result.status == STATUS_UNAVAILABLE


def test_executor_does_not_compute_for_a_short_circuited_metric():
    """The compute method must never run when the gate refuses."""
    calls = []

    class _CountingMetric(_GoodMetric):
        def compute(self, context: MetricContext) -> MetricResult:
            calls.append(context.start_date)
            return super().compute(context)

    metric = _CountingMetric()
    context = _make_context(start_date="2010-01-01", end_date="2010-12-31")
    execute_metric(metric, context)
    assert calls == []
