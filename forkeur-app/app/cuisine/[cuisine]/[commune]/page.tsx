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

function toDisplay(cuisine: string): string {
  return cuisine.charAt(0).toUpperCase() + cuisine.slice(1)
}

export async function generateStaticParams() {
  const { cuisines } = await getRestaurants()
  const params: { cuisine: string; commune: string }[] = []
  for (const cuisine of cuisines) {
    for (const commune of COMMUNE_SLUGS) {
      params.push({ cuisine: cuisine.toLowerCase(), commune })
    }
  }
  return params
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ cuisine: string; commune: string }>
}): Promise<Metadata> {
  const { cuisine, commune } = await params
  const [t, locale] = await Promise.all([
    getTranslations('cross_page'),
    getLocale(),
  ])
  const cuisineDisplay = toDisplay(cuisine)
  const communeDisplay = communeDisplayName(commune, locale as 'fr' | 'nl' | 'en')
  const title = t('title', { cuisine: cuisineDisplay, commune: communeDisplay })
  const description = t('description', { cuisine: cuisineDisplay, commune: communeDisplay })
  const url = pageCanonical(`/cuisine/${cuisine}/${commune}`)
  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { title, description },
    twitter: { card: 'summary', title, description },
  }
}

export default async function CuisineCommunePage({
  params,
}: {
  params: Promise<{ cuisine: string; commune: string }>
}) {
  const { cuisine, commune } = await params
  const [{ restaurants }, t, tCard, tDirect, locale] = await Promise.all([
    getRestaurants(),
    getTranslations('cross_page'),
    getTranslations('card'),
    getTranslations('direct'),
    getLocale(),
  ])

  const filtered = restaurants
    .filter((r) => r.cuisine.some((c) => c.toLowerCase() === cuisine) && r.commune === commune && r.has_comparison)
    .sort(
      (a, b) =>
        (platformSavingsSelector(b.listings)?.savingCents ?? 0) -
        (platformSavingsSelector(a.listings)?.savingCents ?? 0),
    )

  if (filtered.length < MIN_COMPARISON_RESTAURANTS) notFound()

  const cuisineDisplay = toDisplay(cuisine)
  const communeDisplay = communeDisplayName(commune, locale as 'fr' | 'nl' | 'en')

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: t('heading', { cuisine: cuisineDisplay, commune: communeDisplay }),
    description: t('description', { cuisine: cuisineDisplay, commune: communeDisplay }),
    url: pageCanonical(`/cuisine/${cuisine}/${commune}`),
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
            href={`/cuisine/${cuisine}`}
            className="text-sm text-stone-500 hover:text-stone-700 mb-4 inline-block"
          >
            {t('back', { cuisine: cuisineDisplay })}
          </Link>
          <h1 className="text-2xl font-bold text-stone-900 mt-2 mb-1">
            {t('heading', { cuisine: cuisineDisplay, commune: communeDisplay })}
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
