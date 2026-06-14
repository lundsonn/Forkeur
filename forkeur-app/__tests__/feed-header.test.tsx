import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FeedHeader from '../components/FeedHeader'
import type { SortBy } from '../components/FeedHeader'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, params?: Record<string, unknown>) => key,
}))

describe('FeedHeader', () => {
  const defaultProps = {
    neighborhood: 'Ixelles',
    sortBy: 'cheapest' as SortBy,
    onSortChange: vi.fn(),
    onNeighborhoodClick: vi.fn(),
  }

  it('renders neighborhood label when neighborhood is provided', () => {
    render(<FeedHeader {...defaultProps} />)
    expect(screen.getByText('Ixelles')).toBeDefined()
  })

  it('renders fallback label when neighborhood is null', () => {
    render(<FeedHeader {...defaultProps} neighborhood={null} />)
    expect(screen.getByText('feed.allBrussels')).toBeDefined()
  })

  it('cheapest pill has aria-pressed true when sortBy is cheapest', () => {
    render(<FeedHeader {...defaultProps} sortBy="cheapest" />)
    const btn = screen.getByRole('button', { name: 'results.cheapest' })
    expect(btn.getAttribute('aria-pressed')).toBe('true')
  })

  it('fastest pill has aria-pressed true when sortBy is fastest', () => {
    render(<FeedHeader {...defaultProps} sortBy="fastest" />)
    const btn = screen.getByRole('button', { name: 'results.fastest' })
    expect(btn.getAttribute('aria-pressed')).toBe('true')
  })

  it('clicking cheapest pill calls onSortChange with cheapest', async () => {
    const onSortChange = vi.fn()
    render(<FeedHeader {...defaultProps} onSortChange={onSortChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'results.cheapest' }))
    expect(onSortChange).toHaveBeenCalledWith('cheapest')
  })

  it('clicking fastest pill calls onSortChange with fastest', async () => {
    const onSortChange = vi.fn()
    render(<FeedHeader {...defaultProps} onSortChange={onSortChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'results.fastest' }))
    expect(onSortChange).toHaveBeenCalledWith('fastest')
  })

  it('clicking neighborhood button calls onNeighborhoodClick', async () => {
    const onNeighborhoodClick = vi.fn()
    render(<FeedHeader {...defaultProps} onNeighborhoodClick={onNeighborhoodClick} />)
    await userEvent.click(screen.getByRole('button', { name: /Ixelles/ }))
    expect(onNeighborhoodClick).toHaveBeenCalled()
  })
})
