import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StickyOrderBar from '../components/StickyOrderBar'

describe('StickyOrderBar', () => {
  it('renders nothing when platform is null', () => {
    const { container } = render(
      <StickyOrderBar platform={null} total={648} platformUrl="https://example.com" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when total is null', () => {
    const { container } = render(
      <StickyOrderBar platform="uber_eats" total={null} platformUrl="https://example.com" />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders platform name and total', () => {
    render(
      <StickyOrderBar platform="uber_eats" total={648} platformUrl="https://example.com" />
    )
    expect(screen.getByText('Order on Uber Eats')).toBeInTheDocument()
    expect(screen.getByText('€6.48')).toBeInTheDocument()
  })

  it('renders as a link when platformUrl is provided', () => {
    render(
      <StickyOrderBar platform="deliveroo" total={768} platformUrl="https://deliveroo.be/test" />
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', 'https://deliveroo.be/test')
  })

  it('renders as non-interactive div when platformUrl is null', () => {
    render(
      <StickyOrderBar platform="takeaway" total={500} platformUrl={null} />
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Order on Takeaway')).toBeInTheDocument()
  })
})
