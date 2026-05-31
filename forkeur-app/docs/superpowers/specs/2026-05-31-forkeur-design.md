# Forkeur — Design Spec
_2026-05-31_

## What We're Building

Forkeur is a food delivery price comparison app for Brussels. Users browse restaurants, add items to a simulated basket, and see the real-time total per platform (Uber Eats, Deliveroo, Takeaway) including delivery fees. The app recommends the cheapest platform and deep-links directly to order.

---

## Architecture

**Stack:** Next.js 15 App Router · TypeScript · Tailwind CSS · Supabase (Postgres)

**Pattern:** Server Components fetch all data from Supabase. Client Components handle interactivity (search, filters, basket). No API routes. No auth. Public read RLS already enabled on all tables.

**Data flow:**
```
Scrapers (local Puppeteer + ProtonVPN)
  → seed script (manual trigger)
  → Supabase DB
  → Next.js Server Components
  → HTML + hydrated client basket
  → "Order" deep link → platform URL
```

---

## Pages & Routing

### `/` — Homepage

- **Server Component** reads `restaurants` + `cheapest_per_restaurant` view from Supabase
- Shows: search bar, cuisine filter chips, sorted restaurant list
- Each restaurant card: name, cuisine, cheapest platform badge, savings amount vs most expensive
- Sort default: highest savings first
- Client-side: search filters list in memory (no re-fetch), cuisine filter chips toggle

### `/restaurant/[id]` — Detail + Basket Simulator

- **Server Component** fetches restaurant + all platform listings + all menu items
- Left panel: menu items grouped by category, each row shows price per platform (cheapest highlighted green), `+` button adds to basket
- Right panel: live basket — item list with qty, total per platform (items + delivery), cheapest highlighted, "Order on [Platform]" CTA with deep link
- All basket logic is client-side (`useState`)

---

## File Structure

```
forkeur-app/
├── app/
│   ├── page.tsx                        ← homepage
│   ├── restaurant/[id]/page.tsx        ← detail + simulator
│   └── layout.tsx
├── components/
│   ├── RestaurantList.tsx              ← Server Component
│   ├── SearchBar.tsx                   ← Client Component
│   ├── CuisineFilters.tsx              ← Client Component
│   ├── RestaurantCard.tsx              ← Server Component
│   ├── BasketSimulator.tsx             ← Client Component (all basket logic)
│   └── PlatformPriceRow.tsx            ← item row, per-platform prices
├── lib/
│   └── queries.ts                      ← typed Supabase query functions
├── utils/supabase/
│   ├── server.ts
│   ├── client.ts
│   └── middleware.ts
└── scripts/
    └── seed.js                         ← reads scraper output → seeds Supabase
```

---

## Data Layer (`lib/queries.ts`)

```ts
// Homepage
getRestaurants(filters?: { cuisine?: string }): Promise<{
  id: string
  name: string
  cuisine: string[]
  cheapest: { platform: string; fee_label: string; savings_cents: number }
}[]>

// Detail page
getRestaurantWithListings(id: string): Promise<{
  restaurant: Restaurant
  listings: PlatformListing[]          // one per platform
  menuItems: {
    name: string
    description: string | null
    category: string | null
    image_url: string | null
    prices: {
      uber_eats: number | null          // cents
      deliveroo: number | null
      takeaway: number | null
    }
  }[]
}>
```

Menu items are pivoted in the query: one row per item name with prices from all 3 platforms joined by `listing_id`. If an item only exists on 2 platforms, the missing price is `null`.

---

## Basket Simulator

Pure client state — no backend calls, no auth required.

```ts
type BasketItem = {
  name: string
  qty: number
  prices: { uber_eats: number | null; deliveroo: number | null; takeaway: number | null }
}

// Live total per platform:
// platformTotal = sum(item.prices[platform] * qty) + delivery_fee_cents[platform]
// Cheapest = min(platformTotal) across available platforms
```

**Edge cases:**
- Item price `null` for a platform → show "—", exclude from that platform's total
- Platform not available for restaurant → hide column entirely
- Empty basket → show placeholder state, no totals rendered

**Order CTA:** `platform_listings.platform_url` from DB → opens platform in new tab.

---

## Multi-Address Brussels Coverage

Scrapers are already parameterized by GPS coordinates. To test coverage:

1. Run scraper with a different Brussels address/coords
2. Run `node scripts/seed.js` — upserts into `platform_listings` with `scraped_at` timestamp
3. App always reads the latest record per `restaurant_id + platform` (unique constraint)

No schema changes needed. Coverage testing is a scraper/ops concern, not an app concern.

---

## What's Out of Scope

- User accounts / saved baskets
- Price history / charts
- Cities outside Brussels
- Scheduled scraping / automation
- Admin UI for restaurants
