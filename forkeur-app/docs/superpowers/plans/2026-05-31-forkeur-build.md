# Forkeur Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Forkeur food delivery price comparison app — homepage with search/browse, restaurant detail page with basket simulator showing live totals per platform.

**Architecture:** Next.js 15 App Router. Server Components fetch Supabase data directly (no API routes). Client Components handle search, filters, basket state. Pure basket math extracted to `lib/basket.ts` and tested with Vitest.

**Tech Stack:** Next.js 15, TypeScript, Tailwind CSS v4, Supabase (@supabase/ssr), Vitest

> **IMPORTANT — Read before writing any code:** This Next.js version has breaking changes. Read `node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md` and `06-fetching-data.md` before starting. Key breaking changes: `params` in dynamic routes is now a `Promise<{...}>` — you must `await params`. Commits are user-triggered — do NOT run `git commit` unless the user asks.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lib/basket.ts` | Create | Pure basket math functions |
| `lib/queries.ts` | Create | Typed Supabase query functions |
| `__tests__/basket.test.ts` | Create | Vitest tests for basket.ts |
| `vitest.config.mts` | Create | Vitest config for Next.js |
| `app/layout.tsx` | Modify | Forkeur title, clean up boilerplate |
| `app/page.tsx` | Replace | Homepage Server Component |
| `app/restaurant/[id]/page.tsx` | Create | Detail page Server Component |
| `app/restaurant/[id]/loading.tsx` | Create | Streaming fallback |
| `components/HomepageClient.tsx` | Create | Search + filter state, restaurant list |
| `components/RestaurantCard.tsx` | Create | Single restaurant row (presentational) |
| `components/BasketSimulator.tsx` | Create | Basket state + platform totals |
| `components/PlatformPriceRow.tsx` | Create | Menu item row with per-platform prices |
| `scripts/seed.js` | Create | Seeds Supabase from scraper output files |
| `.gitignore` | Modify | Add `.env.local`, `.superpowers/` |

---

## Task 1: Project Setup

**Files:**
- Modify: `app/layout.tsx`
- Modify: `.gitignore`
- Create: `vitest.config.mts`
- Modify: `package.json`

- [ ] **Step 1: Install Vitest dependencies**

```bash
cd forkeur-app
npm install -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom vite-tsconfig-paths
```

Expected: no errors, packages added to `devDependencies`.

- [ ] **Step 2: Create vitest.config.mts**

```ts
// vitest.config.mts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: 'jsdom',
  },
})
```

- [ ] **Step 3: Add test script to package.json**

In `package.json`, add `"test": "vitest"` to the `scripts` block:

```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "eslint",
  "test": "vitest"
}
```

- [ ] **Step 4: Update app/layout.tsx**

Replace the file content:

```tsx
// app/layout.tsx
import type { Metadata } from 'next'
import { Geist } from 'next/font/google'
import './globals.css'

const geist = Geist({ subsets: ['latin'], variable: '--font-geist-sans' })

export const metadata: Metadata = {
  title: 'Forkeur — Cheapest food delivery in Brussels',
  description: 'Compare delivery prices across Uber Eats, Deliveroo, and Takeaway.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} antialiased`}>
      <body className="min-h-screen bg-stone-50">{children}</body>
    </html>
  )
}
```

- [ ] **Step 5: Update .gitignore**

Add to `.gitignore`:

```
.env.local
.superpowers/
```

- [ ] **Step 6: Verify dev server starts**

```bash
npm run dev
```

Expected: server starts at `http://localhost:3000`, no TypeScript errors in terminal.

---

## Task 2: Basket Pure Logic + Tests

**Files:**
- Create: `lib/basket.ts`
- Create: `__tests__/basket.test.ts`

- [ ] **Step 1: Create lib/basket.ts**

