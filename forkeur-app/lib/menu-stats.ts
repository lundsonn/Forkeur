// lib/menu-stats.ts
//
// Pure helpers for the menu-price comparison summary on the restaurant detail page.
// Mirrors the avg-price logic in components/MenuPriceComparison.tsx: a "comparable"
// item is one priced on >=2 aggregator platforms (Direct is excluded from the menu
// price comparison), and per-platform averages are taken over comparable items only.

import type { MenuItemWithPrices } from './queries'

export type AggPlatform = 'uber_eats' | 'deliveroo' | 'takeaway'

const AGG_PLATFORMS: AggPlatform[] = ['uber_eats', 'deliveroo', 'takeaway']

export type MenuStats = {
  /** Only platforms with >=1 priced comparable item, sorted ascending by avgCents. */
  platformStats: { platform: AggPlatform; avgCents: number; pricedCount: number }[]
  cheapestAvgPlatform: AggPlatform
  dearestAvgPlatform: AggPlatform
  maxAvgCents: number
  /** maxAvgCents - cheapest avgCents. */
  avgPerItemGapCents: number
  /** # comparable items (priced on >=2 aggregators). */
  comparedCount: number
  /** items.length */
  totalCount: number
}

export function computeMenuStats(items: MenuItemWithPrices[]): MenuStats | null {
  const comparable = items.filter(
    (item) => AGG_PLATFORMS.filter((p) => item.prices[p] !== null).length >= 2
  )
  if (comparable.length < 1) return null

  const platformStats = AGG_PLATFORMS.map((platform) => {
    const prices = comparable
      .map((item) => item.prices[platform])
      .filter((v): v is number => v !== null)
    if (prices.length === 0) return null
    const avgCents = Math.round(prices.reduce((s, v) => s + v, 0) / prices.length)
    return { platform, avgCents, pricedCount: prices.length }
  })
    .filter((s): s is NonNullable<typeof s> => s !== null)
    .sort((a, b) => a.avgCents - b.avgCents)

  // comparable.length >= 1 guarantees at least one platform has priced items.
  const cheapest = platformStats[0]
  const dearest = platformStats[platformStats.length - 1]

  return {
    platformStats,
    cheapestAvgPlatform: cheapest.platform,
    dearestAvgPlatform: dearest.platform,
    maxAvgCents: dearest.avgCents,
    avgPerItemGapCents: dearest.avgCents - cheapest.avgCents,
    comparedCount: comparable.length,
    totalCount: items.length,
  }
}
