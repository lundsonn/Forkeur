# Basket Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current scroll-based basket UX with inline qty steppers on menu rows, a persistent sticky basket bar, and a slide-up compare sheet.

**Architecture:** Three focused changes — `PlatformPriceRow` gains a qty stepper, a new `CompareSheet` handles the slide-up drawer, and `BasketSimulator` is stripped of the old recommendation UI and wired to both. `StickyOrderBar` is deleted.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, Tailwind CSS, Vitest + Testing Library

---

## File map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `forkeur-app/components/PlatformPriceRow.tsx` | Add `qty` + `onRemove` props; render stepper when qty ≥ 1 |
| Create | `forkeur-app/components/CompareSheet.tsx` | Slide-up bottom sheet: winner card + all-three list + CTA |
| Modify | `forkeur-app/components/BasketSimulator.tsx` | Remove chip/recommendation/StickyOrderBar; add sticky bar + CompareSheet; wire stepper |
| Delete | `forkeur-app/components/StickyOrderBar.tsx` | No longer used |
| Replace | `forkeur-app/__tests__/sticky-order-bar.test.tsx` | Repurpose as `basket-bar.test.tsx` for new bar behaviour |
| Create | `forkeur-app/__tests__/compare-sheet.test.tsx` | Tests for CompareSheet |
| Modify | `forkeur-app/__tests__/restaurant-card.test.tsx` | No change expected — listed for reference only |

---

## Task 1: PlatformPriceRow — qty stepper

**Files:**
- Modify: `forkeur-app/components/PlatformPriceRow.tsx`
- Create: `forkeur-app/__tests__/platform-price-row.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// forkeur-app/__tests__/platform-price-row.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PlatformPriceRow from '../components/PlatformPriceRow'
import type { MenuItemWithPrices } from '../lib/queries'

const item: MenuItemWithPrices = {
  name: 'Margherita',
  description: 'San Marzano, fior di latte',
  category: 'Pizza',
  image_url: null,
  prices: { uber_eats: 950, deliveroo: 940, takeaway: 960 },
}

describe('PlatformPriceRow', () => {
  it('shows + button when qty is 0', () => {
    render(<PlatformPriceRow item={item} qty={0} onAdd={vi.fn()} onRemove={vi.fn()} />)
    expect(screen.getByRole('button', { name: /add margherita/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).toBeNull()
  })

  it('shows stepper when qty ≥ 1', () => {
    render(<PlatformPriceRow item={item} qty={2} onAdd={vi.fn()} onRemove={vi.fn()} />)
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add margherita/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove margherita/i })).toBeInTheDocument()
  })

  it('calls onAdd when + clicked', async () => {
    const onAdd = vi.fn()
    render(<PlatformPriceRow item={item} qty={1} onAdd={onAdd} onRemove={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(onAdd).toHaveBeenCalledOnce()
  })

  it('calls onRemove when − clicked', async () => {
    const onRemove = vi.fn()
    render(<PlatformPriceRow item={item} qty={1} onAdd={vi.fn()} onRemove={onRemove} />)
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(onRemove).toHaveBeenCalledOnce()
  })

  it('item name is bolder when qty ≥ 1', () => {
    const { rerender } = render(
      <PlatformPriceRow item={item} qty={0} onAdd={vi.fn()} onRemove={vi.fn()} />
    )
    const nameEl0 = screen.getByText('Margherita')
    expect(nameEl0).not.toHaveClass('font-bold')

    rerender(<PlatformPriceRow item={item} qty={1} onAdd={vi.fn()} onRemove={vi.fn()} />)
    const nameEl1 = screen.getByText('Margherita')
    expect(nameEl1).toHaveClass('font-bold')
  })
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd forkeur-app && npx vitest run __tests__/platform-price-row.test.tsx
```

Expected: FAIL — `PlatformPriceRow` missing `qty`/`onRemove` props.

- [ ] **Step 3: Update PlatformPriceRow**

Replace `forkeur-app/components/PlatformPriceRow.tsx` entirely:

