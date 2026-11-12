import { useState, useEffect, useCallback } from 'react'
import './Auth.css'
import { api } from './api/client.js'

/**
 * Phase 2 authentication UI.
 *
 * Rules enforced here:
 * - the server is the only authority on authentication state. This component
 *   never sets an "authenticated" flag of its own; it renders whatever
 *   /auth/status reports;
 * - the password and the OTP are held in component state only for the lifetime
 *   of the form. They are cleared as soon as the step completes, and are never
 *   written to localStorage, sessionStorage, cookies or the URL;
 * - the two-factor order is explicit: password, then emailed OTP;
 * - the cookie is the credential, so requests rely on `credentials: 'include'`
 *   which the shared client already sets.
 */
function Auth({ onSuccess } = {}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState('login') // login -> otp -> authenticated | forgot_request -> forgot_reset
  const [forgotId, setForgotId] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [resetOtp, setResetOtp] = useState('')

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.get('/auth/status'))
    } catch {
      setStatus({ authenticated: false })
    }
  }, [])

  useEffect(() => {
    refreshStatus()
  }, [refreshStatus])

  const authenticated = status?.authenticated === true

  const login = async (e) => {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await api.post('/auth/login', { username, password })
      // The password has been accepted; it is no longer needed in memory.
      setPassword('')
      const requested = await api.post('/auth/request-otp')
      setNotice(requested.message || 'OTP sent to your registered email')
      setStep('otp')
      await refreshStatus()
    } catch (err) {
      setError(err.message || 'Login failed')
      setPassword('')
    }
    setBusy(false)
  }

  const verifyOtp = async (e) => {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await api.post('/auth/verify-otp', { otp })
      setOtp('')
      setStep('authenticated')
      setNotice('Signed in')
      if (onSuccess) {
        await onSuccess()
      } else {
        await refreshStatus()
      }
    } catch (err) {
      setError(err.message || 'Verification failed')
      setOtp('')
    }
    setBusy(false)
  }

  const logout = async () => {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await api.post('/auth/logout')
      setStep('login')
      setOtp('')
      setPassword('')
      await refreshStatus()
    } catch (err) {
      setError(err.message || 'Logout failed')
    }
    setBusy(false)
  }

  const resend = async () => {
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const requested = await api.post('/auth/request-otp')
      setNotice(requested.message || 'A new OTP was sent')
    } catch (err) {
      setError(err.message || 'Could not send an OTP')
    }
    setBusy(false)
  }

  const requestForgotPassword = async (e) => {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const res = await api.post('/auth/forgot-password/request', { identifier: forgotId })
      setResetToken(res.reset_token || '')
      setNotice(res.message || 'Verification code sent to your registered email.')
      setStep('forgot_reset')
    } catch (err) {
      setError(err.message || 'Unable to process request.')
    }
    setBusy(false)
  }

  const completePasswordReset = async (e) => {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      const res = await api.post('/auth/forgot-password/reset', {
        reset_token: resetToken,
        otp: resetOtp,
        new_password: newPassword,
      })
      setNewPassword('')
      setResetOtp('')
      setResetToken('')
      setForgotId('')
      setNotice(res.message || 'Password reset successfully. Please log in.')
      setStep('login')
    } catch (err) {
      setError(err.message || 'Failed to reset password.')
      setNewPassword('')
    }
    setBusy(false)
  }

  return (
    <div className="auth-container">
      <h2 className="auth-title">Student Portal Authentication</h2>

      <div className="auth-status" role="status">
        Status: {authenticated ? 'AUTHORIZED' : status?.state || 'unauthenticated'}
      </div>

      {step === 'login' && !authenticated && (
        <form onSubmit={login} className="auth-form">
          <input
            className="auth-input"
            placeholder="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <input
            className="auth-input"
            type="password"
            placeholder="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button className="auth-btn" type="submit" disabled={busy}>
            {busy ? 'Working...' : 'Login'}
          </button>
          <button
            type="button"
            className="auth-btn"
            style={{ background: '#555', marginTop: '0.25rem' }}
            onClick={() => {
              setStep('forgot_request')
              setError('')
              setNotice('')
            }}
          >
            Forgot Password?
          </button>
        </form>
      )}

      {step === 'forgot_request' && !authenticated && (
        <form onSubmit={requestForgotPassword} className="auth-form">
          <p className="auth-hint">
            Enter your USN or Username. We will send a single-use verification code to your email.
          </p>
          <input
            className="auth-input"
            placeholder="USN or Username"
            value={forgotId}
            onChange={(e) => setForgotId(e.target.value)}
            required
          />
          <button className="auth-btn" type="submit" disabled={busy || !forgotId.trim()}>
            {busy ? 'Working...' : 'Send Reset Code'}
          </button>
          <button
            type="button"
            className="auth-btn"
            style={{ background: '#555' }}
            onClick={() => {
              setStep('login')
              setError('')
              setNotice('')
            }}
          >
            Back to Login
          </button>
        </form>
      )}

      {step === 'forgot_reset' && !authenticated && (
        <form onSubmit={completePasswordReset} className="auth-form">
          <p className="auth-hint">
            Enter the 6-digit code sent to your email and your new password (minimum 8 characters).
          </p>
          <input
            className="auth-input"
            placeholder="6-digit OTP"
            inputMode="numeric"
            maxLength={6}
            value={resetOtp}
            onChange={(e) => setResetOtp(e.target.value.replace(/\D/g, ''))}
            required
          />
          <input
            className="auth-input"
            type="password"
            placeholder="New password (min 8 chars)"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
          <button className="auth-btn" type="submit" disabled={busy || resetOtp.length !== 6 || newPassword.length < 8}>
            {busy ? 'Working...' : 'Reset Password'}
          </button>
          <button
            type="button"
            className="auth-btn"
            style={{ background: '#555' }}
            onClick={() => {
              setStep('login')
              setError('')
              setNotice('')
              setResetOtp('')
              setNewPassword('')
            }}
          >
            Cancel
          </button>
        </form>
      )}

      {step === 'otp' && !authenticated && (
        <form onSubmit={verifyOtp} className="auth-form">
          <p className="auth-hint">
            Enter the 6-digit code we emailed you. It expires in 5 minutes.
          </p>
          <input
            className="auth-input"
            placeholder="OTP"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
            required
          />
          <button className="auth-btn" type="submit" disabled={busy || otp.length !== 6}>
            {busy ? 'Working...' : 'Verify OTP'}
          </button>
          <button
            className="auth-btn"
            type="button"
            onClick={resend}
            disabled={busy}
          >
            Send a new code
          </button>
          <button
            className="auth-btn"
            type="button"
            onClick={() => {
              setStep('login')
              setOtp('')
            }}
            disabled={busy}
          >
            Back
          </button>
        </form>
      )}

      {authenticated && (
        <button className="auth-btn" onClick={logout} disabled={busy}>
          {busy ? 'Working...' : 'Logout'}
        </button>
      )}

      {notice && <div className="auth-status" role="status">{notice}</div>}
      {error && <div className="error" role="alert">{error}</div>}
    </div>
  )
}

export default Auth
