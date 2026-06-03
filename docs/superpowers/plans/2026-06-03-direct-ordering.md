# Direct Ordering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** End-to-end direct ordering comparison — clean data, every restaurant with a real ordering link in the grid, structured menu scrapers for ~8-15 restaurants, fee-savings framing, and price-comparison alerts.

**Architecture:** 4 phases shipped in order. Phase 1 is independently shippable and self-contained. Phases 2-4 are additive layers that each degrade gracefully without the next.

**Tech Stack:** Python 3.12 + httpx + pytest (backend), TypeScript + Next.js 15 + vitest (frontend). Both `httpx` and `pytest-asyncio` already in `backend/pyproject.toml`.

---

## File Map

**New files:**
- `supabase/migrations/010_add_url_type.sql`
- `backend/scrapers/direct_classify.py`
- `backend/clean_order_urls.py`
- `backend/sync_direct_listings.py`
- `backend/scrapers/direct_menu.py`
- `backend/tests/test_direct_classify.py`
- `backend/tests/test_direct_menu.py`
- `backend/tests/fixtures/sq_menu_response.json`
- `backend/tests/fixtures/odoo_pos_response.json`
- `backend/tests/fixtures/piki_app_response.json`
- `forkeur-app/__tests__/normalize.test.ts`

**Modified files:**
- `backend/routers/scrapers.py` — repoint `direct` key to `direct_menu.run`
- `backend/scheduler.py` — same repoint
- `forkeur-app/lib/queries.ts` — add `url_type` + `direct_url_type` to types; normalize match key; select new fields
- `forkeur-app/lib/basket.ts` — add overlap + savings helpers
- `forkeur-app/components/BasketSimulator.tsx` — fee-savings framing + savings banner + item highlight
- `forkeur-app/components/RestaurantCard.tsx` — url_type CTA copy
- `forkeur-app/__tests__/basket.test.ts` — overlap + savings tests
- `forkeur-app/__tests__/restaurant-card.test.tsx` — add `direct_url_type` to fixtures

---

## Phase 1 — Data Cleanup + Sync

---

### Task 1: DB migration — add `url_type` column

**Files:**
- Create: `supabase/migrations/010_add_url_type.sql`

- [ ] **Step 1: Create migration file**

```sql
ALTER TABLE platform_listings
  ADD COLUMN IF NOT EXISTS url_type text
  CHECK (url_type IN ('ordering', 'menu', 'website', 'phone'));
```

Save as `supabase/migrations/010_add_url_type.sql`.

- [ ] **Step 2: Apply migration via Supabase MCP**

Use the `apply_migration` MCP tool with name `add_url_type` and the SQL above.

- [ ] **Step 3: Verify column exists**

```sql
SELECT column_name, data_type, check_constraints
FROM information_schema.columns
WHERE table_name = 'platform_listings' AND column_name = 'url_type';
```

Expected: one row, `data_type = 'text'`.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/010_add_url_type.sql
git commit -m "feat: add url_type column to platform_listings"
```

---

### Task 2: `direct_classify.py` — URL classifier + tests

**Files:**
- Create: `backend/scrapers/direct_classify.py`
- Create: `backend/tests/test_direct_classify.py`

- [ ] **Step 1: Write failing tests first**

Create `backend/tests/test_direct_classify.py`:

```python
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scrapers.direct_classify import classify_url, _JUNK_RE


# ── classify_url ──────────────────────────────────────────────────────────────

def test_sq_menu_is_ordering():
    assert classify_url('https://burger-palace.sq-menu.com/order') == 'ordering'

def test_piki_app_is_ordering():
    assert classify_url('https://piki-app.com/vendor/pizza/categories') == 'ordering'

def test_odoo_pos_self_is_ordering():
    assert classify_url('https://restaurant.odoo.com/pos-self/menu') == 'ordering'

def test_odoo_non_pos_is_website():
    assert classify_url('https://restaurant.odoo.com/shop') == 'website'

def test_lightspeed_is_ordering():
    assert classify_url('https://order.lightspeedrestaurant.com/abc') == 'ordering'

def test_clickeat_is_ordering():
    assert classify_url('https://clickeat.be/restaurant/pizza') == 'ordering'

def test_menu_path_is_menu():
    assert classify_url('https://example.com/menu') == 'menu'

def test_carte_path_is_menu():
    assert classify_url('https://example.com/notre-carte') == 'menu'

def test_menukaart_path_is_menu():
    assert classify_url('https://example.com/menukaart') == 'menu'

def test_kaart_path_is_menu():
    assert classify_url('https://example.com/kaart/gerechten') == 'menu'

def test_plain_website_fallback():
    assert classify_url('https://myrestaurant.be') == 'website'

def test_none_with_phone_returns_phone():
    assert classify_url(None, phone='+32471234567') == 'phone'

def test_none_without_phone_returns_website():
    assert classify_url(None) == 'website'

def test_empty_string_with_phone_returns_phone():
    assert classify_url('', phone='+32471234567') == 'phone'


# ── _JUNK_RE ──────────────────────────────────────────────────────────────────

def test_junk_google_searchviewer():
    assert _JUNK_RE.search('https://google.com/searchviewer?q=restaurant')

def test_junk_zenchef():
    assert _JUNK_RE.search('https://bookings.zenchef.com/results?rid=123')

def test_junk_tablebooker():
    assert _JUNK_RE.search('https://www.tablebooker.com/r/myrestaurant')

def test_junk_pdf():
    assert _JUNK_RE.search('https://myrestaurant.be/menu.pdf')

def test_junk_linktree():
    assert _JUNK_RE.search('https://linktr.ee/myrestaurant')

def test_junk_digilink():
    assert _JUNK_RE.search('https://digilink.io/myrestaurant')

def test_not_junk_sq_menu():
    assert not _JUNK_RE.search('https://burger.sq-menu.com/order')

def test_not_junk_normal_website():
    assert not _JUNK_RE.search('https://myrestaurant.be')
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd backend && uv run pytest tests/test_direct_classify.py -v
```

Expected: `ImportError: cannot import name 'classify_url'` (file doesn't exist yet).

- [ ] **Step 3: Implement `direct_classify.py`**

Create `backend/scrapers/direct_classify.py`:

```python
"""Classify direct ordering URLs into url_type values."""
from __future__ import annotations
from urllib.parse import urlparse
import re

_ORDERING_HOSTS = re.compile(
    r'sq-menu\.com'
    r'|piki-app\.com'
    r'|lightspeedrestaurant\.com'
    r'|wixrestaurants\.com'
    r'|flipdish\.'
    r'|livepepper\.'
    r'|obypay\.'
    r'|foodbooking\.'
    r'|orderyoyo\.'
    r'|clickeat\.'
    r'|square\.site'
    r'|app\.orda\.io'
    r'|orderingstack\.',
    re.IGNORECASE,
)

