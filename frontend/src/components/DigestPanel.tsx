import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { get, type Digest } from '../api/client'
import { fmtDateTime } from '../lib/format'

export default function DigestPanel() {
  const q = useQuery({ queryKey: ['digest'], queryFn: () => get<Digest>('/digest', { days: 7 }) })
  const d = q.data
  if (!d?.worst) return null
  const w = d.worst
  const heading = d.fallback ? 'Your hardest recent session' : 'Your hardest session this week'

  return (
    <section className="mb-12 border-t-2 border-rule pt-4">
      <div className="label mb-3">{heading}</div>
      <div className="grid gap-10 lg:grid-cols-[3fr_2fr]">
        <div>
          <Link to={`/sessions/${w.id}`} className="serif text-[24px] leading-snug hover:underline">
            {w.title || w.id.slice(0, 8)}
          </Link>
          <p className="mt-1 text-[13px] text-ink-3">
            {w.project ?? 'no project'} · {w.tool} · {fmtDateTime(w.started_at)} · {w.prompts} prompts
            {w.has_commit ? ' · committed' : ' · no commit'}
          </p>
          {w.first_prompt && (
            <p className="serif mt-4 border-l-2 border-accent pl-4 text-[15px] text-ink-2 italic">“{w.first_prompt}”</p>
          )}
          <h3 className="label mt-6 mb-2">What went wrong</h3>
          <ol className="space-y-3">
            {w.went_wrong.map((item, i) => (
              <li key={item.kind} className="flex gap-3">
                <span className="serif num w-5 shrink-0 text-ink-3">{i + 1}.</span>
                <div>
                  <div className="text-[14px] font-medium">{item.headline}</div>
                  {item.detail && <div className="text-[13px] break-words text-ink-2">{item.detail}</div>}
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h3 className="label mb-2">Try next time</h3>
          <ul className="space-y-3">
            {d.tips.map((t) => (
              <li key={t} className="serif border-b border-line pb-3 text-[16px] leading-snug last:border-0">
                {t}
              </li>
            ))}
          </ul>
          {d.best && (
            <p className="mt-6 text-[13px] text-ink-2">
              For contrast, your smoothest:{' '}
              <Link to={`/sessions/${d.best.id}`} className="text-ink underline decoration-line underline-offset-2">
                {d.best.title || d.best.id.slice(0, 8)}
              </Link>{' '}
              ({d.best.prompts} prompt{d.best.prompts === 1 ? '' : 's'}
              {d.best.has_commit ? ', committed' : ''}).
            </p>
          )}
          {d.insights_progress.sessions < d.insights_progress.needed && (
            <p className="mt-4 text-[12px] text-ink-3">
              Habit-vs-outcome insights unlock at about {d.insights_progress.needed} sessions. You have{' '}
              {d.insights_progress.sessions}.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
