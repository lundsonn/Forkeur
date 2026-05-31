# Forkeur Scraper Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python FastAPI backend + React dashboard to schedule, trigger, monitor, and review the 3 Forkeur food delivery scrapers (UberEats, Deliveroo, Takeaway) with live log streaming and Supabase data storage.

**Architecture:** FastAPI + APScheduler runs in a single asyncio process on localhost:8000. Playwright scrapers are pure Python async functions called directly (no subprocesses). A Vite React dashboard on :5173 (dev) or served from FastAPI (prod) connects via WebSocket for live log streaming.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, APScheduler, Playwright (async), supabase-py, uv, React 18, TypeScript, Tailwind CSS, Vite

---

## File Map

```
food-price-compare/
├── Makefile
├── backend/
│   ├── pyproject.toml
│   ├── main.py
│   ├── models.py
│   ├── db.py
│   ├── ws.py
│   ├── scheduler.py
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── ubereats.py
│   │   ├── deliveroo.py
│   │   └── takeaway.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── scrapers.py
│   │   ├── runs.py
│   │   ├── schedule.py
│   │   └── data.py
│   └── dashboard/          ← Vite React app (created via npm create vite)
│       ├── package.json
│       ├── vite.config.ts
│       └── src/
│           ├── main.tsx
│           ├── App.tsx
│           ├── api.ts
│           ├── types.ts
│           ├── components/
│           │   ├── Sidebar.tsx
│           │   ├── ScraperCard.tsx
│           │   └── LogDrawer.tsx
│           └── pages/
│               ├── Dashboard.tsx
│               ├── Scrapers.tsx
│               ├── History.tsx
│               ├── Schedule.tsx
│               └── Data.tsx
└── supabase/
    └── migrations/
        └── 002_scraper_runs.sql
```

---

## Task 1: DB Migration — `scraper_runs` table

**Files:**
- Create: `supabase/migrations/002_scraper_runs.sql`

- [ ] **Step 1: Write migration file**

```sql
-- supabase/migrations/002_scraper_runs.sql
create table scraper_runs (
  id            uuid primary key default gen_random_uuid(),
  platform      text not null check (platform in ('ubereats', 'deliveroo', 'takeaway')),
  status        text not null check (status in ('running', 'success', 'failed', 'blocked', 'partial')),
  started_at    timestamptz default now(),
  finished_at   timestamptz,
  records_saved integer default 0,
  error_msg     text
);

create index on scraper_runs (platform);
create index on scraper_runs (status);
create index on scraper_runs (started_at desc);

alter table scraper_runs enable row level security;
create policy "anon can read scraper_runs"
  on scraper_runs for select to anon using (true);
```

- [ ] **Step 2: Apply migration via Supabase MCP**

Use `mcp__supabase__apply_migration` with name `002_scraper_runs` and the SQL above.

- [ ] **Step 3: Verify table exists**

Use `mcp__supabase__list_tables` and confirm `scraper_runs` appears with `rls_enabled: true`.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/002_scraper_runs.sql
git commit -m "feat: add scraper_runs migration"
```

---

## Task 2: Python project scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env` (template only — no secrets committed)
- Create: `Makefile`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "forkeur-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.111.0",
  "uvicorn[standard]>=0.29.0",
  "apscheduler>=3.10.4",
  "playwright>=1.44.0",
  "supabase>=2.4.0",
  "python-dotenv>=1.0.1",
  "pydantic>=2.7.0",
]

[tool.uv]
dev-dependencies = [
  "pytest>=8.2.0",
  "pytest-asyncio>=0.23.0",
  "httpx>=0.27.0",
]
```

- [ ] **Step 2: Create `backend/.env.example`**

```
SUPABASE_URL=https://ltpicouyzdmamblzwcgc.supabase.co
SUPABASE_KEY=your_anon_key_here
```

- [ ] **Step 3: Create `Makefile` at repo root**

```makefile
.PHONY: install dev build prod

install:
	cd backend && uv sync
	cd backend/dashboard && npm install
	cd backend && uv run playwright install chromium

dev:
	cd backend && uv run uvicorn main:app --reload --port 8000 &
	cd backend/dashboard && npm run dev

build:
	cd backend/dashboard && npm run build

prod:
	cd backend && uv run uvicorn main:app --port 8000
```

- [ ] **Step 4: Run install to verify uv works**

```bash
cd backend && uv sync
```

Expected: lockfile created, dependencies installed.

- [ ] **Step 5: Install Playwright chromium**

```bash
cd backend && uv run playwright install chromium
```

Expected: `Chromium ... downloaded` in output.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/.env.example Makefile
git commit -m "feat: scaffold Python backend project"
```

---

## Task 3: Models and DB client

**Files:**
- Create: `backend/models.py`
- Create: `backend/db.py`

- [ ] **Step 1: Create `backend/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from pydantic import BaseModel


# ── Scraper interface ──────────────────────────────────────────────────────────

@dataclass
class ScraperConfig:
    address: str = "Pl. Poelaert 1, 1000 Bruxelles"
    target: str | None = None
    max_items: int = 50


@dataclass
class ScraperResult:
    records_saved: int
    restaurants: list[dict] = field(default_factory=list)


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

- [ ] **Step 2: Create `backend/db.py`**

```python
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


def upsert_restaurant(data: dict) -> str:
    """Upsert restaurant by slug. Returns id."""
    client = get_client()
    res = (
        client.table("restaurants")
        .upsert(data, on_conflict="slug")
        .execute()
    )
    return res.data[0]["id"]


def upsert_listing(data: dict) -> str:
    """Upsert platform_listing by restaurant_id + platform. Returns id."""
    client = get_client()
    existing = (
        client.table("platform_listings")
        .select("id")
        .eq("restaurant_id", data["restaurant_id"])
        .eq("platform", data["platform"])
        .execute()
    )
    if existing.data:
        lid = existing.data[0]["id"]
        client.table("platform_listings").update(data).eq("id", lid).execute()
        return lid
    res = client.table("platform_listings").insert(data).execute()
    return res.data[0]["id"]


def insert_menu_items(listing_id: str, items: list[dict]) -> int:
    """Delete existing items for listing, insert new ones. Returns count."""
    client = get_client()
    client.table("menu_items").delete().eq("listing_id", listing_id).execute()
    if not items:
        return 0
    rows = [{**item, "listing_id": listing_id} for item in items]
    res = client.table("menu_items").insert(rows).execute()
    return len(res.data)


