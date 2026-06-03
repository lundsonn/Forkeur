import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const LOGIN_FORM = (error = '') => `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Forkeur Admin</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0 }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f9fafb; display: flex; align-items: center;
           justify-content: center; min-height: 100vh }
    .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 16px;
            padding: 32px; width: 100%; max-width: 360px }
    h1 { font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 4px }
    p  { font-size: 13px; color: #9ca3af; margin-bottom: 24px }
    input { width: 100%; border: 1px solid #e5e7eb; border-radius: 8px;
            padding: 10px 14px; font-size: 14px; outline: none; margin-bottom: 12px }
    input:focus { border-color: #111827; box-shadow: 0 0 0 2px #11182720 }
    button { width: 100%; background: #111827; color: #fff; border: none;
             border-radius: 8px; padding: 10px; font-size: 14px; font-weight: 500;
             cursor: pointer }
    button:hover { background: #374151 }
    .error { font-size: 13px; color: #ef4444; margin-bottom: 12px }
  </style>
</head>
<body>
  <div class="card">
    <h1>Forkeur Admin</h1>
    <p>Enter your password to continue</p>
    <form method="POST" action="/__auth">
      <input type="password" name="password" placeholder="Password" autofocus />
      ${error ? `<p class="error">${error}</p>` : ''}
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>`

function parseCookies(header: string): Record<string, string> {
  return Object.fromEntries(
    header.split(';').map(c => c.trim().split('=').map(decodeURIComponent))
      .filter(([k]) => k).map(([k, ...v]) => [k, v.join('=')])
  )
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const adminPassword = env.VITE_ADMIN_PASSWORD ?? ''
  const cookieToken = Buffer.from(`forkeur:${adminPassword}`).toString('base64')
  const COOKIE = 'fa_session'

  return {
    plugins: [
      react(),
      tailwindcss(),
      {
        name: 'session-auth',
        configureServer(server) {
          server.middlewares.use((req, res, next) => {
            // Pass through WebSocket upgrades and Vite internals
            if (req.headers.upgrade === 'websocket') return next()
            const url = req.url ?? '/'
            if (url.startsWith('/@') || url.startsWith('/node_modules/')) return next()

            // Handle login form POST
            if (req.method === 'POST' && url === '/__auth') {
              let body = ''
              req.on('data', (chunk: Buffer) => { body += chunk.toString() })
              req.on('end', () => {
                const params = new URLSearchParams(body)
                const pw = params.get('password') ?? ''
                if (pw === adminPassword) {
                  res.writeHead(302, {
                    'Set-Cookie': `${COOKIE}=${cookieToken}; HttpOnly; Path=/; SameSite=Strict`,
                    'Location': '/',
                  })
                  res.end()
                } else {
                  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
                  res.end(LOGIN_FORM('Incorrect password'))
                }
              })
              return
            }

            // Check session cookie
            const cookies = parseCookies(req.headers.cookie ?? '')
            if (cookies[COOKIE] === cookieToken) return next()

            // Not authenticated — serve login form
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
            res.end(LOGIN_FORM())
          })
        },
      },
    ],
    server: {
      proxy: {
        '/api': 'http://localhost:8000',
        '/ws': { target: 'ws://localhost:8000', ws: true },
      },
    },
    build: {
      outDir: '../static',
      emptyOutDir: true,
    },
  }
})
