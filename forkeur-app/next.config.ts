import createNextIntlPlugin from 'next-intl/plugin'
import type { NextConfig } from 'next'

const withNextIntl = createNextIntlPlugin('./i18n/request.ts')

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { hostname: 'tb-static.uber.com' },
      { hostname: 'just-eat-prod-eu-res.cloudinary.com' },
      { hostname: '**.deliveroo.com' },
      { hostname: '**.roocdn.com' },
      { hostname: '**.cloudinary.com' },
      { hostname: '**.takeaway.com' },
      { hostname: '**.just-eat.com' },
    ],
  },
}

export default withNextIntl(nextConfig)
