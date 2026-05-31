# Forkeur Frontend Polish + Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign homepage RestaurantCard to 3-col platform fee grid, fix StickyOrderBar theme (blue→stone+accent), add homepage loading skeleton, and remove dead dark-mode CSS.

**Architecture:** All changes are in `forkeur-app/`. No data layer or backend changes. Components receive existing props — only render logic and styles change. New `app/loading.tsx` is a pure skeleton (no data fetching).

**Tech Stack:** Next.js 15 App Router, React, Tailwind CSS v4, Vitest + Testing Library

---

## File Map

| Action | File |
|--------|------|
| Modify | `forkeur-app/components/RestaurantCard.tsx` |
| Modify | `forkeur-app/__tests__/restaurant-card.test.tsx` |
| Modify | `forkeur-app/components/StickyOrderBar.tsx` |
| Modify | `forkeur-app/__tests__/sticky-order-bar.test.tsx` |
| Create | `forkeur-app/app/loading.tsx` |
| Modify | `forkeur-app/app/globals.css` |

---

### Task 1: Update RestaurantCard tests for 3-col grid

**Files:**
- Modify: `forkeur-app/__tests__/restaurant-card.test.tsx`

The existing tests check for `font-semibold` on the cheapest fee. New design uses tile opacity (`opacity-50` on non-cheapest tiles wrapping containers, not the text itself). Update tests to match new DOM structure before touching the component — this is TDD red phase.

- [ ] **Step 1: Update the test for "cheapest fee bold" → "cheapest tile full opacity"**

Replace the `font-semibold` test. New component will wrap each platform in a tile `<div>` with `data-cheapest="true"` on the best tile. Test that attribute instead of a CSS class (more stable than class names).

Open `forkeur-app/__tests__/restaurant-card.test.tsx` and replace the full file content with:

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

const freeListing: RestaurantSummary = {
  id: '4',
  name: 'Burger King',
  cuisine: ['Fast food'],
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 0 },
    { platform: 'deliveroo', delivery_fee_cents: 99 },
    { platform: 'takeaway', delivery_fee_cents: 149 },
  ],
  cheapest: { platform: 'uber_eats', fee_label: 'Free', savings_cents: 149 },
}

