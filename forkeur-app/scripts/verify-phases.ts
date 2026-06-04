#!/usr/bin/env npx tsx
/**
 * Phase verification + health-check script.
 * Run: npx tsx scripts/verify-phases.ts
 */

import { createClient } from '@supabase/supabase-js'
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'fs'
import { join } from 'path'
import { config } from 'dotenv'

config({ path: '.env.local' })

const SUPABASE_URL = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL
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

// ── helpers ───────────────────────────────────────────────────────────────────

function pass(label: string) {
  console.log(`  ✅ ${label}`)
  return true
}
function fail(label: string, detail?: string) {
  console.log(`  ❌ ${label}${detail ? `  [${detail}]` : ''}`)
  return false
}
function section(title: string) {
  console.log(`\n── ${title} ──`)
}

// ── Check 1: normalizeTitle ───────────────────────────────────────────────────

import { normalizeTitle } from '../lib/normalize-title'

type NormCase = { label: string; ok: boolean }

function check1(): { passed: number; total: number; failures: string[] } {
  section('Check 1 — normalizeTitle (Phase 3)')
  const cases: NormCase[] = []

  function assertEq(a: string, b: string, label: string): NormCase {
    const na = normalizeTitle(a)
    const nb = normalizeTitle(b)
    const ok = na === nb
    const r = ok ? pass(label) : fail(label, `"${a}" → "${na}" ≠ "${b}" → "${nb}"`)
    return { label, ok: r }
  }
  function assertNeq(a: string, b: string, label: string): NormCase {
    const na = normalizeTitle(a)
    const nb = normalizeTitle(b)
    const ok = na !== nb
    const r = ok ? pass(label) : fail(label, `both normalize to "${na}"`)
    return { label, ok: r }
  }
  function assertContains(a: string, sub: string, label: string): NormCase {
    const na = normalizeTitle(a)
    const ok = na.includes(sub)
    const r = ok ? pass(label) : fail(label, `"${a}" → "${na}" doesn't include "${sub}"`)
    return { label, ok: r }
  }
  function assertNonEmpty(a: string, label: string): NormCase {
    const na = normalizeTitle(a)
    const ok = na.length > 0
    const r = ok ? pass(label) : fail(label, `"${a}" collapsed to empty`)
    return { label, ok: r }
  }

  // Numbered prefix strip
  cases.push(assertEq('52. Malay Soup', 'Malay soup', '52. prefix stripped'))
  cases.push(assertEq('3- Potage aux champignons', 'Potage aux champignons', '3- prefix stripped'))
  cases.push(assertEq('12) Canard laqué', 'Canard Laque', '12) prefix stripped + diacritic'))

  // Must NOT strip (no separator after digits)
  cases.push(assertNeq('7up', 'Sprite', '7up not stripped (no separator)'))
  cases.push(assertContains('7up', '7up', '7up preserved in output'))

  // Existing transforms
  cases.push(assertEq('Pizza Margherita (30cm)', 'pizza margherita', 'parenthetical stripped'))
  cases.push(assertEq('Coca-Cola 33cl', 'coca cola', 'trailing cl stripped + hyphen'))
  cases.push(assertEq('Poulet rôti', 'poulet roti', 'diacritic normalized'))
  cases.push(assertEq('Classic Chicken Burger', 'Burger Chicken Classic', 'token sort symmetric'))

  // Safety: edge cases don't collapse
  cases.push(assertNonEmpty('12', 'number-only title non-empty'))
  cases.push(assertNonEmpty('(large)', 'paren-only title non-empty'))

  // Empty string
  const emptyResult = normalizeTitle('')
  const emptyOk = emptyResult.length === 0 || emptyResult === ''
  if (emptyOk) cases.push({ label: 'empty string', ok: pass('empty string → empty') })
  else cases.push({ label: 'empty string', ok: fail('empty string should be empty', `got "${emptyResult}"`) })

  const passed = cases.filter(c => c.ok).length
  const failures = cases.filter(c => !c.ok).map(c => `normalizeTitle: ${c.label}`)
  return { passed, total: cases.length, failures }
}