```ts
// lib/basket.ts

export type Platform = 'uber_eats' | 'deliveroo' | 'takeaway'
export const PLATFORMS: Platform[] = ['uber_eats', 'deliveroo', 'takeaway']

export const PLATFORM_LABELS: Record<Platform, string> = {
  uber_eats: 'Uber Eats',
  deliveroo: 'Deliveroo',
  takeaway: 'Takeaway',
}

export type BasketItem = {
  name: string
  qty: number
  prices: Record<Platform, number | null>
}

export type PlatformFees = Record<Platform, number | null>
export type PlatformTotals = Record<Platform, number | null>

/**
 * Total for one platform = sum of (item_price * qty) + delivery_fee.
 * Items with null price for this platform are skipped (not available).
 * Returns null if delivery fee is null (platform not available).
 */
export function calculatePlatformTotal(
  items: BasketItem[],
  platform: Platform,
  deliveryFeeCents: number | null
): number | null {
  if (deliveryFeeCents === null) return null
  let subtotal = 0
  for (const item of items) {
    const price = item.prices[platform]
    if (price === null) continue
    subtotal += price * item.qty
  }
  return subtotal + deliveryFeeCents
}

export function calculateAllTotals(
  items: BasketItem[],
  fees: PlatformFees
): PlatformTotals {
  return {
    uber_eats: calculatePlatformTotal(items, 'uber_eats', fees.uber_eats),
    deliveroo: calculatePlatformTotal(items, 'deliveroo', fees.deliveroo),
    takeaway: calculatePlatformTotal(items, 'takeaway', fees.takeaway),
  }
}

export function findCheapestPlatform(totals: PlatformTotals): Platform | null {
  let cheapest: Platform | null = null
  let minTotal = Infinity
  for (const platform of PLATFORMS) {
    const total = totals[platform]
    if (total !== null && total < minTotal) {
      minTotal = total
      cheapest = platform
    }
  }
  return cheapest
}

export function centsToEuro(cents: number | null): string {
  if (cents === null) return '—'
  if (cents === 0) return 'Free'
  return `€${(cents / 100).toFixed(2)}`
}
```

- [ ] **Step 2: Create __tests__/basket.test.ts**

```ts
// __tests__/basket.test.ts
import { describe, it, expect } from 'vitest'
import {
  calculatePlatformTotal,
  calculateAllTotals,
  findCheapestPlatform,
  centsToEuro,
  type BasketItem,
  type PlatformTotals,
} from '../lib/basket'

const twoItems: BasketItem[] = [
  {
    name: 'Big Mac',
    qty: 1,
    prices: { uber_eats: 660, deliveroo: 640, takeaway: 620 },
  },
  {
    name: 'Large Fries',
    qty: 2,
    prices: { uber_eats: 350, deliveroo: 320, takeaway: 340 },
  },
]

describe('calculatePlatformTotal', () => {
  it('sums item prices * qty and adds delivery fee', () => {
    // uber_eats: 660 + 350*2 + 399 = 1759
    expect(calculatePlatformTotal(twoItems, 'uber_eats', 399)).toBe(1759)
  })

  it('returns null when delivery fee is null', () => {
    expect(calculatePlatformTotal(twoItems, 'uber_eats', null)).toBeNull()
  })

  it('skips items with null price for the platform', () => {
    const items: BasketItem[] = [
      { name: 'Big Mac', qty: 1, prices: { uber_eats: null, deliveroo: 640, takeaway: 620 } },
    ]
    // uber_eats: 0 (skipped) + 299 delivery = 299
    expect(calculatePlatformTotal(items, 'uber_eats', 299)).toBe(299)
  })

  it('handles empty basket — returns just delivery fee', () => {
    expect(calculatePlatformTotal([], 'uber_eats', 399)).toBe(399)
  })
})

describe('findCheapestPlatform', () => {
  it('returns platform with lowest total', () => {
    const totals: PlatformTotals = { uber_eats: 1759, deliveroo: 1459, takeaway: 1139 }
    expect(findCheapestPlatform(totals)).toBe('takeaway')
  })

  it('returns null when all totals are null', () => {
    expect(findCheapestPlatform({ uber_eats: null, deliveroo: null, takeaway: null })).toBeNull()
  })

  it('ignores null platforms when comparing', () => {
    const totals: PlatformTotals = { uber_eats: null, deliveroo: 1459, takeaway: null }
    expect(findCheapestPlatform(totals)).toBe('deliveroo')
  })
})

describe('centsToEuro', () => {
  it('formats cents as euros', () => {
    expect(centsToEuro(399)).toBe('€3.99')
  })

  it('returns "Free" for 0', () => {
    expect(centsToEuro(0)).toBe('Free')
  })

  it('returns "—" for null', () => {
    expect(centsToEuro(null)).toBe('—')
  })
})
```

- [ ] **Step 3: Run tests**

```bash
npm test -- --run
```

Expected output:
```
✓ __tests__/basket.test.ts (9)
Test Files  1 passed (1)
Tests       9 passed (9)
```

---

## Task 3: Supabase Query Functions

**Files:**
- Create: `lib/queries.ts`

- [ ] **Step 1: Create lib/queries.ts**

