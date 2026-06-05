#!/usr/bin/env npx tsx
/**
 * Match-rate diagnostic for cross-platform menu item normalization.
 * Run: npx tsx scripts/match-rate-audit.ts
 */

import { createClient } from '@supabase/supabase-js'
import { writeFileSync, mkdirSync } from 'fs'
import { join } from 'path'
import { config } from 'dotenv'

config({ path: '.env.local' })

// ── Supabase ──────────────────────────────────────────────────────────────────

const SUPABASE_URL =
  process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL
const SUPABASE_KEY =
  process.env.SUPABASE_SERVICE_ROLE_KEY ||
  process.env.SUPABASE_ANON_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error('Set SUPABASE_URL and SUPABASE_KEY in .env.local')
  process.exit(1)
}

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)

// ── normalizeTitle — shared canonical source ─────────────────────────────────
// Single source of truth: lib/normalize-title.ts (also used by frontend itemMap).

import { normalizeTitle } from '../lib/normalize-title'

// ── Near-miss transforms ──────────────────────────────────────────────────────

function stripParentheticals(s: string): string {
  return s.replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim()
}

function stripTrailingSizeTokens(s: string): string {
  return s.replace(/\s+\d+\s*(cm|cl|ml|l|g|kg|oz)\s*$/i, '').trim()
}

function tokenSort(s: string): string {
  return s.split(/\s+/).sort().join(' ')
}

// After normalizeTitle, "3- Potage" becomes "3 potage" — strip leading "N " prefix
function stripLeadingNumber(s: string): string {
  return s.replace(/^\d+\s+/, '').trim()
}

// ── Types ─────────────────────────────────────────────────────────────────────

type Platform = 'uber_eats' | 'deliveroo' | 'takeaway' | 'direct'

interface RawMenuItem {
  title: string
  price: number | null
  listing_id: string
}

interface RawListing {
  id: string
  restaurant_id: string
  platform: Platform
}

interface NearMissExample {
  platform_a: string
  title_a: string
  platform_b: string
  title_b: string
}

interface RestaurantResult {
  id: string
  name: string
  platforms: Platform[]
  platform_counts: Record<string, number>
  total_unique_keys: number
  matched_count: number
  orphan_count: number
  match_rate: number
  near_miss_parentheticals: number
  near_miss_size_tokens: number
  near_miss_token_sort: number
  near_miss_leading_number: number
  sample_orphans: Array<{ platforms: Array<{ platform: string; title: string }> }>
}

// ── Levenshtein similarity ─────────────────────────────────────────────────────

function stringSimilarity(a: string, b: string): number {
  if (a === b) return 1
  const maxLen = Math.max(a.length, b.length)
  if (maxLen === 0) return 1
  // Simple edit-distance via DP
  const prev = Array.from({ length: b.length + 1 }, (_, i) => i)
  const curr = Array(b.length + 1).fill(0)
  for (let i = 1; i <= a.length; i++) {
    curr[0] = i
    for (let j = 1; j <= b.length; j++) {
      curr[j] = a[i - 1] === b[j - 1]
        ? prev[j - 1]
        : 1 + Math.min(prev[j], curr[j - 1], prev[j - 1])
    }
    prev.splice(0, prev.length, ...curr)
  }
  return 1 - prev[b.length] / maxLen
}

// ── Near-miss rescue: count orphans that gain match via transform ──────────────

function analyzeRescue(
  orphansByPlatform: Map<string, Map<string, string>>, // platform → normalizedKey → originalTitle
  transform: (key: string) => string,
): { count: number; examples: NearMissExample[] } {
  // Build: transformedKey → [{platform, originalKey, originalTitle}]
  const transformed = new Map<string, Array<{ platform: string; key: string; title: string }>>()

  for (const [platform, keyToTitle] of orphansByPlatform) {
    for (const [key, title] of keyToTitle) {
      const tKey = transform(key)
      if (!tKey) continue
      const arr = transformed.get(tKey) ?? []
      arr.push({ platform, key, title })
      transformed.set(tKey, arr)
    }
  }

  let count = 0
  const examples: NearMissExample[] = []

  for (const entries of transformed.values()) {
    const platforms = new Set(entries.map(e => e.platform))
    if (platforms.size >= 2) {
      count += entries.length
      if (examples.length < 5) {
        const a = entries[0]
        const b = entries.find(e => e.platform !== a.platform)
        if (b) examples.push({ platform_a: a.platform, title_a: a.title, platform_b: b.platform, title_b: b.title })
      }
    }
  }

  return { count, examples }
}

