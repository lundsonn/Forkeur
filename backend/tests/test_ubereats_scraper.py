import pytest
from scrapers import ubereats
from scrapers.ubereats import _parse_section_hours, _minutes_to_hhmm


def test_minutes_to_hhmm():
    assert _minutes_to_hhmm(510) == "08:30"
    assert _minutes_to_hhmm(1170) == "19:30"
    assert _minutes_to_hhmm(0) == "00:00"
    assert _minutes_to_hhmm(1439) == "23:59"


def test_parse_section_hours_german():
    data = {
        "hours": [
            {"dayRange": "Sonntag", "sectionHours": [{"startTime": 510, "endTime": 690}]},
            {"dayRange": "Montag - Mittwoch", "sectionHours": [{"startTime": 510, "endTime": 1170}]},
            {"dayRange": "Donnerstag", "sectionHours": [{"startTime": 510, "endTime": 1140}]},
            {"dayRange": "Freitag - Samstag", "sectionHours": [{"startTime": 510, "endTime": 1170}]},
        ]
    }
    result = _parse_section_hours(data)
    assert result is not None
    assert result["sun"] == ["08:30", "11:30"]
    assert result["mon"] == ["08:30", "19:30"]
    assert result["tue"] == ["08:30", "19:30"]
    assert result["wed"] == ["08:30", "19:30"]
    assert result["thu"] == ["08:30", "19:00"]
    assert result["fri"] == ["08:30", "19:30"]
    assert result["sat"] == ["08:30", "19:30"]


def test_parse_section_hours_none_when_missing():
    assert _parse_section_hours({}) is None
    assert _parse_section_hours({"hours": []}) is None


def test_parse_section_hours_wrap_around():
    # e.g. "Vendredi - Dimanche" (Fri - Sun wraps around the week)
    data = {"hours": [{"dayRange": "Vendredi - Dimanche", "sectionHours": [{"startTime": 600, "endTime": 1200}]}]}
    result = _parse_section_hours(data)
    assert result is not None
    assert "fri" in result
    assert "sat" in result
    assert "sun" in result


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
