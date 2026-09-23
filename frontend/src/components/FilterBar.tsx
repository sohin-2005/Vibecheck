import { useQuery } from '@tanstack/react-query'
import { get, type Project } from '../api/client'
import { useFilters } from '../lib/filters'
import { selectCls } from './ui'

const PRESETS: { label: string; days: number | null }[] = [
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: 'All time', days: null },
]

const iso = (d: Date) => d.toISOString().slice(0, 10)

export default function FilterBar() {
  const { filters, setFilters } = useFilters()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<Project[]>('/projects') })

  const activePreset = PRESETS.find((p) => {
    if (p.days === null) return !filters.from && !filters.to
    const from = new Date()
    from.setDate(from.getDate() - p.days + 1)
    return filters.from === iso(from) && !filters.to
  })

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px]">
      <span className="label">Period</span>
      <div className="flex gap-3" role="group" aria-label="Date range">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            aria-pressed={activePreset === p}
            className={activePreset === p ? 'text-ink underline decoration-accent decoration-2 underline-offset-4' : 'text-ink-2 hover:text-ink'}
            onClick={() => {
              if (p.days === null) return setFilters({ ...filters, from: undefined, to: undefined })
              const from = new Date()
              from.setDate(from.getDate() - p.days + 1)
              setFilters({ ...filters, from: iso(from), to: undefined })
            }}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2 text-ink-3">
        <input
          type="date"
          aria-label="From"
          value={filters.from ?? ''}
          onChange={(e) => setFilters({ ...filters, from: e.target.value || undefined })}
          className={selectCls}
        />
        <span>to</span>
        <input
          type="date"
          aria-label="To"
          value={filters.to ?? ''}
          onChange={(e) => setFilters({ ...filters, to: e.target.value || undefined })}
          className={selectCls}
        />
      </div>
      <span className="label ml-auto">Project</span>
      <select
        aria-label="Project"
        value={filters.project_id ?? ''}
        onChange={(e) => setFilters({ ...filters, project_id: e.target.value ? Number(e.target.value) : undefined })}
        className={selectCls}
      >
        <option value="">All projects</option>
        {projects.data?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} ({p.sessions})
          </option>
        ))}
      </select>
    </div>
  )
}
