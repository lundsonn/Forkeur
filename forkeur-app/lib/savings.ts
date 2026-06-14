import type { RestaurantSummary } from '@/lib/queries'
import type { Platform } from '@/lib/basket'

type ListingLike = { platform: Platform; delivery_fee_cents: number | null; min_order_cents: number | null }

export function effectiveTotal(listing: Pick<ListingLike, 'delivery_fee_cents' | 'min_order_cents'>): number | null {
  if (listing.delivery_fee_cents === null) return null
  return listing.delivery_fee_cents
}

export function savingsVsNext(
  listings: ListingLike[],
): { cents: number; vs: Platform } | null {
  const withTotal = listings
    .map(l => ({ ...l, total: effectiveTotal(l) }))
    .filter((l): l is typeof l & { total: number } => l.total !== null)
    .sort((a, b) => a.total - b.total)

  if (withTotal.length < 2) return null
  const delta = withTotal[1].total - withTotal[0].total
  if (delta <= 0) return null
  return { cents: delta, vs: withTotal[1].platform }
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

    const withTotal = r.listings
      .map(l => ({ ...l, total: effectiveTotal(l) }))
      .filter((l): l is typeof l & { total: number } => l.total !== null)
      .sort((a, b) => a.total - b.total)

    if (withTotal.length < 2) continue

    const savingsCents = withTotal[1].total - withTotal[0].total
    if (savingsCents <= 0) continue
    if (!best || savingsCents > best.savingsCents) {
      best = {
        restaurant: r,
        winner: withTotal[0],
        loser: withTotal[1],
        winnerTotal: withTotal[0].total,
        loserTotal: withTotal[1].total,
        savingsCents,
      }
    }
  }

  return best
}
