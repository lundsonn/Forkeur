import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getTranslations } from 'next-intl/server'
import { getRestaurantWithListings } from '@/lib/queries'
import { computeFeeRows } from '@/lib/where-to-order'
import { centsToEuro } from '@/lib/basket'
import type { Platform } from '@/lib/basket'
import { pageCanonical } from '@/lib/canonical'

export const revalidate = 3600

// Industry-estimate commission rates — never per-restaurant claims
const COMMISSION_RATES: Partial<Record<Platform, number>> = {
  uber_eats: 0.30,
  deliveroo: 0.30,
  takeaway: 0.27,
}
const PAYMENT_PROC_RATE = 0.03
const TYPICAL_ORDER_CENTS = 2000

const PLATFORM_DISPLAY: Record<string, string> = {
  uber_eats: 'Uber Eats',
  deliveroo: 'Deliveroo',
  takeaway: 'Takeaway',
  direct: 'Direct',
}

type PageProps = { params: Promise<{ slug: string }> }

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params
  const data = await getRestaurantWithListings(slug)
  if (!data) return {}
  return {
    title: `${data.name} — For restaurant owners | Forkeur`,
    description: `See how ordering direct from ${data.name} compares to platform commissions.`,
    alternates: { canonical: pageCanonical(`/owners/${data.slug ?? slug}`) },
    robots: { index: false, follow: false },
  }
}