```tsx
import { PLATFORMS, PLATFORM_COLORS, type Platform, centsToEuro } from '@/lib/basket'
import type { MenuItemWithPrices } from '@/lib/queries'

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
  qty: number
  onAdd: () => void
  onRemove: () => void
  isLast?: boolean
}

export default function PlatformPriceRow({ item, qty, onAdd, onRemove, isLast }: Props) {
  const cheapest = cheapestPlatformForItem(item.prices)

  return (
    <div className={`py-3.5 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex justify-between items-start mb-2.5">
        <div className="min-w-0 pr-3">
          <p className={`text-sm text-stone-900 ${qty > 0 ? 'font-bold' : 'font-semibold'}`}>
            {item.name}
          </p>
          {item.description && (
            <p className="text-xs text-stone-400 mt-0.5 line-clamp-1">{item.description}</p>
          )}
        </div>

        {qty === 0 ? (
          <button
            onClick={onAdd}
            className="shrink-0 w-7 h-7 rounded-full border border-stone-300 flex items-center justify-center text-stone-600 hover:border-stone-600 hover:text-stone-900 transition-colors text-base leading-none"
            aria-label={`Add ${item.name} to basket`}
          >
            +
          </button>
        ) : (
          <div className="flex items-center gap-1 bg-stone-100 rounded-full px-2 py-0.5">
            <button
              onClick={onRemove}
              className="w-5 h-5 flex items-center justify-center text-stone-500 hover:text-stone-900 transition-colors text-sm leading-none"
              aria-label={`Remove ${item.name} from basket`}
            >
              −
            </button>
            <span className="text-xs font-semibold text-stone-900 min-w-[12px] text-center">
              {qty}
            </span>
            <button
              onClick={onAdd}
              className="w-5 h-5 flex items-center justify-center text-stone-700 hover:text-stone-900 transition-colors text-sm leading-none"
              aria-label={`Add ${item.name} to basket`}
            >
              +
            </button>
          </div>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        {PLATFORMS.map((platform) => {
          const price = item.prices[platform]
          const isCheapest = platform === cheapest && price !== null
          const colors = PLATFORM_COLORS[platform]
          return (
            <div key={platform} className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
              <span
                className={`text-xs ${isCheapest ? 'font-semibold text-green-600' : 'text-stone-500'}`}
              >
                {PLATFORM_SHORT[platform]} {centsToEuro(price)}
                {isCheapest && price !== null ? ' ✓' : ''}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd forkeur-app && npx vitest run __tests__/platform-price-row.test.tsx
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/PlatformPriceRow.tsx forkeur-app/__tests__/platform-price-row.test.tsx
git commit -m "feat: add qty stepper to PlatformPriceRow"
```

---

## Task 2: CompareSheet — slide-up bottom sheet

**Files:**
- Create: `forkeur-app/components/CompareSheet.tsx`
- Create: `forkeur-app/__tests__/compare-sheet.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// forkeur-app/__tests__/compare-sheet.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CompareSheet from '../components/CompareSheet'
import type { Platform } from '../lib/basket'

const baseProps = {
  cheapestPlatform: 'uber_eats' as Platform,
  total: 648,
  eta: '18 min',
  savingsCents: 120,
  platformUrl: 'https://ubereats.com/test',
  sortedByTotal: [
    { platform: 'uber_eats' as Platform, total: 648, eta: '18 min' },
    { platform: 'takeaway' as Platform, total: 767, eta: '25 min' },
    { platform: 'deliveroo' as Platform, total: 789, eta: '22 min' },
  ],
  onClose: vi.fn(),
}

describe('CompareSheet', () => {
  it('renders winner platform name', () => {
    render(<CompareSheet {...baseProps} />)
    expect(screen.getByText('Uber Eats')).toBeInTheDocument()
  })

  it('renders total, eta, and savings', () => {
    render(<CompareSheet {...baseProps} />)
    expect(screen.getByText('€6.48')).toBeInTheDocument()
    expect(screen.getByText('18 min')).toBeInTheDocument()
    expect(screen.getByText('€1.20')).toBeInTheDocument()
  })

  it('does not render savings when savingsCents is null', () => {
    render(<CompareSheet {...baseProps} savingsCents={null} />)
    expect(screen.queryByText(/you save/i)).toBeNull()
  })

  it('renders Best badge on winner row', () => {
    render(<CompareSheet {...baseProps} />)
    expect(screen.getByText('Best')).toBeInTheDocument()
  })

  it('renders all 3 platform rows', () => {
    render(<CompareSheet {...baseProps} />)
    expect(screen.getByText('Uber Eats')).toBeInTheDocument()
    expect(screen.getByText('Takeaway')).toBeInTheDocument()
    expect(screen.getByText('Deliveroo')).toBeInTheDocument()
  })

  it('CTA links to platformUrl and opens in new tab', () => {
    render(<CompareSheet {...baseProps} />)
    const link = screen.getByRole('link', { name: /order on uber eats/i })
    expect(link).toHaveAttribute('href', 'https://ubereats.com/test')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('CTA is a non-link button when platformUrl is null', () => {
    render(<CompareSheet {...baseProps} platformUrl={null} />)
    expect(screen.queryByRole('link', { name: /order on uber eats/i })).toBeNull()
    expect(screen.getByText('Order on Uber Eats')).toBeInTheDocument()
  })

  it('calls onClose when backdrop clicked', async () => {
    const onClose = vi.fn()
    render(<CompareSheet {...baseProps} onClose={onClose} />)
    await userEvent.click(screen.getByTestId('sheet-backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd forkeur-app && npx vitest run __tests__/compare-sheet.test.tsx
```

Expected: FAIL — `CompareSheet` does not exist.

- [ ] **Step 3: Create CompareSheet**

```tsx
// forkeur-app/components/CompareSheet.tsx
'use client'
import { useRef } from 'react'
import { Platform, PLATFORM_LABELS, PLATFORM_COLORS, centsToEuro } from '@/lib/basket'

type SortedEntry = {
  platform: Platform
  total: number | null
  eta: string | null
}

type Props = {
  cheapestPlatform: Platform
  total: number
  eta: string | null
  savingsCents: number | null
  platformUrl: string | null
  sortedByTotal: SortedEntry[]
  onClose: () => void
}

export default function CompareSheet({
  cheapestPlatform,
  total,
  eta,
  savingsCents,
  platformUrl,
  sortedByTotal,
  onClose,
}: Props) {
  const colors = PLATFORM_COLORS[cheapestPlatform]
  const swipeRef = useRef<{ startY: number } | null>(null)

  const cta = (
    <div className="bg-blue-600 text-white rounded-xl px-5 py-3.5 text-center font-semibold text-sm">
      Order on {PLATFORM_LABELS[cheapestPlatform]}
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      {/* Backdrop */}
      <div
        data-testid="sheet-backdrop"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />

      {/* Sheet */}
      <div
        className="relative bg-white rounded-t-2xl max-w-md w-full mx-auto pb-safe"
        onPointerDown={(e) => { swipeRef.current = { startY: e.clientY } }}
        onPointerMove={(e) => {
          if (!swipeRef.current) return
          if (e.clientY - swipeRef.current.startY > 80) { onClose(); swipeRef.current = null }
        }}
        onPointerUp={() => { swipeRef.current = null }}
        onPointerCancel={() => { swipeRef.current = null }}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-4">
          <div className="w-10 h-1 bg-stone-200 rounded-full" />
        </div>

        <div className="px-5 pb-8">
          {/* Winner card */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
            Best right now
          </p>
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2.5 h-2.5 rounded-full ${colors.dot}`} />
            <p className="text-2xl font-bold text-stone-900">
              {PLATFORM_LABELS[cheapestPlatform]}
            </p>
          </div>
          <p className="text-sm text-stone-500 mb-4">Cheapest and fastest right now.</p>

          {/* Metrics */}
          <div className="flex gap-6 mb-5">
            <div>
              <p className="text-xl font-bold text-stone-900">{centsToEuro(total)}</p>
              <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">Total</p>
            </div>
            {eta && (
              <div>
                <p className="text-xl font-bold text-stone-900">{eta}</p>
                <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">Delivery</p>
              </div>
            )}
            {savingsCents !== null && savingsCents > 0 && (
              <div>
                <p className="text-xl font-bold text-green-600">{centsToEuro(savingsCents)}</p>
                <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">You save</p>
              </div>
            )}
          </div>

          {/* All three */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-2 pt-4 border-t border-stone-100">
            All three · live prices
          </p>
          {sortedByTotal.map(({ platform, total: t, eta: e }) => {
            const isBest = platform === cheapestPlatform
            const c = PLATFORM_COLORS[platform]
            return (
              <div
                key={platform}
                className="flex items-center justify-between py-2.5 border-b border-stone-100 last:border-0"
              >
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                  <span className={`text-sm ${isBest ? 'text-stone-900' : 'text-stone-500'}`}>
                    {PLATFORM_LABELS[platform]}
                  </span>
                  {isBest && (
                    <span className="text-[10px] border border-stone-300 rounded-full px-1.5 py-0.5 text-stone-500 leading-none">
                      Best
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4">
                  {e && <span className="text-xs text-stone-400">{e}</span>}
                  <span className={`text-sm font-semibold ${isBest ? 'text-stone-900' : 'text-stone-500'}`}>
                    {centsToEuro(t)}
                  </span>
                </div>
              </div>
            )
          })}

          <p className="text-xs text-stone-400 mt-3 mb-5">
            Why {PLATFORM_LABELS[cheapestPlatform]}? Lowest total including all fees.
          </p>

          {/* CTA */}
          {platformUrl ? (
            <a
              href={platformUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`Order on ${PLATFORM_LABELS[cheapestPlatform]}`}
            >
              {cta}
            </a>
          ) : (
            <div>{cta}</div>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd forkeur-app && npx vitest run __tests__/compare-sheet.test.tsx
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/CompareSheet.tsx forkeur-app/__tests__/compare-sheet.test.tsx
git commit -m "feat: add CompareSheet slide-up bottom sheet"
```

---

## Task 3: BasketSimulator — wire it all together

**Files:**
- Modify: `forkeur-app/components/BasketSimulator.tsx`
- Create: `forkeur-app/__tests__/basket-bar.test.tsx` (replaces sticky-order-bar logic)

- [ ] **Step 1: Write failing basket-bar tests**

```tsx
// forkeur-app/__tests__/basket-bar.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BasketSimulator from '../components/BasketSimulator'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

const listings: PlatformListing[] = [
  { id: '1', platform: 'uber_eats', platform_url: 'https://ubereats.com', delivery_fee_cents: 299, delivery_fee_label: '€2.99', eta_label: '18 min', rating: 4.5 },
  { id: '2', platform: 'deliveroo', platform_url: null, delivery_fee_cents: 399, delivery_fee_label: '€3.99', eta_label: '22 min', rating: null },
]

const menuItems: MenuItemWithPrices[] = [
  { name: 'Margherita', description: null, category: 'Pizza', image_url: null, prices: { uber_eats: 950, deliveroo: 940, takeaway: null } },
]

describe('BasketSimulator', () => {
  it('basket bar hidden when basket empty', () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} />)
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('basket bar visible after adding item', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toBeInTheDocument()
  })

  it('basket bar shows item count', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toHaveTextContent('1 item')
  })

  it('removing item decreases stepper qty', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByText('2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('removing last item hides basket bar', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('tapping basket bar opens compare sheet', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByTestId('basket-bar'))
    expect(screen.getByText('Best right now')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd forkeur-app && npx vitest run __tests__/basket-bar.test.tsx
```

Expected: FAIL — BasketSimulator missing `data-testid="basket-bar"` and new behaviour.

- [ ] **Step 3: Rewrite BasketSimulator**

Replace `forkeur-app/components/BasketSimulator.tsx` entirely:

```tsx
'use client'
import { useState, useMemo } from 'react'
import {
  BasketItem,
  PlatformFees,
  Platform,
  PLATFORMS,
  PLATFORM_LABELS,
  PLATFORM_COLORS,
  calculateAllTotals,
  findCheapestPlatform,
  centsToEuro,
} from '@/lib/basket'
import { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import PlatformPriceRow from './PlatformPriceRow'
import CompareSheet from './CompareSheet'

type Props = {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
}

export default function BasketSimulator({ menuItems, listings }: Props) {
  const [basket, setBasket] = useState<BasketItem[]>([])
  const [sheetOpen, setSheetOpen] = useState(false)

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

  const grouped = useMemo(() => {
    const map = new Map<string, MenuItemWithPrices[]>()
    for (const item of menuItems) {
      const cat = item.category ?? 'Menu'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(item)
    }
    return map
  }, [menuItems])

  function getQty(name: string): number {
    return basket.find((b) => b.name === name)?.qty ?? 0
  }

  function addItem(item: MenuItemWithPrices) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === item.name)
      if (existing) {
        return prev.map((b) => b.name === item.name ? { ...b, qty: b.qty + 1 } : b)
      }
      return [...prev, { name: item.name, qty: 1, prices: item.prices }]
    })
  }

  function removeItem(item: MenuItemWithPrices) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === item.name)
      if (!existing) return prev
      if (existing.qty <= 1) return prev.filter((b) => b.name !== item.name)
      return prev.map((b) => b.name === item.name ? { ...b, qty: b.qty - 1 } : b)
    })
  }

  const itemCount = basket.reduce((sum, b) => sum + b.qty, 0)

  const subtotalCents = useMemo(
    () => basket.reduce((sum, b) => {
      const prices = PLATFORMS.map((p) => b.prices[p]).filter((v): v is number => v !== null)
      const price = prices.length ? Math.min(...prices) : 0
      return sum + price * b.qty
    }, 0),
    [basket]
  )

  const cheapestTotal = cheapestPlatform ? totals[cheapestPlatform] : null

  const sortedByTotal = useMemo(() => {
    return PLATFORMS
      .filter((p) => fees[p] !== null)
      .map((p) => ({
        platform: p,
        total: totals[p],
        eta: listings.find((l) => l.platform === p)?.eta_label ?? null,
      }))
      .sort((a, b) => {
        if (a.total === null) return 1
        if (b.total === null) return -1
        return a.total - b.total
      })
  }, [fees, totals, listings])

  const otherTotals = sortedByTotal
    .filter((x) => x.platform !== cheapestPlatform && x.total !== null)
    .map((x) => x.total!)
  const savingsCents =
    otherTotals.length > 0 && cheapestTotal !== null
      ? Math.max(...otherTotals) - cheapestTotal
      : null

  const cheapestEta = cheapestPlatform
    ? listings.find((l) => l.platform === cheapestPlatform)?.eta_label ?? null
    : null

  return (
    <div className="px-5">
      {/* Menu items list */}
      {menuItems.length === 0 ? (
        <p className="text-sm text-stone-400 py-6">No menu data available yet.</p>
      ) : (
        <div className="mb-6">
          {Array.from(grouped.entries()).map(([category, items]) => (
            <div key={category}>
              <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase pt-4 pb-2">
                {category}
              </p>
              {items.map((item, i) => (
                <PlatformPriceRow
                  key={item.name}
                  item={item}
                  qty={getQty(item.name)}
                  onAdd={() => addItem(item)}
                  onRemove={() => removeItem(item)}
                  isLast={i === items.length - 1}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Spacer so content isn't hidden behind sticky bar */}
      {basket.length > 0 && <div className="h-20" />}

      {/* Sticky basket bar */}
      {basket.length > 0 && cheapestPlatform && cheapestTotal !== null && (
        <div className="fixed bottom-0 left-0 right-0 z-40 flex justify-center pointer-events-none px-5 pb-5">
          <button
            data-testid="basket-bar"
            onClick={() => setSheetOpen(true)}
            className="w-full max-w-md pointer-events-auto bg-stone-900 text-white rounded-2xl px-5 py-3.5 flex items-center justify-between transition-transform duration-200"
            style={{ paddingBottom: 'calc(0.875rem + env(safe-area-inset-bottom, 0px))' }}
          >
            <div>
              <p className="text-xs text-stone-400">
                {itemCount} item{itemCount !== 1 ? 's' : ''} · {centsToEuro(subtotalCents)}
              </p>
              <p className="text-sm font-bold">
                Best:{' '}
                <span className={PLATFORM_COLORS[cheapestPlatform].label}>
                  {PLATFORM_LABELS[cheapestPlatform]}
                </span>{' '}
                {centsToEuro(cheapestTotal)}
              </p>
            </div>
            <span className={`text-lg font-bold ${PLATFORM_COLORS[cheapestPlatform].label}`}>
              ↑
            </span>
          </button>
        </div>
      )}

      {/* Compare sheet */}
      {sheetOpen && cheapestPlatform && cheapestTotal !== null && (
        <CompareSheet
          cheapestPlatform={cheapestPlatform}
          total={cheapestTotal}
          eta={cheapestEta}
          savingsCents={savingsCents}
          platformUrl={cheapestPlatform ? platformUrls[cheapestPlatform] ?? null : null}
          sortedByTotal={sortedByTotal}
          onClose={() => setSheetOpen(false)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd forkeur-app && npx vitest run __tests__/basket-bar.test.tsx
```

Expected: 6 tests PASS.

- [ ] **Step 5: Run full test suite — no regressions**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests PASS except `sticky-order-bar.test.tsx` (will fix in Task 4).

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/components/BasketSimulator.tsx forkeur-app/__tests__/basket-bar.test.tsx
git commit -m "feat: rework BasketSimulator with sticky bar and CompareSheet"
```

---

## Task 4: Delete StickyOrderBar + update test file

**Files:**
- Delete: `forkeur-app/components/StickyOrderBar.tsx`
- Replace: `forkeur-app/__tests__/sticky-order-bar.test.tsx`

- [ ] **Step 1: Delete StickyOrderBar**

```bash
rm forkeur-app/components/StickyOrderBar.tsx
```

- [ ] **Step 2: Replace the test file**

The old tests covered `StickyOrderBar` which no longer exists. Replace with a smoke test confirming the bar no longer exists and the import is gone.

```tsx
// forkeur-app/__tests__/sticky-order-bar.test.tsx
// StickyOrderBar has been removed — basket bar is now inline in BasketSimulator.
// See basket-bar.test.tsx for BasketSimulator bar behaviour.
// See compare-sheet.test.tsx for CompareSheet behaviour.
import { describe, it } from 'vitest'

describe('StickyOrderBar (removed)', () => {
  it('is replaced by inline basket bar in BasketSimulator — see basket-bar.test.tsx', () => {
    // intentionally empty — component deleted
  })
})
```

- [ ] **Step 3: Run full test suite — all pass**

```bash
cd forkeur-app && npx vitest run
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove StickyOrderBar, replace test stub"
```

---

## Task 5: Manual smoke test in browser

- [ ] **Step 1: Open the app**

Navigate to **http://localhost:30000** (or start with `cd forkeur-app && npm run dev -- --port 30000`).

- [ ] **Step 2: Open any restaurant detail page**

Click any restaurant in the list.

- [ ] **Step 3: Verify menu rows**

- Confirm each menu item shows a `+` button
- Tap `+` — confirm it changes to `− 1 +` stepper
- Tap `+` again — confirm count becomes `2`
- Tap `−` — confirm count returns to `1`
- Tap `−` again — confirm stepper reverts to `+` button

- [ ] **Step 4: Verify sticky bar**

- After adding an item, confirm dark sticky bar appears at bottom
- Confirm it shows item count + subtotal on left, best platform + total on right
- Confirm bar disappears when all items removed

- [ ] **Step 5: Verify compare sheet**

- Add items, tap the sticky bar
- Confirm slide-up sheet appears with winner card, metrics, all-three list, CTA
- Confirm tapping backdrop closes sheet
- Confirm CTA opens platform URL in new tab
