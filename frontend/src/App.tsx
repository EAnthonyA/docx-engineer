import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api, ApiError } from './api/client'
import HomePage from './pages/HomePage'
import HistoryPage from './pages/HistoryPage'
import HistoryDetailPage from './pages/HistoryDetailPage'
import JobPage from './pages/JobPage'
import LoginPage from './pages/LoginPage'
import NotFoundPage from './pages/NotFoundPage'
import WorkspaceLayout from './components/WorkspaceLayout'

function AuthGuard({ children }: { children: ReactNode }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['me'],
    queryFn: () => api.me(),
    retry: false,
  })

  if (isLoading) return null

  if (error instanceof ApiError && error.status === 401) {
    return <Navigate to="/login" replace />
  }

  if (!data) return <Navigate to="/login" replace />

  return <>{children}</>
}

function WorkspacePage({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <WorkspaceLayout>{children}</WorkspaceLayout>
    </AuthGuard>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <WorkspacePage><HomePage /></WorkspacePage>
          }
        />
        <Route
          path="/jobs/:jobId"
          element={
            <WorkspacePage><JobPage /></WorkspacePage>
          }
        />
        <Route
          path="/istorija"
          element={
            <WorkspacePage><HistoryPage /></WorkspacePage>
          }
        />
        <Route
          path="/istorija/:jobId"
          element={
            <WorkspacePage><HistoryDetailPage /></WorkspacePage>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
