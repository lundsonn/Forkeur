import { describe, it, expect, vi, afterEach } from 'vitest'
import { backendFetch } from '../lib/backend'

afterEach(() => vi.restoreAllMocks())

describe('backendFetch', () => {
  it('returns parsed JSON on 200', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(JSON.stringify([{ id: '1' }]), { status: 200 })
    ))
    const data = await backendFetch<{ id: string }[]>('/api/public/restaurants')
    expect(data).toEqual([{ id: '1' }])
  })

  it('throws on non-OK status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })))
    await expect(backendFetch('/api/public/deals')).rejects.toThrow('backend 500')
  })
})
