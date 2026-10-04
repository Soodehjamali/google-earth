"""Metric catalog and registry.

Holds the collection of every available :class:`~app.services.agriculture.base.Metric`,
provides lookup by key and by domain, and exposes the metadata that the
public catalog endpoint serves.

Importing a metric module is what registers its metrics. That import is
done explicitly here rather than by magic discovery, so the set of
available metrics is readable in one place.
"""

from __future__ import annotations

import threading
from typing import Dict, Iterable, List, Optional, Sequence, Type

from app.services.agriculture.base import Metric, MetricDomain

__all__ = [
    "register_metric",
    "register_metrics",
    "get_metric",
    "has_metric",
    "all_metrics",
    "metric_keys",
    "metrics_in_domain",
    "catalog",
    "registered_domains",
    "clear_registry",
]

_METRICS: Dict[str, Metric] = {}
_LOCK = threading.Lock()


def register_metric(metric: Metric) -> Metric:
    """Register a metric instance.

    Raises on a duplicate key, because a silent collision would mean one
    metric quietly shadowing another with identical API paths.
    """
    if not isinstance(metric, Metric):
        raise TypeError(
            f"Expected a Metric instance, got {type(metric).__name__}"
        )
    with _LOCK:
        existing = _METRICS.get(metric.key)
        if existing is not None and type(existing) is not type(metric):
            raise ValueError(
                f"Metric key {metric.key!r} is already registered by "
                f"{type(existing).__name__}; refusing to shadow it with "
                f"{type(metric).__name__}."
            )
        _METRICS[metric.key] = metric
    return metric


def register_metrics(metrics: Iterable[Metric]) -> List[str]:
    """Register a batch of metrics and return the keys now registered.

    Returning the keys (rather than ``None``) lets callers log what was
    registered and lets the domain-level idempotency tests compare two
    consecutive registrations of the same batch. The set of keys is
    unchanged by re-registering the same metrics, so the return value is
    stable across repeated calls.
    """
    for metric in metrics:
        register_metric(metric)
    return sorted(_METRICS)


def get_metric(key: str) -> Metric:
    """Look up a registered metric, with an actionable error if absent."""
    try:
        return _METRICS[key]
    except KeyError:
        available = ", ".join(sorted(_METRICS)) or "(none registered)"
        raise KeyError(
            f"Metric {key!r} is not registered. Available metrics: {available}"
        ) from None


def has_metric(key: str) -> bool:
    return key in _METRICS


def all_metrics() -> List[Metric]:
    """Every registered metric, ordered by domain then key for stable output."""
    return sorted(_METRICS.values(), key=lambda m: (m.domain, m.key))


def metric_keys() -> List[str]:
    return sorted(_METRICS)


def metrics_in_domain(domain: str) -> List[Metric]:
    if domain not in MetricDomain.ALL:
        raise ValueError(
            f"Unknown domain {domain!r}. Expected one of {MetricDomain.ALL}"
        )
    return sorted(
        (m for m in _METRICS.values() if m.domain == domain),
        key=lambda m: m.key,
    )


def registered_domains() -> List[str]:
    """Domains that currently have at least one metric."""
    present = {m.domain for m in _METRICS.values()}
    return [d for d in MetricDomain.ALL if d in present]


def catalog() -> Dict[str, object]:
    """Full catalog payload for the public datasets and metrics endpoint.

    Includes the dataset registry so a client can show where every number
    came from, and the metric list so it can drive a metric selector
    without hardcoding keys.
    """
    from app.services.agriculture.registry import (
        get_datasets,
        get_external_datasets,
    )

    def dataset_entry(spec) -> Dict[str, object]:
        return {
            "id": spec.id,
            "name": spec.name,
            "name_fa": spec.name_fa,
            "provider": spec.provider,
            "description": spec.description,
            "spatial_resolution": spec.spatial_resolution,
            "temporal_resolution": spec.temporal_resolution,
            "temporal_kind": spec.temporal_kind.value,
            "available_from": spec.available_from,
            "available_to": spec.available_to,
            "measurement_basis": spec.measurement_basis.value,
            "roles": list(spec.roles),
            "bands": [
                {
                    "name": b.name,
                    "description": b.description,
                    "unit": b.unit,
                    "scale_factor": b.scale_factor,
                    "offset": b.offset,
                }
                for b in spec.bands.values()
            ],
            "caveats": list(spec.caveats),
            "citation": spec.citation,
            "docs_url": spec.docs_url,
            "verified": spec.is_verified,
        }

    return {
        "domains": registered_domains(),
        "datasets": [dataset_entry(d) for d in get_datasets()],
        "external_datasets": [dataset_entry(d) for d in get_external_datasets()],
        "metrics": [m.metadata() for m in all_metrics()],
    }


def clear_registry() -> None:
    """Empty the registry. Intended for tests only."""
    with _LOCK:
        _METRICS.clear()
