import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'

function shortText(text: string) {
  return text.length > 58 ? `${text.slice(0, 58)}…` : text
}

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { data: jobs } = useQuery({
    queryKey: ['job-history'],
    queryFn: api.listJobs,
  })

  function logout() {
    api.logout().then(() => {
      queryClient.clear()
      navigate('/login', { replace: true })
    })
  }

  return (
    <div className="workspace">
      <aside className="workspace-sidebar">
        <button className="workspace-brand" onClick={() => navigate('/')} aria-label="Į pradžios puslapį">
          <span className="workspace-brand__mark">D</span>
          <span>Dokumentai</span>
        </button>

        <button className="new-document-button" onClick={() => navigate('/')}>
          <span aria-hidden="true">+</span> Naujas dokumentas
        </button>

        <div className="sidebar-heading">Ankstesni pokalbiai</div>
        <nav className="sidebar-history" aria-label="Ankstesni dokumentai">
          {jobs?.length ? jobs.slice(0, 30).map((job) => {
            const isActive = job.status === 'running' || job.status === 'needs_clarification'
            const destination = isActive ? `/jobs/${job.id}` : `/istorija/${job.id}`
            const active = location.pathname === destination
            return (
              <button
                className={`sidebar-history__item${active ? ' sidebar-history__item--active' : ''}`}
                key={job.id}
                onClick={() => navigate(destination)}
                aria-current={active ? 'page' : undefined}
                title={job.instruction}
              >
                {shortText(job.instruction)}
              </button>
            )
          }) : <p className="sidebar-history__empty">Dar nėra išsaugotų pokalbių.</p>}
        </nav>

        <div className="sidebar-footer">
          <button className="sidebar-link" onClick={() => navigate('/istorija')}>Visi dokumentai</button>
          <button className="sidebar-link" onClick={logout}>Atsijungti</button>
        </div>
      </aside>
      <main className="workspace-main">{children}</main>
    </div>
  )
}
