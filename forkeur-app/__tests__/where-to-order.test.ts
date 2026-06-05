// __tests__/where-to-order.test.ts
import { describe, it, expect } from 'vitest'
import { computeFeeRows, computeDirectSavingsCents } from '../lib/where-to-order'
import type { Platform } from '../lib/basket'
import type { PlatformListing } from '../lib/queries'

function listing(
  platform: Platform,
  delivery_fee_cents: number | null
): PlatformListing {
  return {
    id: `id-${platform}`,
    platform,
    platform_url: null,
    url_type: null,
    delivery_fee_cents,
    delivery_fee_label: null,
    min_order_cents: null,
    min_order_label: null,
    eta_label: null,
    rating: null,
    last_scraped_at: null,
    is_available: true,
    opening_hours: null,
    promotions: [],
  }
}

describe('computeFeeRows', () => {
  it('returns empty array when no listings have a fee', () => {
    expect(computeFeeRows([])).toEqual([])
    expect(
      computeFeeRows([listing('uber_eats', null), listing('deliveroo', null)])
    ).toEqual([])
  })

  it('orders ascending by fee, sets delta and cheapest flag', () => {
    const rows = computeFeeRows([
      listing('uber_eats', 350),
      listing('deliveroo', 200),
      listing('takeaway', 500),
    ])
    expect(rows.map((r) => r.platform)).toEqual([
      'deliveroo',
      'uber_eats',
      'takeaway',
    ])
    expect(rows.map((r) => r.feeCents)).toEqual([200, 350, 500])
    expect(rows.map((r) => r.deltaCents)).toEqual([0, 150, 300])
    expect(rows.map((r) => r.isCheapest)).toEqual([true, false, false])
  })

  it('excludes listings with null fee', () => {
    const rows = computeFeeRows([
      listing('uber_eats', 350),
      listing('deliveroo', null),
      listing('takeaway', 500),
    ])
    expect(rows.map((r) => r.platform)).toEqual(['uber_eats', 'takeaway'])
  })

  it('includes direct only when it has a real (non-null) fee', () => {
    const withoutDirectFee = computeFeeRows([
      listing('uber_eats', 350),
      listing('direct', null),
    ])
    expect(withoutDirectFee.map((r) => r.platform)).toEqual(['uber_eats'])

    const withDirectFee = computeFeeRows([
      listing('uber_eats', 350),
      listing('direct', 0),
    ])
    expect(withDirectFee.map((r) => r.platform)).toEqual(['direct', 'uber_eats'])
    expect(withDirectFee[0].feeCents).toBe(0)
    expect(withDirectFee[0].isCheapest).toBe(true)
  })

  it('breaks fee ties by PLATFORMS order (uber_eats before deliveroo)', () => {
    const rows = computeFeeRows([
      listing('deliveroo', 300),
      listing('uber_eats', 300),
    ])
    expect(rows.map((r) => r.platform)).toEqual(['uber_eats', 'deliveroo'])
    expect(rows[0].isCheapest).toBe(true)
    expect(rows[1].isCheapest).toBe(false)
    expect(rows.map((r) => r.deltaCents)).toEqual([0, 0])
  })
})

describe('computeDirectSavingsCents', () => {
  it('returns null when there are no aggregator fees', () => {
    expect(computeDirectSavingsCents([])).toBeNull()
    expect(computeDirectSavingsCents([listing('direct', 0)])).toBeNull()
  })

  it('computes mean(aggregator fees) - direct fee', () => {
    // mean(400,600,500)=500, direct=0 -> 500
    const result = computeDirectSavingsCents([
      listing('uber_eats', 400),
      listing('deliveroo', 600),
      listing('takeaway', 500),
      listing('direct', 0),
    ])
    expect(result).toBe(500)
  })

  it('treats missing direct fee as 0', () => {
    // mean(400,600)=500, direct missing -> 500
    const result = computeDirectSavingsCents([
      listing('uber_eats', 400),
      listing('deliveroo', 600),
    ])
    expect(result).toBe(500)
  })

  it('subtracts a real direct fee', () => {
    // mean(400,600)=500, direct=200 -> 300
    const result = computeDirectSavingsCents([
      listing('uber_eats', 400),
      listing('deliveroo', 600),
      listing('direct', 200),
    ])
    expect(result).toBe(300)
  })

  it('returns null when result is below the €1.50 floor', () => {
    // mean(140,140)=140 < 150 -> null
    expect(
      computeDirectSavingsCents([
        listing('uber_eats', 140),
        listing('deliveroo', 140),
      ])
    ).toBeNull()
    // exactly 149 -> null (strictly below 150 rejected; 150 itself allowed)
    expect(
      computeDirectSavingsCents([listing('uber_eats', 149)])
    ).toBeNull()
    expect(computeDirectSavingsCents([listing('uber_eats', 150)])).toBe(150)
  })

  it('ignores null aggregator fees in the mean', () => {
    // only uber_eats (400) counts; mean=400, direct=0 -> 400
    const result = computeDirectSavingsCents([
      listing('uber_eats', 400),
      listing('deliveroo', null),
      listing('takeaway', null),
    ])
    expect(result).toBe(400)
  })
})