_MENU_PATHS = re.compile(
    r'/(menu|carte|kaart|menukaart)(\b|/|$)',
    re.IGNORECASE,
)

_JUNK_RE = re.compile(
    r'google\.com/searchviewer'
    r'|zenchef\.com'
    r'|tablebooker\.com'
    r'|reservations?\.'
    r'|bookings?\.'
    r'|\.pdf$'
    r'|linktr\.ee'
    r'|digilink\.io',
    re.IGNORECASE,
)


def classify_url(order_url: str | None, phone: str | None = None) -> str:
    """Classify a direct ordering URL. Returns: ordering|menu|website|phone."""
    if not order_url:
        return 'phone' if phone else 'website'

    try:
        parsed = urlparse(order_url)
        host = parsed.netloc.lower()
        path = parsed.path
    except Exception:
        return 'website'

    # Odoo POS self-order: *.odoo.com/pos-self/...
    if 'odoo.com' in host and 'pos-self' in path:
        return 'ordering'

    if _ORDERING_HOSTS.search(host):
        return 'ordering'

    if _MENU_PATHS.search(path):
        return 'menu'

    return 'website'
```

- [ ] **Step 4: Run tests — all pass**

```bash
cd backend && uv run pytest tests/test_direct_classify.py -v
```

Expected: all 24 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scrapers/direct_classify.py backend/tests/test_direct_classify.py
git commit -m "feat: direct URL classifier with junk regex and url_type logic"
```

---

### Task 3: `clean_order_urls.py` — junk URL nulling script

**Files:**
- Create: `backend/clean_order_urls.py`

- [ ] **Step 1: Create the script**

Create `backend/clean_order_urls.py`:

```python
#!/usr/bin/env python3
"""
Null out junk order_url values in restaurants table.
Idempotent — safe to re-run.

Usage:
  cd backend && uv run python clean_order_urls.py [--dry-run]
"""
from __future__ import annotations
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from scrapers.direct_classify import _JUNK_RE
import db


def clean(dry_run: bool = False) -> int:
    client = db.get_client()
    rows = (
        client.table('restaurants')
        .select('id, name, order_url')
        .not_.is_('order_url', 'null')
        .execute()
    ).data

    nulled = 0
    for row in rows:
        url = row['order_url']
        if _JUNK_RE.search(url):
            print(f"  NULL: {row['name'][:40]!r:<44} {url[:70]}")
            if not dry_run:
                client.table('restaurants').update({'order_url': None}).eq('id', row['id']).execute()
            nulled += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Nulled {nulled} junk order_url rows")
    return nulled


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    clean(dry_run=dry_run)
```

- [ ] **Step 2: Run dry-run against production DB**

```bash
cd backend && uv run python clean_order_urls.py --dry-run
```

Expected: ~46 rows listed. Verify names make sense (google.com/searchviewer, zenchef, .pdf, linktr.ee, etc). **Nothing is changed yet.**

- [ ] **Step 3: Run for real**

```bash
cd backend && uv run python clean_order_urls.py
```

Expected: `Nulled 46 junk order_url rows` (or similar count).

- [ ] **Step 4: Commit**

```bash
git add backend/clean_order_urls.py
git commit -m "feat: clean_order_urls script — nulls junk order_url values"
```

---

### Task 4: `sync_direct_listings.py` — sync order_url to direct listings

**Files:**
- Create: `backend/sync_direct_listings.py`

- [ ] **Step 1: Create the script**

Create `backend/sync_direct_listings.py`:

```python
#!/usr/bin/env python3
"""
Sync restaurants.order_url → platform_listings(platform='direct').
Creates or updates a direct listing for every restaurant with a non-null order_url.
Idempotent — safe to re-run.

Usage:
  cd backend && uv run python sync_direct_listings.py [--dry-run]
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import db
from scrapers.direct_classify import classify_url


def sync(dry_run: bool = False) -> int:
    client = db.get_client()
    restaurants = (
        client.table('restaurants')
        .select('id, name, order_url, phone')
        .not_.is_('order_url', 'null')
        .execute()
    ).data

    print(f"Found {len(restaurants)} restaurants with order_url")
    synced = 0

    for r in restaurants:
        url_type = classify_url(r['order_url'], r.get('phone'))
        data = {
            'restaurant_id': r['id'],
            'platform': 'direct',
            'url': r['order_url'],
            'url_type': url_type,
            'is_available': True,
        }
        label = f"{r['name'][:35]!r:<38} {url_type:<10} {r['order_url'][:55]}"
        print(f"  {'[DRY] ' if dry_run else ''}{label}")
        if not dry_run:
            db.upsert_listing(data)
        synced += 1

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Synced {synced} direct listings")
    return synced


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    sync(dry_run=dry_run)
```

- [ ] **Step 2: Run dry-run**

```bash
cd backend && uv run python sync_direct_listings.py --dry-run
```

Expected: ~413 rows (459 original − ~46 just cleaned). Each row shows restaurant name, url_type, and URL. Verify a few ordering rows (sq-menu.com, piki-app.com) and menu/website rows look correct.

- [ ] **Step 3: Run for real**

```bash
cd backend && uv run python sync_direct_listings.py
```

Expected: `Synced 413 direct listings` (approximate).

- [ ] **Step 4: Verify in DB**

```sql
SELECT url_type, COUNT(*) FROM platform_listings
WHERE platform = 'direct'
GROUP BY url_type
ORDER BY count DESC;
```

Expected: ordering: ~15, menu: ~30, website: ~350+, phone: varies. Total > 400.

- [ ] **Step 5: Run full test suite — confirm no regressions**

```bash
cd backend && uv run pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/sync_direct_listings.py
git commit -m "feat: sync_direct_listings script — 459 order_urls → direct listings with url_type"
```

---

## Phase 2 — Fee-Savings Signal

---

### Task 5: Add `url_type` to queries + `direct_url_type` to RestaurantSummary

**Files:**
- Modify: `forkeur-app/lib/queries.ts`

- [ ] **Step 1: Add `url_type` to `PlatformListing` type**

In `forkeur-app/lib/queries.ts`, find the `PlatformListing` type (line ~21) and add one field:

```typescript
export type PlatformListing = {
  id: string
  platform: Platform
  platform_url: string | null
  delivery_fee_cents: number | null
  delivery_fee_label: string | null
  min_order_cents: number | null
  min_order_label: string | null
  eta_label: string | null
  rating: number | null
  url_type: string | null
}
```

