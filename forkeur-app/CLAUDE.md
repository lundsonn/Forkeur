@AGENTS.md

# Forkeur App (Next.js 15)

Consumer-facing price comparison app. Server Components by default; `'use client'` only when state or browser APIs are needed.

## Structure

```
forkeur-app/
├── app/
│   ├── page.tsx              ← Homepage: restaurant list with cuisine filter + map
│   ├── promotions/page.tsx   ← Live promotions across all platforms
│   └── restaurant/[id]/
│       └── page.tsx          ← Restaurant detail: platform comparison + menu prices
├── components/
│   ├── HomepageClient.tsx    ← Client: search/filter + map toggle
│   ├── RestaurantCard.tsx    ← Single restaurant card (cheapest platform badge)
│   ├── CompareSheet.tsx      ← Bottom sheet comparing all platforms for a restaurant
│   ├── BasketSimulator.tsx   ← Client: build a basket, compare total per platform
│   ├── PromotionsClient.tsx  ← Client: promotions list with type filter
│   ├── MapView.tsx           ← Leaflet map of restaurants
│   └── PlatformPriceRow.tsx  ← One row in the platform comparison table
├── lib/
│   ├── queries.ts            ← All Supabase queries (server-side); exports RestaurantSummary, RestaurantDetail, PromoItem types
│   └── basket.ts             ← Basket state + Platform type
└── utils/supabase/
    ├── server.ts             ← createClient() for Server Components (cookie-based)
    ├── client.ts             ← createClient() for Client Components (browser)
    └── middleware.ts         ← session refresh middleware
```

## Key types (lib/queries.ts)

- `Platform` = `'uber_eats' | 'deliveroo' | 'takeaway' | 'direct'`
- `RestaurantSummary` — homepage card data (listings, cheapest platform, lat/lng)
- `RestaurantDetail` — full detail page (listings with fees + ETAs, menu items with cross-platform prices)
- `PromoItem` — promotions page (promo_type, label, value, min_order per listing)

## Routes

- `/` — restaurant list (server-rendered, client-filtered)
- `/promotions` — live promos (server-fetched, client-filtered by type)
- `/restaurant/[id]` — detail page with basket simulator
