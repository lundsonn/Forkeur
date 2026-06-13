'use client' // Error boundaries must be Client Components

// global-error.tsx replaces the ENTIRE root layout when the root layout (or
// anything above the route-level error boundary) throws. That means the
// NextIntlClientProvider mounted in app/layout.tsx is NOT present here, so
// next-intl's useTranslations() has no context to read from and would throw.
// For that reason this file intentionally uses plain English fallback copy.
// It also renders its own <html>/<body> and relies on inline styles for the
// stone/white/orange theme, since globals.css (imported by the replaced root
// layout) and Tailwind are not guaranteed to be applied in this fallback.

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          padding: '1.25rem',
          background: '#ffffff',
          color: '#1c1917', // stone-900
          fontFamily:
            'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        <h1
          style={{
            fontSize: '1.5rem',
            fontWeight: 700,
            margin: '0 0 0.5rem',
            color: '#1c1917', // stone-900
          }}
        >
          Something went wrong
        </h1>
        <p
          style={{
            fontSize: '0.875rem',
            color: '#78716c', // stone-500
            maxWidth: '20rem',
            margin: '0 0 1.5rem',
          }}
        >
          The app ran into an unexpected error. Please try again in a moment.
        </p>
        <button
          onClick={() => reset()}
          style={{
            background: '#f97316', // orange-500
            color: '#ffffff',
            fontWeight: 500,
            fontSize: '0.875rem',
            border: 'none',
            borderRadius: '9999px',
            padding: '0.625rem 1.5rem',
            cursor: 'pointer',
          }}
        >
          Try again
        </button>
      </body>
    </html>
  )
}
