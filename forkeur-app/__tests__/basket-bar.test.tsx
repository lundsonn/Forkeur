import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
  id: '1', platform: 'uber_eats', platform_url: null,
  delivery_fee_cents: 299, delivery_fee_label: '€2.99',
  min_order_cents: null, min_order_label: null,
  eta_label: '18 min', rating: null,
  ...overrides,
})

const listings: PlatformListing[] = [
  L({ id: '1', platform: 'uber_eats', platform_url: 'https://ubereats.com', delivery_fee_cents: 299, delivery_fee_label: '€2.99', eta_label: '18 min', rating: 4.5 }),
  L({ id: '2', platform: 'deliveroo', platform_url: null, delivery_fee_cents: 399, delivery_fee_label: '€3.99', eta_label: '22 min', rating: null }),
]

const menuItems: MenuItemWithPrices[] = [
  { name: 'Margherita', description: null, category: 'Pizza', image_url: null, prices: { uber_eats: 950, deliveroo: 940, takeaway: null, direct: null } },
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
  { name: 'Margherita', description: null, category: 'Pizza', image_url: null, prices: { uber_eats: 950, deliveroo: null, takeaway: null, direct: 850 } },
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
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toHaveTextContent('1 item')
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

describe('BasketSimulator — direct fee-savings signal', () => {
  it('shows fee-savings line when direct listing exists but has no menu items', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listingsWithDirect} phone={null} />)
    expect(screen.getByTestId('direct-fee-savings')).toBeInTheDocument()
  })

  it('fee-savings line shows cheapest non-direct platform fee (€2.99 from uber_eats)', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listingsWithDirect} phone={null} />)
    const savings = screen.getByTestId('direct-fee-savings')
    expect(savings).toHaveTextContent('€2.99')
  })

  it('fee-savings line includes the CTA copy', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listingsWithDirect} phone={null} />)
    const savings = screen.getByTestId('direct-fee-savings')
    expect(savings).toHaveTextContent('Order directly →')
  })

  it('does NOT show fee-savings line when direct listing has menu items', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItemsWithDirect} listings={listingsWithDirectAndMenu} phone={null} />)
    expect(screen.queryByTestId('direct-fee-savings')).toBeNull()
  })

  it('does NOT show fee-savings line when no direct listing at all', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.queryByTestId('direct-fee-savings')).toBeNull()
  })
})
