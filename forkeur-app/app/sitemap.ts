import type { MetadataRoute } from 'next'
import { backendFetch } from '@/lib/backend'

const BASE_URL = 'https://forkeur.be'

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const restaurants = await backendFetch<{ id: string }[]>('/api/public/restaurants', { revalidate: 3600 }).catch(() => [] as { id: string }[])

  const restaurantUrls: MetadataRoute.Sitemap = restaurants.map((r) => ({
    url: `${BASE_URL}/restaurant/${r.id}`,
    changeFrequency: 'daily',
    priority: 0.7,
  }))

  return [
    { url: BASE_URL, changeFrequency: 'daily', priority: 1.0 },
    { url: `${BASE_URL}/deals`, changeFrequency: 'daily', priority: 0.8 },
    { url: `${BASE_URL}/owners`, changeFrequency: 'monthly', priority: 0.4 },
    ...restaurantUrls,
  ]
}