def create_run(platform: str) -> str:
    """Insert a scraper_run row with status=running. Returns run id."""
    client = get_client()
    res = (
        client.table("scraper_runs")
        .insert({"platform": platform, "status": "running"})
        .execute()
    )
    return res.data[0]["id"]


def finish_run(run_id: str, status: str, records_saved: int = 0, error_msg: str | None = None) -> None:
    client = get_client()
    from datetime import datetime, timezone
    client.table("scraper_runs").update({
        "status": status,
        "records_saved": records_saved,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "error_msg": error_msg,
    }).eq("id", run_id).execute()


def get_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    client = get_client()
    res = (
        client.table("scraper_runs")
        .select("*")
        .order("started_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data


def get_run(run_id: str) -> dict | None:
    client = get_client()
    res = client.table("scraper_runs").select("*").eq("id", run_id).execute()
    return res.data[0] if res.data else None


def get_last_run_per_platform() -> dict[str, dict]:
    """Returns {platform: run_row} for the most recent run of each platform."""
    client = get_client()
    result = {}
    for platform in ("ubereats", "deliveroo", "takeaway"):
        res = (
            client.table("scraper_runs")
            .select("*")
            .eq("platform", platform)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            result[platform] = res.data[0]
    return result


def get_restaurants(limit: int = 100, offset: int = 0, search: str | None = None) -> list[dict]:
    client = get_client()
    q = client.table("restaurants").select("*").range(offset, offset + limit - 1)
    if search:
        q = q.ilike("name", f"%{search}%")
    return q.execute().data


def get_menu_items(listing_id: str) -> list[dict]:
    client = get_client()
    return (
        client.table("menu_items")
        .select("*")
        .eq("listing_id", listing_id)
        .execute()
        .data
    )
```

- [ ] **Step 3: Write tests for db helpers (mock Supabase)**

Create `backend/tests/test_db.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


@patch("db.get_client")
def test_create_run_returns_id(mock_get_client):
    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123", "platform": "ubereats", "status": "running"}
    ]
    mock_get_client.return_value = mock_client

    import db
    run_id = db.create_run("ubereats")
    assert run_id == "abc-123"


@patch("db.get_client")
def test_finish_run_updates_status(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    import db
    db.finish_run("abc-123", "success", records_saved=42)

    update_call = mock_client.table.return_value.update.call_args[0][0]
    assert update_call["status"] == "success"
    assert update_call["records_saved"] == 42
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_db.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/db.py backend/tests/test_db.py
git commit -m "feat: add models and db client"
```

---

## Task 4: Scraper base + CloudflareBlockedError

**Files:**
- Create: `backend/scrapers/__init__.py`
- Create: `backend/scrapers/base.py`

- [ ] **Step 1: Create `backend/scrapers/__init__.py`** (empty)

- [ ] **Step 2: Create `backend/scrapers/base.py`**

```python
from __future__ import annotations
from typing import Callable
from playwright.async_api import async_playwright, Browser, Page


class CloudflareBlockedError(Exception):
    pass


async def new_browser(lang: str = "fr-BE") -> Browser:
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=["--no-sandbox", f"--lang={lang}"],
    )
    return browser


async def new_page(browser: Browser, lang: str = "fr-BE") -> Page:
    page = await browser.new_page(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        extra_http_headers={"Accept-Language": f"{lang},{lang[:2]};q=0.9"},
    )
    return page


def check_cloudflare(title: str) -> None:
    """Raise CloudflareBlockedError if Cloudflare challenge page detected."""
    lower = title.lower()
    if "just a moment" in lower or "cloudflare" in lower:
        raise CloudflareBlockedError("Cloudflare challenge detected")


def noop_log(line: str) -> None:
    pass
```

- [ ] **Step 3: Write test**

Create `backend/tests/test_base.py`:

```python
import pytest
from scrapers.base import check_cloudflare, CloudflareBlockedError


def test_check_cloudflare_raises_on_challenge():
    with pytest.raises(CloudflareBlockedError):
        check_cloudflare("Just a moment...")


def test_check_cloudflare_passes_on_normal_title():
    check_cloudflare("Uber Eats Belgium")  # should not raise
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_base.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/scrapers/ backend/tests/test_base.py
git commit -m "feat: add scraper base and CloudflareBlockedError"
```

---

## Task 5: UberEats scraper (Python)

**Files:**
- Create: `backend/scrapers/ubereats.py`

- [ ] **Step 1: Create `backend/scrapers/ubereats.py`**

```python
from __future__ import annotations
import asyncio
import json
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, check_cloudflare, noop_log
import db


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting UberEats scraper")
    browser = await new_browser(lang="fr-BE")
    records_saved = 0

    try:
        page = await new_page(browser, lang="fr-BE")

        feed_raw: list[str] = []

        async def on_response(response):
            if "getFeedV1" in response.url and not feed_raw:
                try:
                    text = await response.text()
                    feed_raw.append(text)
                except Exception:
                    pass

        page.on("response", on_response)

        log_fn("Loading ubereats.com/be-fr...")
        await page.goto("https://www.ubereats.com/be-fr", wait_until="networkidle", timeout=30000)
        check_cloudflare(await page.title())
        log_fn("Page loaded")

        # Click Find food button
        await page.evaluate("""() => {
            const b = Array.from(document.querySelectorAll('a, button')).find(
                b => b.textContent.includes('Find food') || b.textContent.includes('Trouver')
            );
            if (b) b.click();
        }""")
        await asyncio.sleep(1.2)

        # Type address
        input_sel = "#location-typeahead-home-input"
        await page.wait_for_selector(input_sel, timeout=8000)
        await page.click(input_sel)
        await page.type(input_sel, config.address, delay=60)
        await asyncio.sleep(2.5)
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.4)
        await page.keyboard.press("Enter")

        log_fn("Waiting for feed API response...")
        deadline = asyncio.get_event_loop().time() + 15
        while not feed_raw and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)

        if not feed_raw:
            raise TimeoutError("Feed API not captured")

        feed = json.loads(feed_raw[0])
        feed_items = feed.get("data", {}).get("feedItems", [])
        stores = [i for i in feed_items if i.get("type") == "REGULAR_STORE"]
        log_fn(f"Feed: {len(stores)} restaurants")

        restaurants = []
        for item in stores:
            s = item.get("store", {})
            meta = s.get("meta", [])
            fare_meta = next((m for m in meta if m.get("badgeType") == "FARE"), None)
            eta_meta = next((m for m in meta if m.get("badgeType") == "ETD"), None)
            restaurants.append({
                "name": (s.get("title") or {}).get("text", "Unknown"),
                "url": f"https://www.ubereats.com{s['actionUrl'].split('?')[0]}" if s.get("actionUrl") else None,
                "store_uuid": s.get("storeUuid") or item.get("uuid"),
                "rating": (s.get("rating") or {}).get("text", "N/A"),
                "delivery_fee": (fare_meta or {}).get("text"),
                "eta": (eta_meta or {}).get("text", "N/A"),
            })

        if config.target:
            restaurants = [r for r in restaurants if config.target.lower() in r["name"].lower()]

        log_fn(f"Saving {len(restaurants)} restaurants...")
        for r in restaurants[:config.max_items]:
            slug = (r.get("url") or "").split("/store/")[-1].strip("/") or r["name"].lower().replace(" ", "-")
            rid = db.upsert_restaurant({"name": r["name"], "slug": slug})
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "ubereats",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
            })
            records_saved += 1

        log_fn(f"Done — {records_saved} records saved")
        return ScraperResult(records_saved=records_saved, restaurants=restaurants)

    finally:
        await browser.close()


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    import re
    m = re.search(r"[\d.]+", str(val))
    return float(m.group()) if m else None


