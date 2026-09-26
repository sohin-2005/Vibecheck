import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { get } from '../api/client'
import { Card, ErrorBox, Loading, PageHeader, selectCls, Td, Th } from '../components/ui'

type TeamRow = { member: string; week: string; [k: string]: unknown }
type TeamData = { members: string[]; weeks: string[]; rows: TeamRow[] }

const METRICS: { key: string; label: string; unit?: string; help: string }[] = [
  { key: 'sessions', label: 'Sessions', help: 'AI coding sessions started that week' },
  { key: 'active_hours', label: 'Active hours', help: 'Time with activity, idle gaps over 30 min excluded' },
  { key: 'commit_rate', label: 'Sessions ending in a commit', unit: '%', help: 'Share of sessions linked to at least one commit' },
  { key: 'survival_7d', label: '7-day code survival', unit: '%', help: 'AI-written lines still present a week later' },
  { key: 'median_struggle', label: 'Median struggle (raw)', help: 'Lower is smoother; raw points, comparable across people' },
  { key: 'tool_error_rate', label: 'Tool error rate', unit: '%', help: 'Share of tool calls that failed' },
  { key: 'avg_specificity', label: 'Prompt specificity', help: '1-5, LLM-scored prompts only' },
  { key: 'pct_context', label: 'Prompts with context', unit: '%', help: 'Mentions files, errors or code' },
]

function fmt(v: unknown, unit?: string) {
  if (v === null || v === undefined) return '—'
  return `${typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(1)) : String(v)}${unit ?? ''}`
}

export default function Team() {
  const q = useQuery({ queryKey: ['team'], queryFn: () => get<TeamData>('/team') })
  const [metric, setMetric] = useState('sessions')
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const d = q.data!
  const m = METRICS.find((x) => x.key === metric)!
  const weeks = d.weeks.slice(-8)
  const cell = (member: string, week: string) => d.rows.find((r) => r.member === member && r.week === week)?.[metric]

  return (
    <div>
      <PageHeader
        title="Team"
        subtitle="Weekly aggregates shared by teammates. No prompts, code, file paths or commit messages ever leave anyone's machine."
        right={
          d.members.length ? (
            <select aria-label="Metric" value={metric} onChange={(e) => setMetric(e.target.value)} className={selectCls}>
              {METRICS.map((x) => (
                <option key={x.key} value={x.key}>
                  {x.label}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />
      {!d.members.length ? (
        <Card title="Set up team mode">
          <ol className="max-w-3xl list-decimal space-y-3 pl-5 text-[14px] text-ink-2">
            <li>
              The team lead picks a shared token and starts Vibecheck with it:{' '}
              <code className="font-mono text-[13px] text-ink">VIBECHECK_TEAM_TOKEN=… vibecheck serve --host 0.0.0.0</code>
            </li>
            <li>
              Each teammate, with the same token set, runs{' '}
              <code className="font-mono text-[13px] text-ink">vibecheck team push --url http://lead-host:8000 --member alex</code>
            </li>
            <li>
              No network? Run <code className="font-mono text-[13px] text-ink">vibecheck team export --member alex --out alex.json</code>,
              send the file, and the lead runs <code className="font-mono text-[13px] text-ink">vibecheck team import alex.json</code>.
            </li>
          </ol>
          <p className="mt-4 text-[13px] text-ink-3">
            Exports hold counts, rates and medians per week. Project names are hashed unless a member adds --include-projects.
          </p>
        </Card>
      ) : (
        <Card title={m.label} subtitle={m.help}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-line">
                  <Th>Member</Th>
                  {weeks.map((w) => (
                    <Th key={w} className="text-right">
                      {w.replace(/^\d{4}-/, '')}
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.members.map((member) => (
                  <tr key={member} className="border-b border-line last:border-0">
                    <Td className="font-medium">{member}</Td>
                    {weeks.map((w) => (
                      <Td key={w} className="num text-right">
                        {fmt(cell(member, w), m.unit)}
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-[12px] text-ink-3">
            People work on different things; use this to spot patterns worth talking about, not to rank anyone.
          </p>
        </Card>
      )}
    </div>
  )
}
