export type JobStatus = 'running' | 'needs_review' | 'done' | 'stuck'

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
  diff: Diff | null
  last_error: string | null
}
