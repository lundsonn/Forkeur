import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RestaurantCard from '../components/RestaurantCard'
import type { RestaurantSummary } from '../lib/queries'

const threeListings: RestaurantSummary = {
  id: '1',
  name: "McDonald's",
  neighborhood: null,
  cuisine: ['Burgers'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 49, eta_min: null },
    { platform: 'deliveroo', delivery_fee_cents: 149, eta_min: null },
    { platform: 'takeaway', delivery_fee_cents: 199, eta_min: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€0.49', savings_cents: 150 },
}

const nullFees: RestaurantSummary = {
  id: '3',
  name: 'Sushi Place',
  neighborhood: null,
  cuisine: ['Asian'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: null, eta_min: null },
    { platform: 'deliveroo', delivery_fee_cents: 299, eta_min: null },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€2.99', savings_cents: 0 },
}

const freeListing: RestaurantSummary = {
  id: '4',
  name: 'Burger King',
  neighborhood: null,
  cuisine: ['Fast food'],
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 0, eta_min: null },
    { platform: 'deliveroo', delivery_fee_cents: 99, eta_min: null },
    { platform: 'takeaway', delivery_fee_cents: 149, eta_min: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: 'Free', savings_cents: 149 },
}

const withDirectOrdering: RestaurantSummary = {
  id: '5',
  name: 'Burger Direct',
  cuisine: ['Burgers'],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: 'https://burger.sq-menu.com',
  image_url: null,
  rating: null,
  direct_url_type: 'ordering',
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 299, eta_min: null },
    { platform: 'deliveroo', delivery_fee_cents: 199, eta_min: null },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€1.99', savings_cents: 100 },
}

const withDirectMenu: RestaurantSummary = {
  id: '6',
  name: 'Pizza Direct',
  cuisine: ['Pizza'],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: 'https://pizza.be/menu',
  image_url: null,
  rating: null,
  direct_url_type: 'menu',
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 299, eta_min: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€2.99', savings_cents: 0 },
}

const withNullUrlType: RestaurantSummary = {
  id: '8',
  name: 'Mystery Direct',
  cuisine: ['Other'],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: 'https://mystery.be',
  image_url: null,
  rating: null,
  direct_url_type: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 199, eta_min: null },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€1.99', savings_cents: 0 },
}

describe('RestaurantCard', () => {
  it('shows all 3 platform fees when 3 listings exist', () => {
    render(<RestaurantCard restaurant={threeListings} directBadge="Commander directement · sans frais" />)
    expect(screen.getByText('€0.49')).toBeInTheDocument()
    expect(screen.getByText('€1.49')).toBeInTheDocument()
    expect(screen.getByText('€1.99')).toBeInTheDocument()
  })

  it('marks cheapest tile with data-cheapest attribute', () => {
    render(<RestaurantCard restaurant={threeListings} directBadge="Commander directement · sans frais" />)
    const tile = screen.getByTestId('fee-tile-uber_eats')
    expect(tile).toHaveAttribute('data-cheapest', 'true')
  })

  it('non-cheapest tiles do not have data-cheapest=true', () => {
    render(<RestaurantCard restaurant={threeListings} directBadge="Commander directement · sans frais" />)
    expect(screen.getByTestId('fee-tile-deliveroo')).not.toHaveAttribute('data-cheapest', 'true')
    expect(screen.getByTestId('fee-tile-takeaway')).not.toHaveAttribute('data-cheapest', 'true')
  })

  it('shows restaurant name', () => {
    render(<RestaurantCard restaurant={threeListings} directBadge="Commander directement · sans frais" />)
    expect(screen.getByText("McDonald's")).toBeInTheDocument()
  })

  it('skips platforms with null delivery fee', () => {
    render(<RestaurantCard restaurant={nullFees} directBadge="Commander directement · sans frais" />)
    expect(screen.getByText('€2.99')).toBeInTheDocument()
    expect(screen.queryByTestId('fee-tile-uber_eats')).toBeNull()
  })

  it('shows Free for zero-cent delivery fee', () => {
    render(<RestaurantCard restaurant={freeListing} directBadge="Commander directement · sans frais" />)
    expect(screen.getByText('Free')).toBeInTheDocument()
  })

  it('shows ordering badge when url_type is ordering', () => {
    render(<RestaurantCard restaurant={withDirectOrdering} directBadge="Order directly · no fees" />)
    expect(screen.getByRole('link', { name: 'Order directly · no fees' })).toBeInTheDocument()
  })

  it('shows menu badge when url_type is menu', () => {
    render(<RestaurantCard restaurant={withDirectMenu} directBadge="View menu" />)
    expect(screen.getByRole('link', { name: 'View menu' })).toBeInTheDocument()
  })

  it('shows website badge when url_type is website', () => {
    const withWebsite: RestaurantSummary = {
      ...withDirectOrdering,
      id: '7',
      direct_url_type: 'website',
    }
    render(<RestaurantCard restaurant={withWebsite} directBadge="Restaurant website" />)
    expect(screen.getByRole('link', { name: 'Restaurant website' })).toBeInTheDocument()
  })

  it('does not render direct pill when direct_url_type is null even if order_url is set', () => {
    render(<RestaurantCard restaurant={withNullUrlType} directBadge="Should not appear" />)
    expect(screen.queryByRole('link', { name: 'Should not appear' })).toBeNull()
  })
})
