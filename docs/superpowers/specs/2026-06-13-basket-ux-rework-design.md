# Basket UX Rework — Two-Phase Tab Flow

**Date:** 2026-06-13  
**Status:** Approved  
**Scope:** `forkeur-app/components/BasketSimulator.tsx` and related files

## Problem

The current `BasketSimulator.tsx` (831 lines) conflates four responsibilities: menu browsing, price comparison matrix, basket state, and URL sync. The UX consequence:

1. Dense 4-column `text-xs` price table is hard to scan on mobile
2. Sticky bar shows cheapest platform + total but no relative context (how much cheaper?)
3. Full platform breakdown requires two interactions: tap bar → CompareSheet
4. Direct savings banner is disconnected from the decision moment
5. No visual separation between "I'm browsing" and "I'm deciding where to order"

## Chosen Direction: Two-Phase Tab Flow

Split the simulator into two tabs — **Menu** (browse + add) and **Compare** (decision). Each tab has one job. The user navigates between them deliberately.

## Architecture

### Component split

| File | Responsibility |
|---|---|
| `BasketSimulator.tsx` | Thin orchestrator: basket state, URL sync, tab routing |
| `MenuBrowser.tsx` | Menu tab: category sections, item rows, qty steppers, search |
| `CompareDecision.tsx` | Compare tab: platform cards, totals, coverage, CTAs |

`CompareSheet.tsx` (bottom sheet) retires — its role is absorbed by the Compare tab.  
`basket.ts` pure functions are untouched.

### State (all in orchestrator)

```ts
const [items, setItems] = useState<BasketItem[]>([])  // unchanged shape
const [activeTab, setActiveTab] = useState<'menu' | 'compare'>('menu')
// URL sync: ?basket=name:qty,name:qty,...  (unchanged)
```

## Tab Bar

Sticky below restaurant nav, instant swap (no animation):

```
[ 🍴 Menu ]  [ ⚖ Compare (3) ]
```

- Badge on Compare = item count; hidden when 0
- Default: Menu tab
- Empty basket + Compare tap → show inline empty state on Compare tab ("Add items from the Menu tab to compare prices"); no floating toast
- No forced auto-switch on item add

## Menu Tab (`MenuBrowser.tsx`)

Keeps existing structure with cleanup:

- Category headers + item rows unchanged
- Dense 4-column price table retained (useful context while browsing)
- Qty stepper inline per row (existing `+`/`-` buttons)
- Search filter at top
- DishModal (bottom sheet for item detail) retained, triggered on item name tap
- **Sticky green bar removed** — Compare tab owns that job
- **Floating pill** (viewport-fixed, `fixed bottom-20 right-4`, orange `#ea580c`): "Compare (3) →" appears once basket has ≥1 item; taps to Compare tab

### Code changes

Strip sticky bar render + CompareSheet trigger from current `BasketSimulator.tsx`. Move item-list JSX to `MenuBrowser.tsx`.

## Compare Tab (`CompareDecision.tsx`)

Full-height stack of platform cards, sorted cheapest-first.

### Winner card

```
┌─────────────────────────────────────┐
│ ● Uber Eats              BEST  ★    │  ← colored left border + badge
│ €14.90 total                        │
│ Delivery €1.99 · ~25 min            │
│ 5/5 items priced        [Order →]  │  ← CTA only on winner
└─────────────────────────────────────┘
```

### Non-winner card

```
┌─────────────────────────────────────┐
│ ● Deliveroo                         │
│ €16.40 total  (+€1.50 vs best)     │  ← delta in muted text
│ Delivery €2.49 · ~30 min            │
│ 4/5 items ⚠ missing: Phở bò        │  ← incomplete coverage: list missing items
└─────────────────────────────────────┘
```

### Rules

- Winner: colored left border + "BEST" badge + visible CTA button
- Non-winners: delta vs cheapest complete-coverage platform (`findCheapestCompletePlatform`) in muted text; no CTA (reduces noise)
- Coverage incomplete: list missing item names (up to 2; "+ N more" if beyond 2), not just count
- `direct` platform: if overlap threshold not met, show "Order by phone — X of Y items on menu" in muted/disabled state
- Direct savings (threshold met): orange callout **above** card stack — "Save €3.20 ordering direct"
- Platform unavailable (fee = null): card omitted entirely
- Empty basket: centered "Add items from the Menu tab to compare prices" with arrow pointing at Menu tab

### Platform colors (from `basket.ts`)

| Platform | Color |
|---|---|
| uber_eats | green-500 |
| deliveroo | cyan-500 |
| takeaway | orange-500 |
| direct | violet-500 |

## i18n

All new strings must be added to `messages/en.json`, `messages/fr.json`, `messages/nl.json` simultaneously.

New keys under `BasketSimulator`:

| Key | EN |
|---|---|
| `tab.menu` | Menu |
| `tab.compare` | Compare |
| `compareFloat` | Compare ({count}) |
| `addItemsFirst` | Add items first |
| `emptyCompare` | Add items from the Menu tab to compare prices |
| `bestBadge` | BEST |
| `orderOn` | Order on {platform} |
| `missingItems` | Missing: {items} |
| `deltaVsBest` | +{amount} vs best |
| `directSavings` | Save {amount} ordering direct |
| `directPartialCoverage` | Order by phone — {matched} of {total} items on menu |

## Out of scope

- Menu tab price table redesign (dense 4-column stays)
- DishModal redesign
- Basket persistence beyond URL sync + localStorage (unchanged)
- Any backend / scraper changes
- Deals page

## Files touched

```
forkeur-app/
├── components/
│   ├── BasketSimulator.tsx     ← strip to orchestrator
│   ├── MenuBrowser.tsx         ← new
│   ├── CompareDecision.tsx     ← new
│   └── CompareSheet.tsx        ← delete
├── messages/
│   ├── en.json                 ← new keys
│   ├── fr.json                 ← new keys
│   └── nl.json                 ← new keys
└── lib/
    └── basket.ts               ← untouched
```
