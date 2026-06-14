import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import HeroBlock from '../components/HeroBlock'
import type { RestaurantSummary } from '../lib/queries'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

const emptyRestaurants: RestaurantSummary[] = []

const noSavingsRestaurant: RestaurantSummary = {
  id: '1',
  name: 'Pizza Place',
  neighborhood: null,
  cuisine: ['Italian'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  is_chain: false,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 149, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: null,
}

// Fixture with savings_cents > 0 and >= 2 listings so findBestSavingExample returns non-null
const withSavingsRestaurant: RestaurantSummary = {
  id: '2',
  name: 'Burger Joint',
  neighborhood: null,
  cuisine: ['Burgers'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  is_chain: false,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 49, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'deliveroo', delivery_fee_cents: 249, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: {
    platform: 'uber_eats',
    fee_label: '€0.49',
    savings_cents: 200,
    delivery_fee_cents: 49,
    min_order_cents: null,
  },
}

describe('HeroBlock', () => {
  it('renders credibility key when called with any restaurants', () => {
    render(<HeroBlock restaurants={emptyRestaurants} neighborhood={null} />)
    expect(screen.getByText('hero.credibility')).toBeDefined()
  })

  it('renders neutrality key always', () => {
    render(<HeroBlock restaurants={emptyRestaurants} neighborhood={null} />)
    expect(screen.getByText('hero.neutrality')).toBeDefined()
  })

  it('does NOT render the RIGHT NOW block when findBestSavingExample returns null (empty array)', () => {
    render(<HeroBlock restaurants={emptyRestaurants} neighborhood={null} />)
    expect(screen.queryByText('hero.rightNow')).toBeNull()
  })

  it('does NOT render the RIGHT NOW block when restaurants have no savings', () => {
    render(<HeroBlock restaurants={[noSavingsRestaurant]} neighborhood={null} />)
    expect(screen.queryByText('hero.rightNow')).toBeNull()
  })

  it('renders the RIGHT NOW block with restaurant name and savings when findBestSavingExample returns non-null', () => {
    render(<HeroBlock restaurants={[withSavingsRestaurant]} neighborhood={null} />)
    expect(screen.getByText('hero.rightNow')).toBeDefined()
    expect(screen.getByText('Burger Joint')).toBeDefined()
    // savings_cents=200 → €2.00
    expect(screen.getByText('€2.00')).toBeDefined()
  })
})
