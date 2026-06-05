"""
direct_menu.py — Scrape menu items for direct-ordering listings.

Supported adapters:
  - sq_menu     : foodbooking/sq-menu.com SPA ordering system
  - odoo_pos    : Odoo POS self-order (pos-self) endpoint
  - piki_app    : piki-app.com Angular/Supabase ordering system

Each adapter returns a list of dicts with keys:
  title, price (float, euros), catalog_name, description (optional), image_url (optional)
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

def _detect_adapter(url: str) -> str | None:
    """Return adapter name for a given URL, or None if unsupported."""
    lower = url.lower()
    if "sq-menu.com" in lower or "foodbooking.com" in lower:
        return "sq_menu"
    if "odoo.com" in lower and "/pos-self" in lower:
        return "odoo_pos"
    if "piki-app.com" in lower:
        return "piki_app"
    return None


# ---------------------------------------------------------------------------
# Adapter: sq_menu / foodbooking
# ---------------------------------------------------------------------------
#
# URL patterns observed in DB:
#   https://www.sq-menu.com/api/fb/{hotlink_code}   — hotlink redirect (often stale)
#   https://www.sq-menu.com/ordering/restaurant/menu — generic SPA path
#   https://www.foodbooking.com/api/fb/{code}
#   https://www.foodbooking.com/ordering/restaurant/menu/reservation
#
# The /api/fb/{code} endpoint is a short-link that the backend resolves to a
# restaurant GUID — but codes expire.  When valid, the SPA loads the menu via
# an internal call using company_uid/restaurant_uid query params.
#
# Public JSON API: GET /api/menu/{code}  (returns categories + products)
# Fallback: GET /api/catalog/{code}
# The JSON structure has: { categories: [{ name, products: [{ name, price, description, imageUrl }] }] }

_SQ_MENU_HOSTS = ("sq-menu.com", "foodbooking.com")
_SQ_MENU_API_TEMPLATE = "https://www.{host}/api/menu/{code}"
_SQ_MENU_CATALOG_TEMPLATE = "https://www.{host}/api/catalog/{code}"


def _extract_sq_menu_code(url: str) -> str | None:
    """Extract hotlink code from a sq-menu / foodbooking URL.

    Handles patterns:
      /api/fb/{code}        -> code
      /api/{type}/{code}    -> code
      /ordering/...         -> None (no extractable code)
    """
    parsed = urlparse(url)
    # e.g. /api/fb/v4pnd  or  /api/res/_z9_x8w
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "api":
        # /api/{segment}/{code}
        return parts[-1] if len(parts) >= 3 else None
    return None


def _parse_sq_menu_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a sq-menu / foodbooking JSON menu response into item dicts."""
    items: list[dict[str, Any]] = []
    categories = data.get("categories") or []
    for cat in categories:
        cat_name: str = cat.get("name") or ""
        for prod in cat.get("products") or []:
            title: str = (prod.get("name") or "").strip()
            if not title:
                continue
            raw_price = prod.get("price")
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                continue
            item: dict[str, Any] = {
                "title": title,
                "price": round(price, 2),
                "catalog_name": cat_name or None,
            }
            desc = (prod.get("description") or "").strip() or None
            if desc:
                item["description"] = desc
            img = (prod.get("imageUrl") or "").strip() or None
            if img:
                item["image_url"] = img
            items.append(item)
    return items


