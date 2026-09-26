import type { ReactNode } from 'react'

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-[32px] leading-tight font-normal tracking-tight">{title}</h1>
        {subtitle && <p className="mt-2 text-[15px] text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </header>
  )
}

/** A report section: a heavy rule on top, a small-caps label, no box. */
export function Card({
  title,
  subtitle,
  children,
  className = '',
  right,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  className?: string
  right?: ReactNode
}) {
  return (
    <section className={`border-t border-rule pt-3 ${className}`}>
      {(title || right) && (
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            {title && <h2 className="label font-sans">{title}</h2>}
            {subtitle && <p className="mt-1 text-[13px] text-ink-3">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

/** Headline figures in one ruled strip. */
export function KpiRow({ children, cols = 5 }: { children: ReactNode; cols?: number }) {
  const grid = { 3: 'sm:grid-cols-3', 4: 'lg:grid-cols-4', 5: 'lg:grid-cols-5' }[cols] ?? 'lg:grid-cols-5'
  return (
    <div className={`grid grid-cols-2 border-y border-rule ${grid}`}>
      {children}
    </div>
  )
}

export function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="border-line py-4 pr-4 lg:border-l lg:pl-5 lg:first:border-l-0 lg:first:pl-0">
      <div className="label">{label}</div>
      <div className="num serif mt-2 text-[30px] leading-none">{value}</div>
      {hint && <div className="mt-2 text-xs text-ink-3">{hint}</div>}
    </div>
  )
}

export function Loading() {
  return <div className="py-16 text-center text-sm text-ink-3 italic serif">Loading…</div>
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="border-l-2 border-error-ink bg-error-bg px-4 py-3 text-sm text-error-ink" role="alert">
      Couldn't load data: {error instanceof Error ? error.message : String(error)}. Is <code>vibecheck serve</code>{' '}
      running?
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="serif py-10 text-center text-[15px] text-ink-3 italic">{children}</div>
}

const LEVELS = [
  { max: 33, label: 'Smooth', color: 'var(--good)' },
  { max: 66, label: 'Bumpy', color: 'var(--warning)' },
  { max: 85, label: 'Rough', color: 'var(--serious)' },
  { max: 101, label: 'Struggle', color: 'var(--critical)' },
]

/** Score, a filled-square gauge (1-4 squares) and a word, so colour is never the only cue. */
export function StruggleBadge({ score }: { score: number | null }) {
  if (score == null) return <span className="text-ink-3">—</span>
  const idx = Math.max(0, LEVELS.findIndex((l) => score < l.max))
  const lvl = LEVELS[idx]
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span className="num w-6 text-right">{Math.round(score)}</span>
      <span aria-hidden className="flex gap-[2px]">
        {LEVELS.map((_, i) => (
          <span
            key={i}
            className="h-2 w-2"
            style={{ background: i <= idx ? lvl.color : 'transparent', border: `1px solid ${i <= idx ? lvl.color : 'var(--border)'}` }}
          />
        ))}
      </span>
      <span className="text-xs text-ink-2">{lvl.label}</span>
    </span>
  )
}

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'error' | 'accent' }) {
  const cls =
    tone === 'error'
      ? 'border-error-ink/40 text-error-ink'
      : tone === 'accent'
        ? 'border-accent/50 text-accent'
        : 'border-line text-ink-2'
  return <span className={`inline-flex items-center whitespace-nowrap border px-1.5 py-px text-[11px] tracking-wide ${cls}`}>{children}</span>
}

export function Button({
  children,
  onClick,
  disabled,
  variant = 'default',
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'default' | 'primary'
}) {
  const cls =
    variant === 'primary'
      ? 'bg-ink text-bg border border-ink hover:bg-accent hover:border-accent'
      : 'border border-rule text-ink hover:bg-ink hover:text-bg'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1 text-[13px] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${cls}`}
    >
      {children}
    </button>
  )
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <th className={`label px-3 py-2 text-left font-semibold first:pl-0 ${className}`}>{children}</th>
}

export function Td({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <td className={`px-3 py-2.5 align-top first:pl-0 ${className}`}>{children}</td>
}

export const selectCls = 'border border-line bg-surface px-2 py-1 text-[13px] text-ink'