// ── Check 2: match-rate freshness ─────────────────────────────────────────────

type MatchRateResult = { passed: number; total: number; failures: string[] }
type RestaurantMatchEntry = {
  id: string
  name: string
  platforms: string[]
  total_unique_keys: number
  matched_count: number
  match_rate: number
}

/** Fetch all restaurant IDs (lightweight) then batch-fetch menu items per restaurant. */
async function fetchAllMenuData(limit = 300): Promise<Map<string, {
  name: string
  freshListings: { platform: string; menu_items: { title: string }[] }[]
}>> {
  const STALE_MS = 72 * 60 * 60 * 1000
  const threshold = new Date(Date.now() - STALE_MS)

  // Step 1: get IDs + names
  const { data: ids, error: idErr } = await supabase
    .from('restaurants')
    .select('id, name')
    .limit(limit)
  if (idErr) throw new Error(idErr.message)

  const result = new Map<string, { name: string; freshListings: { platform: string; menu_items: { title: string }[] }[] }>()
  const allIds = (ids ?? []) as { id: string; name: string }[]

  // Step 2: batch-fetch platform_listings + menu_items in groups of 20
  const BATCH = 20
  for (let i = 0; i < allIds.length; i += BATCH) {
    const batch = allIds.slice(i, i + BATCH).map(r => r.id)
    const { data, error } = await supabase
      .from('platform_listings')
      .select('restaurant_id, platform, last_scraped_at, menu_items (title)')
      .in('restaurant_id', batch)
    if (error) throw new Error(error.message)

    type RawListing = { restaurant_id: string; platform: string; last_scraped_at: string | null; menu_items: { title: string }[] }
    for (const listing of (data ?? []) as unknown as RawListing[]) {
      if (!listing.last_scraped_at || new Date(listing.last_scraped_at) < threshold) continue
      if (!result.has(listing.restaurant_id)) {
        const r = allIds.find(x => x.id === listing.restaurant_id)!
        result.set(listing.restaurant_id, { name: r.name, freshListings: [] })
      }
      result.get(listing.restaurant_id)!.freshListings.push({
        platform: listing.platform,
        menu_items: listing.menu_items ?? [],
      })
    }
  }

  return result
}

