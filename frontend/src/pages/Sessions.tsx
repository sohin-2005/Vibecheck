import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { get, type SessionPage } from '../api/client'
import { Button, Card, Empty, ErrorBox, Loading, PageHeader, StruggleBadge, Td, Th } from '../components/ui'
import { useFilters } from '../lib/filters'
import { fmtCompact, fmtDateTime, fmtMinutes, fmtUsd } from '../lib/format'

type Sort = 'started_at' | 'struggle_score' | 'cost' | 'turns' | 'tokens'

const COLS: { key: Sort | null; label: string; right?: boolean }[] = [
  { key: 'started_at', label: 'Started' },
  { key: null, label: 'Session' },
  { key: 'turns', label: 'Prompts', right: true },
  { key: null, label: 'Active', right: true },
  { key: 'tokens', label: 'Tokens', right: true },
  { key: 'cost', label: 'Cost', right: true },
  { key: 'struggle_score', label: 'Struggle' },
  { key: null, label: 'Committed' },
]

export default function Sessions() {
  const { filters } = useFilters()
  const [sort, setSort] = useState<Sort>('started_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [committed, setCommitted] = useState<'' | 'true' | 'false'>('')
  const [page, setPage] = useState(1)
  const params = { ...filters, sort, order, page, page_size: 50, has_commit: committed || undefined }
  const q = useQuery({
    queryKey: ['sessions', params],
    queryFn: () => get<SessionPage>('/sessions', params),
    placeholderData: keepPreviousData,
  })

  const onSort = (k: Sort) => {
    if (k === sort) setOrder(order === 'desc' ? 'asc' : 'desc')
    else {
      setSort(k)
      setOrder('desc')
    }
    setPage(1)
  }

  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1

  return (
    <div>
      <PageHeader
        title="Sessions"
        subtitle="Sort by struggle score to find the sessions that went badly."
        right={
          <select
            aria-label="Filter by commit"
            value={committed}
            onChange={(e) => {
              setCommitted(e.target.value as typeof committed)
              setPage(1)
            }}
            className="border border-line bg-surface px-2 py-1 text-[13px] text-ink"
          >
            <option value="">All sessions</option>
            <option value="true">With a commit</option>
            <option value="false">Without a commit</option>
          </select>
        }
      />
      <Card>
        {q.isLoading ? (
          <Loading />
        ) : q.error ? (
          <ErrorBox error={q.error} />
        ) : !q.data!.items.length ? (
          <Empty>No sessions match these filters.</Empty>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="border-b border-line">
                  <tr>
                    {COLS.map((c) => (
                      <Th key={c.label} className={c.right ? 'text-right' : ''}>
                        {c.key ? (
                          <button
                            type="button"
                            onClick={() => onSort(c.key!)}
                            className={`uppercase tracking-[0.08em] hover:text-ink ${sort === c.key ? "text-ink" : ""}`}
                          >
                            {c.label}
                            {sort === c.key ? (order === 'desc' ? ' ↓' : ' ↑') : ''}
                          </button>
                        ) : (
                          c.label
                        )}
                      </Th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {q.data!.items.map((s) => (
                    <tr key={s.id} className="border-b border-line last:border-0 hover:bg-surface-2">
                      <Td className="num whitespace-nowrap text-ink-2">{fmtDateTime(s.started_at)}</Td>
                      <Td>
                        <Link to={`/sessions/${s.id}`} className="font-medium hover:underline">
                          {s.title || s.id.slice(0, 8)}
                        </Link>
                        <div className="text-xs text-ink-3">{s.project ?? 'unknown project'}</div>
                      </Td>
                      <Td className="num text-right">{s.human_turns}</Td>
                      <Td className="num text-right whitespace-nowrap">{fmtMinutes(s.active_minutes)}</Td>
                      <Td className="num text-right">{fmtCompact(s.input_tokens + s.output_tokens)}</Td>
                      <Td className="num text-right">{fmtUsd(s.cost_usd)}</Td>
                      <Td>
                        <StruggleBadge score={s.struggle_score} />
                      </Td>
                      <Td>{s.has_commit ? 'Yes' : <span className="text-ink-3">No</span>}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex items-center justify-between text-sm text-ink-2">
              <span>
                {q.data!.total} sessions · page {page} of {pages}
              </span>
              <div className="flex gap-2">
                <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
