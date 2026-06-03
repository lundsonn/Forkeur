import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ClaimForm from '@/components/ClaimForm'

describe('ClaimForm', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })

  it('renders trigger button', () => {
    render(<ClaimForm restaurantId="550e8400-e29b-41d4-a716-446655440000" restaurantName="Pizza Roma" />)
    expect(screen.getByText(/vous êtes le propriétaire/i)).toBeInTheDocument()
  })

  it('shows form on button click', () => {
    render(<ClaimForm restaurantId="550e8400-e29b-41d4-a716-446655440000" restaurantName="Pizza Roma" />)
    fireEvent.click(screen.getByText(/vous êtes le propriétaire/i))
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/url/i)).toBeInTheDocument()
  })

  it('submits form and shows success', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ claim_id: 'c1' }),
    })
    render(<ClaimForm restaurantId="550e8400-e29b-41d4-a716-446655440000" restaurantName="Pizza Roma" />)
    fireEvent.click(screen.getByText(/vous êtes le propriétaire/i))
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText(/url/i), { target: { value: 'https://myrest.com/order' } })
    fireEvent.click(screen.getByRole('button', { name: /envoyer/i }))
    await waitFor(() => expect(screen.getByText(/demande envoyée/i)).toBeInTheDocument())
  })

  it('shows error on failed submit', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: false,
      text: async () => 'Server error',
    })
    render(<ClaimForm restaurantId="550e8400-e29b-41d4-a716-446655440000" restaurantName="Pizza Roma" />)
    fireEvent.click(screen.getByText(/vous êtes le propriétaire/i))
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText(/url/i), { target: { value: 'https://myrest.com/order' } })
    fireEvent.click(screen.getByRole('button', { name: /envoyer/i }))
    await waitFor(() => expect(screen.getByText(/erreur/i)).toBeInTheDocument())
  })
})
