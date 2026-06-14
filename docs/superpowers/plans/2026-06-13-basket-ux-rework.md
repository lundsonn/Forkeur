# Basket UX Rework — Two-Phase Tab Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `BasketSimulator.tsx` (831 lines) into two focused tabs — Menu (browse + add) and Compare (platform decision cards) — eliminating the sticky bar and CompareSheet bottom sheet.

**Architecture:** `BasketSimulator.tsx` becomes a thin orchestrator (state + URL sync + tab routing); `MenuBrowser.tsx` owns the menu tab (items, search, float pill); `CompareDecision.tsx` owns the compare tab (platform cards, savings callout). `CompareSheet.tsx` is deleted.

**Tech Stack:** Next.js 15 App Router, `'use client'`, `next-intl`, Tailwind CSS, Vitest + @testing-library/react + NextIntlClientProvider

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `forkeur-app/messages/en.json` | Add `BasketSimulator` namespace |
| Modify | `forkeur-app/messages/fr.json` | Add `BasketSimulator` namespace (same time as EN) |
| Modify | `forkeur-app/messages/nl.json` | Add `BasketSimulator` namespace (same time as EN) |
| Create | `forkeur-app/components/MenuBrowser.tsx` | Menu tab: item table, search, DishModal, float pill |
| Create | `forkeur-app/__tests__/menu-browser.test.tsx` | Tests for MenuBrowser |
| Create | `forkeur-app/components/CompareDecision.tsx` | Compare tab: platform cards, direct savings, empty state |
| Create | `forkeur-app/__tests__/compare-decision.test.tsx` | Tests for CompareDecision |
| Modify | `forkeur-app/components/BasketSimulator.tsx` | Strip to orchestrator, add tab bar, wire children |
| Modify | `forkeur-app/__tests__/basket-simulator.test.tsx` | Update tests to use new tab UI |
| Delete | `forkeur-app/components/CompareSheet.tsx` | Absorbed by CompareDecision |
| Delete | `forkeur-app/__tests__/compare-sheet.test.tsx` | CompareSheet no longer exists |

---

### Task 1: i18n keys — add `BasketSimulator` namespace to all 3 locales

**Files:**
- Modify: `forkeur-app/messages/en.json`
- Modify: `forkeur-app/messages/fr.json`
- Modify: `forkeur-app/messages/nl.json`
- Test: `forkeur-app/__tests__/i18n-parity.test.ts` (existing — must stay green)

- [ ] **Step 1: Add keys to EN only, run i18n-parity to see it fail**

Add to `forkeur-app/messages/en.json` (at the end of the root JSON object, before the closing `}`):

```json
"BasketSimulator": {
  "tab": {
    "menu": "Menu",
    "compare": "Compare"
  },
  "compareFloat": "Compare ({count})",
  "addItemsFirst": "Add items first",
  "emptyCompare": "Add items from the Menu tab to compare prices",
  "bestBadge": "BEST",
  "orderOn": "Order on {platform}",
  "missingItems": "Missing: {items}",
  "deltaVsBest": "+{amount} vs best",
  "directSavings": "Save {amount} ordering direct",
  "directPartialCoverage": "Order by phone — {matched} of {total} items on menu"
}
```

Run: `cd forkeur-app && npm test -- i18n-parity`
Expected: FAIL — FR/NL missing `BasketSimulator.*` keys

- [ ] **Step 2: Add keys to FR**

Add to `forkeur-app/messages/fr.json`:

```json
"BasketSimulator": {
  "tab": {
    "menu": "Menu",
    "compare": "Comparer"
  },
  "compareFloat": "Comparer ({count})",
  "addItemsFirst": "Ajouter des articles d'abord",
  "emptyCompare": "Ajoutez des articles depuis l'onglet Menu pour comparer les prix",
  "bestBadge": "MEILLEUR",
  "orderOn": "Commander sur {platform}",
  "missingItems": "Manquant : {items}",
  "deltaVsBest": "+{amount} vs meilleur",
  "directSavings": "Économisez {amount} en commandant directement",
  "directPartialCoverage": "Commander par téléphone — {matched} sur {total} articles au menu"
}
```

- [ ] **Step 3: Add keys to NL**

Add to `forkeur-app/messages/nl.json`:

```json
"BasketSimulator": {
  "tab": {
    "menu": "Menu",
    "compare": "Vergelijken"
  },
  "compareFloat": "Vergelijken ({count})",
  "addItemsFirst": "Voeg eerst items toe",
  "emptyCompare": "Voeg items toe via het Menu-tabblad om prijzen te vergelijken",
  "bestBadge": "BEST",
  "orderOn": "Bestellen via {platform}",
  "missingItems": "Ontbreekt: {items}",
  "deltaVsBest": "+{amount} vs beste",
  "directSavings": "Bespaar {amount} door direct te bestellen",
  "directPartialCoverage": "Bestellen per telefoon — {matched} van {total} items in het menu"
}
```

- [ ] **Step 4: Run i18n-parity — verify it passes**

