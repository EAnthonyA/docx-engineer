import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import FileDropzone from '../components/FileDropzone'

const EXAMPLES = [
  'Find every <B>…<D> pattern, bold the text between the tags, and remove the tags.',
  'Remove all manual page breaks from the document.',
  'Change every occurrence of "2023" to "2024".',
  'Make all headings with style "Heading 1" use font size 16pt.',
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
      navigate(`/jobs/${job.id}`)
    },
    onError: (e) => {
      setError((e as Error).message)
    },
  })

  function handleLogout() {
    api.logout().then(() => {
      qc.clear()
      navigate('/login', { replace: true })
    })
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    submit.mutate()
  }

  return (
    <div className="page">
      <header className="header">
        <div className="container header__inner">
          <span className="logo">docx-engineer</span>
          <button className="btn btn--ghost" onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <main className="main-content">
        <div className="container">
          <form onSubmit={handleSubmit} className="stack">
            <div className="field">
              <label>Your document</label>
              <FileDropzone value={file} onChange={setFile} />
            </div>

            <div className="field">
              <label htmlFor="instruction">What would you like to do?</label>
              <textarea
                id="instruction"
                className="textarea"
                rows={5}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder={EXAMPLES[0]}
                required
              />
              <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    className="btn btn--secondary"
                    style={{ height: 32, fontSize: 12, padding: '0 10px', borderRadius: 8 }}
                    onClick={() => setInstruction(ex)}
                  >
                    {ex.slice(0, 40)}…
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
                {submit.isPending ? 'Starting…' : 'Run'}
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  )
}
