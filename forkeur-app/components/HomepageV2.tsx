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

// ── types ────────────────────────────────────────────────────────────────────

type SavingsEntry = {
  r: RestaurantSummary
  savingCents: number
  winnerTotal: number
  winner: Platform
  hasComparison: number
}

// ── component ─────────────────────────────────────────────────────────────────

type Props = {
  initialRestaurants: RestaurantSummary[]
  initialCommune: string
}

export default function HomepageV2({ initialRestaurants, initialCommune }: Props) {
  const t = useTranslations('discovery')
  const tPlatform = useTranslations('platform')
  const locale = useLocale()

  const [commune, setCommune] = useState<string>(initialCommune)
  const [restaurants, setRestaurants] = useState<RestaurantSummary[]>(initialRestaurants)
  const [selectedCuisine, setSelectedCuisine] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [decideIdx, setDecideIdx] = useState(-1)
  const [decideExhausted, setDecideExhausted] = useState(false)
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

  // savings-ranked pool (for decide + best-value shelf)
  const savingsRanked = useMemo(() => {
    const entries: SavingsEntry[] = []
    for (const r of cuisineFiltered) {
      const sel = platformSavingsSelector(r.listings)
      if (!sel) continue
      entries.push({
        r,
        savingCents: sel.savingCents,
        winnerTotal: sel.winnerTotal,
        winner: sel.winner,
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

  // ── commune display ─────────────────────────────────────────────────────────

  const communeName = (slug: string) =>
    communeDisplayName(slug, locale === 'nl' ? 'nl' : locale === 'fr' ? 'fr' : 'fr')

  // ── restaurant href ─────────────────────────────────────────────────────────

  const restaurantHref = (r: RestaurantSummary) =>
    r.slug ? `/restaurant/${r.slug}` : `/restaurant/${r.id}`

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

        {/* COMMUNE SELECTOR + SEARCH */}
        <div className="space-y-3">
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

          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search restaurants…"
            className="w-full rounded-xl border border-stone-200 bg-stone-50 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400 placeholder:text-stone-400"
          />
        </div>

        {/* CUISINE PILLS */}
        {cuisines.length > 0 && (
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => setSelectedCuisine(null)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                selectedCuisine === null
                  ? 'bg-stone-900 text-white border-stone-900'
                  : 'bg-white text-stone-600 border-stone-200 hover:border-stone-400'
              }`}
            >
              All
            </button>
            {cuisines.map((c) => (
              <button
                key={c}
                onClick={() => setSelectedCuisine(selectedCuisine === c ? null : c)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors capitalize ${
                  selectedCuisine === c
                    ? 'bg-stone-900 text-white border-stone-900'
                    : 'bg-white text-stone-600 border-stone-200 hover:border-stone-400'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        )}

        {/* DECIDE FOR ME */}
        {!isThin && (
          <div className="rounded-2xl bg-blue-50 border border-blue-100 p-4 space-y-3">
            {decideExhausted ? (
              <div className="space-y-2">
                <p className="font-semibold text-stone-800">{t('decide_exhausted')}</p>
                <button
                  onClick={resetDecide}
                  className="text-sm text-blue-600 hover:underline"
                >
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
                    className="shrink-0 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
                  >
                    Order →
                  </Link>
                </div>
                <button
                  onClick={handleReroll}
                  className="text-sm text-blue-600 hover:underline"
                >
                  {t('decide_not_feeling')}
                </button>
              </div>
            ) : (
              <button
                onClick={handleDecide}
                className="w-full bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white font-bold py-3 px-6 rounded-xl transition-colors text-base"
              >
                {t('decide_btn')}
              </button>
            )}
          </div>
        )}

        {/* BEST VALUE SHELF */}
        {!isThin && bestValueShelf.length > 0 && (
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

        {/* FOOTER LINK TO FULL LIST */}
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
