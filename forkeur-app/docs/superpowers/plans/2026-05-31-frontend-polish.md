# Frontend Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the Forkeur consumer app — show all platform fees on restaurant cards, dynamic cuisine chips, rating in detail header, sticky order CTA, swipe-to-clear basket, skeleton loading, and safe area insets.

**Architecture:** All changes are in `forkeur-app/`. `lib/queries.ts` widens its return types; components consume the new shape. `StickyOrderBar` is a new fixed-position component wired into `BasketSimulator`. No new DB queries — data is already fetched.

**Tech Stack:** Next.js 15 App Router, TypeScript, Tailwind CSS v4, Supabase, Vitest + @testing-library/react + jsdom

---

## File Map

| File | Action | Change |
|---|---|---|
| `lib/queries.ts` | Modify | `RestaurantSummary` adds `listings[]`; `getRestaurants` returns `{ restaurants, cuisines }` |
| `app/page.tsx` | Modify | Destructure new return shape; pass `cuisines` prop |
| `components/HomepageClient.tsx` | Modify | Accept `cuisines: string[]` prop; drop hardcoded array |
| `components/RestaurantCard.tsx` | Modify | Show all 3 platform fees inline; bold cheapest |
| `app/restaurant/[id]/page.tsx` | Modify | Add best rating to subtitle |
| `components/StickyOrderBar.tsx` | Create | Fixed bottom CTA bar — platform + total + safe area |
| `components/BasketSimulator.tsx` | Modify | Remove inline CTA; wire `StickyOrderBar`; swipe-to-clear |
| `app/restaurant/[id]/loading.tsx` | Modify | Full skeleton matching detail page shape |
| `app/layout.tsx` | Modify | Add `viewport` export with `viewportFit: 'cover'` |
| `__tests__/restaurant-card.test.tsx` | Create | Tests for RestaurantCard fee display |
| `__tests__/sticky-order-bar.test.tsx` | Create | Tests for StickyOrderBar visibility |

---

## Task 1: Update `lib/queries.ts` — Widen Types + Return Shape

**Files:**
- Modify: `lib/queries.ts`

- [ ] **Step 1: Update `RestaurantSummary` type**

In `lib/queries.ts`, replace the existing `RestaurantSummary` type:

```ts
export type RestaurantSummary = {
  id: string
  name: string
  cuisine: string[]
  listings: { platform: Platform; delivery_fee_cents: number | null }[]
  cheapest: {
    platform: Platform
    fee_label: string
    savings_cents: number
  } | null
}
```

- [ ] **Step 2: Update `getRestaurants` return type and body**

Replace the entire `getRestaurants` function:

```ts
export async function getRestaurants(): Promise<{
  restaurants: RestaurantSummary[]
  cuisines: string[]
}> {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('restaurants')
    .select(`
      id, name, cuisine,
      platform_listings ( platform, delivery_fee )
    `)

  if (error) throw new Error(`getRestaurants: ${error.message}`)

  const restaurants: RestaurantSummary[] = (data ?? [])
    .map((r) => {
      const rawListings = (r.platform_listings ?? []) as {
        platform: string
        delivery_fee: number | null
      }[]

      const listings = rawListings.map((l) => ({
        platform: l.platform as Platform,
        delivery_fee_cents: feeCents(l.delivery_fee),
      }))

      const available = listings.filter((l) => l.delivery_fee_cents !== null)

      if (available.length === 0) {
        return {
          id: r.id,
          name: r.name,
          cuisine: r.cuisine ? [r.cuisine] : [],
          listings,
          cheapest: null,
        }
      }

      const sorted = [...available].sort(
        (a, b) => a.delivery_fee_cents! - b.delivery_fee_cents!
      )
      const cheapest = sorted[0]
      const mostExpensive = sorted[sorted.length - 1]

      return {
        id: r.id,
        name: r.name,
        cuisine: r.cuisine ? [r.cuisine] : [],
        listings,
        cheapest: {
          platform: cheapest.platform,
          fee_label: feeLabel(cheapest.delivery_fee_cents !== null ? cheapest.delivery_fee_cents / 100 : null) ?? '?',
          savings_cents:
            (mostExpensive.delivery_fee_cents ?? 0) -
            (cheapest.delivery_fee_cents ?? 0),
        },
      }
    })
    .sort((a, b) => (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0))

  const cuisines = [
    ...new Set(restaurants.flatMap((r) => r.cuisine).filter(Boolean)),
  ]
    .sort()
    .slice(0, 8)

  return { restaurants, cuisines }
}
```