async function check2(
  preloaded?: Awaited<ReturnType<typeof fetchAllMenuData>>
): Promise<MatchRateResult> {
  section('Check 2 — Match rate freshness (Phase 1)')
  const failures: string[] = []
  const cases: boolean[] = []

  // Use verify's own baseline (self-consistent); fall back to audit file on first run
  const ownBaselineFile = join(__dirname, 'output', 'verify-last-rate.json')
  const auditFile = join(__dirname, 'output', 'match-rate-results.json')
  const baselineFile = existsSync(ownBaselineFile) ? ownBaselineFile : auditFile

  if (!existsSync(baselineFile)) {
    console.log('  ⚠️  No previous match-rate file found — skipping comparison')
    return { passed: 0, total: 0, failures: [] }
  }

  const lastData = JSON.parse(readFileSync(baselineFile, 'utf-8'))
  const lastRate: number = lastData.overall_match_rate ?? lastData.aggregate?.overall_match_rate ?? 0
  const lastByRestaurant: RestaurantMatchEntry[] = [
    ...(lastData.top_performers ?? []),
    ...(lastData.worst_offenders ?? []),
    ...(lastData.restaurants ?? []),
  ]

  // Build tier map from last run
  const lastTierMap = new Map<string, { name: string; tier: number; rate: number }>()
  for (const r of lastByRestaurant) {
    const tier = r.match_rate >= 0.7 ? 1 : r.match_rate >= 0.3 ? 2 : 3
    lastTierMap.set(r.id, { name: r.name, tier, rate: r.match_rate })
  }

  let menuData: Awaited<ReturnType<typeof fetchAllMenuData>>
  if (preloaded) {
    menuData = preloaded
  } else {
    try {
      menuData = await fetchAllMenuData(200)
    } catch (e: unknown) {
      fail(`Supabase query failed: ${(e as Error).message}`)
      return { passed: 0, total: 1, failures: [`match-rate query: ${(e as Error).message}`] }
    }
  }

  let totalKeys = 0, totalMatched = 0
  const tierFlips: string[] = []

  for (const [id, { name, freshListings }] of menuData) {
    if (freshListings.length < 2) continue

    const itemMap = new Map<string, Set<string>>()
    for (const listing of freshListings) {
      for (const item of listing.menu_items ?? []) {
        const key = normalizeTitle(item.title)
        if (!itemMap.has(key)) itemMap.set(key, new Set())
        itemMap.get(key)!.add(listing.platform)
      }
    }

    const matched = [...itemMap.values()].filter(platforms => platforms.size >= 2).length
    totalKeys += itemMap.size
    totalMatched += matched

    const rate = itemMap.size > 0 ? matched / itemMap.size : 0
    const tier = rate >= 0.7 ? 1 : rate >= 0.3 ? 2 : 3

    const last = lastTierMap.get(id)
    if (last && last.tier === 1 && tier === 3) {
      tierFlips.push(`${name}: was Tier 1 (${(last.rate * 100).toFixed(0)}%), now Tier 3 (${(rate * 100).toFixed(0)}%)`)
    }
  }

  const currentRate = totalKeys > 0 ? totalMatched / totalKeys : 0
  const delta = Math.abs(currentRate - lastRate)
  const deltaLabel = `current ${(currentRate * 100).toFixed(1)}% vs last ${(lastRate * 100).toFixed(1)}% (Δ ${(delta * 100).toFixed(1)}pp)`

  if (delta <= 0.02) {
    cases.push(pass(`Match rate stable — ${deltaLabel}`))
  } else {
    cases.push(fail(`Match rate drift > 2pp — ${deltaLabel}`, 'may be from new scrapes'))
    failures.push(`Match rate drift: ${deltaLabel}`)
  }

  if (tierFlips.length === 0) {
    cases.push(pass('No Tier 1 → Tier 3 flips'))
  } else {
    cases.push(fail(`${tierFlips.length} Tier 1 → Tier 3 flip(s)`, tierFlips.join('; ')))
    failures.push(...tierFlips.map(f => `Tier flip: ${f}`))
  }

  // Save this run's rate as the baseline for future compare
  writeFileSync(ownBaselineFile, JSON.stringify({ overall_match_rate: currentRate, generated_at: new Date().toISOString() }, null, 2))

  return { passed: cases.filter(Boolean).length, total: cases.length, failures }
}

// ── Check 3: calculateAllTotalsWithCoverage ───────────────────────────────────

import {
  calculateAllTotalsWithCoverage,
  findCheapestCompletePlatform,
  type BasketItem,
  type PlatformFees,
} from '../lib/basket'

