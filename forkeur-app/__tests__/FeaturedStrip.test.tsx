import { describe, it, expect } from 'vitest'
import { selectFeatured } from '../components/FeaturedStrip'
import type { DealItem } from '../lib/deals'

const base: DealItem = {
  id: '1', restaurant_id: 'r1', restaurant_name: 'A', platform: 'uber_eats',
  platform_url: null, cuisine: [], area: null, rating: 4.0, review_count: 100,
  promo_type: 'pct_discount', label: '20% off', value: 20, min_order: null,
  opening_hours: null, is_available: true, scraped_at: '2026-06-13T10:00:00Z',
}

describe('selectFeatured', () => {
  it('returns empty if fewer than 2 qualifying deals', () => {
    const result = selectFeatured([{ ...base, promo_type: 'pct_discount' }])
    expect(result).toHaveLength(0)
  })

  it('selects top pct deal, top free_delivery, top bogo; dedupes by restaurant', () => {
    const deals: DealItem[] = [
      { ...base, id: '1', restaurant_id: 'r1', promo_type: 'pct_discount', value: 30 },
      { ...base, id: '2', restaurant_id: 'r2', promo_type: 'free_delivery', value: null, rating: 4.5 },
      { ...base, id: '3', restaurant_id: 'r3', promo_type: 'bogo', value: null },
    ]
    const result = selectFeatured(deals)
    expect(result.map(d => d.id)).toEqual(['1', '2', '3'])
  })

  it('dedupes: skips second deal from same restaurant', () => {
    const deals: DealItem[] = [
      { ...base, id: '1', restaurant_id: 'r1', promo_type: 'pct_discount', value: 30 },
      { ...base, id: '2', restaurant_id: 'r1', promo_type: 'free_delivery', value: null },
      { ...base, id: '3', restaurant_id: 'r2', promo_type: 'bogo', value: null },
    ]
    const result = selectFeatured(deals)
    const ids = result.map(d => d.id)
    expect(ids).not.toContain('2')
    expect(ids).toContain('1')
    expect(ids).toContain('3')
  })

  it('returns empty (not <2 shown) when only 1 slot fills', () => {
    const deals: DealItem[] = [
      { ...base, id: '1', restaurant_id: 'r1', promo_type: 'pct_discount', value: 30 },
    ]
    expect(selectFeatured(deals)).toHaveLength(0)
  })
})
