import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import FileDropzone from '../components/FileDropzone'

const EXAMPLES = [
  {
    label: 'Testas: <B>…<D> žymės',
    text: 'Raskite kiekvieną <B>…<D> žymių porą, tekstą tarp žymių padarykite paryškintą, o pačias žymes pašalinkite.',
  },
  { label: 'Paryškinti svarbius metus', text: 'Paryškinkite visus 1918 metų paminėjimus.' },
  { label: 'Pakeisti metus', text: 'Visus 2023 metų paminėjimus pakeiskite į 2024 metus.' },
  { label: 'Pašalinti puslapių lūžius', text: 'Pašalinkite visus ranka įterptus puslapių lūžius.' },
  { label: 'Sutvarkyti antraštes', text: 'Visoms pirmojo lygio antraštėms nustatykite 16 pt šriftą.' },
]

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null)
  const [instruction, setInstruction] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const qc = useQueryClient()

  const submit = useMutation({
    mutationFn: () => api.createJob(file!, instruction),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ['job-history'] })
      navigate(`/jobs/${job.id}`)
    },
    onError: (e) => {
      console.error('Nepavyko sukurti dokumento užduoties:', e)
      setError('Dokumento nepavyko pradėti tvarkyti. Patikrinkite, ar pasirinkote Word dokumentą, ir bandykite dar kartą.')
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    submit.mutate()
  }

  return (
    <div className="page home-page">
      <main className="main-content">
        <div className="content-column">
          <div className="greeting">
            <p className="greeting__eyebrow">Dokumentų redagavimo erdvė</p>
            <h1 className="greeting__title">Ką šiandien pataisysime?</h1>
            <p className="greeting__sub">Pasirinkite Word dokumentą ir parašykite, ką norėtumėte jame pakeisti.</p>
          </div>

          <form onSubmit={handleSubmit} className="stack">
            <div className="field">
              <label>1. Pasirinkite Word dokumentą</label>
              <FileDropzone value={file} onChange={setFile} />
            </div>

            <div className="field">
              <label htmlFor="instruction">2. Parašykite, ką norite pakeisti</label>
              <textarea
                id="instruction"
                className="textarea"
                rows={5}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Pavyzdžiui: Paryškinkite visus 1918 metų paminėjimus."
                required
              />
              <p className="field__help">Rašykite savais žodžiais. Jei kas nors bus neaišku, paklausime.</p>
              <div className="example-actions">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex.label}
                    type="button"
                    className="btn btn--secondary"
                    onClick={() => setInstruction(ex.text)}
                  >
                    {ex.label}
                  </button>
                ))}
              </div>
            </div>

            {error && <p className="error-text">{error}</p>}

            <div>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={submit.isPending || !file || !instruction.trim()}
                style={{ minWidth: 120 }}
              >
                {submit.isPending ? 'Pradedama…' : 'Tvarkyti dokumentą'}
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  )
}
