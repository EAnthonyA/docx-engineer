export type JobStatus = 'running' | 'needs_review' | 'needs_clarification' | 'done' | 'stuck'

export interface Run {
  text: string
  bold: boolean
  italic: boolean
  underline: boolean
}

export interface Paragraph {
  text: string
  style: string
  runs: Run[]
}

export interface DiffEntry {
  status: 'unchanged' | 'changed' | 'added' | 'removed'
  before: Paragraph | null
  after: Paragraph | null
}

export interface Diff {
  total: number
  changed: number
  entries: DiffEntry[]
}

export interface Job {
  id: string
  status: JobStatus
  instruction: string
  question: string | null
  diff: Diff | null
  last_error: string | null
  attempt: number
  attempt_error: string | null
  max_attempts: number
  stage: string
  stage_detail: string
  stage_started_at: number
  activity: JobActivity[]
  conversation: ConversationMessage[]
}

export interface JobActivity {
  at: number
  stage: string
  detail: string
}

export interface ConversationMessage {
  at: number
  role: 'user' | 'assistant'
  text: string
}

export interface JobSummary {
  id: string
  instruction: string
  status: JobStatus
  stage_detail: string
  created_at: number
  has_result: boolean
}
