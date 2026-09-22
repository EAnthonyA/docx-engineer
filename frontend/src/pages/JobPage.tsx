import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import DiffView from '../components/DiffView'
import LoadingSpinner from '../components/LoadingSpinner'

function splitQuestions(question: string): { numbered: boolean; items: string[] } {
  const text = question.trim()

  // The model usually separates questions with newlines.
  const lines = text
    .split(/\n+/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length > 1) return { numbered: true, items: lines }

  // Fallback: questions dumped inline as "1. … 2. … 3. …".
  const parts = text
    .split(/(?=\d+\.\s)/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length > 1) return { numbered: true, items: parts }

  return { numbered: false, items: [text] }
}

export default function JobPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [showRefine, setShowRefine] = useState(false)
  const [refineNote, setRefineNote] = useState('')
  const [refineError, setRefineError] = useState('')
  const [answer, setAnswer] = useState('')
  const [answerError, setAnswerError] = useState('')

  const { data: job, error } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.getJob(jobId!),
    // Job stages are persisted and displayed, so polling does not need to be
    // noisy. Six seconds keeps the page responsive while cutting requests by 3x.
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 6000 : false),
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
      console.error('Nepavyko pakartoti dokumento tvarkymo:', e)
      setRefineError('Nepavyko pradėti naujo bandymo. Pabandykite dar kartą po akimirkos.')
    },
  })

  const answerJob = useMutation({
    mutationFn: () => api.answerJob(jobId!, answer),
    onSuccess: () => {
      setAnswer('')
      qc.invalidateQueries({ queryKey: ['job', jobId] })
    },
    onError: (e) => {
      console.error('Nepavyko išsiųsti atsakymo:', e)
      setAnswerError('Atsakymo išsiųsti nepavyko. Pabandykite dar kartą.')
    },
  })

  if (error) {
    return (
      <div className="page job-page">
        <div className="stuck-page">
          <h2>Šio dokumento užduoties rasti nepavyko</h2>
          <p>Gali būti, kad ankstesnė užduotis jau nebegalioja. Pasirinkite dokumentą dar kartą ir pradėkime iš naujo.</p>
          <button className="btn btn--primary" onClick={() => navigate('/')}>
            Pradėti iš naujo
          </button>
        </div>
      </div>
    )
  }

  if (job && job.status === 'needs_clarification') {
    const questions = splitQuestions(job.question ?? '')

    return (
      <div className="page job-page">
        <div className="stuck-page">
          <h2>Trumpas klausimas prieš pradedant</h2>
          <div
            style={{
              width: '100%',
              maxWidth: 560,
              marginBottom: 20,
              textAlign: 'left',
            }}
          >
            {questions.numbered ? (
              <ol style={{ margin: 0, paddingLeft: 20 }}>
                {questions.items.map((q, i) => (
                  <li
                    key={i}
                    style={{
                      fontSize: 15,
                      lineHeight: 1.6,
                      color: '#222',
                      marginBottom: 10,
                    }}
                  >
                    {q.replace(/^\d+\.\s*/, '')}
                  </li>
                ))}
              </ol>
            ) : (
              <p style={{ fontSize: 16, color: '#222', margin: 0 }}>{questions.items[0]}</p>
            )}
          </div>

          <div style={{ width: '100%', maxWidth: 480 }}>
            <div className="field" style={{ marginBottom: 12 }}>
              <textarea
                className="textarea"
                rows={3}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Parašykite atsakymą…"
                autoFocus
              />
            </div>
            {answerError && <p className="error-text">{answerError}</p>}
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                className="btn btn--primary"
                disabled={answerJob.isPending || !answer.trim()}
                onClick={() => {
                  setAnswerError('')
                  answerJob.mutate()
                }}
              >
                {answerJob.isPending ? 'Siunčiama…' : 'Tęsti'}
              </button>
              <button className="btn btn--secondary" onClick={() => navigate('/')}>
                Pradėti iš naujo
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!job || job.status === 'running') {
    if (job && job.attempt > 1) {
      const err = job.attempt_error
      const shortErr =
        err && err.length > 140 ? `${err.slice(0, 140)}…` : err
      return (
        <div className="page job-page">
          <LoadingSpinner
            message={`Bandome kitu būdu (${job.attempt} bandymas iš ${job.max_attempts})`}
            subtext={
              shortErr
                ? 'Pirmasis bandymas nepavyko, todėl ieškome kito sprendimo. Jums nieko daryti nereikia.'
                : 'Ieškome kito būdo atlikti pakeitimą. Jums nieko daryti nereikia.'
            }
            detail={job.stage_detail}
            attempt={job.attempt}
            maxAttempts={job.max_attempts}
          />
        </div>
      )
    }

    return (
      <div className="page job-page">
        <LoadingSpinner
          message="Tvarkome Jūsų dokumentą…"
          subtext="Dažniausiai tai užtrunka nuo pusės minutės iki minutės. Šį puslapį galite palikti atidarytą."
          detail={job?.stage_detail ?? 'Ruošiamės pradėti'}
          attempt={job?.attempt || undefined}
          maxAttempts={job?.attempt ? job.max_attempts : undefined}
        />
      </div>
    )
  }

  if (job.status === 'stuck') {
    return (
      <div className="page job-page">
        <div className="stuck-page">
          <h2>Šį kartą dokumento sutvarkyti nepavyko</h2>
          <p>
            Pabandėme kelis būdus, tačiau rezultato nepavyko paruošti. Parašykite, ką norėtumėte atlikti kitaip — padės ir trumpas paaiškinimas.
          </p>

          <div style={{ width: '100%', maxWidth: 480 }}>
            <div className="field" style={{ marginBottom: 12 }}>
              <textarea
                className="textarea"
                rows={4}
                value={refineNote}
                onChange={(e) => setRefineNote(e.target.value)}
                placeholder="Pavyzdžiui: pažymėkite visus datų paminėjimus pirmame skyriuje…"
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
                {refine.isPending ? 'Bandoma dar kartą…' : 'Pabandyti dar kartą'}
              </button>
              <button className="btn btn--secondary" onClick={() => navigate('/')}>
                Pasirinkti kitą dokumentą
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (job.status === 'done' || !job.diff) {
    return (
      <div className="page job-page">
        <div className="stuck-page">
          <h2>Dokumentas atsisiųstas</h2>
          <p>
            Failas išsaugotas Jūsų įrenginyje. Serverio kopija pašalinta, o pokalbis liko tik peržiūrai.
          </p>
          <button className="btn btn--primary" onClick={() => navigate('/')}>
            Pasirinkti naują dokumentą
          </button>
        </div>
      </div>
    )
  }

  // needs_review
  const diff = job.diff
  return (
    <div className="page job-page">
      <main className="main-content">
        <div className="content-column">
          <div className="diff-header">
            <h2>Dokumentas paruoštas</h2>
            <p className="diff-meta">
              Iš viso pastraipų: {diff.total} &middot; <strong>Pakeista: {diff.changed}</strong>
            </p>
          </div>

          <div className="diff-actions">
            <a
              href={api.downloadUrl(jobId!)}
              className="btn btn--primary"
              download="pataisytas-dokumentas.docx"
            >
              Atsisiųsti sutvarkytą dokumentą
            </a>
            <button
              className="btn btn--secondary"
              onClick={() => {
                setShowRefine((v) => !v)
                setRefineNote('')
                setRefineError('')
              }}
            >
              {showRefine ? 'Uždaryti' : 'Reikia dar vieno pakeitimo'}
            </button>
            <button className="btn btn--ghost" onClick={() => navigate('/')}>
              Naujas dokumentas
            </button>
          </div>

          {showRefine && (
            <div className="refine-panel">
              <h3>Kas dar turėtų būti pakeista?</h3>
              <textarea
                className="textarea"
                rows={3}
                value={refineNote}
                onChange={(e) => setRefineNote(e.target.value)}
                placeholder="Pavyzdžiui: trečioje pastraipoje dar liko žymės…"
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
                  {refine.isPending ? 'Tvarkoma…' : 'Pataisyti dokumentą'}
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
