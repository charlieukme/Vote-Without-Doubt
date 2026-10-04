import { useState, useEffect } from 'react'
import './Face.css'

const API_BASE = 'http://localhost:5000/api'

function Face() {
  const [status, setStatus] = useState({ enrolled: false, consent_given: false })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [challenge, setChallenge] = useState(null)
  
  const getStatus = async () => {
    try {
      const res = await fetch(API_BASE + '/face/status', { credentials: 'include' })
      if (res.ok) {
        setStatus(await res.json())
      }
    } catch (e) {
      setError('Status check failed')
    }
  }
  
  useEffect(() => { getStatus() }, [])
  
  const giveConsent = async () => {
    setLoading(true)
    try {
      const res = await fetch(API_BASE + '/face/consent', { method: 'POST', credentials: 'include', headers: {'Content-Type':'application/json'} })
      if (res.ok) {
        await getStatus()
      }
    } catch (e) {
      setError('Consent failed')
    }
    setLoading(false)
  }
  
  const startEnroll = async () => {
    setLoading(true)
    try {
      const res = await fetch(API_BASE + '/face/challenge/enroll', { method: 'POST', credentials: 'include' })
      if (res.ok) {
        setChallenge(await res.json())
      }
    } catch (e) {
      setError('Challenge failed')
    }
    setLoading(false)
  }
  
  const completeEnroll = async () => {
    if (!challenge) return
    setLoading(true)
    try {
      const res = await fetch(API_BASE + '/face/enroll', {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ challenge_id: challenge.challenge_id, frames: [1,2,3], sequence: ['LEFT','RIGHT'] })
      })
      if (res.ok) {
        setChallenge(null)
        await getStatus()
      } else {
        const d = await res.json()
        setError(d.error || 'Enroll failed')
      }
    } catch (e) {
      setError('Enroll failed')
    }
    setLoading(false)
  }
  
  return (
    <div className="face-container">
      <h2>Face Recognition + Liveness (Phase 5)</h2>
      <div className="status-box">
        <div>Enrolled: {status.enrolled ? 'Yes' : 'No'}</div>
        <div>Consent: {status.consent_given ? 'Yes' : 'No'}</div>
      </div>
      {!status.consent_given && <button onClick={giveConsent} disabled={loading}>Give Biometric Consent</button>}
      {status.consent_given && !status.enrolled && !challenge && <button onClick={startEnroll} disabled={loading}>Start Face Enrollment</button>}
      {challenge && <button onClick={completeEnroll} disabled={loading}>Complete Enrollment (Mock)</button>}
      {error && <div className="error">{error}</div>}
    </div>
  )
}

export default Face


