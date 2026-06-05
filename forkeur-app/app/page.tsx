import HomepageClient from '@/components/HomepageClient'
import { getRestaurants } from '@/lib/queries'

export const revalidate = 3600

export default async function Home() {
  const { restaurants, cuisines } = await getRestaurants()

  return (
    <div className="min-h-screen bg-white">
      <HomepageClient restaurants={restaurants} cuisines={cuisines} />
    </div>
  )
}
