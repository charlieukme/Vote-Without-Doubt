import { useState } from 'react'
import './Auth.css'
import { api } from './api/client.js'

function maskEmail(val) {
  if (!val || !val.includes('@')) return '***'
  const [user, domain] = val.split('@')
  if (user.length <= 1) return `${user}***@${domain}`
  if (user.length === 2) return `${user[0]}***@${domain}`
  return `${user[0]}***${user[user.length - 1]}@${domain}`
}

/**
 * Phase 3 / Phase 16 registration UI (electoral roll + eligibility + verified email).
 *
 * Rules enforced here:
 * - the server is authoritative. This component never declares eligibility,
 *   email verification or completion; it renders only what the API reports;
 * - the voter identity is never chosen here. Only a USN is submitted, and the
 *   roll decides who the voter is;
 * - the student enters their email, and the backend dispatches a single-use OTP
 *   to that entered address;
 * - the password and the OTP live in component state only for the lifetime of
 *   their form. Neither is written to localStorage, sessionStorage, cookies or
 *   the URL, and both are cleared as soon as their step completes;
 * - every failure is shown verbatim from the API so the generic,
 *   non-enumerating message from the server is what the user sees.
 */
function Registration({ onPasswordCreated, onStepChange }) {
  const [usn, setUsn] = useState('')
  const [email, setEmail] = useState('')
  const [maskedEmail, setMaskedEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [otp, setOtp] = useState('')
  const [step, setStep] = useState('check') // check -> email -> otp -> complete -> done
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const checkEligibility = async (e) => {
    e.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const data = await api.post('/registration/check', { usn })
      if (!data.eligible) {
        setError(data.message)
        return
      }
      setStep('email')
      setMessage('USN verified on the electoral roll. Please enter your email to receive an OTP.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const requestOtp = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const data = await api.post('/registration/request-otp', { email })
      setMaskedEmail(data.email_masked || maskEmail(email))
      setStep('otp')
      setMessage('OTP sent to your email address')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const verifyOtp = async (e) => {
    e.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.post('/registration/verify-otp', { otp })
      setOtp('')
      setStep('complete')
      setMessage('Email verified. Choose your username and password.')
    } catch (err) {
      setError(err.message)
      setOtp('')
    } finally {
      setBusy(false)
    }
  }

  const complete = async (e) => {
    e.preventDefault()
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (confirmPassword && password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const res = await api.post('/registration/complete', { username, password })
      setPassword('')
      setConfirmPassword('')
      if (onPasswordCreated) {
        onPasswordCreated({ username, res })
      } else {
        setStep('done')
        setMessage('Account credentials created successfully.')
      }
    } catch (err) {
      setError(err.message)
      setPassword('')
      setConfirmPassword('')
    } finally {
      setBusy(false)
    }
  }

  const startOver = () => {
    setStep('check')
    setUsn('')
    setEmail('')
    setMaskedEmail('')
    setUsername('')
    setPassword('')
    setConfirmPassword('')
    setOtp('')
    setError('')
    setMessage('')
  }

  const hasMinLength = password.length >= 8
  const hasLetter = /[a-zA-Z]/.test(password)
  const hasNumber = /[0-9]/.test(password)
  const passwordsMatch = Boolean(password && confirmPassword && password === confirmPassword)
  const strengthScore = (hasMinLength ? 1 : 0) + (hasLetter && hasNumber ? 1 : 0) + (password.length >= 12 || /[^a-zA-Z0-9]/.test(password) ? 1 : 0)

  return (
    <div className="auth-container" style={{ marginTop: '1.5rem' }}>
      <h2 className="auth-title">Student Registration</h2>

      {message && <div className="auth-status" role="status">{message}</div>}

      {step === 'check' && (
        <form id="student-reg-eligibility-form" onSubmit={checkEligibility} className="auth-form" autoComplete="off">
          <p className="auth-hint">
            Step 1 (R1): Enter your college USN. Eligibility is checked against the official
            electoral roll.
          </p>
          <input
            id="student-reg-usn"
            name="student_electoral_usn"
            className="auth-input"
            type="text"
            placeholder="USN (e.g. 1XX23CS000)"
            autoComplete="off"
            data-lpignore="true"
            data-form-type="other"
            spellCheck="false"
            value={usn}
            onChange={(e) => setUsn(e.target.value.toUpperCase())}
            required
          />
          <button className="auth-btn" type="submit" disabled={busy || !usn}>
            {busy ? 'Checking...' : 'Check Eligibility'}
          </button>
        </form>
      )}

      {step === 'email' && (
        <form id="student-reg-email-form" onSubmit={requestOtp} className="auth-form" autoComplete="off">
          <p className="auth-hint">
            Step 2 (R2): Enter your email address. The backend dispatches
            a single-use 6-digit OTP to this address.
          </p>
          <input
            id="student-reg-email"
            name="student_college_email"
            className="auth-input"
            type="email"
            placeholder="College Email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value.trim().toLowerCase())}
            required
          />
          <button className="auth-btn" type="submit" disabled={busy || !email}>
            {busy ? 'Sending OTP...' : 'Send Verification OTP'}
          </button>
          <button className="auth-btn" type="button" onClick={startOver} disabled={busy}>
            Back
          </button>
        </form>
      )}

      {step === 'otp' && (
        <form id="student-reg-otp-form" onSubmit={verifyOtp} className="auth-form" autoComplete="off">
          <p className="auth-hint">
            Step 3 (R3): Enter the 6-digit code emailed to {maskedEmail || 'your email'}.
            It expires in 5 minutes.
          </p>
          <input
            id="student-reg-otp"
            name="student_verification_otp"
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
            {busy ? 'Verifying...' : 'Verify OTP'}
          </button>
          <button className="auth-btn" type="button" onClick={(e) => requestOtp(e)} disabled={busy}>
            Send a new code
          </button>
          <button className="auth-btn" type="button" onClick={() => { setStep('email'); setError(''); }} disabled={busy}>
            Back
          </button>
        </form>
      )}

      {step === 'complete' && (
        <form id="student-reg-credentials-form" onSubmit={complete} className="auth-form" autoComplete="off">
          <p className="auth-hint">
            Step 4 (R4): Your email is verified. Choose your username and password.
          </p>
          <div>
            <label htmlFor="student-reg-new-username" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Username
            </label>
            <input
              id="student-reg-new-username"
              name="student_registration_new_username"
              type="text"
              className="auth-input"
              placeholder="Choose Username"
              autoComplete="off"
              data-lpignore="true"
              data-form-type="other"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div>
            <label htmlFor="student-reg-new-password" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Password
            </label>
            <div className="password-input-wrap">
              <input
                id="student-reg-new-password"
                name="student_registration_new_password"
                className="auth-input"
                type={showPassword ? 'text' : 'password'}
                placeholder="Choose Password (min 8 chars)"
                autoComplete="new-password"
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
            <label htmlFor="student-reg-confirm-password" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Confirm Password
            </label>
            <div className="password-input-wrap">
              <input
                id="student-reg-confirm-password"
                name="student_registration_confirm_password"
                className="auth-input"
                type={showConfirm ? 'text' : 'password'}
                placeholder="Confirm Password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="password-toggle-btn"
                aria-label={showConfirm ? 'Hide confirm password' : 'Show confirm password'}
                onClick={() => setShowConfirm(!showConfirm)}
              >
                {showConfirm ? '🙈' : '👁'}
              </button>
            </div>
          </div>

          {password && (
            <div>
              <div className="strength-bar-container">
                <div className={`strength-segment ${strengthScore >= 1 ? (strengthScore === 1 ? 'active-weak' : strengthScore === 2 ? 'active-medium' : 'active-strong') : ''}`} />
                <div className={`strength-segment ${strengthScore >= 2 ? (strengthScore === 2 ? 'active-medium' : 'active-strong') : ''}`} />
                <div className={`strength-segment ${strengthScore >= 3 ? 'active-strong' : ''}`} />
              </div>
              <div className="password-checklist">
                <div className={`checklist-item ${hasMinLength ? 'valid' : 'invalid'}`}>
                  {hasMinLength ? '✓' : '○'} Minimum 8 characters
                </div>
                <div className={`checklist-item ${hasLetter && hasNumber ? 'valid' : 'invalid'}`}>
                  {hasLetter && hasNumber ? '✓' : '○'} Contains letters & numbers
                </div>
                {confirmPassword && (
                  <div className={`checklist-item ${passwordsMatch ? 'valid' : 'invalid'}`}>
                    {passwordsMatch ? '✓' : '○'} Passwords match
                  </div>
                )}
              </div>
            </div>
          )}

          <button className="auth-btn" type="submit" disabled={busy || !username || !password || (confirmPassword && password !== confirmPassword)}>
            {busy ? 'Creating account...' : 'Create Password'}
          </button>
          <button className="auth-btn" type="button" onClick={startOver} disabled={busy}>
            Back
          </button>
        </form>
      )}

      {step === 'done' && (
        <div className="auth-form">
          <p className="auth-hint">Credentials created. Ready for next step.</p>
          <button className="auth-btn" type="button" onClick={startOver}>
            Register another voter
          </button>
        </div>
      )}

      {error && <div className="error" role="alert">{error}</div>}
    </div>
  )
}

export default Registration