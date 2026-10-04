import { useState, useEffect } from 'react'
import './Auth.css'

function Auth() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [status, setStatus] = useState(null)
  const [step, setStep] = useState('login') // login, otp

  const checkStatus = async () => {
    try {
      const res = await fetch('/api/auth/status', { credentials: 'include' })
      const data = await res.json()
      setStatus(data)
    } catch (e) {
      setStatus({ authenticated: false })
    }
  }

  useEffect(() => { checkStatus() }, [])

  const login = async (e) => {
    e.preventDefault()
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password })
    })
    const data = await res.json()
    if (res.ok) {
      setStep('otp')
      await fetch('/api/auth/request-otp', { method: 'POST', credentials: 'include' })
    }
  }

  const verifyOtp = async (e) => {
    e.preventDefault()
    const res = await fetch('/api/auth/verify-otp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ otp })
    })
    if (res.ok) {
      checkStatus()
      setStep('done')
    }
  }

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    checkStatus()
    setStep('login')
  }

  return (
    <div className="auth-container">
      <h2 className="auth-title">Auth Core (Phase 2)</h2>
      <div className="auth-status">
        Status: {status?.authenticated ? 'AUTHORIZED' : status?.state || 'unauthenticated'}
      </div>
      {step === 'login' && !status?.authenticated && (
        <form onSubmit={login} className="auth-form">
          <input className="auth-input" placeholder="username" value={username} onChange={e => setUsername(e.target.value)} />
          <input className="auth-input" type="password" placeholder="password" value={password} onChange={e => setPassword(e.target.value)} />
          <button className="auth-btn" type="submit">Login</button>
        </form>
      )}
      {step === 'otp' && (
        <form onSubmit={verifyOtp} className="auth-form">
          <input className="auth-input" placeholder="OTP" value={otp} onChange={e => setOtp(e.target.value)} />
          <button className="auth-btn" type="submit">Verify OTP</button>
        </form>
      )}
      {status?.authenticated && (
        <button className="auth-btn" onClick={logout}>Logout</button>
      )}
    </div>
  )
}
export default Auth
