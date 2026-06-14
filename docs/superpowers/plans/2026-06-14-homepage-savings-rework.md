# Homepage Savings Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Forkeur homepage into a savings-led comparison product with honest, data-gated proof blocks and cleaner card design.

**Architecture:** Extract HeroBlock and FeedHeader as new `'use client'` components; centralize all savings math in `lib/savings.ts`; edit HomepageClient and RestaurantCard in-place. Every saving figure rendered only when functions return non-null from real data — no hardcoding, no faking.

**Tech Stack:** Next.js 15 App Router, React, next-intl (EN/FR/NL), vitest, @testing-library/react, TypeScript

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `forkeur-app/lib/savings.ts` | `effectiveTotal`, `savingsVsNext`, `findBestSavingExample` |
| Create | `forkeur-app/__tests__/savings.test.ts` | Unit tests for savings.ts |
| Create | `forkeur-app/components/HeroBlock.tsx` | Hero section: credibility + RIGHT NOW + neutrality |
| Create | `forkeur-app/__tests__/hero-block.test.tsx` | Tests for HeroBlock |
| Create | `forkeur-app/components/FeedHeader.tsx` | Sort pills + neighborhood label |
| Create | `forkeur-app/__tests__/feed-header.test.tsx` | Tests for FeedHeader |
| Modify | `forkeur-app/messages/en.json` | Add 11 new i18n keys |
| Modify | `forkeur-app/messages/fr.json` | Same 11 keys in French |
| Modify | `forkeur-app/messages/nl.json` | Same 11 keys in Dutch |
| Modify | `forkeur-app/components/HomepageClient.tsx` | Wire HeroBlock, FeedHeader, sort logic, nearYou logic |
| Modify | `forkeur-app/__tests__/homepage-client.test.tsx` | Update for removed `'best'` sort + new sections |
| Modify | `forkeur-app/components/RestaurantCard.tsx` | New collapsed state, green badge, loser trust fix |
| Modify | `forkeur-app/__tests__/restaurant-card.test.tsx` | Update for new card design |

---

### Task 1: `lib/savings.ts` — savings math utilities

**Files:**
- Create: `forkeur-app/lib/savings.ts`
- Create: `forkeur-app/__tests__/savings.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// forkeur-app/__tests__/savings.test.ts
import { describe, it, expect } from 'vitest'
import { effectiveTotal, savingsVsNext, findBestSavingExample } from '@/lib/savings'
import type { RestaurantSummary } from '@/lib/queries'
import type { Platform } from '@/lib/basket'

// --- effectiveTotal ---

describe('effectiveTotal', () => {
  it('returns null when delivery_fee_cents is null', () => {
    expect(effectiveTotal({ delivery_fee_cents: null, min_order_cents: null })).toBeNull()
  })

  it('returns fee alone when min_order is null', () => {
    expect(effectiveTotal({ delivery_fee_cents: 199, min_order_cents: null })).toBe(199)
  })

  it('returns fee + min_order when both present', () => {
    expect(effectiveTotal({ delivery_fee_cents: 199, min_order_cents: 1000 })).toBe(1199)
  })

  it('returns fee alone when min_order is 0', () => {
    expect(effectiveTotal({ delivery_fee_cents: 0, min_order_cents: 0 })).toBe(0)
  })
})

// --- savingsVsNext ---

type ListingStub = { platform: Platform; delivery_fee_cents: number | null; min_order_cents: number | null }

const ue: ListingStub = { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0 }
const dl: ListingStub = { platform: 'deliveroo', delivery_fee_cents: 299, min_order_cents: 0 }
const tw: ListingStub = { platform: 'takeaway', delivery_fee_cents: null, min_order_cents: null }

describe('savingsVsNext', () => {
  it('returns null when fewer than 2 non-null listings', () => {
    expect(savingsVsNext([ue, tw], 'uber_eats')).toBeNull()
  })

  it('returns delta and vs-platform when 2 non-null listings', () => {
    const result = savingsVsNext([ue, dl], 'uber_eats')
    expect(result).toEqual({ cents: 100, vs: 'deliveroo' })
  })

  it('returns null when effectiveTotals are equal', () => {
    const same = { platform: 'deliveroo' as Platform, delivery_fee_cents: 199, min_order_cents: 0 }
    expect(savingsVsNext([ue, same], 'uber_eats')).toBeNull()
  })

  it('picks cheapest as winner regardless of winnerPlatform arg', () => {
    // dl is more expensive; caller passes 'uber_eats' as winner (matches cheapest)
    const result = savingsVsNext([dl, ue], 'uber_eats')
    expect(result).toEqual({ cents: 100, vs: 'deliveroo' })
  })
})

// --- findBestSavingExample ---

function makeRestaurant(overrides: Partial<RestaurantSummary> = {}): RestaurantSummary {
  return {
    id: '1', name: 'Test', neighborhood: 'Ixelles', cuisine: [], lat: null, lng: null,
    order_url: null, image_url: null, rating: null, direct_url_type: null, is_chain: false,
    listings: [
      { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
      { platform: 'deliveroo', delivery_fee_cents: 299, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
    ],
    cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 100, delivery_fee_cents: 199, min_order_cents: 0 },
    ...overrides,
  }
}

describe('findBestSavingExample', () => {
  it('returns null for empty array', () => {
    expect(findBestSavingExample([])).toBeNull()
  })

  it('returns null when no restaurant has savings_cents > 0', () => {
    const r = makeRestaurant({ cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 0, delivery_fee_cents: 199, min_order_cents: 0 } })
    expect(findBestSavingExample([r])).toBeNull()
  })

  it('returns null when restaurant has fewer than 2 listings', () => {
    const r = makeRestaurant({
      listings: [{ platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null }],
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 200, delivery_fee_cents: 199, min_order_cents: 0 },
    })
    expect(findBestSavingExample([r])).toBeNull()
  })

  it('returns restaurant with highest savings_cents', () => {
    const low = makeRestaurant({ cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 50, delivery_fee_cents: 199, min_order_cents: 0 } })
    const high = makeRestaurant({ id: '2', name: 'Best', cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 300, delivery_fee_cents: 199, min_order_cents: 0 } })
    const result = findBestSavingExample([low, high])
    expect(result?.restaurant.id).toBe('2')
  })

  it('returns winner/loser/savingsCents breakdown', () => {
    const r = makeRestaurant()
    const result = findBestSavingExample([r])
    expect(result).not.toBeNull()
    expect(result!.savingsCents).toBe(100)
    expect(result!.winner.platform).toBe('uber_eats')
    expect(result!.loser.platform).toBe('deliveroo')
    expect(result!.winnerTotal).toBe(199)
    expect(result!.loserTotal).toBe(299)
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd forkeur-app && npx vitest run __tests__/savings.test.ts
```
Expected: `Cannot find module '@/lib/savings'`

