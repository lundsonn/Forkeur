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
    expect(savingsVsNext([ue, tw])).toBeNull()
  })

  it('returns delta and vs-platform when 2 non-null listings', () => {
    const result = savingsVsNext([ue, dl])
    expect(result).toEqual({ cents: 100, vs: 'deliveroo' })
  })

  it('returns null when effectiveTotals are equal', () => {
    const same = { platform: 'deliveroo' as Platform, delivery_fee_cents: 199, min_order_cents: 0 }
    expect(savingsVsNext([ue, same])).toBeNull()
  })

  it('picks cheapest as winner regardless of input order', () => {
    // dl is more expensive; ue should be the cheapest regardless of order
    const result = savingsVsNext([dl, ue])
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
    const low = makeRestaurant({
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 50, delivery_fee_cents: 199, min_order_cents: 0 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
        { platform: 'deliveroo', delivery_fee_cents: 249, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
      ]
    })
    const high = makeRestaurant({
      id: '2',
      name: 'Best',
      cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 300, delivery_fee_cents: 199, min_order_cents: 0 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: 0, eta_min: 30, is_available: true, opening_hours: null },
        { platform: 'deliveroo', delivery_fee_cents: 499, min_order_cents: 0, eta_min: 35, is_available: true, opening_hours: null },
      ]
    })
    const result = findBestSavingExample([low, high])
    expect(result?.restaurant.id).toBe('2')
  })

  it('returns null when effective-total delta is zero despite positive savings_cents', () => {
    // savings_cents > 0 but min_order_cents equalizes the totals
    const r = makeRestaurant({
      cheapest: { platform: 'deliveroo', fee_label: '€0.50', savings_cents: 50, delivery_fee_cents: 50, min_order_cents: 250 },
      listings: [
        { platform: 'uber_eats', delivery_fee_cents: 100, min_order_cents: 200, eta_min: 30, is_available: true, opening_hours: null },  // total 300
        { platform: 'deliveroo', delivery_fee_cents: 50,  min_order_cents: 250, eta_min: 35, is_available: true, opening_hours: null },  // total 300
      ],
    })
    // effective totals are equal (300 = 300), so delta is 0, must return null
    expect(findBestSavingExample([r])).toBeNull()
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