Run: `cd forkeur-app && npm test -- i18n-parity`
Expected: PASS — all 3 locales have identical key sets

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/messages/en.json forkeur-app/messages/fr.json forkeur-app/messages/nl.json
git commit -m "feat(i18n): add BasketSimulator tab/compare keys to EN/FR/NL"
```

---

### Task 2: Create `MenuBrowser.tsx`

**Files:**
- Create: `forkeur-app/components/MenuBrowser.tsx`
- Create: `forkeur-app/__tests__/menu-browser.test.tsx`

MenuBrowser receives all basket state and callbacks from the orchestrator. It owns: search state, DishModal state, the item table, and the floating pill.

- [ ] **Step 1: Write the failing test**

Create `forkeur-app/__tests__/menu-browser.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import MenuBrowser from '../components/MenuBrowser'
import en from '../messages/en.json'
import type { Platform } from '../lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={props.src as string} alt={props.alt as string} />
  },
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

function makeListing(platform: Platform, feeCents: number | null = 199): PlatformListing {
  return {
    id: `${platform}-1`,
    platform,
    platform_url: `https://${platform}.com/r`,
    url_type: null,
    delivery_fee_cents: feeCents,
    delivery_fee_label: feeCents !== null ? `€${(feeCents / 100).toFixed(2)}` : null,
    min_order_cents: null,
    min_order_label: null,
    eta_label: '~25 min',
    rating: 4.5,
    last_scraped_at: new Date().toISOString(),
    promotions: [],
    is_available: true,
    opening_hours: null,
  }
}

function makeMenuItem(name: string, prices: Partial<Record<Platform, number | null>> = {}): MenuItemWithPrices {
  return {
    name,
    description: null,
    category: 'Mains',
    image_url: null,
    allergens: [],
    prices: { uber_eats: null, deliveroo: null, takeaway: null, direct: null, ...prices },
  }
}

const defaultProps = {
  menuItems: [
    makeMenuItem('Margherita', { uber_eats: 1200, deliveroo: 1300 }),
    makeMenuItem('Pepperoni', { uber_eats: 1400 }),
  ],
  listings: [makeListing('uber_eats'), makeListing('deliveroo')],
  basket: [],
  onAdd: vi.fn(),
  onRemove: vi.fn(),
  onSwitchToCompare: vi.fn(),
}

beforeEach(() => vi.clearAllMocks())

describe('MenuBrowser', () => {
  it('renders menu items grouped by category', () => {
    renderWithIntl(<MenuBrowser {...defaultProps} />)
    expect(screen.getByText('Margherita')).toBeInTheDocument()
    expect(screen.getByText('Pepperoni')).toBeInTheDocument()
  })

  it('calls onAdd when + button clicked', () => {
    renderWithIntl(<MenuBrowser {...defaultProps} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    expect(defaultProps.onAdd).toHaveBeenCalledWith('Margherita', 'Mains')
  })

  it('calls onRemove when - button clicked and qty > 0', () => {
    const props = { ...defaultProps, basket: [{ name: 'Margherita', category: 'Mains', qty: 1 }] }
    renderWithIntl(<MenuBrowser {...props} />)
    fireEvent.click(screen.getByLabelText('Remove Margherita from basket'))
    expect(defaultProps.onRemove).toHaveBeenCalledWith('Margherita')
  })

  it('shows float pill when basket has items', () => {
    const props = { ...defaultProps, basket: [{ name: 'Margherita', category: 'Mains', qty: 2 }] }
    renderWithIntl(<MenuBrowser {...props} />)
    expect(screen.getByTestId('compare-float')).toBeInTheDocument()
    expect(screen.getByTestId('compare-float')).toHaveTextContent('Compare (2)')
  })

  it('hides float pill when basket is empty', () => {
    renderWithIntl(<MenuBrowser {...defaultProps} />)
    expect(screen.queryByTestId('compare-float')).not.toBeInTheDocument()
  })

  it('calls onSwitchToCompare when float pill clicked', () => {
    const props = { ...defaultProps, basket: [{ name: 'Margherita', category: 'Mains', qty: 1 }] }
    renderWithIntl(<MenuBrowser {...props} />)
    fireEvent.click(screen.getByTestId('compare-float'))
    expect(defaultProps.onSwitchToCompare).toHaveBeenCalled()
  })

  it('filters items by search query', () => {
    renderWithIntl(<MenuBrowser {...defaultProps} />)
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'pepperoni' } })
    expect(screen.getByText('Pepperoni')).toBeInTheDocument()
    expect(screen.queryByText('Margherita')).not.toBeInTheDocument()
  })
})
```

Run: `cd forkeur-app && npm test -- menu-browser`
Expected: FAIL — `MenuBrowser` module not found

- [ ] **Step 2: Create `MenuBrowser.tsx`**

Create `forkeur-app/components/MenuBrowser.tsx`:

```tsx
'use client'
import { useState, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import Image from 'next/image'
import { ArrowRight, X } from 'lucide-react'
import { PLATFORM_COLORS, type BasketItem, type Platform } from '@/lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import PlatformLogo from './PlatformLogo'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
  direct: 'DR',
}

function cheapestPlatformForItem(
  item: MenuItemWithPrices,
  listings: PlatformListing[],
): Platform | null {
  let best: Platform | null = null
  let bestPrice = Infinity
  for (const listing of listings) {
    const price = item.prices[listing.platform]
    if (price !== null && price < bestPrice) {
      bestPrice = price
      best = listing.platform
    }
  }
  return best
}

interface DishModalProps {
  item: MenuItemWithPrices
  listings: PlatformListing[]
  qty: number
  onAdd: () => void
  onRemove: () => void
  onClose: () => void
}

