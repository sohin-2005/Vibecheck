import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { get, type SessionDetail as Detail, type TimelineItem } from '../api/client'
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader, Pill, StruggleBadge, Td, Th } from '../components/ui'
import { fmtCompact, fmtDateTime, fmtMinutes, fmtPct, fmtTime, fmtUsd } from '../lib/format'

const SIGNALS: { key: string; label: string; weightKey: string; help: string }[] = [
  { key: 'interrupts', label: 'Interrupts', weightKey: 'interrupts', help: 'You stopped Claude mid-task' },
  { key: 'corrections', label: 'Corrections', weightKey: 'corrections', help: 'Prompts like "no", "that\'s wrong", "try again"' },
  { key: 'tool_errors', label: 'Tool errors', weightKey: 'tool_errors', help: 'Failed commands, edits or reads' },
  { key: 'repeated_edits', label: 'Repeated edits', weightKey: 'repeated_edits', help: 'Edits beyond 3 to the same file' },
  { key: 'turns', label: 'Prompts', weightKey: 'turns', help: 'Longer conversations add a little' },
]

function WhyScore({ signals, weights }: { signals: Record<string, number>; weights: Record<string, number> }) {
  const parts = SIGNALS.map((s) => ({ ...s, n: signals[s.key] ?? 0, pts: (signals[s.key] ?? 0) * (weights[s.weightKey] ?? 0) }))
  const max = Math.max(1, ...parts.map((p) => p.pts))
  return (
    <div className="space-y-3">
      {parts.map((p) => (
        <div key={p.key}>
          <div className="flex items-baseline justify-between text-sm">
            <span>
              {p.label} <span className="text-xs text-ink-3">· {p.help}</span>
            </span>
            <span className="num text-ink-2">
              {p.n} × {weights[p.weightKey] ?? 0} = <span className="font-medium text-ink">{p.pts.toFixed(1)}</span>
            </span>
          </div>
          <div className="mt-1.5 h-[3px] bg-surface-2">
            <div className="h-[3px]" style={{ width: `${(p.pts / max) * 100}%`, background: 'var(--series-1)' }} />
          </div>
        </div>
      ))}
      <p className="text-xs text-ink-3">
        Raw score {signals.raw_score?.toFixed(1)}. The 0-100 score is this session's rank among all your sessions.
      </p>
    </div>
  )
}

function TimelineRow({ item }: { item: TimelineItem }) {
  const [open, setOpen] = useState(false)
  const time = <span className="num w-20 shrink-0 pt-0.5 text-xs text-ink-3">{fmtTime(item.timestamp)}</span>
  if (item.kind === 'tool') {
    const detail = item.file_path ?? item.command ?? ''
    return (
      <div className="flex gap-3 py-1">
        {time}
        <div className="min-w-0">
          <span
            className={`inline-flex max-w-full items-center gap-1.5 border px-1.5 py-px text-xs ${
              item.is_error ? 'border-error-ink/50 text-error-ink' : 'border-line text-ink-2'
            }`}
          >
            <span className="font-medium">{item.is_error ? `✕ ${item.tool_name}` : item.tool_name}</span>
            {detail && <span className="truncate font-mono">{detail.slice(0, 120)}</span>}
            {item.is_sidechain && <span className="text-ink-3">(subagent)</span>}
          </span>
        </div>
      </div>
    )
  }
  if (item.kind === 'interrupt') {
    return (
      <div className="flex gap-3 py-1">
        {time}
        <Pill tone="error">Interrupted by you</Pill>
      </div>
    )
  }
  if (item.kind === 'prompt') {
    return (
      <div className="flex gap-3 py-2">
        {time}
        <div className="min-w-0 flex-1 border-l-2 border-accent py-1 pl-4">
          <div className="label mb-1 text-accent">You</div>
          <div className="serif text-[15px] leading-relaxed break-words whitespace-pre-wrap">{item.text}</div>
        </div>
      </div>
    )
  }
  const text = item.text ?? ''
  const long = text.length > 220
  return (
    <div className="flex gap-3 py-1">
      {time}
      <div className="min-w-0 flex-1 text-sm text-ink-2">
        <span className="mr-1 text-xs font-medium text-ink-3">Claude{item.is_sidechain ? ' (subagent)' : ''}:</span>
        <span className="break-words whitespace-pre-wrap">{open || !long ? text : `${text.slice(0, 220)}…`}</span>
        {long && (
          <button type="button" className="ml-1 text-xs text-accent hover:underline" onClick={() => setOpen(!open)}>
            {open ? 'less' : 'more'}
          </button>
        )}
      </div>
    </div>
  )
}

