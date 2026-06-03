// __tests__/basket.test.ts
import { describe, it, expect } from 'vitest'
import {
  calculatePlatformTotal,
  calculateAllTotals,
  findCheapestPlatform,
  centsToEuro,
  computeDirectOverlap,
  computeDirectSubtotal,
  computeDirectSavingsCents,
  computeDirectOverlapFromMenu,
  computeDirectSubtotalFromMenu,
  computeDirectSavingsCentsFromMenu,
  type BasketItem,
  type PlatformTotals,
  type PlatformFees,
  type MenuItemDirectPrice,
} from '../lib/basket'

const twoItems: BasketItem[] = [
  {
    name: 'Big Mac',
    qty: 1,
    prices: { uber_eats: 660, deliveroo: 640, takeaway: 620, direct: null },
  },
  {
    name: 'Large Fries',
    qty: 2,
    prices: { uber_eats: 350, deliveroo: 320, takeaway: 340, direct: null },
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
      { name: 'Big Mac', qty: 1, prices: { uber_eats: null, deliveroo: 640, takeaway: 620, direct: null } },
    ]
    // uber_eats: 0 (skipped) + 299 delivery = 299
    expect(calculatePlatformTotal(items, 'uber_eats', 299)).toBe(299)
  })

  it('handles empty basket — returns just delivery fee', () => {
    expect(calculatePlatformTotal([], 'uber_eats', 399)).toBe(399)
  })

  it('sums only available items when multiple have null prices', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 100, deliveroo: null, takeaway: null, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: null, deliveroo: 200, takeaway: 300, direct: null } },
      { name: 'C', qty: 2, prices: { uber_eats: 150, deliveroo: 160, takeaway: 170, direct: null } },
    ]
    // uber_eats: 100 + 0 (skipped) + 150*2 + 399 = 799
    expect(calculatePlatformTotal(items, 'uber_eats', 399)).toBe(799)
    // deliveroo: 0 (skipped) + 200 + 160*2 + 299 = 819
    expect(calculatePlatformTotal(items, 'deliveroo', 299)).toBe(819)
  })
})

describe('findCheapestPlatform', () => {
  it('returns platform with lowest total', () => {
    const totals: PlatformTotals = { uber_eats: 1759, deliveroo: 1459, takeaway: 1139, direct: null }
    expect(findCheapestPlatform(totals)).toBe('takeaway')
  })

  it('returns null when all totals are null', () => {
    expect(findCheapestPlatform({ uber_eats: null, deliveroo: null, takeaway: null, direct: null })).toBeNull()
  })

  it('ignores null platforms when comparing', () => {
    const totals: PlatformTotals = { uber_eats: null, deliveroo: 1459, takeaway: null, direct: null }
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

const standardFees: PlatformFees = {
  uber_eats: 249,
  deliveroo: 199,
  takeaway: 299,
  direct: null,
}

describe('computeDirectOverlap', () => {
  it('below threshold: fewer than 3 matched items', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
    ]
    const result = computeDirectOverlap(items)
    expect(result.thresholdMet).toBe(false)
    expect(result.matchedCount).toBe(2)
  })

  it('threshold met: exactly 3 matched items, 100% basket', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
      { name: 'C', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 } },
    ]
    expect(computeDirectOverlap(items).thresholdMet).toBe(true)
  })

  it('boundary: 3 matched out of 6 = exactly 50%', () => {
    const m = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 }
    const u = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null }
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: m },
      { name: 'B', qty: 1, prices: m },
      { name: 'C', qty: 1, prices: m },
      { name: 'D', qty: 1, prices: u },
      { name: 'E', qty: 1, prices: u },
      { name: 'F', qty: 1, prices: u },
    ]
    expect(computeDirectOverlap(items).thresholdMet).toBe(true)
  })

  it('below threshold: 3 matched out of 7 < 50%', () => {
    const m = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 }
    const u = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null }
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: m },
      { name: 'B', qty: 1, prices: m },
      { name: 'C', qty: 1, prices: m },
      { name: 'D', qty: 1, prices: u },
      { name: 'E', qty: 1, prices: u },
      { name: 'F', qty: 1, prices: u },
      { name: 'G', qty: 1, prices: u },
    ]
    expect(computeDirectOverlap(items).thresholdMet).toBe(false)
  })

  it('ignores items with qty=0', () => {
    const m = { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: 500 }
    const items: BasketItem[] = [
      { name: 'A', qty: 0, prices: m },
      { name: 'B', qty: 1, prices: m },
      { name: 'C', qty: 1, prices: m },
      { name: 'D', qty: 1, prices: m },
    ]
    const result = computeDirectOverlap(items)
    expect(result.basketCount).toBe(3)
    expect(result.matchedCount).toBe(3)
  })
})

