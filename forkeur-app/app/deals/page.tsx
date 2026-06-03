import { getDeals } from '@/lib/queries'
import DealsClient from '@/components/DealsClient'

export default async function DealsPage() {
  const deals = await getDeals()
  return (
    <div className="min-h-screen bg-white">
      <DealsClient deals={deals} />
    </div>
  )
}
