import type { MetadataRoute } from 'next'
import { backendFetch } from '@/lib/backend'
import { restaurantCanonical, pageCanonical } from '@/lib/canonical'
import { MIN_COMPARISON_RESTAURANTS } from '@/lib/communes'

type RestaurantSitemapRow = {
  id: string
  slug: string | null
  has_comparison: boolean
  platform_count: number
  commune: string | null
  cuisine: string | null
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const restaurants = await backendFetch<RestaurantSitemapRow[]>('/api/public/restaurants', { revalidate: 3600 }).catch(() => [] as RestaurantSitemapRow[])

  const compared = restaurants.filter((r) => r.has_comparison)

  const restaurantUrls: MetadataRoute.Sitemap = compared.map((r) => ({
    url: restaurantCanonical(r.id, r.slug),
    changeFrequency: 'daily' as const,
    priority: r.platform_count >= 3 ? 0.9 : 0.8,
  }))

  // Collection pages — only include if ≥ MIN_COMPARISON_RESTAURANTS has_comparison restaurants
  const cuisineCount = new Map<string, number>()
  const communeCount = new Map<string, number>()
  const crossCount = new Map<string, number>()

  for (const r of compared) {
    if (r.cuisine) cuisineCount.set(r.cuisine, (cuisineCount.get(r.cuisine) ?? 0) + 1)
    if (r.commune) communeCount.set(r.commune, (communeCount.get(r.commune) ?? 0) + 1)
    if (r.cuisine && r.commune) {
      const key = `${r.cuisine}/${r.commune}`
      crossCount.set(key, (crossCount.get(key) ?? 0) + 1)
    }
  }

  const cuisineUrls: MetadataRoute.Sitemap = [...cuisineCount.entries()]
    .filter(([, n]) => n >= MIN_COMPARISON_RESTAURANTS)
    .map(([cuisine]) => ({
      url: pageCanonical(`/cuisine/${cuisine}`),
      changeFrequency: 'daily' as const,
      priority: 0.7,
    }))

  const communeUrls: MetadataRoute.Sitemap = [...communeCount.entries()]
    .filter(([, n]) => n >= MIN_COMPARISON_RESTAURANTS)
    .map(([commune]) => ({
      url: pageCanonical(`/commune/${commune}`),
      changeFrequency: 'daily' as const,
      priority: 0.7,
    }))

  const crossUrls: MetadataRoute.Sitemap = [...crossCount.entries()]
    .filter(([, n]) => n >= MIN_COMPARISON_RESTAURANTS)
    .map(([key]) => ({
      url: pageCanonical(`/cuisine/${key}`),
      changeFrequency: 'daily' as const,
      priority: 0.6,
    }))

  return [
    { url: pageCanonical(''), changeFrequency: 'daily', priority: 1.0 },
    { url: pageCanonical('/deals'), changeFrequency: 'daily', priority: 0.8 },
    { url: pageCanonical('/owners'), changeFrequency: 'monthly', priority: 0.4 },
    ...restaurantUrls,
    ...cuisineUrls,
    ...communeUrls,
    ...crossUrls,
  ]
}
