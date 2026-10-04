"""Tests for the engine's registration bootstrap.

Registration is explicit rather than an import side effect, so there has
to be one place that ties the domain modules together. These tests
verify that place actually registers every domain, that it is safe to
call more than once, and that the resulting catalog is complete enough
for the API to expose.
"""

from __future__ import annotations

import pytest

from app.services.agriculture import register_all_metrics
from app.services.agriculture.catalog import (
    catalog,
    clear_registry,
    get_metric,
    metric_keys,
    metrics_in_domain,
)
from app.services.agriculture.climate import CLIMATE_METRICS
from app.services.agriculture.thermal import THERMAL_METRICS
from app.services.agriculture.types import MeasurementBasis
from app.services.agriculture.vegetation import VEGETATION_METRICS

#: Metric keys allowed to contain "canopy" despite the engine-wide
#: canopy-temperature prohibition below: the CD-4 middle-canopy
#: dryness proxy, whose mandated name carries "canopy" but which is a
#: PROXY-basis state code in the vegetation domain — not a
#: temperature quantity of any kind.
CANOPY_KEY_ALLOWLIST = frozenset({"middle_canopy_dryness_proxy"})

#: Domains that must be represented once every phase is complete. Phases
#: C, D and E are done; later phases add to this set.
REGISTERED_DOMAINS = {"vegetation", "climate", "thermal"}


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_register_all_populates_the_registry():
    keys = register_all_metrics()
    assert keys, "registration produced no metrics"


def test_every_vegetation_metric_is_registered():
    register_all_metrics()
    for metric in VEGETATION_METRICS:
        assert metric.key in metric_keys(), metric.key


def test_every_climate_metric_is_registered():
    register_all_metrics()
    for metric in CLIMATE_METRICS:
        assert metric.key in metric_keys(), metric.key


def test_every_thermal_metric_is_registered():
    register_all_metrics()
    for metric in THERMAL_METRICS:
        assert metric.key in metric_keys(), metric.key


def test_no_registered_metric_is_a_canopy_temperature_metric():
    """The engine-wide prohibition, checked at the registry level."""
    register_all_metrics()
    for key in metric_keys():
        if key in CANOPY_KEY_ALLOWLIST:
            metric = get_metric(key)
            assert metric.measurement_basis is MeasurementBasis.PROXY, key
            assert "temperature" not in metric.unit.lower(), key
            continue
        assert "canopy" not in key, key
        assert "leaf_temp" not in key, key


def test_registration_is_idempotent():
    """Safe to call from both startup and a test fixture."""
    first = register_all_metrics()
    second = register_all_metrics()
    assert first == second


def test_registration_produces_no_duplicate_keys():
    keys = register_all_metrics()
    assert len(keys) == len(set(keys))


def test_every_declared_domain_is_represented():
    register_all_metrics()
    for domain in REGISTERED_DOMAINS:
        assert metrics_in_domain(domain), f"no metrics registered in {domain}"


def test_metric_keys_are_sorted_for_stable_output():
    """A stable order keeps API responses diffable and testable."""
    keys = register_all_metrics()
    assert keys == sorted(keys)


def test_get_metric_returns_a_working_instance():
    register_all_metrics()
    metric = get_metric("vpd")
    assert metric.key == "vpd"
    assert metric.unit == "kPa"


def test_the_catalog_exposes_every_metric():
    register_all_metrics()
    payload = catalog()
    catalogued = {entry["key"] for entry in payload["metrics"]}
    assert catalogued == set(metric_keys())


def test_every_catalog_entry_carries_its_provenance_vocabulary():
    """The catalog is what the frontend renders, so it must be complete.

    An unavailable metric is exempt from the dataset requirement only in
    the sense that it may legitimately declare no dataset: it produces no
    value, so there is nothing to attribute. Everything else must be
    present, because the entry still has to be describable to a user.
    """
    register_all_metrics()
    for entry in catalog()["metrics"]:
        assert entry["display_name"], entry["key"]
        assert entry["display_name_fa"], entry["key"]
        assert entry["unit"], entry["key"]
        assert entry["description"], entry["key"]
        assert entry["measurement_basis"], entry["key"]
        assert entry["limitations"], entry["key"]
        if entry.get("available", True):
            assert entry["dataset_ids"], entry["key"]


def test_unavailable_metrics_explain_themselves():
    """A metric that can never carry a value must say why, in the catalog.

    Registering an unavailable metric is only defensible if the catalog
    answers the user's question. A bare ``null`` with no explanation is
    indistinguishable from a bug, so both a machine-readable code and a
    human-readable reason are required.
    """
    register_all_metrics()
    unavailable = [
        entry
        for entry in catalog()["metrics"]
        if entry.get("available") is False
    ]
    assert unavailable, "at least one metric is expected to be unavailable"
    for entry in unavailable:
        assert entry.get("unavailable_reason"), entry["key"]
        assert entry.get("unavailable_code"), entry["key"]
        # The reason must be a real explanation, not a placeholder.
        assert len(entry["unavailable_reason"]) > 100, entry["key"]


def test_every_catalog_entry_declares_its_measurement_basis():
    register_all_metrics()
    valid = {
        "direct",
        "product",
        "derived",
        "modelled",
        "proxy",
        "inference",
    }
    for entry in catalog()["metrics"]:
        assert entry["measurement_basis"] in valid, entry["key"]


def test_proxy_metrics_are_flagged_in_the_catalog():
    """A proxy must be labelled as one wherever it is exposed."""
    register_all_metrics()
    proxies = {
        entry["key"]
        for entry in catalog()["metrics"]
        if entry["measurement_basis"] in ("proxy", "inference")
    }
    for entry in catalog()["metrics"]:
        expected = entry["key"] in proxies
        assert entry["is_proxy"] is expected, entry["key"]


def test_the_catalog_lists_the_datasets_the_metrics_use():
    register_all_metrics()
    payload = catalog()
    declared = {entry["id"] for entry in payload["datasets"]}
    used = set()
    for entry in payload["metrics"]:
        used.update(entry["dataset_ids"])
    internal = used - {d for d in used if d.startswith("ISRIC/")}
    missing = internal - declared
    assert not missing, f"metrics use datasets absent from the catalog: {missing}"


def test_the_catalog_reports_which_datasets_are_verified():
    """The verification flag is what tells a consumer to trust a dataset."""
    register_all_metrics()
    for entry in catalog()["datasets"]:
        assert "verified" in entry, entry["id"]
        assert isinstance(entry["verified"], bool), entry["id"]


def test_persian_names_are_actually_persian():
    """A copy-pasted English string would render as untranslated."""
    register_all_metrics()
    for entry in catalog()["metrics"]:
        name_fa = entry["display_name_fa"]
        assert any("\u0600" <= char <= "\u06ff" for char in name_fa), entry["key"]
