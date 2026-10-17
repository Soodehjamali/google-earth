"""Unit and integration tests for Frost Risk API, storage migration, and safety lock.

Verifies:
1. Alembic migration upgrade -> downgrade -> upgrade cycle for 002_frost.
2. Ad-hoc assessment endpoint (/api/v1/agriculture/frost/assess) with unified schema.
3. Earth Engine outage handling (/frost/assess with use_live_gee -> ERR_GEE_UNAVAILABLE / 503).
4. Outbound dispatch safety lock: strictly refuses real outbound notifications
   when thresholds_verified=False unless admin_override=True.
5. Recipient PII masking (phone numbers and emails).
6. Idempotency and upward escalation in alert evaluation.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.agriculture.notification import (
    MockLiveNetworkNotificationProvider,
    NotificationProviderRegistry,
    StubNotificationProvider,
    UnverifiedThresholdsSafetyLockError,
    dispatch_alert_with_safety_lock,
    mask_recipient,
)

SAMPLE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [54.015, 32.310],
            [54.025, 32.310],
            [54.025, 32.320],
            [54.015, 32.320],
            [54.015, 32.310],
        ]
    ],
}


def test_alembic_migration_002_upgrade_downgrade_cycle(tmp_path):
    """Verify that migration 002_frost executes clean upgrade -> downgrade -> upgrade."""
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    test_db = tmp_path / "test_migration.db"
    ini_path = Path("alembic.ini") if Path("alembic.ini").exists() else Path("backend/alembic.ini")
    cfg = Config(str(ini_path))
    if not Path("alembic").exists() and Path("backend/alembic").exists():
        cfg.set_main_option("script_location", "backend/alembic")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{test_db}")

    # Upgrade to head (002_frost)
    command.upgrade(cfg, "head")

    # Downgrade back to 001_initial
    command.downgrade(cfg, "-1")

    # Re-upgrade to head (002_frost)
    command.upgrade(cfg, "head")


def test_mask_recipient_pii():
    """Verify that phone numbers and emails are masked to prevent log leakage."""
    assert mask_recipient("+989123456789") == "+989***89"
    assert mask_recipient("09131234567") == "0913***67"
    assert mask_recipient("farmer@ardakan-pistachio.ir") == "fa***@ardakan-pistachio.ir"
    assert mask_recipient("") == ""


@pytest.mark.asyncio
async def test_outbound_dispatch_safety_lock_enforcement():
    """Verify that outbound safety lock blocks real delivery when thresholds_verified=False."""
    registry = NotificationProviderRegistry()
    real_provider = MockLiveNetworkNotificationProvider("sms")
    registry.register("sms", real_provider)

    recipient = "+989123456789"
    message = "هشدار سرمازدگی"

    # Case 1: Real network provider + thresholds_verified=False + admin_override=False -> BLOCKED
    with pytest.raises(UnverifiedThresholdsSafetyLockError, match="SAFETY LOCK REFUSAL"):
        await dispatch_alert_with_safety_lock(
            channel="sms",
            recipient=recipient,
            message=message,
            thresholds_verified=False,
            admin_override=False,
            force_dry_run=False,
            registry=registry,
        )
    assert real_provider.sent_count == 0

    # Case 2: Force dry run -> Routes to safe stub without throwing
    dry_res = await dispatch_alert_with_safety_lock(
        channel="sms",
        recipient=recipient,
        message=message,
        thresholds_verified=False,
        admin_override=False,
        force_dry_run=True,
        registry=registry,
    )
    assert dry_res.status == "dry_run"
    assert real_provider.sent_count == 0

    # Case 3: Admin override enabled -> Permitted
    sent_res = await dispatch_alert_with_safety_lock(
        channel="sms",
        recipient=recipient,
        message=message,
        thresholds_verified=False,
        admin_override=True,
        force_dry_run=False,
        registry=registry,
    )
    assert sent_res.status == "sent"
    assert real_provider.sent_count == 1

    # Case 4: Thresholds verified -> Permitted
    verified_res = await dispatch_alert_with_safety_lock(
        channel="sms",
        recipient=recipient,
        message=message,
        thresholds_verified=True,
        admin_override=False,
        force_dry_run=False,
        registry=registry,
    )
    assert verified_res.status == "sent"
    assert real_provider.sent_count == 2


def test_assess_frost_risk_endpoint_adhoc():
    """Verify POST /api/v1/agriculture/frost/assess returns complete advisory assessment."""
    from app.core.config import settings
    settings.ADMIN_API_KEY = "admin-secret-token"
    client = TestClient(app)
    headers = {"X-Admin-Token": "admin-secret-token"}
    payload = {
        "geometry": SAMPLE_POLYGON,
        "crop": "pistachio",
        "phenological_stage": "early_bloom",
        "horizon_h": 48,
        "pooling_risk_proxy": 0.65,
        "use_live_gee": False,
    }

    resp = client.post("/api/v1/agriculture/frost/assess", json=payload, headers=headers)
    assert resp.status_code == 200, f"Error {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["crop"] == "pistachio"
    assert data["crop_fa"] == "پسته"
    assert data["stage_fa"] == "اوایل گلدهی"
    assert data["thresholds_status"] == "placeholder"
    assert data["thresholds_verified"] is False
    assert len(data["thresholds_warning_fa"]) > 0
    assert data["evidence_level"] <= "B"
    assert data["evidence_level"] == "B"
    assert "forecast" in data
    assert data["forecast"]["quality_state"] == "coarse_context"
    assert data["forecast"]["native_spatial_resolution_m"] == 27830.0
    assert data["forecast"]["issue_time_utc"] is not None
    assert len(data["forecast"]["series"]) > 0
    assert data["forecast"]["series"][0]["lead_time_uncertainty_c"] is not None
    assert data["forecast"]["series"][0]["elevation_uncertainty_c"] is not None
    assert data["forecast"]["series"][0]["total_uncertainty_c"] is not None
    assert "nightly_risks" in data
    assert len(data["nightly_risks"]) >= 2
    assert "overall_risk_level" in data
    assert "overall_risk_level_fa" in data

    # Unknown stage fallback verification
    payload_unknown = dict(payload)
    payload_unknown["phenological_stage"] = "unrecognized_stage_xyz"
    resp_unknown = client.post("/api/v1/agriculture/frost/assess", json=payload_unknown, headers=headers)
    assert resp_unknown.status_code == 200
    data_unknown = resp_unknown.json()
    assert data_unknown["phenological_stage"] == "fruit_set"
    assert data_unknown["t_critical_10_c"] == -1.0
    assert "مرحله فنولوژیکی نامشخص است" in data_unknown["thresholds_warning_fa"]


def test_assess_frost_risk_endpoint_gee_outage_503_envelope():
    """Verify that live Earth Engine outage returns ERR_GEE_UNAVAILABLE and HTTP 503."""
    from app.core.config import settings
    settings.ADMIN_API_KEY = "admin-secret-token"
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Admin-Token": "admin-secret-token"}
    payload = {
        "geometry": SAMPLE_POLYGON,
        "crop": "pistachio",
        "phenological_stage": "early_bloom",
        "use_live_gee": True,
    }

    # Simulate GEE outage
    with patch(
        "app.services.agriculture.cold_air_pooling.calculate_cold_air_pooling_ee",
        side_effect=RuntimeError("Earth Engine connection timed out (Google service outage)"),
    ):
        resp = client.post("/api/v1/agriculture/frost/assess", json=payload, headers=headers)
        assert resp.status_code == 503
        data = resp.json()
        assert data.get("code") == "ERR_GEE_UNAVAILABLE" or "ERR_GEE_UNAVAILABLE" in resp.text


@pytest.mark.asyncio
async def test_evaluate_alerts_idempotency_and_escalation():
    """Verify that evaluate_alerts_endpoint enforces idempotency and upward-only escalation."""
    from app.api.v1.agriculture import evaluate_alerts_endpoint
    from app.db.models.frost import Orchard, AlertRule, NotificationLog

    orchard_id = uuid.uuid4()
    rule_id = uuid.uuid4()

    mock_orchard = Orchard(
        id=orchard_id,
        name="باغ پسته اردکان",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="early_bloom",
        elevation=1200.0,
    )
    mock_rule = AlertRule(
        id=rule_id,
        orchard_id=orchard_id,
        recipient="+989123456789",
        channel="sms",
        lead_time_h=24,
        enabled=True,
        orchard=mock_orchard,
    )

    db_entries: list[NotificationLog] = []

    class MockDbSession:
        async def execute(self, stmt):
            stmt_str = str(stmt)
            mock_res = MagicMock()
            if "alert_rules" in stmt_str:
                mock_res.scalars.return_value.all.return_value = [mock_rule]
            elif "notification_log" in stmt_str:
                mock_res.scalars.return_value.all.return_value = list(db_entries)
            else:
                mock_res.scalars.return_value.all.return_value = []
            return mock_res

        def add(self, obj):
            db_entries.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    mock_db = MockDbSession()

    from app.services.agriculture.forecast import FakeForecastProvider

    # Evaluate under freezing forecast (Tmin = -4°C -> triggers warning/watch)
    with patch(
        "app.services.agriculture.forecast.FakeForecastProvider",
        lambda *args, **kwargs: FakeForecastProvider(base_tmin_c=-4.0, z_site_m=1200.0),
    ):
        # 1. First evaluation: should dispatch dry_run notification
        res1 = await evaluate_alerts_endpoint(
            eval_in={"dry_run": True, "use_live_gee": False},
            db=mock_db,
        )
        assert res1["evaluated_orchards"] == 1
        assert res1["dispatched_notifications"] == 1
        assert len(db_entries) == 1
        assert db_entries[0].status == "dry_run"

        # 2. Second evaluation under identical forecast: should be skipped (idempotent!)
        res2 = await evaluate_alerts_endpoint(
            eval_in={"dry_run": True, "use_live_gee": False},
            db=mock_db,
        )
        assert res2["evaluated_orchards"] == 1
        assert res2["dispatched_notifications"] == 0  # Did not duplicate!
        assert len(db_entries) == 1


def test_evaluate_alerts_endpoint_admin_auth_required():
    """Verify that POST /api/v1/agriculture/frost/evaluate-alerts requires admin authorization."""
    from app.core.config import settings
    client = TestClient(app)

    # 1. Fail closed when ADMIN_API_KEY is unset on server
    settings.ADMIN_API_KEY = None
    resp_unset = client.post(
        "/api/v1/agriculture/frost/evaluate-alerts",
        json={"dry_run": True},
        headers={"X-Admin-Token": "any-token"},
    )
    assert resp_unset.status_code == 403
    assert "server key unset" in resp_unset.text

    # Configure server key
    settings.ADMIN_API_KEY = "admin-secret-token"

    # 2. No auth header -> 403 Forbidden
    resp_no_auth = client.post("/api/v1/agriculture/frost/evaluate-alerts", json={"dry_run": True})
    assert resp_no_auth.status_code == 403
    assert "Admin authorization required" in resp_no_auth.text

    # 3. Invalid auth token -> 403 Forbidden
    resp_bad_auth = client.post(
        "/api/v1/agriculture/frost/evaluate-alerts",
        json={"dry_run": True},
        headers={"X-Admin-Token": "unauthorized-token"},
    )
    assert resp_bad_auth.status_code == 403


def test_frost_all_routes_require_auth_proving_403():
    """Verify that every route under /agriculture/frost requires authentication and returns 403 without it (D4).

    Routes:
    1. POST /api/v1/agriculture/frost/assess
    2. GET /api/v1/agriculture/frost/orchards
    3. POST /api/v1/agriculture/frost/orchards
    4. POST /api/v1/agriculture/frost/orchards/{id}/alert-rules
    5. POST /api/v1/agriculture/frost/evaluate-alerts
    """
    from app.core.config import settings
    settings.ADMIN_API_KEY = "admin-secret-token"
    client = TestClient(app)

    random_orchard_id = uuid.uuid4()
    routes = [
        ("POST", "/api/v1/agriculture/frost/assess", {"geometry": SAMPLE_POLYGON, "crop": "pistachio"}),
        ("GET", "/api/v1/agriculture/frost/orchards", None),
        ("POST", "/api/v1/agriculture/frost/orchards", {"name": "Test Orchard", "geometry": SAMPLE_POLYGON, "crop": "pistachio"}),
        ("POST", f"/api/v1/agriculture/frost/orchards/{random_orchard_id}/alert-rules", {"recipient": "+989123456789", "channel": "sms"}),
        ("POST", "/api/v1/agriculture/frost/evaluate-alerts", {"dry_run": True}),
    ]

    for method, path, payload in routes:
        # Case 1: Without auth header -> must return 403 Forbidden!
        if method == "POST":
            resp_no_auth = client.post(path, json=payload or {})
        else:
            resp_no_auth = client.get(path)
        assert resp_no_auth.status_code == 403, f"{method} {path} without token returned {resp_no_auth.status_code}"

        # Case 2: With invalid token -> must return 403 Forbidden!
        bad_headers = {"X-Admin-Token": "invalid-token", "X-API-Key": "invalid-key"}
        if method == "POST":
            resp_bad = client.post(path, json=payload or {}, headers=bad_headers)
        else:
            resp_bad = client.get(path, headers=bad_headers)
        assert resp_bad.status_code == 403, f"{method} {path} with bad token returned {resp_bad.status_code}"


def test_assess_geometry_caps():
    """Verify that /frost/assess strictly caps geometry vertices and area (D4)."""
    from app.core.config import settings
    settings.ADMIN_API_KEY = "admin-secret-token"
    client = TestClient(app)
    headers = {"X-Admin-Token": "admin-secret-token"}

    # 1. Vertices cap (>500 vertices) -> 400 ERR_GEOMETRY_TOO_COMPLEX
    excessive_vertices = [
        [54.0 + i * 0.0001, 32.0 + (i % 2) * 0.0001] for i in range(505)
    ]
    excessive_vertices.append(excessive_vertices[0])  # close ring
    poly_many_vertices = {"type": "Polygon", "coordinates": [excessive_vertices]}
    resp_vertices = client.post(
        "/api/v1/agriculture/frost/assess",
        json={"geometry": poly_many_vertices, "crop": "pistachio"},
        headers=headers,
    )
    assert resp_vertices.status_code == 400
    assert resp_vertices.json().get("code") == "ERR_GEOMETRY_TOO_COMPLEX"

    # 2. Area cap (>10,000 hectares = 100,000,000 m2) -> 400 ERR_GEOMETRY_TOO_LARGE
    huge_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [52.0, 30.0],
                [54.0, 30.0],
                [54.0, 32.0],
                [52.0, 32.0],
                [52.0, 30.0],
            ]
        ],
    }
    resp_area = client.post(
        "/api/v1/agriculture/frost/assess",
        json={"geometry": huge_polygon, "crop": "pistachio"},
        headers=headers,
    )
    assert resp_area.status_code == 400
    assert resp_area.json().get("code") == "ERR_GEOMETRY_TOO_LARGE"


def test_assess_rate_limiting():
    """Verify that /frost/assess enforces rate limiting per client IP (D4)."""
    from app.core.config import settings
    from app.api.v1.agriculture import _assess_rate_limiter_history
    _assess_rate_limiter_history.clear()

    settings.ADMIN_API_KEY = "admin-secret-token"
    client = TestClient(app)
    headers = {"X-Admin-Token": "admin-secret-token"}
    payload = {
        "geometry": SAMPLE_POLYGON,
        "crop": "pistachio",
        "use_live_gee": False,
    }

    # Simulate hitting rate limit by sending requests up to limit
    for _ in range(60):
        resp = client.post("/api/v1/agriculture/frost/assess", json=payload, headers=headers)
        assert resp.status_code == 200

    # 61st request must trigger 429 RateLimitError
    resp_rate_limited = client.post("/api/v1/agriculture/frost/assess", json=payload, headers=headers)
    assert resp_rate_limited.status_code == 429
    assert resp_rate_limited.json().get("code") == "ERR_RATE_LIMIT_EXCEEDED"


def test_evaluate_alerts_refuses_admin_override_in_request():
    """Verify that admin_override is forbidden in request body and strictly refused (422)."""
    client = TestClient(app)

    # Attempt to pass admin_override in JSON body -> rejected with 422 Unprocessable Entity
    resp = client.post(
        "/api/v1/agriculture/frost/evaluate-alerts",
        json={"dry_run": True, "admin_override": True},
        headers={"X-Admin-Token": "admin-secret-token"},
    )
    assert resp.status_code == 422
    assert resp.json().get("code") == "ERR_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_phone_number_masked_in_all_responses_and_logs(caplog):
    """Verify that raw phone numbers are masked in all responses and never leak into logs."""
    import logging
    from app.api.v1.agriculture import list_orchards_endpoint, create_alert_rule_endpoint, evaluate_alerts_endpoint
    from app.db.models.frost import Orchard, AlertRule

    raw_phone = "+989123456789"
    orchard_id = uuid.uuid4()
    rule_id = uuid.uuid4()

    mock_orchard = Orchard(
        id=orchard_id,
        name="باغ پسته",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="early_bloom",
        elevation=1200.0,
    )
    mock_rule = AlertRule(
        id=rule_id,
        orchard_id=orchard_id,
        recipient=raw_phone,
        channel="sms",
        lead_time_h=24,
        enabled=True,
        orchard=mock_orchard,
    )
    mock_orchard.alert_rules = [mock_rule]

    db_alert_rules = [mock_rule]
    db_notification_logs = []

    class MockDb:
        async def execute(self, stmt):
            m = MagicMock()
            stmt_s = str(stmt)
            if "notification_log" in stmt_s:
                m.scalars.return_value.all.return_value = list(db_notification_logs)
            elif "alert_rules" in stmt_s:
                m.scalars.return_value.all.return_value = list(db_alert_rules)
            elif "orchards" in stmt_s:
                m.scalars.return_value.all.return_value = [mock_orchard]
                m.scalar_one_or_none.return_value = mock_orchard
            else:
                m.scalars.return_value.all.return_value = []
            return m

        def add(self, obj):
            if isinstance(obj, AlertRule):
                db_alert_rules.append(obj)
            else:
                db_notification_logs.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    db = MockDb()

    # 1. list_orchards_endpoint masks recipient
    orchards_out = await list_orchards_endpoint(db=db)
    assert orchards_out[0]["alert_rules"][0]["recipient"] == "+989***89"
    assert raw_phone not in orchards_out[0]["alert_rules"][0]["recipient"]

    # 2. create_alert_rule_endpoint masks recipient in output
    rule_out = await create_alert_rule_endpoint(
        orchard_id=orchard_id,
        rule_in={"recipient": raw_phone, "channel": "sms", "lead_time_h": 24},
        db=db,
    )
    assert rule_out["recipient"] == "+989***89"
    assert raw_phone not in rule_out["recipient"]

    # 3. Captured logs and API responses during alert evaluation must NOT contain raw phone number
    import json
    from app.services.agriculture.forecast import FakeForecastProvider
    with patch(
        "app.services.agriculture.forecast.FakeForecastProvider",
        lambda *args, **kwargs: FakeForecastProvider(base_tmin_c=-3.0, z_site_m=1200.0),
    ):
        with caplog.at_level(logging.INFO):
            eval_resp = await evaluate_alerts_endpoint(
                eval_in={"dry_run": True, "use_live_gee": False},
                db=db,
            )
    # Grep captured logs: raw phone number must be strictly absent
    assert raw_phone not in caplog.text

    # Grep API response: raw phone number must be strictly absent, masked number present
    eval_resp_str = json.dumps(eval_resp)
    assert raw_phone not in eval_resp_str
    assert "+989***89" in eval_resp_str

    # Database notification_log must store rule reference + masked recipient, never raw phone
    assert len(db_notification_logs) == 1
    log_record = db_notification_logs[0]
    assert log_record.alert_rule_id == rule_id
    assert log_record.recipient == "+989***89"
    assert raw_phone not in log_record.recipient
    assert raw_phone not in json.dumps(log_record.payload)


def test_concurrent_duplicate_alert_insertion_db_constraint(tmp_path):
    """Verify that database unique constraint enforces idempotency against concurrent duplicate alert inserts."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    from app.db.base import Base
    from app.db.models.frost import NotificationLog

    test_db = tmp_path / "idempotency_test.db"
    engine = create_engine(f"sqlite:///{test_db}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        # First insert succeeds
        log1 = NotificationLog(
            idempotency_key="orchard-uuid-1:2026-03-20:warning",
            recipient="+989123456789",
            channel="sms",
            payload={"msg": "first insert"},
            status="dry_run",
        )
        session.add(log1)
        session.commit()

        # Concurrent/duplicate insert with identical idempotency_key must be rejected by DB constraint
        log2 = NotificationLog(
            idempotency_key="orchard-uuid-1:2026-03-20:warning",
            recipient="+989123456789",
            channel="sms",
            payload={"msg": "concurrent second insert"},
            status="dry_run",
        )
        session.add(log2)
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.asyncio
async def test_evaluate_alerts_multiple_rules_per_orchard_different_recipients():
    """Verify that multiple alert rules on the same orchard (different recipient/channel) all dispatch."""
    from app.api.v1.agriculture import evaluate_alerts_endpoint
    from app.db.models.frost import Orchard, AlertRule, NotificationLog
    from app.services.agriculture.forecast import FakeForecastProvider

    orchard_id = uuid.uuid4()
    rule1_id = uuid.uuid4()
    rule2_id = uuid.uuid4()

    mock_orchard = Orchard(
        id=orchard_id,
        name="باغ پسته دوقلو",
        geometry=SAMPLE_POLYGON,
        crop="pistachio",
        default_phenology_stage="early_bloom",
        elevation=1200.0,
    )
    rule1 = AlertRule(
        id=rule1_id,
        orchard_id=orchard_id,
        recipient="+989121111111",
        channel="sms",
        lead_time_h=24,
        enabled=True,
        orchard=mock_orchard,
    )
    rule2 = AlertRule(
        id=rule2_id,
        orchard_id=orchard_id,
        recipient="owner@example.com",
        channel="email",
        lead_time_h=24,
        enabled=True,
        orchard=mock_orchard,
    )
    mock_orchard.alert_rules = [rule1, rule2]

    db_entries: list[NotificationLog] = []

    class MockDbSession:
        async def execute(self, stmt):
            stmt_str = str(stmt)
            mock_res = MagicMock()
            if "alert_rules" in stmt_str:
                mock_res.scalars.return_value.all.return_value = [rule1, rule2]
            elif "notification_log" in stmt_str:
                params = stmt.compile().params
                rule_id = next((v for k, v in params.items() if "alert_rule_id" in k), None)
                if rule_id is not None:
                    matched = [e for e in db_entries if e.alert_rule_id == rule_id]
                else:
                    matched = list(db_entries)
                mock_res.scalars.return_value.all.return_value = matched
            else:
                mock_res.scalars.return_value.all.return_value = []
            return mock_res

        def add(self, obj):
            db_entries.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    mock_db = MockDbSession()

    with patch(
        "app.services.agriculture.forecast.FakeForecastProvider",
        lambda *args, **kwargs: FakeForecastProvider(base_tmin_c=-1.0, z_site_m=1200.0),
    ):
        # 1. First evaluation: BOTH rules should dispatch (e.g. at moderate risk)!
        res1 = await evaluate_alerts_endpoint(
            eval_in={"dry_run": True, "use_live_gee": False},
            db=mock_db,
        )
        assert res1["evaluated_orchards"] == 1
        assert res1["evaluated_rules"] == 2
        # Must dispatch 2 notifications (one for SMS rule, one for Email rule)
        assert res1["dispatched_notifications"] == 2
        assert len(db_entries) == 2
        recipients = {entry.recipient for entry in db_entries}
        assert "+989***11" in recipients
        assert "ow***@example.com" in recipients
        assert "+989121111111" not in recipients
        assert "owner@example.com" not in recipients

        # 2. Second evaluation with identical forecast: neither rule should re-dispatch (idempotent)!
        res2 = await evaluate_alerts_endpoint(
            eval_in={"dry_run": True, "use_live_gee": False},
            db=mock_db,
        )
        assert res2["dispatched_notifications"] == 0
        assert len(db_entries) == 2

    # 3. Third evaluation with escalated risk (lower temperature -> severe): both rules should escalate!
    with patch(
        "app.services.agriculture.forecast.FakeForecastProvider",
        lambda *args, **kwargs: FakeForecastProvider(base_tmin_c=-6.0, z_site_m=1200.0),
    ):
        res3 = await evaluate_alerts_endpoint(
            eval_in={"dry_run": True, "use_live_gee": False},
            db=mock_db,
        )
        assert res3["dispatched_notifications"] == 2
        assert len(db_entries) == 4





