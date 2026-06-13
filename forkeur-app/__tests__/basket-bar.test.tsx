import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import BasketSimulator from '../components/BasketSimulator'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'
import en from '../messages/en.json'

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

const L = (overrides: Partial<PlatformListing>): PlatformListing => ({
  id: '1', platform: 'uber_eats', platform_url: null, url_type: null,
  delivery_fee_cents: 299, delivery_fee_label: '€2.99',
  min_order_cents: null, min_order_label: null,
  eta_label: '18 min', rating: null,
  last_scraped_at: null, promotions: [], is_available: true, opening_hours: null,
  ...overrides,
})

// ---------------------------------------------------------------------------
// Fixtures for savings banner tests
// ---------------------------------------------------------------------------

// 3 menu items with direct prices (cheaper than platform). Threshold: directCount >= 3.
// Platform: uber_eats fee 299 cents. Per-item: UE=1000, direct=800 cents.
// With 3 items in basket: UE total = 3*1000 + 299 = 3299 cents = €32.99
//                         direct subtotal = 3*800 = 2400 cents = €24.00
// Savings = 3299 - 2400 = 899 cents → banner shows €8.99
const bannerMenuItems: MenuItemWithPrices[] = [
  { name: 'Item A', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1000, deliveroo: 1050, takeaway: 1100, direct: 800 } },
  { name: 'Item B', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1000, deliveroo: 1050, takeaway: 1100, direct: 800 } },
  { name: 'Item C', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1000, deliveroo: 1050, takeaway: 1100, direct: 800 } },
]

// 3 menu items WITHOUT direct prices (threshold not met)
const noDirectMenuItems: MenuItemWithPrices[] = [
  { name: 'Item A', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1000, deliveroo: 1050, takeaway: 1100, direct: null } },
  { name: 'Item B', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1000, deliveroo: 1050, takeaway: 1100, direct: null } },
  { name: 'Item C', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1000, deliveroo: 1050, takeaway: 1100, direct: null } },
]

// 3 items with direct prices that are MORE expensive than platform
// UE total = 3*800 + 299 = 2699; direct = 3*1000 = 3000 → no savings
const directMoreExpensiveMenuItems: MenuItemWithPrices[] = [
  { name: 'Item A', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 800, deliveroo: 850, takeaway: 900, direct: 1000 } },
  { name: 'Item B', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 800, deliveroo: 850, takeaway: 900, direct: 1000 } },
  { name: 'Item C', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 800, deliveroo: 850, takeaway: 900, direct: 1000 } },
]

const bannerListings: PlatformListing[] = [
  L({ id: '1', platform: 'uber_eats', platform_url: 'https://ubereats.com', delivery_fee_cents: 299, delivery_fee_label: '€2.99', eta_label: '18 min', rating: 4.5 }),
  L({ id: '2', platform: 'deliveroo', platform_url: null, delivery_fee_cents: 399, delivery_fee_label: '€3.99', eta_label: '22 min', rating: null }),
  L({ id: '3', platform: 'direct', platform_url: 'https://myrestaurant.com', delivery_fee_cents: null, delivery_fee_label: null, eta_label: null, rating: null }),
]

const listings: PlatformListing[] = [
  L({ id: '1', platform: 'uber_eats', platform_url: 'https://ubereats.com', delivery_fee_cents: 299, delivery_fee_label: '€2.99', eta_label: '18 min', rating: 4.5 }),
  L({ id: '2', platform: 'deliveroo', platform_url: null, delivery_fee_cents: 399, delivery_fee_label: '€3.99', eta_label: '22 min', rating: null }),
]

const menuItems: MenuItemWithPrices[] = [
  { name: 'Margherita', description: null, category: 'Pizza', image_url: null, allergens: null, prices: { uber_eats: 950, deliveroo: 940, takeaway: null, direct: null } },
]

// Listings with a direct entry (no menu items for direct)
const listingsWithDirect: PlatformListing[] = [
  L({ id: '1', platform: 'uber_eats', platform_url: 'https://ubereats.com', delivery_fee_cents: 299, delivery_fee_label: '€2.99', eta_label: '18 min', rating: 4.5 }),
  L({ id: '2', platform: 'deliveroo', platform_url: null, delivery_fee_cents: 399, delivery_fee_label: '€3.99', eta_label: '22 min', rating: null }),
  L({ id: '3', platform: 'direct', platform_url: 'https://example.com', delivery_fee_cents: null, delivery_fee_label: null, eta_label: null, rating: null, url_type: 'website' }),
]

// Listings with a direct entry AND direct menu items
const listingsWithDirectAndMenu: PlatformListing[] = [
  L({ id: '1', platform: 'uber_eats', platform_url: 'https://ubereats.com', delivery_fee_cents: 299, delivery_fee_label: '€2.99', eta_label: '18 min', rating: 4.5 }),
  L({ id: '3', platform: 'direct', platform_url: 'https://example.com', delivery_fee_cents: null, delivery_fee_label: null, eta_label: null, rating: null, url_type: 'website' }),
]