- [ ] **Step 3: Implement `lib/savings.ts`**

```typescript
// forkeur-app/lib/savings.ts
import type { RestaurantSummary } from '@/lib/queries'
import type { Platform } from '@/lib/basket'

type ListingLike = { platform: Platform; delivery_fee_cents: number | null; min_order_cents: number | null }

export function effectiveTotal(listing: Pick<ListingLike, 'delivery_fee_cents' | 'min_order_cents'>): number | null {
  if (listing.delivery_fee_cents === null) return null
  return listing.delivery_fee_cents + (listing.min_order_cents ?? 0)
}

export function savingsVsNext(
  listings: ListingLike[],
  _winnerPlatform: Platform,
): { cents: number; vs: Platform } | null {
  const withTotal = listings
    .map(l => ({ ...l, total: effectiveTotal(l) }))
    .filter((l): l is typeof l & { total: number } => l.total !== null)
    .sort((a, b) => a.total - b.total)

  if (withTotal.length < 2) return null
  const delta = withTotal[1].total - withTotal[0].total
  if (delta <= 0) return null
  return { cents: delta, vs: withTotal[1].platform }
}

export type BestSavingExample = {
  restaurant: RestaurantSummary
  winner: ListingLike
  loser: ListingLike
  winnerTotal: number
  loserTotal: number
  savingsCents: number
}

export function findBestSavingExample(restaurants: RestaurantSummary[]): BestSavingExample | null {
  let best: BestSavingExample | null = null

  for (const r of restaurants) {
    if (!r.cheapest || r.cheapest.savings_cents <= 0 || r.listings.length < 2) continue

    const withTotal = r.listings
      .map(l => ({ ...l, total: effectiveTotal(l) }))
      .filter((l): l is typeof l & { total: number } => l.total !== null)
      .sort((a, b) => a.total - b.total)

    if (withTotal.length < 2) continue

    const savingsCents = withTotal[1].total - withTotal[0].total
    if (savingsCents <= 0) continue
    if (!best || savingsCents > best.savingsCents) {
      best = {
        restaurant: r,
        winner: withTotal[0],
        loser: withTotal[1],
        winnerTotal: withTotal[0].total,
        loserTotal: withTotal[1].total,
        savingsCents,
      }
    }
  }

  return best
}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd forkeur-app && npx vitest run __tests__/savings.test.ts
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/lib/savings.ts forkeur-app/__tests__/savings.test.ts
git commit -m "feat(savings): add effectiveTotal, savingsVsNext, findBestSavingExample"
```

