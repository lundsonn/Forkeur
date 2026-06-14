import { render, screen } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import { describe, it, expect, vi } from 'vitest'
import CompareDecision from '../components/CompareDecision'
import en from '../messages/en.json'
import type { Platform, PlatformCoverages } from '../lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '../lib/queries'

vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => <img src={props.src as string} alt={props.alt as string} />,
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

const basket = [{ name: 'Margherita', category: 'Mains', qty: 1 }]
const menuItems = [makeMenuItem('Margherita', { uber_eats: 1200, deliveroo: 1350 })]
const listings = [makeListing('uber_eats', 199), makeListing('deliveroo', 249)]

const totals: Record<Platform, number | null> = {
  uber_eats: 1399,
  deliveroo: 1599,
  takeaway: null,
  direct: null,
}

const coverages: PlatformCoverages = {
  uber_eats: { priced: 1, total: 1, complete: true },
  deliveroo: { priced: 1, total: 1, complete: true },
  takeaway: null,
  direct: null,
}

const defaultProps = {
  basket,
  listings,
  menuItems,
  totals,
  coverages,
  cheapestPlatform: 'uber_eats' as Platform,
  menuDirectSavingsCents: null,
  phone: undefined,
  orderChannel: undefined,
}

describe('CompareDecision', () => {
  it('shows empty state when basket is empty', () => {
    renderWithIntl(<CompareDecision {...defaultProps} basket={[]} />)
    expect(screen.getByText(/add items from the menu tab/i)).toBeInTheDocument()
  })

  it('renders a card for each platform with a non-null total', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('platform-card-uber_eats')).toBeInTheDocument()
    expect(screen.getByTestId('platform-card-deliveroo')).toBeInTheDocument()
    expect(screen.queryByTestId('platform-card-takeaway')).not.toBeInTheDocument()
  })

  it('shows BEST badge on cheapest platform card only', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('best-badge')).toBeInTheDocument()
    expect(screen.getAllByTestId('best-badge')).toHaveLength(1)
    const card = screen.getByTestId('platform-card-uber_eats')
    expect(card).toContainElement(screen.getByTestId('best-badge'))
  })

  it('shows Order CTA only on winner card', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('winner-cta')).toBeInTheDocument()
    expect(screen.getAllByTestId('winner-cta')).toHaveLength(1)
  })

  it('shows delta on non-winner card', () => {
    renderWithIntl(<CompareDecision {...defaultProps} />)
    expect(screen.getByTestId('delta-text')).toBeInTheDocument()
    expect(screen.getByTestId('delta-text')).toHaveTextContent('+')
  })

  it('shows direct savings callout above cards when menuDirectSavingsCents > 0', () => {
    renderWithIntl(<CompareDecision {...defaultProps} menuDirectSavingsCents={300} />)
    const callout = screen.getByTestId('direct-savings')
    expect(callout).toBeInTheDocument()
    expect(callout).toHaveTextContent('Save')
    const cards = screen.getAllByTestId(/^platform-card-/)
    expect(callout.compareDocumentPosition(cards[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('hides direct savings callout when null', () => {
    renderWithIntl(<CompareDecision {...defaultProps} menuDirectSavingsCents={null} />)
    expect(screen.queryByTestId('direct-savings')).not.toBeInTheDocument()
  })

  it('lists missing items for incomplete coverage (up to 2 + N more)', () => {
    const itemsWithMissing = [
      makeMenuItem('Margherita', { uber_eats: 1200, deliveroo: null }),
      makeMenuItem('Pepperoni', { uber_eats: 1400, deliveroo: null }),
      makeMenuItem('Hawaii', { uber_eats: 1300, deliveroo: null }),
    ]
    const basketWithAll = [
      { name: 'Margherita', category: 'Mains', qty: 1 },
      { name: 'Pepperoni', category: 'Mains', qty: 1 },
      { name: 'Hawaii', category: 'Mains', qty: 1 },
    ]
    const coverageWithMissing: PlatformCoverages = {
      uber_eats: { priced: 3, total: 3, complete: true },
      deliveroo: { priced: 0, total: 3, complete: false },
      takeaway: null,
      direct: null,
    }
    const totalsWithMissing: Record<Platform, number | null> = {
      uber_eats: 3900,
      deliveroo: 0,
      takeaway: null,
      direct: null,
    }
    renderWithIntl(
      <CompareDecision
        {...defaultProps}
        basket={basketWithAll}
        menuItems={itemsWithMissing}
        totals={totalsWithMissing}
        coverages={coverageWithMissing}
        cheapestPlatform="uber_eats"
      />,
    )
    const missing = screen.getByTestId('missing-items')
    expect(missing).toHaveTextContent('Missing:')
    expect(missing).toHaveTextContent('+ 1 more')
  })
})
