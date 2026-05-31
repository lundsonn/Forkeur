# Menu Scraping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add phase 2 to all three scrapers so they populate `menu_items` (title, price, catalog_name) by visiting individual restaurant pages after the listing phase.

**Architecture:** Each scraper's `run()` collects `(listing_id, url)` pairs during phase 1, then iterates up to `config.max_menus` of them and calls a per-platform `scrape_menu_page()` helper. UberEats uses API interception (same pattern as feed capture); Deliveroo and Takeaway use JS DOM eval with a price heuristic. Errors per restaurant are caught and logged without failing the overall run.

**Tech Stack:** Python 3.12, Playwright (async), FastAPI, Supabase python-supabase client, pytest + unittest.mock

---

## File Map

| File | Change |
|---|---|
| `backend/models.py` | Add `scrape_menus`, `max_menus` to `ScraperConfig`; `menu_items_saved` to `ScraperResult`; new `RunTriggerIn` model |
| `backend/scrapers/base.py` | Add shared `parse_menu_price()` helper |
| `backend/routers/scrapers.py` | Accept optional `RunTriggerIn` body; pass fields to `ScraperConfig` |
| `backend/scrapers/ubereats.py` | Add `_parse_ue_menu()`, `scrape_menu_page()`; update `run()` |
| `backend/scrapers/deliveroo.py` | Add `scrape_menu_page()`; update `run()` |
| `backend/scrapers/takeaway.py` | Add `scrape_menu_page()`; update `run()` |
| `backend/tests/test_menu_scraping.py` | New — unit tests for all parsing helpers |

---

## Task 1: Update models

**Files:**
- Modify: `backend/models.py`
- Test: `backend/tests/test_menu_scraping.py` (create)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_menu_scraping.py`:

```python
from models import ScraperConfig, ScraperResult, RunTriggerIn


def test_scraper_config_defaults():
    c = ScraperConfig()
    assert c.scrape_menus is False
    assert c.max_menus == 3


def test_scraper_config_custom():
    c = ScraperConfig(scrape_menus=True, max_menus=5)
    assert c.scrape_menus is True
    assert c.max_menus == 5


def test_scraper_result_defaults():
    r = ScraperResult(records_saved=2)
    assert r.menu_items_saved == 0


def test_run_trigger_in_defaults():
    body = RunTriggerIn()
    assert body.scrape_menus is False
    assert body.max_menus == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py -v
```

Expected: `ImportError` or `AttributeError` — `RunTriggerIn` not yet defined.

- [ ] **Step 3: Update models.py**

In `backend/models.py`, update `ScraperConfig`, `ScraperResult`, and add `RunTriggerIn`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel


# ── Scraper interface ──────────────────────────────────────────────────────────

@dataclass
class ScraperConfig:
    address: str = "Pl. Poelaert 1, 1000 Bruxelles"
    target: str | None = None
    max_items: int = 50
    scrape_menus: bool = False
    max_menus: int = 3


@dataclass
class ScraperResult:
    records_saved: int
    restaurants: list[dict] = field(default_factory=list)
    menu_items_saved: int = 0


# ── API request models ─────────────────────────────────────────────────────────

class RunTriggerIn(BaseModel):
    scrape_menus: bool = False
    max_menus: int = 3


# ── API response models ────────────────────────────────────────────────────────

class ScraperRunOut(BaseModel):
    id: str
    platform: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    records_saved: int = 0
    error_msg: str | None = None


class ScraperStatusOut(BaseModel):
    platform: str
    status: str        # "idle" | "running" | "success" | "failed" | "blocked"
    last_run: ScraperRunOut | None = None


class ScheduleConfigIn(BaseModel):
    platform: str
    cron: str          # e.g. "0 */6 * * *"
    enabled: bool = True


class ScheduleConfigOut(ScheduleConfigIn):
    next_run: datetime | None = None


class RestaurantOut(BaseModel):
    id: str
    name: str
    slug: str
    cuisine: str | None = None
    neighborhood: str | None = None


class MenuItemOut(BaseModel):
    id: str
    listing_id: str
    title: str
    price: float | None = None
    catalog_name: str | None = None


class RunTriggerOut(BaseModel):
    run_id: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/tests/test_menu_scraping.py
git commit -m "feat: add scrape_menus config + RunTriggerIn model"
```

---

## Task 2: Add shared price parser to base.py

