import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BasketSimulator from '../components/BasketSimulator'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

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

describe('BasketSimulator', () => {
  it('basket bar hidden when basket empty', () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('basket bar visible after adding item', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toBeInTheDocument()
  })

  it('basket bar shows item count', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByTestId('basket-bar')).toHaveTextContent('1 item')
  })

  it('removing item decreases stepper qty', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(screen.getByText('2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('removing last item hides basket bar', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(screen.queryByTestId('basket-bar')).toBeNull()
  })

  it('tapping basket bar opens compare sheet', async () => {
    render(<BasketSimulator menuItems={menuItems} listings={listings} phone={null} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    await userEvent.click(screen.getByTestId('basket-bar'))
    expect(screen.getByText('Best right now')).toBeInTheDocument()
  })
})
