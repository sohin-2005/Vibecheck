import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { get, type Survival as SurvivalData } from '../api/client'
import { SimpleBarChart, WithTable } from '../components/charts'
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader, Td, Th } from '../components/ui'
import { useFilters } from '../lib/filters'
import { fmtDate, fmtInt, fmtPct } from '../lib/format'

export default function Survival() {
  const { filters } = useFilters()
  const [groupBy, setGroupBy] = useState<'project' | 'file_ext'>('project')
  const q = useQuery({
    queryKey: ['survival', filters, groupBy],
    queryFn: () => get<SurvivalData>('/survival', { ...filters, group_by: groupBy }),
  })

  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const d = q.data!
  const byDays = Object.fromEntries(d.checkpoints.map((c) => [c.days, c]))

  return (
    <div>
      <PageHeader
        title="Code survival"
        subtitle="Of the lines AI-linked commits added, how many still exist on your default branch after 1, 7 and 30 days (git blame, whitespace ignored, renames followed)."
      />
      {!d.checkpoints.length ? (
        <Card>
          <Empty>
            No survival data yet. It needs AI-linked commits that are at least a day old. Run <code>promptlens git</code> then{' '}
            <code>promptlens analyze</code>.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[1, 7, 30].map((days) => {
              const c = byDays[days]
              return (
                <Kpi
                  key={days}
                  label={`After ${days} day${days > 1 ? 's' : ''}`}
                  value={fmtPct(c?.rate)}
                  hint={
                    c
                      ? `${fmtInt(c.lines_surviving)} of ${fmtInt(c.lines_total)} lines · ${c.commits} commits${c.not_merged ? ` · ${c.not_merged} never merged` : ''}`
                      : 'Not due yet'
                  }
                />
              )
            })}
          </div>

          <Card
            className="mt-4"
            title={groupBy === 'project' ? 'Survival by project' : 'Survival by file type'}
            subtitle="7-day survival rate. Deleted code can mean a feature was removed, not that the code was bad."
            right={
              <select
                aria-label="Group by"
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value as typeof groupBy)}
                className="rounded-lg border border-line bg-surface px-2 py-1 text-sm"
              >
                <option value="project">By project</option>
                <option value="file_ext">By file type</option>
              </select>
            }
          >
            <WithTable
              rows={d.groups}
              columns={[
                { key: 'key', label: groupBy === 'project' ? 'Project' : 'Extension' },
                { key: 'd1', label: '1 day', format: (v: number | null) => fmtPct(v) },
                { key: 'd7', label: '7 days', format: (v: number | null) => fmtPct(v) },
                { key: 'd30', label: '30 days', format: (v: number | null) => fmtPct(v) },
                { key: 'lines_d7', label: 'Lines (7d)', format: (v: number | null) => fmtInt(v) },
              ]}
            >
              <SimpleBarChart
                data={d.groups.slice(0, 12)}
                x="key"
                horizontal
                height={Math.max(160, d.groups.slice(0, 12).length * 34)}
                yFormat={(v) => `${v}%`}
                series={[{ key: 'd7', label: '7-day survival', color: 'var(--series-1)', format: (v) => fmtPct(v) }]}
              />
            </WithTable>
          </Card>

          <Card className="mt-4" title="Lowest-survival commits (7 days)">
            {d.lowest_commits.length ? (
              <div className="-mx-5 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line">
                      <Th>Commit</Th>
                      <Th>Project</Th>
                      <Th>Date</Th>
                      <Th className="text-right">Lines</Th>
                      <Th className="text-right">Survived</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.lowest_commits.map((c) => (
                      <tr key={c.sha} className="border-b border-line last:border-0">
                        <Td>
                          <code className="text-xs text-ink-3">{c.sha.slice(0, 8)}</code> {c.subject}
                        </Td>
                        <Td>{c.project}</Td>
                        <Td className="whitespace-nowrap">{fmtDate(c.authored_at)}</Td>
                        <Td className="num text-right">{fmtInt(c.lines_total)}</Td>
                        <Td className="num text-right">{fmtPct(c.survival_7d)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>No commits have reached the 7-day checkpoint.</Empty>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
