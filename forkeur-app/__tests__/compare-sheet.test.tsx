import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NextIntlClientProvider } from 'next-intl'
import CompareSheet from '../components/CompareSheet'
import type { Platform } from '../lib/basket'
import en from '../messages/en.json'

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

const fullCoverages = {
  uber_eats: { priced: 3, total: 3, complete: true },
  deliveroo: { priced: 3, total: 3, complete: true },
  takeaway: { priced: 3, total: 3, complete: true },
  direct: null,
}

const baseProps = {
  cheapestPlatform: 'uber_eats' as Platform,
  total: 648,
  eta: '18 min',
  savingsCents: 120,
  platformUrl: 'https://ubereats.com/test',
  sortedByTotal: [
    { platform: 'uber_eats' as Platform, total: 648, eta: '18 min' },
    { platform: 'takeaway' as Platform, total: 767, eta: '25 min' },
    { platform: 'deliveroo' as Platform, total: 789, eta: '22 min' },
  ],
  coverages: fullCoverages,
  onClose: vi.fn(),
}

describe('CompareSheet', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders winner platform name', () => {
    renderWithIntl(<CompareSheet {...baseProps} />)
    expect(screen.getAllByText('Uber Eats').length).toBeGreaterThan(0)
  })

  it('renders total, eta, and savings', () => {
    renderWithIntl(<CompareSheet {...baseProps} />)
    expect(screen.getAllByText('€6.48').length).toBeGreaterThan(0)
    expect(screen.getAllByText('18 min').length).toBeGreaterThan(0)
    expect(screen.getByText('€1.20')).toBeInTheDocument()
  })

  it('does not render savings when savingsCents is null', () => {
    renderWithIntl(<CompareSheet {...baseProps} savingsCents={null} />)
    expect(screen.queryByText(/you save/i)).toBeNull()
  })

  it('renders Best badge on winner row', () => {
    renderWithIntl(<CompareSheet {...baseProps} />)
    expect(screen.getByText('Best')).toBeInTheDocument()
  })

  it('renders all 3 platform rows', () => {
    renderWithIntl(<CompareSheet {...baseProps} />)
    const uberEatsElements = screen.getAllByText('Uber Eats')
    const takeawayElements = screen.getAllByText('Takeaway')
    const deliverooElements = screen.getAllByText('Deliveroo')
    expect(uberEatsElements.length).toBeGreaterThan(0)
    expect(takeawayElements.length).toBeGreaterThan(0)
    expect(deliverooElements.length).toBeGreaterThan(0)
  })

  it('CTA links to platformUrl and opens in new tab', () => {
    renderWithIntl(<CompareSheet {...baseProps} />)
    const link = screen.getByRole('link', { name: /order on uber eats/i })
    expect(link).toHaveAttribute('href', 'https://ubereats.com/test')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('CTA is a non-link button when platformUrl is null', () => {
    renderWithIntl(<CompareSheet {...baseProps} platformUrl={null} />)
    expect(screen.queryByRole('link', { name: /order on uber eats/i })).toBeNull()
    const orderButtons = screen.getAllByText(/Order on Uber Eats/)
    expect(orderButtons.length).toBeGreaterThan(0)
  })

  it('calls onClose when backdrop clicked', async () => {
    const onClose = vi.fn()
    renderWithIntl(<CompareSheet {...baseProps} onClose={onClose} />)
    await userEvent.click(screen.getByTestId('sheet-backdrop'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