def _parse_eta_min(eta: str | None) -> int | None:
    if not eta:
        return None
    import re
    m = re.match(r"(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_eta_max(eta: str | None) -> int | None:
    if not eta:
        return None
    import re
    m = re.search(r"-(\d+)", eta.strip())
    return int(m.group(1)) if m else None
```

- [ ] **Step 2: Commit**

```bash
git add backend/scrapers/ubereats.py
git commit -m "feat: add UberEats Playwright scraper"
```

---

## Task 6: Deliveroo scraper (Python)

**Files:**
- Create: `backend/scrapers/deliveroo.py`

- [ ] **Step 1: Create `backend/scrapers/deliveroo.py`**

```python
from __future__ import annotations
import asyncio
import re
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, check_cloudflare, noop_log
import db


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Deliveroo scraper")
    browser = await new_browser(lang="en-GB")
    records_saved = 0

    try:
        page = await new_page(browser, lang="en-GB")

        log_fn("Opening deliveroo.be/en...")
        await page.goto("https://deliveroo.be/en", wait_until="networkidle", timeout=30000)
        check_cloudflare(await page.title())
        log_fn("Page loaded")

        input_sel = 'input[id="location-search"], input[placeholder*="address" i], input[placeholder*="adresse" i]'
        await page.wait_for_selector(input_sel, timeout=10000)
        await page.click(input_sel)
        await page.type(input_sel, config.address, delay=60)
        await asyncio.sleep(2.5)
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await asyncio.sleep(5)

        listing_url = page.url
        if "restaurants" not in listing_url:
            raise RuntimeError(f"Did not land on restaurant listing — got: {listing_url}")

        log_fn(f"Listing page: {listing_url}")
        await page.wait_for_selector('a[href*="/menu/"]', timeout=10000)

        for _ in range(10):
            await page.evaluate("window.scrollBy(0, 3000)")
            await asyncio.sleep(0.6)
        await asyncio.sleep(1)

        restaurants = await page.eval_on_selector_all('a[href*="/menu/"]', """anchors => {
            const seen = new Set();
            return anchors.filter(a => {
                const slug = (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1];
                if (!slug || seen.has(slug)) return false;
                seen.add(slug);
                return true;
            }).map(a => {
                const slug = (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
                let card = a;
                for (let i = 0; i < 8; i++) {
                    if (!card.parentElement) break;
                    card = card.parentElement;
                    if (card.tagName === 'LI' || card.tagName === 'ARTICLE') break;
                }
                const lines = (card.innerText || '').split('\\n').map(l => l.trim()).filter(Boolean);
                const ratingIdx = lines.findIndex(l => /^\\d[,.]\\d\\s+(Excellent|Good|Okay)/i.test(l));
                const ratingLine = ratingIdx >= 0 ? lines[ratingIdx] : null;
                const name = ratingIdx > 0 ? lines[ratingIdx - 1] : (lines.find(l => !l.match(/^\\d+\\s*min$/) && !l.includes('€') && l.length > 3) || slug);
                const ratingMatch = (ratingLine || '').match(/^(\\d[,.]\\d)/);
                const reviewMatch = (ratingLine || '').match(/\\((\\d[\\d.,]*\\+?)\\)/);
                const eta = lines.find(l => /^\\d+(-\\d+)?\\s*min$/i.test(l)) || 'N/A';
                return {
                    name,
                    url: a.href,
                    slug,
                    rating: ratingMatch ? ratingMatch[1] : 'N/A',
                    review_count: reviewMatch ? reviewMatch[1] : '',
                    eta,
                };
            });
        }""")

        log_fn(f"Found {len(restaurants)} restaurants")

        if config.target:
            restaurants = [r for r in restaurants if config.target.lower() in r["name"].lower() or config.target.lower() in r["slug"].lower()]

        for r in restaurants[:config.max_items]:
            rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"]})
            db.upsert_listing({
                "restaurant_id": rid,
                "platform": "deliveroo",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
            })
            records_saved += 1

        log_fn(f"Done — {records_saved} records saved")
        return ScraperResult(records_saved=records_saved, restaurants=restaurants)

    finally:
        await browser.close()


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    import re
    m = re.search(r"[\d.]+", str(val).replace(",", "."))
    return float(m.group()) if m else None


def _parse_eta_min(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.match(r"(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_eta_max(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.search(r"-(\d+)", eta.strip())
    return int(m.group(1)) if m else None
```

- [ ] **Step 2: Commit**

```bash
git add backend/scrapers/deliveroo.py
git commit -m "feat: add Deliveroo Playwright scraper"
```

---

## Task 7: Takeaway scraper (Python)

**Files:**
- Create: `backend/scrapers/takeaway.py`

- [ ] **Step 1: Create `backend/scrapers/takeaway.py`**

```python
from __future__ import annotations
import asyncio
import re
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, check_cloudflare, noop_log
import db

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Takeaway scraper")
    browser = await new_browser(lang="fr-BE")
    records_saved = 0

    try:
        page = await new_page(browser, lang="fr-BE")

        log_fn(f"Loading {LISTING_URL}...")
        await page.goto(LISTING_URL, wait_until="networkidle", timeout=30000)
        check_cloudflare(await page.title())
        log_fn("Page loaded")

        log_fn("Scrolling to load restaurants...")
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, 3000)")
            await asyncio.sleep(0.8)
        await asyncio.sleep(1)

        restaurants = await page.eval_on_selector_all('[data-qa="restaurant-card"]', """cards => {
            return cards.map(card => {
                const link = card.querySelector('a[href*="/menu/"]');
                const url = link ? link.href : '';
                const slug = (url.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
                const nameEl = card.querySelector('h2, h3, [data-qa*="name"]');
                const name = (nameEl && nameEl.textContent.trim()) || (link && link.textContent.trim()) || slug;
                const lines = (card.innerText || '').split('\\n').map(l => l.trim()).filter(Boolean);
                const rating = lines.find(l => /^\\d[,.]\\d$/.test(l)) || 'N/A';
                const reviewCount = (lines.find(l => /^\\(\\d[\\d.,]*\\+?\\)$/.test(l)) || '').replace(/[()]/g, '');
                const eta = lines.find(l => /\\d+-\\d+\\s*min/.test(l)) || 'N/A';
                return { name, url, slug, rating, review_count: reviewCount, eta };
            });
        }""")

        # Deduplicate by slug
        seen: set[str] = set()
        unique = []
        for r in restaurants:
            if r["slug"] and r["slug"] not in seen:
                seen.add(r["slug"])
                unique.append(r)

        log_fn(f"Found {len(unique)} unique restaurants")

        if config.target:
            unique = [r for r in unique if config.target.lower() in r["name"].lower() or config.target.lower() in r["slug"].lower()]

        for r in unique[:config.max_items]:
            rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"]})
            db.upsert_listing({
                "restaurant_id": rid,
                "platform": "takeaway",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
            })
            records_saved += 1

        log_fn(f"Done — {records_saved} records saved")
        return ScraperResult(records_saved=records_saved, restaurants=unique)

    finally:
        await browser.close()


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    m = re.search(r"[\d.]+", str(val).replace(",", "."))
    return float(m.group()) if m else None


def _parse_eta_min(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.match(r"(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_eta_max(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.search(r"-(\d+)", eta.strip())
    return int(m.group(1)) if m else None
```

- [ ] **Step 2: Commit**

```bash
git add backend/scrapers/takeaway.py
git commit -m "feat: add Takeaway Playwright scraper"
```

---

## Task 8: WebSocket log streamer

**Files:**
- Create: `backend/ws.py`

- [ ] **Step 1: Create `backend/ws.py`**

```python
from __future__ import annotations
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect

# run_id → asyncio.Queue of log lines
_queues: dict[str, asyncio.Queue] = {}


def get_or_create_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _queues:
        _queues[run_id] = asyncio.Queue()
    return _queues[run_id]


def make_log_fn(run_id: str):
    """Returns a log_fn callback that pushes lines into the run's queue."""
    queue = get_or_create_queue(run_id)

    def log_fn(line: str) -> None:
        try:
            queue.put_nowait({"type": "log", "line": line})
        except asyncio.QueueFull:
            pass

    return log_fn


async def send_done(run_id: str, records: int) -> None:
    queue = get_or_create_queue(run_id)
    await queue.put({"type": "done", "records": records})


async def send_error(run_id: str, msg: str) -> None:
    queue = get_or_create_queue(run_id)
    await queue.put({"type": "error", "msg": msg})


async def ws_endpoint(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    queue = get_or_create_queue(run_id)
    try:
        while True:
            msg = await asyncio.wait_for(queue.get(), timeout=120)
            await websocket.send_text(json.dumps(msg))
            if msg.get("type") in ("done", "error"):
                break
    except (asyncio.TimeoutError, WebSocketDisconnect):
        pass
    finally:
        _queues.pop(run_id, None)
        await websocket.close()
```

- [ ] **Step 2: Write test**

Create `backend/tests/test_ws.py`:

```python
import asyncio
import pytest
import ws


@pytest.mark.asyncio
async def test_make_log_fn_pushes_to_queue():
    log_fn = ws.make_log_fn("test-run-1")
    log_fn("hello world")
    queue = ws.get_or_create_queue("test-run-1")
    msg = queue.get_nowait()
    assert msg == {"type": "log", "line": "hello world"}


@pytest.mark.asyncio
async def test_send_done_puts_done_msg():
    await ws.send_done("test-run-2", records=42)
    queue = ws.get_or_create_queue("test-run-2")
    msg = queue.get_nowait()
    assert msg == {"type": "done", "records": 42}
```

- [ ] **Step 3: Run tests**

```bash
cd backend && uv run pytest tests/test_ws.py -v
```

Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/ws.py backend/tests/test_ws.py
git commit -m "feat: add WebSocket log streamer"
```

---

## Task 9: API routers

**Files:**
- Create: `backend/routers/__init__.py`
- Create: `backend/routers/scrapers.py`
- Create: `backend/routers/runs.py`
- Create: `backend/routers/schedule.py`
- Create: `backend/routers/data.py`

- [ ] **Step 1: Create `backend/routers/__init__.py`** (empty)

- [ ] **Step 2: Create `backend/routers/scrapers.py`**

```python
from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from models import RunTriggerOut, ScraperStatusOut, ScraperConfig
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
async def trigger_run(platform: str):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    if platform in _running:
        raise HTTPException(409, f"{platform} scraper already running")

    run_id = db.create_run(platform)
    log_fn = ws_mod.make_log_fn(run_id)

    async def _run():
        _running.add(platform)
        try:
            config = ScraperConfig()
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

- [ ] **Step 3: Create `backend/routers/runs.py`**

```python
from fastapi import APIRouter, HTTPException
from models import ScraperRunOut
import db

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[ScraperRunOut])
async def list_runs(limit: int = 50, offset: int = 0):
    return db.get_runs(limit=limit, offset=offset)


@router.get("/{run_id}", response_model=ScraperRunOut)
async def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run
```

- [ ] **Step 4: Create `backend/routers/schedule.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from models import ScheduleConfigIn, ScheduleConfigOut
from scheduler import add_or_update_schedule, remove_schedule, list_schedules

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleConfigOut])
async def get_schedules():
    return list_schedules()


@router.post("", response_model=ScheduleConfigOut)
async def upsert_schedule(body: ScheduleConfigIn):
    return add_or_update_schedule(body)


@router.delete("/{platform}", status_code=204)
async def delete_schedule(platform: str):
    removed = remove_schedule(platform)
    if not removed:
        raise HTTPException(404, f"No schedule for {platform}")
```

- [ ] **Step 5: Create `backend/routers/data.py`**

```python
from fastapi import APIRouter
from models import RestaurantOut, MenuItemOut
import db

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/restaurants", response_model=list[RestaurantOut])
async def list_restaurants(limit: int = 100, offset: int = 0, search: str | None = None):
    return db.get_restaurants(limit=limit, offset=offset, search=search)


@router.get("/menu-items/{listing_id}", response_model=list[MenuItemOut])
async def list_menu_items(listing_id: str):
    return db.get_menu_items(listing_id)
```

- [ ] **Step 6: Commit**

```bash
git add backend/routers/
git commit -m "feat: add API routers (scrapers, runs, schedule, data)"
```

---

## Task 10: Scheduler

**Files:**
- Create: `backend/scheduler.py`

- [ ] **Step 1: Create `backend/scheduler.py`**

```python
from __future__ import annotations
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from models import ScraperConfig, ScheduleConfigIn, ScheduleConfigOut
from scrapers.base import CloudflareBlockedError
import db

_scheduler = AsyncIOScheduler()
_schedules: dict[str, ScheduleConfigIn] = {}


def _noop(line: str) -> None:
    pass


async def _run_scraper(platform: str) -> None:
    from scrapers import ubereats, deliveroo, takeaway
    SCRAPERS = {"ubereats": ubereats.run, "deliveroo": deliveroo.run, "takeaway": takeaway.run}

    run_id = db.create_run(platform)
    try:
        result = await SCRAPERS[platform](ScraperConfig(), _noop)
        db.finish_run(run_id, "success", records_saved=result.records_saved)
    except CloudflareBlockedError as e:
        db.finish_run(run_id, "blocked", error_msg=str(e))
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))