- [ ] **Step 2: Add `direct_url_type` to `RestaurantSummary` type**

Find the `RestaurantSummary` type (line ~6) and add:

```typescript
export type RestaurantSummary = {
  id: string
  name: string
  cuisine: string[]
  lat: number | null
  lng: number | null
  order_url: string | null
  direct_url_type: string | null
  listings: { platform: Platform; delivery_fee_cents: number | null }[]
  cheapest: {
    platform: Platform
    fee_label: string
    savings_cents: number
  } | null
}
```

- [ ] **Step 3: Update `getRestaurants` — select `url_type`, populate `direct_url_type`**

In `getRestaurants`, change the select clause from:
```typescript
platform_listings ( platform, delivery_fee )
```
to:
```typescript
platform_listings ( platform, delivery_fee, url_type )
```

Update the `rawListings` type inline:
```typescript
const rawListings = (r.platform_listings ?? []) as {
  platform: string
  delivery_fee: number | null
  url_type: string | null
}[]
```

After `const listings = rawListings.map(...)`, add:
```typescript
const directListing = rawListings.find(l => l.platform === 'direct')
const direct_url_type: string | null = directListing?.url_type ?? null
```

Add `direct_url_type` to both return objects (the `available.length === 0` branch and the normal branch):
```typescript
return {
  id: r.id,
  name: r.name,
  cuisine: r.cuisine ? [r.cuisine] : [],
  lat,
  lng,
  order_url,
  direct_url_type,
  listings,
  cheapest: null,  // (or the computed cheapest)
}
```

- [ ] **Step 4: Update `getRestaurantWithListings` — select and map `url_type`**

In `getRestaurantWithListings`, change the select:
```typescript
platform_listings (
  id, platform, url, url_type,
  delivery_fee, min_order, eta_min, eta_max, rating,
  menu_items ( title, price, catalog_name, image_url, description )
)
```

In the listings mapping (where `PlatformListing` fields are assigned), add:
```typescript
url_type: (l as any).url_type ?? null,
```

- [ ] **Step 5: Fix TypeScript — update `restaurant-card.test.tsx` fixtures**

In `forkeur-app/__tests__/restaurant-card.test.tsx`, add `direct_url_type: null` to every `RestaurantSummary` fixture object (there are 3: `threeListings`, `nullFees`, `freeListing`).

```typescript
const threeListings: RestaurantSummary = {
  id: '1',
  name: "McDonald's",
  cuisine: ['Burgers'],
  lat: null,
  lng: null,
  order_url: null,
  direct_url_type: null,   // ADD
  listings: [...],
  cheapest: {...},
}
```

Repeat for `nullFees` and `freeListing`.

- [ ] **Step 6: Run frontend tests**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add forkeur-app/lib/queries.ts forkeur-app/__tests__/restaurant-card.test.tsx
git commit -m "feat: add url_type to PlatformListing and direct_url_type to RestaurantSummary"
```

---

### Task 6: Fee-savings framing in `BasketSimulator`

**Files:**
- Modify: `forkeur-app/components/BasketSimulator.tsx`

- [ ] **Step 1: Add `hasDirectPrices` and `cheapestPaidFeeCents` memos**

In `BasketSimulator.tsx`, after the `const fees = useMemo(...)` block (line ~46), add:

```tsx
const hasDirectPrices = useMemo(
  () => menuItems.some(item => item.prices.direct !== null),
  [menuItems]
)

const cheapestPaidFeeCents = useMemo(() => {
  const paid = PLATFORMS
    .filter(p => p !== 'direct')
    .map(p => fees[p])
    .filter((f): f is number => f !== null)
  return paid.length > 0 ? Math.min(...paid) : null
}, [fees])
```

- [ ] **Step 2: Update `platformFeeRows` — inject fee-savings copy for direct**

Find the `platformFeeRows` computation (line ~132). Replace the `feeText` computation inside the `.map()` with:

```tsx
const platformFeeRows = listings.map((l) => {
  const colors = PLATFORM_COLORS[l.platform]
  let feeText: string | null
  if (l.platform === 'direct' && !hasDirectPrices && cheapestPaidFeeCents !== null) {
    feeText = `~${centsToEuro(cheapestPaidFeeCents)} de frais de plateforme économisés`
  } else {
    feeText = l.delivery_fee_cents === null
      ? null
      : l.delivery_fee_cents === 0
        ? 'Free delivery'
        : `Delivery ${centsToEuro(l.delivery_fee_cents)}`
  }
  const minText = l.min_order_label ?? null
  const isPhone = l.platform === 'direct' && !l.platform_url
  const href = l.platform === 'direct' && phone
    ? `tel:${phone}`
    : l.platform_url ?? null
  return { platform: l.platform, colors, feeText, minText, href, isPhone, label: PLATFORM_LABELS[l.platform] }
})
```

- [ ] **Step 3: Run frontend tests**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 4: Start dev server and verify manually**

```bash
cd forkeur-app && npm run dev -- --port 30000
```

Open a restaurant detail page that has a direct listing but no direct menu items. The platform fee bar should show `~€X.XX de frais de plateforme économisés` next to the Direct label.

Open a restaurant detail page with no direct listing — no change.

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/BasketSimulator.tsx
git commit -m "feat: phase 2 — fee-savings framing in basket for direct listings without menu data"
```

---

## Phase 3 — Structured Menu Scrapers

---

### Task 7: `direct_menu.py` — adapters + fixture files + tests

**Files:**
- Create: `backend/scrapers/direct_menu.py`
- Create: `backend/tests/test_direct_menu.py`
- Create: `backend/tests/fixtures/sq_menu_response.json`
- Create: `backend/tests/fixtures/odoo_pos_response.json`
- Create: `backend/tests/fixtures/piki_app_response.json`

- [ ] **Step 1: Investigate live sq-menu.com API**

Run the following to find the sq-menu URLs in the DB:

```python
# Run from backend/ directory:
# uv run python -c "
import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
import db
rows = db.get_client().table('platform_listings').select('url').eq('platform','direct').eq('url_type','ordering').execute().data
sqm = [r['url'] for r in rows if 'sq-menu' in (r['url'] or '')]
print('\n'.join(sqm[:5]))
# "
```

Then fetch one URL to observe the API response structure:

```bash
curl -s "https://[slug-from-above].sq-menu.com/api/v1/catalog" | python3 -m json.tool | head -60
```

Note the actual response structure (sections/categories, item field names, price format). The adapter below implements against the fixture shape. If the real API returns different field names (e.g. `categories` instead of `sections`, `price_cents` instead of `price`), update `_parse_sq_menu_response` AND the fixture file to match before writing the test — the fixture is the contract.

