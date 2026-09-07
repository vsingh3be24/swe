import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, getToken, setToken } from '../api/client'
import type { Token, UserOut } from '../api/types'

interface AuthState {
  user: UserOut | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (
    email: string,
    password: string,
    displayName?: string,
  ) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null)
  const [loading, setLoading] = useState(true)

  const loadMe = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const res = await api.get<UserOut>('/auth/me')
      setUser(res.data)
    } catch {
      setToken(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
  }, [loadMe])

  const login = useCallback(async (email: string, password: string) => {
    // OAuth2 password flow: form-encoded body with `username`/`password`.
    const body = new URLSearchParams()
    body.set('username', email)
    body.set('password', password)
    const res = await api.post<Token>('/auth/login', body, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    setToken(res.data.access_token)
    const me = await api.get<UserOut>('/auth/me')
    setUser(me.data)
  }, [])

  const register = useCallback(
    async (email: string, password: string, displayName?: string) => {
      // Public registration always creates a student account server-side; no
      // role is sent (privileged roles are provisioned by an admin/seed).
      await api.post('/auth/register', {
        email,
        password,
        display_name: displayName || null,
      })
      // Registration does not return a token; log in immediately after.
      await login(email, password)
    },
    [login],
  )

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
