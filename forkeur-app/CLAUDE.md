@AGENTS.md

# Forkeur App (Next.js 15)

Consumer-facing price comparison app. Server Components by default; `'use client'` only when state or browser APIs are needed.

## Structure

```
forkeur-app/
├── app/
│   ├── page.tsx              ← Homepage: restaurant list with cuisine filter + map
│   ├── deals/page.tsx        ← Best deals: ranked promos across all platforms
│   ├── promotions/page.tsx   ← Redirect → /deals
│   └── restaurant/[id]/
│       └── page.tsx          ← Restaurant detail: platform comparison + menu prices
├── components/
│   ├── HomepageClient.tsx    ← Client: search/filter + map toggle
│   ├── RestaurantCard.tsx    ← Single restaurant card (cheapest platform badge)
│   ├── CompareSheet.tsx      ← Bottom sheet comparing all platforms for a restaurant
│   ├── BasketSimulator.tsx   ← Client: build a basket, compare total per platform
│   ├── DealsClient.tsx       ← Client: best deals list with filter pills + sort logic
│   ├── MapView.tsx           ← Leaflet map of restaurants
│   └── PlatformPriceRow.tsx  ← One row in the platform comparison table
├── lib/
│   ├── queries.ts            ← All Supabase queries (server-side); exports RestaurantSummary, RestaurantDetail, DealItem types
│   ├── deals.ts              ← Pure helpers: DealItem type, filter/sort/band/badge logic
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
- `DealItem` — deals page (promo_type, label, value, min_order, rating, review_count, cuisine, area per listing)

## Routes

- `/` — restaurant list (server-rendered, client-filtered)
- `/deals` — best deals ranked by type + quality score (server-fetched, client-filtered)
- `/promotions` — redirects to `/deals`
- `/restaurant/[id]` — detail page with basket simulator

## i18n — ALWAYS develop in all 3 languages

App supports **EN / FR / NL** via `next-intl` (cookie-based, no URL prefix).

**Rule: every new UI string must be added to all three message files simultaneously.**

- Translations live in `messages/en.json`, `messages/fr.json`, `messages/nl.json`
- Client components: `const t = useTranslations('namespace')`
- Server components / metadata: `const t = await getTranslations('namespace')`
- Never hardcode user-visible strings — always use `t(key)` even for short labels
- LangToggle (EN · FR · NL) is rendered in every page nav
- Locale detected from `NEXT_LOCALE` cookie → `Accept-Language` header → `'en'`