describe('RestaurantCard', () => {
  it('shows all 3 platform fees when 3 listings exist', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByText('€0.49')).toBeInTheDocument()
    expect(screen.getByText('€1.49')).toBeInTheDocument()
    expect(screen.getByText('€1.99')).toBeInTheDocument()
  })

  it('marks cheapest tile with data-cheapest attribute', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    const tile = screen.getByTestId('fee-tile-uber_eats')
    expect(tile).toHaveAttribute('data-cheapest', 'true')
  })

  it('non-cheapest tiles do not have data-cheapest=true', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByTestId('fee-tile-deliveroo')).not.toHaveAttribute('data-cheapest', 'true')
    expect(screen.getByTestId('fee-tile-takeaway')).not.toHaveAttribute('data-cheapest', 'true')
  })

  it('shows restaurant name', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByText("McDonald's")).toBeInTheDocument()
  })

  it('skips platforms with null delivery fee', () => {
    render(<RestaurantCard restaurant={nullFees} />)
    expect(screen.getByText('€2.99')).toBeInTheDocument()
    expect(screen.queryByTestId('fee-tile-uber_eats')).toBeNull()
  })

  it('shows Free for zero-cent delivery fee', () => {
    render(<RestaurantCard restaurant={freeListing} />)
    expect(screen.getByText('Free')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```

Expected: 3–4 failures (`data-cheapest` attribute not found, `fee-tile-*` testids missing). If all pass, the test is wrong — investigate before continuing.

---

### Task 2: Implement 3-col fee grid in RestaurantCard

**Files:**
- Modify: `forkeur-app/components/RestaurantCard.tsx`

- [ ] **Step 1: Replace RestaurantCard implementation**

Open `forkeur-app/components/RestaurantCard.tsx` and replace the full file with:

```tsx
import { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_COLORS, type Platform } from '@/lib/basket'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
}

type Props = {
  restaurant: RestaurantSummary
  isLast?: boolean
}

export default function RestaurantCard({ restaurant, isLast }: Props) {
  const { name, cuisine, listings, cheapest } = restaurant

  const tiles = listings.filter((l) => l.delivery_fee_cents !== null)

  return (
    <div className={`py-4 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900">{name}</p>
          <p className="text-xs text-stone-400 mt-0.5">{cuisine.join(' · ')}</p>
        </div>
        <span className="text-stone-300 text-xs ml-4 shrink-0 mt-0.5">›</span>
      </div>

      {tiles.length > 0 && (
        <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${tiles.length}, 1fr)` }}>
          {tiles.map((l) => {
            const isCheapest = l.platform === cheapest?.platform
            const colors = PLATFORM_COLORS[l.platform as Platform]
            return (
              <div
                key={l.platform}
                data-testid={`fee-tile-${l.platform}`}
                data-cheapest={isCheapest ? 'true' : undefined}
                className={`rounded-lg px-2 py-2 text-center transition-opacity ${
                  isCheapest ? 'bg-stone-50' : 'bg-stone-50 opacity-40'
                }`}
              >
                <p className={`text-[10px] font-semibold uppercase tracking-wide mb-0.5 ${colors.label}`}>
                  {PLATFORM_SHORT[l.platform as Platform]}
                </p>
                <p className="text-sm font-bold text-stone-900">
                  {centsToEuro(l.delivery_fee_cents)}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd forkeur-app && npx vitest run __tests__/restaurant-card.test.tsx
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
cd forkeur-app && git add components/RestaurantCard.tsx __tests__/restaurant-card.test.tsx
git commit -m "feat: redesign RestaurantCard to 3-col platform fee grid"
```

---

### Task 3: Update StickyOrderBar tests for stone+accent theme

**Files:**
- Modify: `forkeur-app/__tests__/sticky-order-bar.test.tsx`

- [ ] **Step 1: Add test for stone-900 bg and platform-colored price**

Open `forkeur-app/__tests__/sticky-order-bar.test.tsx` and replace the full file with:

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

  it('applies bg-stone-900 class to inner bar', () => {
    render(
      <StickyOrderBar platform="uber_eats" total={648} platformUrl="https://example.com" />
    )
    const bar = screen.getByTestId('order-bar-inner')
    expect(bar).toHaveClass('bg-stone-900')
  })

  it('applies platform left-border class to inner bar for uber_eats', () => {
    render(
      <StickyOrderBar platform="uber_eats" total={648} platformUrl="https://example.com" />
    )
    const bar = screen.getByTestId('order-bar-inner')
    expect(bar).toHaveClass('border-l-4')
    expect(bar).toHaveClass('border-green-500')
  })

  it('applies platform left-border class for deliveroo', () => {
    render(
      <StickyOrderBar platform="deliveroo" total={200} platformUrl={null} />
    )
    const bar = screen.getByTestId('order-bar-inner')
    expect(bar).toHaveClass('border-cyan-500')
  })

  it('applies platform left-border class for takeaway', () => {
    render(
      <StickyOrderBar platform="takeaway" total={200} platformUrl={null} />
    )
    const bar = screen.getByTestId('order-bar-inner')
    expect(bar).toHaveClass('border-orange-500')
  })
})
```

- [ ] **Step 2: Run tests — expect FAIL on new tests**

```bash
cd forkeur-app && npx vitest run __tests__/sticky-order-bar.test.tsx
```

Expected: existing 5 pass, new 4 fail (`order-bar-inner` testid not found, classes wrong).

---

### Task 4: Implement stone+accent StickyOrderBar

**Files:**
- Modify: `forkeur-app/components/StickyOrderBar.tsx`

`PLATFORM_COLORS` already has `ring` keys: `border-green-500`, `border-cyan-500`, `border-orange-500`. Use these for the left border.

- [ ] **Step 1: Replace StickyOrderBar implementation**

Open `forkeur-app/components/StickyOrderBar.tsx` and replace the full file with:

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
      data-testid="order-bar-inner"
      className={`flex items-center justify-between px-5 py-4 bg-stone-900 border-l-4 ${colors.ring}`}
      style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))' }}
    >
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
        <span className="text-sm font-semibold text-white">
          Order on {PLATFORM_LABELS[platform]}
        </span>
      </div>
      <span className={`text-sm font-semibold ${colors.label}`}>{centsToEuro(total)}</span>
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

- [ ] **Step 2: Run tests — expect all PASS**

```bash
cd forkeur-app && npx vitest run __tests__/sticky-order-bar.test.tsx
```

Expected: all 9 tests pass.

- [ ] **Step 3: Commit**

```bash
cd forkeur-app && git add components/StickyOrderBar.tsx __tests__/sticky-order-bar.test.tsx
git commit -m "feat: retheme StickyOrderBar to stone-900 with platform accent border"
```

---

### Task 5: Add homepage loading skeleton

**Files:**
- Create: `forkeur-app/app/loading.tsx`

Next.js automatically uses `app/loading.tsx` as the Suspense fallback for the `/` route. No wiring needed — just create the file.

- [ ] **Step 1: Create `app/loading.tsx`**

```tsx
export default function Loading() {
  return (
    <div className="max-w-md mx-auto px-5">
      {/* Nav */}
      <div className="flex items-center justify-between pt-5 pb-4">
        <div className="w-20 h-5 bg-stone-100 rounded animate-pulse" />
        <div className="w-16 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Hero */}
      <div className="mb-4">
        <div className="w-56 h-8 bg-stone-100 rounded animate-pulse mb-2" />
        <div className="w-40 h-8 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Search */}
      <div className="border border-stone-200 rounded-xl px-4 py-3 mb-5">
        <div className="w-40 h-4 bg-stone-100 rounded animate-pulse" />
      </div>

      {/* Cuisine chips */}
      <div className="flex gap-2 mb-4">
        {[60, 72, 54, 80].map((w, i) => (
          <div key={i} className={`h-7 bg-stone-100 rounded-full animate-pulse`} style={{ width: w }} />
        ))}
      </div>

      {/* Label */}
      <div className="w-24 h-2.5 bg-stone-100 rounded animate-pulse mb-3" />

      {/* 6 card skeletons */}
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="py-4 border-b border-stone-100 last:border-0">
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="w-36 h-4 bg-stone-100 rounded animate-pulse mb-1.5" />
              <div className="w-24 h-3 bg-stone-100 rounded animate-pulse" />
            </div>
            <div className="w-3 h-3 bg-stone-100 rounded animate-pulse mt-0.5" />
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {[0, 1, 2].map((j) => (
              <div key={j} className="h-12 bg-stone-100 rounded-lg animate-pulse" />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Verify file created**

```bash
ls forkeur-app/app/loading.tsx
```

Expected: file exists.

- [ ] **Step 3: Commit**

```bash
cd forkeur-app && git add app/loading.tsx
git commit -m "feat: add homepage loading skeleton"
```

---

### Task 6: Remove dead dark-mode CSS and run full test suite

**Files:**
- Modify: `forkeur-app/app/globals.css`

- [ ] **Step 1: Remove dark-mode block from globals.css**

Open `forkeur-app/app/globals.css`. Remove the entire `@media (prefers-color-scheme: dark)` block. Final file should be:

```css
@import "tailwindcss";

:root {
  --background: #ffffff;
  --foreground: #171717;
}

@theme inline {
  --color-background: var(--background);
  --font-sans: var(--font-geist-sans);
  --font-mono: var(--font-geist-mono);
}

body {
  background: var(--background);
  color: var(--foreground);
  font-family: Arial, Helvetica, sans-serif;
}
```

Note: also removed `--color-foreground` from `@theme inline` since it's unused.

- [ ] **Step 2: Run full test suite**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests pass (no regressions in basket.test.ts either).

- [ ] **Step 3: Commit**

```bash
cd forkeur-app && git add app/globals.css
git commit -m "chore: remove unused dark-mode CSS"
```

---

## Self-Review

**Spec coverage:**
- ✅ RestaurantCard → 3-col fee grid (Tasks 1–2)
- ✅ StickyOrderBar → stone-900 + platform accent (Tasks 3–4)
- ✅ Homepage loading skeleton (Task 5)
- ✅ globals.css dark-mode removal (Task 6)

**Placeholder scan:** None found.

**Type consistency:**
- `PLATFORM_COLORS[platform].ring` used in Task 4 → confirmed exists in `lib/basket.ts` as `ring: 'border-green-500'` etc.
- `PLATFORM_COLORS[platform].label` used in Task 4 → confirmed exists as `label: 'text-green-600'` etc.
- `PLATFORM_SHORT` defined locally in Task 2 RestaurantCard (same pattern as existing PlatformPriceRow.tsx)
- `data-testid="fee-tile-${l.platform}"` written in Task 2, tested in Task 1 ✅
- `data-testid="order-bar-inner"` written in Task 4, tested in Task 3 ✅
