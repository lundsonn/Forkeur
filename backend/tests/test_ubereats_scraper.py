import pytest
from scrapers import ubereats


def test_parse_ue_menu_from_getsectionfeedv1():
    """Parse menu items from getSectionFeedV1 JSON response"""
    json_resp = {
        "catalogSectionsMap": {
            "section_1": {
                "catalogItems": [
                    {"title": "Burger", "price": 1199, "priceType": "FIXED"},
                    {"title": "Fries", "price": 599, "priceType": "FIXED"},
                ]
            }
        }
    }
    items = ubereats._parse_ue_menu(json_resp, catalog_name="Main")
    assert len(items) == 2
    assert items[0]["title"] == "Burger"
    assert items[0]["price"] == 11.99  # 1199 cents


def test_parse_ue_menu_empty_catalog():
    """Handle empty menu sections"""
    json_resp = {"catalogSectionsMap": {}}
    items = ubereats._parse_ue_menu(json_resp, catalog_name="Main")
    assert items == []


def test_parse_ue_menu_nested_structure():
    """Parse items from nested catalogSectionsMap with multiple sections"""
    json_resp = {
        "data": {
            "catalogSectionsMap": {
                "uuid_1": [
                    {
                        "payload": {
                            "standardItemsPayload": {
                                "title": {"text": "Appetizers"},
                                "catalogItems": [
                                    {"title": "Wings", "price": 899},
                                    {"title": "Nachos", "price": 799},
                                ]
                            }
                        }
                    }
                ]
            }
        }
    }
    items = ubereats._parse_ue_menu(json_resp, catalog_name="Starters")
    assert len(items) == 2
    assert items[0]["title"] == "Wings"
    assert items[1]["price"] == 7.99


def test_parse_ue_menu_with_none_prices():
    """Handle items with missing prices"""
    json_resp = {
        "catalogSectionsMap": {
            "section_1": {
                "catalogItems": [
                    {"title": "Item A", "price": 1000},
                    {"title": "Item B"},  # no price
                ]
            }
        }
    }
    items = ubereats._parse_ue_menu(json_resp, catalog_name="Main")
    assert len(items) == 2
    assert items[0]["price"] == 10.0
    assert items[1]["price"] is None


def test_parse_ue_menu_preserves_catalog_name():
    """Catalog name is included in each item"""
    json_resp = {
        "catalogSectionsMap": {
            "section_1": {
                "catalogItems": [
                    {"title": "Burger", "price": 1199},
                ]
            }
        }
    }
    items = ubereats._parse_ue_menu(json_resp, catalog_name="Main Menu")
    assert items[0]["catalog_name"] == "Main Menu"
