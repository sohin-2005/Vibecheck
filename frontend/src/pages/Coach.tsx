import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { get, type CoachPrompt, type CoachSummary, type Insight } from '../api/client'
import { SimpleBarChart, TimeLineChart, WithTable } from '../components/charts'
import PromptRewrite from '../components/PromptRewrite'
import { Button, Card, Empty, ErrorBox, Kpi, Loading, PageHeader, Pill } from '../components/ui'
import { useFilters } from '../lib/filters'
import { fmtDateTime, fmtPct } from '../lib/format'

const CATEGORIES = ['bugfix', 'feature', 'refactor', 'explain', 'test', 'other']

export default function Coach() {
  const { filters } = useFilters()
  const [category, setCategory] = useState('')
  const [weakOnly, setWeakOnly] = useState(false)
  const [page, setPage] = useState(1)
  const summary = useQuery({ queryKey: ['coach', filters], queryFn: () => get<CoachSummary>('/coach/summary', filters) })
  const insights = useQuery({ queryKey: ['insights'], queryFn: () => get<Insight[]>('/insights') })
  const params = { ...filters, category: category || undefined, max_specificity: weakOnly ? 2 : undefined, page, page_size: 25 }
  const prompts = useQuery({
    queryKey: ['coach-prompts', params],
    queryFn: () => get<{ total: number; items: CoachPrompt[] }>('/coach/prompts', params),
    placeholderData: keepPreviousData,
  })

  if (summary.isLoading) return <Loading />
  if (summary.error) return <ErrorBox error={summary.error} />
  const s = summary.data!
  const dist = Object.entries(s.specificity_distribution).map(([k, v]) => ({ specificity: k, prompts: v }))
  const pages = prompts.data ? Math.max(1, Math.ceil(prompts.data.total / 25)) : 1

  return (
    <div>
      <PageHeader title="Prompt coach" subtitle={`How specific and well-scoped your prompts are, with better versions of the vague ones. Rubric ${s.rubric_version}.`} />
      {s.scored === 0 && (
        <div className="mb-8 border-l-2 border-accent py-1 pl-4 text-sm text-ink-2">
          None of your {s.prompts} prompts have LLM scores yet. Run <code>promptlens coach</code> with Ollama running, or
          start it from <Link className="underline" to="/settings">Settings</Link>. Rule-based stats below work without it.
        </div>
      )}
      <div className="grid grid-cols-2 border-y border-rule lg:grid-cols-5">
        <Kpi label="Prompts" value={s.prompts} hint={`${s.scored} scored by LLM`} />
        <Kpi label="Avg specificity" value={s.avg_specificity?.toFixed(2) ?? '—'} hint="1 = vague, 5 = precise" />
        <Kpi label="With context" value={fmtPct(s.pct_context ?? s.features.pct_mentions_file)} hint={s.pct_context == null ? 'Rule-based: mentions a file' : 'Files, errors or code'} />
        <Kpi label="With success criteria" value={fmtPct(s.pct_success_criteria ?? s.features.pct_success_criteria)} hint="States what done looks like" />
        <Kpi label="Median length" value={s.features.median_chars ?? '—'} hint="characters" />
      </div>

      <div className="mt-12 grid gap-x-12 gap-y-12 lg:grid-cols-2">
        <Card title="Specificity distribution" subtitle="LLM-scored prompts only.">
          {s.scored ? (
            <SimpleBarChart data={dist} x="specificity" series={[{ key: 'prompts', label: 'Prompts', color: 'var(--series-1)' }]} height={220} />
          ) : (
            <Empty>No scored prompts yet.</Empty>
          )}
        </Card>
        <Card title="Habits over time" subtitle="Share of prompts per week.">
          {s.weekly.length ? (
            <WithTable
              rows={s.weekly}
              columns={[
                { key: 'week', label: 'Week' },
                { key: 'prompts', label: 'Prompts' },
                { key: 'pct_context', label: 'Context', format: (v: number | null) => fmtPct(v) },
                { key: 'pct_success_criteria', label: 'Success criteria', format: (v: number | null) => fmtPct(v) },
                { key: 'avg_specificity', label: 'Avg specificity', format: (v: number | null) => v?.toFixed(2) ?? '—' },
              ]}
            >
              <TimeLineChart
                data={s.weekly}
                x="week"
                height={220}
                yDomain={[0, 100]}
                yFormat={(v) => `${v}%`}
                series={[
                  { key: 'pct_context', label: 'With context', color: 'var(--series-1)', format: (v) => fmtPct(v) },
                  { key: 'pct_success_criteria', label: 'With success criteria', color: 'var(--series-2)', format: (v) => fmtPct(v) },
                ]}
              />
            </WithTable>
          ) : (
            <Empty>No prompts yet.</Empty>
          )}
        </Card>
      </div>

      <Card className="mt-12" title="Insights" subtitle="Correlations, not causes. Each needs at least 10 sessions per group.">
        {insights.data?.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {insights.data.map((i) => (
              <div key={i.id} className="border-t border-line pt-3">
                <p className="serif text-[16px] leading-snug">{i.title}</p>
                {Array.isArray(i.detail.ci95_diff) && (
                  <p className="mt-1 text-xs text-ink-3">
                    95% interval for the difference in medians: {(i.detail.ci95_diff as number[]).join(' to ')}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty>Not enough sessions yet for any comparison.</Empty>
        )}
      </Card>

      <Card
        className="mt-12"
        title="Your prompts"
        right={
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <select
              aria-label="Category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value)
                setPage(1)
              }}
              className="border border-line bg-surface px-2 py-1 text-[13px] text-ink"
            >
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-ink-2">
              <input
                type="checkbox"
                checked={weakOnly}
                onChange={(e) => {
                  setWeakOnly(e.target.checked)
                  setPage(1)
                }}
              />
              Vague only (≤ 2)
            </label>
          </div>
        }
      >
        {prompts.isLoading ? (
          <Loading />
        ) : !prompts.data?.items.length ? (
          <Empty>No prompts match.</Empty>
        ) : (
          <>
            <ul className="divide-y divide-line">
              {prompts.data.items.map((p) => (
                <li key={p.message_id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3">
                    <span>{fmtDateTime(p.timestamp)}</span>
                    <Link to={`/sessions/${p.session_id}`} className="hover:underline">
                      session
                    </Link>
                    {p.specificity != null && <Pill tone="accent">specificity {p.specificity}/5</Pill>}
                    {p.category && <Pill>{p.category}</Pill>}
                    {p.scope === 'too_large' && <Pill tone="error">too large</Pill>}
                  </div>
                  <p className="mt-1 line-clamp-3 text-sm break-words whitespace-pre-wrap">{p.text}</p>
                  {p.suggestion && <p className="mt-1 text-sm text-ink-2">→ {p.suggestion}</p>}
                  <PromptRewrite prompt={p} />
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center justify-between text-sm text-ink-2">
              <span>
                {prompts.data.total} prompts · page {page} of {pages}
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