- [ ] **Step 3: Fix `feeLabel` call — it currently takes euros not cents**

Check the existing `feeLabel` helper in `lib/queries.ts`:
```ts
function feeLabel(fee: number | null): string | null {
  if (fee == null) return null
  return fee === 0 ? 'Free' : `€${fee.toFixed(2)}`
}
```
This takes euros. The cheapest object was using `feeCents(cheapest.delivery_fee)` in the old code but the label was built with the raw euro value. The new code needs to pass euros to `feeLabel`. Replace the cheapest label line:

```ts
fee_label: feeLabel(cheapest.delivery_fee_cents !== null ? cheapest.delivery_fee_cents / 100 : null) ?? '?',
```

This is already correct in Step 2. No further change needed.

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors related to `getRestaurants` or `RestaurantSummary`.

---

## Task 2: Update `app/page.tsx` — Destructure New Return

**Files:**
- Modify: `app/page.tsx`

- [ ] **Step 1: Update page to destructure restaurants and cuisines**

Replace the entire file:

```ts
// app/page.tsx
import { getRestaurants } from '@/lib/queries'
import HomepageClient from '@/components/HomepageClient'

export default async function Page() {
  const { restaurants, cuisines } = await getRestaurants()
  return <HomepageClient restaurants={restaurants} cuisines={cuisines} />
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

---

## Task 3: Update `HomepageClient.tsx` — Dynamic Cuisines

**Files:**
- Modify: `components/HomepageClient.tsx`

- [ ] **Step 1: Replace hardcoded cuisines with prop**

Replace the top of the component — remove `const CUISINES = [...]` and update the props type:

```tsx
'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import { RestaurantSummary } from '@/lib/queries'
import RestaurantCard from './RestaurantCard'

