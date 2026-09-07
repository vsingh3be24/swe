import axios, { AxiosError } from 'axios'

// Single axios instance. Base URL is the same-origin /api path; in dev the Vite
// proxy forwards it to the FastAPI backend at 127.0.0.1:8000.
export const api = axios.create({
  baseURL: '/api',
})

const TOKEN_KEY = 'finalsay_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

// Attach the bearer token to every request when present.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Turn backend error payloads into readable messages for the UI.
export function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
    }
    if (err.message) return err.message
  }
  if (err instanceof Error) return err.message
  return 'Unexpected error'
}
