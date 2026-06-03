# Direct Ordering — Full Feature Design

**Date:** 2026-06-03
**Status:** Approved design, pre-implementation
**Mission:** Push users to order directly from restaurants when available, by making the savings (platform fees + price differences) visible and honest.

---

## Problem

Forkeur compares restaurant prices across UberEats, Deliveroo, Takeaway. Direct ordering — the biggest potential saver, since it skips the 15-25% platform commission — is half-built:

- **UI exists**: CTA buttons, basket `direct` column, phone fallback all wired in frontend.
- **`order_url` data exists**: 459 of 1,060 restaurants have an `order_url` (from the `website_finder` scraper).
- **But nothing flows**: only 43 restaurants have a `platform_listings.direct` row, and **0 direct listings have menu items**. The direct column is empty for nearly everyone.
- **Data is partly junk**: ~46 `order_url` values are scraper artifacts (`google.com/searchviewer`), reservation links (Zenchef, Tablebooker), or PDFs — clicking "Commander directement" can land users on a non-ordering page.

## Goal

Ship a complete, honest direct-ordering comparison: clean data, every restaurant with a real ordering link appears in the comparison, and where we have real menu prices, users see item-by-item savings. Mission-aligned but **fully transparent** — if direct is more expensive, we show that too.

## Non-goals (v1)

