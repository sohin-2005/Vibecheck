import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, post, type AppConfig, type Job } from '../api/client'
import { Button, Card, ErrorBox, Loading, PageHeader, Pill } from '../components/ui'
import { fmtDateTime } from '../lib/format'

const JOBS = [
  { name: 'run', label: 'Run everything', help: 'ingest + git + analyze + insights' },
  { name: 'ingest', label: 'Ingest', help: 'Read new session logs' },
  { name: 'git', label: 'Git', help: 'Collect commits and link them' },
  { name: 'analyze', label: 'Analyze', help: 'Struggle, survival, features' },
  { name: 'coach', label: 'Coach', help: 'Score prompts with the LLM' },
  { name: 'insights', label: 'Insights', help: 'Recompute comparisons' },
]

export default function Settings() {
  const qc = useQueryClient()
  const cfg = useQuery({ queryKey: ['config'], queryFn: () => get<AppConfig>('/config') })
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => get<Job[]>('/jobs'),
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === 'running' || j.status === 'queued') ? 1000 : false),
  })
  const start = useMutation({
    mutationFn: (name: string) => post<Job>(`/jobs/${name}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
  })
  const running = jobs.data?.some((j) => j.status === 'running' || j.status === 'queued')

  return (
    <div>
      <PageHeader title="Settings" subtitle="Configuration is read-only here; edit the config file and restart to change it." />
      <Card title="Run jobs">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {JOBS.map((j) => (
            <div key={j.name} className="flex items-center justify-between gap-2 border-t border-line py-3">
              <div>
                <div className="text-sm font-medium">{j.label}</div>
                <div className="text-xs text-ink-3">{j.help}</div>
              </div>
              <Button
                variant={j.name === 'run' ? 'primary' : 'default'}
                disabled={running || start.isPending}
                onClick={() => start.mutate(j.name)}
              >
                Start
              </Button>
            </div>
          ))}
        </div>
        <h3 className="label mt-8 mb-2">Recent jobs</h3>
        {jobs.data?.length ? (
          <ul className="space-y-2 text-sm">
            {jobs.data.map((j) => (
              <li key={j.id} className="border-b border-line py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{j.name}</span>
                  <Pill tone={j.status === 'failed' ? 'error' : j.status === 'done' ? 'accent' : 'neutral'}>
                    {j.status === 'done' ? '✓ done' : j.status === 'failed' ? '✕ failed' : `… ${j.status}`}
                  </Pill>
                  <span className="text-xs text-ink-3">{fmtDateTime(j.created_at)}</span>
                </div>
                {j.result && <pre className="mt-1 overflow-x-auto text-xs text-ink-2">{JSON.stringify(j.result)}</pre>}
                {j.error && <pre className="mt-1 overflow-x-auto text-xs whitespace-pre-wrap text-error-ink">{j.error}</pre>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-3">No jobs yet in this server session.</p>
        )}
      </Card>
      <Card className="mt-12" title="Configuration">
        {cfg.isLoading ? (
          <Loading />
        ) : cfg.error ? (
          <ErrorBox error={cfg.error} />
        ) : (
          <>
            {Array.isArray(cfg.data!.priced_models) && !(cfg.data!.priced_models as string[]).length && (
              <p className="mb-4 border-l-2 border-accent py-1 pl-4 text-sm text-ink-2">
                No model prices configured, so costs show as n/a. Add a <code>[pricing.models."model-id"]</code> table with
                current USD-per-million-token prices to your config file.
              </p>
            )}
            <pre className="overflow-x-auto border border-line bg-surface p-4 font-mono text-xs leading-relaxed">{JSON.stringify(cfg.data, null, 2)}</pre>
          </>
        )}
      </Card>
    </div>
  )
}
