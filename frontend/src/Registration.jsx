import { useState } from 'react'
import './Auth.css'

function Registration() {
  const [usn, setUsn] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [step, setStep] = useState('check')
  const [message, setMessage] = useState('')

  const requestOtp = async () => {
    try {
      const res = await fetch('/api/registration/request-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include'
      })
      const data = await res.json()
      setMessage(res.ok ? 'OTP sent to registered college email' : (data.message || 'OTP request failed'))
    } catch (err) {
      setMessage('OTP request failed')
    }
  }

  const checkEligibility = async (e) => {
    e.preventDefault()
    setMessage('')
    try {
      const res = await fetch('/api/registration/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ usn })
      })
      const data = await res.json()
      if (res.ok && data.eligible) {
        setStep('otp')
        await requestOtp()
      } else {
        setMessage(data.message || 'Not eligible or not found')
      }
    } catch (err) {
      setMessage('Check failed')
    }
  }

  const verifyOtp = async (e) => {
    e.preventDefault()
    try {
      const res = await fetch('/api/registration/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ otp })
      })
      const data = await res.json()
      if (res.ok) {
        setStep('complete')
        setMessage('Email verified')
      } else {
        setMessage(data.message || 'OTP verification failed')
      }
    } catch (err) {
      setMessage('OTP verification failed')
    }
  }

  const completeReg = async (e) => {
    e.preventDefault()
    try {
      const res = await fetch('/api/registration/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password })
      })
      const data = await res.json()
      if (res.ok) {
        setStep('done')
        setMessage('Registration complete')
      } else {
        setMessage(data.message || 'Registration failed')
      }
    } catch (err) {
      setMessage('Registration failed')
    }
  }

  return (
    <div className="auth-container" style={{marginTop:'1.5rem'}}>
      <h2 className="auth-title">Registration (Phase 3)</h2>
      {message && <div className="auth-status">{message}</div>}
      {step === 'check' && (
        <form onSubmit={checkEligibility} className="auth-form">
          <input className="auth-input" placeholder="USN" value={usn} onChange={e => setUsn(e.target.value)} required />
          <button className="auth-btn" type="submit">Check Eligibility</button>
        </form>
      )}
      {step === 'otp' && (
        <form onSubmit={verifyOtp} className="auth-form">
          <input className="auth-input" placeholder="Enter OTP (check Mailpit)" value={otp} onChange={e => setOtp(e.target.value)} required />
          <button className="auth-btn" type="submit">Verify OTP</button>
        </form>
      )}
      {step === 'complete' && (
        <form onSubmit={completeReg} className="auth-form">
          <input className="auth-input" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} required />
          <input className="auth-input" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
          <button className="auth-btn" type="submit">Complete Registration</button>
        </form>
      )}
      {step === 'done' && (
        <div>Registration successful. You can now login.</div>
      )}
    </div>
  )
}

export default Registration
