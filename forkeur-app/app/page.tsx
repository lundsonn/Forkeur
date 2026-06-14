import HomepageV2 from '@/components/HomepageV2'
import { getNearMe, type RestaurantSummary } from '@/lib/queries'

export const revalidate = 300

export default async function Home() {
  let restaurants: RestaurantSummary[]
  try {
    restaurants = await getNearMe('')
  } catch {
    restaurants = []
  }

  return (
    <div className="min-h-screen bg-white">
      <HomepageV2 initialRestaurants={restaurants} initialCommune="" />
    </div>
  )
}
