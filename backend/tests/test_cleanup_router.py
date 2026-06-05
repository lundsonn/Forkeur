import os
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-cleanup")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")

import auth
from routers.cleanup import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _valid_token() -> str:
    return auth.create_token()


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def test_no_auth_returns_401():
    client = TestClient(_make_app())
    res = client.post("/api/cleanup/stale-listings")
    assert res.status_code == 401


def test_invalid_token_returns_401():
    client = TestClient(_make_app())
    res = client.post(
        "/api/cleanup/stale-listings",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_auth_calls_delete_and_returns_result():
    with patch("routers.cleanup.db") as mock_db:
        mock_db.delete_stale_listings.return_value = 5
        client = TestClient(_make_app())
        res = client.post(
            "/api/cleanup/stale-listings",
            headers={"Authorization": f"Bearer {_valid_token()}"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] == 5
    assert "5" in body["message"]
    mock_db.delete_stale_listings.assert_called_once_with(days=30)


def test_default_days_is_30():
    with patch("routers.cleanup.db") as mock_db:
        mock_db.delete_stale_listings.return_value = 0
        client = TestClient(_make_app())
        client.post(
            "/api/cleanup/stale-listings",
            headers={"Authorization": f"Bearer {_valid_token()}"},
        )
    mock_db.delete_stale_listings.assert_called_once_with(days=30)


def test_custom_days_param_is_forwarded():
    with patch("routers.cleanup.db") as mock_db:
        mock_db.delete_stale_listings.return_value = 3
        client = TestClient(_make_app())
        res = client.post(
            "/api/cleanup/stale-listings?days=7",
            headers={"Authorization": f"Bearer {_valid_token()}"},
        )
    assert res.status_code == 200
    mock_db.delete_stale_listings.assert_called_once_with(days=7)
    assert "7" in res.json()["message"]


def test_zero_deletions_returns_clean_message():
    with patch("routers.cleanup.db") as mock_db:
        mock_db.delete_stale_listings.return_value = 0
        client = TestClient(_make_app())
        res = client.post(
            "/api/cleanup/stale-listings",
            headers={"Authorization": f"Bearer {_valid_token()}"},
        )
    assert res.status_code == 200
    assert res.json()["deleted"] == 0
