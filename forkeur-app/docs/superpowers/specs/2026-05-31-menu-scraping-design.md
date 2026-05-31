# Menu Scraping — Design Spec

**Date:** 2026-05-31  
**Status:** Approved

## Problem

All three scrapers populate `restaurants` and `platform_listings` but never call `db.insert_menu_items()`. The basket/compare UI requires `menu_items` rows to function.

## Goal

Add phase 2 to each scraper: after listing phase, navigate to individual restaurant pages and scrape menu items (`title`, `price`, `catalog_name`) into the DB.

---

## Config Changes

### `ScraperConfig` (models.py)

```python
@dataclass
class ScraperConfig:
    address: str = "Pl. Poelaert 1, 1000 Bruxelles"
    target: str | None = None
    max_items: int = 50
    scrape_menus: bool = False   # new
    max_menus: int = 3           # new — cap menu page visits per run
```

`scrape_menus` defaults `False` so existing runs are unaffected.

### `ScraperResult` (models.py)

```python
@dataclass
class ScraperResult:
    records_saved: int
    restaurants: list[dict] = field(default_factory=list)
    menu_items_saved: int = 0   # new
```

---

## Per-Scraper Phase 2

After the listing loop, each scraper iterates the saved `(listing_id, url)` pairs (up to `config.max_menus`), reuses the existing Playwright browser/page, and calls `db.insert_menu_items(listing_id, items)`.

Items written: `{title: str, price: float | None, catalog_name: str | None}`.

### UberEats

**Strategy: API interception** — same pattern as phase 1 feed capture.

After navigating to the restaurant URL (`/be-en/store/<slug>`), intercept the `getSectionFeedV1` or `getStoreLayoutV1` API response (JSON). Parse `catalogSectionsMap` or `sections` array for catalog names and item arrays.

Fallback: if API not captured within timeout, fall back to DOM eval on rendered item cards.

### Deliveroo

**Strategy: DOM eval** — same pattern as existing listing scraping.

Navigate to `/en/menu/<slug>`. Scroll once to trigger lazy load. JS eval:
- Section headings: `h2, h3, [data-testid*="category"], [data-testid*="section"]`
- Items: for each section, find sibling cards with text containing `€`
- Extract title (largest non-price text) + price (regex `\d+[,.]\d+\s*€` or `€\s*\d+[,.]\d+`)

### Takeaway

**Strategy: DOM eval** — same pattern as existing listing scraping.

Navigate to `/be-fr/menu/<slug>`. Scroll to load. JS eval:
- Product cards: `[data-qa*="product"], [data-testid*="product"], .product-card`
- Section headings: preceding `h2`/`h3` sibling
- Extract title + price with same regex approach

---

## Router Change

`POST /scrapers/{platform}/run` accepts an optional JSON body:

```python
class RunTriggerIn(BaseModel):
    scrape_menus: bool = False
    max_menus: int = 3
```

If body absent, defaults apply (existing behavior unchanged). The dashboard "Run" button gains a "Scrape menus" toggle that passes this body.

---

## Data Flow

```
trigger_run(scrape_menus=True)
  └── scraper.run(config)
        ├── Phase 1: listing page → upsert restaurants + listings
        │     collected: [(listing_id, url), ...]
        └── Phase 2 (if scrape_menus):
              for (listing_id, url) in collected[:max_menus]:
                navigate to url
                scrape items
                db.insert_menu_items(listing_id, items)
```

---

## Error Handling

- Menu scraping errors per restaurant are caught and logged but do not fail the overall run.
- Run `status` remains `success` even if some menu pages fail; `menu_items_saved` reflects actual count.
- Cloudflare blocks on menu pages are logged as warnings, not run failures.

---

## Not in scope

- Description field on menu items (not in DB schema)
- Image URLs (not in DB schema)
- Pagination within a menu (scroll once is sufficient for popular items)
- Dashboard UI changes beyond the "Scrape menus" toggle on the run button