- [ ] **Step 2: Create fixture files**

Create `backend/tests/fixtures/sq_menu_response.json`:

```json
{
  "sections": [
    {
      "name": "Burgers",
      "items": [
        {
          "name": "Classic Burger",
          "price": 8.50,
          "description": "Beef patty, lettuce, tomato",
          "image_url": null
        },
        {
          "name": "Cheese Burger",
          "price": 9.00,
          "description": null,
          "image_url": null
        }
      ]
    },
    {
      "name": "Sides",
      "items": [
        {
          "name": "Frites",
          "price": 3.50,
          "description": null,
          "image_url": null
        }
      ]
    }
  ]
}
```

Create `backend/tests/fixtures/odoo_pos_response.json`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": [
    {
      "name": "Pizza Margherita",
      "list_price": 12.50,
      "pos_category_id": [1, "Pizzas"],
      "description_sale": "Tomato sauce, mozzarella",
      "image_128": null
    },
    {
      "name": "Pizza Napolitaine",
      "list_price": 14.00,
      "pos_category_id": [1, "Pizzas"],
      "description_sale": null,
      "image_128": null
    },
    {
      "name": "Tiramisu",
      "list_price": 5.50,
      "pos_category_id": [2, "Desserts"],
      "description_sale": "Italian classic",
      "image_128": null
    }
  ]
}
```

Create `backend/tests/fixtures/piki_app_response.json`:

```json
[
  {
    "name": "Sushis",
    "products": [
      {
        "name": "Salmon Roll (8 pcs)",
        "price": 14.00,
        "description": "Fresh Atlantic salmon",
        "image_url": null
      },
      {
        "name": "Tuna Maki (6 pcs)",
        "price": 12.50,
        "description": null,
        "image_url": null
      }
    ]
  }
]
```

- [ ] **Step 3: Write failing tests**

Create `backend/tests/test_direct_menu.py`:

```python
import pytest
import json
import sys, os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

FIXTURES = Path(__file__).parent / 'fixtures'


def test_sq_menu_slug_extraction():
    from scrapers.direct_menu import _sq_menu_slug
    assert _sq_menu_slug('https://burger-palace.sq-menu.com/') == 'burger-palace'
    assert _sq_menu_slug('https://example.com/') is None
    assert _sq_menu_slug('https://my-place.sq-menu.com/order/start') == 'my-place'


def test_parse_sq_menu_response():
    from scrapers.direct_menu import _parse_sq_menu_response
    data = json.loads((FIXTURES / 'sq_menu_response.json').read_text())
    items = _parse_sq_menu_response(data)
    assert len(items) == 3
    assert items[0] == {
        'title': 'Classic Burger',
        'price': 8.50,
        'catalog_name': 'Burgers',
        'description': 'Beef patty, lettuce, tomato',
        'image_url': None,
    }
    assert items[1]['catalog_name'] == 'Burgers'
    assert items[2]['catalog_name'] == 'Sides'
    assert items[2]['title'] == 'Frites'


def test_parse_sq_menu_skips_items_without_price():
    from scrapers.direct_menu import _parse_sq_menu_response
    data = {"sections": [{"name": "Menu", "items": [
        {"name": "Item A", "price": 5.00},
        {"name": "No price item"},
    ]}]}
    items = _parse_sq_menu_response(data)
    assert len(items) == 1
    assert items[0]['title'] == 'Item A'


def test_parse_odoo_pos_response():
    from scrapers.direct_menu import _parse_odoo_pos_response
    data = json.loads((FIXTURES / 'odoo_pos_response.json').read_text())
    items = _parse_odoo_pos_response(data)
    assert len(items) == 3
    assert items[0] == {
        'title': 'Pizza Margherita',
        'price': 12.50,
        'catalog_name': 'Pizzas',
        'description': 'Tomato sauce, mozzarella',
        'image_url': None,
    }
    assert items[2]['catalog_name'] == 'Desserts'
    assert items[2]['price'] == 5.50


def test_parse_odoo_pos_skips_no_name():
    from scrapers.direct_menu import _parse_odoo_pos_response
    data = {"result": [
        {"name": "Burger", "list_price": 8.50, "pos_category_id": [1, "Menu"]},
        {"name": "", "list_price": 5.00, "pos_category_id": [1, "Menu"]},
        {"list_price": 3.00, "pos_category_id": [1, "Menu"]},
    ]}
    items = _parse_odoo_pos_response(data)
    assert len(items) == 1


def test_parse_piki_app_response():
    from scrapers.direct_menu import _parse_piki_app_response
    data = json.loads((FIXTURES / 'piki_app_response.json').read_text())
    items = _parse_piki_app_response(data)
    assert len(items) == 2
    assert items[0] == {
        'title': 'Salmon Roll (8 pcs)',
        'price': 14.00,
        'catalog_name': 'Sushis',
        'description': 'Fresh Atlantic salmon',
        'image_url': None,
    }


def test_pick_adapter_sq_menu():
    from scrapers.direct_menu import _pick_adapter
    fn = _pick_adapter('https://burger.sq-menu.com/order')
    assert fn is not None
    assert fn.__name__ == '_fetch_sq_menu'


def test_pick_adapter_odoo():
    from scrapers.direct_menu import _pick_adapter
    fn = _pick_adapter('https://restaurant.odoo.com/pos-self/menu')
    assert fn is not None
    assert fn.__name__ == '_fetch_odoo_pos'


def test_pick_adapter_piki():
    from scrapers.direct_menu import _pick_adapter
    fn = _pick_adapter('https://piki-app.com/vendor/sushi/categories')
    assert fn is not None
    assert fn.__name__ == '_fetch_piki_app'


def test_pick_adapter_unknown_returns_none():
    from scrapers.direct_menu import _pick_adapter
    assert _pick_adapter('https://myrestaurant.be') is None
```

- [ ] **Step 4: Run tests — verify they all fail**

```bash
cd backend && uv run pytest tests/test_direct_menu.py -v
```

Expected: all fail with `ImportError` or `ModuleNotFoundError`.

- [ ] **Step 5: Implement `direct_menu.py`**

Create `backend/scrapers/direct_menu.py`:

```python
"""
Structured direct-menu scrapers: sq-menu, odoo-pos, piki-app.
Uses httpx (JSON only — no Playwright).
"""
from __future__ import annotations
import asyncio
import re
from urllib.parse import urlparse
from typing import Callable
import httpx
from models import ScraperResult, ScraperConfig
from scrapers.base import noop_log
import db


# ── sq-menu.com ───────────────────────────────────────────────────────────────

