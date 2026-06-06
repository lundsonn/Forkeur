'use client'
import { useState } from 'react'
import Script from 'next/script'
import { useTranslations } from 'next-intl'
import { useSearchParams } from 'next/navigation'

type InquiryType = 'add_url' | 'new_listing' | 'remove'

const SITE_KEY = process.env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY ?? ''

declare global {
  interface Window {
    grecaptcha: {
      enterprise: { execute: (key: string, opts: { action: string }) => Promise<string> }
    }
  }
}

export default function OwnerContactForm() {
  const t = useTranslations('owners')
  const params = useSearchParams()
  const [inquiryType, setInquiryType] = useState<InquiryType>('add_url')
  const [name, setName] = useState(params.get('name') ?? '')
  const [email, setEmail] = useState('')
  const [url, setUrl] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setState('loading')
    try {
      let recaptchaToken: string | undefined
      if (SITE_KEY && window.grecaptcha?.enterprise) {
        recaptchaToken = await window.grecaptcha.enterprise.execute(SITE_KEY, { action: 'submit_claim' })
      }

      const res = await fetch('/api/claims', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          inquiry_type: inquiryType,
          owner_email: email,
          restaurant_name_free: name,
          direct_order_url: inquiryType === 'add_url' && url ? url : undefined,
          recaptcha_token: recaptchaToken,
        }),
      })
      if (!res.ok) throw new Error(await res.text())
      setState('success')
    } catch {
      setState('error')
    }
  }

  if (state === 'success') {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50 px-5 py-4">
        <p className="text-sm text-green-800 font-medium">{t('success')}</p>
      </div>
    )
  }

  return (
    <>
      {SITE_KEY && (
        <Script
          src={`https://www.google.com/recaptcha/enterprise.js?render=${SITE_KEY}`}
          strategy="lazyOnload"
        />
      )}
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <p className="text-sm font-semibold text-stone-900">{t('form_heading')}</p>

      {/* Request type */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-stone-700">{t('type_label')}</label>
        <div className="flex flex-col gap-1.5">
          {(['add_url', 'new_listing', 'remove'] as InquiryType[]).map((type) => (
            <label key={type} className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="radio"
                name="inquiry_type"
                value={type}
                checked={inquiryType === type}
                onChange={() => setInquiryType(type)}
                className="accent-orange-500"
              />
              <span className="text-sm text-stone-700">{t(`type_${type}`)}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Restaurant name */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-stone-700">{t('name_label')}</label>
        <input
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('name_placeholder')}
          className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>

      {/* Email */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-stone-700">{t('email_label')}</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('email_placeholder')}
          className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>

      {/* URL — only for add_url */}
      {inquiryType === 'add_url' && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-stone-700">{t('url_label')}</label>
          <input
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('url_placeholder')}
            className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
          />
        </div>
      )}

      {state === 'error' && (
        <p className="text-xs text-red-600">{t('error')}</p>
      )}

      <button
        type="submit"
        disabled={state === 'loading'}
        className="px-4 min-h-[44px] rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold disabled:opacity-50 transition-colors"
      >
        {state === 'loading' ? t('sending') : t('submit')}
      </button>
    </form>
    </>
  )
}
