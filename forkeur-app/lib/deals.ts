import type { Platform } from './basket'

export type DealType = 'free_delivery' | 'bogo' | 'pct_discount' | 'abs_discount' | 'free_item'

export type DealItem = {
  id: string
  restaurant_id: string
  restaurant_name: string
  platform: Platform
  platform_url: string | null
  cuisine: string[]
  area: string | null
  rating: number | null
  review_count: number | null
  promo_type: DealType
  label: string
  value: number | null
  min_order: number | null
  opening_hours: Record<string, [string, string] | [string, string][]> | null
  is_available: boolean
  scraped_at: string
}

export type ActiveType = 'all' | 'free_delivery' | 'pct' | 'bogo' | 'abs' | 'free_item'
export type ActivePlatform = 'all' | 'uber_eats' | 'deliveroo' | 'takeaway'
export type SortMode = 'best' | 'saving' | 'rated' | 'newest'

export function qualityScore(d: DealItem): number {
  let score = 0
  if (d.promo_type === 'pct_discount' && d.value) score += d.value * 2
  if (d.promo_type === 'abs_discount' && d.value) score += d.value * 10
  if (d.promo_type === 'free_delivery') score += 15
  if (d.promo_type === 'bogo') score += 30
  if (d.promo_type === 'free_item') score += 20
  if (d.rating) score += d.rating * 2
  return score
}

export function savingsEstimate(deal: DealItem): string | null {
  switch (deal.promo_type) {
    case 'pct_discount': {
      if (deal.value == null) return null
      const saved = (deal.value * 20) / 100
      return `Save ~€${saved.toFixed(2)} on a €20 order`
    }
    case 'abs_discount': {
      if (deal.value == null) return null
      return `€${deal.value.toFixed(2)} off your order`
    }
    case 'free_delivery':
      return '€0 delivery fee'
    default:
      return null
  }
}

function promoTypeForActiveType(active: ActiveType): DealType | null {
  switch (active) {
    case 'pct': return 'pct_discount'
    case 'abs': return 'abs_discount'
    case 'free_delivery': return 'free_delivery'
    case 'bogo': return 'bogo'
    case 'free_item': return 'free_item'
    default: return null
  }
}

export function matchesFilter(
  d: DealItem,
  activeType: ActiveType,
  activePlatform: ActivePlatform,
): boolean {
  if (activeType !== 'all') {
    const expected = promoTypeForActiveType(activeType)
    if (expected && d.promo_type !== expected) return false
  }
  if (activePlatform !== 'all' && d.platform !== activePlatform) return false
  return true
}

export function filterCounts(
  deals: DealItem[],
  activePlatform: ActivePlatform,
): Record<ActiveType, number> {
  const platformDeals = activePlatform === 'all'
    ? deals
    : deals.filter(d => d.platform === activePlatform)

  const counts: Record<ActiveType, number> = {
    all: platformDeals.length,
    free_delivery: 0,
    pct: 0,
    bogo: 0,
    abs: 0,
    free_item: 0,
  }
  for (const d of platformDeals) {
    if (d.promo_type === 'free_delivery') counts.free_delivery++
    if (d.promo_type === 'pct_discount') counts.pct++
    if (d.promo_type === 'bogo') counts.bogo++
    if (d.promo_type === 'abs_discount') counts.abs++
    if (d.promo_type === 'free_item') counts.free_item++
  }
  return counts
}

export function sortDeals(deals: DealItem[], mode: SortMode): DealItem[] {
  const copy = [...deals]
  switch (mode) {
    case 'newest':
      return copy.sort((a, b) => b.scraped_at.localeCompare(a.scraped_at))
    case 'rated':
      return copy.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))
    case 'saving':
      return copy.sort((a, b) => {
        const aVal = (a.promo_type === 'pct_discount' || a.promo_type === 'abs_discount')
          ? (a.value ?? 0) : 0
        const bVal = (b.promo_type === 'pct_discount' || b.promo_type === 'abs_discount')
          ? (b.value ?? 0) : 0
        if (bVal !== aVal) return bVal - aVal
        return qualityScore(b) - qualityScore(a)
      })
    case 'best':
    default:
      return copy.sort((a, b) => qualityScore(b) - qualityScore(a))
  }
}
