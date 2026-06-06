'use client'
import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { useLocale } from 'next-intl'

const LANGS = [
  { code: 'en', label: 'EN' },
  { code: 'fr', label: 'FR' },
  { code: 'nl', label: 'NL' },
] as const

export default function LangToggle() {
  const locale = useLocale()
  const router = useRouter()
  const [, startTransition] = useTransition()

  function switchLocale(code: string) {
    // eslint-disable-next-line react-hooks/immutability
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=31536000; SameSite=Lax`
    startTransition(() => { router.refresh() })
  }

  return (
    <div className="flex items-center gap-0.5">
      {LANGS.map(({ code, label }, i) => (
        <button
          key={code}
          onClick={() => switchLocale(code)}
          className={`text-[10px] font-medium transition-colors px-2 min-h-[44px] inline-flex items-center ${
            locale === code
              ? 'text-stone-900'
              : 'text-stone-400 hover:text-stone-600'
          }`}
        >
          {label}{i < LANGS.length - 1 ? <span className="text-stone-200 ml-0.5">·</span> : null}
        </button>
      ))}
    </div>
  )
}
