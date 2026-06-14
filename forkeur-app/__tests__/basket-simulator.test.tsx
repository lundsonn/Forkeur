import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import BasketSimulator from '../components/BasketSimulator'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'
import en from '../messages/en.json'

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock('../components/MenuBrowser', () => ({
  default: ({ onAdd }: { onAdd: (name: string, category: string) => void }) => (
    <div data-testid="menu-browser">
      <button data-testid="add-item-btn" onClick={() => onAdd('Margherita', 'Pizzas')}>
        Add
      </button>
    </div>
  ),
}))

vi.mock('../components/CompareDecision', () => ({
  default: () => <div data-testid="compare-decision" />,
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>,
  )
}

const menuItems: MenuItemWithPrices[] = [
  {
    name: 'Margherita',
    description: null,
    category: 'Pizzas',
    image_url: null,
    allergens: [],
    prices: { uber_eats: 899, deliveroo: 950, takeaway: 870, direct: null },
  },
]

const listings: PlatformListing[] = [
  {
    id: 'listing-uber_eats',
    platform: 'uber_eats',
    platform_url: 'https://ubereats.com/test',
    url_type: null,
    delivery_fee_cents: 199,
    delivery_fee_label: '€1.99',
    min_order_cents: null,
    min_order_label: null,
    eta_label: '25–35 min',
    rating: 4.2,
    last_scraped_at: null,
    promotions: [],
    is_available: true,
    opening_hours: null,
  },
]

const defaultProps = {
  menuItems,
  listings,
  phone: null,
  restaurantId: 'test-restaurant',
  matchRate: 1,
}

describe('BasketSimulator', () => {
  it('renders menu and compare tabs', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    expect(screen.getByTestId('tab-menu')).toBeInTheDocument()
    expect(screen.getByTestId('tab-compare')).toBeInTheDocument()
  })

  it('shows MenuBrowser on menu tab by default', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    expect(screen.getByTestId('menu-browser')).toBeInTheDocument()
    expect(screen.queryByTestId('compare-decision')).not.toBeInTheDocument()
  })

  it('switches to CompareDecision on compare tab click', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    fireEvent.click(screen.getByTestId('tab-compare'))
    expect(screen.getByTestId('compare-decision')).toBeInTheDocument()
    expect(screen.queryByTestId('menu-browser')).not.toBeInTheDocument()
  })

  it('shows compare badge after item added', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    expect(screen.queryByTestId('compare-badge')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('add-item-btn'))
    expect(screen.getByTestId('compare-badge')).toBeInTheDocument()
    expect(screen.getByTestId('compare-badge')).toHaveTextContent('1')
  })

  it('badge count increments on multiple adds', () => {
    renderWithIntl(<BasketSimulator {...defaultProps} />)
    fireEvent.click(screen.getByTestId('add-item-btn'))
    fireEvent.click(screen.getByTestId('add-item-btn'))
    fireEvent.click(screen.getByTestId('add-item-btn'))
    expect(screen.getByTestId('compare-badge')).toHaveTextContent('3')
  })
})
