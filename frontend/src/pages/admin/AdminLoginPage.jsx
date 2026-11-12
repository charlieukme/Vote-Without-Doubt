import React, { useState } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'
import '../../Auth.css'

export default function AdminLoginPage() {
  const { navigate } = useRouter()
  const { setAdminSession } = useAuth()

  const [adminId, setAdminId] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [totpCode, setTotpCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)

    try {
      const res = await api.post('/admin/auth/login', {
        admin_id: adminId.trim(),
        password,
        totp_code: totpCode.trim(),
      })

      if (res?.token && res?.admin) {
        setAdminSession(res.token, res.admin)
        navigate('/admin/dashboard')
      } else {
        setError('Authentication succeeded but invalid token received.')
      }
    } catch (err) {
      setError(err.message || 'Admin authentication failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-container admin-login-page" style={{ maxWidth: '420px', margin: '2.5rem auto', padding: '0 1rem' }}>
      <div className="card" style={{ border: '4px solid #000', boxShadow: '6px 6px 0px #000', background: 'var(--neo-cream, #FFFDF5)' }}>
        <span className="badge" style={{ background: 'var(--neo-red, #FF6B6B)', color: '#000', fontWeight: 900, marginBottom: '0.75rem' }}>
          CHIEF / DEPUTY ELECTION OFFICER & AUDITOR CONSOLE
        </span>
        <h2 className="card-title" style={{ margin: '0 0 0.5rem 0' }}>ADMIN LOGIN</h2>
        <p style={{ fontSize: '0.85rem', color: '#4B5563', marginBottom: '1.25rem' }}>
          Restricted governance console for Chief Election Officer, Deputy Election Officer, and Auditor. Requires Admin ID, Master Password, and 6-digit Authenticator TOTP.
        </p>

        {error && (
          <div className="alert-box alert-error" style={{ marginBottom: '1rem' }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label htmlFor="admin-id-input" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Admin ID
            </label>
            <input
              id="admin-id-input"
              name="admin_id"
              type="text"
              autoComplete="username"
              className="auth-input"
              placeholder="e.g. OFFICER_01"
              value={adminId}
              onChange={(e) => setAdminId(e.target.value)}
              required
            />
          </div>

          <div>
            <label htmlFor="admin-password-input" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Master Password
            </label>
            <div className="password-input-wrap">
              <input
                id="admin-password-input"
                name="admin_password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                className="auth-input"
                placeholder="Enter master password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="password-toggle-btn"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="admin-totp-input" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Authenticator Code (TOTP)
            </label>
            <input
              id="admin-totp-input"
              name="admin_totp"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              placeholder="000000"
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
              style={{ fontFamily: 'monospace', fontWeight: 800, letterSpacing: '0.15em', textAlign: 'center' }}
              required
            />
          </div>

          <button
            className="btn btn-primary"
            type="submit"
            disabled={busy || !adminId || !password || totpCode.length !== 6}
            style={{ marginTop: '0.5rem', width: '100%', padding: '0.75rem', fontWeight: 900 }}
          >
            {busy ? 'Authenticating...' : 'SIGN IN'}
          </button>
        </form>

        <div style={{ marginTop: '1rem', padding: '0.65rem 0.85rem', background: '#F3F4F6', border: '1px solid #D1D5DB', fontSize: '0.775rem', color: '#4B5563', lineHeight: 1.4 }}>
          <strong>Browser Autofill Note:</strong> If Chrome suggests student credentials on this administrative form, open <code>chrome://password-manager</code> in your browser to remove stored student credentials for this origin.
        </div>

        <div style={{ marginTop: '1.25rem', borderTop: '2px solid #000', paddingTop: '1rem', textAlign: 'center' }}>
          <button className="link-button" onClick={() => navigate('/')} style={{ fontSize: '0.85rem', fontWeight: 800 }}>
            &larr; Return to Student Portal
          </button>
        </div>
      </div>
    </div>
  )
}