**Files:**
- Modify: `backend/scrapers/base.py`
- Test: `backend/tests/test_menu_scraping.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_menu_scraping.py`:

```python
from scrapers.base import parse_menu_price


def test_parse_menu_price_euro_prefix():
    assert parse_menu_price("€ 5.99") == 5.99


def test_parse_menu_price_euro_suffix():
    assert parse_menu_price("5,99 €") == 5.99


def test_parse_menu_price_plain_float():
    assert parse_menu_price(5.99) == 5.99


def test_parse_menu_price_none():
    assert parse_menu_price(None) is None


def test_parse_menu_price_free():
    assert parse_menu_price("Gratuit") == 0.0


def test_parse_menu_price_cents_int():
    # UberEats sometimes gives price as integer cents (599 = €5.99)
    assert parse_menu_price(599, is_cents=True) == 5.99
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py::test_parse_menu_price_euro_prefix -v
```

Expected: `ImportError` — `parse_menu_price` not yet defined.

- [ ] **Step 3: Add parse_menu_price to base.py**

Open `backend/scrapers/base.py` and append at the end:

```python
import re as _re


def parse_menu_price(val: str | float | int | None, *, is_cents: bool = False) -> float | None:
    """Parse a price value from various formats into a float (EUR).

    Handles: '€5.99', '5,99 €', 'Gratuit', plain float/int, and integer cents
    when is_cents=True (UberEats priceDoubleCents field).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if is_cents:
            return round(val / 100, 2)
        return float(val)
    low = str(val).lower()
    if any(w in low for w in ("gratuit", "free", "gratis", "0,00", "0.00")):
        return 0.0
    m = _re.search(r"(\d+)[,.](\d{2})", str(val))
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = _re.search(r"(\d+)", str(val))
    return float(m.group(1)) if m else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scrapers/base.py backend/tests/test_menu_scraping.py
git commit -m "feat: add parse_menu_price shared helper"
```

---

## Task 3: Update router to accept RunTriggerIn body

**Files:**
- Modify: `backend/routers/scrapers.py`
- Test: `backend/tests/test_menu_scraping.py`

- [ ] **Step 1: Add failing test**

Append to `backend/tests/test_menu_scraping.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@patch("routers.scrapers.db")
@patch("routers.scrapers.ws_mod")
def test_trigger_run_passes_scrape_menus_to_config(mock_ws, mock_db):
    mock_db.create_run.return_value = "run-1"
    mock_ws.make_log_fn.return_value = lambda msg: None
    mock_ws.send_done = AsyncMock()

    captured_config: list = []

    async def fake_scraper(config, log_fn):
        captured_config.append(config)
        return __import__("models").ScraperResult(records_saved=1)

    with patch("routers.scrapers.SCRAPERS", {"ubereats": fake_scraper}):
        from main import app
        client = TestClient(app)
        resp = client.post(
            "/api/scrapers/ubereats/run",
            json={"scrape_menus": True, "max_menus": 5},
        )
        assert resp.status_code == 200

    # Config is captured asynchronously; we just check the response shape
    assert "run_id" in resp.json()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py::test_trigger_run_passes_scrape_menus_to_config -v
```

Expected: FAIL — router ignores body, or `422 Unprocessable Entity` with body sent.

- [ ] **Step 3: Update routers/scrapers.py**

Replace `backend/routers/scrapers.py` with:

```python
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from models import RunTriggerOut, RunTriggerIn, ScraperStatusOut, ScraperConfig
import db
import ws as ws_mod
from scrapers import ubereats, deliveroo, takeaway
from scrapers.base import CloudflareBlockedError

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

SCRAPERS = {
    "ubereats": ubereats.run,
    "deliveroo": deliveroo.run,
    "takeaway": takeaway.run,
}

# Track currently running platforms
_running: set[str] = set()


@router.post("/{platform}/run", response_model=RunTriggerOut)
async def trigger_run(platform: str, body: RunTriggerIn = RunTriggerIn()):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    if platform in _running:
        raise HTTPException(409, f"{platform} scraper already running")

    run_id = db.create_run(platform)
    log_fn = ws_mod.make_log_fn(run_id)

    async def _run():
        _running.add(platform)
        try:
            config = ScraperConfig(
                scrape_menus=body.scrape_menus,
                max_menus=body.max_menus,
            )
            result = await SCRAPERS[platform](config, log_fn)
            db.finish_run(run_id, "success", records_saved=result.records_saved)
            await ws_mod.send_done(run_id, result.records_saved)
        except CloudflareBlockedError as e:
            db.finish_run(run_id, "blocked", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
        finally:
            _running.discard(platform)

    asyncio.create_task(_run())
    return RunTriggerOut(run_id=run_id)


@router.get("/status", response_model=list[ScraperStatusOut])
async def get_status():
    last_runs = db.get_last_run_per_platform()
    result = []
    for platform in ("ubereats", "deliveroo", "takeaway"):
        last = last_runs.get(platform)
        status = "running" if platform in _running else (last["status"] if last else "idle")
        result.append(ScraperStatusOut(
            platform=platform,
            status=status,
            last_run=last,
        ))
    return result
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/scrapers.py backend/tests/test_menu_scraping.py
git commit -m "feat: router accepts scrape_menus body param"
```

