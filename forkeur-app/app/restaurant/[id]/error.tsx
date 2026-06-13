'use client' // Error boundaries must be Client Components

import { useEffect } from 'react'
import { useTranslations } from 'next-intl'

export default function RestaurantError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  const t = useTranslations('error')

  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="max-w-md mx-auto px-5 min-h-[70vh] flex flex-col items-center justify-center text-center">
      <h1 className="text-2xl font-bold text-stone-900 mb-2">{t('restaurant_title')}</h1>
      <p className="text-sm text-stone-500 mb-6 max-w-xs">{t('restaurant_body')}</p>
      <button
        onClick={() => reset()}
        className="bg-orange-500 hover:bg-orange-600 text-white font-medium text-sm rounded-full px-6 py-2.5 transition-colors"
      >
        {t('retry')}
      </button>
    </div>
  )
}
