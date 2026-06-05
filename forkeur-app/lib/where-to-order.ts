// lib/where-to-order.ts
//
// Pure helpers for the "where to order" / delivery-fees section on the restaurant
// detail page. Operates on PlatformListing rows (fees in cents).

import { PLATFORMS, type Platform } from './basket'
import type { PlatformListing } from './queries'

const AGG_PLATFORMS: Platform[] = ['uber_eats', 'deliveroo', 'takeaway']

/** €1.50 floor below which direct-savings is not worth surfacing. */
const SAVINGS_FLOOR_CENTS = 150

export type FeeRow = {
  platform: Platform
  feeCents: number
  deltaCents: number
  isCheapest: boolean
}

/**
 * Rows for the DELIVERY FEES section.
 *
 * Includes every listing with delivery_fee_cents !== null (Direct included only when
 * it has a real non-null fee — same rule, just usually null in practice).
 * Sorted ascending by feeCents; ties broken by PLATFORMS order. deltaCents is the
 * difference from the cheapest fee; the first (cheapest) row is flagged isCheapest.
 */
export function computeFeeRows(listings: PlatformListing[]): FeeRow[] {
  const priced = listings.filter(
    (l): l is PlatformListing & { delivery_fee_cents: number } =>
      l.delivery_fee_cents !== null
  )
  if (priced.length === 0) return []

  const order = (p: Platform) => {
    const i = PLATFORMS.indexOf(p)
    return i === -1 ? PLATFORMS.length : i
  }

  const sorted = [...priced].sort((a, b) => {
    if (a.delivery_fee_cents !== b.delivery_fee_cents) {
      return a.delivery_fee_cents - b.delivery_fee_cents
    }
    return order(a.platform) - order(b.platform)
  })

  const cheapestFee = sorted[0].delivery_fee_cents

  return sorted.map((l, idx) => ({
    platform: l.platform,
    feeCents: l.delivery_fee_cents,
    deltaCents: l.delivery_fee_cents - cheapestFee,
    isCheapest: idx === 0,
  }))
}

/**
 * Average aggregator delivery fee minus the direct delivery fee (treated as 0 when
 * absent). Returns null when there are no aggregator fees, or when the result is
 * below the €1.50 floor.
 */
export function computeDirectSavingsCents(
  listings: PlatformListing[]
): number | null {
  const aggFees = listings
    .filter((l) => AGG_PLATFORMS.includes(l.platform))
    .map((l) => l.delivery_fee_cents)
    .filter((v): v is number => v !== null)

  if (aggFees.length === 0) return null

  const meanAgg = aggFees.reduce((s, v) => s + v, 0) / aggFees.length
  const directListing = listings.find((l) => l.platform === 'direct')
  const directFee = directListing?.delivery_fee_cents ?? 0

  const savings = Math.round(meanAgg - directFee)
  if (savings < SAVINGS_FLOOR_CENTS) return null
  return savings
}