---

## Task 4: UberEats menu scraping

**Files:**
- Modify: `backend/scrapers/ubereats.py`
- Test: `backend/tests/test_menu_scraping.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_menu_scraping.py`:

```python
import json
from scrapers.ubereats import _parse_ue_menu


def test_parse_ue_menu_sections_format():
    payload = {
        "data": {
            "sections": [
                {
                    "title": {"text": "Burgers"},
                    "payload": {
                        "standardItemsPayload": {
                            "catalogItems": [
                                {
                                    "title": {"text": "Big Mac"},
                                    "itemDescription": {"text": "Two beef patties"},
                                    "price": {"price": "5.99"},
                                },
                                {
                                    "title": {"text": "McChicken"},
                                    "price": {"price": "4.49"},
                                },
                            ]
                        }
                    },
                }
            ]
        }
    }
    items = _parse_ue_menu(json.dumps(payload))
    assert len(items) == 2
    assert items[0] == {"title": "Big Mac", "price": 5.99, "catalog_name": "Burgers"}
    assert items[1] == {"title": "McChicken", "price": 4.49, "catalog_name": "Burgers"}


def test_parse_ue_menu_cents_format():
    payload = {
        "data": {
            "sections": [
                {
                    "title": {"text": "Sides"},
                    "payload": {
                        "standardItemsPayload": {
                            "catalogItems": [
                                {
                                    "title": {"text": "Fries"},
                                    "priceDoubleCents": 299,
                                }
                            ]
                        }
                    },
                }
            ]
        }
    }
    items = _parse_ue_menu(json.dumps(payload))
    assert items[0]["price"] == 2.99


def test_parse_ue_menu_empty_returns_empty():
    assert _parse_ue_menu("{}") == []
    assert _parse_ue_menu("not json") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py::test_parse_ue_menu_sections_format -v
```

Expected: `ImportError` — `_parse_ue_menu` not yet defined.

- [ ] **Step 3: Add _parse_ue_menu and scrape_menu_page to ubereats.py**

Add these functions before the existing `_parse_fee` helper at the bottom of `backend/scrapers/ubereats.py`:

```python
def _parse_ue_menu(text: str) -> list[dict]:
    """Parse UberEats getSectionFeedV1/getStoreV1 JSON into menu items."""
    from scrapers.base import parse_menu_price
    try:
        data = json.loads(text)
    except Exception:
        return []

    # Normalise to top-level sections list
    root = data.get("data") or data
    sections = (
        root.get("sections")
        or (root.get("store") or {}).get("sections")
        or []
    )

    items: list[dict] = []
    for section in sections:
        title_obj = section.get("title") or {}
        section_name: str | None = title_obj.get("text") if isinstance(title_obj, dict) else str(title_obj) or None
        payload = (section.get("payload") or {}).get("standardItemsPayload") or {}
        catalog_items = payload.get("catalogItems") or []
        for ci in catalog_items:
            title_obj2 = ci.get("title") or {}
            title: str = title_obj2.get("text", "") if isinstance(title_obj2, dict) else str(title_obj2)
            if not title:
                continue
            price_obj = ci.get("price") or {}
            price_str = price_obj.get("price") if isinstance(price_obj, dict) else None
            price_cents = ci.get("priceDoubleCents")
            if price_cents is not None:
                price = parse_menu_price(price_cents, is_cents=True)
            else:
                price = parse_menu_price(price_str)
            items.append({"title": title, "price": price, "catalog_name": section_name})

    return items


async def scrape_menu_page(page, listing_id: str, url: str, log_fn) -> int:
    """Navigate to restaurant page, intercept menu API, save items. Returns count."""
    log_fn(f"  Menu: {url}")
    menu_raw: list[str] = []

    async def _on_response(response):
        if menu_raw:
            return
        if any(k in response.url for k in ("getSectionFeedV1", "getStoreV1", "getCatalogV1")):
            try:
                menu_raw.append(await response.text())
            except Exception:
                pass

    page.on("response", _on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        deadline = asyncio.get_event_loop().time() + 12
        while not menu_raw and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)

        items = _parse_ue_menu(menu_raw[0]) if menu_raw else []
        if not items:
            log_fn("  No menu items captured via API")
            return 0

        count = db.insert_menu_items(listing_id, items)
        log_fn(f"  Saved {count} menu items")
        return count
    except Exception as e:
        log_fn(f"  Menu scrape error: {e}")
        return 0
    finally:
        page.remove_listener("response", _on_response)
```

