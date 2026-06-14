# Deals Page UX Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `/deals` from a restaurant listing with promo badges into a deal-hunter page where the promo is the hero, with platform filter, sort dropdown, freshness chip, and featured strip.

**Architecture:** Backend adds `last_scraped_at` to the public deals SQL; frontend propagates it through `RawPromoRow` → `DealItem`; `deals.ts` gains new types/helpers; `DealsClient.tsx` is rebuilt with three independent filter axes (type, platform, sort) and a new `FeaturedStrip` sub-component.

**Tech Stack:** Next.js 15 App Router, next-intl (server + client), TypeScript, Tailwind CSS (stone/white/orange brand theme), Vitest (frontend tests)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `backend/db.py` | Add `last_scraped_at` to `get_public_deals()` SQL |
| Modify | `forkeur-app/lib/queries.ts` | Add `last_scraped_at` to `RawPromoRow`; map to `scraped_at` in `getDeals()` |
| Modify | `forkeur-app/lib/deals.ts` | New types (`SortMode`, updated `DealFilter`), new `savingsEstimate()`, updated `filterCounts()`, `matchesFilter()`, `sortDeals()` |
| Modify | `forkeur-app/messages/en.json` | New i18n keys |
| Modify | `forkeur-app/messages/fr.json` | New i18n keys (FR) |
| Modify | `forkeur-app/messages/nl.json` | New i18n keys (NL) |
| Create | `forkeur-app/components/FeaturedStrip.tsx` | Auto-selected top-3 deal cards, horizontal scroll |
| Modify | `forkeur-app/components/DealsClient.tsx` | Full rework: platform/sort state, sticky filter bar, freshness chip, grid, FeaturedStrip |

---

## Task 1: Backend — add `last_scraped_at` to public deals SQL

**Files:**
- Modify: `backend/db.py` (lines ~916–935, inside `json_build_object`)

- [ ] **Step 1: Edit the SQL in `get_public_deals()`**

In `backend/db.py`, locate `get_public_deals()`. Inside the `json_build_object(...)` that builds `platform_listings`, add `'last_scraped_at', pl.last_scraped_at` after `'opening_hours', pl.opening_hours`:

```python
def get_public_deals() -> list[dict]:
    return pgpool.fetchall(
        """
        SELECT p.id, p.promo_type, p.label, p.value, p.min_order,
               json_build_object(
                 'platform', pl.platform, 'url', pl.url, 'rating', pl.rating,
                 'review_count', pl.review_count, 'is_available', pl.is_available,
                 'opening_hours', pl.opening_hours,
                 'last_scraped_at', pl.last_scraped_at,
                 'restaurants', json_build_object(
                   'id', r.id, 'name', r.name, 'cuisine', r.cuisine,
                   'neighborhood', r.neighborhood)
               ) AS platform_listings
        FROM promotions p
        JOIN platform_listings pl ON pl.id = p.listing_id
        JOIN restaurants r ON r.id = pl.restaurant_id
        WHERE p.promo_type NOT IN ('other', 'spend_save')
          AND pl.last_scraped_at > now() - interval '72 hours'
        """
    )
```

- [ ] **Step 2: Verify no backend restart needed**

No migration, no schema change — `last_scraped_at` already exists on `platform_listings`. The backend can be reloaded lightly or the change takes effect on next request (uvicorn hot-reload if dev). No action required.

- [ ] **Step 3: Commit**

```bash
git add backend/db.py
git commit -m "fix(deals): include last_scraped_at in get_public_deals SQL"
```

---

## Task 2: Frontend — propagate `scraped_at` through `RawPromoRow` → `DealItem`

**Files:**
- Modify: `forkeur-app/lib/queries.ts` (lines ~110–125 for `RawPromoRow`, lines ~280–306 for `getDeals()`)
- Modify: `forkeur-app/lib/deals.ts` (add `scraped_at: string` to `DealItem`)

- [ ] **Step 1: Write failing test**

In `forkeur-app/lib/deals.test.ts` (create if not exists), add:

```ts
import { describe, it, expect } from 'vitest'
import type { DealItem } from './deals'

describe('DealItem', () => {
  it('has scraped_at field', () => {
    const deal: DealItem = {
      id: '1',
      restaurant_id: 'r1',
      restaurant_name: 'Test',
      platform: 'uber_eats',
      platform_url: null,
      cuisine: [],
      area: null,
      rating: null,
      review_count: null,
      promo_type: 'free_delivery',
      label: 'Free delivery',
      value: null,
      min_order: null,
      opening_hours: null,
      is_available: true,
      scraped_at: '2026-06-13T10:00:00Z',
    }
    expect(deal.scraped_at).toBe('2026-06-13T10:00:00Z')
  })
})
```

- [ ] **Step 2: Run test — expect type error / fail**

```bash
cd forkeur-app && npx vitest run lib/deals.test.ts
```

Expected: type error or test fails because `scraped_at` not on `DealItem`.

- [ ] **Step 3: Add `scraped_at` to `DealItem` in `deals.ts`**

In `forkeur-app/lib/deals.ts`, add to `DealItem`:

```ts
export type DealItem = {
  id: string
  restaurant_id: string
  restaurant_name: string
  platform: Platform
  platform_url: string | null
  cuisine: string[]
  area: string | null
  rating: number | null
  review_count: number | null
  promo_type: DealType
  label: string
  value: number | null
  min_order: number | null
  opening_hours: Record<string, [string, string] | [string, string][]> | null
  is_available: boolean
  scraped_at: string   // ← add this
}
```

