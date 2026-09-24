import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { post, type CoachPrompt, type Rewrite } from '../api/client'

/** "You wrote" vs "Could have been", fetched on demand and cached server-side. */
export default function PromptRewrite({ prompt }: { prompt: CoachPrompt }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(Boolean(prompt.rewrite))
  const m = useMutation({
    mutationFn: () => post<Rewrite>(`/coach/rewrite/${prompt.message_id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['coach-prompts'] }),
  })
  const r = prompt.rewrite ?? m.data

  if (!open || !r) {
    return (
      <button
        type="button"
        className="mt-2 text-[13px] text-accent underline decoration-accent/40 underline-offset-4 hover:decoration-accent disabled:opacity-50"
        disabled={m.isPending}
        onClick={() => {
          setOpen(true)
          if (!r) m.mutate()
        }}
      >
        {m.isPending ? 'Writing a better version…' : 'Show a better version'}
      </button>
    )
  }

  if (!r.changes.length) {
    return <p className="mt-2 text-[13px] text-ink-3 italic serif">Already specific; nothing obvious to add.</p>
  }

  return (
    <div className="mt-3 grid gap-0 border-y border-line md:grid-cols-2">
      <div className="py-3 md:border-r md:border-line md:pr-4">
        <div className="label mb-1">You wrote</div>
        <p className="serif text-[15px] break-words whitespace-pre-wrap text-ink-2">{prompt.text}</p>
      </div>
      <div className="py-3 md:pl-4">
        <div className="label mb-1 text-accent">Could have been</div>
        <p className="serif text-[15px] break-words whitespace-pre-wrap">{r.rewrite}</p>
        <ul className="mt-3 space-y-0.5 text-[12px] text-ink-3">
          {r.changes.map((c) => (
            <li key={c}>+ {c}</li>
          ))}
        </ul>
        <p className="mt-2 text-[11px] text-ink-3">
          {r.method === 'llm' ? `Rewritten by ${r.model}` : 'Template rewrite, filled in from what happened in the session'}
        </p>
      </div>
    </div>
  )
}
