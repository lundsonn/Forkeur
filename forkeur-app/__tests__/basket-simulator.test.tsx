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
})

const menuItems: MenuItemWithPrices[] = [
  {
    name: 'Margherita',
    description: 'Classic pizza',
    category: 'Pizzas',
    image_url: null,
    prices: { uber_eats: 899, deliveroo: 950, takeaway: 870, direct: null },
  },
  {
    name: 'Quattro Formaggi',
    description: null,
    category: 'Pizzas',
    image_url: null,
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

  it('renders platform delivery fee labels', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.getByText('Uber Eats')).toBeInTheDocument()
    expect(screen.getByText('Deliveroo')).toBeInTheDocument()
    expect(screen.getByText('Takeaway')).toBeInTheDocument()
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
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    expect(screen.getByText(/1 item/)).toBeInTheDocument()
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
      { name: 'Salad', description: null, category: 'Starters', image_url: null, prices: { uber_eats: 500, deliveroo: 500, takeaway: 500, direct: null } },
      { name: 'Steak', description: null, category: 'Mains', image_url: null, prices: { uber_eats: 1500, deliveroo: 1500, takeaway: 1500, direct: null } },
    ]
    renderWithIntl(<BasketSimulator menuItems={multiCat} listings={listings} phone={null} />)
    expect(screen.getByText('Starters')).toBeInTheDocument()
    expect(screen.getByText('Mains')).toBeInTheDocument()
  })

  it('shows direct fee savings banner when direct listing present but no direct menu items', () => {
    const directListing = makeListing('direct', null)
    directListing.platform_url = 'https://myrestaurant.com/order'
    renderWithIntl(
      <BasketSimulator
        menuItems={menuItems}
        listings={[...listings, directListing]}
        phone={null}
      />
    )
    expect(screen.getByTestId('direct-fee-savings')).toBeInTheDocument()
  })

  it('does not show direct fee savings when no direct listing', () => {
    renderWithIntl(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.queryByTestId('direct-fee-savings')).toBeNull()
  })
})