- [ ] **Step 4: Update run() in ubereats.py to call phase 2**

In the `run()` function, replace the existing listing-save loop with one that also collects `(listing_id, url)`:

```python
        log_fn(f"Saving {len(restaurants)} restaurants...")
        saved_listings: list[tuple[str, str]] = []  # (listing_id, url)
        for r in restaurants[:config.max_items]:
            slug = (r.get("url") or "").split("/store/")[-1].strip("/") or r["name"].lower().replace(" ", "-")
            rid = db.upsert_restaurant({
                "name": r["name"],
                "slug": slug,
                "lat": r.get("lat"),
                "lng": r.get("lng"),
            })
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "uber_eats",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "delivery_fee": r.get("delivery_fee"),
                "discount_label": r.get("discount"),
            })
            records_saved += 1
            if r.get("url"):
                saved_listings.append((lid, r["url"]))

        menu_items_saved = 0
        if config.scrape_menus:
            log_fn(f"Phase 2: scraping menus for up to {config.max_menus} restaurants...")
            for listing_id, url in saved_listings[:config.max_menus]:
                menu_items_saved += await scrape_menu_page(page, listing_id, url, log_fn)

        log_fn(f"Done — {records_saved} records, {menu_items_saved} menu items saved")
        return ScraperResult(records_saved=records_saved, restaurants=restaurants, menu_items_saved=menu_items_saved)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scrapers/ubereats.py backend/tests/test_menu_scraping.py
git commit -m "feat: UberEats menu scraping phase 2"
```

---

## Task 5: Deliveroo menu scraping

**Files:**
- Modify: `backend/scrapers/deliveroo.py`
- Test: `backend/tests/test_menu_scraping.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_menu_scraping.py`:

```python
from scrapers.deliveroo import _parse_dom_items as deliveroo_parse


def test_deliveroo_parse_dom_items_basic():
    raw = [
        {"title": "Big Mac", "price_text": "€ 5,99", "catalog_name": "Burgers"},
        {"title": "McChicken", "price_text": "4.49 €", "catalog_name": "Burgers"},
    ]
    items = deliveroo_parse(raw)
    assert items[0] == {"title": "Big Mac", "price": 5.99, "catalog_name": "Burgers"}
    assert items[1] == {"title": "McChicken", "price": 4.49, "catalog_name": "Burgers"}


def test_deliveroo_parse_dom_items_missing_price():
    raw = [{"title": "Water", "price_text": None, "catalog_name": "Drinks"}]
    items = deliveroo_parse(raw)
    assert items[0]["price"] is None


def test_deliveroo_parse_dom_items_skips_no_title():
    raw = [{"title": "", "price_text": "€1.00", "catalog_name": "x"}]
    items = deliveroo_parse(raw)
    assert items == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py::test_deliveroo_parse_dom_items_basic -v
```

Expected: `ImportError`.

- [ ] **Step 3: Add _parse_dom_items and scrape_menu_page to deliveroo.py**

Add after the existing `_parse_fee` helper at the bottom of `backend/scrapers/deliveroo.py`:

