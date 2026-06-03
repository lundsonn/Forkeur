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

/** Does a deal match a single pill key? */
export function matchesPill(d: DealItem, key: Exclude<DealFilter, 'all'>): boolean {
  if (key === 'pct') return d.promo_type === 'pct_discount' || d.promo_type === 'abs_discount'
  return d.promo_type === key
}

/**
 * Does a deal pass the active selection?
 * Empty set or 'all' = show everything.
 */
export function matchesFilter(d: DealItem, active: Set<Exclude<DealFilter, 'all'>>): boolean {
  if (active.size === 0) return true
  return [...active].some((key) => matchesPill(d, key))
}

/** Live counts per filter pill (always against full dataset, not current selection). */
export function filterCounts(deals: DealItem[]): Record<DealFilter, number> {
  const counts: Record<DealFilter, number> = {
    all: deals.length,
    bogo: 0,
    pct: 0,
    free_delivery: 0,
    free_item: 0,
  }
  for (const d of deals) {
    if (matchesPill(d, 'bogo')) counts.bogo++
    if (matchesPill(d, 'pct')) counts.pct++
    if (matchesPill(d, 'free_delivery')) counts.free_delivery++
    if (matchesPill(d, 'free_item')) counts.free_item++
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
 * Sort deals for display given the active selection.
 *  - exactly {pct}: discount value desc, quality tiebreak
 *  - exactly {bogo|free_delivery|free_item}: quality desc
 *  - empty (all) or multiple: band asc, then quality desc
 * Pure: returns a new array.
 */
export function sortDeals(deals: DealItem[], active: Set<Exclude<DealFilter, 'all'>>): DealItem[] {
  const out = [...deals]
  if (active.size === 1) {
    const [only] = active
    if (only === 'pct') {
      out.sort((a, b) => (b.value ?? 0) - (a.value ?? 0) || qualityScore(b) - qualityScore(a))
    } else {
      out.sort((a, b) => qualityScore(b) - qualityScore(a))
    }
  } else {
    out.sort((a, b) => dealBand(a) - dealBand(b) || qualityScore(b) - qualityScore(a))
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
