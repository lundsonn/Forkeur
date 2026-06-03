// lib/basket.ts

export type Platform = 'uber_eats' | 'deliveroo' | 'takeaway' | 'direct'
export const PLATFORMS: Platform[] = ['uber_eats', 'deliveroo', 'takeaway', 'direct']

export const PLATFORM_LABELS: Record<Platform, string> = {
  uber_eats: 'Uber Eats',
  deliveroo: 'Deliveroo',
  takeaway: 'Takeaway',
  direct: 'Direct',
}

export type BasketItem = {
  name: string
  qty: number
  prices: Record<Platform, number | null>
}

export type PlatformFees = Record<Platform, number | null>
export type PlatformTotals = Record<Platform, number | null>

/**
 * Total for one platform = sum of (item_price * qty) + delivery_fee.
 * Items with null price for this platform are skipped (not available).
 * Returns null if delivery fee is null (platform not available).
 */
export function calculatePlatformTotal(
  items: BasketItem[],
  platform: Platform,
  deliveryFeeCents: number | null
): number | null {
  if (deliveryFeeCents === null) return null
  let subtotal = 0
  for (const item of items) {
    const price = item.prices[platform]
    if (price === null) continue
    subtotal += price * item.qty
  }
  return subtotal + deliveryFeeCents
}

export function calculateAllTotals(
  items: BasketItem[],
  fees: PlatformFees
): PlatformTotals {
  return Object.fromEntries(
    PLATFORMS.map((p) => [p, calculatePlatformTotal(items, p, fees[p])])
  ) as PlatformTotals
}

export function findCheapestPlatform(totals: PlatformTotals): Platform | null {
  let cheapest: Platform | null = null
  let minTotal = Infinity
  for (const platform of PLATFORMS) {
    const total = totals[platform]
    if (total !== null && total < minTotal) {
      minTotal = total
      cheapest = platform
    }
  }
  return cheapest
}

export function centsToEuro(cents: number | null): string {
  if (cents === null) return '—'
  if (cents === 0) return 'Free'
  return `€${(cents / 100).toFixed(2)}`
}

export const PLATFORM_COLORS: Record<Platform, { dot: string; label: string; ring: string }> = {
  uber_eats:  { dot: 'bg-green-500',  label: 'text-green-600',  ring: 'border-green-500' },
  deliveroo:  { dot: 'bg-cyan-500',   label: 'text-cyan-600',   ring: 'border-cyan-500'  },
  takeaway:   { dot: 'bg-orange-500', label: 'text-orange-600', ring: 'border-orange-500'},
  direct:     { dot: 'bg-violet-500', label: 'text-violet-600', ring: 'border-violet-500'},
}
