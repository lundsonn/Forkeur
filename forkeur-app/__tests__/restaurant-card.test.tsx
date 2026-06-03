import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RestaurantCard from '../components/RestaurantCard'
import type { RestaurantSummary } from '../lib/queries'

const threeListings: RestaurantSummary = {
  id: '1',
  name: "McDonald's",
  cuisine: ['Burgers'],
  lat: null,
  lng: null,
  order_url: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 49 },
    { platform: 'deliveroo', delivery_fee_cents: 149 },
    { platform: 'takeaway', delivery_fee_cents: 199 },
  ],
  cheapest: { platform: 'uber_eats', fee_label: '€0.49', savings_cents: 150 },
}

const nullFees: RestaurantSummary = {
  id: '3',
  name: 'Sushi Place',
  cuisine: ['Asian'],
  lat: null,
  lng: null,
  order_url: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: null },
    { platform: 'deliveroo', delivery_fee_cents: 299 },
  ],
  cheapest: { platform: 'deliveroo', fee_label: '€2.99', savings_cents: 0 },
}

const freeListing: RestaurantSummary = {
  id: '4',
  name: 'Burger King',
  cuisine: ['Fast food'],
  lat: null,
  lng: null,
  order_url: null,
  listings: [
    { platform: 'uber_eats', delivery_fee_cents: 0 },
    { platform: 'deliveroo', delivery_fee_cents: 99 },
    { platform: 'takeaway', delivery_fee_cents: 149 },
  ],
  cheapest: { platform: 'uber_eats', fee_label: 'Free', savings_cents: 149 },
}

describe('RestaurantCard', () => {
  it('shows all 3 platform fees when 3 listings exist', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByText('€0.49')).toBeInTheDocument()
    expect(screen.getByText('€1.49')).toBeInTheDocument()
    expect(screen.getByText('€1.99')).toBeInTheDocument()
  })

  it('marks cheapest tile with data-cheapest attribute', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    const tile = screen.getByTestId('fee-tile-uber_eats')
    expect(tile).toHaveAttribute('data-cheapest', 'true')
  })

  it('non-cheapest tiles do not have data-cheapest=true', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByTestId('fee-tile-deliveroo')).not.toHaveAttribute('data-cheapest', 'true')
    expect(screen.getByTestId('fee-tile-takeaway')).not.toHaveAttribute('data-cheapest', 'true')
  })

  it('shows restaurant name', () => {
    render(<RestaurantCard restaurant={threeListings} />)
    expect(screen.getByText("McDonald's")).toBeInTheDocument()
  })

  it('skips platforms with null delivery fee', () => {
    render(<RestaurantCard restaurant={nullFees} />)
    expect(screen.getByText('€2.99')).toBeInTheDocument()
    expect(screen.queryByTestId('fee-tile-uber_eats')).toBeNull()
  })

  it('shows Free for zero-cent delivery fee', () => {
    render(<RestaurantCard restaurant={freeListing} />)
    expect(screen.getByText('Free')).toBeInTheDocument()
  })
})
