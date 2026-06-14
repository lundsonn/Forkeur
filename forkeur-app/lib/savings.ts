import type { RestaurantSummary } from '@/lib/queries'
import type { Platform } from '@/lib/basket'

type ListingLike = { platform: Platform; delivery_fee_cents: number | null; min_order_cents: number | null }

/** max(subtotal ?? 0, minOrder) + deliveryFee */
export function effectiveTotal(
  subtotal: number | null,
  minOrderCents: number,
  deliveryFeeCents: number,
): number {
  return Math.max(subtotal ?? 0, minOrderCents) + deliveryFeeCents
}

export type SavingsSelection = {
  winner: Platform
  winnerTotal: number
  savingCents: number
  canShowSavings: boolean
  overpayDeltas: Map<Platform, number>
}

/** Null-subtotal selector for cards/homepage. Returns null when no listings have fee data. */
export function platformSavingsSelector(listings: ListingLike[]): SavingsSelection | null {
  const withTotal = listings
    .filter((l): l is ListingLike & { delivery_fee_cents: number } => l.delivery_fee_cents !== null)
    .map((l) => ({
      ...l,
      total: effectiveTotal(null, l.min_order_cents ?? 0, l.delivery_fee_cents),
    }))
    .sort((a, b) => a.total - b.total)

  if (withTotal.length === 0) return null

  const [winner, ...rest] = withTotal
  const savingCents = rest.length > 0 ? rest[0].total - winner.total : 0

  const overpayDeltas = new Map<Platform, number>()
  for (const l of rest) {
    const delta = l.total - winner.total
    if (delta > 0) overpayDeltas.set(l.platform, delta)
  }

  return {
    winner: winner.platform,
    winnerTotal: winner.total,
    savingCents,
    canShowSavings: savingCents > 0,
    overpayDeltas,
  }
}

export type BestSavingExample = {
  restaurant: RestaurantSummary
  winner: ListingLike
  loser: ListingLike
  winnerTotal: number
  loserTotal: number
  savingsCents: number
}

export function findBestSavingExample(restaurants: RestaurantSummary[]): BestSavingExample | null {
  let best: BestSavingExample | null = null

  for (const r of restaurants) {
    if (!r.cheapest || r.cheapest.savings_cents <= 0 || r.listings.length < 2) continue

    const sel = platformSavingsSelector(r.listings)
    if (!sel || !sel.canShowSavings) continue

    if (!best || sel.savingCents > best.savingsCents) {
      const winnerListing = r.listings.find((l) => l.platform === sel.winner)
      if (!winnerListing) continue
      const loserEntry = r.listings
        .filter((l) => l.platform !== sel.winner && l.delivery_fee_cents !== null)
        .map((l) => ({
          ...l,
          total: effectiveTotal(null, l.min_order_cents ?? 0, l.delivery_fee_cents!),
        }))
        .sort((a, b) => a.total - b.total)[0]
      if (!loserEntry) continue

      best = {
        restaurant: r,
        winner: winnerListing,
        loser: loserEntry,
        winnerTotal: sel.winnerTotal,
        loserTotal: loserEntry.total,
        savingsCents: sel.savingCents,
      }
    }
  }

  return best
}