export default function SessionDetail() {
  const { id } = useParams()
  const q = useQuery({ queryKey: ['session', id], queryFn: () => get<Detail>(`/sessions/${id}`) })
  const tl = useQuery({ queryKey: ['timeline', id], queryFn: () => get<TimelineItem[]>(`/sessions/${id}/timeline`) })
  const cfg = useQuery({ queryKey: ['config'], queryFn: () => get<{ struggle_weights: Record<string, number> }>('/config') })
  const [hideAssistant, setHideAssistant] = useState(false)

  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const s = q.data!
  const items = (tl.data ?? []).filter((i) => !(hideAssistant && i.kind === 'assistant'))

  return (
    <div>
      <Link to="/sessions" className="text-sm text-ink-2 hover:text-ink">
        ← Sessions
      </Link>
      <PageHeader
        title={s.title || `Session ${s.id.slice(0, 8)}`}
        subtitle={
          <>
            {s.project ?? 'unknown project'} · {fmtDateTime(s.started_at)}
            {s.git_branch ? ` · ${s.git_branch}` : ''}
            {s.models.length ? ` · ${s.models.join(', ')}` : ''}
          </>
        }
        right={<StruggleBadge score={s.struggle_score} />}
      />
      <div className="grid grid-cols-2 border-y border-rule lg:grid-cols-5">
        <Kpi label="Prompts" value={s.human_turns} hint={`${s.assistant_turns} Claude replies`} />
        <Kpi label="Active time" value={fmtMinutes(s.active_minutes)} />
        <Kpi label="Tokens (in + out)" value={fmtCompact(s.input_tokens + s.output_tokens)} hint={`+ ${fmtCompact(s.cache_read_tokens + s.cache_write_tokens)} cache`} />
        <Kpi label="API-equivalent cost" value={fmtUsd(s.cost_usd)} />
        <Kpi label="Prompts to first commit" value={s.turns_to_commit ?? '—'} hint={s.has_commit ? `${s.commits.length} linked commit(s)` : 'No linked commit'} />
      </div>

      <div className="mt-12 grid gap-x-12 gap-y-12 lg:grid-cols-2">
        <Card title="Why this struggle score">
          {s.struggle_signals && cfg.data ? (
            <WhyScore signals={s.struggle_signals} weights={cfg.data.struggle_weights} />
          ) : (
            <Empty>Run promptlens analyze to compute struggle signals.</Empty>
          )}
        </Card>
        <Card title="Linked commits" subtitle="How the link was made, and how much of the code survived.">
          {s.commits.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line">
                    <Th>Commit</Th>
                    <Th>Link</Th>
                    <Th className="text-right">+/−</Th>
                    <Th className="text-right">Survival 1/7/30d</Th>
                  </tr>
                </thead>
                <tbody>
                  {s.commits.map((c) => (
                    <tr key={c.sha} className="border-b border-line last:border-0">
                      <Td>
                        <code className="text-xs text-ink-3">{c.sha.slice(0, 8)}</code> {c.subject}
                      </Td>
                      <Td>
                        <Pill>
                          {c.link_method} · {Math.round(c.confidence * 100)}%
                        </Pill>
                      </Td>
                      <Td className="num text-right whitespace-nowrap">
                        +{c.lines_added} −{c.lines_deleted}
                      </Td>
                      <Td className="num text-right whitespace-nowrap">
                        {['1', '7', '30'].map((d) => fmtPct(c.ai_survival[d] ?? c.survival[d] ?? null)).join(' / ')}
                        {Object.keys(c.ai_survival).length > 0 && <div className="text-[11px] text-ink-3">edit-matched</div>}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>No commits linked to this session.</Empty>
          )}
        </Card>
      </div>

      <Card
        className="mt-12"
        title="Replay"
        subtitle="Your prompts, Claude's replies and every tool call, in order. Errors are shown in red."
        right={
          <label className="flex items-center gap-2 text-xs text-ink-2">
            <input type="checkbox" checked={hideAssistant} onChange={(e) => setHideAssistant(e.target.checked)} />
            Hide Claude's text
          </label>
        }
      >
        {tl.isLoading ? <Loading /> : items.length ? items.map((i, n) => <TimelineRow key={n} item={i} />) : <Empty>Nothing to replay.</Empty>}
      </Card>
    </div>
  )
}
