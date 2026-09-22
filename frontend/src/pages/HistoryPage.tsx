import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { JobStatus } from '../api/types'

function formatDate(timestamp: number) {
  return new Intl.DateTimeFormat('lt-LT', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(new Date(timestamp * 1000))
}

function statusLabel(status: JobStatus) {
  if (status === 'needs_review') return 'Paruoštas peržiūrėti'
  if (status === 'needs_clarification') return 'Laukiama atsakymo'
  if (status === 'running') return 'Tvarkomas'
  return 'Nepavyko paruošti'
}

export default function HistoryPage() {
  const navigate = useNavigate()
  const { data: jobs, isLoading, error } = useQuery({
    queryKey: ['job-history'],
    queryFn: api.listJobs,
  })

  return (
    <div className="page history-shell">
      <main className="main-content">
        <div className="content-column history-page">
          <p className="greeting__eyebrow">Tik peržiūrai</p>
          <h1 className="history-page__title">Ankstesni dokumentai</h1>
          <p className="history-page__intro">Čia galite ramiai peržiūrėti ankstesnius prašymus ir pokalbius. Šių pokalbių tęsti negalima.</p>

          {isLoading && <p className="history-note">Kraunamas sąrašas…</p>}
          {error && <p className="error-text">Sąrašo atidaryti nepavyko. Pabandykite dar kartą vėliau.</p>}
          {jobs?.length === 0 && (
            <div className="history-empty">
              <h2>Dar nėra ankstesnių dokumentų</h2>
              <p>Kai sutvarkysite pirmą dokumentą, jo pokalbį galėsite rasti čia.</p>
              <button className="btn btn--primary" onClick={() => navigate('/')}>Pasirinkti dokumentą</button>
            </div>
          )}
          {jobs && jobs.length > 0 && (
            <div className="history-list">
              {jobs.map((job) => (
                <button className="history-item" key={job.id} onClick={() => navigate(`/istorija/${job.id}`)}>
                  <span className="history-item__date">{formatDate(job.created_at)}</span>
                  <strong>{job.instruction}</strong>
                  <span className={`history-item__status history-item__status--${job.status}`}>{statusLabel(job.status)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
