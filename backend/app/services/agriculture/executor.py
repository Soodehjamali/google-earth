"""Metric executor: runs metrics with per-metric error isolation.

The specification requires that one failing metric must not take down an
entire analysis. If soil moisture cannot be computed because the SMAP
collection is empty for the requested month, the vegetation indices for
that same field and period must still be returned.

This module implements that guarantee. Errors are caught per metric,
converted into an explicit ``error`` result with a sanitised message, and
the remaining metrics proceed unaffected.

Execution is concurrent, using a thread pool, because the work is
dominated by network round trips to Earth Engine rather than CPU. A
thread pool rather than asyncio is the right fit here: the Earth Engine
Python client is synchronous, so wrapping it in asyncio would only add
overhead without adding concurrency.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.logging import get_logger
from app.services.agriculture.base import Metric, MetricContext
from app.services.agriculture.catalog import get_metric, has_metric
from app.services.agriculture.types import (
    NOT_AVAILABLE_REASON_ERROR,
    NOT_AVAILABLE_REASON_UNSUPPORTED,
    STATUS_ERROR,
    STATUS_UNAVAILABLE,
    MetricResult,
)

logger = get_logger(__name__)

__all__ = [
    "ExecutionOutcome",
    "execute_metric",
    "execute_metrics",
    "sanitise_error_message",
    "DEFAULT_MAX_WORKERS",
]

#: Conservative default. Earth Engine applies per-user request quotas, so
#: unbounded parallelism produces rate limit errors rather than speed.
DEFAULT_MAX_WORKERS = 4


def sanitise_error_message(exc: BaseException) -> str:
    """Produce a client-safe description of a failure.

    Error strings from the Earth Engine client can embed credential paths,
    service account addresses and request internals. Anything matching a
    known sensitive pattern is replaced rather than forwarded.
    """
    text = f"{type(exc).__name__}: {exc}"

    # Redact anything that looks like a path, an email, or a key blob.
    import re

    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<path redacted>", text)
    text = re.sub(r"/[^\s\"']*/[^\s\"']*", "<path redacted>", text)
    text = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "<account redacted>",
        text,
    )
    text = re.sub(r"-----BEGIN[^-]+-----[\s\S]*?-----END[^-]+-----",
                  "<key redacted>", text)

    # Keep it short; the detail belongs in the server log, not the payload.
    if len(text) > 400:
        text = text[:397] + "..."
    return text


@dataclass
class ExecutionOutcome:
    """The result of running one metric, plus bookkeeping.

    The timing and error detail here are for observability and are not
    returned to clients; the :class:`MetricResult` is.
    """

    metric_key: str
    result: MetricResult
    duration_ms: float = 0.0
    succeeded: bool = False
    error_type: Optional[str] = None

    @property
    def status(self) -> str:
        return self.result.status


def execute_metric(
    metric: Metric,
    context: MetricContext,
    check_capability: bool = True,
) -> ExecutionOutcome:
    """Run a single metric, never raising.

    Args:
        metric: The metric to run.
        context: The execution context.
        check_capability: When True, ask the metric whether it can attempt
            the requested range before computing, so an out-of-coverage
            request is reported as unavailable rather than producing an
            expensive empty query.

    Returns:
        An :class:`ExecutionOutcome` whose ``result`` is always a valid
        :class:`MetricResult`, whatever went wrong.
    """
    started = time.perf_counter()

    if check_capability:
        try:
            can_attempt, reason = metric.can_attempt(context)
            if not can_attempt:
                return ExecutionOutcome(
                    metric_key=metric.key,
                    result=MetricResult.unavailable(
                        metric_key=metric.key,
                        display_name=metric.display_name,
                        display_name_fa=metric.display_name_fa,
                        reason=reason or NOT_AVAILABLE_REASON_UNSUPPORTED,
                        message=(
                            "The requested period is outside this metric's "
                            "data coverage."
                        ),
                        unit=metric.unit,
                    ),
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )
        except Exception as exc:  # noqa: BLE001 - capability probe must not fail hard
            logger.warning(
                "Capability check failed for metric %s: %s",
                metric.key,
                exc,
            )

    try:
        result = metric.compute(context)
        elapsed = (time.perf_counter() - started) * 1000.0

        if not isinstance(result, MetricResult):
            raise TypeError(
                f"Metric {metric.key!r} returned {type(result).__name__}, "
                "expected MetricResult"
            )

        logger.info(
            "Metric %s computed with status %s in %.1f ms",
            metric.key,
            result.status,
            elapsed,
        )
        return ExecutionOutcome(
            metric_key=metric.key,
            result=result,
            duration_ms=elapsed,
            succeeded=result.status not in (STATUS_ERROR, STATUS_UNAVAILABLE),
        )

    except Exception as exc:  # noqa: BLE001 - isolation is the whole point
        elapsed = (time.perf_counter() - started) * 1000.0
        safe_message = sanitise_error_message(exc)
        logger.error(
            "Metric %s failed with %s in %.1f ms: %s",
            metric.key,
            type(exc).__name__,
            elapsed,
            safe_message,
        )
        return ExecutionOutcome(
            metric_key=metric.key,
            result=MetricResult.error(
                metric_key=metric.key,
                display_name=metric.display_name,
                display_name_fa=metric.display_name_fa,
                message=safe_message,
                unit=metric.unit,
            ),
            duration_ms=elapsed,
            error_type=type(exc).__name__,
        )


def execute_metrics(
    metric_keys: Sequence[str],
    context: MetricContext,
    max_workers: int = DEFAULT_MAX_WORKERS,
    check_capability: bool = True,
) -> Tuple[Dict[str, ExecutionOutcome], List[str]]:
    """Run several metrics concurrently, isolating failures.

    Args:
        metric_keys: Metrics to run, by key.
        context: Shared execution context.
        max_workers: Thread pool size. Kept modest because Earth Engine
            enforces per-user quotas.
        check_capability: Passed through to :func:`execute_metric`.

    Returns:
        A pair of ``(outcomes_by_key, unknown_keys)``. Unknown keys are
        returned rather than raised so a client requesting a
        partly-invalid metric list receives everything that could be
        computed, plus a clear statement of what could not.
    """
    outcomes: Dict[str, ExecutionOutcome] = {}
    unknown: List[str] = []
    resolved: List[Metric] = []

    for key in metric_keys:
        if has_metric(key):
            resolved.append(get_metric(key))
        else:
            unknown.append(key)

    if unknown:
        logger.warning("Unknown metrics requested: %s", ", ".join(unknown))

    if not resolved:
        return outcomes, unknown

    # A single metric does not justify a thread pool.
    if len(resolved) == 1:
        metric = resolved[0]
        outcomes[metric.key] = execute_metric(
            metric, context, check_capability=check_capability
        )
        return outcomes, unknown

    workers = max(1, min(max_workers, len(resolved)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(execute_metric, metric, context, check_capability): metric
            for metric in resolved
        }
        for future in as_completed(futures):
            metric = futures[future]
            try:
                outcomes[metric.key] = future.result()
            except Exception as exc:  # noqa: BLE001 - a pool failure must not escape
                # execute_metric already absorbs exceptions, so reaching
                # here means something failed outside it.
                logger.error(
                    "Executor-level failure for metric %s: %s",
                    metric.key,
                    type(exc).__name__,
                )
                outcomes[metric.key] = ExecutionOutcome(
                    metric_key=metric.key,
                    result=MetricResult.error(
                        metric_key=metric.key,
                        display_name=metric.display_name,
                        display_name_fa=metric.display_name_fa,
                        message=sanitise_error_message(exc),
                        unit=metric.unit,
                    ),
                    error_type=type(exc).__name__,
                )

    return outcomes, unknown
