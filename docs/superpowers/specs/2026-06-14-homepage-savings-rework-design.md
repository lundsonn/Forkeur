# Homepage savings rework — design spec
_2026-06-14_

## Goal

Transform the homepage from "restaurant list with prices attached" into a savings-led comparison product. Structure: **claim → proof → browse**.

---

## Approach

Option B: extract `HeroBlock` and `FeedHeader` components; all savings math lives in one shared selector (`lib/savings.ts`); everything else edited in-place.

---

## Section 1 — Shared savings selector (`lib/savings.ts`)

New file. All savings calculations live here. No component computes savings inline.

### Exports

```ts
// Effective total for homepage (no basket): fee + min_order in cents
// Returns null if delivery_fee_cents is null (platform not listed)
effectiveTotal(listing: { delivery_fee_cents: number | null; min_order_cents: number | null }): number | null

// Savings vs the NEXT cheapest platform (not most expensive).
// Sorts listings by effectiveTotal asc, returns delta between index 1 and index 0.
// Returns null if fewer than 2 listings have a non-null effectiveTotal.
savingsVsNext(
  listings: RestaurantSummary['listings'],
  winnerPlatform: Platform
): { cents: number; vs: Platform } | null

// For the RIGHT NOW block: find the restaurant with highest savings_cents
// across the full list. Gated: savings_cents > 0 AND listings.length >= 2.
// Returns null if no qualifying restaurant exists.
findBestSavingExample(restaurants: RestaurantSummary[]): {
  restaurant: RestaurantSummary
  saving_cents: number
  winner: Platform
  loser: Platform
  winner_total_cents: number
  loser_total_cents: number
} | null
```

### Notes

- `cheapest.savings_cents` from the DB = `(mostExpensive effective total) − (winner effective total)`. Used for ranking and badges. Computed min-order-aware at query level — use as-is.
- `savingsVsNext()` derives the "Save €X vs [Platform]" label from the listings array at render time. No API change needed.
- `effectiveTotal()` = `delivery_fee_cents + (min_order_cents ?? 0)`. If `delivery_fee_cents` is null, returns null.
- `findBestSavingExample()` uses `cheapest.savings_cents` (already on each restaurant) to find the winner, then calls `savingsVsNext()` to identify which platform is the loser for display.

---

## Section 2 — Landing: `HeroBlock` component

New file `forkeur-app/components/HeroBlock.tsx`. Client component. Receives `restaurants: RestaurantSummary[]`.

### Layout (top to bottom)

```
┌─────────────────────────────────────────────────────┐
│  [credibility line]                                 │
│  881 restaurants · all 3 apps compared · fees in   │
│  · checked 4× a day                                │
├─────────────────────────────────────────────────────┤
│  [RIGHT NOW block — omitted entirely if no data]    │
│  Right now in Brussels                              │
│  ~~€8.49 on Deliveroo~~  →  €3.99 on Uber Eats    │
│  Sushi Palace · Ixelles       Save €4.50           │
├─────────────────────────────────────────────────────┤
│  [neutrality line]                                  │
│  We don't sell placement. Cheapest is always        │
│  cheapest.                                          │
└─────────────────────────────────────────────────────┘
```

### Credibility line

- `{restaurants.length}` is live (from prop).
- `· all 3 apps compared · fees in · checked 4× a day` are static strings.
- i18n key `hero.credibility` with `{count}` interpolation.

### RIGHT NOW block

- Calls `findBestSavingExample(restaurants)` from `lib/savings.ts`.
- If result is `null`: block is **omitted entirely**. No fallback text, no placeholder. Honesty rule 2: fake/stale proof is worse than none.
- Strikethrough: loser platform effective total crossed out (`line-through text-stone-400`), winner total shown plain in `font-semibold`.
- Platform names via `PLATFORM_LABELS` from `lib/basket.ts`.
- Restaurant name + neighborhood shown beneath.
- `revalidate = 3600` on `page.tsx` means data is at most 1h stale — acceptable as "live."

### Neutrality line

Static string. i18n key `hero.neutrality`.

### What gets removed from HomepageClient

- `hero.live_badge` pill.
- "How it works" 1-2-3 section (lines 270–288).
- Excessive hero padding / tagline copy — hero shrinks to app name + `<HeroBlock />`.

**Hero trim goal:** first savings card reachable without scroll on a 375 px viewport.

---

## Section 3 — Feed structure

### Sort behavior

- Default `sortBy` state: `'best'` → `'cheapest'`.
- Sort options: `Cheapest` (default) · `Fastest`. Remove `Best match` pill entirely.
- `'cheapest'` sort: currently `minFee` ascending → change to `savings_cents` descending (biggest saving first). Use `restaurant.cheapest?.savings_cents ?? 0`.
- `'fastest'` sort: unchanged (`eta_min` ascending).

### NearYou section

- Find closest 20 restaurants by haversine distance from `userLocation`.
- Sort those 20 by `cheapest.savings_cents` descending.
- Take top 3.
- Section heading: `t('results.biggestSavings')` = "Biggest savings near you".
- If `userLocation === null`: section hidden (no change from current behaviour).

