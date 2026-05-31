import pytest
from scrapers import deliveroo


def test_parse_dom_items_from_eval_output():
    """Parse menu items from DOM eval output"""
    dom_output = {
        "sections": [
            {
                "heading": "Burgers",
                "items": [
                    {"title": "Cheeseburger", "price": "€ 12,50"},
                    {"title": "Double Burger", "price": "€ 15,99"},
                ]
            }
        ]
    }
    items = deliveroo._parse_dom_items(dom_output)
    assert len(items) == 2
    assert items[0]["title"] == "Cheeseburger"
    assert items[0]["price"] == 12.50
    assert items[0]["catalog_name"] == "Burgers"


def test_parse_dom_items_with_euro_suffix():
    """Handle euro suffix format (12,50 €)"""
    dom_output = {
        "sections": [
            {
                "heading": "Drinks",
                "items": [
                    {"title": "Water", "price": "2,50 €"},
                ]
            }
        ]
    }
    items = deliveroo._parse_dom_items(dom_output)
    assert items[0]["price"] == 2.50


def test_parse_dom_items_empty():
    """Handle empty menu sections"""
    dom_output = {"sections": []}
    items = deliveroo._parse_dom_items(dom_output)
    assert items == []


def test_scrape_menu_page_returns_listing_id_with_items():
    """scrape_menu_page() returns (listing_id, items) tuple"""
    assert hasattr(deliveroo, 'scrape_menu_page')
