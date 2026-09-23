import { useQuery } from '@tanstack/react-query'
import { get, type ToolStat } from '../api/client'
import { SimpleBarChart, WithTable } from '../components/charts'
import { Card, Empty, ErrorBox, Loading, PageHeader, Td, Th } from '../components/ui'
import { useFilters } from '../lib/filters'
import { fmtInt, fmtPct } from '../lib/format'

export default function Tools() {
  const { filters } = useFilters()
  const q = useQuery({ queryKey: ['tools', filters], queryFn: () => get<ToolStat[]>('/tools', filters) })
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const tools = q.data!
  const top = tools.slice(0, 12)
  const byErrors = [...tools].filter((t) => t.calls >= 5).sort((a, b) => b.error_rate - a.error_rate)

  return (
    <div>
      <PageHeader title="Tools" subtitle="Which tools Claude uses most, and which ones fail." />
      {!tools.length ? (
        <Card>
          <Empty>No tool calls in this range.</Empty>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Calls per tool" subtitle={tools.length > 12 ? `Top 12 of ${tools.length}` : undefined}>
            <WithTable
              rows={tools}
              columns={[
                { key: 'tool_name', label: 'Tool' },
                { key: 'calls', label: 'Calls', format: (v: number) => fmtInt(v) },
                { key: 'errors', label: 'Errors', format: (v: number) => fmtInt(v) },
                { key: 'error_rate', label: 'Error rate', format: (v: number) => fmtPct(v) },
              ]}
            >
              <SimpleBarChart
                data={top}
                x="tool_name"
                horizontal
                height={Math.max(180, top.length * 30)}
                series={[{ key: 'calls', label: 'Calls', color: 'var(--series-1)', format: fmtInt }]}
              />
            </WithTable>
          </Card>
          <Card title="Error rate by tool" subtitle="Tools with at least 5 calls, highest error rate first.">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line">
                    <Th>Tool</Th>
                    <Th className="text-right">Calls</Th>
                    <Th className="text-right">Errors</Th>
                    <Th>Error rate</Th>
                  </tr>
                </thead>
                <tbody>
                  {byErrors.map((t) => (
                    <tr key={t.tool_name} className="border-b border-line last:border-0">
                      <Td className="font-medium">{t.tool_name}</Td>
                      <Td className="num text-right">{fmtInt(t.calls)}</Td>
                      <Td className="num text-right">{fmtInt(t.errors)}</Td>
                      <Td>
                        <div className="flex items-center gap-2">
                          <div className="h-[3px] w-24 bg-surface-2">
                            <div
                              className="h-[3px]"
                              style={{ width: `${Math.min(100, t.error_rate)}%`, background: 'var(--critical)' }}
                            />
                          </div>
                          <span className="num">{fmtPct(t.error_rate)}</span>
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