def _sq_menu_slug(url: str) -> str | None:
    """'https://burger.sq-menu.com/' → 'burger'"""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    m = re.match(r'^(.+)\.sq-menu\.com$', host)
    return m.group(1) if m else None


def _parse_sq_menu_response(data: dict) -> list[dict]:
    items: list[dict] = []
    for section in data.get('sections', []):
        category = section.get('name', 'Menu')
        for item in section.get('items', []):
            price_raw = item.get('price') or item.get('price_money', {}).get('amount')
            if price_raw is None:
                continue
            price_euros = float(price_raw) / 100 if float(price_raw) > 100 else float(price_raw)
            items.append({
                'title': item.get('name', ''),
                'price': round(price_euros, 2),
                'catalog_name': category,
                'description': item.get('description') or None,
                'image_url': item.get('image_url') or None,
            })
    return items


async def _fetch_sq_menu(url: str, log: Callable) -> list[dict]:
    slug = _sq_menu_slug(url)
    if not slug:
        log(f"  sq-menu: can't extract slug from {url}")
        return []

    api_url = f"https://{slug}.sq-menu.com/api/v1/catalog"
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log(f"  sq-menu fetch failed ({slug}): {e}")
            return []

    return _parse_sq_menu_response(data)


# ── odoo_pos ──────────────────────────────────────────────────────────────────

def _parse_odoo_pos_response(data: dict) -> list[dict]:
    result = data.get('result', [])
    if not isinstance(result, list):
        return []

    items: list[dict] = []
    for product in result:
        name = product.get('name', '')
        price = product.get('list_price')
        if not name or price is None:
            continue
        category_raw = product.get('pos_category_id')
        category = (
            category_raw[1]
            if isinstance(category_raw, (list, tuple)) and len(category_raw) > 1
            else 'Menu'
        )
        items.append({
            'title': name,
            'price': round(float(price), 2),
            'catalog_name': category,
            'description': product.get('description_sale') or None,
            'image_url': None,
        })
    return items


