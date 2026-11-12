import React, { useState } from 'react'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'

export default function AdminVotersPage() {
  const { adminToken } = useAuth()
  const [verificationResult, setVerificationResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Operational Voter Lookup State
  const [lookupUsn, setLookupUsn] = useState('')
  const [lookupResult, setLookupResult] = useState(null)
  const [lookupError, setLookupError] = useState('')
  const [busyLookup, setBusyLookup] = useState(false)

  const handleVerifyRoll = async () => {
    setError('')
    setBusy(true)
    try {
      const res = await api.get('/admin/roll/verify', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setVerificationResult(res)
    } catch (err) {
      setError(err.message || 'Roll verification failed.')
    } finally {
      setBusy(false)
    }
  }

  const handleLookupVoter = async (e) => {
    e.preventDefault()
    if (!lookupUsn.trim()) return
    setLookupError('')
    setLookupResult(null)
    setBusyLookup(true)

    try {
      const res = await api.post(
        '/admin/disputes/query',
        {
          query_type: 'VOTER_OPERATIONAL',
          identifier: lookupUsn.trim().toUpperCase(),
        },
        {
          headers: { Authorization: `Bearer ${adminToken}` },
        }
      )
      setLookupResult(res?.data || res)
    } catch (err) {
      setLookupError(err.message || 'Operational voter lookup failed.')
    } finally {
      setBusyLookup(false)
    }
  }

  return (
    <div className="page-container admin-voters-page">
      {/* Title & Architectural Overview */}
      <div className="card">
        <span className="badge badge-accent">ELECTORAL ROLL & ONBOARDING GOVERNANCE</span>
        <h2 className="card-title" style={{ marginTop: '0.4rem' }}>Electoral Roll & Voter Onboarding</h2>
        <p style={{ fontSize: '0.95rem', color: '#374151', lineHeight: 1.5 }}>
          The electoral roll is the authoritative collegiate registry of eligible voters. Registration and security onboarding are distinct operational steps. In compliance with data minimization, the entire roster is never dumped in bulk.
        </p>

        {/* 3-Tier Conceptual Distinction Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1rem', marginTop: '1.25rem' }}>
          <div style={{ border: '2px solid #000', padding: '1rem', background: '#FFFDF5', boxShadow: '3px 3px 0 #000' }}>
            <span className="badge" style={{ background: '#FFD93D', fontSize: '0.75rem', marginBottom: '0.35rem' }}>STAGE 1</span>
            <h4 style={{ margin: '0.25rem 0', fontSize: '1rem' }}>Electoral Roll Eligibility</h4>
            <p style={{ fontSize: '0.825rem', color: '#4B5563', margin: 0 }}>
              College-certified baseline roster. Verifies whether a student USN is legally eligible to participate in collegiate elections.
            </p>
          </div>

          <div style={{ border: '2px solid #000', padding: '1rem', background: '#FFFDF5', boxShadow: '3px 3px 0 #000' }}>
            <span className="badge" style={{ background: '#C4B5FD', fontSize: '0.75rem', marginBottom: '0.35rem' }}>STAGE 2</span>
            <h4 style={{ margin: '0.25rem 0', fontSize: '1rem' }}>Account Registration</h4>
            <p style={{ fontSize: '0.825rem', color: '#4B5563', margin: 0 }}>
              The student claims their USN, verifies via email OTP, and creates portal login credentials.
            </p>
          </div>

          <div style={{ border: '2px solid #000', padding: '1rem', background: '#FFFDF5', boxShadow: '3px 3px 0 #000' }}>
            <span className="badge" style={{ background: '#D1FAE5', fontSize: '0.75rem', marginBottom: '0.35rem' }}>STAGE 3</span>
            <h4 style={{ margin: '0.25rem 0', fontSize: '1rem' }}>Security Factor Onboarding</h4>
            <p style={{ fontSize: '0.825rem', color: '#4B5563', margin: 0 }}>
              The student binds their MetaMask wallet and enrolls their AI biometric liveness template before ballot casting is permitted.
            </p>
          </div>
        </div>
      </div>

      <div className="grid-cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))' }}>
        {/* Card 1: Electoral Roll Digest Verification */}
        <div className="card">
          <span className="badge badge-accent">INTEGRITY AUDIT</span>
          <h3 style={{ marginTop: '0.4rem', fontSize: '1.25rem' }}>Cryptographic Roll Verification</h3>
          <p style={{ fontSize: '0.875rem', color: '#4B5563', marginBottom: '1.25rem', lineHeight: 1.4 }}>
            Recomputes the cryptographic SHA-256 digest across all active electoral roll entries to mathematically prove zero administrative tampering or unauthorized insertions.
          </p>

          <button className="btn btn-primary" onClick={handleVerifyRoll} disabled={busy} style={{ width: '100%' }}>
            {busy ? 'Computing SHA-256 Digest...' : 'Verify Electoral Roll Integrity'}
          </button>

          {error && (
            <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
              {error}
            </div>
          )}

          {verificationResult && (
            <div className={`alert-box ${verificationResult.verified ? 'alert-success' : 'alert-error'}`} style={{ marginTop: '1.25rem' }}>
              <h4 style={{ margin: '0 0 0.35rem 0' }}>Roll Integrity Verification Result</h4>
              <p style={{ margin: 0, fontSize: '0.9rem' }}>{verificationResult.message || 'Electoral roll digest verified against official records.'}</p>
              <div style={{ marginTop: '0.65rem', fontFamily: 'monospace', fontSize: '0.825rem' }}>
                Status: <strong>{verificationResult.verified ? '✓ PRISTINE (DIGEST MATCH)' : '✗ MISMATCH DETECTED'}</strong>
              </div>
            </div>
          )}
        </div>

        {/* Card 2: Safe Operational Voter Status Lookup */}
        <div className="card">
          <span className="badge badge-violet">OPERATIONAL INQUIRY</span>
          <h3 style={{ marginTop: '0.4rem', fontSize: '1.25rem' }}>Voter Status & Onboarding Inquiry</h3>
          <p style={{ fontSize: '0.875rem', color: '#4B5563', marginBottom: '1.25rem', lineHeight: 1.4 }}>
            Investigate an individual student's eligibility and onboarding progression without exposing the full roster or accessing ballot contents.
          </p>

          <form onSubmit={handleLookupVoter} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              type="text"
              placeholder="Enter Student USN (e.g. 1XX23CS000)"
              value={lookupUsn}
              onChange={(e) => setLookupUsn(e.target.value)}
              style={{ minHeight: '44px', flex: 1, padding: '0.5rem 0.75rem', fontSize: '0.9rem', border: '2px solid #000' }}
              required
            />
            <button className="btn btn-secondary" type="submit" disabled={busyLookup || !lookupUsn.trim()}>
              {busyLookup ? 'Checking...' : 'Inspect'}
            </button>
          </form>

          {lookupError && (
            <div className="alert-box alert-error" style={{ marginBottom: '1rem' }}>
              {lookupError}
            </div>
          )}

          {lookupResult && (
            <div style={{ border: '2px solid #000', padding: '1rem', background: '#F9F8F3', boxShadow: '2px 2px 0 #000' }}>
              <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '1rem', textTransform: 'uppercase' }}>
                Operational Status: {lookupUsn.toUpperCase()}
              </h4>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem', fontSize: '0.85rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Electoral Roll Status:</span>
                  <strong>{lookupResult.electoral_roll_status || (lookupResult.is_eligible ? 'ELIGIBLE' : 'NOT_FOUND')}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Account Registered:</span>
                  <strong>{lookupResult.account_registered ? '✓ YES' : '✗ NO'}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Web3 Wallet Bound:</span>
                  <strong>{lookupResult.wallet_bound ? '✓ BOUND & VERIFIED' : '✗ PENDING'}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Face Biometrics Enrolled:</span>
                  <strong>{lookupResult.face_enrolled ? '✓ ENROLLED' : '✗ PENDING'}</strong>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
