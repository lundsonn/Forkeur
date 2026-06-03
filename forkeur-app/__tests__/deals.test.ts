import { describe, it, expect } from 'vitest'
import {
  matchesFilter,
  matchesPill,
  filterCounts,
  dealBand,
  sortDeals,
  badgeText,
  qualityScore,
  type DealItem,
  type DealFilter,
} from '@/lib/deals'

type ActiveSet = Set<Exclude<DealFilter, 'all'>>
const s = (...keys: Exclude<DealFilter, 'all'>[]): ActiveSet => new Set(keys)

function deal(overrides: Partial<DealItem>): DealItem {
  return {
    id: Math.random().toString(36).slice(2),
    restaurant_id: 'r',
    restaurant_name: 'Test',
    platform: 'uber_eats',
    cuisine: [],
    area: null,
    rating: null,
    review_count: null,
    promo_type: 'bogo',
    label: '',
    value: null,
    min_order: null,
    ...overrides,
  }
}

describe('matchesPill', () => {
  it('pct folds in abs_discount', () => {
    expect(matchesPill(deal({ promo_type: 'pct_discount' }), 'pct')).toBe(true)
    expect(matchesPill(deal({ promo_type: 'abs_discount' }), 'pct')).toBe(true)
    expect(matchesPill(deal({ promo_type: 'free_delivery' }), 'pct')).toBe(false)
  })
})

describe('matchesFilter', () => {
  it('empty set matches everything', () => {
    expect(matchesFilter(deal({ promo_type: 'free_item' }), s())).toBe(true)
  })
  it('single filter', () => {
    expect(matchesFilter(deal({ promo_type: 'bogo' }), s('bogo'))).toBe(true)
    expect(matchesFilter(deal({ promo_type: 'free_delivery' }), s('bogo'))).toBe(false)
  })
  it('multi-filter: OR logic', () => {
    const d = deal({ promo_type: 'free_delivery' })
    expect(matchesFilter(d, s('bogo', 'free_delivery'))).toBe(true)
    expect(matchesFilter(d, s('bogo', 'pct'))).toBe(false)
  })
})

describe('filterCounts', () => {
  it('counts pct as pct_discount + abs_discount', () => {
    const counts = filterCounts([
      deal({ promo_type: 'pct_discount' }),
      deal({ promo_type: 'abs_discount' }),
      deal({ promo_type: 'bogo' }),
      deal({ promo_type: 'free_delivery' }),
    ])
    expect(counts.all).toBe(4)
    expect(counts.pct).toBe(2)
    expect(counts.bogo).toBe(1)
    expect(counts.free_delivery).toBe(1)
    expect(counts.free_item).toBe(0)
  })
})

describe('dealBand', () => {
  it('bogo and pct>=30 share top band', () => {
    expect(dealBand(deal({ promo_type: 'bogo' }))).toBe(0)
    expect(dealBand(deal({ promo_type: 'pct_discount', value: 30 }))).toBe(0)
    expect(dealBand(deal({ promo_type: 'pct_discount', value: 40 }))).toBe(0)
  })
  it('orders remaining bands', () => {
    expect(dealBand(deal({ promo_type: 'pct_discount', value: 20 }))).toBe(1)
    expect(dealBand(deal({ promo_type: 'free_delivery' }))).toBe(2)
    expect(dealBand(deal({ promo_type: 'free_item' }))).toBe(3)
    expect(dealBand(deal({ promo_type: 'abs_discount', value: 5 }))).toBe(4)
  })
})

describe('qualityScore', () => {
  it('weights rating by log review volume; nulls = 0', () => {
    expect(qualityScore(deal({ rating: null, review_count: null }))).toBe(0)
    const hi = qualityScore(deal({ rating: 4.8, review_count: 1000 }))
    const lo = qualityScore(deal({ rating: 4.8, review_count: 5 }))
    expect(hi).toBeGreaterThan(lo)
  })
})

describe('sortDeals', () => {
  it('single pct: discount value desc, quality tiebreak', () => {
    const a = deal({ promo_type: 'pct_discount', value: 20, rating: 5, review_count: 999 })
    const b = deal({ promo_type: 'pct_discount', value: 50, rating: 3, review_count: 1 })
    const c = deal({ promo_type: 'pct_discount', value: 50, rating: 5, review_count: 999 })
    const out = sortDeals([a, b, c], s('pct'))
    expect(out.map((d) => d.value)).toEqual([50, 50, 20])
    expect(out[0]).toBe(c)
  })

  it('single quality-only filter: quality desc', () => {
    const weak = deal({ promo_type: 'bogo', rating: 3, review_count: 2 })
    const strong = deal({ promo_type: 'bogo', rating: 4.9, review_count: 500 })
    expect(sortDeals([weak, strong], s('bogo'))[0]).toBe(strong)
  })

  it('empty set (all): band asc then quality desc', () => {
    const absDeal = deal({ promo_type: 'abs_discount', value: 5, rating: 5, review_count: 999 })
    const bogoDeal = deal({ promo_type: 'bogo', rating: 1, review_count: 1 })
    const out = sortDeals([absDeal, bogoDeal], s())
    expect(out[0]).toBe(bogoDeal)
  })

  it('multi-select: band asc then quality desc', () => {
    const fd = deal({ promo_type: 'free_delivery', rating: 5, review_count: 999 })
    const bogo = deal({ promo_type: 'bogo', rating: 1, review_count: 1 })
    const out = sortDeals([fd, bogo], s('bogo', 'free_delivery'))
    expect(out[0]).toBe(bogo) // band 0 beats band 2 despite worse quality
  })

  it('is pure (does not mutate input)', () => {
    const input = [deal({ value: 10 }), deal({ value: 20 })]
    const snapshot = [...input]
    sortDeals(input, s('pct'))
    expect(input).toEqual(snapshot)
  })
})

describe('badgeText', () => {
  it('renders per type', () => {
    expect(badgeText(deal({ promo_type: 'bogo' }))).toBe('2-for-1')
    expect(badgeText(deal({ promo_type: 'pct_discount', value: 30 }))).toBe('30% off')
    expect(badgeText(deal({ promo_type: 'abs_discount', value: 4.7 }))).toBe('€4.70 off')
    expect(badgeText(deal({ promo_type: 'free_delivery' }))).toBe('Free delivery')
    expect(badgeText(deal({ promo_type: 'free_item', label: 'Kostenloser Artikel (Zahle 20 €)' }))).toBe('Free item')
  })
})