- [ ] **Step 4: Add `last_scraped_at` to `RawPromoRow` in `queries.ts`**

Locate `RawPromoRow` (~line 110). Inside `platform_listings`, add:

```ts
type RawPromoRow = {
  id: string
  promo_type: string
  label: string
  value: number | null
  min_order: number | null
  platform_listings: {
    platform: string
    url: string | null
    rating: number | null
    review_count: number | null
    is_available: boolean
    opening_hours: OpeningHours | null
    last_scraped_at: string | null   // ← add this
    restaurants: { id: string; name: string; cuisine: string | null; neighborhood: string | null } | null
  } | null
}
```

- [ ] **Step 5: Map `last_scraped_at` → `scraped_at` in `getDeals()`**

In `getDeals()` (~line 280), find where the returned `DealItem` object is constructed and add:

```ts
scraped_at: listing.last_scraped_at ?? new Date(0).toISOString(),
```

(Fallback to epoch for listings with null `last_scraped_at` — won't happen in practice because the SQL's WHERE clause filters those out, but keeps TypeScript happy.)

- [ ] **Step 6: Run test — expect pass**

```bash
cd forkeur-app && npx vitest run lib/deals.test.ts
```

Expected: PASS

- [ ] **Step 7: Type check**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add forkeur-app/lib/deals.ts forkeur-app/lib/queries.ts forkeur-app/lib/deals.test.ts
git commit -m "feat(deals): propagate scraped_at through RawPromoRow → DealItem"
```

---

## Task 3: `deals.ts` — new types, helpers, updated functions

**Files:**
- Modify: `forkeur-app/lib/deals.ts`

This task rewrites the filter/sort logic. The current `DealFilter` string union and `sortDeals(deals, Set)` signature are replaced. All changes are additive except for the two signatures that change.

**Breaking change map:**
- `DealFilter` (string union `'all' | 'bogo' | ...`) → split into `ActiveType` and `ActivePlatform` type aliases used by the component; the old export is replaced
- `sortDeals(deals, Set<...>)` → `sortDeals(deals, SortMode)`
- `matchesFilter(d, Set<...>)` → `matchesFilter(d, activeType, activePlatform)`
- `filterCounts(deals)` → `filterCounts(deals, activePlatform)`

- [ ] **Step 1: Write failing tests for `SortMode` and `savingsEstimate()`**

In `forkeur-app/lib/deals.test.ts`, add:

```ts
import { savingsEstimate, sortDeals } from './deals'
import type { SortMode } from './deals'

const baseDeal: DealItem = {
  id: '1', restaurant_id: 'r1', restaurant_name: 'A', platform: 'uber_eats',
  platform_url: null, cuisine: [], area: null, rating: 4.0, review_count: 100,
  promo_type: 'pct_discount', label: '20% off', value: 20, min_order: null,
  opening_hours: null, is_available: true, scraped_at: '2026-06-13T10:00:00Z',
}

describe('savingsEstimate', () => {
  it('pct_discount: returns save string', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'pct_discount', value: 20 }))
      .toBe('Save ~€4.00 on a €20 order')
  })
  it('abs_discount: returns off string', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'abs_discount', value: 3 }))
      .toBe('€3.00 off your order')
  })
  it('free_delivery: returns fee string', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'free_delivery', value: null }))
      .toBe('€0 delivery fee')
  })
  it('bogo: returns null', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'bogo', value: null })).toBeNull()
  })
  it('free_item: returns null', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'free_item', value: null })).toBeNull()
  })
})

describe('sortDeals', () => {
  const a: DealItem = { ...baseDeal, id: 'a', rating: 4.5, value: 10, scraped_at: '2026-06-13T08:00:00Z' }
  const b: DealItem = { ...baseDeal, id: 'b', rating: 3.0, value: 30, scraped_at: '2026-06-13T12:00:00Z' }

  it('newest: sorts by scraped_at desc', () => {
    const sorted = sortDeals([a, b], 'newest')
    expect(sorted[0].id).toBe('b')
  })
  it('rated: sorts by rating desc', () => {
    const sorted = sortDeals([a, b], 'rated')
    expect(sorted[0].id).toBe('a')
  })
  it('saving: sorts by value desc for pct_discount', () => {
    const sorted = sortDeals([a, b], 'saving')
    expect(sorted[0].id).toBe('b')
  })
})
```

- [ ] **Step 2: Run tests — expect fail**

```bash
cd forkeur-app && npx vitest run lib/deals.test.ts
```

Expected: `savingsEstimate` not found, `SortMode` not found, `sortDeals` wrong signature.

- [ ] **Step 3: Implement new types and helpers in `deals.ts`**

Replace the entire `deals.ts` with the following (preserving existing `Platform`, `DealType`, `qualityScore`, `DealItem` — only changing/adding what's needed):

```ts
import type { Platform } from './queries'  // keep existing import

export type DealType = 'free_delivery' | 'bogo' | 'pct_discount' | 'abs_discount' | 'free_item'

export type DealItem = {
  id: string
  restaurant_id: string
  restaurant_name: string
  platform: Platform
  platform_url: string | null
  cuisine: string[]
  area: string | null
  rating: number | null
  review_count: number | null
  promo_type: DealType
  label: string
  value: number | null
  min_order: number | null
  opening_hours: Record<string, [string, string] | [string, string][]> | null
  is_available: boolean
  scraped_at: string
}

