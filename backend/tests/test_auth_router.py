import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-auth-router")
os.environ.setdefault("ADMIN_PASSWORD", "correct-password")

from routers.auth_router import router
import auth


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


client = TestClient(_make_app())


def test_login_correct_password_returns_token():
    res = client.post("/api/auth/login", json={"password": "correct-password"})
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert auth.verify_token(data["token"])


def test_login_wrong_password_returns_401():
    res = client.post("/api/auth/login", json={"password": "wrong-password"})
    assert res.status_code == 401


def test_login_empty_password_returns_401():
    res = client.post("/api/auth/login", json={"password": ""})
    assert res.status_code == 401


def test_login_missing_body_returns_422():
    res = client.post("/api/auth/login", json={})
    assert res.status_code == 422


def test_login_no_admin_password_configured_returns_500():
    original = os.environ.pop("ADMIN_PASSWORD")
    try:
        app = FastAPI()
        app.include_router(router, prefix="/api")
        c = TestClient(app, raise_server_exceptions=False)
        res = c.post("/api/auth/login", json={"password": "anything"})
        assert res.status_code == 500
    finally:
        os.environ["ADMIN_PASSWORD"] = original
