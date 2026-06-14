/**
 * Match-rate audit: fetches all restaurants from the backend API, replicates the
 * queries.ts itemMap + fuzzy-merge logic, and reports the cross-platform match rate.
 *
 * Usage:
 *   cd forkeur-app && npx tsx scripts/match-rate-audit.ts
 *
 * Env:
 *   BACKEND_URL  — default http://localhost:8000
 */

import { normalizeTitle, normalizeForFuzzy } from '../lib/normalize-title'
import { jaroWinkler } from '../lib/fuzzy-title'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const EMOJI_RE = /[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu

type Platform = 'uber_eats' | 'deliveroo' | 'takeaway' | 'direct'
const ALL_PLATFORMS: Platform[] = ['uber_eats', 'deliveroo', 'takeaway', 'direct']

// Minimal shapes — only what we need from the public API
type MenuItem = { title: string; price: number | null; catalog_name: string | null }
type Listing = { platform: string; menu_items: MenuItem[] }
type RestaurantSummary = { id: string; name: string; platform_listings: { platform: string }[] }
type Restaurant = { id: string; name: string; platform_listings: Listing[] }

type PriceMap = Record<Platform, number | null>
type TitleMap = Record<Platform, string | null>
type MergedItem = { name: string; prices: PriceMap; platformTitles: TitleMap }

async function fetchRestaurantSummaries(): Promise<RestaurantSummary[]> {
  const res = await fetch(`${BACKEND}/api/public/restaurants`)
  if (!res.ok) throw new Error(`GET /api/public/restaurants → ${res.status}`)
  const data = await res.json()
  return (data.restaurants ?? data) as RestaurantSummary[]
}

async function fetchDetail(id: string): Promise<Restaurant | null> {
  const res = await fetch(`${BACKEND}/api/public/restaurants/${id}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`GET /api/public/restaurants/${id} → ${res.status}`)
  return res.json()
}

function feeCents(price: number | null): number | null {
  if (price == null) return null
  // Backend returns prices in euros; convert to cents for consistent ratio checks
  return Math.round(price * 100)
}

function buildItemMap(restaurant: Restaurant): MergedItem[] {
  const itemMap = new Map<string, MergedItem>()

  for (const listing of restaurant.platform_listings ?? []) {
    const platform = listing.platform as Platform
    for (const item of listing.menu_items ?? []) {
      const key = normalizeTitle(item.title, item.catalog_name ?? undefined)
      if (!itemMap.has(key)) {
        itemMap.set(key, {
          name: item.title.replace(EMOJI_RE, '').trim(),
          prices: { uber_eats: null, deliveroo: null, takeaway: null, direct: null },
          platformTitles: { uber_eats: null, deliveroo: null, takeaway: null, direct: null },
        })
      }
      const entry = itemMap.get(key)!
      entry.prices[platform] = feeCents(item.price)
      entry.platformTitles[platform] = item.title.replace(EMOJI_RE, '').trim()
    }
  }

  // Fuzzy merge pass — mirrors queries.ts exactly
  const entries = Array.from(itemMap.entries())
  const absorbed = new Set<string>()
  for (let i = 0; i < entries.length; i++) {
    if (absorbed.has(entries[i][0])) continue
    const [, itemA] = entries[i]
    const normA = normalizeForFuzzy(itemA.name)
    for (let j = i + 1; j < entries.length; j++) {
      if (absorbed.has(entries[j][0])) continue
      const [keyB, itemB] = entries[j]
      if (ALL_PLATFORMS.some(p => itemA.prices[p] !== null && itemB.prices[p] !== null)) continue
      const normB = normalizeForFuzzy(itemB.name)
      const lenRatio = Math.min(normA.length, normB.length) / Math.max(normA.length, normB.length)
      if (lenRatio < 0.75) continue
      if (jaroWinkler(normA, normB) < 0.88) continue
      const priceA = ALL_PLATFORMS.map(p => itemA.prices[p]).find(p => p != null)
      const priceB = ALL_PLATFORMS.map(p => itemB.prices[p]).find(p => p != null)
      if (priceA != null && priceB != null) {
        const maxP = Math.max(priceA, priceB)
        if (maxP > 0 && Math.abs(priceA - priceB) / maxP > 0.20) continue
      }
      for (const p of ALL_PLATFORMS) {
        if (itemA.prices[p] === null && itemB.prices[p] !== null) {
          itemA.prices[p] = itemB.prices[p]
          if (itemA.platformTitles && itemB.platformTitles) itemA.platformTitles[p] = itemB.platformTitles[p]
        }
      }
      absorbed.add(keyB)
    }
  }

  return entries.filter(([key]) => !absorbed.has(key)).map(([, item]) => item)
}

// Collect samples where ≥2 platform prices exist and platform titles differ
type Sample = { restaurant: string; name: string; prices: Partial<Record<Platform, number>>; titles: Partial<Record<Platform, string>> }

async function main() {
  console.log(`Backend: ${BACKEND}`)
  console.log('Fetching restaurant list...')
  const allRestaurants = await fetchRestaurantSummaries()
  // Only restaurants with ≥2 platform listings can have cross-platform matches
  const list = allRestaurants.filter(r => r.platform_listings.length >= 2)
  console.log(`${allRestaurants.length} total restaurants, ${list.length} multi-platform (used for match rate)\n`)

  let totalItems = 0        // items from restaurants with menu on ≥2 platforms
  let totalItemsAll = 0     // items from all multi-platform restaurants (for reference)
  let matched2 = 0  // ≥2 platforms
  let matched3 = 0  // ≥3 platforms
  let matched4 = 0  // all 4 platforms
  let menuMultiCount = 0    // restaurants with menu on ≥2 platforms
  const samples: Sample[] = []
  let errors = 0

  const CONCURRENCY = 10
  for (let i = 0; i < list.length; i += CONCURRENCY) {
    const batch = list.slice(i, i + CONCURRENCY)
    const details = await Promise.all(batch.map(r => fetchDetail(r.id).catch(() => { errors++; return null })))
    for (let b = 0; b < batch.length; b++) {
      const detail = details[b]
      if (!detail) continue
      const items = buildItemMap(detail)
      totalItemsAll += items.length

      // Only count restaurants where ≥2 platforms have menu data (mirrors baseline scope)
      const platformsWithItems = new Set(
        (detail.platform_listings ?? [])
          .filter(l => (l.menu_items ?? []).length > 0)
          .map(l => l.platform)
      )
      const hasMenuOnMulti = platformsWithItems.size >= 2
      if (hasMenuOnMulti) {
        menuMultiCount++
        totalItems += items.length
      }

      for (const item of items) {
        const platformCount = ALL_PLATFORMS.filter(p => item.prices[p] !== null).length
        if (platformCount >= 2) {
          matched2++
          if (platformCount >= 3) matched3++
          if (platformCount === 4) matched4++
          // Sample: titles must differ across ≥2 platforms
          if (samples.length < 20) {
            const activeTitles = ALL_PLATFORMS.filter(p => item.platformTitles[p] !== null)
            const uniqueTitles = new Set(activeTitles.map(p => item.platformTitles[p]))
            if (uniqueTitles.size > 1) {
              const titles: Partial<Record<Platform, string>> = {}
              const prices: Partial<Record<Platform, number>> = {}
              for (const p of ALL_PLATFORMS) {
                if (item.platformTitles[p]) titles[p] = item.platformTitles[p]!
                if (item.prices[p] != null) prices[p] = item.prices[p]!
              }
              samples.push({ restaurant: detail.name, name: item.name, prices, titles })
            }
          }
        }
      }
    }
    const done = Math.min(i + CONCURRENCY, list.length)
    process.stdout.write(`\r${done}/${list.length} restaurants processed...`)
  }
  console.log('\n')

  const matchRate = totalItems > 0 ? matched2 / totalItems : 0
  const baseline = 0.190  // measured 2026-06-13 with correct scope (restaurants with menu on ≥2 platforms)

  console.log('=== Match Rate ===')
  console.log(`Total merged items  : ${totalItems}`)
  console.log(`≥2 platforms (match): ${matched2}  (${(matchRate * 100).toFixed(1)}%  |  baseline 47.7%  |  delta ${((matchRate - baseline) * 100).toFixed(1)}pp)`)
  console.log(`≥3 platforms        : ${matched3}  (${totalItems > 0 ? (matched3 / totalItems * 100).toFixed(1) : 0}%)`)
  console.log(`4 platforms         : ${matched4}  (${totalItems > 0 ? (matched4 / totalItems * 100).toFixed(1) : 0}%)`)
  if (errors > 0) console.log(`Fetch errors        : ${errors}`)

  console.log('\n=== Sample: matched items with differing platform titles ===')
  for (const s of samples.slice(0, 20)) {
    console.log(`\n[${s.restaurant}] "${s.name}"`)
    for (const p of ALL_PLATFORMS) {
      if (s.titles[p]) {
        const priceStr = s.prices[p] != null ? `€${(s.prices[p]! / 100).toFixed(2)}` : 'no price'  // prices stored in cents
        console.log(`  ${p.padEnd(12)} "${s.titles[p]}"  ${priceStr}`)
      }
    }
  }
}

main().catch(e => { console.error(e); process.exit(1) })
