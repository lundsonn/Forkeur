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
  type BasketItem,
  type PlatformTotals,
  type PlatformFees,
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
