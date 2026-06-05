import createNextIntlPlugin from 'next-intl/plugin'
import type { NextConfig } from 'next'

const withNextIntl = createNextIntlPlugin('./i18n/request.ts')

// CSP balances the dynamic needs of this app against the audit recommendation:
//   - Google Analytics (gtag) loads from www.googletagmanager.com.
//   - reCAPTCHA Enterprise loads from www.google.com + www.gstatic.com.
//   - Next.js requires 'unsafe-inline' for its hydration runtime script and
//     'unsafe-eval' for some webpack chunks; both are unavoidable for App
//     Router. The other directives stay strict.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com https://www.google.com https://www.gstatic.com",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self' https://*.supabase.co https://www.google-analytics.com",
  "frame-src https://www.google.com",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ')

const securityHeaders = [
  { key: 'Content-Security-Policy', value: CSP },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
]

const nextConfig: NextConfig = {
  images: {
    // Audit recommendation was to narrow these from `**.cdn` wildcards, but
    // Deliveroo / Takeaway both shard image hosts across many subdomains
    // (cdn1.deliveroo.com, cdn4.deliveroo.com, eu-prod-cdn.deliveroo.com, …).
    // Hard-listing every shard breaks production within a week. Compromise:
    // pin protocol to https and forbid SVG so the wildcard can't deliver a
    // scripted image.
    dangerouslyAllowSVG: false,
    remotePatterns: [
      { protocol: 'https', hostname: 'tb-static.uber.com' },
      { protocol: 'https', hostname: 'just-eat-prod-eu-res.cloudinary.com' },
      { protocol: 'https', hostname: '**.deliveroo.com' },
      { protocol: 'https', hostname: '**.roocdn.com' },
      { protocol: 'https', hostname: '**.cloudinary.com' },
      { protocol: 'https', hostname: '**.takeaway.com' },
      { protocol: 'https', hostname: '**.just-eat.com' },
    ],
  },
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }]
  },
}

export default withNextIntl(nextConfig)
