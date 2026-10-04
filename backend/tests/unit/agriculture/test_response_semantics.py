"""F-CONTRACT-FIX-1 focused tests: Agriculture response semantics.

Locks the contract corrections from the PHASE F-CONTRACT-AUDIT:

* explicit domain semantics — domains_with_data / domains_with_statements /
  domains_without_data alongside the legacy statement-based
  available_domains (unchanged meaning);
* canonical de-duplicated unavailability — unavailable_metric_keys
  counts each missing metric once;
* limitation semantics distinguish "no statement fired" from
  "no usable data";
* thermal temporal gating follows all-domain request semantics
  (domains omitted -> thermal requested; explicit lists respected);
* synthesis behavior is unchanged — no additional statements are
  forced, thresholds untouched.

Pure unit tests over the real synthesis and temporal_section modules.
No Earth Engine, no network, no database.  The thermal gating test
reads the module's gating decision through a stubbed builder path so
no GEE dependency is introduced.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import pytest

from app.services.agriculture.evidence import (
    EvidenceBundle,
    EvidenceItem,
    EvidenceStatus,
)
from app.services.agriculture.synthesis import (
    AgriculturalSynthesis,
    DEFAULT_RULES,
    DomainSummary,
    SynthesisDomain,
    SynthesisEngine,
    SynthesisStatement,
)
from app.services.agriculture.types import QualityLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    metric_key: str,
    value: Optional[float],
    quality: QualityLevel = QualityLevel.GOOD,
    status: EvidenceStatus = EvidenceStatus.DERIVED,
    unit: str = "index",
    source: str = "ds_a",
) -> EvidenceItem:
    return EvidenceItem(
        metric_key=metric_key,
        value=value,
        unit=unit,
        status=status,
        temporal_start=date(2024, 7, 1),
        temporal_end=date(2024, 7, 31),
        quality_level=quality,
        provenance=None,
        source_dataset_id=source,
    )


def _bundle(
    name: str,
    items: List[EvidenceItem],
) -> EvidenceBundle:
    bundle = EvidenceBundle(name=name, items=items)
    bundle.run_consistency_checks()
    bundle.assess_sufficiency()
    return bundle


def _water_fire_bundle() -> EvidenceBundle:
    """A water bundle whose three negative anomalies fire a rule."""
    return _bundle(
        "water",
        [
            _item("precipitation_anomaly", -0.8, source="ds_a"),
            _item("soil_moisture_rootzone_anomaly", -0.6, source="ds_b"),
            _item("evapotranspiration_anomaly", -0.4, source="ds_c"),
        ],
    )


def _water_muted_bundle() -> EvidenceBundle:
    """A water bundle with usable data that fires no rule.

    Water rules need at least two usable anomaly values with
    agreeing or opposing signs (below: >=2 negative, above: >=2
    positive, mixed: both signs present).  A single usable value
    carries real data but establishes none of those patterns —
    exactly the audited "data without statement" shape.
    """
    return _bundle(
        "water_muted",
        [
            _item("precipitation_anomaly", -0.8, source="ds_a"),
        ],
    )


def _dataless_bundle(name: str) -> EvidenceBundle:
    """A bundle where every item is unusable."""
    return _bundle(
        name,
        [
            _item(
                "ndvi",
                None,
                quality=QualityLevel.UNAVAILABLE,
                status=EvidenceStatus.UNAVAILABLE,
                source="ds_a",
            ),
        ],
    )


def _statement(domain: SynthesisDomain) -> SynthesisStatement:
    return SynthesisStatement(
        rule_id="test_rule",
        domain=domain,
        statement="Test.",
        pattern=__import__(
            "app.services.agriculture.synthesis", fromlist=["PatternState"]
        ).PatternState.BELOW_CONTEXT,
        evidence_keys=("k",),
        evidence_values={"k": -0.1},
        scientific_basis="Basis.",
        limitations=("Limitation.",),
    )


# ---------------------------------------------------------------------------
# 1-3. Domain semantics
# ---------------------------------------------------------------------------


class TestDomainSemantics:
    def test_usable_evidence_without_statements_is_data_domain(self) -> None:
        """Test 1: usable evidence, zero statements -> data yes, statement no."""
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_muted_bundle(),
        }
        synthesis = engine.synthesise(bundles)

        assert SynthesisDomain.WATER in synthesis.domains_with_data
        assert SynthesisDomain.WATER not in synthesis.domains_with_statements
        # available_domains keeps its statement-based meaning
        assert SynthesisDomain.WATER not in synthesis.available_domains
        # and the without-data complement is empty for this domain
        assert SynthesisDomain.WATER not in synthesis.domains_without_data

    def test_statement_domain_appears_in_both_lists(self) -> None:
        """Test 2: a firing domain appears in data AND statement lists."""
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_fire_bundle(),
        }
        synthesis = engine.synthesise(bundles)

        assert SynthesisDomain.WATER in synthesis.domains_with_data
        assert SynthesisDomain.WATER in synthesis.domains_with_statements
        # legacy field unchanged: statements => available
        assert SynthesisDomain.WATER in synthesis.available_domains

    def test_unavailable_only_domain_has_no_data(self) -> None:
        """Test 3: unavailable-only evidence never counts as usable data."""
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.CROP: _dataless_bundle("crop"),
        }
        synthesis = engine.synthesise(bundles)

        assert SynthesisDomain.CROP not in synthesis.domains_with_data
        assert SynthesisDomain.CROP in synthesis.domains_without_data
        assert SynthesisDomain.CROP not in synthesis.domains_with_statements

    def test_explicit_statement_presence_sets_data_flag(self) -> None:
        """A hand-built summary carrying has_usable_evidence serializes it."""
        summary = DomainSummary(
            domain=SynthesisDomain.SOIL,
            statements=[_statement(SynthesisDomain.SOIL)],
            has_usable_evidence=True,
        )
        d = summary.to_dict()
        assert d["has_usable_evidence"] is True
        assert d["statement_count"] == 1

    def test_domain_summary_defaults_false(self) -> None:
        """Hand-constructed summaries stay data-less until told otherwise."""
        summary = DomainSummary(domain=SynthesisDomain.SOIL)
        assert summary.has_usable_evidence is False


# ---------------------------------------------------------------------------
# 4. De-duplicated unavailability
# ---------------------------------------------------------------------------


class TestUnavailableAggregate:
    def test_duplicate_keys_counted_once(self) -> None:
        """Test 4: the same key in summary lists counts once in aggregate."""
        synthesis = AgriculturalSynthesis(
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
        )
        synthesis.domain_summaries = {
            SynthesisDomain.SOIL: DomainSummary(
                domain=SynthesisDomain.SOIL,
                unavailable_evidence=["soil_ph", "soil_salinity"],
            ),
            # A second domain repeating soil_ph (cross-bundle duplicate,
            # mirroring how derived metrics can appear in two bundles).
            SynthesisDomain.WATER: DomainSummary(
                domain=SynthesisDomain.WATER,
                unavailable_evidence=["cwsi", "soil_ph"],
            ),
        }
        keys = synthesis.unavailable_metric_keys()
        assert keys.count("soil_ph") == 1
        assert keys.count("cwsi") == 1
        assert set(keys) == {"soil_ph", "soil_salinity", "cwsi"}
        assert len(keys) == 3

    def test_first_seen_order_preserved(self) -> None:
        synthesis = AgriculturalSynthesis(
            time_start=date(2024, 7, 1),
            time_end=date(2024, 7, 31),
        )
        synthesis.domain_summaries = {
            SynthesisDomain.WATER: DomainSummary(
                domain=SynthesisDomain.WATER,
                unavailable_evidence=["cwsi", "wdi"],
            ),
            SynthesisDomain.SOIL: DomainSummary(
                domain=SynthesisDomain.SOIL,
                unavailable_evidence=["soil_ph"],
            ),
        }
        assert synthesis.unavailable_metric_keys() == ["cwsi", "wdi", "soil_ph"]

    def test_engine_summary_lists_equal_bundle_lists(self) -> None:
        """The engine still copies bundle.unavailable into the summary.

        The double representation is a compatibility contract; the
        de-duplication is owned by the aggregate, not by mutating the
        per-domain detail.
        """
        engine = SynthesisEngine()
        bundle = _bundle(
            "water",
            [
                _item("ndvi", None, quality=QualityLevel.UNAVAILABLE,
                      status=EvidenceStatus.UNAVAILABLE),
            ],
        )
        summary = engine.evaluate_domain(SynthesisDomain.WATER, bundle)
        assert summary.unavailable_evidence == ["ndvi"]


# ---------------------------------------------------------------------------
# 5. Limitation semantics
# ---------------------------------------------------------------------------


class TestLimitationSemantics:
    def test_data_gap_vs_statement_gap_distinguished(self) -> None:
        bundles = {
            SynthesisDomain.WATER: _water_muted_bundle(),
            SynthesisDomain.CROP: _dataless_bundle("crop"),
        }
        engine = SynthesisEngine()
        synthesis = engine.synthesise(bundles)

        limitations = synthesis.limitations
        # Usable data but no statement -> statement-gap wording only.
        assert "No synthesis rules fired for water." in limitations
        assert "No usable evidence for water." not in limitations
        # No usable data -> data-gap wording, not the statement line.
        assert "No usable evidence for crop." in limitations
        assert "No synthesis rules fired for crop." not in limitations

    def test_legacy_statement_line_still_verbatim(self) -> None:
        """Existing consumers of the exact sentence keep working."""
        engine = SynthesisEngine()
        bundles = {SynthesisDomain.WATER: _water_muted_bundle()}
        synthesis = engine.synthesise(bundles)
        assert (
            f"No synthesis rules fired for {SynthesisDomain.WATER.value}."
            in synthesis.limitations
        )


# ---------------------------------------------------------------------------
# 6-8. Thermal all-domain gating
# ---------------------------------------------------------------------------


class TestThermalGating:
    """The gating decision is read through the real module with the
    downstream builders stubbed, so no Earth Engine is touched."""

    @staticmethod
    def _run(monkeypatch, domains, keys):
        from app.services.agriculture import temporal_section

        wanted: Dict[str, bool] = {"thermal": False}

        class _Ctx:
            start_date = "2024-01-01"
            end_date = "2024-01-31"

        def fake_optical_triplet(context, key):
            raise RuntimeError("stubbed")

        def fake_radar_pair(context, key):
            raise RuntimeError("stubbed")

        def fake_thermal_payload(context, months):
            wanted["thermal"] = True
            return ({}, {}, None, None, None, [])

        monkeypatch.setattr(
            temporal_section, "_optical_triplet", fake_optical_triplet
        )
        monkeypatch.setattr(
            temporal_section, "_radar_pair", fake_radar_pair
        )
        monkeypatch.setattr(
            temporal_section, "_thermal_payload", fake_thermal_payload
        )
        payload = temporal_section.build_temporal_section(
            _Ctx(), list(keys), domains
        )
        return payload, wanted["thermal"]

    def test_domains_omitted_requests_thermal(self, monkeypatch) -> None:
        """Test 5: domains=None means all domains, thermal included."""
        keys = ("ndvi",)
        payload, thermal_requested = self._run(monkeypatch, None, keys)
        assert thermal_requested is True
        # The per-key stubs record their own refusal as a limitation,
        # which is the honest transport behavior.
        assert any("ndvi" in lim for lim in payload["limitations"])

    def test_domains_with_thermal_requests_thermal(self, monkeypatch) -> None:
        """Test 6: explicit thermal in the list requests thermal."""
        _, thermal_requested = self._run(
            monkeypatch, ["vegetation", "thermal"], ("ndvi",)
        )
        assert thermal_requested is True

    def test_domains_without_thermal_skips_thermal(self, monkeypatch) -> None:
        """Test 7: explicit exclusion must not request thermal."""
        _, thermal_requested = self._run(
            monkeypatch, ["vegetation", "water"], ("ndvi",)
        )
        assert thermal_requested is False


# ---------------------------------------------------------------------------
# 8. Synthesis behavior preserved
# ---------------------------------------------------------------------------


class TestSynthesisPreserved:
    def test_statement_rules_unchanged(self) -> None:
        """Test 8: the same bundles fire the same rules as before."""
        engine = SynthesisEngine()
        bundles = {
            SynthesisDomain.WATER: _water_fire_bundle(),
            SynthesisDomain.SOIL: _bundle(
                "soil",
                [
                    _item(
                        "soil_moisture_rootzone_anomaly",
                        -0.2,
                        unit="m3/m3",
                        source="ds_b",
                    ),
                ],
            ),
        }
        synthesis = engine.synthesise(bundles)
        water = synthesis.domain_summaries[SynthesisDomain.WATER]
        assert any(s.rule_id == "water_below_baseline" for s in water.statements)
        # The soil rule still fires on its negative anomaly.
        soil = synthesis.domain_summaries[SynthesisDomain.SOIL]
        assert any(
            s.rule_id == "soil_moisture_below_baseline" for s in soil.statements
        )

    def test_default_rule_count_untouched(self) -> None:
        assert len(DEFAULT_RULES) == 18

    def test_legacy_to_dict_fields_present_and_new_fields_additive(self) -> None:
        engine = SynthesisEngine()
        bundles = {SynthesisDomain.WATER: _water_fire_bundle()}
        synthesis = engine.synthesise(bundles)
        d = synthesis.to_dict()

        # Legacy keys, unchanged meaning
        for key in (
            "time_start",
            "time_end",
            "spatial_context",
            "available_domains",
            "unavailable_domains",
            "overall_sufficiency",
            "domain_summaries",
            "cross_domain_statements",
            "limitations",
            "metadata",
        ):
            assert key in d, key
        assert d["available_domains"] == ["water"]

        # New additive keys
        for key in (
            "domains_with_data",
            "domains_with_statements",
            "domains_without_data",
            "unavailable_metric_keys",
        ):
            assert key in d, key
        assert d["domains_with_statements"] == ["water"]
        assert d["domains_with_data"] == ["water"]
