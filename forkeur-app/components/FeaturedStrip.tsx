'use client'

import { useTranslations } from 'next-intl'
import type { DealItem } from '../lib/deals'
import { qualityScore } from '../lib/deals'

export function selectFeatured(deals: DealItem[]): DealItem[] {
  const selected: DealItem[] = []
  const usedRestaurants = new Set<string>()

  const pick = (candidates: DealItem[]) => {
    for (const d of candidates) {
      if (!usedRestaurants.has(d.restaurant_id)) {
        selected.push(d)
        usedRestaurants.add(d.restaurant_id)
        return
      }
    }
  }

  // Slot 1: best pct_discount
  const pct = deals
    .filter(d => d.promo_type === 'pct_discount')
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  pick(pct)

  // Slot 2: best free_delivery
  const free = deals
    .filter(d => d.promo_type === 'free_delivery')
    .sort((a, b) => qualityScore(b) - qualityScore(a))
  pick(free)

  // Slot 3: best bogo or free_item
  const extra = deals
    .filter(d => d.promo_type === 'bogo' || d.promo_type === 'free_item')
    .sort((a, b) => qualityScore(b) - qualityScore(a))
  pick(extra)

  return selected.length >= 2 ? selected : []
}

const PLATFORM_DOT: Record<string, string> = {
  uber_eats: 'bg-orange-500',
  deliveroo: 'bg-teal-500',
  takeaway: 'bg-stone-700',
}

const BADGE_COLOR: Record<string, string> = {
  pct_discount: 'bg-orange-500 text-white',
  abs_discount: 'bg-orange-500 text-white',
  free_delivery: 'bg-stone-700 text-white',
  bogo: 'bg-amber-600 text-white',
  free_item: 'bg-stone-600 text-white',
}

function FeaturedCard({ deal }: { deal: DealItem }) {
  const t = useTranslations()
  const badgeColor = BADGE_COLOR[deal.promo_type] ?? 'bg-stone-500 text-white'
  const dotColor = PLATFORM_DOT[deal.platform] ?? 'bg-stone-400'

  return (
    <div className="flex-shrink-0 w-64 sm:w-72 rounded-xl border border-stone-200 bg-white shadow-sm overflow-hidden snap-start">
      {/* Promo badge — top 40% of card */}
      <div className={`${badgeColor} px-4 py-5 flex items-center justify-center min-h-[90px]`}>
        <span className="text-2xl font-bold text-center leading-tight">{deal.label}</span>
      </div>

      <div className="px-4 py-3 space-y-2">
        {/* Platform + rating row */}
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
          <span>{t(`platform.${deal.platform}`)}</span>
          {deal.rating && (
            <>
              <span>·</span>
              <span>★ {deal.rating.toFixed(1)}</span>
              {deal.review_count && <span>({deal.review_count})</span>}
            </>
          )}
        </div>

        {/* Restaurant name */}
        <p className="font-semibold text-stone-900 text-sm leading-snug">{deal.restaurant_name}</p>

        {/* Area / cuisine */}
        {(deal.cuisine.length > 0 || deal.area) && (
          <p className="text-xs text-stone-400">
            {[deal.cuisine.slice(0, 2).join(' · '), deal.area].filter(Boolean).join(' · ')}
          </p>
        )}

        {/* Min order */}
        {deal.min_order && deal.min_order > 0 && (
          <p className="text-xs text-stone-400">{t('deals.min_order', { amount: deal.min_order })}</p>
        )}

        {/* CTA */}
        {deal.platform_url && (
          <a
            href={deal.platform_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block mt-1 text-center text-sm font-medium text-orange-600 hover:text-orange-700 border border-orange-200 rounded-lg py-2"
          >
            {t('deals.order_on', { platform: t(`platform.${deal.platform}`) })}
          </a>
        )}
      </div>
    </div>
  )
}

export default function FeaturedStrip({ deals }: { deals: DealItem[] }) {
  const t = useTranslations()
  const featured = selectFeatured(deals)
  if (featured.length < 2) return null

  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-stone-500 uppercase tracking-wide mb-3">
        {t('deals.featured_heading')}
      </h2>
      <div className="flex gap-4 overflow-x-auto snap-x snap-mandatory pb-2 -mx-4 px-4 sm:mx-0 sm:px-0">
        {featured.map(deal => (
          <FeaturedCard key={deal.id} deal={deal} />
        ))}
      </div>
    </section>
  )
}
