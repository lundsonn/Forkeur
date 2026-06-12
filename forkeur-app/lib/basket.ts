// lib/basket.ts
import { fuzzyFindByTitle } from '@/lib/fuzzy-title'

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

export type DirectOverlap = {
  matchedCount: number
  basketCount: number
  thresholdMet: boolean
}

export function computeDirectOverlap(items: BasketItem[]): DirectOverlap {
  const activeItems = items.filter(b => b.qty > 0)
  const basketCount = activeItems.length
  const matchedCount = activeItems.filter(b => b.prices.direct !== null).length
  const thresholdMet = matchedCount >= 3 && basketCount > 0 && matchedCount / basketCount >= 0.5
  return { matchedCount, basketCount, thresholdMet }
}

export function computeDirectSubtotal(items: BasketItem[]): number {
  return items.reduce((sum, b) => {
    const price = b.prices.direct
    return price !== null ? sum + price * b.qty : sum
  }, 0)
}

export function computeDirectSavingsCents(
  items: BasketItem[],
  fees: PlatformFees
): number | null {
  const overlap = computeDirectOverlap(items)
  if (!overlap.thresholdMet) return null

  const nonDirectTotals = PLATFORMS
    .filter(p => p !== 'direct')
    .map(p => calculatePlatformTotal(items, p, fees[p]))
    .filter((t): t is number => t !== null)

  if (nonDirectTotals.length === 0) return null

  const cheapestPlatformTotal = Math.min(...nonDirectTotals)
  const directSubtotal = computeDirectSubtotal(items)
  const savings = cheapestPlatformTotal - directSubtotal
  return savings > 0 ? savings : null
}

// ---------------------------------------------------------------------------
// Menu-item-aware variants (use MenuItemWithPrices from lib/queries.ts)
// These accept a basket of named items and a cross-platform menu item list,
// matching by name to resolve direct prices at query time.
// ---------------------------------------------------------------------------

/** Minimal shape required from MenuItemWithPrices for direct-ordering helpers. */
export interface MenuItemDirectPrice {
  name: string
  prices: { direct: number | null } & Partial<Record<Platform, number | null>>
}

/**
 * Count how many basket items have a direct price, resolved via menuItems.
 *
 * An item "has a direct price" if the matching menu item's prices.direct is
 * not null/undefined. Matching is case-insensitive by name.
 *
 * @returns { directCount, totalCount }
 */
export function computeDirectOverlapFromMenu(
  basket: BasketItem[],
  menuItems: MenuItemDirectPrice[]
): { directCount: number; totalCount: number } {
  const activeItems = basket.filter(b => b.qty > 0)
  const totalCount = activeItems.length

  const directCount = activeItems.filter(b => {
    const found = fuzzyFindByTitle(b.name, menuItems)
    return found != null && found.prices.direct != null
  }).length

  return { directCount, totalCount }
}

/**
 * Compute total basket cost for direct ordering, resolved via menuItems.
 *
 * Only items that have a matching menu item with prices.direct are included.
 * Prices in menuItems are expected to be in cents (same unit as BasketItem.prices).
 *
 * @returns total in euros (float), or null if no items have direct prices
 */
export function computeDirectSubtotalFromMenu(
  basket: BasketItem[],
  menuItems: MenuItemDirectPrice[]
): number | null {
  let totalCents = 0
  let hasAny = false

  for (const b of basket) {
    if (b.qty <= 0) continue
    const found = fuzzyFindByTitle(b.name, menuItems)
    if (found != null && found.prices.direct != null) {
      totalCents += found.prices.direct * b.qty
      hasAny = true
    }
  }

  return hasAny ? totalCents / 100 : null
}

/**
 * Compute savings in cents vs the cheapest non-direct platform.
 *
 * Applies the overlap threshold: directCount >= 3 AND
 * directCount / totalCount >= 0.5. Below threshold → returns null.
 *
 * @param platformTotals - totals per platform in euros (float); null means platform unavailable
 * @returns positive number if direct is cheaper, negative if more expensive,
 *          null if threshold not met or no non-direct platform is available
 */
export function computeDirectSavingsCentsFromMenu(
  basket: BasketItem[],
  menuItems: MenuItemDirectPrice[],
  platformTotals: Record<Platform, number | null>
): number | null {
  const { directCount, totalCount } = computeDirectOverlapFromMenu(basket, menuItems)

  if (directCount < 3 || totalCount === 0 || directCount / totalCount < 0.5) {
    return null
  }

  const nonDirectTotals = (PLATFORMS as Platform[])
    .filter(p => p !== 'direct')
    .map(p => platformTotals[p])
    .filter((t): t is number => t !== null)

  if (nonDirectTotals.length === 0) return null

  const cheapestNonDirectEuros = Math.min(...nonDirectTotals)
  const directEuros = computeDirectSubtotalFromMenu(basket, menuItems)
  if (directEuros === null) return null

  // Convert to cents for the return value (consistent with existing cents-based API)
  const savingsCents = Math.round((cheapestNonDirectEuros - directEuros) * 100)
  return savingsCents
}

export type PlatformCoverage = {
  priced: number
  total: number
  complete: boolean
}

export type PlatformCoverages = Record<Platform, PlatformCoverage | null>

export type TotalsWithCoverage = {
  totals: PlatformTotals
  coverages: PlatformCoverages
}

/**
 * Like calculateAllTotals but also returns per-platform coverage metadata.
 * Coverage is null when the platform is unavailable (fee === null).
 * When basket is empty, all available platforms get complete=true (fee comparison only).
 */
export function calculateAllTotalsWithCoverage(
  items: BasketItem[],
  fees: PlatformFees
): TotalsWithCoverage {
  const totals = calculateAllTotals(items, fees)
  const coverages = {} as PlatformCoverages
  for (const p of PLATFORMS) {
    if (fees[p] === null) {
      coverages[p] = null
    } else if (items.length === 0) {
      coverages[p] = { priced: 0, total: 0, complete: true }
    } else {
      const priced = items.filter((item) => item.prices[p] !== null).length
      coverages[p] = { priced, total: items.length, complete: priced === items.length }
    }
  }
  return { totals, coverages }
}

/**
 * Like findCheapestPlatform but only considers platforms with complete coverage
 * when the basket has items. Falls back to fee-only comparison when basket is empty.
 * Returns null if no platform has complete coverage (no winner).
 */
export function findCheapestCompletePlatform(
  totals: PlatformTotals,
  coverages: PlatformCoverages,
  hasBasketItems: boolean
): Platform | null {
  if (!hasBasketItems) return findCheapestPlatform(totals)
  let cheapest: Platform | null = null
  let minTotal = Infinity
  for (const p of PLATFORMS) {
    const coverage = coverages[p]
    if (coverage === null || !coverage.complete) continue
    const total = totals[p]
    if (total !== null && total < minTotal) {
      minTotal = total
      cheapest = p
    }
  }
  return cheapest
}

export const PLATFORM_COLORS: Record<Platform, { dot: string; label: string; ring: string }> = {
  uber_eats:  { dot: 'bg-green-500',  label: 'text-green-600',  ring: 'border-green-500' },
  deliveroo:  { dot: 'bg-cyan-500',   label: 'text-cyan-600',   ring: 'border-cyan-500'  },
  takeaway:   { dot: 'bg-orange-500', label: 'text-orange-600', ring: 'border-orange-500'},
  direct:     { dot: 'bg-violet-500', label: 'text-violet-600', ring: 'border-violet-500'},
}
