# Forkeur Frontend — Polish + Features

Date: 2026-05-31  
Scope: `forkeur-app/` only  

## Goals

1. Fix theme bug (`bg-blue-600` in StickyOrderBar)
2. Redesign homepage RestaurantCard to 3-col platform fee grid
3. Add homepage loading skeleton
4. Minor cleanup (dark-mode CSS, unused styles)

## Components changed

### `RestaurantCard.tsx`

Replace the dot+fee inline row with a 3-column CSS grid. One tile per platform (`uber_eats`, `deliveroo`, `takeaway`). Best (cheapest) tile: full opacity, fee text `font-bold text-stone-900`. Others: `opacity-50`. Fee shown large (`text-sm font-bold`). Platform abbreviated label above fee (`text-[10px] font-semibold uppercase`), colored per `PLATFORM_COLORS`.

Layout within card:
```
<name>                <cuisine>           ›
┌──────────┬──────────┬──────────┐
│ UE       │ DE       │ TW       │
│ Free     │ €0.99    │ €1.20    │
└──────────┴──────────┴──────────┘
```

Tiles only rendered for platforms with `delivery_fee_cents !== null`. If only 1 platform available, single tile full-width.

### `StickyOrderBar.tsx`

- Background: `bg-stone-900` (was `bg-blue-600`)
- Left border: `border-l-4` colored per platform using `PLATFORM_COLORS[platform].ring`
- Price text: colored per platform using `PLATFORM_COLORS[platform].label` (was white)
- Label text: stays white
- Safe-area padding unchanged

### `app/loading.tsx` (new file)

Root-level Next.js loading boundary for homepage route. Skeleton shape:

- Nav bar: logo placeholder + location pill placeholder
- Hero heading: 2 lines `animate-pulse bg-stone-100`
- Search bar placeholder
- 3 cuisine chip placeholders
- 6 card skeletons — each: name line + cuisine line + 3-col fee grid (3 tiles)

All skeleton elements: `bg-stone-100 rounded animate-pulse`.

### `app/globals.css`

Remove `@media (prefers-color-scheme: dark)` block — dark mode not in scope, conflicts with stone/white theme.

## Data flow

No data layer changes. `RestaurantCard` already receives `listings: { platform, delivery_fee_cents }[]` and `cheapest`. Tile logic derives from these.

## Testing

- Update `RestaurantCard` Vitest snapshot/unit tests to match new tile markup
- Verify `StickyOrderBar` renders `border-l-4` + platform color class in test

## Out of scope

- Restaurant images
- Cross-platform menu item matching (seed-supabase.js)
- Deliveroo/Takeaway scraper bug fixes
