import pytest
from unittest.mock import patch, MagicMock, call, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routers import scrapers
from models import ScraperConfig


def test_trigger_run_accepts_body_with_scrape_menus():
    """Test POST /api/scrapers/{platform}/run accepts body with scrape_menus and max_menus"""
    # Create minimal app without full lifespan
    app = FastAPI()
    app.include_router(scrapers.router, prefix="/api")
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
    # Create minimal app without full lifespan
    app = FastAPI()
    app.include_router(scrapers.router, prefix="/api")
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
    app = FastAPI()
    app.include_router(scrapers.router, prefix="/api")
    client = TestClient(app)

    response = client.post("/api/scrapers/unknown_platform/run")
    assert response.status_code == 404
