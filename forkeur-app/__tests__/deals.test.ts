import { describe, it, expect } from 'vitest'
import { savingsEstimate, sortDeals, matchesFilter, filterCounts, qualityScore } from '@/lib/deals'
import type { DealItem, SortMode, ActiveType, ActivePlatform } from '@/lib/deals'

const baseDeal: DealItem = {
  id: '1',
  restaurant_id: 'r1',
  restaurant_name: 'A',
  platform: 'uber_eats',
  platform_url: null,
  cuisine: [],
  area: null,
  rating: 4.0,
  review_count: 100,
  promo_type: 'pct_discount',
  label: '20% off',
  value: 20,
  min_order: null,
  opening_hours: null,
  is_available: true,
  scraped_at: '2026-06-13T10:00:00Z',
}

describe('savingsEstimate', () => {
  it('pct_discount: returns save string', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'pct_discount', value: 20 }))
      .toBe('Save ~€4.00 on a €20 order')
  })
  it('abs_discount: returns off string', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'abs_discount', value: 3 }))
      .toBe('€3.00 off your order')
  })
  it('free_delivery: returns fee string', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'free_delivery', value: null }))
      .toBe('€0 delivery fee')
  })
  it('bogo: returns null', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'bogo', value: null })).toBeNull()
  })
  it('free_item: returns null', () => {
    expect(savingsEstimate({ ...baseDeal, promo_type: 'free_item', value: null })).toBeNull()
  })
})

describe('sortDeals', () => {
  const a: DealItem = { ...baseDeal, id: 'a', rating: 4.5, value: 10, scraped_at: '2026-06-13T08:00:00Z' }
  const b: DealItem = { ...baseDeal, id: 'b', rating: 3.0, value: 30, scraped_at: '2026-06-13T12:00:00Z' }

  it('newest: sorts by scraped_at desc', () => {
    const sorted = sortDeals([a, b], 'newest')
    expect(sorted[0].id).toBe('b')
  })
  it('rated: sorts by rating desc', () => {
    const sorted = sortDeals([a, b], 'rated')
    expect(sorted[0].id).toBe('a')
  })
  it('saving: sorts by value desc for pct_discount', () => {
    const sorted = sortDeals([a, b], 'saving')
    expect(sorted[0].id).toBe('b')
  })
  it('best: uses qualityScore', () => {
    const hiScore: DealItem = { ...baseDeal, id: 'hi', promo_type: 'bogo', value: null, rating: 4.0 }
    const loScore: DealItem = { ...baseDeal, id: 'lo', promo_type: 'free_delivery', value: null, rating: 1.0 }
    const sorted = sortDeals([loScore, hiScore], 'best')
    expect(sorted[0].id).toBe('hi')
  })
  it('is pure (does not mutate input)', () => {
    const input = [a, b]
    const snapshot = [...input]
    sortDeals(input, 'newest')
    expect(input[0].id).toBe(snapshot[0].id)
  })
})

describe('matchesFilter', () => {
  it('all/all: matches everything', () => {
    expect(matchesFilter(baseDeal, 'all', 'all')).toBe(true)
  })
  it('type filter excludes non-matching promo', () => {
    expect(matchesFilter({ ...baseDeal, promo_type: 'free_delivery' }, 'pct', 'all')).toBe(false)
    expect(matchesFilter({ ...baseDeal, promo_type: 'pct_discount' }, 'pct', 'all')).toBe(true)
  })
  it('platform filter excludes non-matching platform', () => {
    expect(matchesFilter({ ...baseDeal, platform: 'deliveroo' }, 'all', 'uber_eats')).toBe(false)
    expect(matchesFilter({ ...baseDeal, platform: 'uber_eats' }, 'all', 'uber_eats')).toBe(true)
  })
  it('both filters combined', () => {
    const d: DealItem = { ...baseDeal, promo_type: 'bogo', platform: 'deliveroo' }
    expect(matchesFilter(d, 'bogo', 'deliveroo')).toBe(true)
    expect(matchesFilter(d, 'bogo', 'uber_eats')).toBe(false)
    expect(matchesFilter(d, 'pct', 'deliveroo')).toBe(false)
  })
})

describe('filterCounts', () => {
  const deals: DealItem[] = [
    { ...baseDeal, id: '1', promo_type: 'pct_discount', platform: 'uber_eats' },
    { ...baseDeal, id: '2', promo_type: 'abs_discount', platform: 'deliveroo' },
    { ...baseDeal, id: '3', promo_type: 'bogo', platform: 'uber_eats' },
    { ...baseDeal, id: '4', promo_type: 'free_delivery', platform: 'takeaway' },
    { ...baseDeal, id: '5', promo_type: 'free_item', platform: 'deliveroo' },
  ]

  it('all: counts all deals', () => {
    const counts = filterCounts(deals, 'all')
    expect(counts.all).toBe(5)
    expect(counts.pct).toBe(1)
    expect(counts.abs).toBe(1)
    expect(counts.bogo).toBe(1)
    expect(counts.free_delivery).toBe(1)
    expect(counts.free_item).toBe(1)
  })

  it('platform filter narrows counts', () => {
    const counts = filterCounts(deals, 'uber_eats')
    expect(counts.all).toBe(2)
    expect(counts.pct).toBe(1)
    expect(counts.bogo).toBe(1)
    expect(counts.free_delivery).toBe(0)
  })
})

describe('qualityScore', () => {
  it('bogo scores 30 base + rating bonus', () => {
    const score = qualityScore({ ...baseDeal, promo_type: 'bogo', value: null, rating: 4.0 })
    expect(score).toBe(30 + 4.0 * 2)
  })
  it('pct_discount: value*2 + rating*2', () => {
    const score = qualityScore({ ...baseDeal, promo_type: 'pct_discount', value: 20, rating: 4.0 })
    expect(score).toBe(20 * 2 + 4.0 * 2)
  })
  it('nulls score 0 for that component', () => {
    const score = qualityScore({ ...baseDeal, promo_type: 'free_delivery', value: null, rating: null })
    expect(score).toBe(15)
  })
})