async def _fetch_odoo_pos(url: str, log: Callable) -> list[dict]:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    rpc_url = f"{base}/web/dataset/call_kw"
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": 1,
        "params": {
            "model": "product.product",
            "method": "search_read",
            "args": [[["available_in_pos", "=", True]]],
            "kwargs": {
                "fields": ["name", "list_price", "pos_category_id", "description_sale"],
                "limit": 500,
            },
        },
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.post(rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log(f"  odoo_pos fetch failed ({base}): {e}")
            return []

    return _parse_odoo_pos_response(data)


# ── piki-app.com ──────────────────────────────────────────────────────────────

def _parse_piki_app_response(data: list | dict) -> list[dict]:
    categories = data if isinstance(data, list) else data.get('categories', [])
    items: list[dict] = []
    for cat in categories:
        category = cat.get('name', 'Menu')
        for product in cat.get('products', []):
            name = product.get('name', '')
            price = product.get('price') or product.get('price_in_cents')
            if not name or price is None:
                continue
            price_euros = float(price) / 100 if float(price) > 100 else float(price)
            items.append({
                'title': name,
                'price': round(price_euros, 2),
                'catalog_name': category,
                'description': product.get('description') or None,
                'image_url': product.get('image_url') or None,
            })
    return items


async def _fetch_piki_app(url: str, log: Callable) -> list[dict]:
    # Ensure we're hitting the categories endpoint
    if 'categories' not in url:
        parsed = urlparse(url)
        m = re.search(r'/vendor/([^/]+)', parsed.path)
        if m:
            slug = m.group(1)
            url = f"{parsed.scheme}://{parsed.netloc}/vendor/{slug}/categories"
        else:
            log(f"  piki-app: can't resolve categories URL from {url}")
            return []

    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log(f"  piki-app fetch failed: {e}")
            return []

    return _parse_piki_app_response(data)


# ── Dispatcher ────────────────────────────────────────────────────────────────

_URL_ADAPTERS: list[tuple[str, Callable]] = [
    ('sq-menu.com', _fetch_sq_menu),
    ('odoo.com',    _fetch_odoo_pos),
    ('piki-app.com', _fetch_piki_app),
]


def _pick_adapter(url: str) -> Callable | None:
    host = urlparse(url).netloc.lower()
    for pattern, fn in _URL_ADAPTERS:
        if pattern in host:
            return fn
    return None


# ── Entry point ───────────────────────────────────────────────────────────────

async def run(config: ScraperConfig | None = None, log: Callable = noop_log) -> ScraperResult:
    """Scrape menus from all direct listings with structured adapters."""
    client = db.get_client()
    listings = (
        client.table('platform_listings')
        .select('id, url, url_type')
        .eq('platform', 'direct')
        .eq('url_type', 'ordering')
        .not_.is_('url', 'null')
        .execute()
    ).data

    log(f"direct_menu: {len(listings)} ordering listings")

    max_items = config.max_items if config else None
    if max_items:
        listings = listings[:max_items]

    total_saved = 0
    for listing in listings:
        url = listing['url']
        adapter = _pick_adapter(url)
        if not adapter:
            log(f"  skip (no adapter): {url[:60]}")
            continue

        log(f"  → {url[:60]}")
        items = await adapter(url, log)

        if not items:
            log(f"     0 items")
            continue

        saved = db.insert_menu_items(listing['id'], items)
        total_saved += saved
        log(f"     {saved} items saved")

        await asyncio.sleep(0.5)

    log(f"\ndone — {total_saved} menu items total")
    return ScraperResult(records_saved=total_saved)
```

- [ ] **Step 6: Run tests — all pass**

```bash
cd backend && uv run pytest tests/test_direct_menu.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 7: Run full backend test suite**

```bash
cd backend && uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/scrapers/direct_menu.py backend/tests/test_direct_menu.py backend/tests/fixtures/
git commit -m "feat: direct_menu scrapers — sq-menu, odoo-pos, piki-app adapters with fixture tests"
```

---

### Task 8: Wire `direct_menu.run` to scheduler + router

**Files:**
- Modify: `backend/scheduler.py`
- Modify: `backend/routers/scrapers.py`

- [ ] **Step 1: Update `scheduler.py` — swap `direct` to `direct_menu`**

In `backend/scheduler.py`, find line 21-22:
```python
from scrapers import ubereats, deliveroo, takeaway, direct
SCRAPERS = {"ubereats": ubereats.run, "deliveroo": deliveroo.run, "takeaway": takeaway.run, "direct": direct.run}
```

Change to:
```python
from scrapers import ubereats, deliveroo, takeaway, direct_menu
SCRAPERS = {"ubereats": ubereats.run, "deliveroo": deliveroo.run, "takeaway": takeaway.run, "direct": direct_menu.run}
```

- [ ] **Step 2: Update `routers/scrapers.py` — swap `direct` to `direct_menu`**

In `backend/routers/scrapers.py`, find line 7:
```python
from scrapers import ubereats, deliveroo, takeaway, fees, direct
```

Change to:
```python
from scrapers import ubereats, deliveroo, takeaway, fees, direct_menu
```

Find lines 12-17:
```python
SCRAPERS = {
    "ubereats": ubereats.run,
    "deliveroo": deliveroo.run,
    "takeaway": takeaway.run,
    "direct": direct.run,
}
```

Change to:
```python
SCRAPERS = {
    "ubereats": ubereats.run,
    "deliveroo": deliveroo.run,
    "takeaway": takeaway.run,
    "direct": direct_menu.run,
}
```

- [ ] **Step 3: Run backend tests**

```bash
cd backend && uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Start backend locally and test API endpoint**

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

In another terminal (get auth token first, then):
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"<ADMIN_PASSWORD>"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -X POST "http://localhost:8000/api/scrapers/direct/run?test_mode=true" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `{"run_id": "<uuid>"}` — scraper starts.

Check scraper run log:
```bash
curl -s "http://localhost:8000/api/runs" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -20
```

Expected: recent `direct` run with `status: success` and some `records_saved`.

- [ ] **Step 5: Commit**

```bash
git add backend/scheduler.py backend/routers/scrapers.py
git commit -m "feat: wire direct_menu.run to 'direct' scraper key in scheduler + router"
```

---

## Phase 4 — Price Comparison + Alerts

---

### Task 9: Normalized match key in `queries.ts`

**Files:**
- Modify: `forkeur-app/lib/queries.ts`
- Create: `forkeur-app/__tests__/normalize.test.ts`

- [ ] **Step 1: Write failing test**

Create `forkeur-app/__tests__/normalize.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { normalizeTitle } from '../lib/queries'

describe('normalizeTitle', () => {
  it('lowercases', () => {
    expect(normalizeTitle('Big Mac')).toBe('big mac')
  })

  it('strips accents', () => {
    expect(normalizeTitle('Crème brûlée')).toBe('creme brulee')
  })

  it('strips é, à, ñ', () => {
    expect(normalizeTitle('Café au Réglisse Américain')).toBe('cafe au reglisse americain')
  })

  it('strips punctuation', () => {
    expect(normalizeTitle('Pizza (San Marzano, bufala)')).toBe('pizza san marzano bufala')
  })

  it('strips hyphens and apostrophes', () => {
    expect(normalizeTitle("Pain d'épices")).toBe('pain depices')
  })

  it('collapses multiple spaces', () => {
    expect(normalizeTitle('Big   Mac')).toBe('big mac')
  })

  it('trims leading/trailing whitespace', () => {
    expect(normalizeTitle('  Big Mac  ')).toBe('big mac')
  })

  it('cross-platform match: same logical item normalizes to same key', () => {
    expect(normalizeTitle('Pizza Margherita')).toBe(normalizeTitle('pizza margherita'))
  })

  it('does NOT merge different items', () => {
    expect(normalizeTitle('Pizza Margherita')).not.toBe(normalizeTitle('Pizza Napolitaine'))
  })
})
```

- [ ] **Step 2: Run — verify it fails**

```bash
cd forkeur-app && npx vitest run __tests__/normalize.test.ts
```

Expected: `SyntaxError` or `not a function` — `normalizeTitle` not exported yet.

- [ ] **Step 3: Add `normalizeTitle` to `queries.ts`**

In `forkeur-app/lib/queries.ts`, add this function **before** the `getRestaurantWithListings` function and **export** it:

```typescript
export function normalizeTitle(title: string): string {
  return title
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}
```

- [ ] **Step 4: Update the item-grouping key in `getRestaurantWithListings`**

Find line ~227 in `getRestaurantWithListings`:
```typescript
const key = item.title
```

Change to:
```typescript
const key = normalizeTitle(item.title)
```

The `name: item.title` line below stays unchanged — display name is the first-seen raw title.

- [ ] **Step 5: Run tests**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass (including the new normalize.test.ts).

- [ ] **Step 6: Validate on a live restaurant**

With dev server running on port 30000, open a restaurant detail page with menu items. Confirm item counts look reasonable — no unexpected merging of distinct items, no unexpected splits of the same item.

- [ ] **Step 7: Commit**

```bash
git add forkeur-app/lib/queries.ts forkeur-app/__tests__/normalize.test.ts
git commit -m "feat: normalized match key for cross-platform menu item grouping"
```

---

### Task 10: Overlap threshold + direct savings helpers in `basket.ts`

**Files:**
- Modify: `forkeur-app/lib/basket.ts`
- Modify: `forkeur-app/__tests__/basket.test.ts`

- [ ] **Step 1: Write failing tests**

Add the following to the end of `forkeur-app/__tests__/basket.test.ts`:

```typescript
import {
  computeDirectOverlap,
  computeDirectSubtotal,
  computeDirectSavingsCents,
  type PlatformFees,
} from '../lib/basket'

const standardFees: PlatformFees = {
  uber_eats: 249,
  deliveroo: 199,
  takeaway: 299,
  direct: null,
}

describe('computeDirectOverlap', () => {
  it('below threshold: fewer than 3 matched items', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
    ]
    const result = computeDirectOverlap(items)
    expect(result.thresholdMet).toBe(false)
    expect(result.matchedCount).toBe(2)
  })

  it('threshold met: exactly 3 matched items, 100% basket', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
      { name: 'C', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
    ]
    expect(computeDirectOverlap(items).thresholdMet).toBe(true)
  })

  it('boundary: 3 matched out of 6 = exactly 50%', () => {
    const m = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 }
    const u = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null }
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: m },
      { name: 'B', qty: 1, prices: m },
      { name: 'C', qty: 1, prices: m },
      { name: 'D', qty: 1, prices: u },
      { name: 'E', qty: 1, prices: u },
      { name: 'F', qty: 1, prices: u },
    ]
    expect(computeDirectOverlap(items).thresholdMet).toBe(true)
  })

  it('below threshold: 3 matched out of 7 < 50%', () => {
    const m = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 }
    const u = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null }
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: m },
      { name: 'B', qty: 1, prices: m },
      { name: 'C', qty: 1, prices: m },
      { name: 'D', qty: 1, prices: u },
      { name: 'E', qty: 1, prices: u },
      { name: 'F', qty: 1, prices: u },
      { name: 'G', qty: 1, prices: u },
    ]
    expect(computeDirectOverlap(items).thresholdMet).toBe(false)
  })

  it('ignores items with qty=0', () => {
    const m = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 }
    const items: BasketItem[] = [
      { name: 'A', qty: 0, prices: m },
      { name: 'B', qty: 1, prices: m },
      { name: 'C', qty: 1, prices: m },
      { name: 'D', qty: 1, prices: m },
    ]
    const result = computeDirectOverlap(items)
    expect(result.basketCount).toBe(3)
    expect(result.matchedCount).toBe(3)
  })
})

