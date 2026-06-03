import { getRequestConfig } from 'next-intl/server'
import { cookies, headers } from 'next/headers'

export default getRequestConfig(async () => {
  const supported = ['en', 'fr', 'nl']
  const cookieLocale = (await cookies()).get('NEXT_LOCALE')?.value
  let locale = cookieLocale && supported.includes(cookieLocale) ? cookieLocale : null
  if (!locale) {
    const acceptLang = (await headers()).get('accept-language') ?? ''
    const preferred = acceptLang.split(',')[0].split('-')[0]
    locale = supported.includes(preferred) ? preferred : 'en'
  }
  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  }
})
