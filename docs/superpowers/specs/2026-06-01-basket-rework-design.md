# Basket rework — design spec
**Date:** 2026-06-01  
**Scope:** Restaurant detail page only. Home screen unchanged.

---

## Goal

Rework the restaurant detail / basket UX to match the Forkeur core-flow mockup:
inline qty steppers on menu rows, a persistent sticky basket bar, and a slide-up compare sheet.

---

## What changes

### 1. Menu rows — inline qty stepper

**File:** `forkeur-app/components/PlatformPriceRow.tsx`

- When item qty = 0: render a `+` pill (current behavior)
- When item qty ≥ 1: replace `+` pill with `− qty +` stepper pill
- `−` calls `onRemove(item)` (new prop), `+` calls `onAdd(item)` (existing)
- Item name rendered slightly bolder (`font-medium`) when qty ≥ 1
- No other layout changes to the row

**New props on PlatformPriceRow:**
```ts
qty: number          // 0 = not in basket
onAdd: () => void    // existing
onRemove: () => void // new
```

---

### 2. Sticky basket bar

**File:** `forkeur-app/components/BasketSimulator.tsx` (inline, no new file)

Replaces `StickyOrderBar`. Rendered as a fixed bar pinned to viewport bottom.

- **Visible only** when `basket.length > 0`
- **Left side:** `{n} item{s} · €{subtotal}` (stone-400 small + stone-900 bold)
- **Right side:** `Best: {Platform} €{total}` — platform name in its brand color (orange for Takeaway, green for UberEats, cyan for Deliveroo)
- **Tap anywhere on bar** → sets `sheetOpen = true`
- Background: `bg-stone-900`, text white, rounded-2xl, `mx-5 mb-5` so it floats above page
- Transition: `translate-y-full` → `translate-y-0` with `transition-transform duration-200`

---

### 3. Compare sheet

**File:** `forkeur-app/components/CompareSheet.tsx` (new component)

A bottom sheet rendered inside `BasketSimulator`, controlled by `sheetOpen` state.

**Structure:**
```
Backdrop (bg-black/40, tap to close)
└── Sheet panel (bg-white, rounded-t-2xl, fixed bottom-0 inset-x-0, max-w-md mx-auto)
    ├── Drag handle (w-10 h-1 bg-stone-200 mx-auto mt-3 mb-4 rounded-full)
    ├── "BEST RIGHT NOW" label
    ├── Winner row: colored dot + platform name (text-2xl font-bold) + "Cheapest and fastest right now."
    ├── Metrics row: Total · Delivery · You save (green)
    ├── Divider
    ├── "ALL THREE · LIVE PRICES" label
    ├── Platform rows (sorted cheapest first):
    │   dot · name · [Best badge if winner] · eta · total
    │   winner: stone-900 font-semibold; others: stone-500
    ├── Why blurb: "Why {Platform}? Lowest total including all fees." (stone-400 text-xs)
    └── CTA: blue "Order on {Platform} →" button (links to platform_url, opens new tab)
```

**Dismiss:** tap backdrop OR swipe down (pointer delta > 80px down).

**Props:**
```ts
platform: Platform
total: number
eta: string | null
savings: number | null       // max(otherTotals) - cheapestTotal, null if no savings
platformUrl: string | null
sortedByTotal: { platform: Platform; total: number | null; eta: string | null }[]
cheapestPlatform: Platform
onClose: () => void
```

---

### 4. BasketSimulator cleanup

**File:** `forkeur-app/components/BasketSimulator.tsx`

**Remove:**
- Basket chip / swipe-to-clear row at top
- Entire recommendation section (Best right now, metrics, Compare all three collapsible)
- `StickyOrderBar` import and usage
- `compareOpen` state

**Add:**
- `sheetOpen` state (boolean)
- Sticky bar (section 2 above)
- `<CompareSheet>` rendered when `sheetOpen && cheapestPlatform`
- Pass `onRemove` down to `PlatformPriceRow`
- `removeItem` handler: decrease qty by 1, remove from basket if qty reaches 0

**Remove file:**
- `forkeur-app/components/StickyOrderBar.tsx` — no longer used

---

## Data / logic — no backend changes

All changes are client-side. `lib/basket.ts` and `lib/queries.ts` unchanged.

New derived value needed in BasketSimulator:
```ts
// Use the item's cheapest available price across platforms for the subtotal display.
// This avoids showing €0 when an item has no price on the winning platform.
const subtotalCents = useMemo(
  () => basket.reduce((sum, b) => {
    const prices = PLATFORMS.map((p) => b.prices[p]).filter((v): v is number => v !== null)
    const price = prices.length ? Math.min(...prices) : 0
    return sum + price * b.qty
  }, 0),
  [basket]
)
```

Savings = `max(otherTotals) - cheapestTotal` (already computed, rename `elsewhereMax - cheapestTotal`).

---

## Scope boundaries

- Home page: **no changes**
- Restaurant detail header: **no changes**
- Backend / DB: **no changes**
- `lib/basket.ts`, `lib/queries.ts`: **no changes**
