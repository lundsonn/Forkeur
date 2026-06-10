import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pw")
    import pgpool
    pgpool.close_pool()
    import importlib
    import main
    importlib.reload(main)
    yield TestClient(main.app)
    pgpool.close_pool()


def test_public_restaurants_is_unauthenticated(client):
    r = client.get("/api/public/restaurants")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_public_detail_404(client):
    r = client.get("/api/public/restaurants/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
