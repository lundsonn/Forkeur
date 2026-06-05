import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/scrapers', label: 'Scrapers' },
  { to: '/history', label: 'History' },
  { to: '/schedule', label: 'Schedule' },
  { to: '/data', label: 'Data' },
  { to: '/claims', label: 'Claims' },
  { to: '/match-queue', label: 'Match Queue' },
  { to: '/restaurants', label: 'Restaurants' },
]

export default function Sidebar() {
  return (
    <aside className="w-52 shrink-0 bg-white border-r border-stone-200 flex flex-col py-6 px-3 min-h-screen">
      <div className="px-3 mb-8">
        <span className="font-bold text-xl tracking-tight text-stone-900">fork</span>
        <span className="font-bold text-xl tracking-tight text-[#E8472A]">eur</span>
        <span className="ml-2 text-xs text-stone-400 font-normal">manager</span>
      </div>
      <nav className="flex flex-col gap-0.5">
        {links.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-stone-100 text-stone-900'
                  : 'text-stone-500 hover:text-stone-900 hover:bg-stone-50'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
