import type { Metadata } from 'next'
import { getDeals } from '@/lib/queries'
import DealsClient from '@/components/DealsClient'

export const metadata: Metadata = {
  title: "Best deals",
  description: "Best restaurant deals and promotions across UberEats, Deliveroo, and Takeaway in Brussels.",
}

export default async function DealsPage() {
  const deals = await getDeals()
  return (
    <div className="min-h-screen bg-white">
      <DealsClient deals={deals} />
    </div>
  )
}
