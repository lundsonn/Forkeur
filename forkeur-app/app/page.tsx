import HomepageV2 from '@/components/HomepageV2'
import { getNearMe } from '@/lib/queries'

export const revalidate = 300

export default async function Home() {
  let restaurants
  try {
    restaurants = await getNearMe('bruxelles')
  } catch {
    restaurants = []
  }

  return (
    <div className="min-h-screen bg-white">
      <HomepageV2 initialRestaurants={restaurants} initialCommune="bruxelles" />
    </div>
  )
}
