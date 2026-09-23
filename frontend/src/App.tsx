import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import FilterBar from './components/FilterBar'
import Coach from './pages/Coach'
import Overview from './pages/Overview'
import SessionDetail from './pages/SessionDetail'
import Sessions from './pages/Sessions'
import Settings from './pages/Settings'
import Survival from './pages/Survival'
import Tools from './pages/Tools'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/sessions', label: 'Sessions' },
  { to: '/survival', label: 'Code survival' },
  { to: '/tools', label: 'Tools' },
  { to: '/coach', label: 'Coach' },
  { to: '/settings', label: 'Settings' },
]

type Theme = 'system' | 'light' | 'dark'

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('promptlens.theme') as Theme) || 'system'
    } catch {
      return 'system'
    }
  })
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try {
      localStorage.setItem('promptlens.theme', theme)
    } catch {
      /* ignore */
    }
  }, [theme])
  return [theme, setTheme]
}

export default function App() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:w-52 md:shrink-0 md:border-r md:border-b-0">
        <div className="flex items-center justify-between px-4 py-4 md:block">
          <div className="flex items-center gap-2">
            <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
              <circle cx="11" cy="11" r="7" fill="none" stroke="var(--accent)" strokeWidth="2.5" />
              <path d="M16 16l5 5" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
            <span className="font-semibold tracking-tight">PromptLens</span>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-3 py-2 text-sm ${
                  isActive ? 'bg-surface-2 font-medium text-ink' : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-4 py-4 md:absolute md:bottom-0 md:block">
          <label className="text-xs text-ink-3">
            Theme
            <select
              value={theme}
              onChange={(e) => setTheme(e.target.value as Theme)}
              className="mt-1 block rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink"
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <div className="mb-6">
          <FilterBar />
        </div>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/sessions/:id" element={<SessionDetail />} />
          <Route path="/survival" element={<Survival />} />
          <Route path="/tools" element={<Tools />} />
          <Route path="/coach" element={<Coach />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
