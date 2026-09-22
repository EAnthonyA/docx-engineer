import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'

function formatDate(timestamp: number) {
  return new Intl.DateTimeFormat('lt-LT', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(new Date(timestamp * 1000))
}

export default function HistoryDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { data: job, isLoading, error } = useQuery({
    queryKey: ['history-job', jobId],
    queryFn: () => api.getJob(jobId!),
    enabled: !!jobId,
  })

  return (
    <div className="page history-detail-shell">
      <main className="main-content">
        <div className="content-column conversation-page">
          <button className="back-link" onClick={() => navigate('/istorija')}>← Visi ankstesni dokumentai</button>
          {isLoading && <p className="history-note">Atidaromas pokalbis…</p>}
          {error && <div className="history-empty"><h1>Pokalbio atidaryti nepavyko</h1><p>Gali būti, kad šis dokumentas jau nebesaugomas.</p></div>}
          {job && (
            <>
              <p className="greeting__eyebrow">Tik peržiūrai · {formatDate(job.conversation[0]?.at ?? job.stage_started_at)}</p>
              <h1 className="conversation-page__title">Dokumento pokalbis</h1>
              <p className="conversation-page__intro">Šis pokalbis išsaugotas peržiūrai. Jei norite naujų pakeitimų, pradėkite nuo naujo dokumento.</p>

              <section className="conversation" aria-label="Dokumento pokalbis">
                {job.conversation.length > 0 ? job.conversation.map((message, index) => (
                  <article className={`message message--${message.role}`} key={`${message.at}-${index}`}>
                    <p className="message__author">{message.role === 'user' ? 'Jūs' : 'Dokumentų pagalbininkė'}</p>
                    <p>{message.text}</p>
                  </article>
                )) : (
                  <p className="history-note">Šis senesnis dokumentas buvo išsaugotas be pokalbio įrašo.</p>
                )}
              </section>

              <div className="conversation-page__actions">
                <button className="btn btn--secondary" onClick={() => navigate('/')}>Pasirinkti naują dokumentą</button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
