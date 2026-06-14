import type { Metadata } from 'next'
import Image from 'next/image'
import { notFound, permanentRedirect } from 'next/navigation'
import { Suspense } from 'react'

export const revalidate = 3600

import Link from 'next/link'
import { getTranslations } from 'next-intl/server'
import { ExternalLink, List, Globe, Phone, Utensils, ArrowRight } from 'lucide-react'
import { getRestaurantWithListings, type PromoItem } from '@/lib/queries'
import { restaurantCanonical } from '@/lib/canonical'
import { PLATFORM_LABELS, centsToEuro } from '@/lib/basket'
import { computeFeeRows, computeDirectSavingsCents } from '@/lib/where-to-order'
import BasketSimulator from '@/components/BasketSimulator'
import MenuPriceBars from '@/components/MenuPriceBars'
import OpenStatusBadge from '@/components/OpenStatusBadge'
import PlatformLogo from '@/components/ui/PlatformLogo'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

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
  params: Promise<{ slug: string[] }>
}): Promise<Metadata> {
  const { slug: slugParts } = await params
  const slug = slugParts.join('/')
  const data = await getRestaurantWithListings(slug)
  if (!data) return { title: 'Restaurant — Forkeur' }

  const t = await getTranslations('detail')
  const cuisine = (data.cuisine ?? []).join(', ')
  const description = t('meta_description', { name: data.name, cuisine: cuisine || 'Brussels' })
  const title = `${data.name} — Forkeur`

  const recentCutoff = Date.now() - 72 * 60 * 60 * 1000
  const recentDeliveryListings = data.listings.filter(
    (l) => l.platform !== 'direct' && l.last_scraped_at && new Date(l.last_scraped_at).getTime() > recentCutoff
  )
  const hasComparison = recentDeliveryListings.length >= 2 && data.menuItems.length > 0

  const canonical = restaurantCanonical(data.id, data.slug)

  return {
    title,
    description,
    alternates: { canonical },
    robots: { index: hasComparison, follow: true },
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
  params: Promise<{ slug: string[] }>
}) {
  const { slug: slugParts } = await params
  const slug = slugParts.join('/')
  const [data, tDirect, tCard, tDetail, tBadge, tOwners, tCompare, tDeals] = await Promise.all([
    getRestaurantWithListings(slug),
    getTranslations('direct'),
    getTranslations('card'),
    getTranslations('detail'),
    getTranslations('badge'),
    getTranslations('owners'),
    getTranslations('compare'),
    getTranslations('deals'),
  ])
  if (!data) notFound()

  // UUID in the URL → 301 to the canonical slug URL
  if (data.slug && UUID_RE.test(slug)) permanentRedirect(`/restaurant/${data.slug}`)

  const { matchRate } = data
  const tier = matchRate >= 0.7 ? 1 : matchRate >= 0.3 ? 2 : 3

  const bestRating = data.listings
    .map((l) => l.rating)
    .filter((r): r is number => r !== null)
    .sort((a, b) => b - a)[0] ?? null

  const newestScrapedAt = data.listings
    .map((l) => l.last_scraped_at)
    .filter((s): s is string => s !== null)
    .sort()
    .at(-1) ?? null

  function formatAgo(iso: string): string {
    const diffMs = Date.now() - new Date(iso).getTime()
    const diffMin = Math.round(diffMs / 60000)
    if (diffMin < 60) return `${diffMin}m ago`
    const diffH = Math.round(diffMin / 60)
    if (diffH < 24) return `${diffH}h ago`
    const diffD = Math.round(diffH / 24)
    return `${diffD}d ago`
  }

  // Fee overview rows (cheapest first, with deltas)
  const feeRows = computeFeeRows(data.listings)

  // "Where to order" direct-savings + the direct listing for the fee sub-line
  const directSavings = computeDirectSavingsCents(data.listings)
  const directListing = data.listings.find((l) => l.platform === 'direct') ?? null

  const allStale = data.listings.length === 0

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Restaurant',
    '@id': restaurantCanonical(data.id, data.slug),
    name: data.name,
    url: restaurantCanonical(data.id, data.slug),
    ...(data.image_url ? { image: data.image_url } : {}),
    ...((data.cuisine ?? []).length > 0 ? { servesCuisine: data.cuisine } : {}),
    address: {
      '@type': 'PostalAddress',
      addressLocality: 'Brussels',
      addressCountry: 'BE',
    },
    ...(data.phone && (data.phone_confidence === 'high' || data.phone_confidence === 'medium')
      ? { telephone: data.phone }
      : {}),
  }

  return (
    <div className="w-full max-w-md mx-auto">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <Link href="/" className="text-stone-500 hover:text-stone-800 text-lg mr-auto min-w-[44px] min-h-[44px] flex items-center">‹</Link>
        <Link href="/" className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </Link>
      </div>

      {/* Hero image */}
      {data.image_url && (
        <div className="relative w-full h-44">
          <Image
            src={data.image_url}
            alt={data.name}
            fill
            className="object-cover"
            priority
          />
        </div>
      )}

      {/* Restaurant info */}
      <div className="px-5 pb-4 pt-3">
        <h1 className="text-2xl font-bold text-stone-900">{data.name}</h1>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <p className="text-sm text-stone-400">
            {(data.cuisine ?? []).join(' · ')} · {data.city}
            {bestRating !== null && ` · ★ ${bestRating.toFixed(1)}`}
          </p>
          <details className="inline-flex items-center gap-1 relative">
            <summary className="list-none flex items-center gap-1 cursor-pointer">
              <span className="text-[10px] font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
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
        {newestScrapedAt && (
          <p className="text-[11px] text-stone-400 mt-0.5">
            {tDetail('last_updated', { ago: formatAgo(newestScrapedAt) })}
          </p>
        )}
        {data.order_url && /^https?:\/\//i.test(data.order_url) && (() => {
          const isActionable = !data.direct_url_type || data.direct_url_type === 'ordering' || data.direct_url_type === 'menu'
          // Actionable direct ordering is surfaced by the "Where to order" card below;
          // only show this header CTA for non-actionable links (website / phone).
          if (isActionable) return null
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
            <>
              <a
                href={data.order_url}
                target="_blank"
                rel="noopener noreferrer"
                className={`mt-3 flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-sm transition-colors text-white ${isActionable ? 'bg-[#D85A30] hover:bg-[#c04e28]' : 'bg-[#888780] hover:bg-[#7a7a73]'}`}
              >
                <DirectIcon size={16} aria-hidden="true" />
                {label}
              </a>
              {/* Phone shown via a tel: link is only as trustworthy as our source — flag low-confidence numbers */}
              {data.direct_url_type === 'phone' && data.phone_confidence === 'low' && (
                <p className="mt-1.5 text-[11px] text-stone-500 text-center">
                  {tDetail('phone_unverified')}
                </p>
              )}
            </>
          )
        })()}
        {/* The venue only takes orders via a platform already compared above — no extra "order direct" upside */}
        {data.order_channel === 'covered_platform' && (
          <p className="mt-3 text-[11px] text-stone-500">
            {tDetail('order_covered_platform')}
          </p>
        )}
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
          {/* Where to order — the short answer */}
          {data.order_url && /^https?:\/\//i.test(data.order_url) &&
            (!data.direct_url_type || data.direct_url_type === 'ordering' || data.direct_url_type === 'menu') && (
              <div className="rounded-2xl bg-green-50 border border-green-200 p-4 mx-5 mb-4">
                <p className="uppercase tracking-widest text-[10px] font-semibold text-green-700">
                  {tDetail('where_to_order_eyebrow')}
                </p>
                <div className="flex items-start gap-3 mt-2">
                  <div className="w-10 h-10 rounded-xl bg-[#D85A30] flex items-center justify-center text-white shrink-0">
                    <Utensils size={18} aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-bold text-stone-900">{tDetail('order_direct_title')}</p>
                    <p className="text-xs text-stone-500 mt-0.5">
                      {tDetail('order_direct_sub', {
                        fee: centsToEuro(directListing?.delivery_fee_cents ?? 0),
                      })}
                    </p>
                  </div>
                  {directSavings !== null && (
                    <p className="text-sm font-bold text-green-700 text-right shrink-0">
                      {tDetail('save_vs_apps', { amount: centsToEuro(directSavings) })}
                    </p>
                  )}
                </div>
                <a
                  href={data.order_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 flex items-center justify-center gap-2 w-full py-3 rounded-xl text-white font-semibold text-sm transition-colors bg-[#2E86D8] hover:bg-[#2576c2]"
                >
                  {tDetail('order_on_site', { name: data.name })}
                  <ArrowRight size={16} aria-hidden="true" />
                </a>
                <p className="text-[11px] text-stone-400 text-center mt-2">
                  {tDetail('prefer_app')}
                </p>
              </div>
            )}

          {/* Winner hero card — delivery-only restaurants */}
          {(() => {
            const hasActionableDirect = Boolean(
              data.order_url &&
              /^https?:\/\//i.test(data.order_url) &&
              (!data.direct_url_type || data.direct_url_type === 'ordering' || data.direct_url_type === 'menu')
            )
            if (hasActionableDirect) return null
            if (feeRows.length === 0) return null

            const winnerRow = feeRows.find((r) => r.isCheapest)
            if (!winnerRow) return null

            const winnerListing = data.listings.find((l) => l.platform === winnerRow.platform)
            const href =
              winnerListing?.platform_url && /^https?:\/\//i.test(winnerListing.platform_url)
                ? winnerListing.platform_url
                : null

            return (
              <div className="rounded-2xl bg-orange-50 border border-orange-200 p-4 mx-5 mb-4">
                <p className="uppercase tracking-widest text-[10px] font-semibold text-orange-600">
                  {tDetail('where_to_order_eyebrow')}
                </p>
                <div className="flex items-center gap-3 mt-2">
                  <div className="shrink-0">
                    <PlatformLogo platform={winnerRow.platform} size={40} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-bold text-stone-900">{PLATFORM_LABELS[winnerRow.platform]}</p>
                    <p className="text-xs text-stone-500 mt-0.5">{tCompare('subtitle_fees')}</p>
                  </div>
                  <p className="text-xl font-bold text-stone-900 shrink-0">{centsToEuro(winnerRow.feeCents)}</p>
                </div>
                {href && (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 flex items-center justify-center gap-2 w-full py-3 rounded-xl text-white font-semibold text-sm transition-colors bg-[#D85A30] hover:bg-[#c04e28]"
                  >
                    {tDeals('order_on', { platform: PLATFORM_LABELS[winnerRow.platform] })}
                    <ArrowRight size={16} aria-hidden="true" />
                  </a>
                )}
              </div>
            )
          })()}

          {/* Delivery fees */}
          {feeRows.length > 0 && (
            <div className="px-5 mb-2">
              <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-2">
                {tDetail('platform_fees')}
              </p>
              <div className="flex flex-col gap-2">
                {feeRows.map((row) => {
                  const listing = data.listings.find((l) => l.platform === row.platform)
                  const href =
                    listing?.platform_url && /^https?:\/\//i.test(listing.platform_url)
                      ? listing.platform_url
                      : null
                  const rowClass = `flex items-center gap-3 rounded-xl border p-3 transition-colors ${
                    row.isCheapest ? 'border-green-200 bg-green-50' : 'border-stone-100 bg-white'
                  }`
                  const inner = (
                    <>
                      <div className="shrink-0">
                        <PlatformLogo platform={row.platform} size={28} />
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold text-stone-900 text-sm flex items-center">
                          {PLATFORM_LABELS[row.platform]}
                          {row.isCheapest && (
                            <span className="text-[10px] font-bold text-green-700 bg-green-100 rounded px-1.5 py-0.5 ml-2">
                              {tCard('cheapest_badge')}
                            </span>
                          )}
                        </p>
                        <p className="text-[11px] text-stone-400">
                          {row.platform === 'direct'
                            ? tDetail('order_from_restaurant')
                            : tCard('delivery_service_fees')}
                        </p>
                        {listing && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            <OpenStatusBadge
                              openingHours={listing.opening_hours}
                              isAvailable={listing.is_available}
                            />
                            {listing.promotions.map((p, i) => (
                              <span
                                key={i}
                                className="text-[10px] font-semibold text-green-700 bg-green-50 border border-green-200 rounded-full px-1.5 py-0.5 leading-tight"
                              >
                                {promoBadgeText(tBadge, p)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="ml-auto text-right shrink-0">
                        <p className="font-bold text-stone-900">{centsToEuro(row.feeCents)}</p>
                        {row.deltaCents > 0 && (
                          <p className="text-[11px] text-stone-400">+{centsToEuro(row.deltaCents)}</p>
                        )}
                      </div>
                    </>
                  )
                  return href ? (
                    <a
                      key={row.platform}
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={rowClass}
                    >
                      {inner}
                    </a>
                  ) : (
                    <div key={row.platform} className={rowClass}>
                      {inner}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Menu prices */}
          {tier === 3 ? (
            data.menuItems.length > 0 && (
              <div className="px-5 mb-2 mt-4">
                <p className="text-xs" style={{ color: '#888780' }}>
                  {tDetail('no_match_neutral')}
                </p>
              </div>
            )
          ) : (
            <>
              <p className="px-5 mt-4 text-[10px] font-semibold tracking-widest text-stone-400 uppercase">
                {tDetail('menu_prices_eyebrow')}
              </p>
              <MenuPriceBars items={data.menuItems} />
            </>
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
                    {tDetail('build_order_eyebrow')}
                  </p>
                  <p className="text-xs text-stone-400">{tDetail('build_order_sub')}</p>
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
                  <Suspense fallback={null}>
                    <BasketSimulator menuItems={data.menuItems} listings={data.listings} phone={data.phone} phoneConfidence={data.phone_confidence} orderChannel={data.order_channel} matchRate={matchRate} restaurantId={data.id} />
                  </Suspense>
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
