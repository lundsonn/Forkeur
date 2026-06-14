# Deals Page UX Rework

**Date:** 2026-06-13  
**Scope:** `/deals` page — full visual and interaction redesign  
**Files touched:** `forkeur-app/components/DealsClient.tsx`, new `FeaturedStrip` component, `forkeur-app/lib/deals.ts`  
**Assumption:** `scraped_at` is already returned by `/api/public/deals`. If not, backend needs one small addition to the `RawPromoRow` SELECT in `public.py`.  
**Backend changes:** none

---

## Context & Problem

The `/deals` page currently treats deals as a listing feature — a restaurant card with a promo badge tacked on. The discount value is secondary to the restaurant name. Primary user is a deal hunter (browsing to find the best deal right now, flexible on restaurant), so the deal itself must be the visual hero.

Three core problems:
1. **Wrong hierarchy** — restaurant name leads, promo badge is small and secondary
2. **No platform filter** — users with UberEats/Deliveroo accounts can't narrow by platform
3. **No trust signal** — 1h ISR cache with no freshness indicator; users can't tell if a deal is live

---

## Page Structure

```
/deals
├── Page header
│   ├── Headline: "Best deals right now"
│   ├── Live count: "47 offers"
│   └── Freshness chip: "checked 12 min ago"
│
├── Filter bar (sticky on scroll)
│   ├── Deal type pills: All | Free Delivery | % Off | BOGO | Free Item | € Off
│   ├── Platform pills: All | UberEats | Deliveroo | Takeaway
│   └── Sort dropdown (right-aligned): Best deal | Biggest saving | Top rated | Newest
│
├── Featured strip (top 3 auto-selected by score)
│   └── Horizontal cards, larger format, ignores active filters
│
└── Deal grid
    └── Redesigned cards (3 cols desktop / 2 tablet / 1 mobile)
```

---

## Section 1: Page Header

- **Headline:** `"Best deals right now"` (i18n key: `deals.heading`, already exists)
- **Live count:** `"{count} offers"` — count updates as filters change
- **Freshness chip:** `"checked {N} min ago"` — computed from oldest `scraped_at` in result set
  - Normal (< 90 min): stone-500 text, clock icon
  - Warning (90 min – 3h): amber-600
  - Stale (> 3h): red-600
  - Static on load — no client polling; ISR handles page refresh

---

## Section 2: Filter Bar

### Deal type pills
Reordered by expected frequency:
```
[All (47)] [Free Delivery (18)] [% Off (14)] [BOGO (8)] [€ Off (5)] [Free Item (2)]
```
- Counts in parens, update live as platform filter changes
- Existing `filterCounts()` in `deals.ts` — extend to respect platform filter

### Platform pills (new)
```
[All] [● UberEats] [● Deliveroo] [● Takeaway]
```
- Small colored dot prefix (orange / teal / dark) — no logos
- New `platform` field added to `DealFilter` type in `deals.ts`
- `matchesFilter()` extended to check `item.platform === filter.platform`

### Sort dropdown (new)
Right-aligned on same row as platform pills:
```
Sort: Best deal ▾
      └ Best deal      (default — existing qualityScore logic)
        Biggest saving (value desc for pct/abs; qualityScore for others)
        Top rated      (rating desc)
        Newest         (scraped_at desc)
```
- New `SortMode` union type in `deals.ts`: `'best' | 'saving' | 'rated' | 'newest'`
- `sortDeals()` extended with `mode` param

### Sticky behavior
Filter bar sticks below page header on scroll. Header scrolls away, filter bar persists. Implemented via `sticky top-0 z-10` with appropriate background.

### Filter combinations
All three axes (deal type × platform × sort) are combinable simultaneously.

---

## Section 3: Featured Strip

Auto-selects top 3 deals by algorithm — no editorial curation.

### Selection algorithm
1. Best `pct_discount` by `value` desc
2. Best `free_delivery` by `qualityScore` desc
3. Best `bogo` or `free_item` by `qualityScore` desc
4. De-dupe: skip if restaurant already selected

### Visual treatment
- Slightly larger cards than grid cards
- Promo value fills top ~40% of card in large type
- Stone/orange theme consistent with brand
- Mobile: horizontal scroll with snap, shows 1.5 cards to hint scrollability
- Strip hidden if fewer than 2 qualifying deals exist
- Strip always shows best overall picks regardless of active filters