def add_or_update_schedule(config: ScheduleConfigIn) -> ScheduleConfigOut:
    job_id = f"scraper_{config.platform}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)

    _schedules[config.platform] = config

    if config.enabled:
        job = _scheduler.add_job(
            _run_scraper,
            CronTrigger.from_crontab(config.cron),
            id=job_id,
            args=[config.platform],
        )
        next_run = job.next_run_time
    else:
        next_run = None

    return ScheduleConfigOut(**config.model_dump(), next_run=next_run)


def remove_schedule(platform: str) -> bool:
    job_id = f"scraper_{platform}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
        _schedules.pop(platform, None)
        return True
    return False


def list_schedules() -> list[ScheduleConfigOut]:
    result = []
    for platform, cfg in _schedules.items():
        job = _scheduler.get_job(f"scraper_{platform}")
        result.append(ScheduleConfigOut(**cfg.model_dump(), next_run=job.next_run_time if job else None))
    return result


def start() -> None:
    _scheduler.start()


def shutdown() -> None:
    _scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Commit**

```bash
git add backend/scheduler.py
git commit -m "feat: add APScheduler-based cron scheduler"
```

---

## Task 11: FastAPI main app

**Files:**
- Create: `backend/main.py`

- [ ] **Step 1: Create `backend/main.py`**

