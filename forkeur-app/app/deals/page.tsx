import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { getDeals } from '@/lib/queries'
import DealsClient from '@/components/DealsClient'

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations('meta')
  const title = t('deals_title')
  const description = t('deals_description')
  return {
    title,
    description,
    openGraph: { title, description },
    twitter: { card: 'summary', title, description },
  }
}

export default async function DealsPage() {
  const deals = await getDeals()
  return (
    <div className="min-h-screen bg-white">
      <DealsClient deals={deals} />
    </div>
  )
}
