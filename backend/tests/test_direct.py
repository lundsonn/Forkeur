"""
Tests for scrapers/direct.py.

Covers pure helpers (no I/O) and async functions (_check_website,
_enrich_existing, _enrich_neighborhoods) with Playwright/DB/HTTP mocked.
_maps_search and _discover_maps are Playwright + live-Google-Maps heavy
and are covered at the integration level only.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scrapers.direct import (
    _clean_commune,
    _extract_phone,
    _make_slug,
    _normalize_phone,
    _validate_order_url,
    _check_website,
    _enrich_existing,
    _enrich_neighborhoods,
)


# ---------------------------------------------------------------------------
# _normalize_phone
# ---------------------------------------------------------------------------

class TestNormalizePhone:
    def test_mobile_with_spaces(self):
        assert _normalize_phone("0472 12 34 56") == "+32472123456"

    def test_0032_prefix(self):
        assert _normalize_phone("0032 2 123 45 67") == "+3221234567"

    def test_landline_0(self):
        # 10-digit 0-prefixed number: strip 0, prepend 32 → 11-digit result
        assert _normalize_phone("0212345678") == "+32212345678"

    def test_already_plus32(self):
        result = _normalize_phone("+32472123456")
        # +32 → digits start with 32, length 11 → OK
        assert result == "+32472123456"

    def test_too_short_returns_none(self):
        assert _normalize_phone("123") is None

    def test_random_text_returns_none(self):
        assert _normalize_phone("no phone") is None


# ---------------------------------------------------------------------------
# _extract_phone
# ---------------------------------------------------------------------------

class TestExtractPhone:
    def test_finds_mobile_in_text(self):
        text = "Contactez-nous au 0472 12 34 56 pour toute question."
        assert _extract_phone(text) == "+32472123456"

    def test_returns_first_valid_number(self):
        text = "Ring 0032 2 123 45 67 or 0472 99 88 77"
        result = _extract_phone(text)
        assert result is not None
        assert result.startswith("+32")

    def test_no_phone_returns_none(self):
        assert _extract_phone("Aucun numéro ici.") is None

    def test_partial_match_ignored(self):
        # "123" alone shouldn't be extracted
        assert _extract_phone("code: 123") is None


# ---------------------------------------------------------------------------
# _make_slug
# ---------------------------------------------------------------------------

class TestMakeSlug:
    def test_basic(self):
        assert _make_slug("Burger King") == "burger-king"

    def test_accents(self):
        assert _make_slug("Café de Paris") == "cafe-de-paris"

    def test_special_chars_become_hyphens(self):
        slug = _make_slug("Pizza & More!")
        assert "&" not in slug and "!" not in slug

    def test_no_leading_trailing_hyphens(self):
        slug = _make_slug("  --Pizza--  ")
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    def test_truncates_at_60(self):
        assert len(_make_slug("A" * 80)) <= 60

    def test_accent_e_variants(self):
        assert _make_slug("été") == "ete"

    def test_accent_o_variants(self):
        assert _make_slug("Döner") == "doner"


# ---------------------------------------------------------------------------
# _validate_order_url  (direct.py version — filters invalid ordering paths)
# ---------------------------------------------------------------------------

class TestDirectValidateOrderUrl:
    def test_normal_website_ok(self):
        assert _validate_order_url("https://myrestaurant.be") is True

    def test_sq_menu_with_api_code_ok(self):
        assert _validate_order_url("https://www.sq-menu.com/api/fb/v4pnd") is True

    def test_sq_menu_generic_spa_rejected(self):
        assert _validate_order_url("https://www.sq-menu.com/ordering/restaurant/menu") is False

    def test_foodbooking_generic_rejected(self):
        assert _validate_order_url("https://www.foodbooking.com/ordering/restaurant/menu") is False

    def test_odoo_with_numeric_id_ok(self):
        assert _validate_order_url("https://resto.odoo.com/pos-self/15") is True

    def test_odoo_without_numeric_id_rejected(self):
        assert _validate_order_url("https://resto.odoo.com/pos-self/menu") is False

    def test_lightspeed_ok(self):
        assert _validate_order_url("https://order.lightspeedrestaurant.com/abc") is True


# ---------------------------------------------------------------------------
# _clean_commune
# ---------------------------------------------------------------------------

class TestCleanCommune:
    def test_strips_dutch_half(self):
        assert _clean_commune("Ixelles - Elsene") == "Ixelles"

    def test_no_dutch_unchanged(self):
        assert _clean_commune("Uccle") == "Uccle"

    def test_none_returns_none(self):
        assert _clean_commune(None) is None

    def test_empty_string_returns_none(self):
        assert _clean_commune("") is None

    def test_anderlecht_bilingual(self):
        assert _clean_commune("Anderlecht - Anderlecht") == "Anderlecht"


# ---------------------------------------------------------------------------
# _check_website  (async, Playwright page mocked)
# ---------------------------------------------------------------------------

def _make_page(text="", links=None, goto_raises=None):
    page = AsyncMock()
    if goto_raises:
        page.goto.side_effect = goto_raises
    else:
        page.goto.return_value = None
    page.inner_text.return_value = text
    page.eval_on_selector_all.return_value = links or []
    return page


@pytest.mark.asyncio
async def test_check_website_finds_ordering_platform_url():
    page = _make_page(
        text="Order online here",
        links=[
            "https://facebook.com/myrest",
            "https://order.lightspeedrestaurant.com/my-restaurant",
        ],
    )
    result = await _check_website(page, "https://myrest.be", lambda _: None)
    assert result["order_url"] == "https://order.lightspeedrestaurant.com/my-restaurant"
    assert result["has_delivery"] is True


@pytest.mark.asyncio
async def test_check_website_skips_aggregator_links():
    page = _make_page(
        text="commander en ligne",
        links=[
            "https://www.ubereats.com/store/my-rest/abc",
            "https://deliveroo.be/menu/my-rest",
        ],
    )
    result = await _check_website(page, "https://myrest.be", lambda _: None)
    # Aggregator links are ignored; no ordering URL found
    assert result["order_url"] is None


@pytest.mark.asyncio
async def test_check_website_delivery_keyword_sets_has_delivery():
    page = _make_page(text="livraison à domicile disponible", links=[])
    result = await _check_website(page, "https://myrest.be", lambda _: None)
    assert result["has_delivery"] is True
    assert result["order_url"] is None


@pytest.mark.asyncio
async def test_check_website_extracts_phone():
    page = _make_page(text="Appelez-nous: 0472 12 34 56", links=[])
    result = await _check_website(page, "https://myrest.be", lambda _: None)
    assert result["phone"] == "+32472123456"


@pytest.mark.asyncio
async def test_check_website_goto_error_returns_empty():
    page = _make_page(goto_raises=Exception("timeout"))
    result = await _check_website(page, "https://myrest.be", lambda _: None)
    assert result == {"phone": None, "order_url": None, "has_delivery": False}


@pytest.mark.asyncio
async def test_check_website_no_signals_returns_empty():
    page = _make_page(text="Welcome to our restaurant.", links=["https://facebook.com"])
    result = await _check_website(page, "https://myrest.be", lambda _: None)
    assert result["has_delivery"] is False
    assert result["order_url"] is None


# ---------------------------------------------------------------------------
# _enrich_existing  (async, DB + Playwright mocked)
# ---------------------------------------------------------------------------

def _make_db_client(restaurants=None, already_done_ids=None):
    client = MagicMock()
    # already_done: .select('restaurant_id, id, scraped_at').eq('platform', 'direct').execute()
    # scraped_at is a fresh (recent) timestamp so these listings count as "done", not stale.
    fresh = datetime.now(timezone.utc).isoformat()
    client.table.return_value.select.return_value \
        .eq.return_value.execute.return_value.data = [
        {"restaurant_id": rid, "id": f"listing_{rid}", "scraped_at": fresh}
        for rid in (already_done_ids or [])
    ]
    # all restaurants: .select(...).not_.is_(...).neq(...).execute()
    client.table.return_value.select.return_value \
        .not_.is_.return_value.neq.return_value.execute.return_value.data = restaurants or []
    return client


@pytest.mark.asyncio
async def test_enrich_existing_inserts_new_listing():
    db_client = _make_db_client(restaurants=[
        {"id": "r1", "name": "My Rest", "website": "https://myrest.be", "phone": None}
    ])
    mock_page = _make_page(
        text="commander en ligne",
        links=["https://order.lightspeedrestaurant.com/my-restaurant"],
    )
    mock_page.close = AsyncMock()
    browser = AsyncMock()

    with patch("scrapers.direct.db.get_client", return_value=db_client), \
         patch("scrapers.direct.new_page", new_callable=AsyncMock, return_value=mock_page):
        saved = await _enrich_existing(browser, lambda _: None)

    assert saved == 1
    db_client.table.return_value.insert.assert_called_once()


@pytest.mark.asyncio
async def test_enrich_existing_skips_already_done():
    """Restaurants that already have a direct listing are pre-filtered out."""
    db_client = _make_db_client(
        restaurants=[
            {"id": "r1", "name": "My Rest", "website": "https://myrest.be", "phone": None}
        ],
        already_done_ids=["r1"],  # r1 already has a listing
    )
    browser = AsyncMock()

    with patch("scrapers.direct.db.get_client", return_value=db_client), \
         patch("scrapers.direct.new_page", new_callable=AsyncMock):
        saved = await _enrich_existing(browser, lambda _: None)

    assert saved == 0
    db_client.table.return_value.insert.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_existing_saves_phone_when_new():
    db_client = _make_db_client(restaurants=[
        {"id": "r1", "name": "My Rest", "website": "https://myrest.be", "phone": None}
    ])
    mock_page = _make_page(text="0472 12 34 56", links=[])
    mock_page.close = AsyncMock()
    browser = AsyncMock()

    with patch("scrapers.direct.db.get_client", return_value=db_client), \
         patch("scrapers.direct.new_page", new_callable=AsyncMock, return_value=mock_page):
        await _enrich_existing(browser, lambda _: None)

    update_calls = [c[0][0] for c in db_client.table.return_value.update.call_args_list]
    phone_updates = [c for c in update_calls if "phone" in c]
    assert any(c["phone"] == "+32472123456" for c in phone_updates)


@pytest.mark.asyncio
async def test_enrich_existing_skips_no_restaurant():
    """Empty restaurant list returns 0 immediately without touching the browser."""
    db_client = _make_db_client(restaurants=[])
    browser = AsyncMock()

    with patch("scrapers.direct.db.get_client", return_value=db_client), \
         patch("scrapers.direct.new_page", new_callable=AsyncMock) as mock_new_page:
        saved = await _enrich_existing(browser, lambda _: None)

    assert saved == 0
    mock_new_page.assert_not_called()


# ---------------------------------------------------------------------------
# _enrich_neighborhoods  (async, Nominatim HTTP mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_neighborhoods_updates_from_nominatim():
    db_client = MagicMock()
    db_client.table.return_value.select.return_value \
        .is_.return_value.not_.is_.return_value.execute.return_value.data = [
        {"id": "r1", "lat": 50.85, "lng": 4.35}
    ]

    nominatim_response = MagicMock()
    nominatim_response.json.return_value = {
        "address": {"city_district": "Ixelles - Elsene"}
    }

    mock_http = AsyncMock()
    mock_http.get.return_value = nominatim_response
    mock_http_ctx = AsyncMock()
    mock_http_ctx.__aenter__.return_value = mock_http
    mock_http_ctx.__aexit__.return_value = None

    with patch("scrapers.direct.db.get_client", return_value=db_client), \
         patch("httpx.AsyncClient", return_value=mock_http_ctx), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await _enrich_neighborhoods(lambda _: None)

    update_calls = [c[0][0] for c in db_client.table.return_value.update.call_args_list]
    assert any(c.get("neighborhood") == "Ixelles" for c in update_calls)


@pytest.mark.asyncio
async def test_enrich_neighborhoods_skips_when_no_rows():
    db_client = MagicMock()
    db_client.table.return_value.select.return_value \
        .is_.return_value.not_.is_.return_value.execute.return_value.data = []

    mock_http = AsyncMock()
    mock_http_ctx = AsyncMock()
    mock_http_ctx.__aenter__.return_value = mock_http
    mock_http_ctx.__aexit__.return_value = None

    with patch("scrapers.direct.db.get_client", return_value=db_client), \
         patch("httpx.AsyncClient", return_value=mock_http_ctx):
        await _enrich_neighborhoods(lambda _: None)

    # Client instantiated but no requests made (empty rows → loop body never runs)
    mock_http.get.assert_not_called()
