import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getTranslations } from 'next-intl/server'
import { getRestaurantWithListings } from '@/lib/queries'
import { PLATFORM_LABELS, PLATFORM_COLORS } from '@/lib/basket'
import BasketSimulator from '@/components/BasketSimulator'
import ClaimForm from '@/components/ClaimForm'

function freshnessLabel(isoStr: string): { key: string; values?: Record<string, number> } {
  const ageMs = Date.now() - new Date(isoStr).getTime()
  const ageH = ageMs / 3_600_000
  if (ageH < 1) return { key: 'just_now' }
  if (ageH < 24) return { key: 'hours', values: { hours: Math.floor(ageH) } }
  const ageD = Math.floor(ageMs / 86_400_000)
  return { key: 'days', values: { days: ageD } }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>
}): Promise<Metadata> {
  const { id } = await params
  const data = await getRestaurantWithListings(id)
  return {
    title: data?.name ?? "Restaurant",
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
  const tDetail = await getTranslations('detail')

  if (!data) notFound()

  const bestRating = data.listings
    .map((l) => l.rating)
    .filter((r): r is number => r !== null)
    .sort((a, b) => b - a)[0] ?? null

  // Freshness: most recent last_scraped_at across all listings
  const mostRecentScrape = data.listings
    .map((l) => l.last_scraped_at)
    .filter((s): s is string => s !== null)
    .sort()
    .pop() ?? null
  const freshness = mostRecentScrape ? freshnessLabel(mostRecentScrape) : null

  // Fee overview: aggregator platforms only, those with fee data
  const feeListings = data.listings.filter(
    (l) => l.platform !== 'direct' && l.delivery_fee_cents !== null
  )

  return (
    <div className="max-w-md mx-auto">
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <Link href="/" className="text-stone-500 hover:text-stone-800 text-lg mr-auto">‹</Link>
        <span className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </span>
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
          {freshness && (
            <span className="text-[10px] font-medium text-stone-400 bg-stone-100 rounded-full px-2 py-0.5">
              {tDetail(freshness.key, freshness.values)}
            </span>
          )}
        </div>
        {data.order_url && (
          <a
            href={data.order_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-orange-500 hover:bg-orange-600 text-white font-semibold text-sm transition-colors"
          >
            {tDirect('badge_long')}
          </a>
        )}
      </div>

      {/* Platform fee overview */}
      {feeListings.length > 0 && (
        <div className="px-5 mb-2">
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-2">
            {tDetail('platform_fees')}
          </p>
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
                </a>
              )
            })}
          </div>
        </div>
      )}

      <BasketSimulator menuItems={data.menuItems} listings={data.listings} phone={data.phone} />
      <div className="px-5 pb-8">
        <ClaimForm restaurantId={data.id} restaurantName={data.name} />
      </div>
    </div>
  )
}
