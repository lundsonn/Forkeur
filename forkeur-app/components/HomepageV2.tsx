'use client'

import { useState, useMemo, useCallback, useTransition } from 'react'
import Link from 'next/link'
import { useTranslations, useLocale } from 'next-intl'
import type { RestaurantSummary } from '@/lib/queries'
import { platformSavingsSelector } from '@/lib/savings'
import { COMMUNE_SLUGS, communeDisplayName, THIN_THRESHOLD, type CommuneSlug } from '@/lib/communes'
import LangToggle from './LangToggle'
import RestaurantCard from './RestaurantCard'
import HeroBlock from './HeroBlock'
import type { Platform } from '@/lib/basket'

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtFee(cents: number): string {
  if (cents === 0) return '€0'
  if (cents % 100 === 0) return `€${cents / 100}`
  return `€${(cents / 100).toFixed(2)}`
}

const PLATFORM_LABELS: Record<string, string> = {
  uber_eats: 'UberEats',
  deliveroo: 'Deliveroo',
  takeaway: 'Takeaway',
  direct: 'Direct',
}

const MIN_SAVINGS_CENTS = 50

const CUISINE_TILES_MAX = 5

const CUISINE_EMOJI: Record<string, string> = {
  pizza: '🍕', sushi: '🍣', burger: '🍔', burgers: '🍔',
  shawarma: '🌯', kebab: '🌯', noodles: '🍜', ramen: '🍜',
  thai: '🍜', chinese: '🥢', indian: '🍛', curry: '🍛',
  mexican: '🌮', tacos: '🌮', italian: '🍝', pasta: '🍝',
  greek: '🥗', salad: '🥗', sandwich: '🥪', japanese: '🍱',
  korean: '🥘', vietnamese: '🍜', american: '🍔', chicken: '🍗',
  fish: '🐟', seafood: '🦐', vegan: '🥦', vegetarian: '🥗',
  healthy: '🥗', breakfast: '🥐', dessert: '🍰', turkish: '🌯',
  lebanese: '🌮', moroccan: '🫕', spanish: '🥘', poke: '🥙',
  wok: '🥢', wings: '🍗', frites: '🍟', fries: '🍟',
}

function cuisineEmoji(name: string): string {
  return CUISINE_EMOJI[name.toLowerCase()] ?? '🍽️'
}

// ── types ────────────────────────────────────────────────────────────────────

type SavingsEntry = {
  r: RestaurantSummary
  savingCents: number
  winnerTotal: number
  winner: Platform
  runnerTotal: number | null
  runnerPlatform: Platform | null
  hasComparison: number
}

// ── component ─────────────────────────────────────────────────────────────────

type Props = {
  initialRestaurants: RestaurantSummary[]
  initialCommune: string
}

