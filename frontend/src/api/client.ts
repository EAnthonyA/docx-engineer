import type { Job } from './types'

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    ...options,
  })

  if (res.status === 401) {
    throw new ApiError(401, 'Not authenticated')
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      message = body.detail ?? message
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, message)
  }

  return res.json() as Promise<T>
}

export const api = {
  login(password: string) {
    return request<{ ok: boolean }>('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    })
  },

  logout() {
    return request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' })
  },

  me() {
    return request<{ user: string }>('/api/auth/me')
  },

  createJob(file: File, instruction: string) {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('instruction', instruction)
    return request<Job>('/api/jobs', { method: 'POST', body: fd })
  },

  getJob(jobId: string) {
    return request<Job>(`/api/jobs/${jobId}`)
  },

  refineJob(jobId: string, note: string) {
    return request<Job>(`/api/jobs/${jobId}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note }),
    })
  },

  downloadUrl(jobId: string) {
    return `/api/jobs/${jobId}/download`
  },
}

export { ApiError }
