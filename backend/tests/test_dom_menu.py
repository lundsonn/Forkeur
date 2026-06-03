"""
Tests for dom_menu generic extractor (pure-Python, no Playwright).
Only the _validate_items helper and JSON-LD extraction logic are tested here
since the Playwright-dependent scrape_url requires a real browser.
"""
from __future__ import annotations

import pytest
from scrapers.dom_menu.generic import _validate_items
from scrapers.dom_menu.sites import get_adapter, _REGISTRY


# ── _validate_items ───────────────────────────────────────────────────────────

class TestValidateItems:
    def test_valid_item_passes(self):
        items = _validate_items([
            {"title": "Burger", "price": 12.50, "catalog_name": "Mains"}
        ])
        assert len(items) == 1
        assert items[0]["title"] == "Burger"
        assert items[0]["price"] == pytest.approx(12.50)

    def test_title_too_short_skipped(self):
        assert _validate_items([{"title": "AB", "price": 5.0}]) == []

    def test_title_too_long_skipped(self):
        assert _validate_items([{"title": "x" * 121, "price": 5.0}]) == []

    def test_price_below_range_skipped(self):
        assert _validate_items([{"title": "Item", "price": 0.50}]) == []

    def test_price_above_range_skipped(self):
        assert _validate_items([{"title": "Item", "price": 250.0}]) == []

    def test_noise_title_skipped(self):
        assert _validate_items([{"title": "Frais de livraison", "price": 2.50}]) == []
        assert _validate_items([{"title": "Delivery fee", "price": 2.50}]) == []
        assert _validate_items([{"title": "Total", "price": 25.00}]) == []

    def test_duplicate_deduped(self):
        items = _validate_items([
            {"title": "Pizza", "price": 10.0},
            {"title": "Pizza", "price": 10.0},
        ])
        assert len(items) == 1

    def test_same_title_different_price_both_kept(self):
        items = _validate_items([
            {"title": "Pizza", "price": 10.0},
            {"title": "Pizza", "price": 12.0},
        ])
        assert len(items) == 2

    def test_price_rounded_to_2dp(self):
        items = _validate_items([{"title": "Item", "price": 9.999}])
        assert items[0]["price"] == pytest.approx(10.0)

    def test_none_description_set_to_none(self):
        items = _validate_items([{"title": "Item", "price": 5.0, "description": None}])
        assert items[0]["description"] is None

    def test_empty_description_set_to_none(self):
        items = _validate_items([{"title": "Item", "price": 5.0, "description": ""}])
        assert items[0]["description"] is None

    def test_catalog_name_defaults_to_menu(self):
        items = _validate_items([{"title": "Item", "price": 5.0, "catalog_name": None}])
        assert items[0]["catalog_name"] == "Menu"

    def test_missing_price_skipped(self):
        assert _validate_items([{"title": "Item"}]) == []


# ── sites registry ────────────────────────────────────────────────────────────

class TestSiteRegistry:
    def test_empty_registry_returns_none(self):
        assert get_adapter("www.somerestaurant.be") is None

    def test_registered_domain_matched(self):
        sentinel = object()
        _REGISTRY["testsite.be"] = sentinel
        try:
            assert get_adapter("www.testsite.be") is sentinel
            assert get_adapter("TESTSITE.BE") is sentinel
        finally:
            del _REGISTRY["testsite.be"]

    def test_partial_domain_match(self):
        sentinel = object()
        _REGISTRY["myplace.be"] = sentinel
        try:
            assert get_adapter("www.myplace.be") is sentinel
        finally:
            del _REGISTRY["myplace.be"]

    def test_non_matching_domain_returns_none(self):
        sentinel = object()
        _REGISTRY["specific.be"] = sentinel
        try:
            assert get_adapter("other.be") is None
        finally:
            del _REGISTRY["specific.be"]
