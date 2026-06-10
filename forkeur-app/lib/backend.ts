export const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000'

/**
 * Server-side fetch to the FastAPI backend. ISR-friendly: callers pass a
 * revalidate window. Throws on non-OK so callers fail loudly (matching the old
 * `if (error) throw` Supabase behavior).
 */
export async function backendFetch<T>(
  path: string,
  init?: RequestInit & { revalidate?: number }
): Promise<T> {
  const { revalidate, ...rest } = init ?? {}
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...rest,
    next: revalidate != null ? { revalidate } : undefined,
  })
  if (!res.ok) throw new Error(`backend ${res.status}: ${path}`)
  return res.json() as Promise<T>
}
