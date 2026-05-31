import { useState } from 'react'
import type { Diff, DiffEntry, Paragraph, Run } from '../api/types'

const CONTEXT_SIZE = 2

type VisibleItem =
  | { kind: 'entry'; entry: DiffEntry }
  | { kind: 'separator'; count: number; expandAt: number }

function buildVisible(entries: DiffEntry[], expanded: Set<number>): VisibleItem[] {
  const shown = new Set<number>()

  entries.forEach((e, i) => {
    if (e.status !== 'unchanged') {
      for (let j = Math.max(0, i - CONTEXT_SIZE); j <= Math.min(entries.length - 1, i + CONTEXT_SIZE); j++) {
        shown.add(j)
      }
    }
  })

  expanded.forEach((idx) => shown.add(idx))

  const result: VisibleItem[] = []
  let hidden = 0
  let hiddenStart = 0

  for (let i = 0; i < entries.length; i++) {
    if (shown.has(i)) {
      if (hidden > 0) {
        result.push({ kind: 'separator', count: hidden, expandAt: hiddenStart })
        hidden = 0
      }
      result.push({ kind: 'entry', entry: entries[i] })
    } else {
      if (hidden === 0) hiddenStart = i
      hidden++
    }
  }

  if (hidden > 0) {
    result.push({ kind: 'separator', count: hidden, expandAt: hiddenStart })
  }

  return result
}

function renderRuns(runs: Run[]) {
  if (!runs.length) return <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>—</span>
  return (
    <>
      {runs.map((r, i) => {
        const cls = [r.bold && 'run-bold', r.italic && 'run-italic', r.underline && 'run-underline']
          .filter(Boolean)
          .join(' ')
        return (
          <span key={i} className={cls || undefined}>
            {r.text}
          </span>
        )
      })}
    </>
  )
}

function renderPara(para: Paragraph | null) {
  if (!para) return <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>—</span>
  if (!para.runs.length) return <span style={{ color: 'var(--text-secondary)' }}>{para.text || '(empty)'}</span>
  return renderRuns(para.runs)
}

interface Props {
  diff: Diff
}

export default function DiffView({ diff }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  function expandAt(start: number, count: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      for (let i = start; i < start + count; i++) next.add(i)
      return next
    })
  }

  const items = buildVisible(diff.entries, expanded)

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="diff-table">
        <thead>
          <tr>
            <th>Before</th>
            <th>After</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => {
            if (item.kind === 'separator') {
              return (
                <tr
                  key={`sep-${idx}`}
                  className="diff-separator"
                  onClick={() => expandAt(item.expandAt, item.count)}
                  title="Click to expand"
                >
                  <td colSpan={2}>
                    ··· {item.count} unchanged paragraph{item.count !== 1 ? 's' : ''} (click to expand)
                  </td>
                </tr>
              )
            }

            const { entry } = item
            return (
              <tr key={idx} className={`diff-row diff-row--${entry.status}`}>
                <td>{renderPara(entry.before)}</td>
                <td>{renderPara(entry.after)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
