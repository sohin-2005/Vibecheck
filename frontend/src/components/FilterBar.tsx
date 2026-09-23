import { useQuery } from '@tanstack/react-query'
import { get, type Project } from '../api/client'
import { useFilters } from '../lib/filters'

const PRESETS: { label: string; days: number | null }[] = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: 'All', days: null },
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
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <div className="flex overflow-hidden rounded-lg border border-line bg-surface" role="group" aria-label="Date range">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            aria-pressed={activePreset === p}
            className={`px-2.5 py-1.5 ${activePreset === p ? 'bg-surface-2 font-medium text-ink' : 'text-ink-2 hover:text-ink'}`}
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
      <label className="flex items-center gap-1 text-ink-2">
        <span className="sr-only">From</span>
        <input
          type="date"
          value={filters.from ?? ''}
          onChange={(e) => setFilters({ ...filters, from: e.target.value || undefined })}
          className="rounded-lg border border-line bg-surface px-2 py-1 text-ink"
        />
      </label>
      <span className="text-ink-3">to</span>
      <label className="flex items-center gap-1 text-ink-2">
        <span className="sr-only">To</span>
        <input
          type="date"
          value={filters.to ?? ''}
          onChange={(e) => setFilters({ ...filters, to: e.target.value || undefined })}
          className="rounded-lg border border-line bg-surface px-2 py-1 text-ink"
        />
      </label>
      <select
        aria-label="Project"
        value={filters.project_id ?? ''}
        onChange={(e) => setFilters({ ...filters, project_id: e.target.value ? Number(e.target.value) : undefined })}
        className="rounded-lg border border-line bg-surface px-2 py-1.5 text-ink"
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
