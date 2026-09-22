import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

export default function LoginPage() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const qc = useQueryClient()

  const login = useMutation({
    mutationFn: () => api.login(password),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me'] })
      navigate('/', { replace: true })
    },
    onError: () => {
      setError('Slaptažodis netinka. Bandykite dar kartą.')
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    login.mutate()
  }

  return (
    <div className="login-page">
      <div className="card login-card">
        <div className="login-logo">docx-engineer</div>
        <div className="login-tagline">Ramus ir paprastas būdas sutvarkyti Word dokumentus.</div>

        <form onSubmit={handleSubmit} className="stack">
          <div className="field">
            <label htmlFor="password">Slaptažodis</label>
            <input
              id="password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoFocus
              autoComplete="current-password"
              required
            />
          </div>

          {error && <p className="error-text">{error}</p>}

          <button
            type="submit"
            className="btn btn--primary"
            disabled={login.isPending || !password}
          >
            {login.isPending ? 'Jungiamasi…' : 'Prisijungti'}
          </button>
        </form>
      </div>
    </div>
  )
}
