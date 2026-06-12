import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routers import claims as claims_router

_VALID_UUID = "123e4567-e89b-12d3-a456-426614174000"


def _make_app():
    app = FastAPI()
    app.include_router(claims_router.router, prefix="/api")
    return app


def test_post_claim_returns_201():
    with patch("routers.claims.db") as mock_db:
        mock_db.insert_claim.return_value = "claim-xyz"
        client = TestClient(_make_app())
        res = client.post("/api/claims", json={
            "restaurant_id": _VALID_UUID,
            "owner_email": "owner@example.com",
            "direct_order_url": "https://myrest.com/order",
        })
    assert res.status_code == 201
    assert res.json()["claim_id"] == "claim-xyz"


def test_post_claim_rejects_invalid_email():
    client = TestClient(_make_app())
    res = client.post("/api/claims", json={
        "restaurant_id": _VALID_UUID,
        "owner_email": "not-an-email",
        "direct_order_url": "https://myrest.com/order",
    })
    assert res.status_code == 422


def test_post_claim_rejects_invalid_url():
    client = TestClient(_make_app())
    res = client.post("/api/claims", json={
        "restaurant_id": _VALID_UUID,
        "owner_email": "owner@example.com",
        "direct_order_url": "not-a-url",
    })
    assert res.status_code == 422


def test_get_claims_returns_list(auth_headers):
    with patch("routers.claims.db") as mock_db:
        mock_db.get_claims.return_value = [
            {"id": "c1", "restaurant_id": _VALID_UUID, "owner_email": "a@b.com",
             "direct_order_url": "https://a.com", "verified": False}
        ]
        client = TestClient(_make_app())
        res = client.get("/api/claims", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_approve_claim_returns_200(auth_headers):
    with patch("routers.claims.db") as mock_db:
        mock_db.approve_claim.return_value = None
        client = TestClient(_make_app())
        res = client.post("/api/claims/c1/approve", headers=auth_headers)
    assert res.status_code == 200
    mock_db.approve_claim.assert_called_once_with("c1")


def test_reject_claim_returns_200(auth_headers):
    with patch("routers.claims.db") as mock_db:
        mock_db.reject_claim.return_value = None
        client = TestClient(_make_app())
        res = client.post("/api/claims/c1/reject", headers=auth_headers)
    assert res.status_code == 200
    mock_db.reject_claim.assert_called_once_with("c1")


def test_get_claims_with_verified_filter(auth_headers):
    with patch("routers.claims.db") as mock_db:
        mock_db.get_claims.return_value = []
        client = TestClient(_make_app())
        res = client.get("/api/claims?verified=false", headers=auth_headers)
    assert res.status_code == 200
    mock_db.get_claims.assert_called_once_with(verified=False)


def test_post_claim_rejects_invalid_restaurant_id():
    client = TestClient(_make_app())
    res = client.post("/api/claims", json={
        "restaurant_id": "not-a-uuid",
        "owner_email": "owner@example.com",
        "direct_order_url": "https://myrest.com/order",
    })
    assert res.status_code == 422
