import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { NextIntlClientProvider } from 'next-intl'
import HomepageClient from '../components/HomepageClient'
import type { RestaurantSummary } from '../lib/queries'
import en from '../messages/en.json'

vi.mock('../components/MapView', () => ({
  default: () => <div data-testid="map-view" />,
}))

vi.mock('../components/LangToggle', () => ({
  default: () => <div />,
}))

function renderWithIntl(ui: React.ReactElement) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  )
}

const makeRestaurant = (overrides: Partial<RestaurantSummary> & { id: string; name: string }): RestaurantSummary => ({
  id: overrides.id,
  name: overrides.name,
  cuisine: overrides.cuisine ?? [],
  neighborhood: null,
  lat: null,
  lng: null,
  order_url: null,
  image_url: null,
  rating: null,
  direct_url_type: null,
  listings: [],
  cheapest: null,
  ...overrides,
})

const restaurants: RestaurantSummary[] = [
  makeRestaurant({ id: '1', name: 'Pizza Palace', cuisine: ['Pizza'] }),
  makeRestaurant({ id: '2', name: 'Sushi House', cuisine: ['Asian'] }),
  makeRestaurant({ id: '3', name: 'Burger Barn', cuisine: ['Burgers'] }),
]

const cuisines = ['Pizza', 'Asian', 'Burgers']

describe('HomepageClient', () => {
  it('renders all restaurants initially', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    expect(screen.getByText('Pizza Palace')).toBeInTheDocument()
    expect(screen.getByText('Sushi House')).toBeInTheDocument()
    expect(screen.getByText('Burger Barn')).toBeInTheDocument()
  })

  it('filters by search text', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.change(screen.getByPlaceholderText('Search a restaurant'), {
      target: { value: 'pizza' },
    })
    expect(screen.getByText('Pizza Palace')).toBeInTheDocument()
    expect(screen.queryByText('Sushi House')).toBeNull()
    expect(screen.queryByText('Burger Barn')).toBeNull()
  })

  it('shows result count when search active', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.change(screen.getByPlaceholderText('Search a restaurant'), {
      target: { value: 'pizza' },
    })
    expect(screen.getByText('1 result')).toBeInTheDocument()
  })

  it('shows no results message when search matches nothing', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.change(screen.getByPlaceholderText('Search a restaurant'), {
      target: { value: 'zzznomatch' },
    })
    expect(screen.getByText('No restaurants found')).toBeInTheDocument()
  })

  it('clears search when ✕ button clicked', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    const input = screen.getByPlaceholderText('Search a restaurant')
    fireEvent.change(input, { target: { value: 'pizza' } })
    fireEvent.click(screen.getByText('✕'))
    expect(screen.getByText('Sushi House')).toBeInTheDocument()
  })

  it('filters by cuisine pill', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.click(screen.getByText('Asian'))
    expect(screen.getByText('Sushi House')).toBeInTheDocument()
    expect(screen.queryByText('Pizza Palace')).toBeNull()
    expect(screen.queryByText('Burger Barn')).toBeNull()
  })

  it('deselects cuisine when same pill clicked again', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.click(screen.getByText('Asian'))
    fireEvent.click(screen.getByText('Asian'))
    expect(screen.getByText('Pizza Palace')).toBeInTheDocument()
    expect(screen.getByText('Sushi House')).toBeInTheDocument()
  })

  it('All pill resets cuisine filter', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.click(screen.getByText('Asian'))
    fireEvent.click(screen.getByText('All'))
    expect(screen.getByText('Pizza Palace')).toBeInTheDocument()
    expect(screen.getByText('Burger Barn')).toBeInTheDocument()
  })

  it('renders cuisine pills from prop', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    expect(screen.getByText('Pizza')).toBeInTheDocument()
    expect(screen.getByText('Asian')).toBeInTheDocument()
    expect(screen.getByText('Burgers')).toBeInTheDocument()
  })

  it('switches to map view when Map button clicked', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.click(screen.getByText('Map'))
    expect(screen.getByTestId('map-view')).toBeInTheDocument()
  })

  it('switches back to list view when List button clicked', () => {
    renderWithIntl(<HomepageClient restaurants={restaurants} cuisines={cuisines} />)
    fireEvent.click(screen.getByText('Map'))
    fireEvent.click(screen.getByText('List'))
    expect(screen.getByText('Pizza Palace')).toBeInTheDocument()
    expect(screen.queryByTestId('map-view')).toBeNull()
  })
})