---

### Task 2: i18n — add 11 keys to all 3 locale files

**Files:**
- Modify: `forkeur-app/messages/en.json`
- Modify: `forkeur-app/messages/fr.json`
- Modify: `forkeur-app/messages/nl.json`

All 3 files must be updated in one commit so `i18n-parity.test.ts` stays green.

- [ ] **Step 1: Write failing parity test (already exists — just run it first)**

```bash
cd forkeur-app && npx vitest run __tests__/i18n-parity.test.ts
```
Expected: PASS (baseline — no new keys yet)

- [ ] **Step 2: Add keys to `messages/en.json`**

In `en.json`, make the following additions (keep existing keys, add new ones):

In the `"hero"` object, add after `"live_badge"`:
```json
"credibility": "We compare {count} Brussels restaurants across 4 platforms.",
"rightNow": "Right now, {name} in {neighborhood} is {loserTotal} on {loserPlatform} but only {winnerTotal} on {winnerPlatform}.",
"neutrality": "We're independent — no affiliate fees, no rankings for sale."
```

In the `"search"` object, replace `"placeholder"` with (or add alongside):
```json
"hint": "Search by name or cuisine…"
```

In the `"results"` object, add:
```json
"biggestSavings": "Biggest savings near you"
```

In the `"card"` object, add:
```json
"cheapestOn": "Cheapest on {platform} · {fee}",
"saveVs": "Save {amount} vs {platform}",
"overpay": "+{amount} more here"
```

Add a new top-level `"feed"` namespace:
```json
"feed": {
  "savingsNear": "Savings in {commune}",
  "savingsNearAll": "Savings near you",
  "coverageFooter": "Comparing {count} restaurants in Brussels"
}
```

- [ ] **Step 3: Add keys to `messages/fr.json`**

In `"hero"`, add after `"live_badge"`:
```json
"credibility": "Nous comparons {count} restaurants bruxellois sur 4 plateformes.",
"rightNow": "En ce moment, {name} à {neighborhood} coûte {loserTotal} sur {loserPlatform} mais seulement {winnerTotal} sur {winnerPlatform}.",
"neutrality": "Nous sommes indépendants — pas de frais d'affiliation, pas de classements à vendre."
```

In `"search"`, add:
```json
"hint": "Rechercher par nom ou cuisine…"
```

In `"results"`, add:
```json
"biggestSavings": "Les plus grandes économies près de vous"
```

In `"card"`, add:
```json
"cheapestOn": "Le moins cher sur {platform} · {fee}",
"saveVs": "Économise {amount} vs {platform}",
"overpay": "+{amount} de plus ici"
```

Add new top-level `"feed"`:
```json
"feed": {
  "savingsNear": "Économies à {commune}",
  "savingsNearAll": "Économies près de vous",
  "coverageFooter": "Comparaison de {count} restaurants à Bruxelles"
}
```

- [ ] **Step 4: Add keys to `messages/nl.json`**

In `"hero"`, add after `"live_badge"`:
```json
"credibility": "We vergelijken {count} Brusselse restaurants op 4 platforms.",
"rightNow": "Nu kost {name} in {neighborhood} {loserTotal} op {loserPlatform} maar slechts {winnerTotal} op {winnerPlatform}.",
"neutrality": "We zijn onafhankelijk — geen affiliate kosten, geen te koop staande ranglijsten."
```

In `"search"`, add:
```json
"hint": "Zoek op naam of keuken…"
```

In `"results"`, add:
```json
"biggestSavings": "Grootste besparingen bij u in de buurt"
```

In `"card"`, add:
```json
"cheapestOn": "Goedkoopst op {platform} · {fee}",
"saveVs": "Bespaar {amount} vs {platform}",
"overpay": "+{amount} meer hier"
```

Add new top-level `"feed"`:
```json
"feed": {
  "savingsNear": "Besparingen in {commune}",
  "savingsNearAll": "Besparingen bij u in de buurt",
  "coverageFooter": "Vergelijking van {count} restaurants in Brussel"
}
```

- [ ] **Step 5: Run parity test to verify all 3 in sync**

```bash
cd forkeur-app && npx vitest run __tests__/i18n-parity.test.ts
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/messages/en.json forkeur-app/messages/fr.json forkeur-app/messages/nl.json
git commit -m "feat(i18n): add feed, hero.credibility/rightNow/neutrality, card savings keys"
```

