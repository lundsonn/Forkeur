import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getTranslations, getLocale } from 'next-intl/server'
import { getRestaurants } from '@/lib/queries'
import { platformSavingsSelector } from '@/lib/savings'
import { MIN_COMPARISON_RESTAURANTS, COMMUNE_SLUGS, communeDisplayName } from '@/lib/communes'
import { pageCanonical, restaurantCanonical } from '@/lib/canonical'
import RestaurantCard from '@/components/RestaurantCard'

export const revalidate = 3600

export async function generateStaticParams() {
  return COMMUNE_SLUGS.map((commune) => ({ commune }))
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ commune: string }>
}): Promise<Metadata> {
  const { commune } = await params
  const [t, locale] = await Promise.all([
    getTranslations('commune_page'),
    getLocale(),
  ])
  const display = communeDisplayName(commune, locale as 'fr' | 'nl' | 'en')
  const title = t('title', { commune: display })
  const description = t('description', { commune: display })
  const url = pageCanonical(`/commune/${commune}`)
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { title, description },
    twitter: { card: 'summary', title, description },
  }
}

export default async function CommunePage({
  params,
}: {
  params: Promise<{ commune: string }>
}) {
  const { commune } = await params
  const [{ restaurants }, t, tCard, tDirect, locale] = await Promise.all([
    getRestaurants(),
    getTranslations('commune_page'),
    getTranslations('card'),
    getTranslations('direct'),
    getLocale(),
  ])

  const filtered = restaurants
    .filter((r) => r.commune === commune && r.has_comparison)
    .sort(
      (a, b) =>
        (platformSavingsSelector(b.listings)?.savingCents ?? 0) -
        (platformSavingsSelector(a.listings)?.savingCents ?? 0),
    )

  if (filtered.length < MIN_COMPARISON_RESTAURANTS) notFound()

  const display = communeDisplayName(commune, locale as 'fr' | 'nl' | 'en')

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: t('heading', { commune: display }),
    description: t('description', { commune: display }),
    url: pageCanonical(`/commune/${commune}`),
    mainEntity: {
      '@type': 'ItemList',
      numberOfItems: filtered.length,
      itemListElement: filtered.map((r, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        url: restaurantCanonical(r.id, r.slug),
        name: r.name,
      })),
    },
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <div className="min-h-screen bg-white">
        <div className="max-w-2xl mx-auto px-4 py-8">
          <Link
            href="/"
            className="text-sm text-stone-500 hover:text-stone-700 mb-4 inline-block"
          >
            {t('back')}
          </Link>
          <h1 className="text-2xl font-bold text-stone-900 mt-2 mb-1">
            {t('heading', { commune: display })}
          </h1>
          <p className="text-sm text-stone-500 mb-6">
            {t('count', { count: filtered.length })}
          </p>
          <ul className="space-y-3">
            {filtered.map((r, i) => {
              const directBadge =
                r.direct_url_type === 'ordering'
                  ? tCard('direct_cta_ordering')
                  : r.direct_url_type === 'menu'
                    ? tCard('direct_cta_menu')
                    : r.direct_url_type === 'website'
                      ? tCard('direct_cta_website')
                      : r.direct_url_type === 'phone'
                        ? tCard('direct_cta_phone')
                        : tDirect('badge')
              return (
                <li key={r.id}>
                  <RestaurantCard
                    restaurant={r}
                    href={`/restaurant/${r.slug ?? r.id}`}
                    isLast={i === filtered.length - 1}
                    directBadge={directBadge}
                    priority={i < 3}
                  />
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </>
  )
}
