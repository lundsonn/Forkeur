import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PlatformPriceRow from '../components/PlatformPriceRow'
import type { MenuItemWithPrices } from '../lib/queries'

const item: MenuItemWithPrices = {
  name: 'Margherita',
  description: 'San Marzano, fior di latte',
  category: 'Pizza',
  image_url: null,
  prices: { uber_eats: 950, deliveroo: 940, takeaway: 960 },
}

describe('PlatformPriceRow', () => {
  it('shows + button when qty is 0', () => {
    render(<PlatformPriceRow item={item} qty={0} onAdd={vi.fn()} onRemove={vi.fn()} />)
    expect(screen.getByRole('button', { name: /add margherita/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).toBeNull()
  })

  it('shows stepper when qty ≥ 1', () => {
    render(<PlatformPriceRow item={item} qty={2} onAdd={vi.fn()} onRemove={vi.fn()} />)
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add margherita/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /remove margherita/i })).toBeInTheDocument()
  })

  it('calls onAdd when + clicked', async () => {
    const onAdd = vi.fn()
    render(<PlatformPriceRow item={item} qty={1} onAdd={onAdd} onRemove={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /add margherita/i }))
    expect(onAdd).toHaveBeenCalledOnce()
  })

  it('calls onRemove when − clicked', async () => {
    const onRemove = vi.fn()
    render(<PlatformPriceRow item={item} qty={1} onAdd={vi.fn()} onRemove={onRemove} />)
    await userEvent.click(screen.getByRole('button', { name: /remove margherita/i }))
    expect(onRemove).toHaveBeenCalledOnce()
  })

  it('item name is bolder when qty ≥ 1', () => {
    const { rerender } = render(
      <PlatformPriceRow item={item} qty={0} onAdd={vi.fn()} onRemove={vi.fn()} />
    )
    const nameEl0 = screen.getByText('Margherita')
    expect(nameEl0).not.toHaveClass('font-bold')

    rerender(<PlatformPriceRow item={item} qty={1} onAdd={vi.fn()} onRemove={vi.fn()} />)
    const nameEl1 = screen.getByText('Margherita')
    expect(nameEl1).toHaveClass('font-bold')
  })
})