```ts
// lib/queries.ts
import { cookies } from 'next/headers'
import { createClient } from '@/utils/supabase/server'
import type { Platform } from '@/lib/basket'

// ── Types ─────────────────────────────────────────────────────────────────────

export type RestaurantSummary = {
  id: string
  name: string
  cuisine: string[]
  cheapest: {
    platform: Platform
    fee_label: string
    savings_cents: number
  } | null
}

export type PlatformListing = {
  id: string
  platform: Platform
  platform_url: string | null
  delivery_fee_cents: number | null
  delivery_fee_label: string | null
  eta_label: string | null
  rating: number | null
}

export type MenuItemWithPrices = {
  name: string
  description: string | null
  category: string | null
  image_url: string | null
  prices: Record<Platform, number | null>
}

export type RestaurantDetail = {
  id: string
  name: string
  city: string
  cuisine: string[]
  listings: PlatformListing[]
  menuItems: MenuItemWithPrices[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function getSupabase() {
  const cookieStore = await cookies()
  return createClient(cookieStore)
}

// ── Queries ───────────────────────────────────────────────────────────────────

export async function getRestaurants(): Promise<RestaurantSummary[]> {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('restaurants')
    .select(`
      id, name, cuisine,
      platform_listings ( platform, delivery_fee_cents, delivery_fee_label )
    `)
    .eq('city', 'Brussels')

  if (error) throw new Error(`getRestaurants: ${error.message}`)

  return (data ?? [])
    .map((r) => {
      const listings = (r.platform_listings ?? []) as {
        platform: string
        delivery_fee_cents: number | null
        delivery_fee_label: string | null
      }[]

      const available = listings.filter((l) => l.delivery_fee_cents !== null)

      if (available.length === 0) {
        return { id: r.id, name: r.name, cuisine: r.cuisine ?? [], cheapest: null }
      }

      const sorted = [...available].sort(
        (a, b) => a.delivery_fee_cents! - b.delivery_fee_cents!
      )
      const cheapest = sorted[0]
      const mostExpensive = sorted[sorted.length - 1]

      return {
        id: r.id,
        name: r.name,
        cuisine: r.cuisine ?? [],
        cheapest: {
          platform: cheapest.platform as Platform,
          fee_label: cheapest.delivery_fee_label ?? '?',
          savings_cents: mostExpensive.delivery_fee_cents! - cheapest.delivery_fee_cents!,
        },
      }
    })
    .sort((a, b) => (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0))
}

export async function getRestaurantWithListings(
  id: string
): Promise<RestaurantDetail | null> {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('restaurants')
    .select(`
      id, name, city, cuisine,
      platform_listings (
        id, platform, platform_url,
        delivery_fee_cents, delivery_fee_label, eta_label, rating,
        menu_items ( name, description, price_cents, category, image_url )
      )
    `)
    .eq('id', id)
    .single()

  if (error) return null

  const listings: PlatformListing[] = (data.platform_listings ?? []).map((l: any) => ({
    id: l.id,
    platform: l.platform as Platform,
    platform_url: l.platform_url ?? null,
    delivery_fee_cents: l.delivery_fee_cents ?? null,
    delivery_fee_label: l.delivery_fee_label ?? null,
    eta_label: l.eta_label ?? null,
    rating: l.rating !== null ? parseFloat(String(l.rating)) : null,
  }))

  // Pivot menu items: one entry per item name, prices from all platforms
  const itemMap = new Map<string, MenuItemWithPrices>()

  for (const listing of data.platform_listings ?? [] as any[]) {
    const platform = listing.platform as Platform
    for (const item of listing.menu_items ?? []) {
      if (!itemMap.has(item.name)) {
        itemMap.set(item.name, {
          name: item.name,
          description: item.description ?? null,
          category: item.category ?? null,
          image_url: item.image_url ?? null,
          prices: { uber_eats: null, deliveroo: null, takeaway: null },
        })
      }
      itemMap.get(item.name)!.prices[platform] = item.price_cents ?? null
    }
  }

  return {
    id: data.id,
    name: data.name,
    city: data.city,
    cuisine: data.cuisine ?? [],
    listings,
    menuItems: Array.from(itemMap.values()),
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
npx tsc --noEmit
```

Expected: no errors.

---

## Task 4: Homepage

**Files:**
- Replace: `app/page.tsx`
- Create: `components/RestaurantCard.tsx`
- Create: `components/HomepageClient.tsx`

- [ ] **Step 1: Create components/RestaurantCard.tsx**

