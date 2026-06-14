import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import RestaurantCard from '../components/RestaurantCard'
import type { RestaurantSummary } from '../lib/queries'
import en from '../messages/en.json'

function renderCard(props: Omit<React.ComponentProps<typeof RestaurantCard>, 'href'> & { href?: string }) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <RestaurantCard href={props.href ?? '/restaurant/test'} {...props} />
    </NextIntlClientProvider>
  )
}

const threeListings: RestaurantSummary = {
  id: '1',
  name: "McDonald's",
  slug: null,
  neighborhood: null,
  cuisine: ['Burgers'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  is_chain: false,
  platform_count: 3,
  has_comparison: true,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 49, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'deliveroo', delivery_fee_cents: 149, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'takeaway', delivery_fee_cents: 199, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€0.49', savings_cents: 150, delivery_fee_cents: 49, min_order_cents: null },
}

const nullFees: RestaurantSummary = {
  id: '3',
  name: 'Sushi Place',
  slug: null,
  neighborhood: null,
  cuisine: ['Asian'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  is_chain: false,
  platform_count: 1,
  has_comparison: false,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: null, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'deliveroo', delivery_fee_cents: 299, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€2.99', savings_cents: 0, delivery_fee_cents: 299, min_order_cents: null },
}

const freeListing: RestaurantSummary = {
  id: '4',
  name: 'Burger King',
  slug: null,
  neighborhood: null,
  cuisine: ['Fast food'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  is_chain: false,
  platform_count: 3,
  has_comparison: true,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 0, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'deliveroo', delivery_fee_cents: 99, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'takeaway', delivery_fee_cents: 149, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: 'Free', savings_cents: 149, delivery_fee_cents: 0, min_order_cents: null },
}

const withDirectOrdering: RestaurantSummary = {
  id: '5',
  name: 'Burger Direct',
  slug: null,
  cuisine: ['Burgers'],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: 'https://burger.sq-menu.com',
  image_url: null,
  rating: null,
  direct_url_type: 'ordering',
  is_chain: false,
  platform_count: 2,
  has_comparison: true,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 299, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
    { platform: 'deliveroo', delivery_fee_cents: 199, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€1.99', savings_cents: 100, delivery_fee_cents: 199, min_order_cents: null },
}

const withDirectMenu: RestaurantSummary = {
  id: '6',
  name: 'Pizza Direct',
  slug: null,
  cuisine: ['Pizza'],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: 'https://pizza.be/menu',
  image_url: null,
  rating: null,
  direct_url_type: 'menu',
  is_chain: false,
  platform_count: 1,
  has_comparison: false,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 299, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€2.99', savings_cents: 0, delivery_fee_cents: 299, min_order_cents: null },
}

const withNullUrlType: RestaurantSummary = {
  id: '8',
  name: 'Mystery Direct',
  slug: null,
  cuisine: ['Other'],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: 'https://mystery.be',
  image_url: null,
  rating: null,
  direct_url_type: null,
  is_chain: false,
  platform_count: 1,
  has_comparison: false,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 199, min_order_cents: null, eta_min: null, is_available: true, opening_hours: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 0, delivery_fee_cents: 199, min_order_cents: null },
}

describe('RestaurantCard', () => {
  it('shows all 3 platform fees when 3 listings exist', () => {
    renderCard({ restaurant: threeListings, directBadge: "Commander directement · sans frais" })
    expect(screen.getAllByText('€0.49').length).toBeGreaterThan(0)
    expect(screen.getByText('€1.49')).toBeInTheDocument()
    expect(screen.getByText('€1.99')).toBeInTheDocument()
  })

  it('marks cheapest tile with data-cheapest attribute', () => {
    renderCard({ restaurant: threeListings, directBadge: "Commander directement · sans frais" })
    const tile = screen.getByTestId('fee-tile-uber_eats')
    expect(tile).toHaveAttribute('data-cheapest', 'true')
  })

  it('non-cheapest tiles do not have data-cheapest=true', () => {
    renderCard({ restaurant: threeListings, directBadge: "Commander directement · sans frais" })
    expect(screen.getByTestId('fee-tile-deliveroo')).not.toHaveAttribute('data-cheapest', 'true')
    expect(screen.getByTestId('fee-tile-takeaway')).not.toHaveAttribute('data-cheapest', 'true')
  })

  it('shows restaurant name', () => {
    renderCard({ restaurant: threeListings, directBadge: "Commander directement · sans frais" })
    expect(screen.getByText("McDonald's")).toBeInTheDocument()
  })

  it('skips platforms with null delivery fee', () => {
    renderCard({ restaurant: nullFees, directBadge: "Commander directement · sans frais" })
    expect(screen.getAllByText('€2.99').length).toBeGreaterThan(0)
    expect(screen.queryByTestId('fee-tile-uber_eats')).toBeNull()
  })

  it('shows Free for zero-cent delivery fee', () => {
    renderCard({ restaurant: freeListing, directBadge: "Commander directement · sans frais" })
    expect(screen.getByText('Free')).toBeInTheDocument()
  })

  it('shows ordering badge when url_type is ordering', () => {
    renderCard({ restaurant: withDirectOrdering, directBadge: "Order directly · no fees" })
    expect(screen.getByRole('link', { name: 'Order directly · no fees' })).toBeInTheDocument()
  })

  it('shows menu badge when url_type is menu', () => {
    renderCard({ restaurant: withDirectMenu, directBadge: "View menu" })
    expect(screen.getByRole('link', { name: 'View menu' })).toBeInTheDocument()
  })

  it('shows website badge when url_type is website', () => {
    const withWebsite: RestaurantSummary = {
      ...withDirectOrdering,
      id: '7',
      direct_url_type: 'website',
    }
    renderCard({ restaurant: withWebsite, directBadge: "Restaurant website" })
    expect(screen.getByRole('link', { name: 'Restaurant website' })).toBeInTheDocument()
  })

  it('does not render direct pill when direct_url_type is null even if order_url is set', () => {
    renderCard({ restaurant: withNullUrlType, directBadge: "Should not appear" })
    expect(screen.queryByRole('link', { name: 'Should not appear' })).toBeNull()
  })

  // --- Task 6 new tests ---

  it('root element has data-testid="restaurant-card" and data-id attribute', () => {
    renderCard({ restaurant: threeListings, directBadge: "Order" })
    const card = screen.getByTestId('restaurant-card')
    expect(card).toBeInTheDocument()
    expect(card).toHaveAttribute('data-id', threeListings.id)
  })

  it('CHEAPEST badge has bg-green-500 class (not bg-orange-500)', () => {
    renderCard({ restaurant: threeListings, directBadge: "Order" })
    // Find the cheapest badge by its text content (translation key cheapest_badge = "CHEAPEST")
    const badge = screen.getByText('CHEAPEST')
    expect(badge).toHaveClass('bg-green-500')
    expect(badge).not.toHaveClass('bg-orange-500')
  })

  it('winner listing shows green savings text with "cheaper"', () => {
    // threeListings: uber_eats=49, deliveroo=149 → savings = 100 cents = €1.00
    renderCard({ restaurant: threeListings, directBadge: "Order" })
    const cheaperText = screen.getByText(/\+€1\.00 cheaper/)
    expect(cheaperText).toBeInTheDocument()
    expect(cheaperText).toHaveClass('text-green-600')
  })

  it('loser listing shows red overpay text "+€X more here"', () => {
    // threeListings: deliveroo=149, uber_eats(winner)=49 → overpay = 100 cents = €1.00
    renderCard({ restaurant: threeListings, directBadge: "Order" })
    // deliveroo overpay: 149 - 49 = 100 cents = €1.00
    const overpayDeliveroo = screen.getByText(/\+€1\.00 more here/)
    expect(overpayDeliveroo).toBeInTheDocument()
    expect(overpayDeliveroo).toHaveClass('text-red-600')
  })

  it('loser listings all show correct red overpay amounts', () => {
    // threeListings: uber_eats=49(winner), deliveroo=149(+1.00), takeaway=199(+1.50)
    renderCard({ restaurant: threeListings, directBadge: "Order" })
    expect(screen.getByText(/\+€1\.00 more here/)).toBeInTheDocument()
    expect(screen.getByText(/\+€1\.50 more here/)).toBeInTheDocument()
  })
})