describe('computeDirectSubtotal', () => {
  it('sums price * qty for items with direct prices, skips others', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 2, prices: { uber_eats: 100, deliveroo: 100, takeaway: 100, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 100, deliveroo: 100, takeaway: 100, direct: null } },
    ]
    expect(computeDirectSubtotal(items)).toBe(1000)
  })
})

describe('computeDirectSavingsCents — three alert states', () => {
  const makeItems = (directPrices: number[]): BasketItem[] =>
    directPrices.map((d, i) => ({
      name: `Item${i}`,
      qty: 1,
      prices: { uber_eats: 1000, deliveroo: 900, takeaway: 1100, direct: d },
    }))

  it('state 1: direct cheaper + threshold met → positive savings', () => {
    // 3 items: direct=600 each, cheapest platform=deliveroo: 3*900+199=2899, direct=3*600=1800
    const items = makeItems([600, 600, 600])
    const savings = computeDirectSavingsCents(items, standardFees)
    expect(savings).toBe(2899 - 1800)  // 1099
  })

  it('state 2: direct same/higher + threshold met → null', () => {
    // 3 items: direct=1200 each → direct subtotal > cheapest platform total
    const items = makeItems([1200, 1200, 1200])
    expect(computeDirectSavingsCents(items, standardFees)).toBeNull()
  })

  it('state 3: below threshold → null regardless of price', () => {
    // Only 2 matched items
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 900, takeaway: 1100, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 900, takeaway: 1100, direct: 500 } },
    ]
    expect(computeDirectSavingsCents(items, standardFees)).toBeNull()
  })
})
```

- [ ] **Step 2: Run — verify they fail**

```bash
cd forkeur-app && npx vitest run __tests__/basket.test.ts
```

Expected: `computeDirectOverlap is not a function` or similar.

- [ ] **Step 3: Implement helpers in `basket.ts`**

Add to the end of `forkeur-app/lib/basket.ts`:

```typescript
export type DirectOverlap = {
  matchedCount: number
  basketCount: number
  thresholdMet: boolean
}

export function computeDirectOverlap(items: BasketItem[]): DirectOverlap {
  const activeItems = items.filter(b => b.qty > 0)
  const basketCount = activeItems.length
  const matchedCount = activeItems.filter(b => b.prices.direct !== null).length
  const thresholdMet = matchedCount >= 3 && basketCount > 0 && matchedCount / basketCount >= 0.5
  return { matchedCount, basketCount, thresholdMet }
}

export function computeDirectSubtotal(items: BasketItem[]): number {
  return items.reduce((sum, b) => {
    const price = b.prices.direct
    return price !== null ? sum + price * b.qty : sum
  }, 0)
}

export function computeDirectSavingsCents(
  items: BasketItem[],
  fees: PlatformFees
): number | null {
  const overlap = computeDirectOverlap(items)
  if (!overlap.thresholdMet) return null

  const nonDirectTotals = PLATFORMS
    .filter(p => p !== 'direct')
    .map(p => calculatePlatformTotal(items, p, fees[p]))
    .filter((t): t is number => t !== null)

  if (nonDirectTotals.length === 0) return null

  const cheapestPlatformTotal = Math.min(...nonDirectTotals)
  const directSubtotal = computeDirectSubtotal(items)
  const savings = cheapestPlatformTotal - directSubtotal
  return savings > 0 ? savings : null
}
```

- [ ] **Step 4: Run tests — all pass**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/lib/basket.ts forkeur-app/__tests__/basket.test.ts
git commit -m "feat: overlap threshold + direct savings helpers in basket.ts"
```

---

### Task 11: Basket savings banner in `BasketSimulator`

**Files:**
- Modify: `forkeur-app/components/BasketSimulator.tsx`

- [ ] **Step 1: Add imports**

At the top of `BasketSimulator.tsx`, add to the existing import from `@/lib/basket`:

```typescript
import {
  // ... existing imports ...
  computeDirectSavingsCents,
} from '@/lib/basket'
```

- [ ] **Step 2: Add `directSavingsCents` memo**

After the `const savingsCents = ...` computation, add:

```tsx
const directSavingsCents = useMemo(
  () => computeDirectSavingsCents(basket, fees),
  [basket, fees]
)
```

- [ ] **Step 3: Add savings banner to JSX**

In the JSX, find `{/* Spacer so content isn't hidden behind sticky bar */}` (line ~277). Add the savings banner **before** that spacer:

```tsx
{/* Direct ordering savings banner */}
{directSavingsCents !== null && basket.length > 0 && (
  <div className="mb-4 p-3.5 rounded-xl bg-orange-50 border border-orange-200">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-sm font-bold text-orange-700">
          Commander directement vous économise {centsToEuro(directSavingsCents)}
        </p>
        <p className="text-xs text-orange-500 mt-0.5">
          Mêmes plats · sans frais de plateforme
        </p>
      </div>
      {listings.find(l => l.platform === 'direct')?.platform_url && (
        <a
          href={listings.find(l => l.platform === 'direct')!.platform_url!}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 px-3 py-1.5 rounded-lg bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 transition-colors"
        >
          Commander →
        </a>
      )}
    </div>
  </div>
)}
```

- [ ] **Step 4: Run tests**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 5: Verify in browser**

Start dev server on port 30000. Navigate to a restaurant with direct menu items and add 3+ basket items that have direct prices. The orange savings banner should appear when direct is cheaper.

Navigate to a restaurant where direct is the same or more expensive — banner should not appear.