```tsx
// components/RestaurantCard.tsx
import { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_LABELS } from '@/lib/basket'

export default function RestaurantCard({ restaurant }: { restaurant: RestaurantSummary }) {
  const { name, cuisine, cheapest } = restaurant
  return (
    <div className="bg-white border border-stone-200 rounded-xl p-4 flex justify-between items-center hover:border-stone-300 transition-colors cursor-pointer">
      <div className="min-w-0">
        <p className="text-sm font-bold text-stone-900 truncate">{name}</p>
        <p className="text-xs text-stone-400 mt-0.5">{cuisine.join(' · ')}</p>
        {cheapest && (
          <span className="inline-block mt-2 bg-green-50 text-green-700 text-xs px-2 py-0.5 rounded font-semibold">
            {PLATFORM_LABELS[cheapest.platform]} {cheapest.fee_label}
          </span>
        )}
      </div>
      {cheapest && cheapest.savings_cents > 0 && (
        <div className="text-right ml-4 shrink-0">
          <p className="text-xs text-stone-400">save up to</p>
          <p className="text-lg font-extrabold text-green-700">{centsToEuro(cheapest.savings_cents)}</p>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create components/HomepageClient.tsx**

```tsx
// components/HomepageClient.tsx
'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import { RestaurantSummary } from '@/lib/queries'
import RestaurantCard from './RestaurantCard'

const CUISINES = ['Burgers', 'Pizza', 'Asian', 'Healthy', 'Sandwiches']

export default function HomepageClient({ restaurants }: { restaurants: RestaurantSummary[] }) {
  const [search, setSearch] = useState('')
  const [selectedCuisine, setSelectedCuisine] = useState<string | null>(null)

  const filtered = useMemo(
    () =>
      restaurants.filter((r) => {
        const matchSearch = r.name.toLowerCase().includes(search.toLowerCase())
        const matchCuisine =
          !selectedCuisine ||
          r.cuisine.some((c) => c.toLowerCase().includes(selectedCuisine.toLowerCase()))
        return matchSearch && matchCuisine
      }),
    [restaurants, search, selectedCuisine]
  )

  return (
    <div className="max-w-lg mx-auto px-4 pb-10">
      {/* Hero + search */}
      <div className="bg-stone-50 pt-8 pb-4">
        <h1 className="text-2xl font-extrabold text-stone-900 tracking-tight">
          Find the cheapest delivery
        </h1>
        <p className="text-sm text-stone-400 mt-1">
          Compare Uber Eats · Deliveroo · Takeaway in Brussels
        </p>
        <div className="mt-4 flex items-center gap-2 bg-white border border-stone-200 rounded-xl px-4 py-3 shadow-sm">
          <span className="text-stone-400 text-sm">🔍</span>
          <input
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-stone-400"
            placeholder="Search restaurant or dish…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="text-stone-300 hover:text-stone-500 text-xs"
            >✕</button>
          )}
        </div>
      </div>

      {/* Cuisine filters */}
      <div className="flex gap-2 overflow-x-auto py-3">
        <button
          onClick={() => setSelectedCuisine(null)}
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            !selectedCuisine
              ? 'bg-stone-900 text-white'
              : 'bg-white border border-stone-200 text-stone-600'
          }`}
        >
          All
        </button>
        {CUISINES.map((c) => (
          <button
            key={c}
            onClick={() => setSelectedCuisine(selectedCuisine === c ? null : c)}
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              selectedCuisine === c
                ? 'bg-stone-900 text-white'
                : 'bg-white border border-stone-200 text-stone-600'
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      {/* Count */}
      <p className="text-xs text-stone-400 mb-3">
        {filtered.length} restaurant{filtered.length !== 1 ? 's' : ''}
      </p>

      {/* Restaurant list */}
      <div className="flex flex-col gap-3">
        {filtered.map((r) => (
          <Link key={r.id} href={`/restaurant/${r.id}`}>
            <RestaurantCard restaurant={r} />
          </Link>
        ))}
        {filtered.length === 0 && (
          <p className="text-center text-stone-400 text-sm py-16">No restaurants found</p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Replace app/page.tsx**

```tsx
// app/page.tsx
import { getRestaurants } from '@/lib/queries'
import HomepageClient from '@/components/HomepageClient'

