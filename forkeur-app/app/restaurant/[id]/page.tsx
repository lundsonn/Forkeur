import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getTranslations } from 'next-intl/server'
import { ExternalLink, List, Globe, Phone } from 'lucide-react'
import { getRestaurantWithListings, type PromoItem } from '@/lib/queries'
import { PLATFORM_LABELS, PLATFORM_COLORS } from '@/lib/basket'
import BasketSimulator from '@/components/BasketSimulator'
import MenuPriceComparison from '@/components/MenuPriceComparison'
import StaleRefresh from '@/components/StaleRefresh'
import OpenStatusBadge from '@/components/OpenStatusBadge'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function promoBadgeText(tBadge: any, promo: PromoItem): string {
  switch (promo.promo_type) {
    case 'bogo': return tBadge('bogo')
    case 'pct_discount': return promo.value != null ? tBadge('pct_off', { value: Math.round(promo.value) }) : tBadge('pct_off', { value: '' })
    case 'abs_discount': return promo.value != null ? tBadge('eur_off', { value: promo.value.toFixed(2) }) : tBadge('eur_off', { value: '' })
    case 'free_delivery': return tBadge('free_delivery')
    case 'free_item': return tBadge('free_item')
    default: return promo.label
  }
}


export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>
}): Promise<Metadata> {
  const { id } = await params
  const data = await getRestaurantWithListings(id)
  if (!data) return { title: 'Restaurant — Forkeur' }

  const t = await getTranslations('detail')
  const cuisine = data.cuisine.join(', ')
  const description = t('meta_description', { name: data.name, cuisine: cuisine || 'Brussels' })
  const title = `${data.name} — Forkeur`

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      ...(data.image_url ? { images: [{ url: data.image_url }] } : {}),
    },
    twitter: {
      card: data.image_url ? 'summary_large_image' : 'summary',
      title,
      description,
      ...(data.image_url ? { images: [data.image_url] } : {}),
    },
  }
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const data = await getRestaurantWithListings(id)
  const tDirect = await getTranslations('direct')
  const tCard = await getTranslations('card')
  const tDetail = await getTranslations('detail')
  const tBadge = await getTranslations('badge')
  const tOwners = await getTranslations('owners')
  if (!data) notFound()

  const { matchRate } = data
  const tier = matchRate >= 0.7 ? 1 : matchRate >= 0.3 ? 2 : 3

  const bestRating = data.listings
    .map((l) => l.rating)
    .filter((r): r is number => r !== null)
    .sort((a, b) => b - a)[0] ?? null

  // Most recent last_scraped_at across all listings (used by StaleRefresh)
  const mostRecentScrape = data.listings
    .map((l) => l.last_scraped_at)
    .filter((s): s is string => s !== null)
    .sort()
    .pop() ?? null

  // Fee overview: aggregator platforms only, those with fee data
  const feeListings = data.listings.filter(
    (l) => l.platform !== 'direct' && l.delivery_fee_cents !== null
  )
  const sortedFeeListings = [...feeListings].sort(
    (a, b) => (a.delivery_fee_cents ?? 0) - (b.delivery_fee_cents ?? 0)
  )
  const cheapestFee = sortedFeeListings[0] ?? null
  const mostExpensiveFee = sortedFeeListings[sortedFeeListings.length - 1] ?? null
  const feeGapCents =
    feeListings.length >= 2 && cheapestFee && mostExpensiveFee && cheapestFee !== mostExpensiveFee
      ? (mostExpensiveFee.delivery_fee_cents ?? 0) - (cheapestFee.delivery_fee_cents ?? 0)
      : 0

  const allStale = data.listings.length === 0

  return (
    <div className="max-w-md mx-auto">
      <StaleRefresh lastScrapedAt={mostRecentScrape} />
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <Link href="/" className="text-stone-500 hover:text-stone-800 text-lg mr-auto">‹</Link>
        <Link href="/" className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </Link>
      </div>

      {/* Hero image */}
      {data.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={data.image_url}
          alt={data.name}
          className="w-full h-44 object-cover"
        />
      )}

      {/* Restaurant info */}
      <div className="px-5 pb-4 pt-3">
        <h1 className="text-2xl font-bold text-stone-900">{data.name}</h1>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <p className="text-sm text-stone-400">
            {data.cuisine.join(' · ')} · {data.city}
            {bestRating !== null && ` · ★ ${bestRating.toFixed(1)}`}
          </p>
          <details className="inline-flex items-center gap-1 relative">
            <summary className="list-none flex items-center gap-1 cursor-pointer">
              <span className="text-[10px] font-medium text-stone-400 bg-stone-100 rounded-full px-2 py-0.5">
                {tDetail('fees_included')}
              </span>
              <span className="w-4 h-4 rounded-full bg-stone-200 text-stone-500 text-[9px] font-bold flex items-center justify-center leading-none select-none">
                i
              </span>
            </summary>
            <span className="absolute top-6 left-0 text-[11px] bg-stone-800 text-white rounded-lg px-3 py-2 shadow-lg z-10 max-w-[min(200px,calc(100vw-2rem))] leading-snug pointer-events-none">
              {tDetail('fees_info')}
            </span>
          </details>
        </div>
        {data.order_url && (() => {
          const isActionable = !data.direct_url_type || data.direct_url_type === 'ordering' || data.direct_url_type === 'menu'
          const DirectIcon =
            data.direct_url_type === 'menu' ? List
            : data.direct_url_type === 'website' ? Globe
            : data.direct_url_type === 'phone' ? Phone
            : ExternalLink
          const label =
            data.direct_url_type === 'menu' ? tCard('direct_cta_menu')
            : data.direct_url_type === 'website' ? tCard('direct_cta_website')
            : data.direct_url_type === 'phone' ? tCard('direct_cta_phone')
            : tDirect('badge_long')
          return (
            <a
              href={data.order_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`mt-3 flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-sm transition-colors text-white ${isActionable ? 'bg-[#D85A30] hover:bg-[#c04e28]' : 'bg-[#888780] hover:bg-[#7a7a73]'}`}
            >
              <DirectIcon size={16} aria-hidden="true" />
              {label}
            </a>
          )
        })()}
      </div>

      {allStale ? (
        <div className="px-5 mb-4">
          <div className="rounded-xl border border-stone-100 bg-stone-50 px-5 py-8 text-center">
            <p className="text-sm font-medium text-stone-600">{tDetail('prices_updating')}</p>
            <p className="text-xs text-stone-400 mt-1">{tDetail('prices_updating_sub')}</p>
          </div>
        </div>
      ) : (
        <>
          {/* Platform fee overview */}
          {feeListings.length > 0 && (
            <div className="px-5 mb-2">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase">
                  {tDetail('platform_fees')}
                </p>
                {feeGapCents > 0 && cheapestFee && mostExpensiveFee && (
                  <span className="text-[11px] font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
                    {tDetail('cheapest_signal', {
                      platform: PLATFORM_LABELS[cheapestFee.platform],
                      amount: (feeGapCents / 100).toFixed(2),
                      other: PLATFORM_LABELS[mostExpensiveFee.platform],
                    })}
                  </span>
                )}
              </div>
              <div className={`grid gap-2 ${feeListings.length === 2 ? 'grid-cols-2' : 'grid-cols-3'}`}>
                {feeListings.map((l) => {
                  const colors = PLATFORM_COLORS[l.platform]
                  const isCheapest = feeListings.every(
                    (o) => o.platform === l.platform || (o.delivery_fee_cents ?? Infinity) >= (l.delivery_fee_cents ?? 0)
                  )
                  return (
                    <a
                      key={l.platform}
                      href={l.platform_url ?? undefined}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`rounded-xl border p-3 text-center transition-colors ${
                        isCheapest
                          ? 'border-stone-300 bg-white'
                          : 'border-stone-100 bg-stone-50 opacity-60'
                      }`}
                    >
                      <p className={`text-[10px] font-semibold uppercase tracking-wide ${colors.label}`}>
                        {PLATFORM_LABELS[l.platform]}
                      </p>
                      <p className="text-xl font-bold text-stone-900 mt-1">
                        {l.delivery_fee_label}
                      </p>
                      {l.eta_label && (
                        <p className="text-[11px] text-stone-400 mt-0.5">{l.eta_label}</p>
                      )}
                      {l.min_order_label && (
                        <p className="text-[11px] text-stone-400">{l.min_order_label}</p>
                      )}
                      <div className="flex flex-wrap justify-center gap-1 mt-1.5">
                        <OpenStatusBadge openingHours={l.opening_hours} isAvailable={l.is_available} />
                        {l.promotions.map((p, i) => (
                          <span key={i} className="text-[10px] font-semibold text-green-700 bg-green-50 border border-green-200 rounded-full px-1.5 py-0.5 leading-tight">
                            {promoBadgeText(tBadge, p)}
                          </span>
                        ))}
                      </div>
                    </a>
                  )
                })}
              </div>
            </div>
          )}

          {/* Menu price comparison */}
          {tier === 3 ? (
            data.menuItems.length > 0 && (
              <div className="px-5 mb-2 mt-4">
                <p className="text-xs" style={{ color: '#888780' }}>
                  {tDetail('no_match_neutral')}
                </p>
              </div>
            )
          ) : (
            <MenuPriceComparison items={data.menuItems} matchRate={matchRate} />
          )}

          {/* Basket simulator section */}
          {(() => {
            if (data.menuItems.length === 0) return null

            const platformsWithMenu = new Set<string>()
            for (const item of data.menuItems) {
              for (const [platform, price] of Object.entries(item.prices)) {
                if (price !== null && platform !== 'direct') platformsWithMenu.add(platform)
              }
            }

            return (
              <div className="mt-4">
                <div className="px-5 mb-3">
                  <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-0.5">
                    {tDetail('basket_section_title')}
                  </p>
                  <p className="text-xs text-stone-400">{tDetail('basket_section_subtitle')}</p>
                </div>

                {platformsWithMenu.size < 2 ? (
                  <div className="px-5 py-4 text-center">
                    <p className="text-sm text-stone-400">
                      {tDetail('basket_single_platform', {
                        platform: PLATFORM_LABELS[[...platformsWithMenu][0] as keyof typeof PLATFORM_LABELS] ?? [...platformsWithMenu][0],
                      })}
                    </p>
                  </div>
                ) : (
                  <BasketSimulator menuItems={data.menuItems} listings={data.listings} phone={data.phone} matchRate={matchRate} />
                )}
              </div>
            )
          })()}
        </>
      )}
      <div className="px-5 pb-8">
        <Link
          href={`/owners?name=${encodeURIComponent(data.name)}`}
          className="text-xs text-stone-400 hover:text-stone-600 underline underline-offset-2 transition-colors"
        >
          {tOwners('detail_link')}
        </Link>
      </div>
    </div>
  )
}