---

### Task 3: `HeroBlock.tsx` — new hero component

**Files:**
- Create: `forkeur-app/components/HeroBlock.tsx`
- Create: `forkeur-app/__tests__/hero-block.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// forkeur-app/__tests__/hero-block.test.tsx
import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect } from 'vitest'
import en from '../messages/en.json'
import HeroBlock from '@/components/HeroBlock'
import type { RestaurantSummary } from '@/lib/queries'

function makeRestaurant(overrides: Partial<RestaurantSummary> = {}): RestaurantSummary {
  return {
    id: '1', name: 'Pasta Palace', neighborhood: 'Ixelles', cuisine: [], lat: null, lng: null,
    order_url: null, image_url: null, rating: null, direct_url_type: null, is_chain: false,
    listings: [
      { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
      { platform: 'deliveroo', delivery_fee_cents: 399, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
    ],
    cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 200, delivery_fee_cents: 199, min_order_cents: 0 },
    ...overrides,
  }
}

function wrap(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en as Record<string, unknown>}>
      {ui}
    </NextIntlClientProvider>
  )
}

describe('HeroBlock', () => {
  it('renders credibility line with restaurant count', () => {
    wrap(<HeroBlock restaurants={[makeRestaurant()]} />)
    expect(screen.getByText(/We compare 1 Brussels restaurant/i)).toBeInTheDocument()
  })

  it('renders neutrality line', () => {
    wrap(<HeroBlock restaurants={[makeRestaurant()]} />)
    expect(screen.getByText(/independent/i)).toBeInTheDocument()
  })

  it('renders RIGHT NOW block when savings example exists', () => {
    wrap(<HeroBlock restaurants={[makeRestaurant()]} />)
    expect(screen.getByText(/Pasta Palace/i)).toBeInTheDocument()
    expect(screen.getByText(/Ixelles/i)).toBeInTheDocument()
  })

  it('omits RIGHT NOW block when no savings example', () => {
    const noSavings = makeRestaurant({
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 0, delivery_fee_cents: 199, min_order_cents: 0 },
    })
    wrap(<HeroBlock restaurants={[noSavings]} />)
    expect(screen.queryByText(/Right now/i)).not.toBeInTheDocument()
  })

  it('omits RIGHT NOW block when restaurant list is empty', () => {
    wrap(<HeroBlock restaurants={[]} />)
    expect(screen.queryByText(/Right now/i)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd forkeur-app && npx vitest run __tests__/hero-block.test.tsx
```
Expected: `Cannot find module '@/components/HeroBlock'`

- [ ] **Step 3: Implement `HeroBlock.tsx`**

```typescript
// forkeur-app/components/HeroBlock.tsx
'use client'

import { useTranslations } from 'next-intl'
import { findBestSavingExample } from '@/lib/savings'
import { centsToEuro, PLATFORM_LABELS } from '@/lib/basket'
import type { RestaurantSummary } from '@/lib/queries'

export default function HeroBlock({ restaurants }: { restaurants: RestaurantSummary[] }) {
  const t = useTranslations('hero')
  const example = findBestSavingExample(restaurants)

  return (
    <div className="text-center py-8 px-4 space-y-4">
      <p className="text-sm text-stone-500">
        {t('credibility', { count: restaurants.length })}
      </p>

      {example && (
        <div className="bg-stone-50 border border-stone-200 rounded-xl px-5 py-4 inline-block text-left max-w-md mx-auto">
          <p className="text-xs font-semibold text-stone-400 uppercase tracking-wide mb-1">Right now</p>
          <p className="text-sm text-stone-700">
            {t('rightNow', {
              name: example.restaurant.name,
              neighborhood: example.restaurant.neighborhood ?? '',
              loserTotal: centsToEuro(example.loserTotal),
              loserPlatform: PLATFORM_LABELS[example.loser.platform],
              winnerTotal: centsToEuro(example.winnerTotal),
              winnerPlatform: PLATFORM_LABELS[example.winner.platform],
            })}
          </p>
        </div>
      )}

      <p className="text-xs text-stone-400">
        {t('neutrality')}
      </p>
    </div>
  )
}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd forkeur-app && npx vitest run __tests__/hero-block.test.tsx
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/HeroBlock.tsx forkeur-app/__tests__/hero-block.test.tsx
git commit -m "feat(hero): add HeroBlock with credibility, RIGHT NOW, neutrality"
```

---

### Task 4: `FeedHeader.tsx` — sort pills + neighborhood label

