import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api, ApiError } from './api/client'
import HomePage from './pages/HomePage'
import JobPage from './pages/JobPage'
import LoginPage from './pages/LoginPage'

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

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <AuthGuard>
              <HomePage />
            </AuthGuard>
          }
        />
        <Route
          path="/jobs/:jobId"
          element={
            <AuthGuard>
              <JobPage />
            </AuthGuard>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