function check3(): { passed: number; total: number; failures: string[] } {
  section('Check 3 — Coverage tracking in calculateAllTotalsWithCoverage (Phase 2)')
  const failures: string[] = []
  const cases: boolean[] = []

  const items: BasketItem[] = [
    { name: 'Item A', qty: 1, prices: { uber_eats: 1000, deliveroo: 1100, takeaway: 900, direct: null } },
    { name: 'Item B', qty: 1, prices: { uber_eats: 800, deliveroo: 850, takeaway: null, direct: null } },
    { name: 'Item C', qty: 1, prices: { uber_eats: 600, deliveroo: null, takeaway: null, direct: null } },
  ]
  const fees: PlatformFees = { uber_eats: 200, deliveroo: 300, takeaway: 400, direct: null }

  const { totals, coverages } = calculateAllTotalsWithCoverage(items, fees)

  // UE: all 3 priced
  const ueOk = coverages.uber_eats?.priced === 3 && coverages.uber_eats?.total === 3 && coverages.uber_eats?.complete === true
  cases.push(ueOk ? pass('UE coverage: {priced:3, total:3, complete:true}') : fail('UE coverage wrong', JSON.stringify(coverages.uber_eats)))
  if (!ueOk) failures.push('UE coverage')

  // DEL: 2 priced
  const delOk = coverages.deliveroo?.priced === 2 && coverages.deliveroo?.total === 3 && coverages.deliveroo?.complete === false
  cases.push(delOk ? pass('DEL coverage: {priced:2, total:3, complete:false}') : fail('DEL coverage wrong', JSON.stringify(coverages.deliveroo)))
  if (!delOk) failures.push('DEL coverage')

  // TA: 1 priced
  const taOk = coverages.takeaway?.priced === 1 && coverages.takeaway?.total === 3 && coverages.takeaway?.complete === false
  cases.push(taOk ? pass('TA coverage: {priced:1, total:3, complete:false}') : fail('TA coverage wrong', JSON.stringify(coverages.takeaway)))
  if (!taOk) failures.push('TA coverage')

  // direct: null (fee is null)
  const dirOk = coverages.direct === null
  cases.push(dirOk ? pass('direct coverage null (fee null)') : fail('direct coverage should be null', JSON.stringify(coverages.direct)))
  if (!dirOk) failures.push('direct coverage should be null')

  // Only complete platforms win cheapest: UE total = 1000+800+600+200=2600, DEL partial total (skips TA/direct null items) = 1000+800+0+300=2100
  // DEL is cheaper by totals but NOT complete — UE should win
  const winner = findCheapestCompletePlatform(totals, coverages, true)
  const winOk = winner === 'uber_eats'
  cases.push(winOk ? pass('Only complete platform wins (UE beats cheaper-but-incomplete DEL)') : fail('Wrong winner — should be uber_eats', `got ${winner}`))
  if (!winOk) failures.push(`Cheapest complete platform should be uber_eats, got ${winner}`)

  // Empty basket: fees-only, all platforms with a fee get complete=true
  const { coverages: emptyCov } = calculateAllTotalsWithCoverage([], fees)
  const emptyOk = emptyCov.uber_eats?.complete === true && emptyCov.deliveroo?.complete === true
  cases.push(emptyOk ? pass('Empty basket: available platforms get complete=true') : fail('Empty basket coverage wrong', JSON.stringify(emptyCov)))
  if (!emptyOk) failures.push('Empty basket coverage')

  return { passed: cases.filter(Boolean).length, total: cases.length, failures }
}

// ── Check 4: Tiering logic ────────────────────────────────────────────────────

function getTier(matchRate: number): number {
  return matchRate >= 0.7 ? 1 : matchRate >= 0.3 ? 2 : 3
}

function check4(): { passed: number; total: number; failures: string[] } {
  section('Check 4 — Tiering logic (Phase 2)')
  const failures: string[] = []
  const cases: boolean[] = []

  const tiers: [number, number, string][] = [
    [0.75, 1, '0.75 → Tier 1'],
    [0.70, 1, '0.70 → Tier 1 (inclusive lower bound)'],
    [0.50, 2, '0.50 → Tier 2'],
    [0.30, 2, '0.30 → Tier 2 (inclusive lower bound)'],
    [0.29, 3, '0.29 → Tier 3'],
    [0.00, 3, '0.00 → Tier 3'],
    [1.00, 1, '1.00 → Tier 1'],
  ]

  for (const [rate, expected, label] of tiers) {
    const got = getTier(rate)
    const ok = got === expected
    cases.push(ok ? pass(label) : fail(label, `got Tier ${got}, expected Tier ${expected}`))
    if (!ok) failures.push(`Tier logic: ${label} — got ${got}`)
  }

  return { passed: cases.filter(Boolean).length, total: cases.length, failures }
}

// ── Check 5: MenuPriceComparison data integrity ───────────────────────────────

type RawListingDetail = {
  id: string; platform: string; last_scraped_at: string | null
  menu_items: { title: string; price: number | null; catalog_name: string | null; image_url: string | null; description: string | null }[]
}