**Files:**
- Create: `forkeur-app/components/FeedHeader.tsx`
- Create: `forkeur-app/__tests__/feed-header.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// forkeur-app/__tests__/feed-header.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect, vi } from 'vitest'
import en from '../messages/en.json'
import FeedHeader from '@/components/FeedHeader'

function wrap(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en as Record<string, unknown>}>
      {ui}
    </NextIntlClientProvider>
  )
}

describe('FeedHeader', () => {
  it('shows "Savings near you" when no neighborhood selected', () => {
    wrap(
      <FeedHeader
        selectedNeighborhood={null}
        onChangeNeighborhood={vi.fn()}
        sortBy="cheapest"
        onSortChange={vi.fn()}
        restaurantCount={42}
      />
    )
    expect(screen.getByText(/Savings near you/i)).toBeInTheDocument()
  })

  it('shows commune name when neighborhood selected', () => {
    wrap(
      <FeedHeader
        selectedNeighborhood="Ixelles"
        onChangeNeighborhood={vi.fn()}
        sortBy="cheapest"
        onSortChange={vi.fn()}
        restaurantCount={10}
      />
    )
    expect(screen.getByText(/Savings in Ixelles/i)).toBeInTheDocument()
  })

  it('renders cheapest and fastest sort pills', () => {
    wrap(
      <FeedHeader
        selectedNeighborhood={null}
        onChangeNeighborhood={vi.fn()}
        sortBy="cheapest"
        onSortChange={vi.fn()}
        restaurantCount={5}
      />
    )
    expect(screen.getByRole('button', { name: /cheapest/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /fastest/i })).toBeInTheDocument()
  })

  it('does not render a "best" sort pill', () => {
    wrap(
      <FeedHeader
        selectedNeighborhood={null}
        onChangeNeighborhood={vi.fn()}
        sortBy="cheapest"
        onSortChange={vi.fn()}
        restaurantCount={5}
      />
    )
    expect(screen.queryByRole('button', { name: /best/i })).not.toBeInTheDocument()
  })

  it('calls onSortChange when fastest pill clicked', () => {
    const onSortChange = vi.fn()
    wrap(
      <FeedHeader
        selectedNeighborhood={null}
        onChangeNeighborhood={vi.fn()}
        sortBy="cheapest"
        onSortChange={onSortChange}
        restaurantCount={5}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: /fastest/i }))
    expect(onSortChange).toHaveBeenCalledWith('fastest')
  })

  it('calls onChangeNeighborhood when label clicked', () => {
    const onChangeNeighborhood = vi.fn()
    wrap(
      <FeedHeader
        selectedNeighborhood={null}
        onChangeNeighborhood={onChangeNeighborhood}
        sortBy="cheapest"
        onSortChange={vi.fn()}
        restaurantCount={5}
      />
    )
    fireEvent.click(screen.getByText(/Savings near you/i))
    expect(onChangeNeighborhood).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd forkeur-app && npx vitest run __tests__/feed-header.test.tsx
```
Expected: `Cannot find module '@/components/FeedHeader'`

- [ ] **Step 3: Implement `FeedHeader.tsx`**

```typescript
// forkeur-app/components/FeedHeader.tsx
'use client'

import { useTranslations } from 'next-intl'

export type SortBy = 'cheapest' | 'fastest'

const SORT_PILLS: { key: SortBy; label: string }[] = [
  { key: 'cheapest', label: 'sort.cheapest' },
  { key: 'fastest', label: 'sort.fastest' },
]

interface FeedHeaderProps {
  selectedNeighborhood: string | null
  onChangeNeighborhood: () => void
  sortBy: SortBy
  onSortChange: (s: SortBy) => void
  restaurantCount: number
}

export default function FeedHeader({
  selectedNeighborhood,
  onChangeNeighborhood,
  sortBy,
  onSortChange,
}: FeedHeaderProps) {
  const tFeed = useTranslations('feed')
  const tSort = useTranslations('sort')

  const label = selectedNeighborhood
    ? tFeed('savingsNear', { commune: selectedNeighborhood })
    : tFeed('savingsNearAll')

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2">
      <button
        onClick={onChangeNeighborhood}
        className="text-base font-semibold text-stone-800 hover:text-orange-600 transition-colors text-left"
      >
        {label}
      </button>

      <div className="flex gap-1">
        {SORT_PILLS.map(({ key, label: labelKey }) => (
          <button
            key={key}
            onClick={() => onSortChange(key)}
            className={[
              'px-3 py-1 rounded-full text-xs font-medium transition-colors',
              sortBy === key
                ? 'bg-orange-500 text-white'
                : 'bg-stone-100 text-stone-600 hover:bg-stone-200',
            ].join(' ')}
          >
            {tSort(labelKey.replace('sort.', '') as 'cheapest' | 'fastest')}
          </button>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd forkeur-app && npx vitest run __tests__/feed-header.test.tsx
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/FeedHeader.tsx forkeur-app/__tests__/feed-header.test.tsx
git commit -m "feat(feed): add FeedHeader with sort pills and neighborhood label"
```

