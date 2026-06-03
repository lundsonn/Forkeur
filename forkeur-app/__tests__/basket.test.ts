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
