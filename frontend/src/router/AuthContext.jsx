import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api/client.js'

const AuthContext = createContext({
  studentAuth: { authenticated: false, state: 'unauthenticated' },
  studentSession: null,
  refreshStudentAuth: async () => {},
  studentLogout: async () => {},

  adminAuth: null,
  adminToken: null,
  setAdminSession: () => {},
  adminLogout: async () => {},

  sessionExpired: false,
  clearSessionExpired: () => {},
})

export function AuthProvider({ children }) {
  // Student Auth State (null indicates initial check in progress)
  const [studentAuth, setStudentAuth] = useState(null)
  const [studentSession, setStudentSession] = useState(null)
  const [sessionExpired, setSessionExpired] = useState(false)

  // Admin Auth State (in-memory for maximum security, optionally cached per window session)
  const [adminToken, setAdminToken] = useState(() => {
    if (typeof window !== 'undefined' && window.sessionStorage) {
      return window.sessionStorage.getItem('vwd_admin_token') || null
    }
    return null
  })
  const [adminAuth, setAdminAuth] = useState(() => {
    if (typeof window !== 'undefined' && window.sessionStorage) {
      const stored = window.sessionStorage.getItem('vwd_admin_user')
      try {
        return stored ? JSON.parse(stored) : null
      } catch {
        return null
      }
    }
    return null
  })

  // Refresh student auth from server authority
  const refreshStudentAuth = useCallback(async () => {
    try {
      const statusRes = await api.get('/auth/status')
      setStudentAuth(statusRes || { authenticated: false, state: 'unauthenticated' })

      if (statusRes?.authenticated) {
        try {
          const sessRes = await api.get('/auth/session')
          setStudentSession(sessRes)
        } catch {
          setStudentSession(null)
        }
      } else {
        setStudentSession(null)
      }
    } catch (err) {
      if (err?.status === 401) {
        setStudentAuth({ authenticated: false, state: 'unauthenticated' })
        setStudentSession(null)
      } else {
        // For transient errors, 429 rate limits, or network timeouts:
        // Do not invalidate an already-authenticated session.
        setStudentAuth((prev) => prev ?? { authenticated: false, state: 'unauthenticated' })
      }
    }
  }, [])

  // Check student auth on mount
  useEffect(() => {
    refreshStudentAuth()
  }, [refreshStudentAuth])

  // React to 401 Unauthorized events from api client
  useEffect(() => {
    const handleUnauthorized = (e) => {
      const url = e?.detail?.url || ''
      if (url.includes('/admin/')) return
      // Ignore 401s from login or verification attempts (invalid credentials are not expired sessions)
      if (url.includes('/auth/login') || url.includes('/auth/verify-otp')) return
      setStudentAuth({ authenticated: false, state: 'unauthenticated' })
      setStudentSession(null)
      setSessionExpired(true)
    }
    window.addEventListener('vwd:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('vwd:unauthorized', handleUnauthorized)
  }, [])

  // Student Logout
  const studentLogout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // Ignore network failures on logout
    }
    setStudentAuth({ authenticated: false, state: 'unauthenticated' })
    setStudentSession(null)
  }, [])

  // Admin Session Setter
  const setAdminSession = useCallback((token, user) => {
    setAdminToken(token)
    setAdminAuth(user)
    if (typeof window !== 'undefined' && window.sessionStorage) {
      if (token) window.sessionStorage.setItem('vwd_admin_token', token)
      else window.sessionStorage.removeItem('vwd_admin_token')
      if (user) window.sessionStorage.setItem('vwd_admin_user', JSON.stringify(user))
      else window.sessionStorage.removeItem('vwd_admin_user')
    }
  }, [])

  // Admin Logout
  const adminLogout = useCallback(async () => {
    if (adminToken) {
      try {
        await api.post('/admin/auth/logout', {}, {
          headers: { Authorization: `Bearer ${adminToken}` }
        })
      } catch {
        // Ignore logout transport errors
      }
    }
    setAdminSession(null, null)
  }, [adminToken, setAdminSession])

  const clearSessionExpired = useCallback(() => {
    setSessionExpired(false)
  }, [])

  const value = {
    studentAuth,
    studentSession,
    refreshStudentAuth,
    studentLogout,

    adminAuth,
    adminToken,
    setAdminSession,
    adminLogout,

    sessionExpired,
    clearSessionExpired,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}

export default AuthContext
