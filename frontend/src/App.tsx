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

const today = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

export default function App() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="mx-auto min-h-screen max-w-[1240px] px-4 pb-16 sm:px-8">
      <header className="pt-7">
        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-rule pb-3">
          <div className="flex items-baseline gap-4">
            <span className="serif text-[26px] leading-none tracking-tight">PromptLens</span>
            <span className="hidden text-[13px] text-ink-3 italic serif sm:inline">a ledger of your AI-assisted coding</span>
          </div>
          <div className="flex items-baseline gap-4 text-[12px] text-ink-3">
            <span className="hidden md:inline">{today}</span>
            <span role="group" aria-label="Theme" className="flex gap-2">
              {(['system', 'light', 'dark'] as Theme[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  aria-pressed={theme === t}
                  onClick={() => setTheme(t)}
                  className={theme === t ? 'text-ink underline underline-offset-4' : 'hover:text-ink'}
                >
                  {t === 'system' ? 'Auto' : t[0].toUpperCase() + t.slice(1)}
                </button>
              ))}
            </span>
          </div>
        </div>
        <nav className="flex gap-6 overflow-x-auto overflow-y-hidden border-b border-line" aria-label="Sections">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `-mb-px whitespace-nowrap border-b-2 py-3 text-[14px] transition-colors ${
                  isActive ? 'border-accent text-ink' : 'border-transparent text-ink-2 hover:text-ink'
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="py-4">
          <FilterBar />
        </div>
      </header>
      <main className="pt-4">
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
      <footer className="mt-16 border-t border-line pt-4 text-[12px] text-ink-3">
        Local data only. Costs are API-equivalent estimates; insights are correlations, not causes.
      </footer>
    </div>
  )
}
