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
    "TRANSPORT_MAX_ATTEMPTS",
]

#: Conservative default. Earth Engine applies per-user request quotas, so
#: unbounded parallelism produces rate limit errors rather than speed.
DEFAULT_MAX_WORKERS = 4

#: Total attempts allowed for a transport-class failure: the initial try
#: plus one retry. Deliberately small — a dead endpoint does not get
#: healthier by being asked twice in quick succession, and the retry
#: exists only to ride out a single dropped connection.
TRANSPORT_MAX_ATTEMPTS = 2

#: Base delay before the single retry, in seconds. Short, deterministic
#: bounds: attempt N waits ``base * 2**(N-1)`` seconds plus jitter.
TRANSPORT_BACKOFF_BASE_S = 0.5
TRANSPORT_BACKOFF_CAP_S = 2.0
TRANSPORT_JITTER_FRACTION = 0.25


def _is_transport_error(exc: BaseException) -> bool:
    """True only for network-transport failure classes.

    Retry is restricted to failures where the request never completed as a
    server-side computation: TLS/SSL breakage, DNS, connection refusal or
    reset, and request timeouts. Everything else — including an EE
    computation error, a bad dataset ID, an empty collection, or an HTTP
    response the server did send — is a definitive answer and must NOT be
    retried, because the same request would fail identically.

    Note on HTTP errors: an ``HttpError`` carries the server's answer
    (including Google's IP-block 403 HTML), so it is transport-adjacent
    but NOT retryable here — the block will not lift between two attempts
    0.5 s apart, and treating a refusal as transient would only add
    latency. Authentication and EarthEngineAuthError are likewise
    definitive.
    """
    # Authentication errors are definitional failures, never transport.
    from app.core.exceptions import EarthEngineAuthError

    if isinstance(exc, EarthEngineAuthError):
        return False

    # Module-level import of the transport exception classes.
    import requests.exceptions as _requests_exc

    # SSL errors subclass both SSLError and RequestException; listing the
    # specific classes first keeps intent explicit.
    if isinstance(
        exc,
        (
            _requests_exc.SSLError,
            _requests_exc.ConnectionError,
            _requests_exc.Timeout,
            _requests_exc.ChunkedEncodingError,
            ConnectionError,
            TimeoutError,
        ),
    ):
        return True

    # ``requests.exceptions.RequestException`` catches remaining requests
    # failures (e.g. ``ConnectionResetError`` wrapped by urllib3 as
    # ProtocolError). Explicitly NOT retryable subclasses — HTTPError —
    # were already matched above by exclusion order, so reaching here with
    # a RequestException means the request never completed.
    if isinstance(exc, _requests_exc.HTTPError):
        return False
    if isinstance(exc, _requests_exc.RequestException):
        return True

    # googleapiclient surfaces transport problems as socket-level errors.
    # NOTE: googleapiclient HttpError is deliberately absent: it means the
    # server answered (403 block page, quota, IAM), which is definitive.
    import socket

    if isinstance(exc, (socket.timeout, OSError)):
        return True

    return False


def _transport_backoff_seconds(attempt: int) -> float:
    """Short exponential backoff with bounded deterministic jitter.

    Attempt 1 waits ~0.5 s, attempt 2 ~1 s, capped at 2 s. Jitter is a
    deterministic fraction of the base so two workers never retry in
    lockstep while the delay stays reproducible in tests.
    """
    import random

    base = min(
        TRANSPORT_BACKOFF_CAP_S,
        TRANSPORT_BACKOFF_BASE_S * (2 ** (max(0, attempt - 1))),
    )
    return base * (1.0 + random.uniform(0.0, TRANSPORT_JITTER_FRACTION))


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

    attempts = 0
    first_error: Optional[BaseException] = None
    while attempts < TRANSPORT_MAX_ATTEMPTS:
        attempts += 1
        try:
            result = metric.compute(context)
            elapsed = (time.perf_counter() - started) * 1000.0

            if not isinstance(result, MetricResult):
                raise TypeError(
                    f"Metric {metric.key!r} returned {type(result).__name__}, "
                    "expected MetricResult"
                )

            logger.info(
                "Metric %s computed with status %s in %.1f ms (attempt %d)",
                metric.key,
                result.status,
                elapsed,
                attempts,
            )
            return ExecutionOutcome(
                metric_key=metric.key,
                result=result,
                duration_ms=elapsed,
                succeeded=result.status not in (STATUS_ERROR, STATUS_UNAVAILABLE),
            )

        except Exception as exc:  # noqa: BLE001 - isolation is the whole point
            if first_error is None:
                first_error = exc
            if attempts < TRANSPORT_MAX_ATTEMPTS and _is_transport_error(exc):
                delay = _transport_backoff_seconds(attempts)
                logger.warning(
                    "Metric %s transport failure (%s) on attempt %d/%d, "
                    "retrying in %.2fs",
                    metric.key,
                    type(exc).__name__,
                    attempts,
                    TRANSPORT_MAX_ATTEMPTS,
                    delay,
                )
                time.sleep(delay)
                continue
            break

    # Both attempts failed (or the failure was non-transport): the FIRST
    # error is reported — the retry exists to succeed, not to rewrite the
    # failure mode. No fallback value is produced and no unavailable result
    # is converted into a usable one.
    elapsed = (time.perf_counter() - started) * 1000.0
    first_error = (
        first_error
        if first_error is not None
        else RuntimeError("metric produced no result")
    )
    safe_message = sanitise_error_message(first_error)
    logger.error(
        "Metric %s failed with %s after %d attempt(s) in %.1f ms: %s",
        metric.key,
        type(first_error).__name__,
        attempts,
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
        error_type=type(first_error).__name__,
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