def fetch_sq_menu(url: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch and parse menu items from a sq-menu / foodbooking URL.

    Tries /api/menu/{code} then /api/catalog/{code}.
    Returns empty list on any error or unsupported URL pattern.
    """
    code = _extract_sq_menu_code(url)
    if not code:
        logger.debug("sq_menu: no extractable code from %s", url)
        return []

    parsed = urlparse(url)
    # Normalise host: strip leading www.
    host = re.sub(r"^www\.", "", parsed.netloc)

    for template in (_SQ_MENU_API_TEMPLATE, _SQ_MENU_CATALOG_TEMPLATE):
        api_url = template.format(host=host, code=code)
        try:
            resp = client.get(api_url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                items = _parse_sq_menu_items(data)
                logger.info("sq_menu: %d items from %s", len(items), api_url)
                return items
            logger.debug("sq_menu: %s → HTTP %d", api_url, resp.status_code)
        except httpx.HTTPError as exc:
            logger.warning("sq_menu: HTTP error for %s: %s", api_url, exc)
        except Exception as exc:
            logger.warning("sq_menu: unexpected error for %s: %s", api_url, exc)

    return []


# ---------------------------------------------------------------------------
# Adapter: odoo_pos
# ---------------------------------------------------------------------------
#
# URL pattern: https://{tenant}.odoo.com/pos-self/{config_id}
#
# Odoo JSON-RPC:  POST /web/dataset/call_kw
# Model: product.product, method: search_read
# Filter: [["available_in_pos", "=", true]]
# Fields: name, list_price, categ_id ([id, name] tuple), description_sale, image_128
#
# Requires a valid session cookie.  Without one, Odoo 17/18/19 returns
# SessionExpiredException.  We first attempt a session-less call (works on
# some older/public instances), and if that fails we perform a two-step
# approach: GET the pos-self page to obtain a session cookie, then retry.

_ODOO_CALL_KW_PATH = "/web/dataset/call_kw"
_ODOO_PRODUCT_PAYLOAD: dict[str, Any] = {
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "model": "product.product",
        "method": "search_read",
        "args": [[["available_in_pos", "=", True]]],
        "kwargs": {
            "fields": [
                "name",
                "list_price",
                "categ_id",
                "description_sale",
                "image_128",
            ],
            "limit": 200,
        },
    },
}


def _parse_odoo_items(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse a list of Odoo product.product dicts into item dicts."""
    items: list[dict[str, Any]] = []
    for prod in result:
        title: str = (prod.get("name") or "").strip()
        if not title:
            continue
        raw_price = prod.get("list_price")
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            continue

        # categ_id is [id, name] or False
        categ = prod.get("categ_id")
        if isinstance(categ, (list, tuple)) and len(categ) == 2:
            cat_name: str | None = str(categ[1]) if categ[1] else None
        else:
            cat_name = None

        item: dict[str, Any] = {
            "title": title,
            "price": round(price, 2),
            "catalog_name": cat_name,
        }
        desc = (prod.get("description_sale") or "").strip() or None
        if desc:
            item["description"] = desc
        items.append(item)
    return items


def fetch_odoo_pos(url: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch and parse POS products from an Odoo pos-self URL.

    Attempts a session-less JSON-RPC call first; if Odoo returns
    SessionExpiredException, establishes a session via the pos-self page
    and retries once.

    Returns empty list on unrecoverable errors.
    """
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    rpc_url = base_url + _ODOO_CALL_KW_PATH

    def _call_rpc() -> list[dict[str, Any]] | None:
        """Returns parsed items or None if session error."""
        try:
            resp = client.post(
                rpc_url,
                json=_ODOO_PRODUCT_PAYLOAD,
                timeout=20,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                logger.debug("odoo_pos: HTTP %d from %s", resp.status_code, rpc_url)
                return []
            body = resp.json()
            if "error" in body:
                err_name: str = (
                    body["error"].get("data", {}).get("name") or ""
                )
                if "SessionExpired" in err_name or "session" in err_name.lower():
                    return None  # signal: need session
                logger.warning(
                    "odoo_pos: RPC error from %s: %s",
                    rpc_url,
                    body["error"].get("message"),
                )
                return []
            result = body.get("result", [])
            if not isinstance(result, list):
                return []
            return _parse_odoo_items(result)
        except httpx.HTTPError as exc:
            logger.warning("odoo_pos: HTTP error for %s: %s", rpc_url, exc)
            return []

    # First attempt — no session
    items = _call_rpc()
    if items is not None:
        logger.info("odoo_pos: %d items from %s (no-auth)", len(items), rpc_url)
        return items

    # Session expired — attempt to prime a session via the pos-self page
    logger.debug("odoo_pos: session expired, retrying with session from %s", url)
    try:
        client.get(url, timeout=15)  # sets session cookie in client's cookie jar
    except httpx.HTTPError as exc:
        logger.warning("odoo_pos: could not prime session from %s: %s", url, exc)
        return []

    items = _call_rpc()
    if items is None:
        logger.warning(
            "odoo_pos: session still expired after prime from %s", url
        )
        return []
    logger.info("odoo_pos: %d items from %s (with-session)", len(items), rpc_url)
    return items


# ---------------------------------------------------------------------------
# Adapter: piki_app
# ---------------------------------------------------------------------------
#
# URL pattern: https://piki-app.com/vendor/{slug}/...
#
# piki-app is an Angular SPA backed by Supabase.
# Public REST endpoint (best-effort, requires per-tenant anon key):
#   GET https://api.piki-app.com/v1/vendor/{slug}/categories   (domain not resolving)
#   GET https://piki-app.com/api/vendor/{slug}/categories       (returns 404)
#
# Fallback: POST to the Supabase PostgREST at
#   https://ajblxmolmmvvnobpzzhr.supabase.co/rest/v1/
# but that requires the anon key (not publicly exposed without the app loading).
#
# In practice this adapter attempts the known API patterns and returns items
# if any succeeds; otherwise returns an empty list so the caller can log and
# continue without crashing the run.

_PIKI_API_TEMPLATES = [
    "https://api.piki-app.com/v1/vendor/{slug}/categories",
    "https://www.piki-app.com/api/vendor/{slug}/categories",
    "https://piki-app.com/api/vendor/{slug}/categories",
]


def _extract_piki_slug(url: str) -> str | None:
    """Extract vendor slug from a piki-app URL.

    Handles:
      /vendor/{slug}/...
    """
    m = re.search(r"/vendor/([^/?#]+)", url)
    return m.group(1) if m else None


def _parse_piki_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a piki-app categories response into item dicts.

    Expected structure:
      { categories: [{ name, items: [{ name, price (cents), description, imageUrl }] }] }
    """
    items: list[dict[str, Any]] = []
    categories = data.get("categories") or []
    for cat in categories:
        cat_name: str = (cat.get("name") or "").strip()
        for prod in cat.get("items") or []:
            title: str = (prod.get("name") or "").strip()
            if not title:
                continue
            raw_price = prod.get("price")
            try:
                # piki-app stores prices in euro-cents
                price = round(float(raw_price) / 100.0, 2)
            except (TypeError, ValueError):
                continue
            item: dict[str, Any] = {
                "title": title,
                "price": price,
                "catalog_name": cat_name or None,
            }
            desc = (prod.get("description") or "").strip() or None
            if desc:
                item["description"] = desc
            img = (prod.get("imageUrl") or "").strip() or None
            if img:
                item["image_url"] = img
            items.append(item)
    return items


def fetch_piki_app(url: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch and parse menu items from a piki-app URL.

    Returns empty list if no supported API endpoint responds.
    """
    slug = _extract_piki_slug(url)
    if not slug:
        logger.debug("piki_app: no slug in %s", url)
        return []

    for template in _PIKI_API_TEMPLATES:
        api_url = template.format(slug=slug)
        try:
            resp = client.get(
                api_url,
                timeout=15,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                items = _parse_piki_items(data)
                logger.info("piki_app: %d items from %s", len(items), api_url)
                return items
            logger.debug("piki_app: %s → HTTP %d", api_url, resp.status_code)
        except httpx.HTTPError as exc:
            logger.debug("piki_app: HTTP error for %s: %s", api_url, exc)
        except Exception as exc:
            logger.warning("piki_app: unexpected error for %s: %s", api_url, exc)

    return []


# ---------------------------------------------------------------------------
# Dispatch helper
# ---------------------------------------------------------------------------

_ADAPTER_MAP = {
    "sq_menu": fetch_sq_menu,
    "odoo_pos": fetch_odoo_pos,
    "piki_app": fetch_piki_app,
}


def fetch_items(
    url: str,
    client: httpx.Client,
) -> list[dict[str, Any]]:
    """Detect adapter from URL and fetch items. Returns [] if unsupported."""
    adapter = _detect_adapter(url)
    if adapter is None:
        logger.debug("direct_menu: no adapter for %s", url)
        return []
    fn = _ADAPTER_MAP[adapter]
    return fn(url, client)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run(max_items: int | None = None) -> dict[str, Any]:
    """Fetch menu items for all direct listings with url_type='ordering'.

    Runs up to 10 listings concurrently using asyncio.Semaphore(10) +
    asyncio.to_thread so the sync HTTP fetchers don't block the event loop.

    Args:
        max_items: If set, cap total items inserted (useful for testing).

    Returns:
        dict with keys: total_scraped, listings_processed, errors (list[str])
    """
    client_db = db.get_client()
    listings = (
        client_db.table("platform_listings")
        .select("id, url, restaurant_id")
        .eq("platform", "direct")
        .eq("url_type", "ordering")
        .execute()
        .data
    )

    sem = asyncio.Semaphore(10)

    def _fetch_sync(listing: dict) -> dict[str, Any]:
        """Sync worker: opens its own httpx.Client and fetches items."""
        lid = listing["id"]
        url = listing.get("url") or ""
        if not url:
            return {"lid": lid, "items": [], "error": None, "skipped": True}
        try:
            with httpx.Client(follow_redirects=True) as http:
                items = fetch_items(url, http)
            return {"lid": lid, "url": url, "items": items, "error": None}
        except Exception as exc:
            return {"lid": lid, "url": url, "items": [], "error": str(exc)}

    async def _fetch_one(listing: dict) -> dict[str, Any]:
        async with sem:
            return await asyncio.to_thread(_fetch_sync, listing)

    tasks = [asyncio.ensure_future(_fetch_one(l)) for l in listings]
    results = await asyncio.gather(*tasks)

    total_scraped = 0
    listings_processed = 0
    errors: list[str] = []

    for r in results:
        if r.get("skipped"):
            continue
        lid = r["lid"]
        url = r.get("url", "")
        if r["error"]:
            msg = f"listing {lid} ({url[:60]}): {r['error']}"
            logger.error("direct_menu: error — %s", msg)
            errors.append(msg)
            continue
        items = r["items"]
        if max_items is not None:
            remaining = max_items - total_scraped
            if remaining <= 0:
                break
            items = items[:remaining]
        if not items:
            # API returned nothing — downgrade to 'menu' so dom_menu can try Playwright
            db.get_client().table("platform_listings").update(
                {"url_type": "menu"}
            ).eq("id", lid).execute()
            logger.info("direct_menu: no items from %s — downgraded to menu", url[:60])
            continue
        try:
            db.delete_menu_items(lid)
            saved = db.insert_menu_items(lid, items)
        except Exception as exc:
            msg = f"listing {lid} ({url[:60]}): {exc}"
            logger.error("direct_menu: error — %s", msg)
            errors.append(msg)
            continue
        total_scraped += saved
        listings_processed += 1
        logger.info("direct_menu: listing %s — saved %d items from %s", lid, saved, url[:60])

    return {
        "total_scraped": total_scraped,
        "listings_processed": listings_processed,
        "errors": errors,
    }