```python
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import scheduler as sched
import ws as ws_mod
from routers import scrapers, runs, schedule, data


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched.start()
    yield
    sched.shutdown()


app = FastAPI(title="Forkeur Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrapers.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(data.router, prefix="/api")


@app.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    await ws_mod.ws_endpoint(websocket, run_id)


# Serve React build in prod
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

- [ ] **Step 2: Start server and verify it boots**

```bash
cd backend && cp .env.example .env
# Edit .env — add real SUPABASE_URL and SUPABASE_KEY
uv run uvicorn main:app --reload --port 8000
```

Expected: `Uvicorn running on http://127.0.0.1:8000` with no import errors.

- [ ] **Step 3: Verify API endpoints respond**

```bash
curl http://localhost:8000/api/scrapers/status
```

Expected: JSON array with 3 platform status objects.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: add FastAPI main app with lifespan and WebSocket"
```

---

## Task 12: React dashboard scaffold

**Files:**
- Create: `backend/dashboard/` (Vite project)
- Create: `backend/dashboard/vite.config.ts`
- Create: `backend/dashboard/src/types.ts`
- Create: `backend/dashboard/src/api.ts`

- [ ] **Step 1: Scaffold Vite React app**

```bash
cd backend && npm create vite@latest dashboard -- --template react-ts
cd dashboard && npm install && npm install -D tailwindcss @tailwindcss/vite
```

- [ ] **Step 2: Configure Tailwind — update `backend/dashboard/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
})
```

- [ ] **Step 3: Add Tailwind import to `backend/dashboard/src/index.css`**

```css
@import "tailwindcss";
```

- [ ] **Step 4: Create `backend/dashboard/src/types.ts`**

```typescript
export type Platform = 'ubereats' | 'deliveroo' | 'takeaway'

export type RunStatus = 'running' | 'success' | 'failed' | 'blocked' | 'partial' | 'idle'

export interface ScraperRun {
  id: string
  platform: Platform
  status: RunStatus
  started_at: string
  finished_at: string | null
  records_saved: number
  error_msg: string | null
}

export interface ScraperStatus {
  platform: Platform
  status: RunStatus
  last_run: ScraperRun | null
}

export interface ScheduleConfig {
  platform: Platform
  cron: string
  enabled: boolean
  next_run: string | null
}

export interface Restaurant {
  id: string
  name: string
  slug: string
  cuisine: string | null
  neighborhood: string | null
}

export interface MenuItem {
  id: string
  listing_id: string
  title: string
  price: number | null
  catalog_name: string | null
}

export interface WsMessage {
  type: 'log' | 'done' | 'error'
  line?: string
  records?: number
  msg?: string
}
```

- [ ] **Step 5: Create `backend/dashboard/src/api.ts`**

```typescript
import type { ScraperStatus, ScraperRun, ScheduleConfig, Restaurant, MenuItem } from './types'

const BASE = '/api'

