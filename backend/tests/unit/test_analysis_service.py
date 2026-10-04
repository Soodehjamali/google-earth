"""Tests for the analysis service routing (Phase S.2).

Proves that climate, water, soil, stress, and irrigation analysis types
are routed through the agriculture engine and return real results instead
of ``not_implemented``.

All tests are deterministic and mock Earth Engine. No live GEE calls.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.services.analysis_service import (
    AnalysisService,
    _ANALYSIS_TYPE_DOMAINS,
    _extract_min_max,
    _extract_value,
    _map_climate,
    _map_irrigation,
    _map_soil,
    _map_stress,
    _map_water,
)


# ---------------------------------------------------------------------------
# 1. Routing table tests
# ---------------------------------------------------------------------------


class TestAnalysisTypeDomains:
    """Verify the routing table covers the expected analysis types."""

    def test_climate_in_routing_table(self) -> None:
        assert "climate" in _ANALYSIS_TYPE_DOMAINS

    def test_water_in_routing_table(self) -> None:
        assert "water" in _ANALYSIS_TYPE_DOMAINS

    def test_soil_in_routing_table(self) -> None:
        assert "soil" in _ANALYSIS_TYPE_DOMAINS

    def test_stress_in_routing_table(self) -> None:
        assert "stress" in _ANALYSIS_TYPE_DOMAINS

    def test_irrigation_in_routing_table(self) -> None:
        assert "irrigation" in _ANALYSIS_TYPE_DOMAINS

    def test_climate_routes_to_climate_domain(self) -> None:
        assert _ANALYSIS_TYPE_DOMAINS["climate"] == ["climate"]

    def test_water_routes_to_water_domain(self) -> None:
        assert _ANALYSIS_TYPE_DOMAINS["water"] == ["water"]

    def test_soil_routes_to_soil_domain(self) -> None:
        assert _ANALYSIS_TYPE_DOMAINS["soil"] == ["soil"]

    def test_five_types_total(self) -> None:
        assert len(_ANALYSIS_TYPE_DOMAINS) == 5


# ---------------------------------------------------------------------------
# 2. Value extraction helper tests
# ---------------------------------------------------------------------------


class TestExtractValue:
    def test_none_outcome(self) -> None:
        assert _extract_value(None) is None

    def test_dict_value(self) -> None:
        outcome = MagicMock()
        outcome.result.value = {"mean": 0.42, "min": 0.1, "max": 0.9}
        assert _extract_value(outcome) == 0.42

    def test_scalar_value(self) -> None:
        outcome = MagicMock()
        outcome.result.value = 0.42
        assert _extract_value(outcome) == 0.42

    def test_none_value(self) -> None:
        outcome = MagicMock()
        outcome.result.value = None
        assert _extract_value(outcome) is None

    def test_custom_field(self) -> None:
        outcome = MagicMock()
        outcome.result.value = {"total": 120.5}
        assert _extract_value(outcome, field="total") == 120.5


class TestExtractMinMax:
    def test_none_outcome(self) -> None:
        result = _extract_min_max(None)
        assert result == {"min": None, "max": None, "mean": None}

    def test_dict_value(self) -> None:
        outcome = MagicMock()
        outcome.result.value = {"mean": 25.0, "min": 18.0, "max": 32.0}
        result = _extract_min_max(outcome)
        assert result["mean"] == 25.0
        assert result["min"] == 18.0
        assert result["max"] == 32.0

    def test_scalar_value(self) -> None:
        outcome = MagicMock()
        outcome.result.value = 25.0
        result = _extract_min_max(outcome)
        assert result["mean"] == 25.0
        assert result["min"] == 25.0
        assert result["max"] == 25.0


# ---------------------------------------------------------------------------
# 3. Response mapper tests
# ---------------------------------------------------------------------------


class TestMapClimate:
    def test_maps_temperature_precipitation_et(self) -> None:
        outcomes: Dict[str, Any] = {
            "temperature_mean": MagicMock(result=MagicMock(value={"mean": 25.0, "min": 18.0, "max": 32.0})),
            "temperature_min": MagicMock(result=MagicMock(value=18.0)),
            "temperature_max": MagicMock(result=MagicMock(value=32.0)),
            "precipitation": MagicMock(result=MagicMock(value=45.0)),
            "evapotranspiration": MagicMock(result=MagicMock(value=120.0)),
        }
        result = _map_climate(outcomes, {"status": "completed"})
        climate = result["climate"]
        assert climate["temperature"]["mean"] == 25.0
        assert climate["temperature"]["min"] == 18.0
        assert climate["temperature"]["max"] == 32.0
        assert climate["precipitation"]["total"] == 45.0
        assert climate["evapotranspiration"]["total"] == 120.0

    def test_missing_metrics_handled(self) -> None:
        result = _map_climate({}, {"status": "completed"})
        climate = result["climate"]
        assert climate["temperature"]["mean"] is None
        assert climate["precipitation"]["total"] is None
        assert climate["evapotranspiration"]["total"] is None


class TestMapWater:
    def test_maps_ndwi_soil_moisture_precipitation(self) -> None:
        outcomes: Dict[str, Any] = {
            "ndwi": MagicMock(result=MagicMock(value={"mean": 0.35, "min": 0.1, "max": 0.6})),
            "soil_moisture_surface": MagicMock(result=MagicMock(value={"mean": 0.18})),
            "precipitation": MagicMock(result=MagicMock(value=30.0)),
        }
        result = _map_water(outcomes, {"status": "completed"})
        water = result["water"]
        assert water["ndwi"]["mean"] == 0.35
        assert water["soil_moisture"]["mean"] == 0.18
        assert water["precipitation"]["total"] == 30.0

    def test_stress_level_from_ndwi(self) -> None:
        # High NDWI → low stress
        outcomes = {"ndwi": MagicMock(result=MagicMock(value={"mean": 0.5}))}
        result = _map_water(outcomes, {"status": "completed"})
        assert result["water"]["stress_level"] == "low"

        # Moderate NDWI
        outcomes = {"ndwi": MagicMock(result=MagicMock(value={"mean": 0.1}))}
        result = _map_water(outcomes, {"status": "completed"})
        assert result["water"]["stress_level"] == "moderate"

        # Low NDWI
        outcomes = {"ndwi": MagicMock(result=MagicMock(value={"mean": -0.2}))}
        result = _map_water(outcomes, {"status": "completed"})
        assert result["water"]["stress_level"] == "high"


class TestMapSoil:
    def test_maps_all_soil_properties(self) -> None:
        outcomes: Dict[str, Any] = {
            "soil_moisture_surface": MagicMock(result=MagicMock(value={"mean": 0.22})),
            "soil_organic_carbon": MagicMock(result=MagicMock(value={"mean": 12.5})),
            "soil_ph": MagicMock(result=MagicMock(value={"mean": 7.0})),
            "soil_sand_content": MagicMock(result=MagicMock(value=45.0)),
            "soil_clay_content": MagicMock(result=MagicMock(value=25.0)),
            "soil_silt_content": MagicMock(result=MagicMock(value=30.0)),
            "soil_texture_class": MagicMock(result=MagicMock(value="loam")),
        }
        result = _map_soil(outcomes, {"status": "completed"})
        soil = result["soil"]
        assert soil["soil_moisture"]["mean"] == 0.22
        assert soil["organic_carbon"]["mean"] == 12.5
        assert soil["ph"]["mean"] == 7.0
        assert soil["sand"] == 45.0
        assert soil["clay"] == 25.0
        assert soil["silt"] == 30.0
        assert soil["texture"]["class"] == "loam"


class TestMapStress:
    def test_maps_stress_metrics(self) -> None:
        outcomes: Dict[str, Any] = {
            "evaporative_fraction": MagicMock(result=MagicMock(value={"mean": 0.6})),
            "vpd_anomaly": MagicMock(result=MagicMock(value={"mean": 0.5})),
            "lst_day_anomaly": MagicMock(result=MagicMock(value={"mean": -1.2})),
        }
        result = _map_stress(outcomes, {"status": "completed"})
        stress = result["stress"]
        assert stress["evaporative_fraction"]["mean"] == 0.6
        assert stress["vpd_anomaly"]["mean"] == 0.5
        assert stress["lst_day_anomaly"]["mean"] == -1.2


class TestMapIrrigation:
    def test_maps_irrigation_metrics(self) -> None:
        outcomes: Dict[str, Any] = {
            "precipitation_cumulative": MagicMock(result=MagicMock(value={"mean": 150.0})),
            "et_precipitation_deficit": MagicMock(result=MagicMock(value={"mean": -30.0})),
            "precipitation_anomaly": MagicMock(result=MagicMock(value={"mean": -0.5})),
        }
        result = _map_irrigation(outcomes, {"status": "completed"})
        irr = result["irrigation"]
        assert irr["precipitation_cumulative"]["mean"] == 150.0
        assert irr["et_precipitation_deficit"]["mean"] == -30.0
        assert irr["precipitation_anomaly"]["mean"] == -0.5


# ---------------------------------------------------------------------------
# 4. Integration: create_analysis routes correctly
# ---------------------------------------------------------------------------


class TestAnalysisServiceRouting:
    """Prove the service routes new analysis types to the agriculture engine."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        from app.services.cache_service import cache_service
        cache_service.clear()
        self.service = AnalysisService()
        self.geometry = {"type": "Point", "coordinates": [51.3, 35.7]}
        self.start_date = "2025-01-01"
        self.end_date = "2025-09-01"
        yield
        cache_service.clear()

    @pytest.mark.parametrize("analysis_type", ["climate", "water", "soil", "stress", "irrigation"])
    @patch("app.services.analysis_service.create_ee_geometry")
    @patch.object(AnalysisService, "_run_domain_analysis")
    def test_domain_types_route_to_domain_analysis(
        self, mock_domain: MagicMock, mock_geom: MagicMock, analysis_type: str
    ) -> None:
        mock_domain.return_value = {"status": "completed", "analysis_type": analysis_type}
        db = MagicMock()

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.service.create_analysis(
                    db, self.geometry, self.start_date, self.end_date, analysis_type
                )
            )
        finally:
            loop.close()

        mock_domain.assert_called_once()
        assert result["status"] == "completed"
        assert result["analysis_type"] == analysis_type

    @pytest.mark.parametrize("analysis_type", ["climate", "water", "soil"])
    @patch("app.services.analysis_service.create_ee_geometry")
    @patch.object(AnalysisService, "_run_domain_analysis")
    def test_domain_types_no_longer_return_not_implemented(
        self, mock_domain: MagicMock, mock_geom: MagicMock, analysis_type: str
    ) -> None:
        mock_domain.return_value = {"status": "completed", "analysis_type": analysis_type}
        db = MagicMock()

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.service.create_analysis(
                    db, self.geometry, self.start_date, self.end_date, analysis_type
                )
            )
        finally:
            loop.close()

        assert result["status"] == "completed"
        assert "not_implemented" not in str(result)

    @patch("app.services.analysis_service.create_ee_geometry")
    def test_unknown_type_still_returns_not_implemented(self, mock_geom: MagicMock) -> None:
        db = MagicMock()

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self.service.create_analysis(
                    db, self.geometry, self.start_date, self.end_date, "unknown_type"
                )
            )
        finally:
            loop.close()

        assert result["status"] == "failed"
        assert "not_implemented" in str(result.get("result_data", {}))