---

### Task 5: `HomepageClient.tsx` — wire everything together

**Files:**
- Modify: `forkeur-app/components/HomepageClient.tsx`
- Modify: `forkeur-app/__tests__/homepage-client.test.tsx`

- [ ] **Step 1: Write failing tests first**

Open `forkeur-app/__tests__/homepage-client.test.tsx`. Add these tests (keep all existing ones):

```typescript
// Add to existing homepage-client.test.tsx describe block

it('default sort is cheapest, not best', () => {
  // Check there is no selected state on "best" — just verify "cheapest" pill is active
  // (actual pill rendering is in FeedHeader; here we check sort logic)
  // Make restaurant A have higher savings than B
  const highSavings = makeRestaurant({ id: 'a', cheapest: { platform: 'uber_eats', fee_label: '€0', savings_cents: 500, delivery_fee_cents: 0, min_order_cents: 0 } })
  const lowSavings  = makeRestaurant({ id: 'b', cheapest: { platform: 'uber_eats', fee_label: '€2', savings_cents: 50,  delivery_fee_cents: 200, min_order_cents: 0 } })
  render(wrap(<HomepageClient restaurants={[lowSavings, highSavings]} userLocation={null} />))
  const cards = screen.getAllByTestId('restaurant-card')
  expect(cards[0]).toHaveAttribute('data-id', 'a')
})

it('does not render "How it works" section', () => {
  render(wrap(<HomepageClient restaurants={[makeRestaurant()]} userLocation={null} />))
  expect(screen.queryByText(/How it works/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/Choose your meal/i)).not.toBeInTheDocument()
})

it('renders coverage footer with restaurant count', () => {
  render(wrap(<HomepageClient restaurants={[makeRestaurant(), makeRestaurant({ id: '2' })]} userLocation={null} />))
  expect(screen.getByText(/Comparing 2 restaurants/i)).toBeInTheDocument()
})
```

Note: `RestaurantCard` needs `data-testid="restaurant-card"` and `data-id={id}` — add those in Task 6.

- [ ] **Step 2: Run to verify failure**

```bash
cd forkeur-app && npx vitest run __tests__/homepage-client.test.tsx
```
Expected: new tests FAIL, existing tests PASS (or at worst have minor breakage from the refactor below)

- [ ] **Step 3: Edit `HomepageClient.tsx`**

Apply the following changes to `forkeur-app/components/HomepageClient.tsx`:

**3a. Update imports** (top of file):
```typescript
// Add:
import HeroBlock from '@/components/HeroBlock'
import FeedHeader, { type SortBy } from '@/components/FeedHeader'
// Remove: import for howItWorks translations (tHowItWorks)
```

**3b. Change `SortBy` type** (line ~16):
```typescript
// Remove:
type SortBy = 'best' | 'cheapest' | 'fastest'
// (SortBy is now imported from FeedHeader)
```

**3c. Change default sort state** (line ~63):
```typescript
// Change:
const [sortBy, setSortBy] = useState<SortBy>('best')
// To:
const [sortBy, setSortBy] = useState<SortBy>('cheapest')
```

**3d. Remove `tHowItWorks` hook** (line ~88):
```typescript
// Remove this line:
const tHowItWorks = useTranslations('howItWorks')
```

**3e. Add `tFeed` hook** (after existing `useTranslations` calls):
```typescript
const tFeed = useTranslations('feed')
```

**3f. Update `'cheapest'` sort branch** (lines ~127-143):
```typescript
// Change the 'cheapest' case from:
case 'cheapest':
  return [...restaurants].sort((a, b) => {
    const aFee = a.cheapest?.delivery_fee_cents ?? Infinity
    const bFee = b.cheapest?.delivery_fee_cents ?? Infinity
    return aFee - bFee
  })
// To:
case 'cheapest':
  return [...restaurants].sort(
    (a, b) => (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0)
  )
```

