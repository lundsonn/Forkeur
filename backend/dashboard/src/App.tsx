import { useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Scrapers from './pages/Scrapers'
import History from './pages/History'
import Schedule from './pages/Schedule'
import Data from './pages/Data'
import Login from './pages/Login'

export default function App() {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem('admin_token')
  )

  if (!token) {
    return <Login onLogin={setToken} />
  }

  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-white font-sans">
        <Sidebar />
        <main className="flex-1 p-6 overflow-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/scrapers" element={<Scrapers />} />
            <Route path="/history" element={<History />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/data" element={<Data />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
