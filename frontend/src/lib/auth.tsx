import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api, bootstrapSession, setAccessToken, setAuthLostHandler } from './api'
import { hasPermission, type Action } from './permissions'

export interface User {
  id: string
  email: string
  full_name: string
  role: string
  permissions: string[]
  preferences: { theme?: 'light' | 'dark'; density?: 'comfortable' | 'compact' }
  is_active: boolean
}

interface TokenResponse {
  access_token: string
  user: User
}

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  setUser: (u: User) => void
  can: (module: string, action: Action) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setAuthLostHandler(() => {
      setAccessToken(null)
      setUser(null)
    })
    // Restaura la sesión con la cookie de refresco (el access token vive solo en memoria).
    void (async () => {
      const token = await bootstrapSession()
      if (token) {
        try {
          setUser(await api.get<User>('/auth/me'))
        } catch {
          setAccessToken(null)
        }
      }
      setLoading(false)
    })()
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const data = await api.post<TokenResponse>('/auth/login', { email, password })
    setAccessToken(data.access_token)
    setUser(data.user)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } finally {
      setAccessToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login,
      logout,
      setUser,
      can: (module, action) => (user ? hasPermission(user.permissions, module, action) : false),
    }),
    [user, loading, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth debe usarse dentro de AuthProvider')
  return ctx
}