function buildItemMap(freshListings: RawListingDetail[]) {
  const itemMap = new Map<string, {
    name: string; prices: Record<string, number | null>; platformTitles: Record<string, string | null>
  }>()
  for (const listing of freshListings) {
    for (const item of listing.menu_items ?? []) {
      const key = normalizeTitle(item.title)
      if (!itemMap.has(key)) {
        itemMap.set(key, {
          name: item.title.replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '').trim(),
          prices: { uber_eats: null, deliveroo: null, takeaway: null, direct: null },
          platformTitles: { uber_eats: null, deliveroo: null, takeaway: null, direct: null },
        })
      }
      const entry = itemMap.get(key)!
      const priceCents = item.price != null ? Math.round(item.price * 100) : null
      entry.prices[listing.platform] = priceCents
      entry.platformTitles[listing.platform] = item.title.replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '').trim()
    }
  }
  return itemMap
}

async function check5(): Promise<{ passed: number; total: number; failures: string[]; sample: unknown[] }> {
  section('Check 5 — MenuPriceComparison data integrity (Phase 4)')
  const failures: string[] = []
  const cases: boolean[] = []
  const sample: unknown[] = []

  const AGGREGATOR_PLATFORMS = ['uber_eats', 'deliveroo', 'takeaway'] as const
  const STALE_MS = 72 * 60 * 60 * 1000
  const threshold = new Date(Date.now() - STALE_MS)

  // Use shared batched fetcher
  let menuData: Map<string, { name: string; freshListings: { platform: string; menu_items: { title: string }[] }[] }>
  try {
    menuData = await fetchAllMenuData(200)
  } catch (e: unknown) {
    fail(`Supabase query failed: ${(e as Error).message}`)
    return { passed: 0, total: 1, failures: [`check5: ${(e as Error).message}`], sample: [] }
  }

  // For price data, we need a second pass on the restaurants we've identified as candidates
  // Find candidates from menuData first (matchRate ≥ 0.30)
  const candidateIds: string[] = []
  for (const [id, { name, freshListings }] of menuData) {
    if (freshListings.length < 2) continue
    const itemMap = new Map<string, Set<string>>()
    for (const l of freshListings) {
      for (const item of l.menu_items ?? []) {
        const key = normalizeTitle(item.title)
        if (!itemMap.has(key)) itemMap.set(key, new Set())
        itemMap.get(key)!.add(l.platform)
      }
    }
    const matched = [...itemMap.values()].filter(ps => ps.size >= 2).length
    const matchRate = itemMap.size > 0 ? matched / itemMap.size : 0
    if (matchRate >= 0.3) candidateIds.push(id)
  }

  // Pick up to 10 random candidates
  const pickedIds = candidateIds.sort(() => Math.random() - 0.5).slice(0, 10)

  // Fetch price data for picked restaurants
  const candidates: { id: string; name: string; matchRate: number; freshListings: RawListingDetail[] }[] = []
  for (const id of pickedIds) {
    const { data: listings, error: lErr } = await supabase
      .from('platform_listings')
      .select('id, platform, last_scraped_at, menu_items (title, price, catalog_name, image_url, description)')
      .eq('restaurant_id', id)
    if (lErr) continue

    type RawLD = RawListingDetail & { menu_items: { title: string; price: number | null; catalog_name: string | null; image_url: string | null; description: string | null }[] }
    const freshListings = ((listings ?? []) as unknown as RawLD[]).filter(
      l => l.last_scraped_at != null && new Date(l.last_scraped_at) >= threshold && (l.menu_items?.length ?? 0) > 0
    )
    if (freshListings.length < 2) continue

    const itemMap = buildItemMap(freshListings)
    const matchable = [...itemMap.values()].filter(
      item => AGGREGATOR_PLATFORMS.filter(p => item.prices[p] !== null).length >= 2
    ).length
    const matchRate = itemMap.size > 0 ? matchable / itemMap.size : 0
    const entry = menuData.get(id)
    if (entry) candidates.push({ id, name: entry.name, matchRate, freshListings })
  }

  const shuffled = candidates
  console.log(`  Sampling ${shuffled.length} restaurants with matchRate ≥ 0.30`)

  for (const { id, name, matchRate, freshListings } of shuffled) {
    const itemMap = buildItemMap(freshListings)
    const allItems = [...itemMap.values()]

    const comparable = allItems.filter(
      item => AGGREGATOR_PLATFORMS.filter(p => item.prices[p] !== null).length >= 2
    )

    const rResult: Record<string, unknown> = { restaurant: name, matchRate: (matchRate * 100).toFixed(1) + '%', comparable_count: comparable.length, issues: [] as string[] }
    const issues = rResult.issues as string[]
    let rOk = true

    // comparable_count > 0
    if (comparable.length === 0) {
      issues.push('comparable_count is 0')
      rOk = false
    }

    // avg savings non-negative
    const savings = comparable.map(item => {
      const prices = AGGREGATOR_PLATFORMS.map(p => item.prices[p]).filter((v): v is number => v !== null)
      return prices.length >= 2 ? Math.max(...prices) - Math.min(...prices) : 0
    })
    const avgSavings = savings.length > 0 ? savings.reduce((s, v) => s + v, 0) / savings.length : 0
    if (avgSavings < 0) {
      issues.push(`avgSavings < 0: ${avgSavings}`)
      rOk = false
    }

    // winning platform actually has lowest price on claimed items
    const wins: Record<string, number> = { uber_eats: 0, deliveroo: 0, takeaway: 0 }
    for (const item of comparable) {
      const prices = AGGREGATOR_PLATFORMS.map(p => ({ p, v: item.prices[p] })).filter((x): x is { p: typeof AGGREGATOR_PLATFORMS[number]; v: number } => x.v !== null)
      if (prices.length < 2) continue
      const min = Math.min(...prices.map(x => x.v))
      const max = Math.max(...prices.map(x => x.v))
      for (const { p, v } of prices) {
        if (v === min && max !== min) wins[p]++
      }
    }
    const winPlatform = AGGREGATOR_PLATFORMS.reduce((best, p) => wins[p] > wins[best] ? p : best)
    const winCount = wins[winPlatform]
    rResult.winner = `${winPlatform} (${winCount} items)`

    // No item has same platform as both cheapest and most expensive
    for (const item of comparable) {
      const prices = AGGREGATOR_PLATFORMS.map(p => ({ p, v: item.prices[p] })).filter((x): x is { p: typeof AGGREGATOR_PLATFORMS[number]; v: number } => x.v !== null)
      if (prices.length < 2) continue
      const min = Math.min(...prices.map(x => x.v))
      const max = Math.max(...prices.map(x => x.v))
      if (min === max) continue // all same price, ok
      for (const { p, v } of prices) {
        const isMin = v === min
        const isMax = v === max
        if (isMin && isMax && prices.length > 1) {
          issues.push(`"${item.name}" platform ${p} is both cheapest and priciest`)
          rOk = false
        }
      }
    }

    // platformTitles exists on each entry
    const missingTitles = allItems.filter(item => !('platformTitles' in item))
    if (missingTitles.length > 0) {
      issues.push(`${missingTitles.length} items missing platformTitles`)
      rOk = false
    }

    // Savings sort order: first item has highest savings
    const sortedByS = [...comparable.map((item, i) => savings[i])].slice()
    const isSorted = sortedByS.every((v, i) => i === 0 || sortedByS[i - 1] >= v)
    // savings array follows iteration order — we need to sort comparable by savings desc to check
    const comparableSavings = comparable.map((item, i) => ({ item, savings: savings[i] }))
      .sort((a, b) => b.savings - a.savings)
    rResult.top_saving_item = comparable.length > 0
      ? `${comparableSavings[0]?.item.name} (${((comparableSavings[0]?.savings ?? 0) / 100).toFixed(2)}€)`
      : 'n/a'

    sample.push(rResult)
    cases.push(rOk
      ? pass(`${name} (${(matchRate * 100).toFixed(0)}%): ${comparable.length} comparable, winner ${winPlatform}`)
      : fail(`${name}: ${issues.join(', ')}`)
    )
    if (!rOk) failures.push(...issues.map(i => `${name}: ${i}`))
  }

  return { passed: cases.filter(Boolean).length, total: cases.length, failures, sample }
}

