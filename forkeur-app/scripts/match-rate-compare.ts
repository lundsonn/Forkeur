#!/usr/bin/env npx tsx
/**
 * Comparison script: run OLD and NEW normalizer on the same data, show the delta.
 * Run: npx tsx scripts/match-rate-compare.ts
 */

import { createClient } from '@supabase/supabase-js'
import { writeFileSync, mkdirSync } from 'fs'
import { join } from 'path'
import { config } from 'dotenv'
import { normalizeTitle as normalizeNew } from '../lib/normalize-title'

config({ path: '.env.local' })

// ── Old normalizer (pre-strengthening) ───────────────────────────────────────

function normalizeOld(title: string): string {
  return title
    .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '')
    .normalize('NFD').replace(/\p{Mn}/gu, '')
    .replace(/['']/g, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

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

async function main() {
  console.log('=== normalizeTitle Before/After Comparison ===\n')

  const allListings: Array<{ id: string; restaurant_id: string; platform: string }> = []
  let offset = 0
  while (true) {
    const { data: batch, error } = await supabase
      .from('platform_listings')
      .select('id, restaurant_id, platform')
      .neq('platform', 'direct')
      .range(offset, offset + 999)
    if (error) { console.error('listings fetch failed', error.message); process.exit(1) }
    if (!batch || batch.length === 0) break
    allListings.push(...batch)
    if (batch.length < 1000) break
    offset += 1000
  }
  const listings = allListings
  console.log(`  ${listings.length} listings loaded`)

  const byRestaurant = new Map<string, Array<{ id: string; platform: string }>>()
  for (const l of listings) {
    const arr = byRestaurant.get(l.restaurant_id) ?? []
    arr.push({ id: l.id, platform: l.platform })
    byRestaurant.set(l.restaurant_id, arr)
  }

  const qualifyingIds = [...byRestaurant.entries()]
    .filter(([, ls]) => new Set(ls.map(l => l.platform)).size >= 2)
    .map(([id]) => id)

  const qualifyingListingIds = [...byRestaurant.entries()]
    .filter(([id]) => qualifyingIds.includes(id))
    .flatMap(([, ls]) => ls.map(l => l.id))

  const allItems: Array<{ title: string; listing_id: string }> = []
  const LISTING_BATCH = 300
  for (let i = 0; i < qualifyingListingIds.length; i += LISTING_BATCH) {
    const listingSlice = qualifyingListingIds.slice(i, i + LISTING_BATCH)
    let itemOffset = 0
    while (true) {
      const { data, error } = await supabase
        .from('menu_items')
        .select('title, listing_id')
        .in('listing_id', listingSlice)
        .range(itemOffset, itemOffset + 999)
      if (error) break
      if (!data || data.length === 0) break
      allItems.push(...data)
      if (data.length < 1000) break
      itemOffset += 1000
    }
    process.stdout.write(`\r  items fetched: ${allItems.length}`)
  }
  console.log()

  const listingPlatform = new Map<string, string>()
  const listingRestaurant = new Map<string, string>()
  for (const [rid, ls] of byRestaurant) {
    for (const l of ls) {
      listingPlatform.set(l.id, l.platform)
      listingRestaurant.set(l.id, rid)
    }
  }

  // Per-restaurant: count matched keys under old vs new normalizer
  type PerRestaurant = { old_matched: number; new_matched: number; total: number }
  const perRestaurant = new Map<string, PerRestaurant>()

  // Collect newly matched pairs for spot-check
  type NewlyMatchedPair = {
    restaurant_id: string
    old_key_a: string
    old_key_b: string
    new_key: string
    title_a: string
    title_b: string
    platform_a: string
    platform_b: string
  }
  const newlyMatched: NewlyMatchedPair[] = []

  for (const rid of qualifyingIds) {
    const ls = byRestaurant.get(rid)!
    const platformItems = new Map<string, Array<{ title: string }>>()
    for (const l of ls) {
      const items = allItems.filter(i => i.listing_id === l.id)
      if (items.length) platformItems.set(l.platform, items)
    }
    if (platformItems.size < 2) continue

    // Build maps under old normalizer
    const oldMap = new Map<string, Map<string, string[]>>() // oldKey → platform → titles
    const newMap = new Map<string, Map<string, string[]>>()

    for (const [platform, items] of platformItems) {
      for (const { title } of items) {
        const oKey = normalizeOld(title)
        const nKey = normalizeNew(title)

        const oEntry = oldMap.get(oKey) ?? new Map()
        const oTitles = oEntry.get(platform) ?? []
        oTitles.push(title)
        oEntry.set(platform, oTitles)
        oldMap.set(oKey, oEntry)

        const nEntry = newMap.get(nKey) ?? new Map()
        const nTitles = nEntry.get(platform) ?? []
        nTitles.push(title)
        nEntry.set(platform, nTitles)
        newMap.set(nKey, nEntry)
      }
    }

    const oldMatched = [...oldMap.values()].filter(m => m.size >= 2).length
    const newMatched = [...newMap.values()].filter(m => m.size >= 2).length
    const total = newMap.size

    perRestaurant.set(rid, { old_matched: oldMatched, new_matched: newMatched, total })

    // Find newly matched: nKey has ≥2 platforms, but all contributing old keys were singletons
    for (const [nKey, platformMap] of newMap) {
      if (platformMap.size < 2) continue
      // Check if these items would have been separate under old normalizer
      const platformEntries = [...platformMap.entries()]
      const pa = platformEntries[0]
      const pb = platformEntries[1]
      const titleA = pa[1][0]
      const titleB = pb[1][0]
      const oldKeyA = normalizeOld(titleA)
      const oldKeyB = normalizeOld(titleB)
      if (oldKeyA !== oldKeyB && newlyMatched.length < 200) {
        newlyMatched.push({
          restaurant_id: rid,
          old_key_a: oldKeyA,
          old_key_b: oldKeyB,
          new_key: nKey,
          title_a: titleA,
          title_b: titleB,
          platform_a: pa[0],
          platform_b: pb[0],
        })
      }
    }
  }

  // Aggregate
  let oldTotalMatched = 0, newTotalMatched = 0, totalKeys = 0
  for (const { old_matched, new_matched, total } of perRestaurant.values()) {
    oldTotalMatched += old_matched
    newTotalMatched += new_matched
    totalKeys += total
  }

  const n = perRestaurant.size
  const oldRates = [...perRestaurant.values()].map(r => r.old_matched / (r.total || 1)).sort((a, b) => a - b)
  const newRates = [...perRestaurant.values()].map(r => r.new_matched / (r.total || 1)).sort((a, b) => a - b)
  const avg = (arr: number[]) => arr.reduce((s, x) => s + x, 0) / arr.length
  const median = (arr: number[]) => arr.length % 2 === 0
    ? (arr[arr.length / 2 - 1] + arr[arr.length / 2]) / 2
    : arr[Math.floor(arr.length / 2)]

  const pct = (x: number) => `${(x * 100).toFixed(1)}%`

  console.log(`Restaurants compared : ${n}`)
  console.log(`Total unique keys (new normalizer) : ${totalKeys.toLocaleString()}`)
  console.log()
  console.log('                   OLD        NEW      DELTA')
  console.log(`  Overall rate   : ${pct(oldTotalMatched / totalKeys).padEnd(10)} ${pct(newTotalMatched / totalKeys).padEnd(10)} +${pct((newTotalMatched - oldTotalMatched) / totalKeys)}`)
  console.log(`  Matched keys   : ${String(oldTotalMatched).padEnd(10)} ${String(newTotalMatched).padEnd(10)} +${newTotalMatched - oldTotalMatched}`)
  console.log(`  Mean rate      : ${pct(avg(oldRates)).padEnd(10)} ${pct(avg(newRates)).padEnd(10)}`)
  console.log(`  Median rate    : ${pct(median(oldRates)).padEnd(10)} ${pct(median(newRates)).padEnd(10)}`)
  console.log()
  console.log(`  Newly matched pairs found    : ${newlyMatched.length}`)

  // Sample 20 newly matched pairs
  const sample = newlyMatched.sort(() => Math.random() - 0.5).slice(0, 20)
  console.log('\n── 20 random newly-matched pairs (spot-check for false positives) ──\n')
  for (const p of sample) {
    console.log(`  [${p.platform_a}] "${p.title_a}"`)
    console.log(`  [${p.platform_b}] "${p.title_b}"`)
    console.log(`   old keys: "${p.old_key_a}" / "${p.old_key_b}"`)
    console.log(`   new key : "${p.new_key}"`)
    console.log()
  }

  // Write comparison JSON
  const outputDir = join(__dirname, 'output')
  mkdirSync(outputDir, { recursive: true })
  const outPath = join(outputDir, 'match-rate-after-normalization.json')
  writeFileSync(outPath, JSON.stringify({
    generated_at: new Date().toISOString(),
    note: 'Comparison runs old and new normalizer on identical live data.',
    aggregate: {
      restaurants_compared: n,
      total_unique_keys_new_normalizer: totalKeys,
      old_matched: oldTotalMatched,
      new_matched: newTotalMatched,
      old_overall_rate: oldTotalMatched / totalKeys,
      new_overall_rate: newTotalMatched / totalKeys,
      delta_matched: newTotalMatched - oldTotalMatched,
      delta_rate: (newTotalMatched - oldTotalMatched) / totalKeys,
      old_mean_rate: avg(oldRates),
      new_mean_rate: avg(newRates),
      old_median_rate: median(oldRates),
      new_median_rate: median(newRates),
    },
    newly_matched_sample: sample,
  }, null, 2))
  console.log(`Comparison JSON written to: ${outPath}`)
}

main().catch(err => { console.error(err); process.exit(1) })