export default async function Page() {
  const restaurants = await getRestaurants()
  return <HomepageClient restaurants={restaurants} />
}
```

- [ ] **Step 4: Verify homepage in browser**

```bash
npm run dev
```

Open `http://localhost:3000`. Expected: search bar, cuisine filters, restaurant cards (or "No restaurants found" if DB is empty — that's fine, data comes in Task 8).

- [ ] **Step 5: Check TypeScript**

```bash
npx tsc --noEmit
```

Expected: no errors.

---

## Task 5: Detail Page

**Files:**
- Create: `app/restaurant/[id]/page.tsx`
- Create: `app/restaurant/[id]/loading.tsx`

- [ ] **Step 1: Create app/restaurant/[id]/loading.tsx**

```tsx
// app/restaurant/[id]/loading.tsx
export default function Loading() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="h-7 w-40 bg-stone-200 rounded animate-pulse mb-2" />
      <div className="h-4 w-24 bg-stone-100 rounded animate-pulse mb-8" />
      <div className="flex gap-6">
        <div className="flex-1 space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 bg-stone-100 rounded-xl animate-pulse" />
          ))}
        </div>
        <div className="w-52 h-80 bg-stone-100 rounded-xl animate-pulse" />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create app/restaurant/[id]/page.tsx**

Note: `params` is a `Promise` in Next.js 15 — must `await` it.

```tsx
// app/restaurant/[id]/page.tsx
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getRestaurantWithListings } from '@/lib/queries'
import BasketSimulator from '@/components/BasketSimulator'

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const data = await getRestaurantWithListings(id)

  if (!data) notFound()

  return (
    <div className="max-w-4xl mx-auto px-4 py-6">
      <Link href="/" className="text-xs text-stone-400 hover:text-stone-700 mb-4 inline-block">
        ← Back
      </Link>
      <h1 className="text-2xl font-extrabold text-stone-900">{data.name}</h1>
      <p className="text-sm text-stone-400 mt-1 mb-6">{data.cuisine.join(' · ')}</p>
      <BasketSimulator menuItems={data.menuItems} listings={data.listings} />
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript**

```bash
npx tsc --noEmit
```

Expected: no errors.

---

## Task 6: PlatformPriceRow

**Files:**
- Create: `components/PlatformPriceRow.tsx`

- [ ] **Step 1: Create components/PlatformPriceRow.tsx**

```tsx
// components/PlatformPriceRow.tsx
import { PLATFORMS, Platform, centsToEuro } from '@/lib/basket'
import { MenuItemWithPrices } from '@/lib/queries'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
}

function cheapestPlatformForItem(prices: Record<Platform, number | null>): Platform | null {
  let cheapest: Platform | null = null
  let min = Infinity
  for (const platform of PLATFORMS) {
    const price = prices[platform]
    if (price !== null && price < min) {
      min = price
      cheapest = platform
    }
  }
  return cheapest
}

type Props = {
  item: MenuItemWithPrices
  onAdd: () => void
}

export default function PlatformPriceRow({ item, onAdd }: Props) {
  const cheapest = cheapestPlatformForItem(item.prices)

  return (
    <div className="bg-white border border-stone-200 rounded-xl p-3 mb-2">
      <div className="flex justify-between items-start mb-2">
        <div className="min-w-0 pr-3">
          <p className="text-sm font-bold text-stone-900">{item.name}</p>
          {item.description && (
            <p className="text-xs text-stone-400 mt-0.5 line-clamp-1">{item.description}</p>
          )}
        </div>
        <button
          onClick={onAdd}
          className="shrink-0 bg-stone-900 text-white rounded-lg w-7 h-7 flex items-center justify-center text-base font-bold hover:bg-stone-700 transition-colors"
          aria-label={`Add ${item.name} to basket`}
        >
          +
        </button>
      </div>
      <div className="flex gap-1.5 flex-wrap">
        {PLATFORMS.map((platform) => {
          const price = item.prices[platform]
          const isCheapest = platform === cheapest && price !== null
          return (
            <span
              key={platform}
              className={`text-xs px-2 py-0.5 rounded font-medium ${
                isCheapest
                  ? 'bg-green-50 text-green-700 font-bold'
                  : 'bg-stone-100 text-stone-500'
              }`}
            >
              {PLATFORM_SHORT[platform]} {centsToEuro(price)}
              {isCheapest ? ' ✓' : ''}
            </span>
          )
        })}
      </div>
    </div>
  )
}
```

---

## Task 7: Basket Simulator

**Files:**
- Create: `components/BasketSimulator.tsx`

- [ ] **Step 1: Create components/BasketSimulator.tsx**

```tsx
// components/BasketSimulator.tsx
'use client'
import { useState, useMemo } from 'react'
import {
  BasketItem,
  PlatformFees,
  Platform,
  PLATFORMS,
  PLATFORM_LABELS,
  calculateAllTotals,
  findCheapestPlatform,
  centsToEuro,
} from '@/lib/basket'
import { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import PlatformPriceRow from './PlatformPriceRow'

type Props = {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
}

export default function BasketSimulator({ menuItems, listings }: Props) {
  const [basket, setBasket] = useState<BasketItem[]>([])

  const fees: PlatformFees = useMemo(() => {
    const result: PlatformFees = { uber_eats: null, deliveroo: null, takeaway: null }
    for (const l of listings) result[l.platform] = l.delivery_fee_cents
    return result
  }, [listings])

  const platformUrls = useMemo(() => {
    const result: Partial<Record<Platform, string>> = {}
    for (const l of listings) {
      if (l.platform_url) result[l.platform] = l.platform_url
    }
    return result
  }, [listings])

  const totals = useMemo(() => calculateAllTotals(basket, fees), [basket, fees])
  const cheapestPlatform = useMemo(() => findCheapestPlatform(totals), [totals])

  const mostExpensiveTotal = useMemo(
    () => Math.max(...PLATFORMS.map((p) => totals[p] ?? 0)),
    [totals]
  )

  // Group menu items by category
  const grouped = useMemo(() => {
    const map = new Map<string, MenuItemWithPrices[]>()
    for (const item of menuItems) {
      const cat = item.category ?? 'Menu'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(item)
    }
    return map
  }, [menuItems])

  function addItem(item: MenuItemWithPrices) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === item.name)
      if (existing) {
        return prev.map((b) =>
          b.name === item.name ? { ...b, qty: b.qty + 1 } : b
        )
      }
      return [...prev, { name: item.name, qty: 1, prices: item.prices }]
    })
  }

  function removeItem(name: string) {
    setBasket((prev) => prev.filter((b) => b.name !== name))
  }

  return (
    <div className="flex gap-6 items-start">
      {/* Left panel: menu items */}
      <div className="flex-1 min-w-0">
        {menuItems.length === 0 && (
          <p className="text-sm text-stone-400">No menu data available for this restaurant.</p>
        )}
        {Array.from(grouped.entries()).map(([category, items]) => (
          <div key={category} className="mb-6">
            <h3 className="text-xs font-bold text-stone-500 uppercase tracking-widest mb-3">
              {category}
            </h3>
            {items.map((item) => (
              <PlatformPriceRow
                key={item.name}
                item={item}
                onAdd={() => addItem(item)}
              />
            ))}
          </div>
        ))}
      </div>

      {/* Right panel: basket + totals */}
      <div className="w-52 shrink-0 sticky top-4">
        <div className="bg-white border border-stone-200 rounded-xl p-4">
          <h3 className="text-xs font-bold text-stone-500 uppercase tracking-widest mb-3">
            Your basket
          </h3>

          {basket.length === 0 ? (
            <p className="text-xs text-stone-400 mb-4">Add items to compare prices</p>
          ) : (
            <div className="mb-4 space-y-1">
              {basket.map((item) => (
                <div key={item.name} className="flex justify-between items-center">
                  <span className="text-xs text-stone-600 truncate">
                    {item.qty}× {item.name}
                  </span>
                  <button
                    onClick={() => removeItem(item.name)}
                    className="text-stone-300 hover:text-stone-500 text-xs ml-2 shrink-0"
                    aria-label={`Remove ${item.name}`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          <h3 className="text-xs font-bold text-stone-500 uppercase tracking-widest mb-3">
            Total per platform
          </h3>

          {basket.length === 0 ? (
            <p className="text-xs text-stone-300">—</p>
          ) : (
            <div className="space-y-2 mb-4">
              {PLATFORMS.map((platform) => {
                if (fees[platform] === null) return null
                const total = totals[platform]
                const isCheapest = platform === cheapestPlatform
                const itemsSubtotal = total !== null ? total - (fees[platform] ?? 0) : null

                return (
                  <div
                    key={platform}
                    className={`rounded-lg p-2.5 ${
                      isCheapest
                        ? 'bg-green-50 border border-green-200'
                        : 'bg-stone-50 border border-stone-200'
                    }`}
                  >
                    {isCheapest && (
                      <p className="text-xs text-green-600 font-bold mb-0.5">🏆 CHEAPEST</p>
                    )}
                    <p
                      className={`text-sm font-bold ${
                        isCheapest ? 'text-green-700' : 'text-stone-600'
                      }`}
                    >
                      {PLATFORM_LABELS[platform]}
                    </p>
                    <p className="text-xs text-stone-400">
                      Items: {centsToEuro(itemsSubtotal)}
                    </p>
                    <p className="text-xs text-stone-400">
                      Delivery: {centsToEuro(fees[platform])}
                    </p>
                    <p
                      className={`text-base font-extrabold mt-1 ${
                        isCheapest ? 'text-green-700' : 'text-stone-600'
                      }`}
                    >
                      {centsToEuro(total)}
                    </p>
                  </div>
                )
              })}
            </div>
          )}

          {cheapestPlatform && basket.length > 0 && (
            <>
              {platformUrls[cheapestPlatform] ? (
                <a
                  href={platformUrls[cheapestPlatform]}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block w-full bg-stone-900 text-white text-center text-xs font-bold rounded-lg py-2.5 hover:bg-stone-700 transition-colors"
                >
                  Order on {PLATFORM_LABELS[cheapestPlatform]} →
                </a>
              ) : (
                <p className="text-xs text-stone-400 text-center">
                  Best: {PLATFORM_LABELS[cheapestPlatform]}
                </p>
              )}
              {mostExpensiveTotal > (totals[cheapestPlatform] ?? 0) && (
                <p className="text-xs text-stone-400 text-center mt-2">
                  saves {centsToEuro(mostExpensiveTotal - (totals[cheapestPlatform] ?? 0))} vs most expensive
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run full build to catch any issues**

```bash
npm run build
```

Expected: build succeeds. If there are TypeScript errors, fix them before continuing.

---

## Task 8: Seed Script

**Files:**
- Create: `scripts/seed.js`

This script reads the existing scraper output files from the parent `food-price-compare/` directory and seeds them into Supabase. Run after running the scrapers.

- [ ] **Step 1: Create scripts/seed.js**

```js
// scripts/seed.js
// Seeds Supabase from scraper output files.
// Prerequisites: run scrapers first, then: node scripts/seed.js

require('dotenv').config({ path: '.env.local' })
const fs = require('fs')
const path = require('path')
const { createClient } = require('@supabase/supabase-js')

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
)

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseFeeCents(raw) {
  if (raw === null || raw === undefined) return null
  const str = String(raw)
  if (/free|gratuit/i.test(str)) return 0
  const match = str.match(/(\d+)[.,](\d{2})/)
  if (match) return parseInt(match[1]) * 100 + parseInt(match[2])
  const whole = str.match(/(\d+)/)
  if (whole) return parseInt(whole[1]) * 100
  return null
}