### New component
`forkeur-app/components/FeaturedStrip.tsx` — receives `deals: DealItem[]`, runs selection logic internally, renders 3 cards.

---

## Section 4: Deal Card Redesign

### Layout
```
┌──────────────────────────────────────────┐
│ ┌─────────────┐                          │
│ │  35% OFF    │  ● UberEats              │
│ │  on order   │  ★ 4.2  (890 reviews)   │
│ └─────────────┘                          │
│                                          │
│  Sushi Shop                              │
│  Japanese · Ixelles                      │
│                                          │
│  Save ~€7 on a €20 order                 │
│  Min. €20                                │
│                                          │
│  [Order on UberEats →]                   │
└──────────────────────────────────────────┘
```

### Hierarchy (top to bottom visual weight)
1. Promo badge — large, top-left, hero element
2. Platform dot + rating — top-right, scannable
3. Restaurant name + cuisine + area — secondary
4. Savings estimate — concrete value translation
5. Min order — shown only when > €0
6. CTA — single action per card

### Savings estimate
New helper `savingsEstimate(deal: DealItem): string | null` in `deals.ts`:
- `pct_discount`: `"Save ~€{value * 20 / 100} on a €20 order"` (assumes €20 avg)
- `abs_discount`: `"€{value} off your order"`
- `free_delivery`: `"€0 delivery fee"`
- `bogo` / `free_item`: `null` (no estimate shown)

### Deal type color accents (within stone/orange brand)
| Type | Badge style |
|---|---|
| `pct_discount` | orange-500 bg, white text |
| `abs_discount` | orange-500 bg, white text |
| `free_delivery` | stone-700 bg, white text |
| `bogo` | amber-600 bg, white text |
| `free_item` | stone-600 bg, white text |

### Grid
- Desktop: 3 columns
- Tablet: 2 columns
- Mobile: 1 column

---

## Section 5: Empty State & Freshness

### Empty state (filters return 0 results)
```
No deals match these filters.
47 deals available — adjust filters to see them.
[Clear filters]
```
- Count references total unfiltered deal count
- "Clear filters" resets deal type, platform, and sort to defaults

### Zero deals total (backend returns empty)
```
No deals right now.
We check every hour — come back soon.
```

---

## Data & Types

### `DealFilter` changes (`deals.ts`)
```ts
type DealFilter = {
  type: DealType | 'all'
  platform: 'uber_eats' | 'deliveroo' | 'takeaway' | 'all'  // NEW
}
```

### `SortMode` (new, `deals.ts`)
```ts
type SortMode = 'best' | 'saving' | 'rated' | 'newest'
```

### `savingsEstimate()` (new, `deals.ts`)
```ts
function savingsEstimate(deal: DealItem): string | null
```

### `sortDeals()` signature change (`deals.ts`)
```ts
function sortDeals(deals: DealItem[], mode: SortMode): DealItem[]
```

### `DealItem` additions
`scraped_at: string` — needed for freshness chip and "Newest" sort. Must be included in `/api/public/deals` response and `getDeals()` transform.

---

## i18n Keys to Add

```json
"deals.freshness": "checked {minutes} min ago",
"deals.freshness_warning": "last checked {minutes} min ago",
"deals.freshness_stale": "data may be outdated",
"deals.sort_label": "Sort",
"deals.sort_best": "Best deal",
"deals.sort_saving": "Biggest saving",
"deals.sort_rated": "Top rated",
"deals.sort_newest": "Newest",
"deals.savings_pct": "Save ~€{amount} on a €20 order",
"deals.savings_abs": "€{amount} off your order",
"deals.savings_free_delivery": "€0 delivery fee",
"deals.featured_heading": "Best picks right now",
"deals.empty_filtered": "No deals match these filters.",
"deals.empty_filtered_hint": "{total} deals available — adjust filters to see them.",
"deals.empty_total": "No deals right now.",
"deals.empty_total_hint": "We check every hour — come back soon.",
"deals.clear_filters": "Clear filters",
"filters.eur_off": "€ Off",
"platform.uber_eats": "UberEats",
"platform.deliveroo": "Deliveroo",
"platform.takeaway": "Takeaway"
```

---

## Out of Scope

- Restaurant detail page promo display (unchanged)
- Backend API changes (no new endpoints, `scraped_at` already in DB)
- Animations / skeleton loaders
- Deal expiry / countdown timers (no expiry data in DB)
- Map view
