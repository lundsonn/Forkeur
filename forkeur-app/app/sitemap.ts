import type { MetadataRoute } from 'next'
import { backendFetch } from '@/lib/backend'
import { restaurantCanonical, pageCanonical } from '@/lib/canonical'

type RestaurantSitemapRow = { id: string; has_comparison: boolean; platform_count: number }

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const restaurants = await backendFetch<RestaurantSitemapRow[]>('/api/public/restaurants', { revalidate: 3600 }).catch(() => [] as RestaurantSitemapRow[])

  const restaurantUrls: MetadataRoute.Sitemap = restaurants
    .filter((r) => r.has_comparison)
    .map((r) => ({
      url: restaurantCanonical(r.id),
      changeFrequency: 'daily' as const,
      priority: r.platform_count >= 3 ? 0.9 : 0.8,
    }))

  return [
    { url: pageCanonical(''), changeFrequency: 'daily', priority: 1.0 },
    { url: pageCanonical('/deals'), changeFrequency: 'daily', priority: 0.8 },
    { url: pageCanonical('/owners'), changeFrequency: 'monthly', priority: 0.4 },
    ...restaurantUrls,
  ]
}
