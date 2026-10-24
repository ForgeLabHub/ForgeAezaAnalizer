import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, getToken, setToken, setUnauthorizedListener } from './api'

interface AuthState {
  email: string | null
  ready: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setUnauthorizedListener(() => {
      setToken(null)
      setEmail(null)
    })
    return () => {
      setUnauthorizedListener(null)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function restore() {
      try {
        if (!getToken()) {
          const token = await api.refresh()
          setToken(token.access_token)
        }
        const me = await api.me()
        if (!cancelled) setEmail(me.email)
      } catch {
        setToken(null)
      } finally {
        if (!cancelled) setReady(true)
      }
    }
    void restore()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (loginEmail: string, password: string) => {
    const result = await api.login(loginEmail, password)
    setToken(result.access_token)
    const me = await api.me()
    setEmail(me.email)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // A failed logout call must not trap the user in the app.
    }
    setToken(null)
    setEmail(null)
  }, [])

  const value = useMemo(() => ({ email, ready, login, logout }), [email, ready, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
