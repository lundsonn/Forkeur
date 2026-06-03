'use client'
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

  function switchLocale(code: string) {
    document.cookie = `NEXT_LOCALE=${code}; path=/; max-age=31536000; SameSite=Lax`
    router.refresh()
  }

  return (
    <div className="flex items-center gap-0.5">
      {LANGS.map(({ code, label }, i) => (
        <button
          key={code}
          onClick={() => switchLocale(code)}
          className={`text-[10px] font-medium transition-colors px-1 ${
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