Navigate to a restaurant with fewer than 3 direct-priced items in basket — banner should not appear.

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/components/BasketSimulator.tsx
git commit -m "feat: phase 4 — direct savings banner in basket when threshold met"
```

---

### Task 12: Item-level orange highlight for cheapest-direct prices

**Files:**
- Modify: `forkeur-app/components/BasketSimulator.tsx`

- [ ] **Step 1: Update item price cell styling**

In `BasketSimulator.tsx`, find the menu table price cell (line ~229-234):

```tsx
const isCheapest = platform === cheapest && price !== null
return (
  <td key={platform} className="text-center py-3 w-14">
    <span className={`text-xs ${isCheapest ? 'font-semibold text-green-600' : price !== null ? 'text-stone-500' : 'text-stone-300'}`}>
      {price !== null ? centsToEuro(price) : '—'}
    </span>
  </td>
)
```

Replace with:

```tsx
const isCheapest = platform === cheapest && price !== null
const isDirectCheapest = platform === 'direct' && isCheapest
const priceClass = isDirectCheapest
  ? 'font-semibold text-orange-500'
  : isCheapest
    ? 'font-semibold text-green-600'
    : price !== null
      ? 'text-stone-500'
      : 'text-stone-300'
return (
  <td key={platform} className="text-center py-3 w-14">
    <span className={`text-xs ${priceClass}`}>
      {price !== null ? centsToEuro(price) : '—'}
    </span>
  </td>
)
```

- [ ] **Step 2: Run tests**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 3: Verify in browser**

For a restaurant with direct menu items, open the detail page and add items to the basket. When a direct price is the cheapest for an item, the price should appear in orange. Other cheapest-platform prices remain green.

- [ ] **Step 4: Commit**

```bash
git add forkeur-app/components/BasketSimulator.tsx
git commit -m "feat: orange highlight for item-level cheapest direct prices"
```

---

### Task 13: Restaurant card url_type CTA copy

**Files:**
- Modify: `forkeur-app/components/RestaurantCard.tsx`
- Modify: `forkeur-app/__tests__/restaurant-card.test.tsx`

- [ ] **Step 1: Add url_type fixture and test to restaurant-card.test.tsx**

In `forkeur-app/__tests__/restaurant-card.test.tsx`, add a fixture with a direct listing and url_type, then add tests:

```typescript
const withDirectOrdering: RestaurantSummary = {
  id: '5',
  name: 'Burger Direct',
  cuisine: ['Burgers'],
  lat: null,
  lng: null,
  order_url: 'https://burger.sq-menu.com',
  direct_url_type: 'ordering',
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 299 },
    { platform: 'deliveroo', delivery_fee_cents: 199 },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€1.99', savings_cents: 100 },
}

const withDirectMenu: RestaurantSummary = {
  id: '6',
  name: 'Pizza Direct',
  cuisine: ['Pizza'],
  lat: null,
  lng: null,
  order_url: 'https://pizza.be/menu',
  direct_url_type: 'menu',
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 299 },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€2.99', savings_cents: 0 },
}
```

Add tests at the end of the `describe('RestaurantCard')` block:

```typescript
it('shows "Commander directement" when url_type is ordering', () => {
  render(<RestaurantCard restaurant={withDirectOrdering} />)
  expect(screen.getByRole('link', { name: /Commander directement/i })).toBeInTheDocument()
})

it('shows "Voir le menu" when url_type is menu', () => {
  render(<RestaurantCard restaurant={withDirectMenu} />)
  expect(screen.getByRole('link', { name: /Voir le menu/i })).toBeInTheDocument()
})

it('shows "Site du restaurant" when url_type is website', () => {
  const withWebsite: RestaurantSummary = {
    ...withDirectOrdering,
    id: '7',
    direct_url_type: 'website',
  }
  render(<RestaurantCard restaurant={withWebsite} />)
  expect(screen.getByRole('link', { name: /Site du restaurant/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests — verify new tests fail**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```

Expected: new tests fail (component still shows static copy).

- [ ] **Step 3: Update `RestaurantCard.tsx`**

In `forkeur-app/components/RestaurantCard.tsx`:

Change the import to destructure `direct_url_type`:
```tsx
const { name, cuisine, listings, cheapest, order_url, direct_url_type } = restaurant
```

Replace the static CTA copy with url_type-driven copy:
```tsx
{order_url && (
  <a
    href={order_url}
    target="_blank"
    rel="noopener noreferrer"
    onClick={(e) => e.stopPropagation()}
    className="inline-flex items-center gap-1 mb-2.5 px-2.5 py-1 rounded-full bg-orange-50 border border-orange-200 text-orange-600 text-[11px] font-semibold hover:bg-orange-100 transition-colors"
  >
    {direct_url_type === 'menu'
      ? 'Voir le menu'
      : direct_url_type === 'website'
        ? 'Site du restaurant'
        : 'Commander directement'}
  </a>
)}
```

- [ ] **Step 4: Run tests — all pass**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/RestaurantCard.tsx forkeur-app/__tests__/restaurant-card.test.tsx
git commit -m "feat: url_type-aware CTA copy on restaurant card (Commander/Voir le menu/Site)"
```

> **Known v1 gap:** The spec also describes a "X% moins cher en direct" badge on the card when direct avg price < cheapest platform avg. This requires comparing menu item averages across platforms, but `RestaurantSummary` (homepage list query) contains no menu items. Computing it requires either a pre-computed `direct_savings_pct` field on `platform_listings` (populated by `direct_menu.run` after scraping) or an expensive per-card join. Deferred to a follow-up task.

---

### Task 14: Final verification + deploy

- [ ] **Step 1: Run all tests**

```bash
cd backend && uv run pytest -v
cd ../forkeur-app && npx vitest run
```

Expected: all pass.

- [ ] **Step 2: Verify all 4 phases in browser on port 30000**

Phase 1: Homepage shows direct listings. Restaurant cards with `order_url` show correct CTA label.

Phase 2: Restaurant detail page → basket simulator → platform fee bar shows `~€X.XX de frais de plateforme économisés` for direct when no direct menu items.

Phase 3: Navigate to one of the ~8-15 sq-menu/odoo/piki-app restaurants. Verify the menu table's `DIR` column has prices.

Phase 4: Build a basket of 3+ items with direct prices. When direct is cheaper: orange savings banner appears, direct prices appear in orange in the item table. When direct is more expensive: no banner, direct prices show normally.

- [ ] **Step 3: Deploy to production**

```bash
ssh -i ~/.ssh/id_ed25519 root@178.104.57.72
cd /opt/forkeur && git pull && systemctl restart forkeur-backend && systemctl restart forkeur-frontend
```

- [ ] **Step 4: Trigger direct_menu scraper in production**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"<ADMIN_PASSWORD>"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -X POST "http://localhost:8000/api/scrapers/direct/run" \
  -H "Authorization: Bearer $TOKEN"
```

Wait ~60 seconds, then check:

```sql
SELECT COUNT(*) FROM menu_items mi
JOIN platform_listings pl ON mi.listing_id = pl.id
WHERE pl.platform = 'direct';
```

Expected: > 0 rows (menu items saved for structured restaurants).

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: direct ordering — phases 1-4 complete"
```