describe('computeDirectSubtotal', () => {
  it('sums price * qty for items with direct prices, skips others', () => {
    const items: BasketItem[] = [
      { name: 'A', qty: 2, prices: { uber_eats: 100, deliveroo: 100, takeaway: 100, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 100, deliveroo: 100, takeaway: 100, direct: null } },
    ]
    expect(computeDirectSubtotal(items)).toBe(1000)
  })
})

describe('computeDirectSavingsCents — three alert states', () => {
  const makeItems = (directPrices: number[]): BasketItem[] =>
    directPrices.map((d, i) => ({
      name: `Item${i}`,
      qty: 1,
      prices: { uber_eats: 1000, deliveroo: 900, takeaway: 1100, direct: d },
    }))

  it('state 1: direct cheaper + threshold met → positive savings', () => {
    // 3 items: direct=600 each, cheapest platform=deliveroo: 3*900+199=2899, direct=3*600=1800
    const items = makeItems([600, 600, 600])
    const savings = computeDirectSavingsCents(items, standardFees)
    expect(savings).toBe(2899 - 1800)  // 1099
  })

  it('state 2: direct same/higher + threshold met → null', () => {
    // 3 items: direct=1200 each → direct subtotal > cheapest platform total
    const items = makeItems([1200, 1200, 1200])
    expect(computeDirectSavingsCents(items, standardFees)).toBeNull()
  })

  it('state 3: below threshold → null regardless of price', () => {
    // Only 2 matched items
    const items: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 900, takeaway: 1100, direct: 500 } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 900, takeaway: 1100, direct: 500 } },
    ]
    expect(computeDirectSavingsCents(items, standardFees)).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Menu-item-aware helpers
// ---------------------------------------------------------------------------

/** Build a MenuItemDirectPrice with all platforms priced the same unless overridden. */
function makeMenuItem(
  name: string,
  directCents: number | null,
  otherCents = 1000
): MenuItemDirectPrice {
  return {
    name,
    prices: {
      uber_eats: otherCents,
      deliveroo: otherCents,
      takeaway: otherCents,
      direct: directCents,
    },
  }
}