function centsToLabel(cents) {
  if (cents === null || cents === undefined) return null
  if (cents === 0) return 'Free'
  return `€${(cents / 100).toFixed(2)}`
}

function parseEta(raw) {
  if (!raw) return { min: null, max: null, label: null }
  const range = raw.match(/(\d+)\s*(?:à|to|-|–)\s*(\d+)/)
  if (range) {
    const min = parseInt(range[1])
    const max = parseInt(range[2])
    return { min, max, label: min === max ? `${min} min` : `${min}–${max} min` }
  }
  const single = raw.match(/(\d+)\s*min/i)
  if (single) {
    const v = parseInt(single[1])
    return { min: v, max: v, label: `${v} min` }
  }
  return { min: null, max: null, label: raw }
}

function priceToCents(raw) {
  if (raw === null || raw === undefined) return null
  const str = String(raw)
  if (/free|gratuit/i.test(str)) return 0
  const match = str.match(/(\d+)[.,](\d{2})/)
  if (match) return parseInt(match[1]) * 100 + parseInt(match[2])
  return null
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function seedPlatform({ platformKey, dbPlatform, dataFile }) {
  const filePath = path.join(__dirname, '..', '..', dataFile)
  if (!fs.existsSync(filePath)) {
    console.log(`⏭  ${dataFile} not found — skipping ${platformKey}`)
    return
  }

  const raw = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
  const restaurants = Array.isArray(raw) ? raw : [raw]

  console.log(`\n📥 ${dbPlatform}: ${restaurants.length} restaurants`)

  for (const r of restaurants) {
    const name = r.name || r.restaurantName || r.title
    if (!name) continue

    // Upsert restaurant
    const { data: restaurant, error: rErr } = await supabase
      .from('restaurants')
      .upsert({ name, city: 'Brussels' }, { onConflict: 'name,city' })
      .select()
      .single()

    if (rErr) { console.error(`  ❌ ${name} restaurant:`, rErr.message); continue }

    const feeCents = parseFeeCents(r.deliveryFee)
    const eta = parseEta(r.eta)

    // Upsert platform listing
    const { data: listing, error: lErr } = await supabase
      .from('platform_listings')
      .upsert({
        restaurant_id: restaurant.id,
        platform: dbPlatform,
        platform_url: r.url ?? r.restaurantUrl ?? null,
        delivery_fee_cents: feeCents,
        delivery_fee_label: centsToLabel(feeCents),
        eta_min: eta.min,
        eta_max: eta.max,
        eta_label: eta.label,
        rating: r.rating && r.rating !== 'N/A' ? parseFloat(String(r.rating)) : null,
        rating_count: r.reviewCount ?? null,
        hero_image_url: r.heroImage ?? r.imageUrl ?? null,
        scraped_at: new Date().toISOString(),
      }, { onConflict: 'restaurant_id,platform' })
      .select()
      .single()

    if (lErr) { console.error(`  ❌ ${name} listing:`, lErr.message); continue }

    // Refresh menu items
    await supabase.from('menu_items').delete().eq('listing_id', listing.id)

    const menuItems = r.menuItems ?? r.menu ?? []
    if (menuItems.length > 0) {
      const rows = menuItems.map((item) => {
        const cents = priceToCents(item.price)
        return {
          listing_id: listing.id,
          name: item.name ?? 'Unknown',
          description: item.description ?? null,
          price_cents: cents,
          price_label: cents !== null ? centsToLabel(cents) : (item.price ?? null),
          category: item.category ?? null,
          image_url: item.image ?? item.imageUrl ?? null,
        }
      })
      const { error: mErr } = await supabase.from('menu_items').insert(rows)
      if (mErr) console.error(`  ❌ ${name} menu items:`, mErr.message)
      else console.log(`  ✅ ${name} — ${rows.length} menu items`)
    } else {
      console.log(`  ✅ ${name} — no menu items`)
    }
  }
}

async function main() {
  console.log('\n🌱 Seeding Forkeur Supabase...\n')

  await seedPlatform({
    platformKey: 'uberEats',
    dbPlatform: 'uber_eats',
    dataFile: 'uber-eats-output.json',
  })

  await seedPlatform({
    platformKey: 'deliveroo',
    dbPlatform: 'deliveroo',
    dataFile: 'deliveroo-data.json',
  })

  await seedPlatform({
    platformKey: 'takeaway',
    dbPlatform: 'takeaway',
    dataFile: 'takeaway-restaurants.json',
  })

  console.log('\n🎉 Done! Check your Supabase dashboard to verify.\n')
}

main().catch((err) => {
  console.error('❌', err.message)
  process.exit(1)
})
```

- [ ] **Step 2: Run the seed script**

Ensure scrapers have been run first so the output JSON files exist in `food-price-compare/`.

```bash
node scripts/seed.js
```

Expected output:
```
🌱 Seeding Forkeur Supabase...
📥 uber_eats: N restaurants
  ✅ McDonald's — X menu items
...
🎉 Done!
```

- [ ] **Step 3: Verify data in app**

```bash
npm run dev
```

Open `http://localhost:3000`. Expected: restaurant cards with platform badges and savings amounts. Click a restaurant to open detail page with menu items and basket simulator.

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - Homepage search + browse ✓ (Task 4)
  - Cuisine filters ✓ (Task 4)
  - Restaurant card with cheapest platform + savings ✓ (Task 4)
  - Detail page with item prices per platform ✓ (Task 6, 7)
  - Basket simulator with live totals ✓ (Task 7)
  - Order CTA deep link ✓ (Task 7)
  - Platform not available → hidden ✓ (`fees[platform] === null` check)
  - Item not available on platform → "—", excluded from total ✓ (`calculatePlatformTotal` skips null prices)
  - Empty basket placeholder ✓ (Task 7)
  - Seed script ✓ (Task 8)
  - Multi-address Brussels: scraper concern, no app changes needed ✓

- [x] **No placeholders** — all code blocks complete
- [x] **Type consistency** — `Platform`, `BasketItem`, `MenuItemWithPrices`, `PlatformListing` used consistently across tasks 2–7
- [x] **params awaited** — `const { id } = await params` in Task 5 ✓
- [x] **No commits in plan** — user triggers all commits
