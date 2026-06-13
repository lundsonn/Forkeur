import os
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-data-router")
os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")

from routers.data import router


def _make_app():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


_SAMPLE_RESTAURANTS = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Pizza Palace",
        "slug": "pizza-palace",
        "cuisine": "Italian",
        "neighborhood": "Ixelles",
    }
]

_SAMPLE_MENU_ITEMS = [
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "listing_id": "00000000-0000-0000-0000-000000000003",
        "title": "Margherita",
        "price": 8.99,
        "catalog_name": "Pizzas",
        "image_url": None,
        "description": "Classic pizza",
    }
]


def test_list_restaurants_returns_200(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = _SAMPLE_RESTAURANTS
        client = TestClient(_make_app())
        res = client.get("/api/data/restaurants", headers=auth_headers)
    assert res.status_code == 200


def test_list_restaurants_default_limit_100(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/restaurants", headers=auth_headers)
        mock_db.get_restaurants.assert_called_once_with(limit=100, offset=0, search=None)


def test_list_restaurants_accepts_limit_and_offset(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/restaurants?limit=10&offset=20", headers=auth_headers)
        mock_db.get_restaurants.assert_called_once_with(limit=10, offset=20, search=None)


def test_list_restaurants_accepts_search(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/restaurants?search=pizza", headers=auth_headers)
        mock_db.get_restaurants.assert_called_once_with(limit=100, offset=0, search="pizza")


def test_list_menu_items_returns_200(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_menu_items.return_value = _SAMPLE_MENU_ITEMS
        client = TestClient(_make_app())
        res = client.get("/api/data/menu-items/listing-1", headers=auth_headers)
    assert res.status_code == 200


def test_list_menu_items_calls_db_with_listing_id(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_menu_items.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/menu-items/listing-abc", headers=auth_headers)
        mock_db.get_menu_items.assert_called_once_with("listing-abc")


def test_list_menu_items_empty_returns_empty_list(auth_headers):
    with patch("routers.data.db") as mock_db:
        mock_db.get_menu_items.return_value = []
        client = TestClient(_make_app())
        res = client.get("/api/data/menu-items/unknown", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []
