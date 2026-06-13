import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-metrics")

from routers.metrics import router


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


class _FakePool:
    def get_stats(self):
        return {
            "pool_size": 2,
            "pool_available": 2,
            "requests_waiting": 0,
        }


def _fake_fetchone(sql, params=None):
    return {"?column?": 1}


def _fake_fetchall(sql, params=None):
    # Latest run per platform — used by the "scrapers" section.
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    return [
        {
            "platform": "ubereats",
            "status": "success",
            "started_at": started,
            "finished_at": started + timedelta(minutes=5),
        }
    ]


def _patches():
    return (
        patch("pgpool.fetchone", _fake_fetchone),
        patch("pgpool.fetchall", _fake_fetchall),
        patch("pgpool.get_pool", lambda: _FakePool()),
    )


def test_health_returns_200_with_expected_keys(auth_headers):
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        client = TestClient(_make_app())
        res = client.get("/api/metrics/health", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) >= {"db", "pool", "migrations", "scrapers"}


def test_health_sections_populated(auth_headers):
    p1, p2, p3 = _patches()
    # compute_pending_via_pool reads schema_migrations via fetchall; patch the
    # migrate helper so we don't depend on the real migrations dir / DB.
    with p1, p2, p3, patch(
        "ops.migrate.compute_pending_via_pool", return_value=[]
    ):
        client = TestClient(_make_app())
        res = client.get("/api/metrics/health", headers=auth_headers)

    body = res.json()
    assert body["db"] == {"ok": True}
    assert body["pool"]["requests_waiting"] == 0
    assert body["migrations"] == {"pending": [], "count": 0}
    assert isinstance(body["scrapers"], list)
    assert body["scrapers"][0]["platform"] == "ubereats"
    assert body["scrapers"][0]["age_seconds"] > 0


def test_health_requires_auth():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        client = TestClient(_make_app())
        res = client.get("/api/metrics/health")
    assert res.status_code == 401


def test_health_db_section_degrades_on_error(auth_headers):
    def _boom(sql, params=None):
        raise RuntimeError("connection refused")

    with patch("pgpool.fetchone", _boom), patch(
        "pgpool.fetchall", _fake_fetchall
    ), patch("pgpool.get_pool", lambda: _FakePool()), patch(
        "ops.migrate.compute_pending_via_pool", return_value=[]
    ):
        client = TestClient(_make_app())
        res = client.get("/api/metrics/health", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["db"]["ok"] is False
    assert "connection refused" in body["db"]["error"]