export async function getScraperStatus(): Promise<ScraperStatus[]> {
  const res = await fetch(`${BASE}/scrapers/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function triggerRun(platform: string): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE}/scrapers/${platform}/run`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getRuns(limit = 50, offset = 0): Promise<ScraperRun[]> {
  const res = await fetch(`${BASE}/runs?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSchedules(): Promise<ScheduleConfig[]> {
  const res = await fetch(`${BASE}/schedules`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function upsertSchedule(config: Omit<ScheduleConfig, 'next_run'>): Promise<ScheduleConfig> {
  const res = await fetch(`${BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteSchedule(platform: string): Promise<void> {
  await fetch(`${BASE}/schedules/${platform}`, { method: 'DELETE' })
}

export async function getRestaurants(params?: { limit?: number; offset?: number; search?: string }): Promise<Restaurant[]> {
  const q = new URLSearchParams()
  if (params?.limit) q.set('limit', String(params.limit))
  if (params?.offset) q.set('offset', String(params.offset))
  if (params?.search) q.set('search', params.search)
  const res = await fetch(`${BASE}/data/restaurants?${q}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getMenuItems(listingId: string): Promise<MenuItem[]> {
  const res = await fetch(`${BASE}/data/menu-items/${listingId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
```

- [ ] **Step 6: Verify dashboard dev server starts**

```bash
cd backend/dashboard && npm run dev
```

Expected: `Local: http://localhost:5173/` with no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/dashboard/
git commit -m "feat: scaffold React dashboard with Vite + Tailwind + API client"
```

---

## Task 13: Sidebar + App shell

**Files:**
- Modify: `backend/dashboard/src/App.tsx`
- Create: `backend/dashboard/src/components/Sidebar.tsx`

- [ ] **Step 1: Create `backend/dashboard/src/components/Sidebar.tsx`**

```tsx
import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: '📊 Dashboard', end: true },
  { to: '/scrapers', label: '⚙️ Scrapers' },
  { to: '/history', label: '📋 History' },
  { to: '/schedule', label: '⏰ Schedule' },
  { to: '/data', label: '🗄️ Data' },
]

export default function Sidebar() {
  return (
    <aside className="w-48 shrink-0 bg-slate-900 text-slate-300 flex flex-col py-4 px-2 min-h-screen">
      <div className="text-slate-100 font-bold text-lg px-3 mb-6">🍴 Forkeur</div>
      <nav className="flex flex-col gap-1">
        {links.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `px-3 py-2 rounded-md text-sm transition-colors ${
                isActive ? 'bg-blue-600 text-white' : 'hover:bg-slate-800'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
```

- [ ] **Step 2: Install react-router-dom**

```bash
cd backend/dashboard && npm install react-router-dom
```

- [ ] **Step 3: Rewrite `backend/dashboard/src/App.tsx`**

```tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Scrapers from './pages/Scrapers'
import History from './pages/History'
import Schedule from './pages/Schedule'
import Data from './pages/Data'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-slate-50 font-sans">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/scrapers" element={<Scrapers />} />
            <Route path="/history" element={<History />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/data" element={<Data />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
```

- [ ] **Step 4: Create stub pages (so app compiles)**

Create each file with a minimal placeholder:

`backend/dashboard/src/pages/Dashboard.tsx`:
```tsx
export default function Dashboard() { return <h1 className="text-2xl font-bold">Dashboard</h1> }
```

`backend/dashboard/src/pages/Scrapers.tsx`:
```tsx
export default function Scrapers() { return <h1 className="text-2xl font-bold">Scrapers</h1> }
```

`backend/dashboard/src/pages/History.tsx`:
```tsx
export default function History() { return <h1 className="text-2xl font-bold">History</h1> }
```

`backend/dashboard/src/pages/Schedule.tsx`:
```tsx
export default function Schedule() { return <h1 className="text-2xl font-bold">Schedule</h1> }
```

`backend/dashboard/src/pages/Data.tsx`:
```tsx
export default function Data() { return <h1 className="text-2xl font-bold">Data</h1> }
```

- [ ] **Step 5: Verify in browser**

```bash
cd backend/dashboard && npm run dev
```

Open `http://localhost:5173`. Should see dark sidebar with 5 nav links, content area with page title.

- [ ] **Step 6: Commit**

```bash
git add backend/dashboard/src/
git commit -m "feat: add sidebar nav and app shell with routing"
```

---

## Task 14: LogDrawer component

**Files:**
- Create: `backend/dashboard/src/components/LogDrawer.tsx`

- [ ] **Step 1: Create `backend/dashboard/src/components/LogDrawer.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import type { WsMessage } from '../types'

interface Props {
  runId: string | null
  platform: string | null
  onClose: () => void
}

export default function LogDrawer({ runId, platform, onClose }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [done, setDone] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!runId) return
    setLines([])
    setDone(false)

    const ws = new WebSocket(`ws://localhost:8000/ws/${runId}`)
    ws.onmessage = (e) => {
      const msg: WsMessage = JSON.parse(e.data)
      if (msg.type === 'log' && msg.line) {
        setLines(prev => [...prev, msg.line!])
      } else if (msg.type === 'done') {
        setLines(prev => [...prev, `✅ Done — ${msg.records} records saved`])
        setDone(true)
      } else if (msg.type === 'error') {
        setLines(prev => [...prev, `❌ Error: ${msg.msg}`])
        setDone(true)
      }
    }
    return () => ws.close()
  }, [runId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  if (!runId) return null

  return (
    <div className="fixed bottom-0 left-48 right-0 bg-slate-900 border-t-2 border-blue-500 z-50 transition-all">
      <div className="flex items-center justify-between px-4 py-2 text-slate-400 text-sm">
        <span>▼ {platform} log {done ? '— complete' : '— live'}</span>
        {done && (
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            ✕ Dismiss
          </button>
        )}
      </div>
      <div className="h-40 overflow-y-auto px-4 pb-3 font-mono text-xs text-green-400 leading-5">
        {lines.map((line, i) => <div key={i}>{line}</div>)}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add backend/dashboard/src/components/LogDrawer.tsx
git commit -m "feat: add WebSocket LogDrawer component"
```

---

## Task 15: ScraperCard + Scrapers page

**Files:**
- Create: `backend/dashboard/src/components/ScraperCard.tsx`
- Modify: `backend/dashboard/src/pages/Scrapers.tsx`

- [ ] **Step 1: Create `backend/dashboard/src/components/ScraperCard.tsx`**

```tsx
import type { ScraperStatus } from '../types'

const STATUS_COLORS: Record<string, string> = {
  idle: 'bg-slate-400',
  running: 'bg-blue-500 animate-pulse',
  success: 'bg-green-500',
  failed: 'bg-red-500',
  blocked: 'bg-orange-500',
  partial: 'bg-yellow-500',
}

interface Props {
  status: ScraperStatus
  onRun: () => void
  isRunning: boolean
}

export default function ScraperCard({ status, onRun, isRunning }: Props) {
  const dot = STATUS_COLORS[status.status] ?? 'bg-slate-400'
  const last = status.last_run

  const duration = last?.finished_at && last?.started_at
    ? Math.round((new Date(last.finished_at).getTime() - new Date(last.started_at).getTime()) / 1000)
    : null

  return (
    <div className={`bg-white rounded-xl border-2 p-5 flex flex-col gap-3 ${status.status === 'failed' || status.status === 'blocked' ? 'border-red-300' : 'border-slate-200'}`}>
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full ${dot}`} />
        <span className="font-bold text-slate-800 capitalize">{status.platform}</span>
      </div>

      {last ? (
        <div className="text-sm text-slate-500 space-y-0.5">
          <div>{last.records_saved} records saved</div>
          {duration !== null && <div>{duration}s duration</div>}
          <div>{new Date(last.started_at).toLocaleTimeString()}</div>
          {last.error_msg && <div className="text-red-500 text-xs">{last.error_msg}</div>}
        </div>
      ) : (
        <div className="text-sm text-slate-400">Never run</div>
      )}

      <button
        onClick={onRun}
        disabled={isRunning}
        className={`mt-auto rounded-md py-2 text-sm font-medium transition-colors ${
          isRunning
            ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
            : status.status === 'failed' || status.status === 'blocked'
            ? 'bg-red-500 hover:bg-red-600 text-white'
            : 'bg-blue-600 hover:bg-blue-700 text-white'
        }`}
      >
        {isRunning ? '⏳ Running…' : status.status === 'failed' ? '↺ Retry' : '▶ Run now'}
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `backend/dashboard/src/pages/Scrapers.tsx`**

```tsx
import { useEffect, useState } from 'react'
import type { ScraperStatus } from '../types'
import { getScraperStatus, triggerRun } from '../api'
import ScraperCard from '../components/ScraperCard'
import LogDrawer from '../components/LogDrawer'

export default function Scrapers() {
  const [statuses, setStatuses] = useState<ScraperStatus[]>([])
  const [runningPlatform, setRunningPlatform] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const load = async () => {
    const data = await getScraperStatus()
    setStatuses(data)
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleRun = async (platform: string) => {
    setRunningPlatform(platform)
    try {
      const { run_id } = await triggerRun(platform)
      setActiveRunId(run_id)
    } catch (e) {
      alert(String(e))
      setRunningPlatform(null)
    }
  }

  const handleClose = () => {
    setActiveRunId(null)
    setRunningPlatform(null)
    load()
  }

  return (
    <div className="pb-52">
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Scrapers</h1>
      <div className="grid grid-cols-3 gap-4">
        {statuses.map(s => (
          <ScraperCard
            key={s.platform}
            status={s}
            onRun={() => handleRun(s.platform)}
            isRunning={runningPlatform === s.platform}
          />
        ))}
      </div>
      <LogDrawer
        runId={activeRunId}
        platform={runningPlatform}
        onClose={handleClose}
      />
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

With backend running on `:8000` and dashboard on `:5173`, open `/scrapers`. Should see 3 expanded cards. Click "Run now" on any platform — log drawer should slide up.

- [ ] **Step 4: Commit**

```bash
git add backend/dashboard/src/components/ScraperCard.tsx backend/dashboard/src/pages/Scrapers.tsx
git commit -m "feat: add ScraperCard and Scrapers page with live log drawer"
```

---

## Task 16: Dashboard, History, Schedule, Data pages

**Files:**
- Modify: `backend/dashboard/src/pages/Dashboard.tsx`
- Modify: `backend/dashboard/src/pages/History.tsx`
- Modify: `backend/dashboard/src/pages/Schedule.tsx`
- Modify: `backend/dashboard/src/pages/Data.tsx`

- [ ] **Step 1: Rewrite `backend/dashboard/src/pages/Dashboard.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { getScraperStatus, getRuns } from '../api'
import type { ScraperStatus, ScraperRun } from '../types'

const STATUS_BADGE: Record<string, string> = {
  success: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  blocked: 'bg-orange-100 text-orange-800',
  running: 'bg-blue-100 text-blue-800',
  partial: 'bg-yellow-100 text-yellow-800',
  idle: 'bg-slate-100 text-slate-600',
}

export default function Dashboard() {
  const [statuses, setStatuses] = useState<ScraperStatus[]>([])
  const [recentRuns, setRecentRuns] = useState<ScraperRun[]>([])

  useEffect(() => {
    getScraperStatus().then(setStatuses)
    getRuns(10).then(setRecentRuns)
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Overview</h1>

      <div className="grid grid-cols-3 gap-4 mb-8">
        {statuses.map(s => (
          <div key={s.platform} className="bg-white rounded-xl border border-slate-200 p-5">
            <div className="text-sm text-slate-500 capitalize mb-1">{s.platform}</div>
            <div className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_BADGE[s.status]}`}>
              {s.status}
            </div>
            {s.last_run && (
              <div className="mt-2 text-xs text-slate-400">
                {s.last_run.records_saved} records · {new Date(s.last_run.started_at).toLocaleString()}
              </div>
            )}
          </div>
        ))}
      </div>

      <h2 className="text-lg font-semibold text-slate-700 mb-3">Recent runs</h2>
      <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100">
        {recentRuns.map(run => (
          <div key={run.id} className="flex items-center gap-4 px-4 py-3 text-sm">
            <span className="capitalize w-24 font-medium">{run.platform}</span>
            <span className={`px-2 py-0.5 rounded text-xs ${STATUS_BADGE[run.status]}`}>{run.status}</span>
            <span className="text-slate-500">{run.records_saved} records</span>
            <span className="text-slate-400 ml-auto">{new Date(run.started_at).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `backend/dashboard/src/pages/History.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { getRuns } from '../api'
import type { ScraperRun } from '../types'

const STATUS_BADGE: Record<string, string> = {
  success: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  blocked: 'bg-orange-100 text-orange-800',
  running: 'bg-blue-100 text-blue-800',
  partial: 'bg-yellow-100 text-yellow-800',
}

export default function History() {
  const [runs, setRuns] = useState<ScraperRun[]>([])
  const [offset, setOffset] = useState(0)

  const load = (o: number) => getRuns(50, o).then(setRuns)

  useEffect(() => { load(0) }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Run History</h1>
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Platform</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Records</th>
              <th className="text-left px-4 py-3">Duration</th>
              <th className="text-left px-4 py-3">Started</th>
              <th className="text-left px-4 py-3">Error</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.map(run => {
              const duration = run.finished_at
                ? Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)
                : null
              return (
                <tr key={run.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium capitalize">{run.platform}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${STATUS_BADGE[run.status] ?? 'bg-slate-100'}`}>
                      {run.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{run.records_saved}</td>
                  <td className="px-4 py-3 text-slate-500">{duration !== null ? `${duration}s` : '—'}</td>
                  <td className="px-4 py-3 text-slate-400">{new Date(run.started_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-red-500 text-xs max-w-xs truncate">{run.error_msg ?? ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2 mt-4">
        <button
          onClick={() => { const o = Math.max(0, offset - 50); setOffset(o); load(o) }}
          disabled={offset === 0}
          className="px-3 py-1.5 text-sm border rounded disabled:opacity-40"
        >← Prev</button>
        <button
          onClick={() => { const o = offset + 50; setOffset(o); load(o) }}
          className="px-3 py-1.5 text-sm border rounded"
        >Next →</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Rewrite `backend/dashboard/src/pages/Schedule.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { getSchedules, upsertSchedule, deleteSchedule } from '../api'
import type { ScheduleConfig, Platform } from '../types'

const PLATFORMS: Platform[] = ['ubereats', 'deliveroo', 'takeaway']

const DEFAULT_CRON: Record<Platform, string> = {
  ubereats: '0 */6 * * *',
  deliveroo: '0 */6 * * *',
  takeaway: '0 */6 * * *',
}

export default function Schedule() {
  const [schedules, setSchedules] = useState<Record<string, ScheduleConfig>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    getSchedules().then(list => {
      const map: Record<string, ScheduleConfig> = {}
      list.forEach(s => { map[s.platform] = s })
      setSchedules(map)
    })
  }, [])

  const save = async (platform: Platform) => {
    const cron = drafts[platform] ?? schedules[platform]?.cron ?? DEFAULT_CRON[platform]
    const enabled = schedules[platform]?.enabled ?? true
    const updated = await upsertSchedule({ platform, cron, enabled })
    setSchedules(prev => ({ ...prev, [platform]: updated }))
  }

  const toggle = async (platform: Platform) => {
    const s = schedules[platform]
    if (!s) return
    const updated = await upsertSchedule({ platform, cron: s.cron, enabled: !s.enabled })
    setSchedules(prev => ({ ...prev, [platform]: updated }))
  }

  const remove = async (platform: Platform) => {
    await deleteSchedule(platform)
    setSchedules(prev => { const n = { ...prev }; delete n[platform]; return n })
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Schedule</h1>
      <div className="flex flex-col gap-4">
        {PLATFORMS.map(platform => {
          const s = schedules[platform]
          return (
            <div key={platform} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="font-bold capitalize text-slate-800">{platform}</span>
                {s && (
                  <label className="flex items-center gap-2 text-sm text-slate-500">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      onChange={() => toggle(platform)}
                      className="w-4 h-4"
                    />
                    Enabled
                  </label>
                )}
              </div>
              <div className="flex gap-2">
                <input
                  className="flex-1 border border-slate-200 rounded-md px-3 py-2 text-sm font-mono"
                  placeholder={DEFAULT_CRON[platform]}
                  value={drafts[platform] ?? s?.cron ?? ''}
                  onChange={e => setDrafts(prev => ({ ...prev, [platform]: e.target.value }))}
                />
                <button
                  onClick={() => save(platform)}
                  className="bg-blue-600 text-white px-4 py-2 rounded-md text-sm hover:bg-blue-700"
                >
                  Save
                </button>
                {s && (
                  <button
                    onClick={() => remove(platform)}
                    className="text-red-500 border border-red-200 px-3 py-2 rounded-md text-sm hover:bg-red-50"
                  >
                    Remove
                  </button>
                )}
              </div>
              {s?.next_run && (
                <div className="mt-2 text-xs text-slate-400">
                  Next run: {new Date(s.next_run).toLocaleString()}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Rewrite `backend/dashboard/src/pages/Data.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { getRestaurants } from '../api'
import type { Restaurant } from '../types'

export default function Data() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([])
  const [search, setSearch] = useState('')

  const load = (q: string) => getRestaurants({ limit: 100, search: q || undefined }).then(setRestaurants)

  useEffect(() => { load('') }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Data Browser</h1>
      <input
        className="w-full max-w-md border border-slate-200 rounded-md px-3 py-2 text-sm mb-4"
        placeholder="Search restaurants..."
        value={search}
        onChange={e => { setSearch(e.target.value); load(e.target.value) }}
      />
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Slug</th>
              <th className="text-left px-4 py-3">Cuisine</th>
              <th className="text-left px-4 py-3">Neighborhood</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {restaurants.map(r => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-medium">{r.name}</td>
                <td className="px-4 py-3 text-slate-500 font-mono text-xs">{r.slug}</td>
                <td className="px-4 py-3 text-slate-500">{r.cuisine ?? '—'}</td>
                <td className="px-4 py-3 text-slate-500">{r.neighborhood ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Verify all pages render without errors**

With both servers running, open each route in browser:
- `http://localhost:5173/` — stat cards + recent runs
- `http://localhost:5173/history` — run table
- `http://localhost:5173/schedule` — cron inputs per platform
- `http://localhost:5173/data` — searchable restaurant table

- [ ] **Step 6: Commit**

```bash
git add backend/dashboard/src/pages/
git commit -m "feat: build out Dashboard, History, Schedule, and Data pages"
```

---

## Task 17: End-to-end smoke test

- [ ] **Step 1: Start backend**

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Start dashboard**

```bash
cd backend/dashboard && npm run dev
```

- [ ] **Step 3: Trigger a scraper run via UI**

Open `http://localhost:5173/scrapers`. Click "Run now" on Takeaway (fastest). Log drawer should slide up and stream lines.

- [ ] **Step 4: Verify DB updated**

After run completes, open `http://localhost:5173/data`. Restaurants should appear.

- [ ] **Step 5: Verify history**

Open `http://localhost:5173/history`. Run should appear with status=success (or blocked if VPN not active).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: complete Forkeur scraper manager backend + dashboard"
```