// ── Fetch data ────────────────────────────────────────────────────────────────

async function fetchData() {
  console.log('Fetching platform_listings...')

  const allListings: RawListing[] = []
  let listingOffset = 0
  while (true) {
    const { data: batch, error: lErr } = await supabase
      .from('platform_listings')
      .select('id, restaurant_id, platform')
      .neq('platform', 'direct')
      .range(listingOffset, listingOffset + 999)

    if (lErr) throw new Error(`listings fetch failed: ${lErr.message}`)
    if (!batch || batch.length === 0) break
    allListings.push(...(batch as RawListing[]))
    if (batch.length < 1000) break
    listingOffset += 1000
  }
  const listings = allListings
  console.log(`  ${listings.length} listings loaded`)

  const byRestaurant = new Map<string, RawListing[]>()
  for (const l of listings as RawListing[]) {
    const arr = byRestaurant.get(l.restaurant_id) ?? []
    arr.push(l)
    byRestaurant.set(l.restaurant_id, arr)
  }

  const qualifyingRestaurantIds = [...byRestaurant.entries()]
    .filter(([, ls]) => new Set(ls.map(l => l.platform)).size >= 2)
    .map(([id]) => id)

  console.log(`  ${qualifyingRestaurantIds.length} restaurants with 2+ platforms`)

  const { data: restaurants, error: rErr } = await supabase
    .from('restaurants')
    .select('id, name')
    .in('id', qualifyingRestaurantIds)

  if (rErr || !restaurants) throw new Error(`restaurants fetch failed: ${rErr?.message}`)
  const restaurantMap = new Map((restaurants as { id: string; name: string }[]).map(r => [r.id, r.name]))

  // Listing ID set for qualifying restaurants
  const qualifyingListingIds = [...byRestaurant.entries()]
    .filter(([id]) => qualifyingRestaurantIds.includes(id))
    .flatMap(([, ls]) => ls.map(l => l.id))

  console.log(`  Fetching menu_items for ${qualifyingListingIds.length} listings...`)

  // Fetch all items with pagination (Supabase 1000-row limit per request)
  const LISTING_BATCH = 300  // chunk of listing IDs per query
  const PAGE_SIZE = 1000
  const allItems: RawMenuItem[] = []

  for (let li = 0; li < qualifyingListingIds.length; li += LISTING_BATCH) {
    const listingBatch = qualifyingListingIds.slice(li, li + LISTING_BATCH)
    let offset = 0
    while (true) {
      const { data: items, error: iErr } = await supabase
        .from('menu_items')
        .select('title, price, listing_id')
        .in('listing_id', listingBatch)
        .range(offset, offset + PAGE_SIZE - 1)

      if (iErr) throw new Error(`menu_items fetch failed: ${iErr.message}`)
      if (!items || items.length === 0) break
      allItems.push(...(items as RawMenuItem[]))
      process.stdout.write(
        `\r  listing batch ${Math.min(li + LISTING_BATCH, qualifyingListingIds.length)}/${qualifyingListingIds.length}, total items: ${allItems.length}`
      )
      if (items.length < PAGE_SIZE) break
      offset += PAGE_SIZE
    }
  }
  console.log()

  return { byRestaurant, qualifyingRestaurantIds, restaurantMap, allItems }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log('=== Match-Rate Audit ===\n')

  const { byRestaurant, qualifyingRestaurantIds, restaurantMap, allItems } = await fetchData()

  // listing_id → platform
  const listingPlatform = new Map<string, Platform>()
  // listing_id → restaurant_id
  const listingRestaurant = new Map<string, string>()
  for (const [rid, ls] of byRestaurant) {
    for (const l of ls) {
      listingPlatform.set(l.id, l.platform)
      listingRestaurant.set(l.id, rid)
    }
  }

  // Group items by restaurant → platform
  const itemsByRestaurant = new Map<string, Map<Platform, Array<{ title: string; key: string }>>>()
  for (const item of allItems) {
    const platform = listingPlatform.get(item.listing_id)
    const rid = listingRestaurant.get(item.listing_id)
    if (!platform || !rid) continue

    const byPlatform = itemsByRestaurant.get(rid) ?? new Map()
    const platformItems = byPlatform.get(platform) ?? []
    platformItems.push({ title: item.title, key: normalizeTitle(item.title) })
    byPlatform.set(platform, platformItems)
    itemsByRestaurant.set(rid, byPlatform)
  }

  // Global near-miss example collectors
  const globalExamples: Record<string, NearMissExample[]> = {
    parentheticals: [],
    size_tokens: [],
    token_sort: [],
    leading_number: [],
  }

  const results: RestaurantResult[] = []

  for (const restaurantId of qualifyingRestaurantIds) {
    const name = restaurantMap.get(restaurantId) ?? 'Unknown'
    const byPlatform = itemsByRestaurant.get(restaurantId)
    if (!byPlatform || byPlatform.size < 2) continue

    const platforms = [...byPlatform.keys()]
    const platform_counts: Record<string, number> = {}
    for (const [p, items] of byPlatform) platform_counts[p] = items.length

    // itemMap: normalizedKey → set of platforms
    const itemMap = new Map<string, Set<string>>()
    // keyPlatformTitle: normalizedKey → platform → first original title
    const keyPlatformTitle = new Map<string, Map<string, string>>()

    for (const [platform, items] of byPlatform) {
      for (const { title, key } of items) {
        const pSet = itemMap.get(key) ?? new Set()
        pSet.add(platform)
        itemMap.set(key, pSet)

        const ptMap = keyPlatformTitle.get(key) ?? new Map()
        if (!ptMap.has(platform)) ptMap.set(platform, title)
        keyPlatformTitle.set(key, ptMap)
      }
    }

    let matched_count = 0
    let orphan_count = 0
    const orphansByPlatform = new Map<string, Map<string, string>>() // platform → key → title

    for (const [key, pSet] of itemMap) {
      if (pSet.size >= 2) {
        matched_count++
      } else {
        orphan_count++
        const platform = [...pSet][0]
        const title = keyPlatformTitle.get(key)?.get(platform) ?? key
        const pm = orphansByPlatform.get(platform) ?? new Map()
        pm.set(key, title)
        orphansByPlatform.set(platform, pm)
      }
    }

    // Near-miss analysis
    const { count: nm_paren, examples: ex_paren } = analyzeRescue(orphansByPlatform, stripParentheticals)
    const { count: nm_size, examples: ex_size } = analyzeRescue(orphansByPlatform, stripTrailingSizeTokens)
    const { count: nm_sort, examples: ex_sort } = analyzeRescue(orphansByPlatform, tokenSort)
    const { count: nm_num, examples: ex_num } = analyzeRescue(orphansByPlatform, stripLeadingNumber)

    if (globalExamples.parentheticals.length < 5) globalExamples.parentheticals.push(...ex_paren)
    if (globalExamples.size_tokens.length < 5) globalExamples.size_tokens.push(...ex_size)
    if (globalExamples.token_sort.length < 5) globalExamples.token_sort.push(...ex_sort)
    if (globalExamples.leading_number.length < 5) globalExamples.leading_number.push(...ex_num)

    // Sample orphan near-miss pairs (by string similarity across platforms)
    const sampleOrphans: RestaurantResult['sample_orphans'] = []
    const platformsWithOrphans = [...orphansByPlatform.keys()]

    if (platformsWithOrphans.length >= 2) {
      const aOrphans = [...(orphansByPlatform.get(platformsWithOrphans[0]) ?? new Map()).entries()].slice(0, 40)
      const bOrphans = [...(orphansByPlatform.get(platformsWithOrphans[1]) ?? new Map()).entries()].slice(0, 40)
      const pairs: Array<{ sim: number; a: [string, string]; b: [string, string]; pa: string; pb: string }> = []

      for (const [aKey, aTitle] of aOrphans) {
        for (const [bKey, bTitle] of bOrphans) {
          const sim = stringSimilarity(aKey, bKey)
          if (sim > 0.6) pairs.push({ sim, a: [aKey, aTitle], b: [bKey, bTitle], pa: platformsWithOrphans[0], pb: platformsWithOrphans[1] })
        }
      }
      pairs.sort((x, y) => y.sim - x.sim)
      for (const { a, b, pa, pb } of pairs.slice(0, 5)) {
        sampleOrphans.push({ platforms: [{ platform: pa, title: a[1] }, { platform: pb, title: b[1] }] })
      }
    }

    results.push({
      id: restaurantId,
      name,
      platforms,
      platform_counts,
      total_unique_keys: itemMap.size,
      matched_count,
      orphan_count,
      match_rate: itemMap.size > 0 ? matched_count / itemMap.size : 0,
      near_miss_parentheticals: nm_paren,
      near_miss_size_tokens: nm_size,
      near_miss_token_sort: nm_sort,
      near_miss_leading_number: nm_num,
      sample_orphans: sampleOrphans,
    })
  }

  // ── Aggregate ────────────────────────────────────────────────────────────────

  const rates = results.map(r => r.match_rate).sort((a, b) => a - b)
  const n = rates.length
  const mean = rates.reduce((s, x) => s + x, 0) / n
  const median = n % 2 === 0 ? (rates[n / 2 - 1] + rates[n / 2]) / 2 : rates[Math.floor(n / 2)]
  const pct_at = (p: number) => rates[Math.max(0, Math.floor(p * n / 100))]

  const totalItems = results.reduce((s, r) => s + r.total_unique_keys, 0)
  const totalMatched = results.reduce((s, r) => s + r.matched_count, 0)
  const totalOrphaned = results.reduce((s, r) => s + r.orphan_count, 0)

  const buckets = { '0-25%': 0, '25-50%': 0, '50-75%': 0, '75-100%': 0 }
  for (const r of rates) {
    if (r < 0.25) buckets['0-25%']++
    else if (r < 0.5) buckets['25-50%']++
    else if (r < 0.75) buckets['50-75%']++
    else buckets['75-100%']++
  }

  const totalNmParen = results.reduce((s, r) => s + r.near_miss_parentheticals, 0)
  const totalNmSize = results.reduce((s, r) => s + r.near_miss_size_tokens, 0)
  const totalNmSort = results.reduce((s, r) => s + r.near_miss_token_sort, 0)
  const totalNmNum = results.reduce((s, r) => s + r.near_miss_leading_number, 0)

  const worstOffenders = results
    .filter(r => r.total_unique_keys >= 10)
    .sort((a, b) => a.match_rate - b.match_rate)
    .slice(0, 20)

  // ── Print report ─────────────────────────────────────────────────────────────

  const pct = (x: number) => `${(x * 100).toFixed(1)}%`
  const bar = (x: number, w = 20) => '█'.repeat(Math.round(x * w)) + '░'.repeat(w - Math.round(x * w))

  console.log('\n' + '═'.repeat(64))
  console.log('  MATCH-RATE AUDIT REPORT')
  console.log('═'.repeat(64))

  console.log(`\nRestaurants analyzed : ${n}`)
  console.log(`Total unique keys    : ${totalItems.toLocaleString()}`)
  console.log(`  ✓ Matched (2+ platforms) : ${totalMatched.toLocaleString()} (${pct(totalMatched / totalItems)})`)
  console.log(`  ✗ Orphaned (1 platform)  : ${totalOrphaned.toLocaleString()} (${pct(totalOrphaned / totalItems)})`)

  console.log('\n── Per-restaurant match-rate distribution ──')
  console.log(`  Mean   : ${pct(mean)}`)
  console.log(`  Median : ${pct(median)}`)
  console.log(`  p10    : ${pct(pct_at(10))}`)
  console.log(`  p25    : ${pct(pct_at(25))}`)
  console.log(`  p75    : ${pct(pct_at(75))}`)
  console.log(`  p90    : ${pct(pct_at(90))}`)

  console.log('\n── Bucket distribution (per restaurant) ──')
  for (const [bucket, count] of Object.entries(buckets)) {
    const frac = count / n
    console.log(`  ${bucket.padEnd(8)} ${bar(frac)} ${count} restaurants (${pct(frac)})`)
  }

  console.log('\n── Near-miss rescue potential (orphaned items that gain a cross-platform match) ──')
  console.log()
  console.log(`  1. Strip leading number    → rescues ${totalNmNum} orphans`)
  for (const ex of globalExamples.leading_number.slice(0, 5)) {
    console.log(`     "${ex.title_a}" [${ex.platform_a}]`)
    console.log(`       ↔ "${ex.title_b}" [${ex.platform_b}]`)
  }
  console.log()
  console.log(`  2. Strip parentheticals    → rescues ${totalNmParen} orphans`)
  for (const ex of globalExamples.parentheticals.slice(0, 5)) {
    console.log(`     "${ex.title_a}" [${ex.platform_a}]`)
    console.log(`       ↔ "${ex.title_b}" [${ex.platform_b}]`)
  }
  console.log()
  console.log(`  3. Strip trailing size tokens → rescues ${totalNmSize} orphans`)
  for (const ex of globalExamples.size_tokens.slice(0, 5)) {
    console.log(`     "${ex.title_a}" [${ex.platform_a}]`)
    console.log(`       ↔ "${ex.title_b}" [${ex.platform_b}]`)
  }
  console.log()
  console.log(`  4. Token sort              → rescues ${totalNmSort} orphans`)
  for (const ex of globalExamples.token_sort.slice(0, 5)) {
    console.log(`     "${ex.title_a}" [${ex.platform_a}]`)
    console.log(`       ↔ "${ex.title_b}" [${ex.platform_b}]`)
  }

  console.log('\n── 20 worst offenders (≥10 unique keys, lowest match rate) ──\n')
  const hdr = '  Name'.padEnd(37) + 'Platforms'.padEnd(30) + 'Keys'.padEnd(8) + 'Rate'
  console.log(hdr)
  console.log('  ' + '─'.repeat(62))

  for (const r of worstOffenders) {
    const name = r.name.length > 34 ? r.name.slice(0, 31) + '...' : r.name
    const plats = r.platforms.join(', ')
    console.log(
      '  ' + name.padEnd(35) +
      plats.padEnd(30) +
      String(r.total_unique_keys).padEnd(8) +
      pct(r.match_rate)
    )
    if (r.sample_orphans.length > 0) {
      for (const o of r.sample_orphans.slice(0, 3)) {
        console.log(`      [${o.platforms[0].platform}] ${o.platforms[0].title}`)
        console.log(`      [${o.platforms[1].platform}] ${o.platforms[1].title}`)
      }
      console.log()
    }
  }

  // ── Write JSON ───────────────────────────────────────────────────────────────

  const outputDir = join(__dirname, 'output')
  mkdirSync(outputDir, { recursive: true })
  const outputPath = join(outputDir, 'match-rate-results.json')

  writeFileSync(outputPath, JSON.stringify({
    generated_at: new Date().toISOString(),
    aggregate: {
      restaurants_analyzed: n,
      total_unique_keys: totalItems,
      total_matched: totalMatched,
      total_orphaned: totalOrphaned,
      overall_match_rate: totalMatched / totalItems,
      mean_match_rate: mean,
      median_match_rate: median,
      p10: pct_at(10), p25: pct_at(25), p75: pct_at(75), p90: pct_at(90),
      buckets,
      near_miss: {
        parentheticals: totalNmParen,
        size_tokens: totalNmSize,
        token_sort: totalNmSort,
        leading_number: totalNmNum,
      },
    },
    worst_offenders: worstOffenders,
    restaurants: results,
  }, null, 2))

  console.log(`JSON written to: ${outputPath}\n`)
}

main().catch(err => {
  console.error(err)
  process.exit(1)
})