export default function HomepageClient({
  restaurants,
  cuisines,
}: {
  restaurants: RestaurantSummary[]
  cuisines: string[]
}) {
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
    <div className="max-w-md mx-auto px-5">
      {/* Nav */}
      <div className="flex items-center justify-between pt-5 pb-4">
        <div className="flex items-center gap-1.5">
          <span className="text-stone-700 text-base">⑂</span>
          <span className="font-bold text-base tracking-tight">
            fork<span className="text-orange-500">eur</span>
          </span>
        </div>
        <span className="text-sm text-stone-500">Brussels ↓</span>
      </div>

      {/* Hero */}
      <h1 className="text-[1.65rem] font-bold text-stone-900 leading-tight mb-4">
        Where are you<br />ordering from?
      </h1>

      {/* Search */}
      <div className="flex items-center gap-2.5 border border-stone-200 rounded-xl px-4 py-3 mb-5">
        <span className="text-stone-400 text-sm">🔍</span>
        <input
          className="flex-1 text-sm outline-none placeholder:text-stone-400"
          placeholder="Search a restaurant"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button onClick={() => setSearch('')} className="text-stone-300 text-xs">✕</button>
        )}
      </div>

      {/* Cuisine filters — dynamic */}
      <div className="flex gap-2 overflow-x-auto pb-1 mb-4">
        <button
          onClick={() => setSelectedCuisine(null)}
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            !selectedCuisine ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600'
          }`}
        >All</button>
        {cuisines.map((c) => (
          <button
            key={c}
            onClick={() => setSelectedCuisine(selectedCuisine === c ? null : c)}
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              selectedCuisine === c ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600'
            }`}
          >{c}</button>
        ))}
      </div>

      {/* List label */}
      <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
        {search || selectedCuisine ? `${filtered.length} result${filtered.length !== 1 ? 's' : ''}` : 'Restaurants'}
      </p>

      {/* Restaurant list */}
      <div>
        {filtered.map((r, i) => (
          <Link key={r.id} href={`/restaurant/${r.id}`}>
            <RestaurantCard restaurant={r} isLast={i === filtered.length - 1} />
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

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

---

## Task 4: Update `RestaurantCard.tsx` — All 3 Fees Inline

**Files:**
- Modify: `components/RestaurantCard.tsx`
- Create: `__tests__/restaurant-card.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `__tests__/restaurant-card.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RestaurantCard from '../components/RestaurantCard'
import type { RestaurantSummary } from '../lib/queries'

const threeListings: RestaurantSummary = {
  id: '1',
  name: "McDonald's",
  cuisine: ['Burgers'],
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 49 },
    { platform: 'deliveroo', delivery_fee_cents: 149 },
    { platform: 'takeaway', delivery_fee_cents: 199 },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€0.49', savings_cents: 150 },
}

const oneListing: RestaurantSummary = {
  id: '2',
  name: 'Pizza Hut',
  cuisine: ['Pizza'],
  listings: [
    { platform: 'deliveroo', delivery_fee_cents: 199 },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€1.99', savings_cents: 0 },
}

const nullFees: RestaurantSummary = {
  id: '3',
  name: 'Sushi Place',
  cuisine: ['Asian'],
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: null },
    { platform: 'deliveroo', delivery_fee_cents: 299 },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€2.99', savings_cents: 0 },
}

describe('RestaurantCard', () => {
  it('shows all 3 platform fees when 3 listings exist', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByText('€0.49')).toBeInTheDocument()
    expect(screen.getByText('€1.49')).toBeInTheDocument()
    expect(screen.getByText('€1.99')).toBeInTheDocument()
  })

  it('shows cheapest fee in bold (font-semibold class)', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    const cheapestEl = screen.getByText('€0.49')
    expect(cheapestEl).toHaveClass('font-semibold')
  })

  it('shows restaurant name', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByText("McDonald's")).toBeInTheDocument()
  })

  it('skips platforms with null delivery fee', () => {
    render(<RestaurantCard restaurant={nullFees} />)
    expect(screen.getByText('€2.99')).toBeInTheDocument()
    expect(screen.queryByText('—')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```

Expected: FAIL — `RestaurantCard` doesn't have `listings` prop in its type yet.

- [ ] **Step 3: Rewrite `RestaurantCard.tsx`**

Replace the entire file:

```tsx
import { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_COLORS, type Platform } from '@/lib/basket'

type Props = {
  restaurant: RestaurantSummary
  isLast?: boolean
}

export default function RestaurantCard({ restaurant, isLast }: Props) {
  const { name, cuisine, listings, cheapest } = restaurant

  const sortedListings = [...listings]
    .filter((l) => l.delivery_fee_cents !== null)
    .sort((a, b) => a.delivery_fee_cents! - b.delivery_fee_cents!)

  return (
    <div className={`py-4 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900">{name}</p>
          <p className="text-xs text-stone-400 mt-0.5">{cuisine.join(' · ')}</p>
        </div>
        <span className="text-stone-300 text-xs ml-4 shrink-0 mt-0.5">›</span>
      </div>
      {sortedListings.length > 0 && (
        <div className="flex gap-3 mt-2">
          {sortedListings.map((l) => {
            const isCheapest = l.platform === cheapest?.platform
            const colors = PLATFORM_COLORS[l.platform as Platform]
            return (
              <span
                key={l.platform}
                className={`flex items-center gap-1 text-xs ${
                  isCheapest
                    ? 'font-semibold text-stone-900'
                    : 'text-stone-400'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
                {centsToEuro(l.delivery_fee_cents)}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```

Expected: 4 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

---

## Task 5: Detail Page — Rating in Header

**Files:**
- Modify: `app/restaurant/[id]/page.tsx`

- [ ] **Step 1: Add rating derivation and display**

Replace the entire file:

```tsx
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

  const bestRating = data.listings
    .map((l) => l.rating)
    .filter((r): r is number => r !== null)
    .sort((a, b) => b - a)[0] ?? null

  return (
    <div className="max-w-md mx-auto">
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <Link href="/" className="text-stone-500 hover:text-stone-800 text-lg mr-auto">‹</Link>
        <span className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </span>
      </div>

      {/* Restaurant info */}
      <div className="px-5 pb-4">
        <h1 className="text-2xl font-bold text-stone-900 mt-2">{data.name}</h1>
        <p className="text-sm text-stone-400 mt-1">
          {data.cuisine.join(' · ')} · {data.city}
          {bestRating !== null && ` · ★ ${bestRating.toFixed(1)}`}
        </p>
      </div>

      <BasketSimulator menuItems={data.menuItems} listings={data.listings} />
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

---

## Task 6: Create `StickyOrderBar.tsx`

**Files:**
- Create: `components/StickyOrderBar.tsx`
- Create: `__tests__/sticky-order-bar.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `__tests__/sticky-order-bar.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StickyOrderBar from '../components/StickyOrderBar'

describe('StickyOrderBar', () => {
  it('renders nothing when platform is null', () => {
    const { container } = render(
      <StickyOrderBar platform={null} total={648} platformUrl="https://example.com" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when total is null', () => {
    const { container } = render(
      <StickyOrderBar platform="uber_eats" total={null} platformUrl="https://example.com" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders platform name and total', () => {
    render(
      <StickyOrderBar platform="uber_eats" total={648} platformUrl="https://example.com" />
    )
    expect(screen.getByText('Order on Uber Eats')).toBeInTheDocument()
    expect(screen.getByText('€6.48')).toBeInTheDocument()
  })

  it('renders as a link when platformUrl is provided', () => {
    render(
      <StickyOrderBar platform="deliveroo" total={768} platformUrl="https://deliveroo.be/test" />
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', 'https://deliveroo.be/test')
  })

  it('renders as non-interactive div when platformUrl is null', () => {
    render(
      <StickyOrderBar platform="takeaway" total={500} platformUrl={null} />
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Order on Takeaway')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd forkeur-app && npx vitest run __tests__/sticky-order-bar.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create `components/StickyOrderBar.tsx`**

```tsx
'use client'
import { Platform, PLATFORM_LABELS, PLATFORM_COLORS, centsToEuro } from '@/lib/basket'

type Props = {
  platform: Platform | null
  total: number | null
  platformUrl: string | null
}

export default function StickyOrderBar({ platform, total, platformUrl }: Props) {
  if (!platform || total === null) return null

  const colors = PLATFORM_COLORS[platform]

  const inner = (
    <div
      className="flex items-center justify-between px-5 py-4 bg-blue-600"
      style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))' }}
    >
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
        <span className="text-sm font-semibold text-white">
          Order on {PLATFORM_LABELS[platform]}
        </span>
      </div>
      <span className="text-sm font-semibold text-white">{centsToEuro(total)}</span>
    </div>
  )

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 flex justify-center pointer-events-none">
      <div className="w-full max-w-md pointer-events-auto">
        {platformUrl ? (
          <a
            href={platformUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="block hover:opacity-90 transition-opacity"
          >
            {inner}
          </a>
        ) : (
          <div className="opacity-60 cursor-not-allowed">{inner}</div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd forkeur-app && npx vitest run __tests__/sticky-order-bar.test.tsx
```

Expected: 5 tests pass.

---

## Task 7: Update `BasketSimulator.tsx` — Wire StickyOrderBar + Swipe

**Files:**
- Modify: `components/BasketSimulator.tsx`

- [ ] **Step 1: Add StickyOrderBar import and remove inline CTA**

In `components/BasketSimulator.tsx`:

1. Add import at top:
```tsx
import StickyOrderBar from './StickyOrderBar'
import { useRef } from 'react'
```

2. Add `swipeRef` after existing `useState` hooks:
```tsx
const swipeRef = useRef<{ startX: number; startY: number } | null>(null)
```

3. Replace the basket summary chip div (the `{basket.length > 0 && (` block at the top) with swipe handlers:

```tsx
{basket.length > 0 && (
  <div
    className="flex items-center justify-between mb-4 py-2.5 border-b border-stone-100 cursor-grab active:cursor-grabbing"
    onPointerDown={(e) => {
      swipeRef.current = { startX: e.clientX, startY: e.clientY }
    }}
    onPointerMove={(e) => {
      if (!swipeRef.current) return
      const dy = Math.abs(e.clientY - swipeRef.current.startY)
      if (dy > 20) { swipeRef.current = null; return }
      if (e.clientX - swipeRef.current.startX < -80) {
        setBasket([])
        swipeRef.current = null
      }
    }}
    onPointerUp={() => { swipeRef.current = null }}
    onPointerCancel={() => { swipeRef.current = null }}
  >
    <p className="text-xs text-stone-500 truncate pr-3">{basketLabel}</p>
    <button
      onClick={() => setBasket([])}
      className="text-xs text-stone-400 hover:text-stone-700 shrink-0"
    >
      Clear
    </button>
  </div>
)}
```

4. Find the existing inline CTA block inside the recommendation section — the `<div className="mt-6">` block containing the `<a>` and `<div>` "Order on X →" buttons. Delete that entire block:

```tsx
{/* DELETE this entire block: */}
<div className="mt-6">
  {cheapestPlatform && platformUrls[cheapestPlatform] ? (
    <a ... >Order on {PLATFORM_LABELS[cheapestPlatform]} →</a>
  ) : (
    cheapestPlatform && (
      <div ...>Order on {PLATFORM_LABELS[cheapestPlatform]} →</div>
    )
  )}
  <p className="text-[11px] text-stone-400 text-center mt-2">
    Fees included · updated just now
  </p>
</div>
```

5. Add `StickyOrderBar` and content padding at the bottom of the returned JSX, just before the closing `</div>` of `<div className="px-5">`:

```tsx
      </div> {/* closes recommendation section */}
    )}

    <StickyOrderBar
      platform={cheapestPlatform}
      total={cheapestTotal}
      platformUrl={cheapestPlatform ? platformUrls[cheapestPlatform] ?? null : null}
    />

    {/* Bottom padding so content clears the sticky bar */}
    {basket.length > 0 && cheapestPlatform && <div className="h-24" />}
  </div>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Run full test suite**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass.

---

## Task 8: Upgrade `loading.tsx` — Full Skeleton

**Files:**
- Modify: `app/restaurant/[id]/loading.tsx`

- [ ] **Step 1: Replace with structured skeleton**

Replace the entire file:

```tsx
export default function Loading() {
  return (
    <div className="max-w-md mx-auto">
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <div className="w-4 h-4 bg-stone-100 rounded animate-pulse mr-auto" />
        <div className="w-16 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Restaurant header */}
      <div className="px-5 pb-4 mt-2">
        <div className="w-44 h-7 bg-stone-100 rounded animate-pulse mb-2" />
        <div className="w-36 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      <div className="px-5">
        {/* "BEST RIGHT NOW" label */}
        <div className="w-24 h-2.5 bg-stone-100 rounded animate-pulse mb-3" />

        {/* Platform name */}
        <div className="w-40 h-8 bg-stone-100 rounded animate-pulse mb-1" />
        <div className="w-48 h-4 bg-stone-100 rounded animate-pulse mb-5" />

        {/* Metrics row */}
        <div className="flex gap-6 mb-5">
          {[0, 1, 2].map((i) => (
            <div key={i}>
              <div className="w-14 h-6 bg-stone-100 rounded animate-pulse mb-1" />
              <div className="w-10 h-2.5 bg-stone-100 rounded animate-pulse" />
            </div>
          ))}
        </div>

        {/* Compare rows */}
        <div className="border-t border-stone-100 pt-4">
          <div className="w-28 h-4 bg-stone-100 rounded animate-pulse mb-4" />
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="flex items-center justify-between py-3 border-b border-stone-100"
            >
              <div className="w-24 h-4 bg-stone-100 rounded animate-pulse" />
              <div className="w-12 h-4 bg-stone-100 rounded animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
```

---

## Task 9: Safe Area — `layout.tsx`

**Files:**
- Modify: `app/layout.tsx`

- [ ] **Step 1: Add `Viewport` export**

Read the current `app/layout.tsx` and add the viewport export. Add after any existing imports:

```ts
import type { Viewport } from 'next'

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
}
```

If `layout.tsx` already exports `metadata`, keep it — just add `viewport` alongside it.

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd forkeur-app && npx tsc --noEmit
```

Expected: no errors.

---

## Task 10: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass (basket tests + restaurant-card tests + sticky-order-bar tests).

- [ ] **Step 2: Start dev server and check homepage**

```bash
cd forkeur-app && npm run dev
```

Open http://localhost:3000. Verify:
- If restaurants in DB: cards show platform fee dots inline, cheapest bold
- Cuisine chips are dynamic (from DB data, not hardcoded)
- If no DB data: empty state shows correctly

- [ ] **Step 3: Check restaurant detail page**

Navigate to any restaurant. Verify:
- Rating shown in subtitle if available (`★ X.X`)
- Sticky order bar appears at bottom when items added to basket
- Swipe left on the basket chip clears it
- Content doesn't hide behind sticky bar (padding present)
- Skeleton shows correctly on slow network (use DevTools throttling)

- [ ] **Step 4: Check mobile safe area (iOS simulator or real device)**

Verify sticky bar doesn't overlap iOS home indicator.