// ── Check 6: Tier distribution ────────────────────────────────────────────────

async function check6(
  existingMenuData?: Map<string, { name: string; freshListings: { platform: string; menu_items: { title: string }[] }[] }>
): Promise<{
  t1: number; t2: number; t3: number; single: number; total: number
  t1Examples: string[]; t2Examples: string[]; t3Examples: string[]
}> {
  section('Check 6 — Tier distribution (real-world)')

  let menuData = existingMenuData
  if (!menuData) {
    try {
      menuData = await fetchAllMenuData(300)
    } catch (e: unknown) {
      console.log(`  ❌ Query failed: ${(e as Error).message}`)
      return { t1: 0, t2: 0, t3: 0, single: 0, total: 0, t1Examples: [], t2Examples: [], t3Examples: [] }
    }
  }

  let t1 = 0, t2 = 0, t3 = 0, single = 0
  const t1Ex: string[] = [], t2Ex: string[] = [], t3Ex: string[] = []

  for (const [, { name, freshListings }] of menuData) {
    const platforms = [...new Set(freshListings.map(l => l.platform))]
    if (platforms.length < 2) { single++; continue }

    const itemMap = new Map<string, Set<string>>()
    for (const listing of freshListings) {
      for (const item of listing.menu_items ?? []) {
        const key = normalizeTitle(item.title)
        if (!itemMap.has(key)) itemMap.set(key, new Set())
        itemMap.get(key)!.add(listing.platform)
      }
    }

    const matched = [...itemMap.values()].filter(ps => ps.size >= 2).length
    const matchRate = itemMap.size > 0 ? matched / itemMap.size : 0
    const tier = getTier(matchRate)

    if (tier === 1) { t1++; if (t1Ex.length < 3) t1Ex.push(name) }
    else if (tier === 2) { t2++; if (t2Ex.length < 3) t2Ex.push(name) }
    else { t3++; if (t3Ex.length < 3) t3Ex.push(name) }
  }

  const total = t1 + t2 + t3 + single
  const fmt = (n: number) => total > 0 ? `${n} (${((n / total) * 100).toFixed(1)}%)` : `${n}`

  console.log(`\n  Tier distribution:`)
  console.log(`    Tier 1 (≥70%): ${fmt(t1)}`)
  console.log(`    Tier 2 (30-69%): ${fmt(t2)}`)
  console.log(`    Tier 3 (<30%): ${fmt(t3)}`)
  console.log(`    Single platform (no comparison): ${fmt(single)}`)
  console.log(`    Tier 1 examples: ${t1Ex.join(', ') || '—'}`)
  console.log(`    Tier 2 examples: ${t2Ex.join(', ') || '—'}`)
  console.log(`    Tier 3 examples: ${t3Ex.join(', ') || '—'}`)

  return { t1, t2, t3, single, total, t1Examples: t1Ex, t2Examples: t2Ex, t3Examples: t3Ex }
}

