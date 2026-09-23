import { useState, type ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const axis = { stroke: 'var(--ink-3)', fontSize: 11, tickLine: false, axisLine: false } as const

type Series = { key: string; label: string; color: string; format?: (v: number) => string }

function ChartTooltip({
  active,
  payload,
  label,
  series,
  labelFormat,
}: {
  active?: boolean
  payload?: readonly { dataKey?: unknown; value?: unknown }[]
  label?: unknown
  series: Series[]
  labelFormat?: (l: string) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="border border-rule bg-surface px-3 py-2 text-xs">
      <div className="mb-1 font-medium text-ink">{labelFormat ? labelFormat(String(label)) : String(label ?? "")}</div>
      {payload.map((p) => {
        const s = series.find((x) => x.key === p.dataKey)
        const v = typeof p.value === 'number' ? p.value : Number(p.value)
        return (
          <div key={String(p.dataKey)} className="flex items-center gap-2 text-ink-2">
            <span className="inline-block h-2 w-2" style={{ background: s?.color }} />
            <span>{s?.label}</span>
            <span className="num ml-auto pl-3 font-medium text-ink">{s?.format ? s.format(v) : v}</span>
          </div>
        )
      })}
    </div>
  )
}

/** A chart with an accessible table view one click away. */
export function WithTable({
  children,
  rows,
  columns,
}: {
  children: ReactNode
  rows: Record<string, unknown>[]
  columns: { key: string; label: string; format?: (v: never) => string }[]
}) {
  const [table, setTable] = useState(false)
  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button
          type="button"
          className="label text-ink-3 hover:text-ink"
          onClick={() => setTable(!table)}
        >
          {table ? 'Show chart' : 'Show table'}
        </button>
      </div>
      {table ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} className="label px-2 py-1 text-left">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-line">
                  {columns.map((c) => (
                    <td key={c.key} className="num px-2 py-1">
                      {c.format ? c.format(r[c.key] as never) : String(r[c.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </div>
  )
}

export function TimeLineChart({
  data,
  x,
  series,
  height = 240,
  labelFormat,
  yFormat,
  yDomain,
}: {
  data: Record<string, unknown>[]
  x: string
  series: Series[]
  height?: number
  labelFormat?: (l: string) => string
  yFormat?: (v: number) => string
  yDomain?: [number, number]
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey={x} {...axis} tickFormatter={labelFormat} minTickGap={24} />
        <YAxis {...axis} width={56} tickFormatter={yFormat} domain={yDomain} />
        <Tooltip
          cursor={{ stroke: 'var(--ink-3)', strokeDasharray: '3 3' }}
          content={(p) => <ChartTooltip {...p} series={series} labelFormat={labelFormat} />}
        />
        {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)', paddingTop: 8 }} />}
        {series.map((s) => (
          <Line
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stroke={s.color}
            strokeWidth={2}
            dot={data.length < 20 ? { r: 4, strokeWidth: 2, stroke: 'var(--surface)', fill: s.color } : false}
            activeDot={{ r: 5, strokeWidth: 2, stroke: 'var(--surface)' }}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

export function SimpleBarChart({
  data,
  x,
  series,
  height = 240,
  horizontal = false,
  yFormat,
}: {
  data: Record<string, unknown>[]
  x: string
  series: Series[]
  height?: number
  horizontal?: boolean
  yFormat?: (v: number) => string
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={horizontal ? 'vertical' : 'horizontal'}
        margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
        barCategoryGap={horizontal ? 6 : '20%'}
      >
        <CartesianGrid stroke="var(--grid)" vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axis} tickFormatter={yFormat} />
            <YAxis type="category" dataKey={x} {...axis} width={110} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...axis} />
            <YAxis {...axis} width={48} tickFormatter={yFormat} />
          </>
        )}
        <Tooltip cursor={{ fill: 'var(--surface-2)' }} content={(p) => <ChartTooltip {...p} series={series} />} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)' }} />}
        {series.map((s) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={s.color}
            radius={horizontal ? [0, 2, 2, 0] : [2, 2, 0, 0]}
            maxBarSize={horizontal ? 18 : 48}
            stroke="var(--surface)"
            strokeWidth={1}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
