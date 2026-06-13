export const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000'

/** Default request timeout (ms) for backend calls. Override per-call via `init.timeout`. */
const DEFAULT_TIMEOUT_MS = 10_000

/**
 * Server-side fetch to the FastAPI backend. ISR-friendly: callers pass a
 * revalidate window. Throws on non-OK so callers fail loudly (matching the old
 * `if (error) throw` Supabase behavior).
 *
 * Requests are bounded by a timeout (default 10s, override via `init.timeout`)
 * using AbortSignal — a hung backend now throws instead of stalling the render,
 * surfacing to the nearest error.tsx boundary. No retries by design.
 */
export async function backendFetch<T>(
  path: string,
  init?: RequestInit & { revalidate?: number; timeout?: number }
): Promise<T> {
  const { revalidate, timeout, signal, ...rest } = init ?? {}
  const timeoutMs = timeout ?? DEFAULT_TIMEOUT_MS

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  // If the caller passed their own signal, abort our request when theirs aborts.
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      ...rest,
      signal: controller.signal,
      next: revalidate != null ? { revalidate } : undefined,
    })
    if (!res.ok) throw new Error(`backend ${res.status}: ${path}`)
    return (await res.json()) as T
  } catch (err) {
    // A caller-provided AbortError is genuine cancellation; our own timeout is a
    // distinct failure mode the error boundary should surface clearly.
    if (err instanceof Error && err.name === 'AbortError' && !signal?.aborted) {
      throw new Error(`backend timeout after ${timeoutMs}ms: ${path}`)
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}
