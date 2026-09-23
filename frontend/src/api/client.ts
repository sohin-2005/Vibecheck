export type Filters = { from?: string; to?: string; project_id?: number }

export class ApiError extends Error {}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function get<T>(path: string, params: Record<string, unknown> = {}): Promise<T> {
  const r = await fetch(`/api${path}${qs(params)}`)
  if (!r.ok) throw new ApiError(`${r.status} ${r.statusText} for ${path}`)
  return r.json() as Promise<T>
}

export async function post<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`, { method: 'POST' })
  if (!r.ok) throw new ApiError(`${r.status} ${r.statusText} for ${path}`)
  return r.json() as Promise<T>
}

export type Overview = {
  totals: {
    sessions: number
    active_hours: number
    prompts: number
    input_tokens: number
    output_tokens: number
    cache_write_tokens: number
    cache_read_tokens: number
    cost_usd: number | null
    unpriced_sessions: number
    sessions_with_commit: number
    survival_7d: number | null
  }
  daily: { date: string; sessions: number; tokens: number; cost: number; active_minutes: number }[]
  by_project: { project: string; sessions: number }[]
}

export type Project = {
  id: number
  name: string
  cwd: string
  repo_root: string | null
  sessions: number
  cost_usd: number | null
}

export type SessionSummary = {
  id: string
  title: string | null
  project_id: number | null
  project: string | null
  started_at: string | null
  ended_at: string | null
  active_minutes: number | null
  human_turns: number
  assistant_turns: number
  input_tokens: number
  output_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  cost_usd: number | null
  models: string[]
  struggle_score: number | null
  has_commit: boolean
  turns_to_commit: number | null
}

export type SessionPage = { total: number; page: number; page_size: number; items: SessionSummary[] }

export type LinkedCommit = {
  sha: string
  subject: string
  authored_at: string
  link_method: string
  confidence: number
  ai_coauthored: boolean
  lines_added: number
  lines_deleted: number
  survival: Record<string, number | null>
}

export type SessionDetail = SessionSummary & {
  git_branch: string | null
  cc_version: string | null
  cwd: string | null
  struggle_signals: Record<string, number> | null
  commits: LinkedCommit[]
  tools: { tool_name: string; calls: number; errors: number }[]
}

export type TimelineItem =
  | {
      kind: 'prompt' | 'assistant' | 'interrupt'
      timestamp: string | null
      text: string | null
      model: string | null
      is_sidechain: boolean
    }
  | {
      kind: 'tool'
      timestamp: string | null
      tool_name: string
      file_path: string | null
      command: string | null
      is_error: boolean | null
      is_sidechain: boolean
    }

export type Survival = {
  checkpoints: {
    days: number
    lines_total: number
    lines_surviving: number
    commits: number
    not_merged: number
    rate: number | null
  }[]
  groups: Record<string, string | number | null>[]
  lowest_commits: {
    sha: string
    subject: string
    project: string
    authored_at: string
    lines_total: number
    survival_7d: number | null
  }[]
}

export type ToolStat = { tool_name: string; calls: number; errors: number; error_rate: number }

export type CoachSummary = {
  prompts: number
  scored: number
  rubric_version: string
  avg_specificity: number | null
  pct_context: number | null
  pct_success_criteria: number | null
  features: {
    pct_mentions_file: number | null
    pct_error_text: number | null
    pct_code_block: number | null
    pct_success_criteria: number | null
    median_chars: number | null
  }
  specificity_distribution: Record<string, number>
  categories: Record<string, number>
  scopes: Record<string, number>
  weekly: {
    week: string
    prompts: number
    avg_specificity: number | null
    pct_context: number | null
    pct_success_criteria: number | null
  }[]
}

export type CoachPrompt = {
  message_id: number
  session_id: string
  timestamp: string | null
  text: string
  char_len: number
  mentions_file: boolean | null
  specificity: number | null
  has_context: boolean | null
  has_success_criteria: boolean | null
  scope: string | null
  category: string | null
  suggestion: string | null
}

export type Insight = {
  id: number
  generated_at: string
  kind: string
  title: string
  detail: Record<string, unknown>
  n_a: number
  n_b: number
}

export type Job = {
  id: string
  name: string
  status: 'queued' | 'running' | 'done' | 'failed'
  created_at: string
  finished_at: string | null
  result: Record<string, unknown> | null
  error: string | null
}

export type AppConfig = Record<string, unknown>