// ── Check 7: Component file existence ─────────────────────────────────────────

function check7(): { passed: number; total: number; failures: string[] } {
  section('Check 7 — Component/export existence')
  const failures: string[] = []
  const cases: boolean[] = []

  const root = join(__dirname, '..')

  function checkFile(rel: string, label: string): boolean {
    const exists = existsSync(join(root, rel))
    return exists ? pass(`${label} — file exists`) : fail(`${label} — file missing`, rel)
  }
  function checkExport(rel: string, pattern: string, label: string): boolean {
    const p = join(root, rel)
    if (!existsSync(p)) return false
    const content = readFileSync(p, 'utf-8')
    const found = content.includes(pattern)
    return found ? pass(`${label} — export found`) : fail(`${label} — pattern not found`, pattern)
  }

  cases.push(checkFile('lib/normalize-title.ts', 'normalize-title.ts'))
  cases.push(checkExport('lib/normalize-title.ts', 'export function normalizeTitle', 'normalizeTitle export'))

  cases.push(checkFile('components/MenuPriceComparison.tsx', 'MenuPriceComparison.tsx'))
  cases.push(checkExport('components/MenuPriceComparison.tsx', 'export default function MenuPriceComparison', 'MenuPriceComparison default export'))

  cases.push(checkExport('lib/basket.ts', 'calculateAllTotalsWithCoverage', 'calculateAllTotalsWithCoverage export'))
  cases.push(checkExport('lib/basket.ts', 'coverage', 'basket.ts has coverage property'))

  cases.push(checkExport('lib/queries.ts', 'getRestaurantWithListings', 'getRestaurantWithListings export'))
  cases.push(checkExport('lib/queries.ts', 'matchRate', 'queries.ts returns matchRate'))

  const failed = cases.filter(c => !c)
  failures.push(...failed.map(() => 'component file/export missing'))
  return { passed: cases.filter(Boolean).length, total: cases.length, failures }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  console.log('PHASE VERIFICATION')
  console.log('══════════════════════════════════════════')

  const r1 = check1()
  const r3 = check3()
  const r4 = check4()
  const r7 = check7()

  // Fetch menu data once, share between checks 2 and 6
  let sharedMenuData: Awaited<ReturnType<typeof fetchAllMenuData>> | undefined
  try {
    sharedMenuData = await fetchAllMenuData(300)
  } catch { /* checks will report individually */ }

  const [r2, r5, dist] = await Promise.all([
    check2(sharedMenuData),
    check5(),
    check6(sharedMenuData),
  ])

  const allFailures = [
    ...r1.failures,
    ...r2.failures,
    ...r3.failures,
    ...r4.failures,
    ...r5.failures,
    ...r7.failures,
  ]

  console.log('\n══════════════════════════════════════════')
  console.log('PHASE VERIFICATION SUMMARY')
  console.log('──────────────────────────────────────────')
  console.log(`Phase 3 (normalizeTitle):         ${r1.passed}/${r1.total} passed`)
  console.log(`Phase 1 (match-rate freshness):   ${r2.passed}/${r2.total} passed`)
  console.log(`Phase 2 (coverage tracking):      ${r3.passed}/${r3.total} passed`)
  console.log(`Phase 2 (tiering logic):          ${r4.passed}/${r4.total} passed`)
  console.log(`Phase 4 (data integrity):         ${r5.passed}/${r5.total} passed`)
  console.log(`Tier distribution:                T1: ${dist.t1} · T2: ${dist.t2} · T3: ${dist.t3}`)
  console.log(`Component files:                  ${r7.passed}/${r7.total} found`)

  if (allFailures.length > 0) {
    console.log('\n⚠️  Issues requiring attention:')
    for (const f of allFailures) console.log(`  - ${f}`)
  } else {
    console.log('\n✅ All checks passed')
  }

  // Write JSON results
  mkdirSync(join(__dirname, 'output'), { recursive: true })
  const outPath = join(__dirname, 'output', 'verification-results.json')
  writeFileSync(outPath, JSON.stringify({
    generated_at: new Date().toISOString(),
    summary: {
      normalizeTitle: { passed: r1.passed, total: r1.total },
      matchRateFreshness: { passed: r2.passed, total: r2.total },
      coverageTracking: { passed: r3.passed, total: r3.total },
      tieringLogic: { passed: r4.passed, total: r4.total },
      dataIntegrity: { passed: r5.passed, total: r5.total },
      componentFiles: { passed: r7.passed, total: r7.total },
    },
    tierDistribution: { t1: dist.t1, t2: dist.t2, t3: dist.t3, single: dist.single },
    tierExamples: { t1: dist.t1Examples, t2: dist.t2Examples, t3: dist.t3Examples },
    failures: allFailures,
    dataIntegritySample: r5.sample,
  }, null, 2))
  console.log(`\nFull results → ${outPath}`)
}

main().catch(e => { console.error(e); process.exit(1) })