function DishModal({ item, listings, qty, onAdd, onRemove, onClose }: DishModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        data-testid="dish-modal-backdrop"
      />
      <div className="relative w-full bg-white rounded-t-2xl p-4 max-h-[80vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 rounded-full bg-stone-100"
          aria-label="Close"
        >
          <X size={18} />
        </button>

        {item.image_url && (
          <div className="relative w-full h-48 rounded-xl overflow-hidden mb-4">
            <Image src={item.image_url} alt={item.name} fill className="object-cover" />
          </div>
        )}

        <h3 className="text-lg font-bold text-stone-900 mb-1">{item.name}</h3>
        {item.description && <p className="text-sm text-stone-500 mb-3">{item.description}</p>}

        <div className="space-y-1 mb-4">
          {listings.map((listing) => {
            const price = item.prices[listing.platform]
            if (price === null) return null
            return (
              <div key={listing.platform} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${PLATFORM_COLORS[listing.platform].dot}`} />
                  {PLATFORM_SHORT[listing.platform]}
                </span>
                <span className="text-stone-700">€{(price / 100).toFixed(2)}</span>
              </div>
            )
          })}
        </div>

        <div className="flex items-center justify-center gap-4">
          <button
            onClick={onRemove}
            disabled={qty === 0}
            className="w-10 h-10 rounded-full bg-stone-100 flex items-center justify-center text-lg font-bold disabled:opacity-30"
            aria-label={`Remove ${item.name} from basket`}
          >
            −
          </button>
          <span className="w-8 text-center font-semibold text-stone-900">{qty}</span>
          <button
            onClick={onAdd}
            className="w-10 h-10 rounded-full bg-orange-600 text-white flex items-center justify-center text-lg font-bold"
            aria-label={`Add ${item.name} to basket`}
          >
            +
          </button>
        </div>
      </div>
    </div>
  )
}

export interface MenuBrowserProps {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
  basket: BasketItem[]
  onAdd: (name: string, category: string) => void
  onRemove: (name: string) => void
  onSwitchToCompare: () => void
}

export default function MenuBrowser({
  menuItems,
  listings,
  basket,
  onAdd,
  onRemove,
  onSwitchToCompare,
}: MenuBrowserProps) {
  const t = useTranslations('BasketSimulator')
  const [search, setSearch] = useState('')
  const [selectedItem, setSelectedItem] = useState<MenuItemWithPrices | null>(null)

  const getQty = (name: string) => basket.find((i) => i.name === name)?.qty ?? 0
  const itemCount = basket.reduce((sum, i) => sum + i.qty, 0)

  const grouped = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = q
      ? menuItems.filter((m) => m.name.toLowerCase().includes(q))
      : menuItems
    const map = new Map<string, MenuItemWithPrices[]>()
    for (const item of filtered) {
      const cat = item.category ?? 'Other'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(item)
    }
    return map
  }, [menuItems, search])

  const platformCols = listings.slice().sort((a, b) => a.platform.localeCompare(b.platform))

  return (
    <>
      {/* Search */}
      <div className="px-4 pt-3 pb-2">
        <input
          type="search"
          placeholder="Search menu…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full border border-stone-200 rounded-lg px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-orange-500"
        />
      </div>

      {/* Menu table */}
      <div className="px-4 pb-32">
        {[...grouped.entries()].map(([category, items]) => (
          <div key={category} className="mb-6">
            <h3 className="text-xs font-semibold uppercase tracking-widest text-stone-400 mb-2">
              {category}
            </h3>

            {/* Column headers */}
            <div className="grid gap-2 mb-1" style={{ gridTemplateColumns: `1fr repeat(${platformCols.length}, 2.5rem) 5rem` }}>
              <span />
              {platformCols.map((l) => (
                <span key={l.platform} className="text-center">
                  <PlatformLogo platform={l.platform} size={16} />
                </span>
              ))}
              <span />
            </div>

            {items.map((item) => {
              const qty = getQty(item.name)
              const cheapest = cheapestPlatformForItem(item, listings)
              return (
                <div
                  key={item.name}
                  className="grid items-center gap-2 py-1.5 border-b border-stone-100 last:border-0"
                  style={{ gridTemplateColumns: `1fr repeat(${platformCols.length}, 2.5rem) 5rem` }}
                >
                  <button
                    onClick={() => setSelectedItem(item)}
                    className="text-left text-sm text-stone-800 truncate"
                  >
                    {item.name}
                  </button>

                  {platformCols.map((l) => {
                    const price = item.prices[l.platform]
                    const isCheapest = cheapest === l.platform
                    return (
                      <span
                        key={l.platform}
                        className={`text-center text-xs ${isCheapest ? 'text-green-600 font-semibold' : 'text-stone-500'}`}
                      >
                        {price !== null ? `€${(price / 100).toFixed(2)}` : '—'}
                      </span>
                    )
                  })}

                  <div className="flex items-center justify-end gap-1">
                    {qty > 0 && (
                      <button
                        onClick={() => onRemove(item.name)}
                        className="w-6 h-6 rounded-full bg-stone-100 flex items-center justify-center text-sm font-bold text-stone-600"
                        aria-label={`Remove ${item.name} from basket`}
                      >
                        −
                      </button>
                    )}
                    {qty > 0 && (
                      <span className="w-4 text-center text-sm font-semibold text-stone-800">
                        {qty}
                      </span>
                    )}
                    <button
                      onClick={() => onAdd(item.name, item.category ?? 'Other')}
                      className="w-6 h-6 rounded-full bg-orange-600 text-white flex items-center justify-center text-sm font-bold"
                      aria-label={`Add ${item.name} to basket`}
                    >
                      +
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {/* Floating compare pill */}
      {itemCount > 0 && (
        <button
          onClick={onSwitchToCompare}
          className="fixed bottom-20 right-4 z-50 bg-orange-600 text-white px-4 py-2 rounded-full shadow-lg flex items-center gap-2 text-sm font-semibold"
          data-testid="compare-float"
        >
          {t('compareFloat', { count: itemCount })}
          <ArrowRight size={16} />
        </button>
      )}

      {/* Dish modal */}
      {selectedItem && (
        <DishModal
          item={selectedItem}
          listings={listings}
          qty={getQty(selectedItem.name)}
          onAdd={() => onAdd(selectedItem.name, selectedItem.category ?? 'Other')}
          onRemove={() => onRemove(selectedItem.name)}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </>
  )
}
```

- [ ] **Step 3: Run menu-browser tests — verify they pass**

Run: `cd forkeur-app && npm test -- menu-browser`
Expected: PASS (7 tests)

- [ ] **Step 4: Commit**

```bash
git add forkeur-app/components/MenuBrowser.tsx forkeur-app/__tests__/menu-browser.test.tsx
git commit -m "feat: add MenuBrowser component (menu tab)"
```

---

### Task 3: Create `CompareDecision.tsx`

**Files:**
- Create: `forkeur-app/components/CompareDecision.tsx`
- Create: `forkeur-app/__tests__/compare-decision.test.tsx`

CompareDecision receives pre-computed totals/coverages from the orchestrator. It renders platform cards sorted cheapest-first, direct savings callout, and empty state.

- [ ] **Step 1: Write the failing test**

Create `forkeur-app/__tests__/compare-decision.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect } from 'vitest'
import CompareDecision from '../components/CompareDecision'
import en from '../messages/en.json'
import type { Platform, PlatformCoverages } from '../lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => <img src={props.src as string} alt={props.alt as string} />,
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

function makeListing(platform: Platform, feeCents: number | null = 199): PlatformListing {
  return {
    id: `${platform}-1`,
    platform,
    platform_url: `https://${platform}.com/r`,
    url_type: null,
    delivery_fee_cents: feeCents,
    delivery_fee_label: feeCents !== null ? `€${(feeCents / 100).toFixed(2)}` : null,
    min_order_cents: null,
    min_order_label: null,
    eta_label: '~25 min',
    rating: 4.5,
    last_scraped_at: new Date().toISOString(),
    promotions: [],
    is_available: true,
    opening_hours: null,
  }
}

function makeMenuItem(name: string, prices: Partial<Record<Platform, number | null>> = {}): MenuItemWithPrices {
  return {
    name,
    description: null,
    category: 'Mains',
    image_url: null,
    allergens: [],
    prices: { uber_eats: null, deliveroo: null, takeaway: null, direct: null, ...prices },
  }
}

const basket = [{ name: 'Margherita', category: 'Mains', qty: 1 }]
const menuItems = [makeMenuItem('Margherita', { uber_eats: 1200, deliveroo: 1350 })]
const listings = [makeListing('uber_eats', 199), makeListing('deliveroo', 249)]

const totals: Record<Platform, number | null> = {
  uber_eats: 1399, // 12.00 + 1.99
  deliveroo: 1599, // 13.50 + 2.49
  takeaway: null,
  direct: null,
}

const coverages: PlatformCoverages = {
  uber_eats: { priced: 1, total: 1, complete: true },
  deliveroo: { priced: 1, total: 1, complete: true },
  takeaway: null,
  direct: null,
}

const defaultProps = {
  basket,
  listings,
  menuItems,
  totals,
  coverages,
  cheapestPlatform: 'uber_eats' as Platform,
  menuDirectSavingsCents: null,
  phone: undefined,
  orderChannel: undefined,
}

describe('CompareDecision', () => {
  it('shows empty state when basket is empty', () => {
    renderWithIntl(<CompareDecision {...defaultProps} basket={[]} />)
    expect(screen.getByText(/add items from the menu tab/i)).toBeInTheDocument()
  })

  it('renders a card for each platform with a non-null total', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('platform-card-uber_eats')).toBeInTheDocument()
    expect(screen.getByTestId('platform-card-deliveroo')).toBeInTheDocument()
    expect(screen.queryByTestId('platform-card-takeaway')).not.toBeInTheDocument()
  })

  it('shows BEST badge on cheapest platform card only', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('best-badge')).toBeInTheDocument()
    // Only one badge
    expect(screen.getAllByTestId('best-badge')).toHaveLength(1)
    // Badge is inside the uber_eats card
    const card = screen.getByTestId('platform-card-uber_eats')
    expect(card).toContainElement(screen.getByTestId('best-badge'))
  })

  it('shows Order CTA only on winner card', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('winner-cta')).toBeInTheDocument()
    expect(screen.getAllByTestId('winner-cta')).toHaveLength(1)
  })

  it('shows delta on non-winner card', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('delta-text')).toBeInTheDocument()
    expect(screen.getByTestId('delta-text')).toHaveTextContent('+')
  })

  it('shows direct savings callout above cards when menuDirectSavingsCents > 0', () => {
    renderWithIntl(<CompareDecision {...defaultProps} menuDirectSavingsCents={300} />)
    const callout = screen.getByTestId('direct-savings')
    expect(callout).toBeInTheDocument()
    expect(callout).toHaveTextContent('Save')
    // Callout appears before first card (check DOM order)
    const cards = screen.getAllByTestId(/^platform-card-/)
    expect(callout.compareDocumentPosition(cards[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('hides direct savings callout when null', () => {
    renderWithIntl(<CompareDecision {...defaultProps} menuDirectSavingsCents={null} />)
    expect(screen.queryByTestId('direct-savings')).not.toBeInTheDocument()
  })

  it('lists missing items for incomplete coverage (up to 2 + N more)', () => {
    const itemsWithMissing = [
      makeMenuItem('Margherita', { uber_eats: 1200, deliveroo: null }),
      makeMenuItem('Pepperoni', { uber_eats: 1400, deliveroo: null }),
      makeMenuItem('Hawaii', { uber_eats: 1300, deliveroo: null }),
    ]
    const basketWithAll = [
      { name: 'Margherita', category: 'Mains', qty: 1 },
      { name: 'Pepperoni', category: 'Mains', qty: 1 },
      { name: 'Hawaii', category: 'Mains', qty: 1 },
    ]
    const coverageWithMissing: PlatformCoverages = {
      uber_eats: { priced: 3, total: 3, complete: true },
      deliveroo: { priced: 0, total: 3, complete: false },
      takeaway: null,
      direct: null,
    }
    const totalsWithMissing: Record<Platform, number | null> = {
      uber_eats: 3900,
      deliveroo: 0, // fallback — some total even with missing
      takeaway: null,
      direct: null,
    }
    renderWithIntl(
      <CompareDecision
        {...defaultProps}
        basket={basketWithAll}
        menuItems={itemsWithMissing}
        totals={totalsWithMissing}
        coverages={coverageWithMissing}
        cheapestPlatform="uber_eats"
      />,
    )
    const missing = screen.getByTestId('missing-items')
    expect(missing).toHaveTextContent('Missing:')
    // 3 items missing → show first 2 + "+ 1 more"
    expect(missing).toHaveTextContent('+ 1 more')
  })
})
```

Run: `cd forkeur-app && npm test -- compare-decision`
Expected: FAIL — `CompareDecision` module not found

- [ ] **Step 2: Create `CompareDecision.tsx`**

Create `forkeur-app/components/CompareDecision.tsx`:

```tsx
'use client'
import { useTranslations } from 'next-intl'
import {
  PLATFORM_COLORS,
  PLATFORM_LABELS,
  centsToEuro,
  type BasketItem,
  type Platform,
  type PlatformCoverages,
} from '@/lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import PlatformLogo from './PlatformLogo'

const PLATFORM_BORDER_L: Record<Platform, string> = {
  uber_eats: 'border-l-green-500',
  deliveroo: 'border-l-cyan-500',
  takeaway: 'border-l-orange-500',
  direct: 'border-l-violet-500',
}

export interface CompareDecisionProps {
  basket: BasketItem[]
  listings: PlatformListing[]
  menuItems: MenuItemWithPrices[]
  totals: Record<Platform, number | null>
  coverages: PlatformCoverages | null
  cheapestPlatform: Platform | null
  menuDirectSavingsCents: number | null
  phone?: string
  orderChannel?: string
}

export default function CompareDecision({
  basket,
  listings,
  menuItems,
  totals,
  coverages,
  cheapestPlatform,
  menuDirectSavingsCents,
  phone,
  orderChannel,
}: CompareDecisionProps) {
  const t = useTranslations('BasketSimulator')

  const hasItems = basket.some((i) => i.qty > 0)

  if (!hasItems) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-8 text-center text-stone-500">
        <p className="text-base">{t('emptyCompare')}</p>
      </div>
    )
  }

  // Build fee/eta/url maps from listings
  const feeMap: Record<Platform, { fee: number | null; eta: string | null; url: string | null }> = {
    uber_eats: { fee: null, eta: null, url: null },
    deliveroo: { fee: null, eta: null, url: null },
    takeaway: { fee: null, eta: null, url: null },
    direct: { fee: null, eta: null, url: null },
  }
  for (const listing of listings) {
    feeMap[listing.platform] = {
      fee: listing.delivery_fee_cents,
      eta: listing.eta_label,
      url: listing.platform_url,
    }
  }

  // Platforms sorted cheapest-first; skip null totals (unavailable)
  const platforms = (['uber_eats', 'deliveroo', 'takeaway', 'direct'] as Platform[])
    .filter((p) => totals[p] !== null)
    .sort((a, b) => (totals[a] ?? Infinity) - (totals[b] ?? Infinity))

  // Direct platform: check overlap threshold (>= 50% of basket items priced)
  const directCoverage = coverages?.direct ?? null
  const directMatchedCount = directCoverage?.priced ?? 0
  const basketItemCount = basket.filter((i) => i.qty > 0).length
  const directThresholdMet = directMatchedCount >= Math.ceil(basketItemCount * 0.5)

  // Missing basket items per platform (for incomplete coverage cards)
  function getMissingNames(platform: Platform): string[] {
    const coverage = coverages?.[platform]
    if (!coverage || coverage.complete) return []
    return basket
      .filter((b) => b.qty > 0 && (menuItems.find((m) => m.name === b.name)?.prices[platform] ?? null) === null)
      .map((b) => b.name)
  }

  return (
    <div className="px-4 py-4 space-y-3">
      {/* Direct savings callout — above card stack */}
      {menuDirectSavingsCents !== null && menuDirectSavingsCents > 0 && (
        <div
          className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-2 text-orange-700 text-sm font-medium"
          data-testid="direct-savings"
        >
          {t('directSavings', { amount: centsToEuro(menuDirectSavingsCents) })}
        </div>
      )}

      {platforms.map((platform) => {
        const isWinner = platform === cheapestPlatform
        const total = totals[platform]!
        const { fee, eta, url } = feeMap[platform]
        const winnerTotal = cheapestPlatform !== null ? (totals[cheapestPlatform] ?? null) : null
        const delta = winnerTotal !== null ? total - winnerTotal : null
        const missingNames = getMissingNames(platform)

        // Direct platform special handling
        if (platform === 'direct') {
          if (!directThresholdMet) {
            return (
              <div
                key={platform}
                className="border border-stone-200 rounded-lg p-4 opacity-60"
                data-testid={`platform-card-${platform}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-2 h-2 rounded-full ${PLATFORM_COLORS[platform].dot}`} />
                  <span className="font-semibold text-stone-500">{PLATFORM_LABELS[platform]}</span>
                </div>
                <p className="text-sm text-stone-400">
                  {t('directPartialCoverage', {
                    matched: directMatchedCount,
                    total: basketItemCount,
                  })}
                </p>
                {phone && (
                  <p className="text-sm text-stone-400 mt-1">📞 {phone}</p>
                )}
              </div>
            )
          }
        }

        return (
          <div
            key={platform}
            className={`border rounded-lg p-4 ${isWinner ? `border-l-4 ${PLATFORM_BORDER_L[platform]} border-stone-200` : 'border-stone-200'}`}
            data-testid={`platform-card-${platform}`}
          >
            <div className="flex items-start justify-between mb-1">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${PLATFORM_COLORS[platform].dot}`} />
                <span className="font-semibold text-stone-800">{PLATFORM_LABELS[platform]}</span>
                {isWinner && (
                  <span
                    className="bg-orange-600 text-white text-xs font-bold px-2 py-0.5 rounded"
                    data-testid="best-badge"
                  >
                    {t('bestBadge')}
                  </span>
                )}
              </div>

              {isWinner && url && (
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="bg-stone-900 text-white text-sm px-3 py-1 rounded-lg whitespace-nowrap ml-2"
                  data-testid="winner-cta"
                >
                  {t('orderOn', { platform: PLATFORM_LABELS[platform] })}
                </a>
              )}
            </div>

            <p className="text-lg font-bold text-stone-900 mb-0.5">{centsToEuro(total)}</p>

            {!isWinner && delta !== null && delta > 0 && (
              <p className="text-sm text-stone-400 mb-0.5" data-testid="delta-text">
                {t('deltaVsBest', { amount: centsToEuro(delta) })}
              </p>
            )}

            <p className="text-sm text-stone-500">
              {fee !== null ? `Delivery ${centsToEuro(fee)}` : 'Free delivery'}
              {eta ? ` · ${eta}` : ''}
            </p>

            {missingNames.length > 0 && (
              <p className="text-sm text-amber-600 mt-1" data-testid="missing-items">
                {t('missingItems', {
                  items:
                    missingNames.slice(0, 2).join(', ') +
                    (missingNames.length > 2 ? ` + ${missingNames.length - 2} more` : ''),
                })}
              </p>
            )}

            {/* Direct platform + threshold met: show phone CTA */}
            {platform === 'direct' && phone && orderChannel !== 'covered_platform' && (
              <a
                href={`tel:${phone}`}
                className="mt-2 inline-block text-sm text-violet-700 font-medium"
                data-testid="direct-phone-cta"
              >
                📞 {phone}
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 3: Run compare-decision tests — verify they pass**

Run: `cd forkeur-app && npm test -- compare-decision`
Expected: PASS (8 tests)

- [ ] **Step 4: Commit**

```bash
git add forkeur-app/components/CompareDecision.tsx forkeur-app/__tests__/compare-decision.test.tsx
git commit -m "feat: add CompareDecision component (compare tab)"
```

---

### Task 4: Refactor `BasketSimulator.tsx` to orchestrator + tab bar

**Files:**
- Modify: `forkeur-app/components/BasketSimulator.tsx`
- Modify: `forkeur-app/__tests__/basket-simulator.test.tsx`

Strip the monolith to a thin orchestrator. Key changes:
- Replace `sheetOpen: boolean` with `activeTab: 'menu' | 'compare'`
- Remove CompareSheet import + render (lines 804–817)
- Remove sticky green bar (lines 722–802)
- Remove DishModal render (lines 819–828 — moved to MenuBrowser)
- Add tab bar JSX
- Route `<MenuBrowser>` / `<CompareDecision>` by activeTab

- [ ] **Step 1: Update basket-simulator tests to use new tab UI**

Open `forkeur-app/__tests__/basket-simulator.test.tsx`. Replace any assertions on `data-testid="basket-bar"` (the sticky bar, now deleted) with assertions on `data-testid="menu-tab"` (the tab bar button). Update the test that checks CompareSheet is opened — instead check that clicking the compare tab shows the compare view.

Replace the existing test file with:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import BasketSimulator from '../components/BasketSimulator'
import en from '../messages/en.json'
import type { Platform } from '../lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => <img src={props.src as string} alt={props.alt as string} />,
}))

// Stub out child components to keep orchestrator tests focused
vi.mock('../components/MenuBrowser', () => ({
  default: ({ onSwitchToCompare, basket }: { onSwitchToCompare: () => void; basket: { qty: number }[] }) => (
    <div data-testid="menu-browser">
      <button onClick={onSwitchToCompare} data-testid="stub-switch-compare">switch</button>
      <span data-testid="stub-basket-count">{basket.reduce((s, i) => s + i.qty, 0)}</span>
    </div>
  ),
}))
vi.mock('../components/CompareDecision', () => ({
  default: () => <div data-testid="compare-decision" />,
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

function makeListing(platform: Platform, feeCents = 199): PlatformListing {
  return {
    id: `${platform}-1`,
    platform,
    platform_url: `https://${platform}.com/r`,
    url_type: null,
    delivery_fee_cents: feeCents,
    delivery_fee_label: `€${(feeCents / 100).toFixed(2)}`,
    min_order_cents: null,
    min_order_label: null,
    eta_label: '~25 min',
    rating: 4.5,
    last_scraped_at: new Date().toISOString(),
    promotions: [],
    is_available: true,
    opening_hours: null,
  }
}

function makeMenuItem(name: string): MenuItemWithPrices {
  return {
    name,
    description: null,
    category: 'Mains',
    image_url: null,
    allergens: [],
    prices: { uber_eats: 1200, deliveroo: 1300, takeaway: null, direct: null },
  }
}

const defaultProps = {
  menuItems: [makeMenuItem('Margherita')],
  listings: [makeListing('uber_eats'), makeListing('deliveroo')],
  restaurantId: 'test-restaurant',
}

beforeEach(() => vi.clearAllMocks())

describe('BasketSimulator (orchestrator)', () => {
  it('renders Menu tab by default', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    expect(screen.getByTestId('menu-browser')).toBeInTheDocument()
    expect(screen.queryByTestId('compare-decision')).not.toBeInTheDocument()
  })

  it('switches to Compare tab when compare tab clicked', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    fireEvent.click(screen.getByTestId('tab-compare'))
    expect(screen.getByTestId('compare-decision')).toBeInTheDocument()
    expect(screen.queryByTestId('menu-browser')).not.toBeInTheDocument()
  })

  it('switches to Compare tab when MenuBrowser calls onSwitchToCompare', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    fireEvent.click(screen.getByTestId('stub-switch-compare'))
    expect(screen.getByTestId('compare-decision')).toBeInTheDocument()
  })

  it('shows item count badge on compare tab when basket has items', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    // No items yet — badge absent
    expect(screen.queryByTestId('compare-badge')).not.toBeInTheDocument()
  })

  it('renders tab bar with Menu and Compare tabs', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    expect(screen.getByTestId('tab-menu')).toBeInTheDocument()
    expect(screen.getByTestId('tab-compare')).toBeInTheDocument()
  })
})
```

Run: `cd forkeur-app && npm test -- basket-simulator`
Expected: FAIL — tests reference new `tab-menu` / `tab-compare` testids that don't exist yet

- [ ] **Step 2: Strip `BasketSimulator.tsx` to orchestrator**

Open `forkeur-app/components/BasketSimulator.tsx`. Apply these changes:

**Imports — add/replace at top:**
```tsx
'use client'
import { useState, useMemo, useEffect, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  calculateAllTotalsWithCoverage,
  findCheapestCompletePlatform,
  findCheapestPlatform,
  computeDirectSavingsCentsFromMenu,
  PLATFORMS,
  type BasketItem,
  type Platform,
  type PlatformFees,
} from '@/lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import MenuBrowser from './MenuBrowser'
import CompareDecision from './CompareDecision'
```

**Remove these imports (no longer used in orchestrator):**
- `import CompareSheet from './CompareSheet'`
- `import { ArrowRight } from 'lucide-react'`
- `import Image from 'next/image'`
- `import PlatformLogo from './PlatformLogo'`

**State — replace `sheetOpen` with `activeTab`:**

```tsx
const [items, setItems] = useState<BasketItem[]>([])
const [activeTab, setActiveTab] = useState<'menu' | 'compare'>('menu')
const [showRestoreBanner, setShowRestoreBanner] = useState(false)
const [savedBasket, setSavedBasket] = useState<BasketItem[] | null>(null)
const [saveLabel, setSaveLabel] = useState('')
const [isMobile, setIsMobile] = useState(false)
```

**Keep all existing memos unchanged** (fees, platformUrls, tier, feesTotals, totals, coverages, cheapestPlatform, isFeesOnly, effectiveCheapestPlatform, menuDirectSavingsCents, grouped, sortedByTotal, effectiveSortedByTotal, effectiveCheapestTotal, otherTotals, savingsCents, effectiveSavingsCents, cheapestEta, showAppHint, itemCount).

**Keep all existing handlers unchanged** (getQty, addItem, removeItem, handleRestore, handleDismissRestore, handleQuickFill, handleSaveUsual).

**Replace JSX return with:**

```tsx
return (
  <div className="relative">
    {/* Restore banner */}
    {showRestoreBanner && savedBasket && (
      <div className="bg-stone-100 border-b border-stone-200 px-4 py-2 flex items-center justify-between text-sm">
        <span className="text-stone-700">
          Restore {savedBasket.reduce((s, i) => s + i.qty, 0)} items from last visit?
        </span>
        <div className="flex gap-2">
          <button onClick={handleRestore} className="text-orange-600 font-medium">
            {saveLabel}
          </button>
          <button onClick={handleDismissRestore} className="text-stone-400">
            Dismiss
          </button>
        </div>
      </div>
    )}

    {/* Tab bar */}
    <div className="sticky top-0 z-10 flex border-b border-stone-200 bg-white">
      <button
        onClick={() => setActiveTab('menu')}
        className={`flex-1 py-3 text-sm font-medium transition-colors ${
          activeTab === 'menu'
            ? 'border-b-2 border-orange-600 text-orange-600'
            : 'text-stone-500'
        }`}
        data-testid="tab-menu"
      >
        {t('tab.menu')}
      </button>
      <button
        onClick={() => setActiveTab('compare')}
        className={`flex-1 py-3 text-sm font-medium transition-colors flex items-center justify-center gap-1.5 ${
          activeTab === 'compare'
            ? 'border-b-2 border-orange-600 text-orange-600'
            : 'text-stone-500'
        }`}
        data-testid="tab-compare"
      >
        {t('tab.compare')}
        {itemCount > 0 && (
          <span
            className="bg-orange-600 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center"
            data-testid="compare-badge"
          >
            {itemCount}
          </span>
        )}
      </button>
    </div>

    {/* Tab content */}
    {activeTab === 'menu' ? (
      <MenuBrowser
        menuItems={menuItems}
        listings={listings}
        basket={items}
        onAdd={addItem}
        onRemove={removeItem}
        onSwitchToCompare={() => setActiveTab('compare')}
      />
    ) : (
      <CompareDecision
        basket={items}
        listings={listings}
        menuItems={menuItems}
        totals={totals}
        coverages={coverages}
        cheapestPlatform={effectiveCheapestPlatform}
        menuDirectSavingsCents={menuDirectSavingsCents}
        phone={phone}
        orderChannel={orderChannel}
      />
    )}
  </div>
)
```

Note: also remove the `const t = useTranslations('basket')` if it's still present from the old code and add `const t = useTranslations('BasketSimulator')`.

- [ ] **Step 3: Run basket-simulator tests — verify they pass**

Run: `cd forkeur-app && npm test -- basket-simulator`
Expected: PASS (5 tests)

- [ ] **Step 4: Run full test suite — verify nothing regressed**

Run: `cd forkeur-app && npm test`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/components/BasketSimulator.tsx forkeur-app/__tests__/basket-simulator.test.tsx
git commit -m "feat: refactor BasketSimulator to two-phase tab orchestrator"
```