```python
# JS evaluated on the restaurant menu page to extract items
_MENU_JS = """() => {
    const priceRe = /€\\s*\\d+|\\d+[,.]\\d+\\s*€/;
    const seen = new Set();
    const items = [];
    document.querySelectorAll(
        'li, article, [data-testid*="item"], [data-testid*="MenuItem"], [data-testid*="Item"]'
    ).forEach(card => {
        const text = card.innerText || '';
        if (!priceRe.test(text)) return;
        const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
        const priceIdx = lines.findIndex(l => priceRe.test(l));
        if (priceIdx < 0) return;
        const title = lines.slice(0, priceIdx).find(l => l.length > 2 && l.length < 100 && !priceRe.test(l));
        if (!title || seen.has(title)) return;
        seen.add(title);
        items.push({title, price_text: lines[priceIdx], catalog_name: null});
    });
    return items;
}"""


def _parse_dom_items(raw: list[dict]) -> list[dict]:
    """Normalise JS-eval DOM output into DB-ready dicts."""
    from scrapers.base import parse_menu_price
    result = []
    for r in raw:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        result.append({
            "title": title,
            "price": parse_menu_price(r.get("price_text")),
            "catalog_name": r.get("catalog_name") or None,
        })
    return result


async def scrape_menu_page(page, listing_id: str, url: str, log_fn) -> int:
    """Navigate to restaurant menu page, scrape items via DOM eval. Returns count."""
    log_fn(f"  Menu: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Scroll once to trigger lazy-loaded items
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 2000)")
            await asyncio.sleep(0.5)
        raw: list[dict] = await page.evaluate(_MENU_JS)
        items = _parse_dom_items(raw)
        if not items:
            log_fn("  No menu items found")
            return 0
        count = db.insert_menu_items(listing_id, items)
        log_fn(f"  Saved {count} menu items")
        return count
    except Exception as e:
        log_fn(f"  Menu scrape error: {e}")
        return 0
```

- [ ] **Step 4: Update run() in deliveroo.py to call phase 2**

Replace the listing-save loop with one that collects `(listing_id, url)`:

```python
        saved_listings: list[tuple[str, str]] = []
        for r in restaurants[:config.max_items]:
            rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"]})
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "deliveroo",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "discount_label": r.get("discount"),
            })
            records_saved += 1
            if r.get("url"):
                saved_listings.append((lid, r["url"]))

        menu_items_saved = 0
        if config.scrape_menus:
            log_fn(f"Phase 2: scraping menus for up to {config.max_menus} restaurants...")
            for listing_id, url in saved_listings[:config.max_menus]:
                menu_items_saved += await scrape_menu_page(page, listing_id, url, log_fn)

        log_fn(f"Done — {records_saved} records, {menu_items_saved} menu items saved")
        return ScraperResult(records_saved=records_saved, restaurants=restaurants, menu_items_saved=menu_items_saved)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scrapers/deliveroo.py backend/tests/test_menu_scraping.py
git commit -m "feat: Deliveroo menu scraping phase 2"
```

---

## Task 6: Takeaway menu scraping

**Files:**
- Modify: `backend/scrapers/takeaway.py`
- Test: `backend/tests/test_menu_scraping.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_menu_scraping.py`:

```python
from scrapers.takeaway import _parse_dom_items as takeaway_parse


def test_takeaway_parse_dom_items_basic():
    raw = [
        {"title": "Shoarma", "price_text": "9,50 €", "catalog_name": "Grillades"},
    ]
    items = takeaway_parse(raw)
    assert items[0] == {"title": "Shoarma", "price": 9.50, "catalog_name": "Grillades"}


def test_takeaway_parse_dom_items_free():
    raw = [{"title": "Sauce", "price_text": "Gratuit", "catalog_name": None}]
    items = takeaway_parse(raw)
    assert items[0]["price"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_menu_scraping.py::test_takeaway_parse_dom_items_basic -v
```

Expected: `ImportError`.

- [ ] **Step 3: Add _parse_dom_items and scrape_menu_page to takeaway.py**

Add after the existing `_parse_fee` helper at the bottom of `backend/scrapers/takeaway.py`:

