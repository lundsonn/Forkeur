"""
Tests for backend/scrapers/direct_menu.py

All HTTP calls are mocked — no live network access.
Fixture data lives in tests/fixtures/*.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scrapers.direct_menu import (
    _detect_adapter,
    _extract_piki_slug,
    _extract_sq_menu_code,
    _parse_odoo_items,
    _parse_piki_items,
    _parse_sq_menu_items,
    fetch_items,
    fetch_odoo_pos,
    fetch_piki_app,
    fetch_sq_menu,
    run,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a minimal httpx.Response mock."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    if json_data is not None:
        mock.json.return_value = json_data
    if raise_exc is not None:
        mock.json.side_effect = raise_exc
    return mock


# ---------------------------------------------------------------------------
# _detect_adapter
# ---------------------------------------------------------------------------

class TestDetectAdapter:
    def test_sq_menu_domain(self):
        assert _detect_adapter("https://www.sq-menu.com/api/fb/v4pnd") == "sq_menu"

    def test_foodbooking_domain(self):
        assert _detect_adapter("https://www.foodbooking.com/ordering/restaurant/menu") == "sq_menu"

    def test_odoo_pos_self(self):
        assert _detect_adapter("https://afrobowl.odoo.com/pos-self/15") == "odoo_pos"

    def test_odoo_non_pos_returns_none(self):
        # Only /pos-self paths are scraped — plain odoo.com sites are not ordering pages
        assert _detect_adapter("https://myplace.odoo.com/shop") is None

    def test_piki_app(self):
        assert _detect_adapter("https://piki-app.com/vendor/allo-couscous/categories") == "piki_app"

    def test_unknown_url_returns_none(self):
        assert _detect_adapter("https://example.com/menu") is None

    def test_case_insensitive(self):
        assert _detect_adapter("https://WWW.SQ-MENU.COM/api/fb/xyz") == "sq_menu"


# ---------------------------------------------------------------------------
# _extract_sq_menu_code
# ---------------------------------------------------------------------------

class TestExtractSqMenuCode:
    def test_api_fb_path(self):
        assert _extract_sq_menu_code("https://www.sq-menu.com/api/fb/v4pnd") == "v4pnd"

    def test_api_res_path(self):
        assert _extract_sq_menu_code("https://www.foodbooking.com/api/res/_z9_x8w") == "_z9_x8w"

    def test_generic_ordering_path_returns_none(self):
        assert _extract_sq_menu_code("https://www.sq-menu.com/ordering/restaurant/menu") is None

    def test_short_api_path_returns_none(self):
        # /api/fb only — no code segment
        assert _extract_sq_menu_code("https://www.sq-menu.com/api/fb") is None


# ---------------------------------------------------------------------------
# _extract_piki_slug
# ---------------------------------------------------------------------------

class TestExtractPikiSlug:
    def test_standard_vendor_path(self):
        assert (
            _extract_piki_slug(
                "https://piki-app.com/vendor/allo-couscous/promotional-banner/categories"
            )
            == "allo-couscous"
        )

    def test_short_vendor_path(self):
        assert _extract_piki_slug("https://piki-app.com/vendor/my-place") == "my-place"

    def test_no_vendor_segment_returns_none(self):
        assert _extract_piki_slug("https://piki-app.com/menu/something") is None


# ---------------------------------------------------------------------------
# _parse_sq_menu_items
# ---------------------------------------------------------------------------

class TestParseSqMenuItems:
    @pytest.fixture()
    def fixture_data(self) -> dict:
        return _load_fixture("sq_menu_response.json")

    def test_item_count(self, fixture_data):
        items = _parse_sq_menu_items(fixture_data)
        assert len(items) == 5

    def test_first_item_title(self, fixture_data):
        items = _parse_sq_menu_items(fixture_data)
        assert items[0]["title"] == "Soupe du jour"

    def test_price_is_float_euros(self, fixture_data):
        items = _parse_sq_menu_items(fixture_data)
        # All prices from fixture are already in euros
        prices = [item["price"] for item in items]
        assert all(isinstance(p, float) for p in prices)
        assert items[0]["price"] == pytest.approx(6.50)
        assert items[2]["price"] == pytest.approx(22.50)

    def test_catalog_name_preserved(self, fixture_data):
        items = _parse_sq_menu_items(fixture_data)
        assert items[0]["catalog_name"] == "Entrées"
        assert items[2]["catalog_name"] == "Plats"
        assert items[4]["catalog_name"] == "Desserts"

    def test_image_url_present_when_available(self, fixture_data):
        items = _parse_sq_menu_items(fixture_data)
        # First item has an imageUrl
        assert "image_url" in items[0]
        assert items[0]["image_url"].startswith("https://")

    def test_null_image_url_omitted(self, fixture_data):
        items = _parse_sq_menu_items(fixture_data)
        # Second item has null imageUrl → key should be absent
        assert "image_url" not in items[1]

    def test_empty_categories_returns_empty_list(self):
        assert _parse_sq_menu_items({"categories": []}) == []

    def test_missing_categories_key_returns_empty_list(self):
        assert _parse_sq_menu_items({}) == []

    def test_product_with_invalid_price_skipped(self):
        data = {
            "categories": [
                {
                    "name": "Main",
                    "products": [
                        {"name": "Bad item", "price": "not-a-number"},
                        {"name": "Good item", "price": 9.99},
                    ],
                }
            ]
        }
        items = _parse_sq_menu_items(data)
        assert len(items) == 1
        assert items[0]["title"] == "Good item"

    def test_product_without_name_skipped(self):
        data = {
            "categories": [
                {
                    "name": "Main",
                    "products": [
                        {"name": "", "price": 5.00},
                        {"name": "Valid", "price": 5.00},
                    ],
                }
            ]
        }
        items = _parse_sq_menu_items(data)
        assert len(items) == 1


# ---------------------------------------------------------------------------
# _parse_odoo_items
# ---------------------------------------------------------------------------

class TestParseOdooItems:
    @pytest.fixture()
    def fixture_result(self) -> list[dict]:
        data = _load_fixture("odoo_pos_response.json")
        return data["result"]

    def test_item_count(self, fixture_result):
        items = _parse_odoo_items(fixture_result)
        assert len(items) == 5

    def test_title_from_name_field(self, fixture_result):
        items = _parse_odoo_items(fixture_result)
        assert items[0]["title"] == "Poulet yassa"

    def test_price_is_float_euros(self, fixture_result):
        items = _parse_odoo_items(fixture_result)
        assert all(isinstance(i["price"], float) for i in items)
        assert items[0]["price"] == pytest.approx(14.50)
        assert items[3]["price"] == pytest.approx(3.50)

    def test_catalog_name_from_categ_id_tuple(self, fixture_result):
        items = _parse_odoo_items(fixture_result)
        assert items[0]["catalog_name"] == "Plats chauds"
        assert items[3]["catalog_name"] == "Boissons"

    def test_description_present_when_available(self, fixture_result):
        items = _parse_odoo_items(fixture_result)
        assert items[0]["description"] == "Poulet mariné au citron et oignons, riz basmati"

    def test_null_description_omitted(self, fixture_result):
        items = _parse_odoo_items(fixture_result)
        # Last item has null description_sale
        assert "description" not in items[4]

    def test_categ_id_false_gives_none_catalog_name(self):
        products = [{"name": "Item", "list_price": 5.0, "categ_id": False}]
        items = _parse_odoo_items(products)
        assert items[0]["catalog_name"] is None

    def test_empty_result_returns_empty_list(self):
        assert _parse_odoo_items([]) == []

    def test_invalid_price_skipped(self):
        products = [
            {"name": "Bad", "list_price": None, "categ_id": [1, "Cat"]},
            {"name": "Good", "list_price": 8.0, "categ_id": [1, "Cat"]},
        ]
        items = _parse_odoo_items(products)
        assert len(items) == 1
        assert items[0]["title"] == "Good"


# ---------------------------------------------------------------------------
# _parse_piki_items
# ---------------------------------------------------------------------------

class TestParsePikiItems:
    @pytest.fixture()
    def fixture_data(self) -> dict:
        return _load_fixture("piki_app_response.json")

    def test_item_count(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        assert len(items) == 6

    def test_title(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        assert items[0]["title"] == "Couscous Royal"

    def test_price_converted_cents_to_euros(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        # 1650 cents → 16.50 €
        assert items[0]["price"] == pytest.approx(16.50)
        # 1200 cents → 12.00 €
        assert items[1]["price"] == pytest.approx(12.00)

    def test_price_is_float(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        assert all(isinstance(i["price"], float) for i in items)

    def test_catalog_name(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        assert items[0]["catalog_name"] == "Couscous"
        assert items[3]["catalog_name"] == "Tajines"
        assert items[5]["catalog_name"] == "Entrées"

    def test_image_url_present_when_available(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        assert "image_url" in items[0]
        assert items[0]["image_url"].startswith("https://")

    def test_null_image_url_omitted(self, fixture_data):
        items = _parse_piki_items(fixture_data)
        # Second item has null imageUrl
        assert "image_url" not in items[1]

    def test_empty_categories_returns_empty_list(self):
        assert _parse_piki_items({"categories": []}) == []

    def test_missing_categories_key_returns_empty_list(self):
        assert _parse_piki_items({}) == []

    def test_zero_price_item_included(self):
        data = {
            "categories": [
                {"name": "Free", "items": [{"name": "Sample", "price": 0}]}
            ]
        }
        items = _parse_piki_items(data)
        assert len(items) == 1
        assert items[0]["price"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# fetch_sq_menu (with mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchSqMenu:
    def test_successful_fetch(self):
        fixture = _load_fixture("sq_menu_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response(200, fixture)

        items = fetch_sq_menu("https://www.sq-menu.com/api/fb/v4pnd", mock_client)

        assert len(items) == 5
        assert items[0]["title"] == "Soupe du jour"
        assert items[0]["price"] == pytest.approx(6.50)

    def test_first_endpoint_fails_tries_second(self):
        fixture = _load_fixture("sq_menu_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        # First call → 404, second call → 200
        mock_client.get.side_effect = [
            _mock_response(404),
            _mock_response(200, fixture),
        ]

        items = fetch_sq_menu("https://www.sq-menu.com/api/fb/v4pnd", mock_client)
        assert len(items) == 5

    def test_all_endpoints_fail_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response(404)

        items = fetch_sq_menu("https://www.sq-menu.com/api/fb/v4pnd", mock_client)
        assert items == []

    def test_no_extractable_code_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        items = fetch_sq_menu(
            "https://www.sq-menu.com/ordering/restaurant/menu", mock_client
        )
        assert items == []
        mock_client.get.assert_not_called()

    def test_http_error_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        items = fetch_sq_menu("https://www.sq-menu.com/api/fb/v4pnd", mock_client)
        assert items == []


# ---------------------------------------------------------------------------
# fetch_odoo_pos (with mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchOdooPos:
    def test_successful_no_auth_fetch(self):
        fixture = _load_fixture("odoo_pos_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = _mock_response(200, fixture)

        items = fetch_odoo_pos(
            "https://afrobowl.odoo.com/pos-self/15", mock_client
        )
        assert len(items) == 5
        assert items[0]["title"] == "Poulet yassa"

    def test_session_expired_retries_with_session(self):
        fixture = _load_fixture("odoo_pos_response.json")
        session_error = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": 100,
                "message": "Odoo Session Expired",
                "data": {"name": "odoo.http.SessionExpiredException"},
            },
        }
        mock_client = MagicMock(spec=httpx.Client)
        # First POST → session expired, second POST → success
        mock_client.post.side_effect = [
            _mock_response(200, session_error),
            _mock_response(200, fixture),
        ]
        mock_client.get.return_value = _mock_response(200)  # session prime

        items = fetch_odoo_pos(
            "https://afrobowl.odoo.com/pos-self/15", mock_client
        )
        assert len(items) == 5
        # GET was called to prime the session
        mock_client.get.assert_called_once()

    def test_session_expired_twice_returns_empty(self):
        session_error = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": 100,
                "message": "Odoo Session Expired",
                "data": {"name": "odoo.http.SessionExpiredException"},
            },
        }
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = _mock_response(200, session_error)
        mock_client.get.return_value = _mock_response(200)

        items = fetch_odoo_pos(
            "https://afrobowl.odoo.com/pos-self/15", mock_client
        )
        assert items == []

    def test_http_error_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.side_effect = httpx.ConnectError("refused")

        items = fetch_odoo_pos(
            "https://afrobowl.odoo.com/pos-self/15", mock_client
        )
        assert items == []

    def test_rpc_non_session_error_returns_empty(self):
        error_response = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": 200,
                "message": "Access Denied",
                "data": {"name": "AccessDenied"},
            },
        }
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = _mock_response(200, error_response)

        items = fetch_odoo_pos(
            "https://afrobowl.odoo.com/pos-self/15", mock_client
        )
        assert items == []


# ---------------------------------------------------------------------------
# fetch_piki_app (with mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchPikiApp:
    def test_successful_fetch(self):
        fixture = _load_fixture("piki_app_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response(200, fixture)

        items = fetch_piki_app(
            "https://piki-app.com/vendor/allo-couscous/categories", mock_client
        )
        assert len(items) == 6
        assert items[0]["title"] == "Couscous Royal"
        assert items[0]["price"] == pytest.approx(16.50)

    def test_all_endpoints_fail_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response(404)

        items = fetch_piki_app(
            "https://piki-app.com/vendor/allo-couscous/categories", mock_client
        )
        assert items == []

    def test_no_slug_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        items = fetch_piki_app("https://piki-app.com/home", mock_client)
        assert items == []
        mock_client.get.assert_not_called()

    def test_connection_error_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.ConnectError("name not resolved")

        items = fetch_piki_app(
            "https://piki-app.com/vendor/test-slug/categories", mock_client
        )
        assert items == []

    def test_first_endpoint_fails_tries_next(self):
        fixture = _load_fixture("piki_app_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = [
            _mock_response(404),
            _mock_response(200, fixture),
        ]

        items = fetch_piki_app(
            "https://piki-app.com/vendor/allo-couscous/categories", mock_client
        )
        assert len(items) == 6


# ---------------------------------------------------------------------------
# fetch_items dispatch
# ---------------------------------------------------------------------------

class TestFetchItemsDispatch:
    def test_dispatches_to_sq_menu(self):
        fixture = _load_fixture("sq_menu_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response(200, fixture)

        items = fetch_items("https://www.sq-menu.com/api/fb/v4pnd", mock_client)
        assert len(items) == 5

    def test_dispatches_to_odoo_pos(self):
        fixture = _load_fixture("odoo_pos_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = _mock_response(200, fixture)

        items = fetch_items("https://afrobowl.odoo.com/pos-self/15", mock_client)
        assert len(items) == 5

    def test_dispatches_to_piki_app(self):
        fixture = _load_fixture("piki_app_response.json")
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response(200, fixture)

        items = fetch_items(
            "https://piki-app.com/vendor/allo-couscous/categories", mock_client
        )
        assert len(items) == 6

    def test_unknown_url_returns_empty(self):
        mock_client = MagicMock(spec=httpx.Client)
        items = fetch_items("https://example.com/menu", mock_client)
        assert items == []
        mock_client.get.assert_not_called()
        mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# run() integration (DB + HTTP both mocked)
# ---------------------------------------------------------------------------

class TestRun:
    @pytest.fixture()
    def mock_listings(self) -> list[dict]:
        return [
            {
                "id": "listing-sq",
                "restaurant_id": "rest-1",
                "url": "https://www.sq-menu.com/api/fb/v4pnd",
            },
            {
                "id": "listing-odoo",
                "restaurant_id": "rest-2",
                "url": "https://afrobowl.odoo.com/pos-self/15",
            },
            {
                "id": "listing-piki",
                "restaurant_id": "rest-3",
                "url": "https://piki-app.com/vendor/allo-couscous/categories",
            },
        ]

    def test_run_processes_all_listings(self, mock_listings):
        sq_fixture = _load_fixture("sq_menu_response.json")
        odoo_fixture = _load_fixture("odoo_pos_response.json")
        piki_fixture = _load_fixture("piki_app_response.json")

        db_client_mock = MagicMock()
        db_client_mock.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.execute.return_value.data = mock_listings

        with (
            patch("scrapers.direct_menu.db.get_client", return_value=db_client_mock),
            patch("scrapers.direct_menu.db.delete_menu_items") as mock_delete,
            patch("scrapers.direct_menu.db.insert_menu_items") as mock_insert,
            patch("httpx.Client") as mock_http_cls,
        ):
            mock_insert.side_effect = [5, 5, 6]  # items saved per listing
            http_instance = MagicMock()
            mock_http_cls.return_value.__enter__.return_value = http_instance
            http_instance.get.side_effect = [
                _mock_response(200, sq_fixture),   # sq_menu first attempt
                _mock_response(200, piki_fixture), # piki first attempt
            ]
            http_instance.post.return_value = _mock_response(200, odoo_fixture)

            result = run()

        assert result["listings_processed"] == 3
        assert result["total_scraped"] == 16  # 5 + 5 + 6
        assert result["errors"] == []
        # delete must be called once per listing, before insert
        assert mock_delete.call_count == 3
        deleted_ids = [call.args[0] for call in mock_delete.call_args_list]
        assert deleted_ids == ["listing-sq", "listing-odoo", "listing-piki"]

    def test_run_continues_after_per_listing_error(self, mock_listings):
        sq_fixture = _load_fixture("sq_menu_response.json")
        piki_fixture = _load_fixture("piki_app_response.json")

        db_client_mock = MagicMock()
        db_client_mock.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.execute.return_value.data = mock_listings

        with (
            patch("scrapers.direct_menu.db.get_client", return_value=db_client_mock),
            patch("scrapers.direct_menu.db.delete_menu_items") as mock_delete,
            patch("scrapers.direct_menu.db.insert_menu_items") as mock_insert,
            patch("httpx.Client") as mock_http_cls,
        ):
            # listing-sq: delete raises (error); listing-odoo/piki: delete+insert succeed
            mock_delete.side_effect = [RuntimeError("DB error"), None, None]
            mock_insert.side_effect = [5, 6]
            http_instance = MagicMock()
            mock_http_cls.return_value.__enter__.return_value = http_instance
            # sq_menu uses GET; piki uses GET (first template succeeds)
            http_instance.get.side_effect = [
                _mock_response(200, sq_fixture),   # sq_menu /api/menu/{code}
                _mock_response(200, piki_fixture), # piki first template
            ]
            http_instance.post.return_value = _mock_response(200, _load_fixture("odoo_pos_response.json"))

            result = run()

        assert result["listings_processed"] == 2
        assert len(result["errors"]) == 1
        assert "listing-sq" in result["errors"][0]

    def test_run_respects_max_items(self, mock_listings):
        sq_fixture = _load_fixture("sq_menu_response.json")  # 5 items

        db_client_mock = MagicMock()
        db_client_mock.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.execute.return_value.data = mock_listings[:1]

        with (
            patch("scrapers.direct_menu.db.get_client", return_value=db_client_mock),
            patch("scrapers.direct_menu.db.delete_menu_items") as mock_delete,
            patch("scrapers.direct_menu.db.insert_menu_items") as mock_insert,
            patch("httpx.Client") as mock_http_cls,
        ):
            mock_insert.return_value = 3
            http_instance = MagicMock()
            mock_http_cls.return_value.__enter__.return_value = http_instance
            http_instance.get.return_value = _mock_response(200, sq_fixture)

            result = run(max_items=3)

        # delete was called for the listing before insert
        mock_delete.assert_called_once_with("listing-sq")
        # insert_menu_items was called with at most 3 items
        call_args = mock_insert.call_args
        inserted_items = call_args[0][1]  # second positional arg = items list
        assert len(inserted_items) <= 3

    def test_run_empty_listings(self):
        db_client_mock = MagicMock()
        db_client_mock.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.execute.return_value.data = []

        with (
            patch("scrapers.direct_menu.db.get_client", return_value=db_client_mock),
            patch("scrapers.direct_menu.db.delete_menu_items") as mock_delete,
            patch("scrapers.direct_menu.db.insert_menu_items") as mock_insert,
            patch("httpx.Client"),
        ):
            result = run()

        assert result == {"total_scraped": 0, "listings_processed": 0, "errors": []}
        mock_delete.assert_not_called()
        mock_insert.assert_not_called()