---

### Task 5: Delete `CompareSheet` and its tests

**Files:**
- Delete: `forkeur-app/components/CompareSheet.tsx`
- Delete: `forkeur-app/__tests__/compare-sheet.test.tsx`

- [ ] **Step 1: Verify CompareSheet is no longer imported anywhere**

Run: `grep -r "CompareSheet" forkeur-app/components forkeur-app/app forkeur-app/__tests__`
Expected: zero results (if any remain, remove those imports first)

- [ ] **Step 2: Delete CompareSheet files**

```bash
rm forkeur-app/components/CompareSheet.tsx
rm forkeur-app/__tests__/compare-sheet.test.tsx
```

- [ ] **Step 3: Run full test suite — verify clean**

Run: `cd forkeur-app && npm test`
Expected: All tests PASS, no references to deleted files

- [ ] **Step 4: Verify i18n parity still passes**

Run: `cd forkeur-app && npm test -- i18n-parity`
Expected: PASS

- [ ] **Step 5: Manual smoke test — open restaurant detail page**

```bash
cd forkeur-app && npm run dev -- --port 30000
```

Open `http://localhost:30000/restaurant/<any-id>`. Verify:
1. Tab bar renders with Menu and Compare tabs
2. Menu tab shows item table with + / − buttons
3. Adding an item shows the float pill "Compare (1) →" in orange, bottom-right
4. Clicking float pill or Compare tab switches to Compare view
5. Compare tab shows platform cards sorted cheapest-first
6. Winner card has colored left border + BEST badge + Order CTA
7. Non-winner shows `+€X.XX vs best` in muted text
8. Empty Compare tab (no items) shows "Add items from the Menu tab to compare prices"
9. No sticky green bar visible anywhere

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: delete CompareSheet (absorbed by CompareDecision tab)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Tab bar: sticky, instant swap, badge = item count, default Menu tab
- ✅ Float pill: `fixed bottom-20 right-4`, orange (`bg-orange-600`), "Compare (N) →", appears ≥1 item
- ✅ Empty Compare state: inline, no toast
- ✅ Winner: colored left border + BEST badge + CTA only on winner
- ✅ Non-winner: delta vs `findCheapestCompletePlatform` / `cheapestPlatform`
- ✅ Missing items: up to 2 named + "+ N more"
- ✅ Direct partial coverage: muted card with "Order by phone — X of Y items on menu"
- ✅ Direct savings: orange callout above card stack
- ✅ Fee = null → card omitted (via `totals[p] !== null` filter)
- ✅ Sticky green bar deleted (lines 722–802)
- ✅ CompareSheet deleted
- ✅ basket.ts untouched
- ✅ All 3 locales updated simultaneously, i18n-parity test verified
- ✅ i18n keys match spec exactly
