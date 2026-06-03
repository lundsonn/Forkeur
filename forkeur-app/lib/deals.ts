import type { Platform } from './basket'

export type DealType =
  | 'free_delivery'
  | 'bogo'
  | 'pct_discount'
  | 'abs_discount'
  | 'free_item'

export type DealItem = {
  id: string
  restaurant_id: string
  restaurant_name: string
  platform: Platform
  cuisine: string[]
  area: string | null
  rating: number | null
  review_count: number | null
  promo_type: DealType
  label: string
  value: number | null
  min_order: number | null
}

/** Active filter pills. `pct` covers both pct_discount and abs_discount. */
export type DealFilter = 'all' | 'bogo' | 'pct' | 'free_delivery' | 'free_item'

export const DEAL_FILTERS: { key: DealFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'bogo', label: '2-for-1' },
  { key: 'pct', label: '% Off' },
  { key: 'free_delivery', label: 'Free Delivery' },
  { key: 'free_item', label: 'Free Item' },
]

/** Does a deal belong under the given filter pill? */
export function matchesFilter(d: DealItem, filter: DealFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'pct') return d.promo_type === 'pct_discount' || d.promo_type === 'abs_discount'
  return d.promo_type === filter
}

/** Live counts per filter pill. */
export function filterCounts(deals: DealItem[]): Record<DealFilter, number> {
  const counts: Record<DealFilter, number> = {
    all: deals.length,
    bogo: 0,
    pct: 0,
    free_delivery: 0,
    free_item: 0,
  }
  for (const d of deals) {
    if (matchesFilter(d, 'bogo')) counts.bogo++
    if (matchesFilter(d, 'pct')) counts.pct++
    if (matchesFilter(d, 'free_delivery')) counts.free_delivery++
    if (matchesFilter(d, 'free_item')) counts.free_item++
  }
  return counts
}

/** Restaurant-quality tiebreaker: rating weighted by review volume. */
export function qualityScore(d: DealItem): number {
  const rating = d.rating ?? 0
  const reviews = d.review_count ?? 0
  return rating * Math.log(reviews + 1)
}

/**
 * Coarse band for the "All" view. Lower = ranked higher.
 *  0: 2-for-1 + big % off (>= 30%)
 *  1: smaller % off (< 30%)
 *  2: free delivery
 *  3: free item
 *  4: absolute € off
 */
export function dealBand(d: DealItem): number {
  if (d.promo_type === 'bogo') return 0
  if (d.promo_type === 'pct_discount') return (d.value ?? 0) >= 30 ? 0 : 1
  if (d.promo_type === 'free_delivery') return 2
  if (d.promo_type === 'free_item') return 3
  if (d.promo_type === 'abs_discount') return 4
  return 5
}

/**
 * Sort deals for display given the active filter.
 *  - pct: discount value desc, quality tiebreak
 *  - bogo / free_delivery / free_item: quality desc
 *  - all: band asc, then quality desc
 * Pure: returns a new array.
 */
export function sortDeals(deals: DealItem[], filter: DealFilter): DealItem[] {
  const out = [...deals]
  if (filter === 'pct') {
    out.sort((a, b) => (b.value ?? 0) - (a.value ?? 0) || qualityScore(b) - qualityScore(a))
  } else if (filter === 'all') {
    out.sort((a, b) => dealBand(a) - dealBand(b) || qualityScore(b) - qualityScore(a))
  } else {
    out.sort((a, b) => qualityScore(b) - qualityScore(a))
  }
  return out
}

/** Green badge text per deal type. */
export function badgeText(d: DealItem): string {
  switch (d.promo_type) {
    case 'bogo':
      return '2-for-1'
    case 'pct_discount':
      return d.value != null ? `${Math.round(d.value)}% off` : '% off'
    case 'abs_discount':
      return d.value != null ? `€${d.value.toFixed(2)} off` : '€ off'
    case 'free_delivery':
      return 'Free delivery'
    case 'free_item':
      // Scraper labels are generic spend-threshold phrases (often DE/FR), not item
      // names — the Min. €X line conveys the threshold, so keep the badge clean.
      return 'Free item'
    default:
      return d.label
  }
}