export default function HomepageV2({ initialRestaurants, initialCommune }: Props) {
  const t = useTranslations('discovery')
  const locale = useLocale()

  const [commune, setCommune] = useState<string>(initialCommune)
  const [restaurants, setRestaurants] = useState<RestaurantSummary[]>(initialRestaurants)
  const [selectedCuisine, setSelectedCuisine] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [decideIdx, setDecideIdx] = useState(-1)
  const [decideExhausted, setDecideExhausted] = useState(false)
  const [showAllCuisines, setShowAllCuisines] = useState(false)
  const [showSearch, setShowSearch] = useState(false)
  const [isPending, startTransition] = useTransition()

  // ── commune change ──────────────────────────────────────────────────────────

  const handleCommuneChange = useCallback(async (slug: string) => {
    setCommune(slug)
    setDecideIdx(-1)
    setDecideExhausted(false)
    startTransition(async () => {
      try {
        const res = await fetch(`/api/near-me?commune=${encodeURIComponent(slug)}`)
        if (res.ok) {
          const data: RestaurantSummary[] = await res.json()
          setRestaurants(data)
        }
      } catch {
        // keep current restaurants on error
      }
    })
  }, [])

  // ── derived data ────────────────────────────────────────────────────────────

  const cuisines = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of restaurants) {
      for (const c of r.cuisine) {
        counts.set(c, (counts.get(c) ?? 0) + 1)
      }
    }
    return Array.from(counts.entries())
      .filter(([, n]) => n >= 2)
      .sort((a, b) => b[1] - a[1])
      .map(([c]) => c)
  }, [restaurants])

  const cravingCuisines = useMemo(() => {
    const withComp = new Set<string>()
    for (const r of restaurants) {
      if (r.has_comparison) {
        for (const c of r.cuisine) withComp.add(c)
      }
    }
    return cuisines.filter((c) => withComp.has(c))
  }, [cuisines, restaurants])

  const cuisineFiltered = useMemo(() => {
    let list = restaurants
    if (selectedCuisine) list = list.filter((r) => r.cuisine.includes(selectedCuisine))
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter((r) => r.name.toLowerCase().includes(q))
    }
    return list
  }, [restaurants, selectedCuisine, search])

  const isThin = cuisineFiltered.length < THIN_THRESHOLD

  // savings-ranked pool (for decide + shelves)
  const savingsRanked = useMemo(() => {
    const entries: SavingsEntry[] = []
    for (const r of cuisineFiltered) {
      const sel = platformSavingsSelector(r.listings)
      if (!sel) continue
      const sorted = r.listings
        .filter((l) => l.delivery_fee_cents !== null && l.delivery_fee_cents !== undefined)
        .sort((a, b) => (a.delivery_fee_cents as number) - (b.delivery_fee_cents as number))
      const runner = sorted.length >= 2 ? sorted[1] : null
      entries.push({
        r,
        savingCents: sel.savingCents,
        winnerTotal: sel.winnerTotal,
        winner: sel.winner,
        runnerTotal: runner?.delivery_fee_cents ?? null,
        runnerPlatform: runner ? (runner.platform as Platform) : null,
        hasComparison: r.has_comparison ? 1 : 0,
      })
    }
    return entries.sort((a, b) => b.savingCents - a.savingCents)
  }, [cuisineFiltered])

  const bestValueShelf = useMemo(() => savingsRanked.slice(0, 6), [savingsRanked])

  const directWinnersShelf = useMemo(() => {
    return cuisineFiltered.filter((r) => {
      if (r.direct_url_type !== 'ordering') return false
      const platformListings = r.listings.filter(
        (l) => l.platform !== 'direct' && l.delivery_fee_cents !== null,
      )
      if (platformListings.length === 0) return false
      const minPlatformFee = Math.min(...platformListings.map((l) => l.delivery_fee_cents!))
      return minPlatformFee > 0
    })
  }, [cuisineFiltered])

  const dealsShelf = useMemo(() => {
    return cuisineFiltered.filter((r) =>
      r.listings.some((l) => l.promotions && l.promotions.length > 0),
    )
  }, [cuisineFiltered])

  // ── decide for me ───────────────────────────────────────────────────────────

  const decidePool = savingsRanked
  const decideRestaurant = decideIdx >= 0 && decideIdx < decidePool.length ? decidePool[decideIdx] : null

  const handleDecide = useCallback(() => {
    if (decidePool.length === 0) {
      setDecideExhausted(true)
      return
    }
    setDecideIdx(0)
    setDecideExhausted(false)
  }, [decidePool.length])

  const handleReroll = useCallback(() => {
    const next = decideIdx + 1
    if (next >= decidePool.length) {
      setDecideExhausted(true)
    } else {
      setDecideIdx(next)
    }
  }, [decideIdx, decidePool.length])

  const resetDecide = useCallback(() => {
    setDecideIdx(-1)
    setDecideExhausted(false)
  }, [])

  const handleTileClick = useCallback((c: string) => {
    setSelectedCuisine((prev) => (prev === c ? null : c))
    setDecideIdx(-1)
    setDecideExhausted(false)
  }, [])

  // ── helpers ─────────────────────────────────────────────────────────────────

  const communeName = (slug: string) =>
    communeDisplayName(slug, locale === 'nl' ? 'nl' : locale === 'fr' ? 'fr' : 'fr')

  const restaurantHref = (r: RestaurantSummary) =>
    r.slug ? `/restaurant/${r.slug}` : `/restaurant/${r.id}`

  const etaMin = (r: RestaurantSummary): number | null => {
    const mins = r.listings.map((l) => (l as any).eta_min).filter((v): v is number => typeof v === 'number')
    return mins.length > 0 ? Math.min(...mins) : null
  }

  // ── render vars ─────────────────────────────────────────────────────────────

  const visibleCuisines = showAllCuisines ? cravingCuisines : cravingCuisines.slice(0, CUISINE_TILES_MAX)
  const hasCuisineToggle = cravingCuisines.length > CUISINE_TILES_MAX
  const showCravingResults = Boolean(selectedCuisine && !isThin && savingsRanked.length > 0)
  const cravingHero = showCravingResults ? savingsRanked[0] : null

  // ── render ──────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-white">
      {/* NAV */}
      <nav className="sticky top-0 z-30 bg-white/95 backdrop-blur border-b border-stone-100 px-4 py-3 flex items-center gap-3">
        <Link href="/" className="flex items-center gap-1.5 font-bold text-base tracking-tight text-stone-900">
          <span className="text-stone-700 text-base">⑂</span>
          fork<span className="text-orange-500">eur</span>
        </Link>
        <div className="flex-1" />
        <LangToggle />
        <Link href="/owners" className="text-sm text-stone-500 hover:text-stone-700">
          Owners
        </Link>
        <Link href="/deals" className="text-sm font-medium text-stone-700 hover:text-orange-500">
          Deals 🏷️
        </Link>
      </nav>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-8">

        {/* HERO */}
        <HeroBlock restaurants={restaurants} neighborhood={null} />

        {/* COMMUNE SELECTOR */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-stone-500">{t('commune_label')}</span>
          <select
            value={commune}
            onChange={(e) => handleCommuneChange(e.target.value as CommuneSlug)}
            className="text-sm font-semibold text-stone-900 bg-stone-50 border border-stone-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-orange-400"
          >
            {COMMUNE_SLUGS.map((s) => (
              <option key={s} value={s}>
                {communeName(s)}
              </option>
            ))}
          </select>
          {isPending && (
            <span className="text-xs text-stone-400 animate-pulse">{t('loading')}</span>
          )}
        </div>

        {/* COLD-START SURFACE */}
        {cravingCuisines.length > 0 && (
          <div className="space-y-4">
            <h2 className="text-xl font-bold text-stone-900">{t('craving_heading')}</h2>

            {/* Cuisine tile grid */}
            <div className="grid grid-cols-3 gap-2">
              {visibleCuisines.map((c) => (
                <button
                  key={c}
                  onClick={() => handleTileClick(c)}
                  className={`flex flex-col items-center gap-1.5 py-4 px-2 rounded-2xl border-2 transition-all ${
                    selectedCuisine === c
                      ? 'border-orange-500 bg-orange-50'
                      : 'border-stone-100 bg-stone-50 hover:border-stone-300'
                  }`}
                >
                  <span className="text-2xl leading-none">{cuisineEmoji(c)}</span>
                  <span className={`text-xs font-semibold capitalize ${selectedCuisine === c ? 'text-orange-600' : 'text-stone-700'}`}>
                    {c}
                  </span>
                </button>
              ))}
              {hasCuisineToggle && (
                <button
                  onClick={() => setShowAllCuisines((v) => !v)}
                  className="flex flex-col items-center gap-1.5 py-4 px-2 rounded-2xl border-2 border-dashed border-stone-200 bg-white hover:border-stone-400 transition-all"
                >
                  <span className="text-2xl leading-none">{showAllCuisines ? '▲' : '▾'}</span>
                  <span className="text-xs font-semibold text-stone-400">
                    {showAllCuisines ? t('craving_less') : t('craving_more')}
                  </span>
                </button>
              )}
            </div>

            {/* DECIDE FOR ME (orange, inside cold-start surface) */}
            {!isThin && (
              <div className="rounded-2xl bg-orange-50 border border-orange-100 p-4 space-y-3">
                {decideExhausted ? (
                  <div className="space-y-2">
                    <p className="font-semibold text-stone-800">{t('decide_exhausted')}</p>
                    <button onClick={resetDecide} className="text-sm text-orange-600 hover:underline">
                      {t('decide_browse_all')}
                    </button>
                  </div>
                ) : decideRestaurant ? (
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-bold text-lg text-stone-900">{decideRestaurant.r.name}</p>
                        <p className="text-sm text-stone-500">
                          {decideRestaurant.r.cuisine.join(', ')}
                          {decideRestaurant.r.commune ? ` · ${communeName(decideRestaurant.r.commune)}` : ''}
                        </p>
                        <p className="text-sm text-stone-700 mt-1">
                          {t('from_label', {
                            amount: fmtFee(decideRestaurant.winnerTotal),
                            platform: PLATFORM_LABELS[decideRestaurant.winner] ?? decideRestaurant.winner,
                          })}
                          {decideRestaurant.savingCents >= MIN_SAVINGS_CENTS && (
                            <span className="ml-2 text-green-700 font-semibold">
                              · {t('save_label', { amount: fmtFee(decideRestaurant.savingCents) })}
                            </span>
                          )}
                        </p>
                      </div>
                      <Link
                        href={restaurantHref(decideRestaurant.r)}
                        className="shrink-0 bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
                      >
                        Order →
                      </Link>
                    </div>
                    <button onClick={handleReroll} className="text-sm text-orange-600 hover:underline">
                      {t('decide_not_feeling')}
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={handleDecide}
                    className="w-full bg-orange-500 hover:bg-orange-600 active:bg-orange-700 text-white font-bold py-3 px-6 rounded-xl transition-colors text-base"
                  >
                    {t('decide_btn')}
                  </button>
                )}
              </div>
            )}

            {/* Search toggle */}
            <div>
              {showSearch ? (
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus
                  placeholder="Search restaurants…"
                  className="w-full rounded-xl border border-stone-200 bg-stone-50 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400 placeholder:text-stone-400"
                />
              ) : (
                <button
                  onClick={() => setShowSearch(true)}
                  className="text-sm text-stone-400 hover:text-orange-500 transition-colors"
                >
                  {t('search_link')}
                </button>
              )}
            </div>
          </div>
        )}

        {/* CRAVING RESULTS */}
        {showCravingResults && cravingHero && (() => {
          const heroR = cravingHero.r
          const heroEta = etaMin(heroR)
          const heroImg = (heroR as any).image_url as string | null | undefined
          return (
            <section className="space-y-3">
              <p className="text-sm font-semibold text-stone-500">
                {t('craving_results_label', { cuisine: selectedCuisine, count: savingsRanked.length })}
              </p>

              {/* Hero card */}
              <Link href={restaurantHref(heroR)} className="block rounded-2xl overflow-hidden border border-stone-100 shadow-sm hover:shadow-md transition-shadow">
                {/* Photo / fallback */}
                <div className="relative h-44 bg-gradient-to-br from-stone-100 to-stone-200 overflow-hidden">
                  {heroImg ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={heroImg}
                      alt={heroR.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <span className="text-8xl opacity-20 select-none">{cuisineEmoji(heroR.cuisine[0] ?? '')}</span>
                    </div>
                  )}
                  {/* Top saver badge */}
                  <span className="absolute top-3 left-3 bg-orange-500 text-white text-xs font-bold px-2.5 py-1 rounded-full">
                    🏆 {t('top_saver_badge')}
                  </span>
                </div>

                {/* Card body */}
                <div className="p-4 space-y-1.5">
                  {/* Rating + ETA chips */}
                  <div className="flex items-center gap-2">
                    {typeof heroR.rating === 'number' && heroR.rating > 0 && (
                      <span className="text-xs font-medium text-stone-600 bg-stone-100 px-2 py-0.5 rounded-full">
                        ⭐ {heroR.rating.toFixed(1)}
                      </span>
                    )}
                    {heroEta !== null && (
                      <span className="text-xs font-medium text-stone-500 bg-stone-50 border border-stone-100 px-2 py-0.5 rounded-full">
                        🕐 {t('eta_label', { min: heroEta })}
                      </span>
                    )}
                  </div>

                  <p className="font-bold text-lg text-stone-900 leading-tight">{heroR.name}</p>

                  {/* Savings row */}
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-2xl font-black text-green-700">
                      {t('save_label', { amount: fmtFee(cravingHero.savingCents) })}
                    </span>
                    <span className="text-sm text-stone-500">
                      {t('from_label', {
                        amount: fmtFee(cravingHero.winnerTotal),
                        platform: PLATFORM_LABELS[cravingHero.winner] ?? cravingHero.winner,
                      })}
                    </span>
                    {cravingHero.runnerTotal !== null && cravingHero.runnerPlatform !== null && (
                      <span className="text-sm text-stone-400">
                        vs <span className="line-through">{fmtFee(cravingHero.runnerTotal)}</span>{' '}
                        {PLATFORM_LABELS[cravingHero.runnerPlatform] ?? cravingHero.runnerPlatform}
                      </span>
                    )}
                  </div>
                </div>
              </Link>

              {/* Remaining rows */}
              <div className="space-y-2">
                {savingsRanked.slice(1, 10).map(({ r, savingCents, winnerTotal, winner, runnerPlatform }) => {
                  const rowEta = etaMin(r)
                  const rowImg = (r as any).image_url as string | null | undefined
                  const isDirectWinner = winner === 'direct'
                  return (
                    <Link
                      key={r.id}
                      href={restaurantHref(r)}
                      className="flex items-center gap-3 p-3 rounded-xl border border-stone-100 bg-white hover:border-stone-300 hover:shadow-sm transition-all"
                    >
                      {/* Thumbnail */}
                      <div className="shrink-0 w-14 h-14 rounded-xl overflow-hidden bg-gradient-to-br from-stone-100 to-stone-200 flex items-center justify-center">
                        {rowImg ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={rowImg} alt={r.name} className="w-full h-full object-cover" />
                        ) : (
                          <span className="text-2xl opacity-30">{cuisineEmoji(r.cuisine[0] ?? '')}</span>
                        )}
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <p className="font-semibold text-stone-900 truncate">{r.name}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          {typeof r.rating === 'number' && r.rating > 0 && (
                            <span className="text-xs text-stone-500">⭐ {r.rating.toFixed(1)}</span>
                          )}
                          {rowEta !== null && (
                            <span className="text-xs text-stone-400">· {t('eta_label', { min: rowEta })}</span>
                          )}
                        </div>
                      </div>

                      {/* Right: savings + platform */}
                      <div className="shrink-0 text-right space-y-1">
                        {savingCents >= MIN_SAVINGS_CENTS && (
                          <p className="text-sm font-bold text-green-700">
                            {t('save_label', { amount: fmtFee(savingCents) })}
                          </p>
                        )}
                        <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${
                          isDirectWinner
                            ? 'bg-orange-100 text-orange-700'
                            : 'bg-stone-100 text-stone-600'
                        }`}>
                          {PLATFORM_LABELS[winner] ?? winner}
                        </span>
                      </div>
                    </Link>
                  )
                })}
              </div>
            </section>
          )
        })()}

        {/* DEFAULT SHELVES (when no cuisine selected and not thin) */}
        {!selectedCuisine && !isThin && (
          <>
            {/* BEST VALUE SHELF */}
            {bestValueShelf.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-base font-bold text-stone-900">{t('shelf_best_value')}</h2>
                <div className="space-y-2">
                  {bestValueShelf.map(({ r, savingCents, winnerTotal, winner }) => (
                    <Link
                      key={r.id}
                      href={restaurantHref(r)}
                      className="flex items-center justify-between gap-3 p-3 rounded-xl border border-stone-100 bg-white hover:border-stone-300 hover:shadow-sm transition-all"
                    >
                      <div className="min-w-0">
                        <p className="font-semibold text-stone-900 truncate">{r.name}</p>
                        <p className="text-xs text-stone-400 truncate">
                          {r.cuisine.join(', ')}
                          {r.commune ? ` · ${communeName(r.commune)}` : ''}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="text-sm font-medium text-stone-700">
                          {t('from_label', {
                            amount: fmtFee(winnerTotal),
                            platform: PLATFORM_LABELS[winner] ?? winner,
                          })}
                        </p>
                        {savingCents >= MIN_SAVINGS_CENTS && (
                          <p className="text-xs font-semibold text-green-700">
                            {t('save_label', { amount: fmtFee(savingCents) })}
                          </p>
                        )}
                      </div>
                    </Link>
                  ))}
                </div>
              </section>
            )}

            {/* SKIP THE FEES SHELF */}
            {directWinnersShelf.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-base font-bold text-stone-900">{t('shelf_direct')}</h2>
                <div className="space-y-2">
                  {directWinnersShelf.slice(0, 6).map((r) => (
                    <a
                      key={r.id}
                      href={r.order_url ?? restaurantHref(r)}
                      target={r.order_url ? '_blank' : undefined}
                      rel={r.order_url ? 'noopener noreferrer' : undefined}
                      className="flex items-center justify-between gap-3 p-3 rounded-xl border border-orange-100 bg-orange-50 hover:border-orange-300 hover:shadow-sm transition-all"
                    >
                      <div className="min-w-0">
                        <p className="font-semibold text-stone-900 truncate">{r.name}</p>
                        <p className="text-xs text-stone-400 truncate">
                          {r.cuisine.join(', ')}
                          {r.commune ? ` · ${communeName(r.commune)}` : ''}
                        </p>
                      </div>
                      <span className="shrink-0 text-xs font-semibold text-orange-700 bg-orange-100 px-2 py-1 rounded-full">
                        {t('no_platform_fee')}
                      </span>
                    </a>
                  ))}
                </div>
              </section>
            )}

            {/* TONIGHT'S DEALS SHELF */}
            {dealsShelf.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-base font-bold text-stone-900">{t('shelf_deals')}</h2>
                <div className="space-y-2">
                  {dealsShelf.slice(0, 6).map((r) => {
                    const promoListings = r.listings.filter(
                      (l) => l.promotions && l.promotions.length > 0,
                    )
                    const firstPromo = promoListings[0]?.promotions?.[0]
                    return (
                      <Link
                        key={r.id}
                        href={restaurantHref(r)}
                        className="flex items-center justify-between gap-3 p-3 rounded-xl border border-stone-100 bg-white hover:border-stone-300 hover:shadow-sm transition-all"
                      >
                        <div className="min-w-0">
                          <p className="font-semibold text-stone-900 truncate">{r.name}</p>
                          <p className="text-xs text-stone-400 truncate">
                            {r.cuisine.join(', ')}
                            {r.commune ? ` · ${communeName(r.commune)}` : ''}
                          </p>
                        </div>
                        {firstPromo && (
                          <span className="shrink-0 text-xs font-medium text-stone-700 bg-stone-100 px-2 py-1 rounded-full max-w-[140px] truncate">
                            {firstPromo.label}
                          </span>
                        )}
                      </Link>
                    )
                  })}
                </div>
              </section>
            )}
          </>
        )}

        {/* THIN STATE: full restaurant list */}
        {isThin && cuisineFiltered.length > 0 && (
          <section className="space-y-3">
            <p className="text-sm text-stone-400">{t('thin_hint', { count: cuisineFiltered.length })}</p>
            <div className="space-y-2">
              {cuisineFiltered.map((r, i) => (
                <RestaurantCard
                  key={r.id}
                  restaurant={r}
                  href={restaurantHref(r)}
                  directBadge="Order direct"
                  priority={i < 3}
                />
              ))}
            </div>
          </section>
        )}

        {/* FOOTER */}
        {!isThin && (
          <div className="pt-4 border-t border-stone-100 text-center">
            <p className="text-sm text-stone-400">
              {restaurants.length} restaurants compared near {communeName(commune)}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
