import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import BasketSimulator from '../components/BasketSimulator'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'
import en from '../messages/en.json'

vi.mock('next/image', () => ({
  default: ({ alt, ...props }: { alt: string; [key: string]: unknown }) => <img alt={alt} {...props} />,
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

const makeListing = (platform: PlatformListing['platform'], fee: number | null): PlatformListing => ({
  id: `listing-${platform}`,
  platform,
  platform_url: `https://${platform}.com/test`,
  url_type: 'order',
  delivery_fee_cents: fee,
  delivery_fee_label: fee === null ? null : fee === 0 ? 'Free' : `€${(fee / 100).toFixed(2)}`,
  min_order_cents: null,
  min_order_label: null,
  eta_label: '25–35 min',
  rating: 4.2,
  last_scraped_at: null,
  promotions: [], is_available: true, opening_hours: null,
})

const menuItems: MenuItemWithPrices[] = [
  {
    name: 'Margherita',
    description: 'Classic pizza',
    category: 'Pizzas',
    image_url: null, allergens: null,
    prices: { uber_eats: 899, deliveroo: 950, takeaway: 870, direct: null },
  },
  {
    name: 'Quattro Formaggi',
    description: null,
    category: 'Pizzas',
    image_url: null, allergens: null,
    prices: { uber_eats: 1050, deliveroo: 1100, takeaway: 1020, direct: null },
  },
]

const listings: PlatformListing[] = [
  makeListing('uber_eats', 199),
  makeListing('deliveroo', 149),
  makeListing('takeaway', 249),
]

describe('BasketSimulator', () => {
  it('renders menu items', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.getByText('Margherita')).toBeInTheDocument()
    expect(screen.getByText('Quattro Formaggi')).toBeInTheDocument()
  })

  it('surfaces the cheapest platform in the sticky bar after adding an item', () => {
    // The old top platform-fee bar was removed (delivery fees now live on the
    // detail page). The cheapest platform is now surfaced via the green all-in
    // CTA card once the basket has items.
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    // Margherita: Uber 899+199=1098 < Deliveroo 950+149=1099 < Takeaway 870+249=1119
    // → Uber Eats is the cheapest complete platform and appears in the all-in CTA.
    expect(screen.getAllByText(/Uber Eats/).length).toBeGreaterThan(0)
  })

  it('shows no menu message when empty', () => {
    renderWithIntl(<BasketSimulator menuItems={[]} listings={listings} phone={null} />)
    expect(screen.getByText('No menu data available yet.')).toBeInTheDocument()
  })

  it('shows add button for each item', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    const addButtons = screen.getAllByLabelText(/Add .* to basket/)
    expect(addButtons).toHaveLength(2)
  })

  it('basket bar absent before adding items', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('basket bar appears after adding an item', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    expect(screen.getByTestId('basket-bar')).toBeInTheDocument()
  })

  it('basket bar shows item count after add', () => {
    // Redesigned sticky bar shows "Cheapest for your 1-item order" (basket.bottom_cheapest)
    // instead of the old "1 item · €subtotal" subline.
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    expect(screen.getByText(/1-item order/)).toBeInTheDocument()
  })

  it('stepper appears after adding item', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    expect(screen.getByLabelText('Remove Margherita from basket')).toBeInTheDocument()
  })

  it('remove button decrements and hides stepper at 0', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    fireEvent.click(screen.getByLabelText('Remove Margherita from basket'))
    // stepper gone, add button back
    expect(screen.getByLabelText('Add Margherita to basket')).toBeInTheDocument()
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('groups items by category', () => {
    const multiCat: MenuItemWithPrices[] = [
      { name: 'Salad', description: null, category: 'Starters', image_url: null, allergens: null, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
      { name: 'Steak', description: null, category: 'Mains', image_url: null, allergens: null, prices: { uber_eats: 1500, deliveroo: 1500, takeaway: 1500, direct: null } },
    ]
    renderWithIntl(<BasketSimulator menuItems={multiCat} listings={listings} phone={null} />)
    expect(screen.getByText('Starters')).toBeInTheDocument()
    expect(screen.getByText('Mains')).toBeInTheDocument()
  })

  // The "direct-fee-savings" bar inside BasketSimulator was removed in the detail-page
  // redesign — the per-platform DELIVERY FEES list (with direct-savings) now lives on
  // app/restaurant/[id]/page.tsx. Tests for that removed bar were dropped accordingly.
})