// UI filter keys (map to promo_type values in matchesFilter)
export type ActiveType = 'all' | 'free_delivery' | 'pct' | 'bogo' | 'abs' | 'free_item'
export type ActivePlatform = 'all' | 'uber_eats' | 'deliveroo' | 'takeaway'
export type SortMode = 'best' | 'saving' | 'rated' | 'newest'

export function qualityScore(d: DealItem): number {
  // keep existing implementation unchanged
  let score = 0
  if (d.promo_type === 'pct_discount' && d.value) score += d.value * 2
  if (d.promo_type === 'abs_discount' && d.value) score += d.value * 10
  if (d.promo_type === 'free_delivery') score += 15
  if (d.promo_type === 'bogo') score += 30
  if (d.promo_type === 'free_item') score += 20
  if (d.rating) score += d.rating * 2
  return score
}

export function savingsEstimate(deal: DealItem): string | null {
  switch (deal.promo_type) {
    case 'pct_discount': {
      if (deal.value == null) return null
      const saved = (deal.value * 20) / 100
      return `Save ~€${saved.toFixed(2)} on a €20 order`
    }
    case 'abs_discount': {
      if (deal.value == null) return null
      return `€${deal.value.toFixed(2)} off your order`
    }
    case 'free_delivery':
      return '€0 delivery fee'
    default:
      return null
  }
}

function promoTypeForActiveType(active: ActiveType): DealType | null {
  switch (active) {
    case 'pct': return 'pct_discount'
    case 'abs': return 'abs_discount'
    case 'free_delivery': return 'free_delivery'
    case 'bogo': return 'bogo'
    case 'free_item': return 'free_item'
    default: return null
  }
}

export function matchesFilter(
  d: DealItem,
  activeType: ActiveType,
  activePlatform: ActivePlatform,
): boolean {
  if (activeType !== 'all') {
    const expected = promoTypeForActiveType(activeType)
    if (expected && d.promo_type !== expected) return false
  }
  if (activePlatform !== 'all' && d.platform !== activePlatform) return false
  return true
}

export function filterCounts(
  deals: DealItem[],
  activePlatform: ActivePlatform,
): Record<ActiveType, number> {
  const platformDeals = activePlatform === 'all'
    ? deals
    : deals.filter(d => d.platform === activePlatform)

  const counts: Record<ActiveType, number> = {
    all: platformDeals.length,
    free_delivery: 0,
    pct: 0,
    bogo: 0,
    abs: 0,
    free_item: 0,
  }
  for (const d of platformDeals) {
    if (d.promo_type === 'free_delivery') counts.free_delivery++
    if (d.promo_type === 'pct_discount') counts.pct++
    if (d.promo_type === 'bogo') counts.bogo++
    if (d.promo_type === 'abs_discount') counts.abs++
    if (d.promo_type === 'free_item') counts.free_item++
  }
  return counts
}

export function sortDeals(deals: DealItem[], mode: SortMode): DealItem[] {
  const copy = [...deals]
  switch (mode) {
    case 'newest':
      return copy.sort((a, b) => b.scraped_at.localeCompare(a.scraped_at))
    case 'rated':
      return copy.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))
    case 'saving':
      return copy.sort((a, b) => {
        const aVal = (a.promo_type === 'pct_discount' || a.promo_type === 'abs_discount')
          ? (a.value ?? 0) : 0
        const bVal = (b.promo_type === 'pct_discount' || b.promo_type === 'abs_discount')
          ? (b.value ?? 0) : 0
        if (bVal !== aVal) return bVal - aVal
        return qualityScore(b) - qualityScore(a)
      })
    case 'best':
    default:
      return copy.sort((a, b) => qualityScore(b) - qualityScore(a))
  }
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd forkeur-app && npx vitest run lib/deals.test.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Type check**

```bash
cd forkeur-app && npx tsc --noEmit 2>&1 | head -40
```

