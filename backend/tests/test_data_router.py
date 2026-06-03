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
        "id": "r1",
        "name": "Pizza Palace",
        "platform": "uber_eats",
        "url": "https://ubereats.com/pizza",
        "delivery_fee": 1.99,
        "min_order": 10.0,
        "eta_min": 20,
        "eta_max": 35,
        "rating": 4.5,
    }
]

_SAMPLE_MENU_ITEMS = [
    {
        "id": "m1",
        "listing_id": "listing-1",
        "title": "Margherita",
        "price": 8.99,
        "catalog_name": "Pizzas",
        "image_url": None,
        "description": "Classic pizza",
    }
]


def test_list_restaurants_returns_200():
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = _SAMPLE_RESTAURANTS
        client = TestClient(_make_app())
        res = client.get("/api/data/restaurants")
    assert res.status_code == 200


def test_list_restaurants_default_limit_100():
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/restaurants")
        mock_db.get_restaurants.assert_called_once_with(limit=100, offset=0, search=None)


def test_list_restaurants_accepts_limit_and_offset():
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/restaurants?limit=10&offset=20")
        mock_db.get_restaurants.assert_called_once_with(limit=10, offset=20, search=None)


def test_list_restaurants_accepts_search():
    with patch("routers.data.db") as mock_db:
        mock_db.get_restaurants.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/restaurants?search=pizza")
        mock_db.get_restaurants.assert_called_once_with(limit=100, offset=0, search="pizza")


def test_list_menu_items_returns_200():
    with patch("routers.data.db") as mock_db:
        mock_db.get_menu_items.return_value = _SAMPLE_MENU_ITEMS
        client = TestClient(_make_app())
        res = client.get("/api/data/menu-items/listing-1")
    assert res.status_code == 200


def test_list_menu_items_calls_db_with_listing_id():
    with patch("routers.data.db") as mock_db:
        mock_db.get_menu_items.return_value = []
        client = TestClient(_make_app())
        client.get("/api/data/menu-items/listing-abc")
        mock_db.get_menu_items.assert_called_once_with("listing-abc")


def test_list_menu_items_empty_returns_empty_list():
    with patch("routers.data.db") as mock_db:
        mock_db.get_menu_items.return_value = []
        client = TestClient(_make_app())
        res = client.get("/api/data/menu-items/unknown")
    assert res.status_code == 200
    assert res.json() == []
