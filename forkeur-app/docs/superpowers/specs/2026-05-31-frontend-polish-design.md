# Forkeur Frontend Polish — Design Spec

**Date:** 2026-05-31  
**Status:** Approved  
**Scope:** forkeur-app (Next.js 15)

## Overview

Polish the consumer-facing app across 6 areas: all-platform fees on restaurant cards, dynamic cuisine chips, rating in detail header, sticky order CTA, swipe-to-remove basket items, skeleton loading, and safe area insets.

Existing search/filter and BasketSimulator logic are already working — this spec does not touch their business logic.

Design theme: white background, stone palette, orange accent (`#f97316`), platform dots (green/cyan/orange). Never deviate.

---

## 1. RestaurantCard — All 3 Platform Fees

**File:** `components/RestaurantCard.tsx`

**Current:** Shows cheapest platform dot + "from €X.XX" delivery fee.

**New:** Show all available platform delivery fees inline. Cheapest is bold + dark (`text-stone-900 font-semibold`), others are muted (`text-stone-400`). Platforms with no listing for this restaurant are hidden entirely.

**Layout:**
```
McDonald's
Burgers · Fast Food
● €0.49  ○ €1.49  ○ €1.99
         ↑ bold       ↑ muted
```

**Edge cases:**
- 1 platform only: show as current (dot + "from €X")
- No platforms: show nothing in the right column
- Platform fee is null: skip that platform

**Data:** `RestaurantSummary` already receives `platform_listings` from `getRestaurants()`. The type needs to include all listings, not just the cheapest. Update `RestaurantSummary` in `lib/queries.ts` to include `listings: { platform: Platform, delivery_fee_cents: number | null }[]`.

---

## 2. Dynamic Cuisine Chips

**Files:** `lib/queries.ts`, `components/HomepageClient.tsx`

**Current:** `CUISINES` is a hardcoded array `['Burgers', 'Pizza', 'Asian', 'Healthy', 'Sandwiches']`.

**New:** `getRestaurants()` returns `{ restaurants, cuisines }` where `cuisines` is a deduplicated, sorted array of cuisine strings from the actual DB data. `HomepageClient` receives `cuisines` as a prop and renders them as chips.

**Implementation note:** `cuisine` column on `restaurants` table may be a string or array. The query already does `r.cuisine ? [r.cuisine] : []` — collect all values, flatten, deduplicate, sort alphabetically, return top 8 max to avoid overflow.

---

## 3. Rating in Detail Header

**File:** `app/restaurant/[id]/page.tsx`

**Current:** `{data.cuisine.join(' · ')} · {data.city}`

**New:** `{data.cuisine.join(' · ')} · {data.city}` + if best rating available: ` · ★ {rating}`

**Data:** `RestaurantDetail.listings` already includes `rating: number | null`. Use the highest rating across all listings (or the first non-null). Format: `★ 4.5` (one decimal place). If no ratings in DB: subtitle unchanged.

**No new DB query needed.**

---

## 4. Sticky Order CTA Bar

**New file:** `components/StickyOrderBar.tsx`

**Behaviour:**
- Hidden when basket is empty or no cheapest platform determined
- Appears (no animation needed — just conditional render) when basket has ≥1 item
- Fixed to bottom of viewport, full width, max-w-md centered to match layout
- Safe-area-aware: `padding-bottom: env(safe-area-inset-bottom, 0px)` via inline style or Tailwind `pb-safe`
- Content: `[Platform dot]  Order on {Platform} →  {total}`

**Props:**
```ts
type Props = {
  platform: Platform | null
  total: number | null        // cents
  platformUrl: string | null
}
```

**Integration:** `BasketSimulator.tsx` already computes `cheapestPlatform`, `cheapestTotal`, `platformUrls`. Pass these to `StickyOrderBar` rendered at the bottom of `BasketSimulator`.

**Remove:** The existing inline CTA block at the bottom of `BasketSimulator` (the `<a>` / `<div>` "Order on X →" block inside the recommendation section). `StickyOrderBar` replaces it entirely.

**Content padding:** `BasketSimulator`'s wrapper div gets `pb-24` when bar is visible so content isn't hidden behind it.

---

## 5. Swipe-to-Remove Basket Items

**File:** `components/BasketSimulator.tsx`

**Target element:** The basket summary chip at the top of `BasketSimulator` (the line showing selected items when `basket.length > 0`).

**Behaviour:** Touch/pointer swipe left → clear entire basket. Desktop: existing "Clear" button remains. No per-item swipe (basket chip is a summary line, not a list).

**Implementation:** Use `onPointerDown` / `onPointerMove` / `onPointerUp`. If horizontal delta > 80px leftward: call `setBasket([])` with a brief translate-x CSS transition (`translate-x-[-100%] opacity-0`). No external library.

**Fallback:** "Clear" button stays visible on all screen sizes as backup.

---

## 6. Skeleton Loading

**File:** `app/restaurant/[id]/loading.tsx`

**Current:** Minimal placeholder.

**New:** Matches actual detail page structure with pulsing gray bars (`animate-pulse bg-stone-100`):
- Nav bar (back + logo)
- Restaurant name block (wide bar)
- Subtitle (narrow bar)
- "BEST RIGHT NOW" label
- Platform name (large bar)
- 3 metric boxes
- "Compare all three" row
- 3 compare rows

Same `max-w-md mx-auto` layout. Stone palette only.

---

## 7. Safe Area Insets

**File:** `app/layout.tsx`

Add `viewport` metadata with `viewport-fit=cover`:
```ts
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
}
```

`StickyOrderBar` uses `style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}` for iOS notch safety.

---

## Component Map

| Component | Change |
|---|---|
| `RestaurantCard` | All 3 fees inline |
| `HomepageClient` | Accept `cuisines` prop, drop hardcoded array |
| `lib/queries.ts` | `getRestaurants` returns `{ restaurants, cuisines }`, `RestaurantSummary` includes all listings |
| `app/page.tsx` | Destructure new return shape |
| `app/restaurant/[id]/page.tsx` | Add rating to subtitle |
| `BasketSimulator` | Remove inline CTA, add swipe-to-clear, add `StickyOrderBar` |
| `components/StickyOrderBar.tsx` | New — sticky bottom CTA |
| `app/restaurant/[id]/loading.tsx` | Full skeleton upgrade |
| `app/layout.tsx` | viewport-fit=cover |

---

## Out of Scope

- Per-item swipe removal (basket is a summary chip, not a list)
- Image support in menu items (no images in DB yet)
- "Order again" / recently viewed section
- Auth / user accounts
