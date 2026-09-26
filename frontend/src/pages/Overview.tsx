import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { get, type Insight, type Overview as OverviewData } from '../api/client'
import { SimpleBarChart, TimeLineChart, WithTable } from '../components/charts'
import DigestPanel from '../components/DigestPanel'
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader } from '../components/ui'
import { useFilters } from '../lib/filters'
import { fmtCompact, fmtInt, fmtPct, fmtUsd, shortDay } from '../lib/format'

export default function Overview() {
  const { filters } = useFilters()
  const q = useQuery({ queryKey: ['overview', filters], queryFn: () => get<OverviewData>('/overview', filters) })
  const insights = useQuery({ queryKey: ['insights'], queryFn: () => get<Insight[]>('/insights') })

  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const d = q.data!
  const t = d.totals
  const hasCost = t.cost_usd !== null
  const series = hasCost
    ? { key: 'cost', label: 'API-equivalent cost', color: 'var(--series-1)', format: (v: number) => fmtUsd(v) }
    : { key: 'tokens', label: 'Tokens (in + out)', color: 'var(--series-1)', format: (v: number) => fmtInt(v) }

  return (
    <div>
      <PageHeader title="Overview" subtitle="How much you use AI coding tools, and how it's going." />
      <DigestPanel />
      {t.sessions === 0 ? (
        <Card>
          <Empty>
            No sessions in this range. Run <code>vibecheck ingest</code>, or try <code>vibecheck demo</code>.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 border-y border-rule lg:grid-cols-5">
            <Kpi label="Sessions" value={fmtInt(t.sessions)} hint={`${fmtInt(t.prompts)} prompts`} />
            <Kpi label="Active hours" value={t.active_hours.toFixed(1)} hint="Idle gaps over 30 min excluded" />
            <Kpi
              label="Tokens (in + out)"
              value={fmtCompact(t.input_tokens + t.output_tokens)}
              hint={`+ ${fmtCompact(t.cache_read_tokens + t.cache_write_tokens)} cache`}
            />
            <Kpi
              label="API-equivalent cost"
              value={fmtUsd(t.cost_usd)}
              hint={
                t.unpriced_sessions ? (
                  <span>
                    {t.unpriced_sessions} session(s) unpriced.{' '}
                    <Link className="underline" to="/settings">
                      Add prices
                    </Link>
                  </span>
                ) : (
                  'Not what subscribers pay'
                )
              }
            />
            <Kpi
              label="7-day code survival"
              value={fmtPct(t.survival_7d)}
              hint={`${t.sessions_with_commit} sessions with commits`}
            />
          </div>

          <div className="mt-12 grid gap-x-12 gap-y-12 lg:grid-cols-3">
            <Card
              className="lg:col-span-2"
              title={hasCost ? 'Daily API-equivalent cost' : 'Daily tokens (in + out)'}
              subtitle={hasCost ? undefined : 'Add model prices in config to see cost instead.'}
            >
              <WithTable
                rows={d.daily}
                columns={[
                  { key: 'date', label: 'Date' },
                  { key: 'sessions', label: 'Sessions' },
                  { key: 'tokens', label: 'Tokens', format: (v: number) => fmtInt(v) },
                  { key: 'cost', label: 'Cost', format: (v: number) => fmtUsd(v) },
                ]}
              >
                <TimeLineChart
                  data={d.daily}
                  x="date"
                  series={[series]}
                  labelFormat={shortDay}
                  yFormat={hasCost ? (v) => `$${v}` : fmtCompact}
                />
              </WithTable>
            </Card>
            <Card title="Sessions per project">
              <SimpleBarChart
                data={d.by_project.slice(0, 10)}
                x="project"
                horizontal
                height={Math.max(160, d.by_project.slice(0, 10).length * 34)}
                series={[{ key: 'sessions', label: 'Sessions', color: 'var(--series-1)' }]}
              />
            </Card>
          </div>

          <Card className="mt-12" title="Insights" subtitle="Correlations between your prompting habits and outcomes.">
            {insights.data?.length ? (
              <ul>
                {insights.data.slice(0, 5).map((i) => (
                  <li key={i.id} className="serif border-b border-line py-3 text-[16px] leading-snug last:border-0">
                    {i.title}
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>These appear once each comparison has at least 10 sessions per group. Until then, the digest above is the place to look.</Empty>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
