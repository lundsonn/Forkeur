import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routers import scrapers
from routers.auth_router import require_auth
from models import ScraperConfig


@pytest.fixture(autouse=True)
def clear_running_state():
    """Reset module-level _running/_tasks state between tests."""
    scrapers._running.clear()
    scrapers._tasks.clear()
    yield
    scrapers._running.clear()
    scrapers._tasks.clear()


def _make_app():
    """Create a minimal test app with auth bypassed."""
    app = FastAPI()
    app.include_router(scrapers.router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: "test-admin"
    return app


def test_trigger_run_accepts_body_with_scrape_menus():
    """Test POST /api/scrapers/{platform}/run accepts body with scrape_menus and max_menus"""
    app = _make_app()
    client = TestClient(app)

    with patch("routers.scrapers.db") as mock_db, \
         patch("routers.scrapers.ws_mod") as mock_ws, \
         patch("routers.scrapers.SCRAPERS") as mock_scrapers, \
         patch("routers.scrapers.asyncio") as mock_asyncio:

        mock_db.create_run.return_value = "run-123"
        mock_ws.make_log_fn.return_value = lambda x: None
        mock_scrapers.__contains__.return_value = True
        mock_scrapers.__getitem__.return_value = MagicMock()

        response = client.post(
            "/api/scrapers/ubereats/run",
            json={"scrape_menus": True, "max_menus": 5}
        )
        # Status should be 200 (async task started)
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["run_id"] == "run-123"


def test_trigger_run_without_body_uses_defaults():
    """Test POST /api/scrapers/{platform}/run without body uses RunTriggerIn defaults"""
    app = _make_app()
    client = TestClient(app)

    with patch("routers.scrapers.db") as mock_db, \
         patch("routers.scrapers.ws_mod") as mock_ws, \
         patch("routers.scrapers.SCRAPERS") as mock_scrapers, \
         patch("routers.scrapers.asyncio") as mock_asyncio:

        mock_db.create_run.return_value = "run-456"
        mock_ws.make_log_fn.return_value = lambda x: None
        mock_scrapers.__contains__.return_value = True
        mock_scrapers.__getitem__.return_value = MagicMock()

        response = client.post("/api/scrapers/ubereats/run")
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["run_id"] == "run-456"


def test_trigger_run_rejects_unknown_platform():
    """Test POST /api/scrapers/{platform}/run rejects unknown platforms"""
    app = _make_app()
    client = TestClient(app)

    response = client.post("/api/scrapers/unknown_platform/run")
    assert response.status_code == 404


def test_health_check_uses_batch_query():
    """health_check calls get_last_successful_run_batch (single query) not 3x get_last_successful_run."""
    app = _make_app()
    client = TestClient(app)

    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    batch_result = {
        "ubereats":  {"platform": "ubereats",  "status": "success", "started_at": recent, "finished_at": recent, "records_saved": 10},
        "deliveroo": {"platform": "deliveroo", "status": "success", "started_at": recent, "finished_at": recent, "records_saved": 8},
        "takeaway":  {"platform": "takeaway",  "status": "success", "started_at": recent, "finished_at": recent, "records_saved": 5},
    }

    with patch("routers.scrapers.db") as mock_db:
        mock_db.get_last_successful_run_batch.return_value = batch_result

        response = client.get("/api/scrapers/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["platforms"]["ubereats"] == "ok"
        assert data["platforms"]["deliveroo"] == "ok"
        assert data["platforms"]["takeaway"] == "ok"
        # Must use the batch function, not the single-platform one
        mock_db.get_last_successful_run_batch.assert_called_once_with(
            ["ubereats", "deliveroo", "takeaway"]
        )
        mock_db.get_last_successful_run.assert_not_called()


def test_health_check_never_run():
    """health_check returns never_run for platforms with no successful run."""
    app = _make_app()
    client = TestClient(app)

    with patch("routers.scrapers.db") as mock_db:
        mock_db.get_last_successful_run_batch.return_value = {}

        response = client.get("/api/scrapers/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert all(v == "never_run" for v in data["platforms"].values())


def test_health_check_stale():
    """health_check returns stale for platforms whose last run is older than 25 hours."""
    app = _make_app()
    client = TestClient(app)

    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()

    with patch("routers.scrapers.db") as mock_db:
        mock_db.get_last_successful_run_batch.return_value = {
            "ubereats":  {"platform": "ubereats",  "status": "success", "started_at": old, "finished_at": old, "records_saved": 0},
            "deliveroo": {"platform": "deliveroo", "status": "success", "started_at": old, "finished_at": old, "records_saved": 0},
            "takeaway":  {"platform": "takeaway",  "status": "success", "started_at": old, "finished_at": old, "records_saved": 0},
        }

        response = client.get("/api/scrapers/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert all(v == "stale" for v in data["platforms"].values())
