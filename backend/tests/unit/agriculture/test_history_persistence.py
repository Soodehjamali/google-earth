"""Unit and integration tests for Agricultural Analysis Persistent History (Phase P0-HISTORY).

Verifies:
1. Analysis persistence into PostgreSQL database.
2. Result data integrity and field correspondence between API and stored record.
3. Decoupled retrieval from history endpoint with ZERO calls to Earth Engine / executor.
4. Independent records for consecutive runs on the same orchard/field.
5. Idempotent replay preventing duplicate records on request retries with identical request_id.
6. Proper 404 / 400 error handling for invalid or missing IDs.
7. Single-record deletion without impacting other stored runs.
8. Recording and reporting failed or incomplete analysis states truthfully.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.models.analysis import Analysis
from app.db.models.location import Location
from app.db.session import get_db
from app.main import app
from app.schemas.agriculture import (
    AgriculturalAnalysisResponse,
    AgricultureAnalysisRequest,
    DomainSummaryResponse,
    SynthesisStatementResponse,
)
from app.services.agriculture.history_store import (
    compute_geometry_centroid_and_area,
    delete_analysis_history_item,
    get_analysis_history_item,
    get_analysis_history_list,
    record_analysis_completion,
    record_analysis_failure,
    record_analysis_start,
    sanitize_error_message,
)

SAMPLE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [54.01, 32.31],
            [54.02, 32.31],
            [54.02, 32.32],
            [54.01, 32.32],
            [54.01, 32.31],
        ]
    ],
}


@pytest.fixture
def mock_analysis_response():
    """Build a deterministic realistic analysis response for testing."""
    return AgriculturalAnalysisResponse(
        request_id=str(uuid.uuid4()),
        time_start="2026-05-01",
        time_end="2026-08-31",
        spatial_context="Ardakan Pistachio Orchard",
        generated_at="2026-09-01T10:00:00Z",
        overall_sufficiency="sufficient",
        available_domains=["vegetation", "water", "soil"],
        domains_with_data=["vegetation", "water", "soil"],
        domains_with_statements=["vegetation"],
        domain_summaries={
            "vegetation": DomainSummaryResponse(
                domain="vegetation",
                sufficiency="sufficient",
                pattern_type="stable_high",
                statements=[
                    SynthesisStatementResponse(
                        rule_id="V01",
                        domain="vegetation",
                        pattern="trend",
                        statement="پوشش تاجی مطلوب است",
                    )

                ],
            )
        },
    )


class TestOfflineGeometryMath:
    """Verify centroid and area calculation runs offline with zero GEE latency."""

    def test_point_geometry_centroid(self):
        point_geom = {"type": "Point", "coordinates": [54.015, 32.315]}
        lat, lng, area, g_type = compute_geometry_centroid_and_area(point_geom)
        assert lat == 32.315
        assert lng == 54.015
        assert area is None
        assert g_type == "Point"

    def test_polygon_geometry_centroid_and_area(self):
        lat, lng, area, g_type = compute_geometry_centroid_and_area(SAMPLE_POLYGON)
        assert lat is not None and 32.31 <= lat <= 32.32
        assert lng is not None and 54.01 <= lng <= 54.02
        assert area is not None and area > 0
        assert g_type == "Polygon"

    def test_unclosed_polygon_automatically_closes_and_computes(self):
        unclosed = {
            "type": "Polygon",
            "coordinates": [
                [
                    [54.01, 32.31],
                    [54.02, 32.31],
                    [54.02, 32.32],
                    [54.01, 32.32],
                ]
            ],
        }
        lat, lng, area, g_type = compute_geometry_centroid_and_area(unclosed)
        assert lat is not None and 32.31 <= lat <= 32.32
        assert lng is not None and 54.01 <= lng <= 54.02
        assert area is not None and area > 0
        assert g_type == "Polygon"

    def test_malformed_coordinates_fallback_safely(self):
        # Coordinates with too few points
        lat, lng, area, g_type = compute_geometry_centroid_and_area({"type": "Polygon", "coordinates": [[[54.01, 32.31]]]})
        assert lat is None and area is None and g_type == "Polygon"

        # Non-numeric or missing coordinates
        lat, lng, area, g_type = compute_geometry_centroid_and_area({"type": "Polygon", "coordinates": None})
        assert lat is None and area is None and g_type == "Polygon"

        # Point with out-of-range coordinates
        lat, lng, area, g_type = compute_geometry_centroid_and_area({"type": "Point", "coordinates": [250.0, 95.0]})
        assert lat is None and lng is None and g_type == "Point"


class TestErrorSanitization:
    """Verify secrets, passwords, and file paths are sanitized."""

    def test_sanitize_removes_passwords_and_paths(self):
        raw = "Connection failed: postgres:postgres123@localhost:5432 at C:\\Users\\Secret\\app.py"
        sanitized = sanitize_error_message(raw)
        assert "postgres123" not in sanitized
        assert "Secret" not in sanitized


import pytest_asyncio

@pytest_asyncio.fixture
async def async_db_session():
    """Shared database session fixture tied to the current test event loop."""
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.connect() as conn:
            pass
    except Exception as exc:
        pytest.skip(f"Database not available or authentication failed: {exc}")

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        async def _override_get_db():
            yield session
        app.dependency_overrides[get_db] = _override_get_db
        try:
            yield session
        finally:
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()



@pytest.mark.asyncio
class TestHistoryPersistenceIntegration:
    """Integration tests with the live or configured database."""

    async def test_record_start_completion_and_retrieval(self, async_db_session, mock_analysis_response):
        """Prove that analysis start and completion persist into PostgreSQL and can be retrieved."""
        session = async_db_session
        test_analysis_id = uuid.uuid4()
        req = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2026-05-01",
            end_date="2026-08-31",
            name="باغ پسته احمدآباد اردکان",
            request_id=str(test_analysis_id),
        )

        # 1. Start
        analysis, is_replay = await record_analysis_start(session, req, test_analysis_id)
        await session.commit()
        assert is_replay is False
        assert analysis.status == "running"
        assert analysis.location_id is not None

        # 2. Complete
        mock_analysis_response.request_id = str(test_analysis_id)
        await record_analysis_completion(session, test_analysis_id, mock_analysis_response)

        # 3. Retrieve
        retrieved = await get_analysis_history_item(session, test_analysis_id)
        assert retrieved is not None
        assert retrieved.status == "completed"
        assert retrieved.result_data is not None
        assert retrieved.result_data["request_id"] == str(test_analysis_id)
        assert retrieved.result_data["overall_sufficiency"] == "sufficient"
        assert retrieved.location.name == "باغ پسته احمدآباد اردکان"

        # 4. List
        history_list = await get_analysis_history_list(session, skip=0, limit=10)
        assert history_list.total >= 1
        found = next((item for item in history_list.items if item.id == test_analysis_id), None)
        assert found is not None
        assert found.location_name == "باغ پسته احمدآباد اردکان"
        assert found.status == "completed"
        assert found.overall_sufficiency == "sufficient"

        # 5. Idempotent replay check: starting with the same completed target_id returns existing record
        replay_rec, is_replay2 = await record_analysis_start(session, req, test_analysis_id)
        assert is_replay2 is True
        assert replay_rec.id == test_analysis_id

        # 6. Delete
        deleted = await delete_analysis_history_item(session, test_analysis_id)
        assert deleted is True

        # Verify deletion
        deleted_check = await get_analysis_history_item(session, test_analysis_id)
        assert deleted_check is None

    async def test_consecutive_runs_create_distinct_records(self, async_db_session, mock_analysis_response):
        """Two intentional runs on the same orchard must produce two independent history records."""
        session = async_db_session
        run1_id = uuid.uuid4()
        run2_id = uuid.uuid4()

        req1 = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2025-05-01",
            end_date="2025-08-31",
            name="باغ آزمایش مستقل",
            request_id=str(run1_id),
        )
        req2 = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2026-05-01",
            end_date="2026-08-31",
            name="باغ آزمایش مستقل",
            request_id=str(run2_id),
        )

        a1, _ = await record_analysis_start(session, req1, run1_id)
        a2, _ = await record_analysis_start(session, req2, run2_id)
        await session.commit()

        assert a1.id != a2.id
        assert str(a1.id) == str(run1_id)
        assert str(a2.id) == str(run2_id)

        # Cleanup
        await delete_analysis_history_item(session, run1_id)
        await delete_analysis_history_item(session, run2_id)

    async def test_retry_failed_analysis_resets_status_and_clears_error(self, async_db_session, mock_analysis_response):
        """Retrying a previously failed request_id must safely transition back to running."""
        session = async_db_session
        test_id = uuid.uuid4()
        req = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2026-05-01",
            end_date="2026-08-31",
            name="باغ تست آزمون مجدد",
            request_id=str(test_id),
        )

        # 1. Start and fail
        await record_analysis_start(session, req, test_id)
        await record_analysis_failure(session, test_id, "Transient network timeout to Earth Engine")

        rec_failed = await get_analysis_history_item(session, test_id)
        assert rec_failed.status == "failed"
        assert "Transient network timeout" in (rec_failed.error_message or "")

        # 2. Retry with same request_id
        retried_rec, is_completed = await record_analysis_start(session, req, test_id)
        assert is_completed is False
        assert retried_rec.status == "running"
        assert retried_rec.error_message is None
        assert retried_rec.completed_at is None

        # 3. Complete retry
        mock_analysis_response.request_id = str(test_id)
        await record_analysis_completion(session, test_id, mock_analysis_response)

        rec_done = await get_analysis_history_item(session, test_id)
        assert rec_done.status == "completed"
        assert rec_done.error_message is None

        # Cleanup
        await delete_analysis_history_item(session, test_id)

    async def test_persistence_across_completely_closed_session(self, async_db_session, mock_analysis_response):
        """Stage 4 Requirement: Persist analysis, close session, open brand new connection, verify data."""
        engine = create_async_engine(settings.DATABASE_URL)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        test_id = uuid.uuid4()
        req = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2026-05-01",
            end_date="2026-08-31",
            name="باغ ماندگاری مستقل سشن",
            request_id=str(test_id),
        )

        # Session 1: Create and complete
        async with session_factory() as session1:
            await record_analysis_start(session1, req, test_id)
            mock_analysis_response.request_id = str(test_id)
            await record_analysis_completion(session1, test_id, mock_analysis_response)
        # Session 1 is now explicitly closed and disposed

        # Session 2: Fresh independent connection to PostgreSQL
        async with session_factory() as session2:
            retrieved = await get_analysis_history_item(session2, test_id)
            assert retrieved is not None
            assert retrieved.id == test_id
            assert retrieved.status == "completed"
            assert retrieved.result_data["request_id"] == str(test_id)
            assert retrieved.result_data["overall_sufficiency"] == "sufficient"
            assert "vegetation" in retrieved.result_data["domain_summaries"]
            assert retrieved.location.name == "باغ ماندگاری مستقل سشن"

            # Cleanup only this test record
            await delete_analysis_history_item(session2, test_id)

        await engine.dispose()


@pytest.mark.asyncio
class TestHistoryApiEndpointsAndNoGeeReexecution:
    """Verify API endpoints and explicitly prove zero GEE re-execution on history retrieval."""

    async def test_get_history_detail_never_executes_gee(self, async_db_session, mock_analysis_response):
        """Retrieving an existing analysis from /api/v1/agriculture/history/{id}

        must NEVER call Earth Engine, execute_metrics, or synthesis engine.
        """
        session = async_db_session
        test_id = uuid.uuid4()
        req = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2026-05-01",
            end_date="2026-08-31",
            name="باغ تست عدم اجرای مجدد GEE",
            request_id=str(test_id),
        )

        await record_analysis_start(session, req, test_id)
        mock_analysis_response.request_id = str(test_id)
        await record_analysis_completion(session, test_id, mock_analysis_response)

        try:
            # We patch execute_metrics and create_ee_geometry with Spies/Mocks that assert 0 calls
            with patch("app.services.agriculture.executor.execute_metrics") as mock_exec, \
                 patch("app.utils.geometry.create_ee_geometry") as mock_ee_geom, \
                 patch("app.services.agriculture.synthesis.SynthesisEngine.synthesise") as mock_synth:

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(f"/api/v1/agriculture/history/{test_id}")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["request_id"] == str(test_id)
                    assert data["overall_sufficiency"] == "sufficient"
                    assert "vegetation" in data["domain_summaries"]

                    # PROOF OF ZERO GEE / EXECUTOR RE-EXECUTION
                    assert mock_exec.call_count == 0, "execute_metrics was unexpectedly called!"
                    assert mock_ee_geom.call_count == 0, "create_ee_geometry was unexpectedly called!"
                    assert mock_synth.call_count == 0, "SynthesisEngine was unexpectedly called!"

        finally:
            await delete_analysis_history_item(session, test_id)

    async def test_get_nonexistent_history_returns_404(self, async_db_session):
        """Nonexistent analysis ID must return standard 404."""
        nonexistent_id = uuid.uuid4()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/agriculture/history/{nonexistent_id}")
            assert resp.status_code == 404

    async def test_delete_history_item_via_api(self, async_db_session, mock_analysis_response):
        """Deleting an analysis via DELETE /api/v1/agriculture/history/{id} works properly."""
        session = async_db_session
        test_id = uuid.uuid4()
        req = AgricultureAnalysisRequest(
            geometry=SAMPLE_POLYGON,
            start_date="2026-05-01",
            end_date="2026-08-31",
            request_id=str(test_id),
        )

        await record_analysis_start(session, req, test_id)
        await record_analysis_completion(session, test_id, mock_analysis_response)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            del_resp = await client.delete(f"/api/v1/agriculture/history/{test_id}")
            assert del_resp.status_code == 200
            assert del_resp.json()["deleted"] is True

            # Subsequent fetch should be 404
            get_resp = await client.get(f"/api/v1/agriculture/history/{test_id}")
            assert get_resp.status_code == 404

