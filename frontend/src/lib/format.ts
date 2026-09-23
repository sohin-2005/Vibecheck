const intFmt = new Intl.NumberFormat()

export const fmtInt = (n: number | null | undefined) => (n == null ? '—' : intFmt.format(n))

export function fmtCompact(n: number | null | undefined): string {
  if (n == null) return '—'
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)}B`
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}k`
  return String(n)
}

export const fmtUsd = (n: number | null | undefined) =>
  n == null ? 'n/a' : `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export const fmtPct = (n: number | null | undefined) => (n == null ? '—' : `${n.toFixed(1)}%`)

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtMinutes(m: number | null | undefined): string {
  if (m == null) return '—'
  if (m < 60) return `${Math.round(m)} min`
  return `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`
}

export const shortDay = (d: string) =>
  new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