### FeedHeader component

New file `forkeur-app/components/FeedHeader.tsx`. Client component.

Props:
```ts
{
  selectedNeighborhood: string | null
  onChangeNeighborhood: () => void
  sortBy: SortBy
  onSortChange: (s: SortBy) => void
  restaurantCount: number
}
```

Layout:
```
Savings near Ixelles · Change          [Cheapest] [Fastest]
```

- When `selectedNeighborhood` is null: shows "All of Brussels · Change".
- Tapping "Change" opens existing neighborhood bottom sheet (callback).
- Sort pills right-aligned desktop, second row mobile.

### Search input

- Stays in HomepageClient; repositioned **below FeedHeader** in DOM order.
- Label / placeholder changes to `t('search.hint')` = "Know the place? Search it."

### Coverage footer

Plain text line after the last card in the feed:

> Still mapping Brussels — {n} spots live, more weekly.

`{n}` = `restaurants.length`. i18n key `feed.coverageFooter`. Rendered in HomepageClient after the card list map.

---

## Section 4 — Card design

### Collapsed state

Replace `from €X` with two lines:

```
Cheapest on Uber Eats · €2.99
Save €4.50 vs Deliveroo              [green]
```

- Line 1: `t('card.cheapestOn', { platform, fee })` where `fee = centsToEuro(cheapest.delivery_fee_cents)`.
- Line 2: calls `savingsVsNext(listings, cheapest.platform)` → `t('card.saveVs', { amount, platform })`. Shown in `text-green-600`.
- If `savingsVsNext` returns null (only 1 listing): line 1 only, no green line.
- If `cheapest === null`: show nothing (unchanged).

### CHEAPEST badge

`bg-orange-500` → `bg-green-500 text-white`.

Orange stays as Takeaway platform colour (`PLATFORM_COLORS.takeaway`). No other colour changes.

### Expanded tiles — trust bug fix

**Current bug:** loser rows display bare `delivery_fee_cents` as headline, which can appear lower than the winner's fee even though effective total is higher.

**Winner tile:**
```
[CHEAPEST badge]   Uber Eats
€2.99 delivery · €10 min order
```

**Loser tile:**
```
+€4.50 more   Deliveroo                 [red headline]
€5.99 delivery · €15 min order          [cause, beneath]
```

- `+€X.XX more` = `effectiveTotal(loserListing) − effectiveTotal(winnerListing)` via `lib/savings.ts`.
- Raw fee + min-order breakdown shown beneath as the cause, never as headline.
- Gate: delta shown only when `cheapest !== null && effectiveTotal(loser) !== null && effectiveTotal(winner) !== null`.
- Colours: `+€X.XX more` in `text-red-600`; fee breakdown line in `text-stone-500`.

---

## i18n keys (all 3 locales: en / fr / nl)

| Key | EN value |
|-----|----------|
| `card.cheapestOn` | `Cheapest on {platform} · {fee}` |
| `card.saveVs` | `Save {amount} vs {platform}` |
| `card.overpay` | `+{amount} more` |
| `hero.credibility` | `{count} restaurants · all 3 apps compared · fees in · checked 4× a day` |
| `hero.rightNow` | `Right now in Brussels` |
| `hero.neutrality` | `We don't sell placement. Cheapest is always cheapest.` |
| `results.biggestSavings` | `Biggest savings near you` |
| `search.hint` | `Know the place? Search it.` |
| `feed.savingsNear` | `Savings near {commune} · Change` |
| `feed.savingsNearAll` | `All of Brussels · Change` |
| `feed.coverageFooter` | `Still mapping Brussels — {count} spots live, more weekly.` |

Existing `howItWorks.*` keys left in place (unused but harmless).

---

## Honesty rules (hard gates — non-negotiable)

1. `card.saveVs` renders only when `savingsVsNext()` returns a non-null result (≥2 listings with valid effective totals).
2. RIGHT NOW block renders only when `findBestSavingExample()` returns non-null. Omitted entirely otherwise.
3. Expanded tile `+€X.XX more` renders only when both effectiveTotals are non-null.
4. Never invent or hardcode a saving figure.

---

## Files changed / created

| File | Action |
|------|--------|
| `forkeur-app/lib/savings.ts` | **Create** |
| `forkeur-app/components/HeroBlock.tsx` | **Create** |
| `forkeur-app/components/FeedHeader.tsx` | **Create** |
| `forkeur-app/components/HomepageClient.tsx` | **Edit** (default sort, nearYou sort, remove 1-2-3 + live badge, add HeroBlock + FeedHeader + coverage footer) |
| `forkeur-app/components/RestaurantCard.tsx` | **Edit** (collapsed lines, badge colour, expanded tile trust fix) |
| `forkeur-app/messages/en.json` | **Edit** (add new keys) |
| `forkeur-app/messages/fr.json` | **Edit** (add new keys, translated) |
| `forkeur-app/messages/nl.json` | **Edit** (add new keys, translated) |

`forkeur-app/app/page.tsx` — no changes needed.  
`forkeur-app/lib/queries.ts` — no changes needed.
