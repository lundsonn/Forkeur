import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import MenuBrowser from '../components/MenuBrowser'
import en from '../messages/en.json'
import type { Platform } from '../lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

vi.mock('next/image', () => ({
  default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

function makeListing(platform: Platform, feeCents: number | null = 199): PlatformListing {
  return {
    id: `${platform}-1`,
    platform,
    platform_url: `https://${platform}.com/r`,
    url_type: null,
    delivery_fee_cents: feeCents,
    delivery_fee_label: feeCents !== null ? `€${(feeCents / 100).toFixed(2)}` : null,
    min_order_cents: null,
    min_order_label: null,
    eta_label: '~25 min',
    rating: 4.5,
    last_scraped_at: new Date().toISOString(),
    promotions: [],
    is_available: true,
    opening_hours: null,
  }
}

function makeMenuItem(name: string, prices: Partial<Record<Platform, number | null>> = {}): MenuItemWithPrices {
  return {
    name,
    description: null,
    category: 'Mains',
    image_url: null,
    allergens: [],
    prices: { uber_eats: null, deliveroo: null, takeaway: null, direct: null, ...prices },
  }
}

const staticProps = {
  menuItems: [
    makeMenuItem('Margherita', { uber_eats: 1200, deliveroo: 1300 }),
    makeMenuItem('Pepperoni', { uber_eats: 1400 }),
  ],
  listings: [makeListing('uber_eats'), makeListing('deliveroo')],
  basket: [],
}

let onAdd: ReturnType<typeof vi.fn>
let onRemove: ReturnType<typeof vi.fn>
let onSwitchToCompare: ReturnType<typeof vi.fn>

beforeEach(() => {
  onAdd = vi.fn()
  onRemove = vi.fn()
  onSwitchToCompare = vi.fn()
})

const makeDefaultProps = () => ({ ...staticProps, onAdd, onRemove, onSwitchToCompare })

describe('MenuBrowser', () => {
  it('renders menu items grouped by category', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    expect(screen.getByText('Margherita')).toBeInTheDocument()
    expect(screen.getByText('Pepperoni')).toBeInTheDocument()
  })

  it('calls onAdd when + button clicked', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    fireEvent.click(screen.getByLabelText('Add Margherita to basket'))
    expect(onAdd).toHaveBeenCalledWith('Margherita', 'Mains')
  })

  it('calls onRemove when - button clicked and qty > 0', () => {
    const props = { ...makeDefaultProps(), basket: [{ name: 'Margherita', category: 'Mains', qty: 1 }] }
    renderWithIntl(<MenuBrowser {...props} />)
    fireEvent.click(screen.getByLabelText('Remove Margherita from basket'))
    expect(onRemove).toHaveBeenCalledWith('Margherita')
  })

  it('shows float pill when basket has items', () => {
    const props = { ...makeDefaultProps(), basket: [{ name: 'Margherita', category: 'Mains', qty: 2 }] }
    renderWithIntl(<MenuBrowser {...props} />)
    expect(screen.getByTestId('compare-float')).toBeInTheDocument()
    expect(screen.getByTestId('compare-float')).toHaveTextContent('Compare (2)')
  })

  it('hides float pill when basket is empty', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    expect(screen.queryByTestId('compare-float')).not.toBeInTheDocument()
  })

  it('calls onSwitchToCompare when float pill clicked', () => {
    const props = { ...makeDefaultProps(), basket: [{ name: 'Margherita', category: 'Mains', qty: 1 }] }
    renderWithIntl(<MenuBrowser {...props} />)
    fireEvent.click(screen.getByTestId('compare-float'))
    expect(onSwitchToCompare).toHaveBeenCalled()
  })

  it('filters items by search query', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'pepperoni' } })
    expect(screen.getByText('Pepperoni')).toBeInTheDocument()
    expect(screen.queryByText('Margherita')).not.toBeInTheDocument()
  })

  it('opens DishModal when item name is clicked', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    fireEvent.click(screen.getByText('Margherita'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Margherita', { selector: 'h3' })).toBeInTheDocument()
  })

  it('closes DishModal when backdrop is clicked', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    fireEvent.click(screen.getByText('Margherita'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('dish-modal-backdrop'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('DishModal + button calls onAdd', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    fireEvent.click(screen.getByText('Margherita'))
    const modalAddBtn = screen.getAllByLabelText('Add Margherita to basket')
    fireEvent.click(modalAddBtn[modalAddBtn.length - 1])
    expect(onAdd).toHaveBeenCalledWith('Margherita', 'Mains')
  })

  it('DishModal only shows prices for platforms where price is not null', () => {
    renderWithIntl(<MenuBrowser {...makeDefaultProps()} />)
    // Pepperoni only has uber_eats price — click it
    fireEvent.click(screen.getByText('Pepperoni'))
    // should show 'UE' label for uber_eats
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // Deliveroo price is null for Pepperoni — 'DE' label should not appear in modal
    const dialog = screen.getByRole('dialog')
    const priceRows = dialog.querySelectorAll('.flex.items-center.justify-between')
    expect(priceRows).toHaveLength(1) // only uber_eats
  })
})