**3g. Update nearYou logic** (lines ~158-165):
```typescript
// Change from top-3-by-distance to top-20-by-distance → sort-by-savings → top-3:
const nearYou = userLocation
  ? [...filtered]
      .sort((a, b) => haversine(userLocation, a) - haversine(userLocation, b))
      .slice(0, 20)
      .sort((a, b) => (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0))
      .slice(0, 3)
  : []
```

**3h. Replace live_badge + h1 + subtitle with HeroBlock** (lines ~217-227):
```typescript
// Remove:
{/* live badge, h1, subtitle paragraph */}
// Replace with:
<HeroBlock restaurants={restaurants} />
```

**3i. Remove "How it works" section** (lines ~270-288):
```typescript
// Delete entire section: the <section> or <div> containing "How it works", "Choose your meal", etc.
```

**3j. Replace toolbar with FeedHeader** (lines ~291-338):
```typescript
// Remove: existing sort pills + area filter toolbar
// Replace with:
<FeedHeader
  selectedNeighborhood={selectedNeighborhood}
  onChangeNeighborhood={() => setNeighborhoodSheetOpen(true)}
  sortBy={sortBy}
  onSortChange={(s) => { resetPage(); setSortBy(s) }}
  restaurantCount={restaurants.length}
/>
```

**3k. Reposition search input** — move `<input>` for search to appear immediately after `<FeedHeader>` (before the card list). Update placeholder:
```typescript
// Change placeholder prop from existing value to:
placeholder={tSearch('hint')}
```

**3l. Change nearYou section heading** (line ~350):
```typescript
// Change:
{tResults('popular')}
// To:
{tResults('biggestSavings')}
```

**3m. Add coverage footer** — after the card list closing tag, before `</main>` or equivalent wrapper:
```typescript
<p className="text-center text-xs text-stone-400 py-6">
  {tFeed('coverageFooter', { count: restaurants.length })}
</p>
```

- [ ] **Step 4: Run to verify pass**

```bash
cd forkeur-app && npx vitest run __tests__/homepage-client.test.tsx
```
Expected: all tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd forkeur-app && npx vitest run
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/components/HomepageClient.tsx forkeur-app/__tests__/homepage-client.test.tsx
git commit -m "feat(homepage): wire HeroBlock, FeedHeader, savings sort, coverage footer"
```

---

### Task 6: `RestaurantCard.tsx` — new collapsed state, green badge, loser trust fix

**Files:**
- Modify: `forkeur-app/components/RestaurantCard.tsx`
- Modify: `forkeur-app/__tests__/restaurant-card.test.tsx`

- [ ] **Step 1: Write failing tests**

Open `forkeur-app/__tests__/restaurant-card.test.tsx`. Add these tests (keep existing ones):

```typescript
// Add to existing restaurant-card.test.tsx

it('collapsed: shows cheapestOn line', () => {
  render(wrap(
    <RestaurantCard restaurant={makeRestaurant({
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 100, delivery_fee_cents: 199, min_order_cents: 0 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
        { platform: 'deliveroo', delivery_fee_cents: 299, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
      ],
    })} />
  ))
  expect(screen.getByText(/Cheapest on Uber Eats/i)).toBeInTheDocument()
})

it('collapsed: shows saveVs line when savings > 0', () => {
  render(wrap(
    <RestaurantCard restaurant={makeRestaurant({
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 100, delivery_fee_cents: 199, min_order_cents: 0 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
        { platform: 'deliveroo', delivery_fee_cents: 299, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
      ],
    })} />
  ))
  expect(screen.getByText(/Save €1\.00 vs Deliveroo/i)).toBeInTheDocument()
})

it('collapsed: omits saveVs when listings have equal effective total', () => {
  render(wrap(
    <RestaurantCard restaurant={makeRestaurant({
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 0, delivery_fee_cents: 199, min_order_cents: 0 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
        { platform: 'deliveroo', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
      ],
    })} />
  ))
  expect(screen.queryByText(/Save/i)).not.toBeInTheDocument()
})

it('expanded loser tile shows overpay amount in red', async () => {
  render(wrap(
    <RestaurantCard restaurant={makeRestaurant({
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 100, delivery_fee_cents: 199, min_order_cents: 0 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
        { platform: 'deliveroo', delivery_fee_cents: 299, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
      ],
    })} />
  ))
  // expand card
  fireEvent.click(screen.getByText(/Compare all/i))
  expect(await screen.findByText(/\+€1\.00 more here/i)).toBeInTheDocument()
})
```

(`fireEvent` and `makeRestaurant` should already be imported in the existing test file.)

- [ ] **Step 2: Run to verify failure**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```
Expected: new tests FAIL

- [ ] **Step 3: Edit `RestaurantCard.tsx`**