- **Generic DOM menu scraping** of arbitrary custom restaurant websites. ~400 restaurants have bespoke sites (WordPress/PHP/PDFs). Scraping them is fragile, low-accuracy, high-maintenance. Deferred to a future spike, gated on observed click-through to direct links.
- Direct delivery-fee data (we don't have it; copy works around this — see Phase 2).
- Menu staleness UI.

---

## Architecture overview

Four phases, **ordered so Phase 1 ships independently first**. Each later phase is additive and degrades gracefully if the next isn't done.

```
Phase 1  Data cleanup + sync        →  every order_url restaurant gets a direct listing
Phase 2  Fee-savings signal         →  fallback alert when no direct menu data
Phase 3  Structured menu scrapers   →  real prices for sq-menu / odoo / piki-app (~8-15 restaurants)
Phase 4  Price comparison + alerts  →  item/basket/card surfaces, gated on overlap threshold
```

---

## Phase 1 — Data cleanup + sync

### 1a. Cleanup pass (one-time, idempotent script)

New CLI: `backend/clean_order_urls.py`. Null out `restaurants.order_url` where it matches any junk pattern:

- `google.com/searchviewer`
- `zenchef.com`, `tablebooker.com`, `reservations.`, `bookings.`
- ends in `.pdf`
- `linktr.ee`, `digilink.io` (link aggregators, not ordering)

~46 rows affected. Safe to re-run.

### 1b. URL classification

New column on `platform_listings`:

```sql
ALTER TABLE platform_listings
  ADD COLUMN IF NOT EXISTS url_type text
  CHECK (url_type IN ('ordering','menu','website','phone'));
```

Classifier (`backend/scrapers/direct_classify.py`, pure function, unit-tested):

| `url_type` | Detection rule |
|---|---|
| `ordering` | host/path matches known ordering platforms: `sq-menu`, `odoo.*pos-self`, `piki-app`, `lightspeedrestaurant`, `wixrestaurants`, `flipdish`, `livepepper`, `obypay`, `foodbooking`, `orderyoyo`, `clickeat`, `square.site` |
| `menu` | path contains `/menu`, `/carte`, `/kaart`, `/menukaart` |
| `phone` | `order_url` is null but `restaurants.phone` present |
| `website` | everything else |

### 1c. Sync

New CLI: `backend/sync_direct_listings.py`. For every restaurant with a non-null `order_url`, upsert a `platform_listings` row:

```
restaurant_id, platform='direct', url=order_url, url_type=<classified>, is_available=true
```

Creates ~416 new rows (459 total − 43 existing). Idempotent upsert on `(restaurant_id, platform='direct')`.

**Shippable checkpoint:** after Phase 1, every direct restaurant appears in the basket comparison with a correctly-labelled CTA. No menu prices yet, but the feature is honest and usable.

---

## Phase 2 — Fee-savings signal (no menu scraping)

When a restaurant has a `direct` listing but **no direct menu items**, the basket direct column shows a fee-savings framing instead of prices.

**Copy (locked):** "sans frais **de plateforme**" — we skip the *platform's commission/fee*, NOT a claim of free delivery (we have no direct delivery-fee data; restaurants often charge their own).

Savings figure = the cheapest available platform's `delivery_fee_cents` for that restaurant (already in DB from the fees scraper). Displayed as approximate:

```
~€2.49 de frais de plateforme économisés · Commander directement →
```

Direct column states:

| Condition | Display |
|---|---|
| Direct listing + direct menu items | Real prices (Phase 4) |
| Direct listing, no menu items | Fee-savings line above |
| No direct listing | dash / empty |

---

## Phase 3 — Structured menu scrapers (Way A only)

New file: `backend/scrapers/direct_menu.py`. Adapter dispatch on the direct listing's URL. **Structured platforms only** — no generic DOM fallback in v1.

| Adapter | Source | How | Known count |
|---|---|---|---|
| `sq_menu` | `sq-menu.com` | REST/JSON endpoint (slug in URL → `/api/...` returns menu JSON) | 5 |
| `odoo_pos` | `*.odoo.com/pos-self/*` | Odoo JSON-RPC `/web/dataset/call_kw` → `product.product` | 1+ |
| `piki_app` | `piki-app.com` | REST — URL path already `/vendor/{slug}/.../categories`, fetch JSON | 2 |

Each adapter:
1. Resolves restaurant slug from `order_url`.
2. Fetches menu (httpx, JSON — no Playwright needed for these).
3. Writes `menu_items` rows: `listing_id` → the direct listing, `title`, `price` (numeric euros, matching existing convention), `catalog_name` (category), `description`/`image_url` if available.
4. Re-run = replace this listing's direct items (delete + insert, or upsert) to keep prices fresh.

Realistic outcome: real menu data for **~8-15 restaurants**. That is the validated proof-of-concept set; everyone else stays on Phase 2 fee-savings framing.

### Scheduler

Register a `direct` job in the existing APScheduler setup (`backend/scheduler.py`), persisted to `scraper_schedules`. Daily cadence is sufficient (direct menus change slowly). Reuses the existing `scraper_runs` history table with `platform='direct'`.

### API trigger

Extend the existing scraper-run router so `POST /api/scrapers/direct/run` runs the structured menu scrape (consistent with ubereats/deliveroo/takeaway/fees). Honor the test limit convention (`max_items` small for testing per project rules).

---

## Phase 4 — Price comparison + alerts

### 4a. Normalized match key (foundation)

**Current behavior** ([queries.ts:227](../../forkeur-app/lib/queries.ts#L227)): menu items are grouped across platforms by **exact `title` string**. Direct items will rarely match platform titles exactly (e.g. "Pizza Margherita" vs "Margherita (San Marzano, bufala)").

Introduce a normalized match key for grouping: `lowercase → strip accents → strip punctuation → collapse whitespace`. Applied to all platforms (not just direct), so it also tightens existing cross-platform matching.

**Risk & mitigation:** changing the group key can merge or split existing UberEats/Deliveroo/Takeaway groups. Mitigation: the normalization is conservative (no stemming, no fuzzy matching — just canonicalize casing/accents/punctuation). Validate against current restaurant detail pages before/after (snapshot a few restaurants, confirm item counts don't collapse unexpectedly). Covered by frontend tests.

### 4b. Overlap threshold (locked decision)

A direct **savings percentage / "cheaper in direct"** claim is shown ONLY when:

- **≥3 basket items** have a direct price, AND
- **≥50% of basket items** (by distinct item) have a direct price.

Below threshold → no savings %; fall back to Phase 2 fee-savings framing. This prevents a confident-but-wrong number computed from a 1-item overlap.

### 4c. Full transparency (locked decision)

The basket comparison grid shows the `direct` column like any other platform — including when direct total is **higher**. We do not hide unfavorable direct prices.

- Direct cheaper + threshold met → savings banner (4d) fires.
- Direct same/higher + threshold met → grid shows direct honestly, no savings banner, CTA still present.
- Threshold not met → fee-savings framing only.

### 4d. Alert surfaces

**1. Basket banner** (in `BasketSimulator`) — when direct total < cheapest platform total AND threshold met:

```
🟠 Commander directement vous économise €4.20
   Mêmes plats · sans frais de plateforme            [Commander →]
```

**2. Restaurant card badge** ([RestaurantCard.tsx](../../forkeur-app/components/RestaurantCard.tsx)) — replaces current static pill:
- Direct menu items exist + direct avg < cheapest platform avg (threshold met on overlap) → **"X% moins cher en direct"**
- Otherwise → keep existing "Commander directement" pill, copy driven by `url_type` ("Commander" for `ordering`, "Voir le menu" for `menu`, "Site du restaurant" for `website`).

**3. Item-level highlight** (menu list) — when an item has a direct price and direct is the cheapest for that item, render the direct price label in orange.

### Frontend data plumbing

- [lib/queries.ts](../../forkeur-app/lib/queries.ts): select `url_type` on the direct listing; apply normalized match key; direct prices already flow into `prices.direct`.
- [lib/basket.ts](../../forkeur-app/lib/basket.ts): add helper for overlap-threshold check + direct savings computation.
- [restaurant/[id]/page.tsx](../../forkeur-app/app/restaurant/%5Bid%5D/page.tsx): CTA copy from `url_type`.

---

## Data flow

```
website_finder  →  restaurants.order_url
                        │
   clean_order_urls (null junk)
                        │
   sync_direct_listings  →  platform_listings(platform='direct', url_type)
                        │
   direct_menu scrapers  →  menu_items(listing_id → direct listing)   [~8-15 restaurants]
                        │
   queries.ts (normalized match key)  →  prices.direct in comparison grid
                        │
   BasketSimulator / RestaurantCard / item rows  →  transparent comparison + savings alerts
```

---

## DB changes

```sql
-- platform_listings: classify the direct link
ALTER TABLE platform_listings
  ADD COLUMN IF NOT EXISTS url_type text
  CHECK (url_type IN ('ordering','menu','website','phone'));
```

No other schema changes. `restaurants.order_url`, `website`, `website_searched_at` already exist. `menu_items` already supports direct items via `listing_id`.

---

## Testing

- **Backend**: pytest for `direct_classify` (URL → url_type table), and per-adapter parse tests using a captured JSON fixture for each structured platform (sq-menu, odoo, piki-app). Cleanup + sync scripts tested against a seeded fixture / dry-run mode.
- **Frontend**: vitest for normalized match key (accents/punctuation cases), overlap-threshold logic (boundary: exactly 3 items / exactly 50%), and the three alert states (cheaper / same-higher / below-threshold). Update existing `restaurant-card.test.tsx` fixtures with `url_type`.

## Rollout

1. Phase 1 cleanup + sync — run scripts, verify direct listings populated, ship UI label changes.
2. Phase 2 fee-savings copy — ship.
3. Phase 3 scrapers — validate end-to-end on the ~8-15 structured restaurants before scheduling.
4. Phase 4 alerts — ship once real direct prices exist for the structured set.

## Risks

| Risk | Mitigation |
|---|---|
| Title matching too sparse → direct rarely joins comparison | Normalized match key + honest fallback; alerts gated on overlap threshold |
| Structured adapters break on platform changes | Few platforms, fixture-based tests, daily re-scrape catches drift |
| Direct often priced same/higher (parity) → undercuts mission | Accepted: full transparency. Fee-savings framing still applies universally |
| Implying free direct delivery | Copy locked to "frais de plateforme" (platform commission), never "livraison gratuite" |
| Changing group key corrupts existing comparisons | Conservative normalization; before/after validation on sample restaurants |
