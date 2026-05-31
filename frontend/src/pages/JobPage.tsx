import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import DiffView from '../components/DiffView'
import LoadingSpinner from '../components/LoadingSpinner'

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [showRefine, setShowRefine] = useState(false)
  const [refineNote, setRefineNote] = useState('')
  const [refineError, setRefineError] = useState('')

  const { data: job, error } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId!),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 2000 : false),
    enabled: !!jobId,
  })

  const refine = useMutation({
    mutationFn: () => api.refineJob(jobId!, refineNote),
    onSuccess: () => {
      setShowRefine(false)
      setRefineNote('')
      qc.invalidateQueries({ queryKey: ['job', jobId] })
    },
    onError: (e) => {
      setRefineError((e as Error).message)
    },
  })

  function handleLogout() {
    api.logout().then(() => {
      qc.clear()
      navigate('/login', { replace: true })
    })
  }

  const header = (
    <header className="header">
      <div className="container header__inner">
        <a className="logo" href="/" style={{ textDecoration: 'none' }}>
          docx-engineer
        </a>
        <button className="btn btn--ghost" onClick={handleLogout}>
          Log out
        </button>
      </div>
    </header>
  )

  if (error) {
    return (
      <div className="page">
        {header}
        <div className="stuck-page">
          <h2>Job not found</h2>
          <p>This job may have expired. Upload your document again to start fresh.</p>
          <button className="btn btn--primary" onClick={() => navigate('/')}>
            Start over
          </button>
        </div>
      </div>
    )
  }

  if (!job || job.status === 'running') {
    return (
      <div className="page">
        {header}
        <LoadingSpinner
          message="Working on it…"
          subtext="I'm reading your document and figuring out the best way to make those changes. This usually takes 15–30 seconds."
        />
      </div>
    )
  }

  if (job.status === 'stuck') {
    return (
      <div className="page">
        {header}
        <div className="stuck-page">
          <h2>Hmm, I got stuck</h2>
          <p>
            I gave it a few tries but couldn't quite get that right. Want to try describing it a
            different way? The more specific, the better.
          </p>

          <div style={{ width: '100%', maxWidth: 480 }}>
            <div className="field" style={{ marginBottom: 12 }}>
              <textarea
                className="textarea"
                rows={4}
                value={refineNote}
                onChange={(e) => setRefineNote(e.target.value)}
                placeholder="Describe the change in more detail…"
              />
            </div>
            {refineError && <p className="error-text">{refineError}</p>}
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                className="btn btn--primary"
                disabled={refine.isPending || !refineNote.trim()}
                onClick={() => {
                  setRefineError('')
                  refine.mutate()
                }}
              >
                {refine.isPending ? 'Trying…' : 'Try again'}
              </button>
              <button className="btn btn--secondary" onClick={() => navigate('/')}>
                Start over
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // needs_review
  const diff = job.diff!
  return (
    <div className="page">
      {header}
      <main className="main-content">
        <div className="container">
          <div className="diff-header">
            <h2>Here's what changed</h2>
            <p className="diff-meta">
              {diff.total} paragraph{diff.total !== 1 ? 's' : ''} total &middot;{' '}
              <strong>{diff.changed} changed</strong>
            </p>
          </div>

          <div className="diff-actions">
            <a
              href={api.downloadUrl(jobId!)}
              className="btn btn--primary"
              download="result.docx"
            >
              Download result
            </a>
            <button
              className="btn btn--secondary"
              onClick={() => {
                setShowRefine((v) => !v)
                setRefineNote('')
                setRefineError('')
              }}
            >
              {showRefine ? 'Cancel' : 'Not quite — describe a fix'}
            </button>
            <button className="btn btn--ghost" onClick={() => navigate('/')}>
              New document
            </button>
          </div>

          {showRefine && (
            <div className="refine-panel">
              <h3>What needs to change?</h3>
              <textarea
                className="textarea"
                rows={3}
                value={refineNote}
                onChange={(e) => setRefineNote(e.target.value)}
                placeholder="e.g. The tags are still there in paragraph 3…"
                autoFocus
              />
              {refineError && <p className="error-text">{refineError}</p>}
              <div>
                <button
                  className="btn btn--primary"
                  disabled={refine.isPending || !refineNote.trim()}
                  onClick={() => {
                    setRefineError('')
                    refine.mutate()
                  }}
                >
                  {refine.isPending ? 'Trying…' : 'Re-run with this fix'}
                </button>
              </div>
            </div>
          )}

          <DiffView diff={diff} />
        </div>
      </main>
    </div>
  )
}