**3a. Add imports** at top:
```typescript
import { effectiveTotal, savingsVsNext } from '@/lib/savings'
```

**3b. Add `data-testid` and `data-id` to card root element** (for HomepageClient tests):
```typescript
// Find the outermost <div> or <article> of the card and add:
data-testid="restaurant-card"
data-id={restaurant.id}
```

**3c. Replace collapsed fee display** (lines ~70-73). Replace the current "from €X" block with:
```typescript
{cheapest && (
  <div className="text-right leading-tight">
    <p className="text-xs text-stone-600">
      {tCard('cheapestOn', {
        platform: PLATFORM_LABELS[cheapest.platform],
        fee: centsToEuro(cheapest.delivery_fee_cents),
      })}
    </p>
    {(() => {
      const vsResult = savingsVsNext(restaurant.listings, cheapest.platform)
      return vsResult && vsResult.cents > 0 ? (
        <p className="text-xs font-semibold text-green-600">
          {tCard('saveVs', {
            amount: centsToEuro(vsResult.cents),
            platform: PLATFORM_LABELS[vsResult.vs],
          })}
        </p>
      ) : null
    })()}
  </div>
)}
```

**3d. Change CHEAPEST badge color** (line ~121):
```typescript
// Change:
className="... bg-orange-500 ..."
// To:
className="... bg-green-500 ..."
```

**3e. Fix expanded loser tile** — in the expanded listings section, find where loser rows are rendered. For each loser listing `l` (not the cheapest platform), replace the raw fee headline with:

```typescript
{(() => {
  const cheapestTotal = cheapest ? effectiveTotal(cheapest) : null
  const loserTotal = effectiveTotal(l)
  const overpay = cheapestTotal !== null && loserTotal !== null ? loserTotal - cheapestTotal : null
  return (
    <>
      {overpay !== null && overpay > 0 && (
        <span className="text-xs font-semibold text-red-600">
          {tCard('overpay', { amount: centsToEuro(overpay) })}
        </span>
      )}
      <span className="text-xs text-stone-400">
        {centsToEuro(l.delivery_fee_cents)} delivery
        {l.min_order_cents ? ` · €${(l.min_order_cents / 100).toFixed(2)} min` : ''}
      </span>
    </>
  )
})()}
```

Gate: only render `overpay` span when `overpay !== null && overpay > 0`. The `effectiveTotal(cheapest)` call uses the cheapest listing object from `restaurant.listings.find(l => l.platform === cheapest.platform)`.

Full loser-tile fee area replacement:
```typescript
{(() => {
  const cheapestListing = cheapest
    ? restaurant.listings.find(li => li.platform === cheapest.platform) ?? null
    : null
  const cheapestTotal = cheapestListing ? effectiveTotal(cheapestListing) : null
  const loserTotal = effectiveTotal(l)
  const overpay = cheapestTotal !== null && loserTotal !== null && loserTotal > cheapestTotal
    ? loserTotal - cheapestTotal
    : null
  return (
    <div className="flex flex-col items-end">
      {overpay !== null && (
        <span className="text-xs font-semibold text-red-600">
          {tCard('overpay', { amount: centsToEuro(overpay) })}
        </span>
      )}
      <span className="text-xs text-stone-400">
        {centsToEuro(l.delivery_fee_cents)} delivery
        {l.min_order_cents ? ` · min €${(l.min_order_cents / 100).toFixed(2)}` : ''}
      </span>
    </div>
  )
})()}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```
Expected: all tests PASS

- [ ] **Step 5: Run full suite**

```bash
cd forkeur-app && npx vitest run
```
Expected: all tests PASS. TypeScript check:
```bash
cd forkeur-app && npx tsc --noEmit
```
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/components/RestaurantCard.tsx forkeur-app/__tests__/restaurant-card.test.tsx
git commit -m "feat(card): savings-led collapsed state, green badge, loser overpay trust fix"
```

---

## Post-Implementation Checklist

- [ ] `npx vitest run` — all suites green
- [ ] `npx tsc --noEmit` — no type errors
- [ ] Start dev server (`cd forkeur-app && npm run dev -- --port 30000`) and visually verify:
  - Hero credibility line renders with real count
  - RIGHT NOW block appears (or is absent when no savings data)
  - Feed sort pills show only "Cheapest" and "Fastest" (no "Best")
  - Card collapsed state shows "Cheapest on X · €Y" + green "Save €Z vs W"
  - Card badge is green not orange
  - Expanded loser tile shows red "+€X more here"
  - Coverage footer appears at bottom of list