```python
# JS evaluated on the restaurant menu page
_MENU_JS = """() => {
    const priceRe = /€\\s*\\d+|\\d+[,.]\\d+\\s*€|gratuit/i;
    const seen = new Set();
    const items = [];
    document.querySelectorAll(
        '[data-qa*="product"], [data-testid*="product"], [data-testid*="item"], li, article'
    ).forEach(card => {
        const text = card.innerText || '';
        if (!priceRe.test(text)) return;
        const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
        const priceIdx = lines.findIndex(l => priceRe.test(l));
        if (priceIdx < 0) return;
        const title = lines.slice(0, priceIdx).find(l => l.length > 2 && l.length < 100 && !priceRe.test(l));
        if (!title || seen.has(title)) return;
        seen.add(title);
        items.push({title, price_text: lines[priceIdx], catalog_name: null});
    });
    return items;
}"""


def _parse_dom_items(raw: list[dict]) -> list[dict]:
    """Normalise JS-eval DOM output into DB-ready dicts."""
    from scrapers.base import parse_menu_price
    result = []
    for r in raw:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        result.append({
            "title": title,
            "price": parse_menu_price(r.get("price_text")),
            "catalog_name": r.get("catalog_name") or None,
        })
    return result


async def scrape_menu_page(page, listing_id: str, url: str, log_fn) -> int:
    """Navigate to restaurant menu page, scrape items via DOM eval. Returns count."""
    log_fn(f"  Menu: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 2000)")
            await asyncio.sleep(0.5)
        raw: list[dict] = await page.evaluate(_MENU_JS)
        items = _parse_dom_items(raw)
        if not items:
            log_fn("  No menu items found")
            return 0
        count = db.insert_menu_items(listing_id, items)
        log_fn(f"  Saved {count} menu items")
        return count
    except Exception as e:
        log_fn(f"  Menu scrape error: {e}")
        return 0
```

- [ ] **Step 4: Update run() in takeaway.py to call phase 2**

Replace the listing-save loop with one that collects `(listing_id, url)`:

```python
        saved_listings: list[tuple[str, str]] = []
        for r in unique[:config.max_items]:
            rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"]})
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "takeaway",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "delivery_fee": _parse_fee(r.get("delivery_fee")),
                "discount_label": r.get("discount"),
            })
            records_saved += 1
            if r.get("url"):
                saved_listings.append((lid, r["url"]))

        menu_items_saved = 0
        if config.scrape_menus:
            log_fn(f"Phase 2: scraping menus for up to {config.max_menus} restaurants...")
            for listing_id, url in saved_listings[:config.max_menus]:
                menu_items_saved += await scrape_menu_page(page, listing_id, url, log_fn)

        log_fn(f"Done — {records_saved} records, {menu_items_saved} menu items saved")
        return ScraperResult(records_saved=records_saved, restaurants=unique, menu_items_saved=menu_items_saved)
```

- [ ] **Step 5: Run all tests**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scrapers/takeaway.py backend/tests/test_menu_scraping.py
git commit -m "feat: Takeaway menu scraping phase 2"
```

---

## Task 7: Smoke-test end-to-end with max_menus=1

This task runs a real scraper with `scrape_menus=True, max_menus=1` to verify the pipeline works live.

**Prerequisite:** Backend `.env` present with `SUPABASE_URL` + `SUPABASE_KEY`. Chromium installed (`uv run playwright install chromium`).

- [ ] **Step 1: Start backend**

```bash
cd backend && uv run uvicorn main:app --reload
```

- [ ] **Step 2: Trigger UberEats run with menu scraping**

In a separate terminal:

```bash
curl -X POST http://localhost:8000/api/scrapers/ubereats/run \
  -H "Content-Type: application/json" \
  -d '{"scrape_menus": true, "max_menus": 1}'
```

Expected response: `{"run_id": "<uuid>"}`.

- [ ] **Step 3: Watch logs via WebSocket** (or check Supabase dashboard)

```bash
# Watch run status until finished
watch -n2 'curl -s http://localhost:8000/api/runs | python3 -m json.tool | head -30'
```

Wait for `status: "success"`.

- [ ] **Step 4: Verify menu_items in DB**

Query Supabase directly (uses service key from `.env`):

```bash
cd backend && uv run python3 -c "
import db
client = db.get_client()
rows = client.table('menu_items').select('title,price,catalog_name,listing_id').limit(10).execute().data
for r in rows: print(r)
"
```

Expected: at least 1 row with `title` and `price` populated.

If no items: check run logs for `"No menu items captured via API"` — the UberEats API interception may need selector adjustment. See troubleshooting note below.

> **Troubleshooting:** If UberEats API interception returns 0 items, open DevTools Network on a UberEats restaurant page and look for XHR requests. Find the one returning menu JSON and update the `getSectionFeedV1`/`getStoreV1` URL filter in `scrape_menu_page` to match the actual endpoint name.

- [ ] **Step 5: Commit**

No code changes expected — this is a verification step.
