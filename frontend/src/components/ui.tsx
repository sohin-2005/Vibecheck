import type { ReactNode } from 'react'

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </div>
  )
}

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
    <section className={`rounded-xl border border-line bg-surface p-5 ${className}`}>
      {(title || right) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-xs font-medium text-ink-2">{label}</div>
      <div className="num mt-1 text-2xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-3">{hint}</div>}
    </div>
  )
}

export function Loading() {
  return <div className="py-12 text-center text-sm text-ink-3">Loading…</div>
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="rounded-lg bg-error-bg p-4 text-sm text-error-ink" role="alert">
      Couldn't load data: {error instanceof Error ? error.message : String(error)}. Is{' '}
      <code>promptlens serve</code> running?
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-ink-3">{children}</div>
}

const LEVELS = [
  { max: 33, label: 'Smooth', color: 'var(--good)', icon: '●' },
  { max: 66, label: 'Bumpy', color: 'var(--warning)', icon: '▲' },
  { max: 85, label: 'Rough', color: 'var(--serious)', icon: '▲' },
  { max: 101, label: 'Struggle', color: 'var(--critical)', icon: '■' },
]

export function StruggleBadge({ score }: { score: number | null }) {
  if (score == null) return <span className="text-ink-3">—</span>
  const lvl = LEVELS.find((l) => score < l.max) ?? LEVELS[3]
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span aria-hidden style={{ color: lvl.color }} className="text-[10px]">
        {lvl.icon}
      </span>
      <span className="num font-medium">{Math.round(score)}</span>
      <span className="text-xs text-ink-2">{lvl.label}</span>
    </span>
  )
}

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'error' | 'accent' }) {
  const cls =
    tone === 'error'
      ? 'bg-error-bg text-error-ink'
      : tone === 'accent'
        ? 'bg-accent/15 text-accent'
        : 'bg-surface-2 text-ink-2'
  return <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs ${cls}`}>{children}</span>
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
      ? 'bg-accent text-white hover:opacity-90'
      : 'border border-line bg-surface hover:bg-surface-2 text-ink'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-50 ${cls}`}
    >
      {children}
    </button>
  )
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <th className={`px-3 py-2 text-left text-xs font-medium text-ink-2 ${className}`}>{children}</th>
}

export function Td({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <td className={`px-3 py-2 align-top ${className}`}>{children}</td>
}
