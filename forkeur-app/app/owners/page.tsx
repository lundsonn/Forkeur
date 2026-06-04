import type { Metadata } from 'next'
import Link from 'next/link'
import { Suspense } from 'react'
import { getTranslations } from 'next-intl/server'
import OwnerContactForm from '@/components/OwnerContactForm'

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations('meta')
  return { title: t('owners_title'), description: t('owners_description') }
}

export default async function OwnersPage() {
  const t = await getTranslations('owners')
  const tNav = await getTranslations('nav')

  return (
    <div className="max-w-md mx-auto px-5 pb-16">
      {/* Nav */}
      <div className="flex items-center pt-5 pb-4">
        <Link href="/" className="text-stone-500 hover:text-stone-800 text-lg mr-auto">‹</Link>
        <Link href="/" className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </Link>
      </div>

      {/* Heading */}
      <h1 className="text-2xl font-bold text-stone-900 mt-2 mb-3">{t('heading')}</h1>
      <p className="text-sm text-stone-500 leading-relaxed mb-8">{t('intro')}</p>

      {/* Section: Add URL */}
      <div className="mb-6">
        <h2 className="text-base font-semibold text-stone-900 mb-1">{t('section_add')}</h2>
        <p className="text-sm text-stone-500 leading-relaxed">{t('section_add_body')}</p>
      </div>

      {/* Section: Remove */}
      <div className="mb-8">
        <h2 className="text-base font-semibold text-stone-900 mb-1">{t('section_remove')}</h2>
        <p className="text-sm text-stone-500 leading-relaxed">{t('section_remove_body')}</p>
      </div>

      {/* Contact form */}
      <div className="border border-stone-200 rounded-2xl p-5">
        <Suspense>
          <OwnerContactForm />
        </Suspense>
      </div>
    </div>
  )
}
