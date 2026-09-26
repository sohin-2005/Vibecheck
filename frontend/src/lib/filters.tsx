import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Filters } from '../api/client'

const KEY = 'vibecheck.filters'

type Ctx = { filters: Filters; setFilters: (f: Filters) => void }

const FiltersContext = createContext<Ctx>({ filters: {}, setFilters: () => {} })

function load(): Filters {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Filters
  } catch {
    return {}
  }
}

export function FiltersProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>(load)
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(filters))
    } catch {
      /* storage unavailable: filters just won't persist */
    }
  }, [filters])
  return <FiltersContext.Provider value={{ filters, setFilters }}>{children}</FiltersContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useFilters = () => useContext(FiltersContext)