const menuItemsWithDirect: MenuItemWithPrices[] = [
  { name: 'Margherita', description: null, category: 'Pizza', image_url: null, allergens: null, prices: { uber_eats: 950, deliveroo: null, takeaway: null, direct: 850 } },
]

describe('BasketSimulator', () => {
  it('basket bar hidden when basket empty', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('basket bar visible after adding item', async () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toBeInTheDocument()
  })

  it('basket bar shows item count', async () => {
    // Redesigned sticky bar surfaces the count via basket.bottom_cheapest
    // ("Cheapest for your 1-item order").
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toHaveTextContent('1-item order')
  })

  it('removing item decreases stepper qty', async () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByText('2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('removing last item hides basket bar', async () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('tapping basket bar opens compare sheet', async () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByTestId('basket-bar'))
    expect(screen.getByText('Best right now')).toBeInTheDocument()
  })
})

// The top "direct-fee-savings" signal bar inside BasketSimulator was removed in the
// detail-page redesign; per-platform delivery fees (with direct savings) now render on
// app/restaurant/[id]/page.tsx. The positive-render tests for that bar were dropped.
// The negative ("does NOT show") cases below still hold — the testid is simply absent now.
describe('BasketSimulator — direct fee-savings signal', () => {
  it('does NOT show fee-savings line when direct listing has menu items', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItemsWithDirect} listings={listingsWithDirectAndMenu} phone={null} />)
    expect(screen.queryByTestId('direct-fee-savings')).toBeNull()
  })

  it('does NOT show fee-savings line when no direct listing at all', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.queryByTestId('direct-fee-savings')).toBeNull()
  })
})

describe('BasketSimulator — direct savings banner (menu-aware)', () => {
  it('banner shows when direct is cheaper and threshold met (≥3 items with direct prices)', () => {
    renderWithIntl(
      <BasketSimulator menuItems={bannerMenuItems} listings={bannerListings} phone={null} />
    )
    // Add all 3 items to meet the threshold
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    fireEvent.click(screen.getByLabelText('Add Item C to basket'))
    expect(screen.getByTestId('direct-savings-banner')).toBeInTheDocument()
  })

  it('banner shows savings amount formatted as €X.XX', () => {
    renderWithIntl(
      <BasketSimulator menuItems={bannerMenuItems} listings={bannerListings} phone={null} />
    )
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    fireEvent.click(screen.getByLabelText('Add Item C to basket'))
    const banner = screen.getByTestId('direct-savings-banner')
    // Banner should contain a euro amount (savings from direct ordering)
    expect(banner).toHaveTextContent(/€\d+\.\d{2}/)
  })

  it('banner shows the locked French copy', () => {
    renderWithIntl(
      <BasketSimulator menuItems={bannerMenuItems} listings={bannerListings} phone={null} />
    )
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    fireEvent.click(screen.getByLabelText('Add Item C to basket'))
    // Test with EN locale — messages use en.json keys; sub-line key is direct_savings_subtitle
    const banner = screen.getByTestId('direct-savings-banner')
    expect(banner).toHaveTextContent('Same dishes · no platform fees')
  })

  it('banner includes CTA link to direct URL', () => {
    renderWithIntl(
      <BasketSimulator menuItems={bannerMenuItems} listings={bannerListings} phone={null} />
    )
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    fireEvent.click(screen.getByLabelText('Add Item C to basket'))
    const link = screen.getByRole('link', { name: /order →/i })
    expect(link).toHaveAttribute('href', 'https://myrestaurant.com')
  })

  it('banner hidden when threshold not met (fewer than 3 items with direct prices)', () => {
    // Only add 2 items — threshold requires directCount >= 3
    const twoItemMenuItems: MenuItemWithPrices[] = bannerMenuItems.slice(0, 2)
    renderWithIntl(
      <BasketSimulator menuItems={twoItemMenuItems} listings={bannerListings} phone={null} />
    )
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    expect(screen.queryByTestId('direct-savings-banner')).toBeNull()
  })

  it('banner hidden when basket is empty', () => {
    renderWithIntl(
      <BasketSimulator menuItems={bannerMenuItems} listings={bannerListings} phone={null} />
    )
    expect(screen.queryByTestId('direct-savings-banner')).toBeNull()
  })

  it('banner hidden when direct is more expensive than platform', () => {
    renderWithIntl(
      <BasketSimulator menuItems={directMoreExpensiveMenuItems} listings={bannerListings} phone={null} />
    )
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    fireEvent.click(screen.getByLabelText('Add Item C to basket'))
    expect(screen.queryByTestId('direct-savings-banner')).toBeNull()
  })

  it('banner hidden when no items have direct prices (threshold not met)', () => {
    renderWithIntl(
      <BasketSimulator menuItems={noDirectMenuItems} listings={bannerListings} phone={null} />
    )
    fireEvent.click(screen.getByLabelText('Add Item A to basket'))
    fireEvent.click(screen.getByLabelText('Add Item B to basket'))
    fireEvent.click(screen.getByLabelText('Add Item C to basket'))
    expect(screen.queryByTestId('direct-savings-banner')).toBeNull()
  })
})
