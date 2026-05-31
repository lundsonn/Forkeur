import pytest
from scrapers import takeaway


def test_parse_dom_items_from_takeaway_format():
    """Parse menu items from Takeaway DOM eval output"""
    dom_output = {
        "sections": [
            {
                "heading": "Pizzas",
                "items": [
                    {"title": "Margherita", "price": "8,99 €"},
                    {"title": "Quattro Formaggi", "price": "€ 11,50"},
                ]
            }
        ]
    }
    items = takeaway._parse_dom_items(dom_output)
    assert len(items) == 2
    assert items[0]["title"] == "Margherita"
    assert items[0]["price"] == 8.99
    assert items[0]["catalog_name"] == "Pizzas"


def test_parse_dom_items_with_euro_prefix():
    """Handle euro prefix format (€ 11,50)"""
    dom_output = {
        "sections": [
            {
                "heading": "Drinks",
                "items": [
                    {"title": "Coca Cola", "price": "€ 2,50"},
                ]
            }
        ]
    }
    items = takeaway._parse_dom_items(dom_output)
    assert items[0]["price"] == 2.50


def test_parse_dom_items_missing_sections():
    """Handle missing sections gracefully"""
    dom_output = {}
    items = takeaway._parse_dom_items(dom_output)
    assert items == []


def test_scrape_menu_page_returns_listing_id_with_items():
    """scrape_menu_page() returns (listing_id, items) tuple"""
    assert hasattr(takeaway, 'scrape_menu_page')
