import { getPromotions } from '@/lib/queries'
import PromotionsClient from '@/components/PromotionsClient'

export default async function PromotionsPage() {
  const promos = await getPromotions()
  return (
    <div className="min-h-screen bg-white">
      <PromotionsClient promos={promos} />
    </div>
  )
}
