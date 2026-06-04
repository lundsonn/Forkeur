import type { MetadataRoute } from 'next'
import { createClient } from '@/utils/supabase/server'
import { cookies } from 'next/headers'

const BASE_URL = 'https://forkeur.be'

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const cookieStore = await cookies()
  const supabase = createClient(cookieStore)

  const { data: restaurants } = await supabase
    .from('restaurants')
    .select('id, name')
    .limit(2000)

  const restaurantUrls: MetadataRoute.Sitemap = (restaurants ?? []).map((r) => ({
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