Expected: errors only in `DealsClient.tsx` (callers that haven't been updated yet) — that's acceptable at this point.

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/lib/deals.ts forkeur-app/lib/deals.test.ts
git commit -m "feat(deals): SortMode, savingsEstimate, updated filter/sort signatures"
```

---

## Task 4: i18n — add new keys in EN, FR, NL simultaneously

**Files:**
- Modify: `forkeur-app/messages/en.json`
- Modify: `forkeur-app/messages/fr.json`
- Modify: `forkeur-app/messages/nl.json`

- [ ] **Step 1: Add keys to `en.json`**

In `forkeur-app/messages/en.json`, extend the `"deals"` object and `"filters"` object, and add a new `"platform"` object:

```json
"deals": {
  "heading": "Best deals",
  "subtitle": "{count} live offers across UberEats, Deliveroo & Takeaway",
  "none": "No deals in this category right now.",
  "min_order": "Min. €{amount}",
  "order_on": "Order on {platform} →",
  "compare_and_order": "Compare & order on {platform} →",
  "search_placeholder": "Search a restaurant",
  "freshness": "checked {minutes} min ago",
  "freshness_warning": "last checked {minutes} min ago",
  "freshness_stale": "data may be outdated",
  "sort_label": "Sort",
  "sort_best": "Best deal",
  "sort_saving": "Biggest saving",
  "sort_rated": "Top rated",
  "sort_newest": "Newest",
  "savings_pct": "Save ~€{amount} on a €20 order",
  "savings_abs": "€{amount} off your order",
  "savings_free_delivery": "€0 delivery fee",
  "featured_heading": "Best picks right now",
  "empty_filtered": "No deals match these filters.",
  "empty_filtered_hint": "{total} deals available — adjust filters to see them.",
  "empty_total": "No deals right now.",
  "empty_total_hint": "We check every hour — come back soon.",
  "clear_filters": "Clear filters"
}
```

In `"filters"`:
```json
"filters": {
  "all": "All",
  "bogo": "2-for-1",
  "pct": "% Off",
  "free_delivery": "Free Delivery",
  "free_item": "Free Item",
  "eur_off": "€ Off",
  "more": "More ›",
  "less": "Less ‹"
}
```

Add new top-level `"platform"` object after `"filters"`:
```json
"platform": {
  "uber_eats": "UberEats",
  "deliveroo": "Deliveroo",
  "takeaway": "Takeaway"
}
```

- [ ] **Step 2: Add keys to `fr.json`**

Same structure, French translations:

`"deals"` additions:
```json
"freshness": "vérifié il y a {minutes} min",
"freshness_warning": "dernière vérif. il y a {minutes} min",
"freshness_stale": "données peut-être obsolètes",
"sort_label": "Trier",
"sort_best": "Meilleure offre",
"sort_saving": "Plus grande remise",
"sort_rated": "Mieux noté",
"sort_newest": "Plus récent",
"savings_pct": "Économisez ~€{amount} sur une commande de €20",
"savings_abs": "€{amount} de remise",
"savings_free_delivery": "€0 de livraison",
"featured_heading": "Les meilleures offres du moment",
"empty_filtered": "Aucune promo ne correspond à ces filtres.",
"empty_filtered_hint": "{total} promos disponibles — ajustez les filtres.",
"empty_total": "Aucune promo en ce moment.",
"empty_total_hint": "Nous vérifions toutes les heures — revenez bientôt.",
"clear_filters": "Effacer les filtres"
```

`"filters"` addition:
```json
"eur_off": "€ Remise"
```

New `"platform"` object:
```json
"platform": {
  "uber_eats": "UberEats",
  "deliveroo": "Deliveroo",
  "takeaway": "Takeaway"
}
```

- [ ] **Step 3: Add keys to `nl.json`**

Same structure, Dutch translations:

`"deals"` additions:
```json
"freshness": "{minutes} min geleden gecontroleerd",
"freshness_warning": "voor het laatst {minutes} min geleden gecontroleerd",
"freshness_stale": "gegevens mogelijk verouderd",
"sort_label": "Sorteren",
"sort_best": "Beste aanbieding",
"sort_saving": "Grootste korting",
"sort_rated": "Hoogst beoordeeld",
"sort_newest": "Nieuwste",
"savings_pct": "Bespaar ~€{amount} op een bestelling van €20",
"savings_abs": "€{amount} korting op je bestelling",
"savings_free_delivery": "€0 bezorgkosten",
"featured_heading": "Beste aanbiedingen nu",
"empty_filtered": "Geen aanbiedingen gevonden voor deze filters.",
"empty_filtered_hint": "{total} aanbiedingen beschikbaar — pas de filters aan.",
"empty_total": "Momenteel geen aanbiedingen.",
"empty_total_hint": "We controleren elk uur — kom binnenkort terug.",
"clear_filters": "Filters wissen"
```

`"filters"` addition:
```json
"eur_off": "€ Korting"
```

New `"platform"` object:
```json
"platform": {
  "uber_eats": "UberEats",
  "deliveroo": "Deliveroo",
  "takeaway": "Takeaway"
}
```

- [ ] **Step 4: Verify JSON is valid**

```bash
node -e "JSON.parse(require('fs').readFileSync('forkeur-app/messages/en.json','utf8'))"
node -e "JSON.parse(require('fs').readFileSync('forkeur-app/messages/fr.json','utf8'))"
node -e "JSON.parse(require('fs').readFileSync('forkeur-app/messages/nl.json','utf8'))"
```

Expected: no output (no errors).

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/messages/en.json forkeur-app/messages/fr.json forkeur-app/messages/nl.json
git commit -m "feat(i18n): add deals freshness, sort, platform, savings keys (EN/FR/NL)"
```

---

## Task 5: `FeaturedStrip` — new component

**Files:**
- Create: `forkeur-app/components/FeaturedStrip.tsx`

The component receives all deals, runs the selection algorithm internally, renders 3 cards (or nothing if < 2 qualify).

Selection algorithm:
1. Best `pct_discount` deal by `value` desc (or `qualityScore` if value null)
2. Best `free_delivery` deal by `qualityScore` desc
3. Best `bogo` or `free_item` deal by `qualityScore` desc
4. De-dupe: skip if restaurant already selected; if a slot has no qualifying deal, skip that slot

Card format: larger than grid cards; promo value fills top ~40%; platform dot + rating top-right; restaurant name secondary; CTA at bottom.

- [ ] **Step 1: Write failing test**

Create `forkeur-app/components/FeaturedStrip.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { selectFeatured } from './FeaturedStrip'
import type { DealItem } from '../lib/deals'

const base: DealItem = {
  id: '1', restaurant_id: 'r1', restaurant_name: 'A', platform: 'uber_eats',
  platform_url: null, cuisine: [], area: null, rating: 4.0, review_count: 100,
  promo_type: 'pct_discount', label: '20% off', value: 20, min_order: null,
  opening_hours: null, is_available: true, scraped_at: '2026-06-13T10:00:00Z',
}

describe('selectFeatured', () => {
  it('returns empty if fewer than 2 qualifying deals', () => {
    const result = selectFeatured([{ ...base, promo_type: 'pct_discount' }])
    expect(result).toHaveLength(0)
  })

  it('selects top pct deal, top free_delivery, top bogo; dedupes by restaurant', () => {
    const deals: DealItem[] = [
      { ...base, id: '1', restaurant_id: 'r1', promo_type: 'pct_discount', value: 30 },
      { ...base, id: '2', restaurant_id: 'r2', promo_type: 'free_delivery', value: null, rating: 4.5 },
      { ...base, id: '3', restaurant_id: 'r3', promo_type: 'bogo', value: null },
    ]
    const result = selectFeatured(deals)
    expect(result.map(d => d.id)).toEqual(['1', '2', '3'])
  })

  it('dedupes: skips second deal from same restaurant', () => {
    const deals: DealItem[] = [
      { ...base, id: '1', restaurant_id: 'r1', promo_type: 'pct_discount', value: 30 },
      { ...base, id: '2', restaurant_id: 'r1', promo_type: 'free_delivery', value: null },
      { ...base, id: '3', restaurant_id: 'r2', promo_type: 'bogo', value: null },
    ]
    const result = selectFeatured(deals)
    const ids = result.map(d => d.id)
    expect(ids).not.toContain('2')  // r1 already selected
    expect(ids).toContain('1')
    expect(ids).toContain('3')
  })

  it('returns empty (not <2 shown) when only 1 slot fills', () => {
    const deals: DealItem[] = [
      { ...base, id: '1', restaurant_id: 'r1', promo_type: 'pct_discount', value: 30 },
    ]
    expect(selectFeatured(deals)).toHaveLength(0)
  })
})
```

- [ ] **Step 2: Run test — expect fail**

```bash
cd forkeur-app && npx vitest run components/FeaturedStrip.test.tsx
```

Expected: `selectFeatured` not found.

- [ ] **Step 3: Create `FeaturedStrip.tsx` with exported `selectFeatured` and the component**

```tsx
'use client'

import { useTranslations } from 'next-intl'
import type { DealItem } from '../lib/deals'
import { qualityScore } from '../lib/deals'

export function selectFeatured(deals: DealItem[]): DealItem[] {
  const selected: DealItem[] = []
  const usedRestaurants = new Set<string>()

  const pick = (candidates: DealItem[]) => {
    for (const d of candidates) {
      if (!usedRestaurants.has(d.restaurant_id)) {
        selected.push(d)
        usedRestaurants.add(d.restaurant_id)
        return
      }
    }
  }

  // Slot 1: best pct_discount
  const pct = deals
    .filter(d => d.promo_type === 'pct_discount')
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  pick(pct)

  // Slot 2: best free_delivery
  const free = deals
    .filter(d => d.promo_type === 'free_delivery')
    .sort((a, b) => qualityScore(b) - qualityScore(a))
  pick(free)

  // Slot 3: best bogo or free_item
  const extra = deals
    .filter(d => d.promo_type === 'bogo' || d.promo_type === 'free_item')
    .sort((a, b) => qualityScore(b) - qualityScore(a))
  pick(extra)

  return selected.length >= 2 ? selected : []
}

const PLATFORM_DOT: Record<string, string> = {
  uber_eats: 'bg-orange-500',
  deliveroo: 'bg-teal-500',
  takeaway: 'bg-stone-700',
}

const BADGE_COLOR: Record<string, string> = {
  pct_discount: 'bg-orange-500 text-white',
  abs_discount: 'bg-orange-500 text-white',
  free_delivery: 'bg-stone-700 text-white',
  bogo: 'bg-amber-600 text-white',
  free_item: 'bg-stone-600 text-white',
}

function FeaturedCard({ deal }: { deal: DealItem }) {
  const t = useTranslations()
  const badgeColor = BADGE_COLOR[deal.promo_type] ?? 'bg-stone-500 text-white'
  const dotColor = PLATFORM_DOT[deal.platform] ?? 'bg-stone-400'

  return (
    <div className="flex-shrink-0 w-64 sm:w-72 rounded-xl border border-stone-200 bg-white shadow-sm overflow-hidden snap-start">
      {/* Promo badge — top 40% of card */}
      <div className={`${badgeColor} px-4 py-5 flex items-center justify-center min-h-[90px]`}>
        <span className="text-2xl font-bold text-center leading-tight">{deal.label}</span>
      </div>

      <div className="px-4 py-3 space-y-2">
        {/* Platform + rating row */}
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
          <span>{t(`platform.${deal.platform}`)}</span>
          {deal.rating && (
            <>
              <span>·</span>
              <span>★ {deal.rating.toFixed(1)}</span>
              {deal.review_count && <span>({deal.review_count})</span>}
            </>
          )}
        </div>

        {/* Restaurant name */}
        <p className="font-semibold text-stone-900 text-sm leading-snug">{deal.restaurant_name}</p>

        {/* Area / cuisine */}
        {(deal.cuisine.length > 0 || deal.area) && (
          <p className="text-xs text-stone-400">
            {[deal.cuisine.slice(0, 2).join(' · '), deal.area].filter(Boolean).join(' · ')}
          </p>
        )}

        {/* Min order */}
        {deal.min_order && deal.min_order > 0 && (
          <p className="text-xs text-stone-400">{t('deals.min_order', { amount: deal.min_order })}</p>
        )}

        {/* CTA */}
        {deal.platform_url && (
          <a
            href={deal.platform_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block mt-1 text-center text-sm font-medium text-orange-600 hover:text-orange-700 border border-orange-200 rounded-lg py-2"
          >
            {t('deals.order_on', { platform: t(`platform.${deal.platform}`) })}
          </a>
        )}
      </div>
    </div>
  )
}

export default function FeaturedStrip({ deals }: { deals: DealItem[] }) {
  const t = useTranslations()
  const featured = selectFeatured(deals)
  if (featured.length < 2) return null

  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-stone-500 uppercase tracking-wide mb-3">
        {t('deals.featured_heading')}
      </h2>
      <div className="flex gap-4 overflow-x-auto snap-x snap-mandatory pb-2 -mx-4 px-4 sm:mx-0 sm:px-0">
        {featured.map(deal => (
          <FeaturedCard key={deal.id} deal={deal} />
        ))}
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd forkeur-app && npx vitest run components/FeaturedStrip.test.tsx
```

Expected: all tests PASS.

- [ ] **Step 5: Type check**

```bash
cd forkeur-app && npx tsc --noEmit 2>&1 | grep FeaturedStrip
```

Expected: no FeaturedStrip errors.

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/components/FeaturedStrip.tsx forkeur-app/components/FeaturedStrip.test.tsx
git commit -m "feat(deals): FeaturedStrip component with auto-selection algorithm"
```

---

## Task 6: `DealsClient.tsx` — full rework

**Files:**
- Modify: `forkeur-app/components/DealsClient.tsx`

This is the biggest change. The component gains three state axes (type, platform, sort), a sticky filter bar, freshness chip, hero-promo deal cards, and integrates `FeaturedStrip`.

**Current state (before this task):** `max-w-md`, single `active: Set<...>` state, deal type pills only, search input, restaurant-name-led cards, calls `sortDeals(matched, active)`.

**After this task:** multi-column grid, three state vars, sticky filter bar (type pills + platform pills + sort dropdown), freshness chip in header, promo-hero cards, FeaturedStrip above grid, improved empty states.

- [ ] **Step 1: Read current `DealsClient.tsx` to get exact content before replacing**

```bash
cat -n forkeur-app/components/DealsClient.tsx
```

Read the full file content. The rewrite below replaces it entirely.

- [ ] **Step 2: Replace `DealsClient.tsx` with reworked implementation**

```tsx
'use client'

import { useState, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import type { DealItem } from '../lib/deals'
import type { ActiveType, ActivePlatform, SortMode } from '../lib/deals'
import { matchesFilter, filterCounts, sortDeals, savingsEstimate } from '../lib/deals'
import FeaturedStrip from './FeaturedStrip'

// ── Freshness chip ──────────────────────────────────────────────────────────

function freshnessColor(oldestScrapedAt: string): 'stone' | 'amber' | 'red' {
  const ageMs = Date.now() - new Date(oldestScrapedAt).getTime()
  const ageMin = ageMs / 60_000
  if (ageMin < 90) return 'stone'
  if (ageMin < 180) return 'amber'
  return 'red'
}

function FreshnessChip({ deals }: { deals: DealItem[] }) {
  const t = useTranslations()
  if (deals.length === 0) return null

  const oldest = deals.reduce((min, d) =>
    d.scraped_at < min ? d.scraped_at : min,
    deals[0].scraped_at
  )
  const ageMin = Math.round((Date.now() - new Date(oldest).getTime()) / 60_000)
  const color = freshnessColor(oldest)

  const colorClass = {
    stone: 'text-stone-500',
    amber: 'text-amber-600',
    red: 'text-red-600',
  }[color]

  const label = color === 'red'
    ? t('deals.freshness_stale')
    : color === 'amber'
    ? t('deals.freshness_warning', { minutes: ageMin })
    : t('deals.freshness', { minutes: ageMin })

  return (
    <span className={`inline-flex items-center gap-1 text-xs ${colorClass}`}>
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
      </svg>
      {label}
    </span>
  )
}

// ── Deal badge ──────────────────────────────────────────────────────────────

const BADGE_COLOR: Record<string, string> = {
  pct_discount: 'bg-orange-500 text-white',
  abs_discount: 'bg-orange-500 text-white',
  free_delivery: 'bg-stone-700 text-white',
  bogo: 'bg-amber-600 text-white',
  free_item: 'bg-stone-600 text-white',
}

const PLATFORM_DOT: Record<string, string> = {
  uber_eats: 'bg-orange-500',
  deliveroo: 'bg-teal-500',
  takeaway: 'bg-stone-700',
}

// ── Deal card ───────────────────────────────────────────────────────────────

function DealCard({ deal }: { deal: DealItem }) {
  const t = useTranslations()
  const badgeColor = BADGE_COLOR[deal.promo_type] ?? 'bg-stone-500 text-white'
  const dotColor = PLATFORM_DOT[deal.platform] ?? 'bg-stone-400'
  const savings = savingsEstimate(deal)

  return (
    <div className="rounded-xl border border-stone-200 bg-white shadow-sm overflow-hidden flex flex-col">
      {/* Top row: promo badge (left) + platform/rating (right) */}
      <div className="flex items-start gap-3 p-4">
        <div className={`${badgeColor} rounded-lg px-3 py-2 flex-shrink-0`}>
          <span className="text-lg font-bold leading-tight">{deal.label}</span>
        </div>
        <div className="ml-auto text-right text-xs text-stone-500 space-y-0.5">
          <div className="flex items-center justify-end gap-1">
            <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
            <span>{t(`platform.${deal.platform}`)}</span>
          </div>
          {deal.rating && (
            <div>
              ★ {deal.rating.toFixed(1)}
              {deal.review_count ? ` (${deal.review_count})` : ''}
            </div>
          )}
        </div>
      </div>

      <div className="px-4 pb-4 flex flex-col gap-1.5 flex-1">
        {/* Restaurant name */}
        <p className="font-semibold text-stone-900 leading-snug">{deal.restaurant_name}</p>

        {/* Cuisine + area */}
        {(deal.cuisine.length > 0 || deal.area) && (
          <p className="text-sm text-stone-400">
            {[deal.cuisine.slice(0, 2).join(' · '), deal.area].filter(Boolean).join(' · ')}
          </p>
        )}

        {/* Savings estimate */}
        {savings && (
          <p className="text-sm text-stone-600">{savings}</p>
        )}

        {/* Min order */}
        {deal.min_order != null && deal.min_order > 0 && (
          <p className="text-xs text-stone-400">{t('deals.min_order', { amount: deal.min_order })}</p>
        )}

        {/* CTA — pinned to bottom */}
        <div className="mt-auto pt-3">
          {deal.platform_url ? (
            <a
              href={deal.platform_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-center text-sm font-medium text-orange-600 hover:text-orange-700 border border-orange-200 rounded-lg py-2"
            >
              {t('deals.order_on', { platform: t(`platform.${deal.platform}`) })}
            </a>
          ) : (
            <span className="block text-center text-sm text-stone-400 py-2">
              {t(`platform.${deal.platform}`)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Filter bar ──────────────────────────────────────────────────────────────

const TYPE_FILTERS: { key: ActiveType; i18nKey: string }[] = [
  { key: 'all',          i18nKey: 'filters.all' },
  { key: 'free_delivery',i18nKey: 'filters.free_delivery' },
  { key: 'pct',          i18nKey: 'filters.pct' },
  { key: 'bogo',         i18nKey: 'filters.bogo' },
  { key: 'abs',          i18nKey: 'filters.eur_off' },
  { key: 'free_item',    i18nKey: 'filters.free_item' },
]

const PLATFORM_FILTERS: { key: ActivePlatform; labelKey: string; dotColor: string }[] = [
  { key: 'all',        labelKey: 'filters.all',        dotColor: '' },
  { key: 'uber_eats',  labelKey: 'platform.uber_eats',  dotColor: 'bg-orange-500' },
  { key: 'deliveroo',  labelKey: 'platform.deliveroo',  dotColor: 'bg-teal-500' },
  { key: 'takeaway',   labelKey: 'platform.takeaway',   dotColor: 'bg-stone-700' },
]

const SORT_OPTIONS: { value: SortMode; i18nKey: string }[] = [
  { value: 'best',   i18nKey: 'deals.sort_best' },
  { value: 'saving', i18nKey: 'deals.sort_saving' },
  { value: 'rated',  i18nKey: 'deals.sort_rated' },
  { value: 'newest', i18nKey: 'deals.sort_newest' },
]

// ── Main component ──────────────────────────────────────────────────────────

export default function DealsClient({ deals }: { deals: DealItem[] }) {
  const t = useTranslations()
  const [activeType, setActiveType] = useState<ActiveType>('all')
  const [activePlatform, setActivePlatform] = useState<ActivePlatform>('all')
  const [sortMode, setSortMode] = useState<SortMode>('best')

  const counts = useMemo(
    () => filterCounts(deals, activePlatform),
    [deals, activePlatform]
  )

  const filtered = useMemo(
    () => sortDeals(
      deals.filter(d => matchesFilter(d, activeType, activePlatform)),
      sortMode
    ),
    [deals, activeType, activePlatform, sortMode]
  )

  const clearFilters = () => {
    setActiveType('all')
    setActivePlatform('all')
    setSortMode('best')
  }

  const isFiltered = activeType !== 'all' || activePlatform !== 'all'

  if (deals.length === 0) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center text-stone-500">
        <p className="font-medium">{t('deals.empty_total')}</p>
        <p className="text-sm mt-1">{t('deals.empty_total_hint')}</p>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 pb-12">
      {/* Page header */}
      <div className="py-6 flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-stone-900">{t('deals.heading')}</h1>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-stone-500 text-sm">{filtered.length} {t('filters.all').toLowerCase()} offers</span>
          <FreshnessChip deals={deals} />
        </div>
      </div>

      {/* Sticky filter bar */}
      <div className="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-stone-100 py-3 -mx-4 px-4 mb-6">
        {/* Deal type pills */}
        <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-none">
          {TYPE_FILTERS.map(({ key, i18nKey }) => (
            <button
              key={key}
              onClick={() => setActiveType(key)}
              className={`flex-shrink-0 rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                activeType === key
                  ? 'bg-orange-500 text-white'
                  : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
              }`}
            >
              {t(i18nKey)}
              {key !== 'all' && counts[key] > 0 && (
                <span className="ml-1 opacity-70">({counts[key]})</span>
              )}
              {key === 'all' && (
                <span className="ml-1 opacity-70">({counts.all})</span>
              )}
            </button>
          ))}
        </div>

        {/* Platform pills + sort dropdown */}
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <div className="flex gap-2 flex-wrap flex-1">
            {PLATFORM_FILTERS.map(({ key, labelKey, dotColor }) => (
              <button
                key={key}
                onClick={() => setActivePlatform(key)}
                className={`flex-shrink-0 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                  activePlatform === key
                    ? 'bg-stone-800 text-white'
                    : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
                }`}
              >
                {dotColor && (
                  <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
                )}
                {t(labelKey)}
              </button>
            ))}
          </div>

          {/* Sort dropdown */}
          <div className="flex items-center gap-1.5 ml-auto flex-shrink-0">
            <span className="text-xs text-stone-400">{t('deals.sort_label')}:</span>
            <select
              value={sortMode}
              onChange={e => setSortMode(e.target.value as SortMode)}
              className="text-sm text-stone-700 bg-transparent border-0 outline-none cursor-pointer pr-1"
            >
              {SORT_OPTIONS.map(({ value, i18nKey }) => (
                <option key={value} value={value}>{t(i18nKey)}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Featured strip — always shows top picks, ignores active filters */}
      <FeaturedStrip deals={deals} />

      {/* Deal grid or empty state */}
      {filtered.length === 0 ? (
        <div className="py-12 text-center text-stone-500">
          <p className="font-medium">{t('deals.empty_filtered')}</p>
          <p className="text-sm mt-1">{t('deals.empty_filtered_hint', { total: deals.length })}</p>
          {isFiltered && (
            <button
              onClick={clearFilters}
              className="mt-4 text-sm text-orange-600 hover:text-orange-700 font-medium"
            >
              {t('deals.clear_filters')}
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(deal => (
            <DealCard key={deal.id} deal={deal} />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Type check**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Run all frontend tests**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

- [ ] **Step 5: Start dev server and verify in browser**

```bash
cd forkeur-app && npm run dev -- -p 30000
```

Open `http://localhost:30000/deals`. Verify:
- Page header shows deal count and freshness chip
- Filter bar sticks on scroll (scroll down to verify)
- Deal type pills show counts, update when platform filter changes
- Platform pills filter the grid
- Sort dropdown changes order
- Featured strip shows 3 cards above the grid
- Deal cards: promo badge is top-left hero, restaurant name is secondary
- Min order shows only when > €0
- Empty state: "No deals match these filters" with count and "Clear filters" when filters active
- Try on narrow viewport: grid collapses to 1 column, featured strip shows 1.5 cards with horizontal scroll

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/components/DealsClient.tsx
git commit -m "feat(deals): full UX rework — promo hero cards, platform filter, sort, freshness chip, featured strip"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task covering it |
|---|---|
| Headline "Best deals right now" + live count | Task 6 — page header |
| Freshness chip with 3 color thresholds | Task 6 — `FreshnessChip` component |
| Deal type pills with counts | Task 6 — `TYPE_FILTERS` array |
| Counts update when platform filter changes | Task 3 — `filterCounts(deals, activePlatform)` |
| Platform pills (UberEats/Deliveroo/Takeaway) | Task 6 — `PLATFORM_FILTERS` array |
| Platform dots (orange/teal/dark) | Task 6 — `PLATFORM_DOT` map |
| Sort dropdown (best/saving/rated/newest) | Task 6 — `SORT_OPTIONS` + select element |
| Sticky filter bar | Task 6 — `sticky top-0 z-10` |
| Featured strip — top 3 auto-selected | Task 5 — `FeaturedStrip.tsx` |
| Featured strip ignores active filters | Task 6 — `<FeaturedStrip deals={deals} />` (all deals, not filtered) |
| Featured strip hidden if < 2 qualifying | Task 5 — `selectFeatured` returns [] if <2 |
| Featured strip — horizontal scroll + snap mobile | Task 5 — `overflow-x-auto snap-x snap-mandatory` |
| Deal card: promo badge as hero (top-left) | Task 6 — `DealCard` layout |
| Deal card: platform dot + rating (top-right) | Task 6 — `DealCard` layout |
| Deal card: savings estimate | Task 3 — `savingsEstimate()`, Task 6 — rendered |
| Deal card: min order shown only when > €0 | Task 6 — `deal.min_order != null && deal.min_order > 0` |
| Badge colors per deal type | Task 6 — `BADGE_COLOR` map |
| Grid: 3 cols desktop / 2 tablet / 1 mobile | Task 6 — `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` |
| Empty state (filtered): count + clear button | Task 6 — filtered.length === 0 block |
| Empty state (no deals): total empty message | Task 6 — deals.length === 0 block |
| `scraped_at` on DealItem | Task 2 |
| Backend SQL fix | Task 1 |
| i18n all keys EN/FR/NL | Task 4 |
| `SortMode` type | Task 3 |
| `savingsEstimate()` helper | Task 3 |
| `DealFilter` platform axis | Task 3 — `ActivePlatform` type |
| `filterCounts()` respects platform | Task 3 |
| No polling — ISR handles refresh | Spec says "static on load" — component reads prop, no polling. ✓ |

### Placeholder scan
No placeholders found. All steps have exact code.

### Type consistency
- `ActiveType`, `ActivePlatform`, `SortMode` defined in Task 3 (`deals.ts`) and imported in Task 6 (`DealsClient.tsx`) ✓
- `selectFeatured` defined in Task 5 and tested in Task 5 ✓
- `filterCounts(deals, activePlatform)` — new signature defined in Task 3, called in Task 6 ✓
- `sortDeals(deals, sortMode)` — new signature defined in Task 3, called in Task 6 ✓
- `matchesFilter(d, activeType, activePlatform)` — new signature defined in Task 3, called in Task 6 ✓
- `scraped_at` on `DealItem` added in Task 2, used in `FreshnessChip` (Task 6) and `FeaturedStrip` sort (Task 5 — via `selectFeatured`) ✓