describe('computeDirectOverlapFromMenu', () => {
  it('3 items, 2 have direct → { directCount: 2, totalCount: 3 }', () => {
    const basket: BasketItem[] = [
      { name: 'Burger', qty: 1, prices: { uber_eats: 800, deliveroo: 800, takeaway: 800, direct: null } },
      { name: 'Fries',  qty: 1, prices: { uber_eats: 300, deliveroo: 300, takeaway: 300, direct: null } },
      { name: 'Drink',  qty: 1, prices: { uber_eats: 250, deliveroo: 250, takeaway: 250, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('Burger', 700),
      makeMenuItem('Fries',  280),
      makeMenuItem('Drink',  null),   // no direct price
    ]
    const result = computeDirectOverlapFromMenu(basket, menu)
    expect(result).toEqual({ directCount: 2, totalCount: 3 })
  })

  it('all items have direct → { directCount: 3, totalCount: 3 }', () => {
    const basket: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
      { name: 'C', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 400),
      makeMenuItem('B', 400),
      makeMenuItem('C', 400),
    ]
    expect(computeDirectOverlapFromMenu(basket, menu)).toEqual({ directCount: 3, totalCount: 3 })
  })

  it('matching is case-insensitive', () => {
    const basket: BasketItem[] = [
      { name: 'big mac', qty: 1, prices: { uber_eats: 600, deliveroo: 600, takeaway: 600, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [makeMenuItem('Big Mac', 500)]
    expect(computeDirectOverlapFromMenu(basket, menu).directCount).toBe(1)
  })

  it('items with qty=0 are excluded from totalCount', () => {
    const basket: BasketItem[] = [
      { name: 'A', qty: 0, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [makeMenuItem('A', 400), makeMenuItem('B', 400)]
    const result = computeDirectOverlapFromMenu(basket, menu)
    expect(result).toEqual({ directCount: 1, totalCount: 1 })
  })
})

describe('computeDirectSubtotalFromMenu', () => {
  it('returns correct sum of (price * qty) in euros for items with direct price', () => {
    // Item A: 500 cents * 2 = 1000 cents = €10.00
    // Item B: no direct price — excluded
    const basket: BasketItem[] = [
      { name: 'A', qty: 2, prices: { uber_eats: 600, deliveroo: 600, takeaway: 600, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 600, deliveroo: 600, takeaway: 600, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 500),
      makeMenuItem('B', null),
    ]
    expect(computeDirectSubtotalFromMenu(basket, menu)).toBeCloseTo(10.0)
  })

  it('returns null when no direct prices exist in menu', () => {
    const basket: BasketItem[] = [
      { name: 'X', qty: 2, prices: { uber_eats: 600, deliveroo: 600, takeaway: 600, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [makeMenuItem('X', null)]
    expect(computeDirectSubtotalFromMenu(basket, menu)).toBeNull()
  })

  it('returns null when basket items have no matching menu entry', () => {
    const basket: BasketItem[] = [
      { name: 'Unknown Item', qty: 1, prices: { uber_eats: 600, deliveroo: 600, takeaway: 600, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [makeMenuItem('Something Else', 400)]
    expect(computeDirectSubtotalFromMenu(basket, menu)).toBeNull()
  })

  it('accounts for qty > 1', () => {
    const basket: BasketItem[] = [
      { name: 'Pizza', qty: 3, prices: { uber_eats: 1200, deliveroo: 1200, takeaway: 1200, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [makeMenuItem('Pizza', 1000)]
    // 1000 cents * 3 = 3000 cents = €30.00
    expect(computeDirectSubtotalFromMenu(basket, menu)).toBeCloseTo(30.0)
  })
})

describe('computeDirectSavingsCentsFromMenu', () => {
  // platformTotals: totals in euros including delivery
  const platformTotals: Record<import('../lib/basket').Platform, number | null> = {
    uber_eats:  28.99,
    deliveroo:  26.99,   // cheapest non-direct
    takeaway:   30.99,
    direct:     null,
  }

  it('threshold met, direct cheaper → positive savings in cents', () => {
    // direct subtotal = 3 items * 500 cents = €15.00
    // cheapest non-direct = €26.99 → savings = €11.99 = 1199 cents
    const basket: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'C', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 500),
      makeMenuItem('B', 500),
      makeMenuItem('C', 500),
    ]
    const savings = computeDirectSavingsCentsFromMenu(basket, menu, platformTotals)
    expect(savings).toBe(1199)
  })

  it('threshold met, direct more expensive → negative savings in cents', () => {
    // direct subtotal = 3 items * 1500 cents = €45.00 > deliveroo €26.99
    const basket: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'C', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 1500),
      makeMenuItem('B', 1500),
      makeMenuItem('C', 1500),
    ]
    const savings = computeDirectSavingsCentsFromMenu(basket, menu, platformTotals)
    expect(savings).toBeLessThan(0)
    // (26.99 - 45.00) * 100 = -1801
    expect(savings).toBe(-1801)
  })

  it('exactly 3 items / 50% threshold boundary → meets threshold', () => {
    // 6 items total, 3 have direct prices (exactly 50%)
    const basket: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'C', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'D', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'E', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'F', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 500),
      makeMenuItem('B', 500),
      makeMenuItem('C', 500),
      makeMenuItem('D', null),   // no direct
      makeMenuItem('E', null),
      makeMenuItem('F', null),
    ]
    // directCount=3, totalCount=6 → exactly 50% → threshold met
    // direct subtotal = 3 * 500 cents = €15.00; cheapest non-direct = €26.99
    const savings = computeDirectSavingsCentsFromMenu(basket, menu, platformTotals)
    expect(savings).not.toBeNull()
    expect(savings).toBeGreaterThan(0)
  })

  it('2 items (< 3) → null (below count threshold)', () => {
    const basket: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 500),
      makeMenuItem('B', 500),
    ]
    expect(computeDirectSavingsCentsFromMenu(basket, menu, platformTotals)).toBeNull()
  })

  it('3 items but only 1 has direct (33%) → null (below 50% ratio)', () => {
    const basket: BasketItem[] = [
      { name: 'A', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'B', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
      { name: 'C', qty: 1, prices: { uber_eats: 1000, deliveroo: 1000, takeaway: 1000, direct: null } },
    ]
    const menu: MenuItemDirectPrice[] = [
      makeMenuItem('A', 500),
      makeMenuItem('B', null),
      makeMenuItem('C', null),
    ]
    // directCount=1, totalCount=3 → 33% < 50% → null
    expect(computeDirectSavingsCentsFromMenu(basket, menu, platformTotals)).toBeNull()
  })
})