export default async function OwnerProofPage({ params }: PageProps) {
  const { slug } = await params
  const data = await getRestaurantWithListings(slug)
  if (!data) notFound()

  const t = await getTranslations('owners_proof')

  // Coverage gate — same logic as consumer detail page
  const recentCutoff = Date.now() - 7 * 24 * 60 * 60 * 1000
  const recentDeliveryListings = data.listings.filter(
    l => l.platform !== 'direct' && l.last_scraped_at && new Date(l.last_scraped_at).getTime() > recentCutoff
  )
  const hasComparison = recentDeliveryListings.length >= 2 && data.menuItems.length > 0

  // Cheapest check — reuse computeFeeRows, do NOT reimplement
  const feeRows = computeFeeRows(data.listings)
  const directIsCheapest = hasComparison && feeRows.length > 0 && feeRows[0].platform === 'direct'

  // Which agg platforms are present for this restaurant?
  const aggPlatforms = [
    ...new Set(
      data.listings
        .filter(l => l.platform !== 'direct' && COMMISSION_RATES[l.platform as Platform] !== undefined)
        .map(l => l.platform as Platform)
    ),
  ]

  // Hero: pick Uber Eats if present (highest commission in the mockup), else first
  const heroPlatform = aggPlatforms.find(p => p === 'uber_eats') ?? aggPlatforms[0]
  const heroRate = heroPlatform ? (COMMISSION_RATES[heroPlatform] ?? 0.30) : 0.30
  const heroCommissionCents = Math.round(TYPICAL_ORDER_CENTS * heroRate)

  // What-you-keep rows (industry estimates, labeled ≈)
  const directKeepCents = Math.round(TYPICAL_ORDER_CENTS * (1 - PAYMENT_PROC_RATE))
  const keepRows = [
    {
      platform: 'direct' as Platform,
      keepCents: directKeepCents,
      commissionCents: TYPICAL_ORDER_CENTS - directKeepCents,
      isDirect: true,
    },
    ...aggPlatforms.map(p => {
      const rate = COMMISSION_RATES[p] ?? 0.30
      const keepCents = Math.round(TYPICAL_ORDER_CENTS * (1 - rate))
      return { platform: p, keepCents, commissionCents: TYPICAL_ORDER_CENTS - keepCents, isDirect: false }
    }),
  ]

  const subtitle = [data.cuisine?.[0], data.city].filter(Boolean).join(' · ')
  const heroPlatformLabel = heroPlatform ? PLATFORM_DISPLAY[heroPlatform] : t('platforms_generic')

  return (
    <div className="w-full max-w-md mx-auto px-5 pb-16">
      {/* Nav */}
      <div className="flex items-center pt-5 pb-4">
        <Link
          href="/owners"
          className="text-stone-500 hover:text-stone-800 text-lg mr-auto min-w-[44px] min-h-[44px] flex items-center"
        >
          ‹
        </Link>
        <Link href="/" className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </Link>
        <Link href="/owners" className="text-xs text-stone-500 hover:text-stone-800 ml-auto whitespace-nowrap">
          {t('for_owners_link')}
        </Link>
      </div>

      {/* Eyebrow + heading */}
      <p className="text-[10px] font-semibold tracking-widest text-orange-500 uppercase mt-4 mb-1">
        {t('eyebrow')}
      </p>
      <h1 className="text-2xl font-bold text-stone-900 leading-tight">{data.name}</h1>
      {subtitle && <p className="text-sm text-stone-400 mt-0.5 mb-6">{subtitle}</p>}

      {/* Hero green card */}
      <div className="rounded-2xl bg-emerald-50 border border-emerald-200 p-5 mb-4">
        <p className="text-sm font-medium text-emerald-900 leading-relaxed">
          {t('hero_commission', {
            amount: centsToEuro(heroCommissionCents),
            platform: heroPlatformLabel,
            order: centsToEuro(TYPICAL_ORDER_CENTS),
            pct: Math.round(heroRate * 100),
          })}
        </p>

        {/* Cheapest rank — only when real and gated on hasComparison + actual cheapest */}
        {directIsCheapest && (
          <div className="mt-3 flex items-start gap-2">
            <span className="text-emerald-600 mt-0.5 shrink-0">✓</span>
            <p className="text-sm text-emerald-800">
              {t('rank_claim', { name: data.name })}
            </p>
          </div>
        )}
      </div>

      {/* What you keep table */}
      {keepRows.length > 1 && (
        <div className="mb-1">
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
            {t('section_keep', { order: centsToEuro(TYPICAL_ORDER_CENTS) })}
          </p>
          <div className="rounded-2xl border border-stone-200 overflow-hidden">
            {keepRows.map((row, i) => (
              <div
                key={row.platform}
                className={`flex items-center justify-between px-4 py-3 ${i < keepRows.length - 1 ? 'border-b border-stone-100' : ''} ${row.isDirect ? 'bg-stone-50' : ''}`}
              >
                <div>
                  <p className={`text-sm font-medium ${row.isDirect ? 'text-stone-900' : 'text-stone-700'}`}>
                    {PLATFORM_DISPLAY[row.platform]}
                  </p>
                  {row.isDirect ? (
                    <p className="text-[11px] text-stone-400 mt-0.5">{t('direct_approx')}</p>
                  ) : (
                    <p className="text-[11px] text-red-400 mt-0.5">
                      {t('commission_taken', { amount: centsToEuro(row.commissionCents) })}
                    </p>
                  )}
                </div>
                <div className="text-right">
                  <p className={`text-base font-bold tabular-nums ${row.isDirect ? 'text-emerald-700' : 'text-stone-500'}`}>
                    ≈{centsToEuro(row.keepCents)}
                  </p>
                  {row.isDirect && (
                    <span className="text-[10px] font-semibold tracking-wide text-emerald-600 uppercase">
                      {t('keep_label')}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-stone-400 mt-2 leading-relaxed px-1">
            {t('estimate_note')}
          </p>
        </div>
      )}

      {/* Neutrality firewall */}
      <div className="rounded-xl bg-stone-100 px-4 py-3 my-6">
        <p className="text-xs text-stone-500 leading-relaxed">
          <span className="font-semibold text-stone-700">{t('firewall_bold')}</span>{' '}
          {t('firewall_body')}
        </p>
      </div>

      {/* Claim CTA — Chunk 2 handoff: replace Link with real verification flow */}
      <div className="rounded-2xl border-2 border-orange-200 bg-orange-50 p-5">
        <h2 className="text-base font-bold text-stone-900 mb-1">
          {t('claim_heading', { name: data.name })}
        </h2>
        <p className="text-sm text-stone-500 mb-4 leading-relaxed">
          {t('claim_body')}
        </p>
        <Link
          href={`/owners?name=${encodeURIComponent(data.name)}`}
          className="block w-full text-center rounded-xl bg-orange-500 hover:bg-orange-600 active:bg-orange-700 text-white font-semibold text-sm py-3 transition-colors"
        >
          {t('claim_cta', { name: data.name })}
        </Link>
      </div>
    </div>
  )
}
