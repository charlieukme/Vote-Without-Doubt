import React, { useState } from 'react'
import { api } from '../../api/client.js'
import './Pages.css'

export default function ReportProblemPage() {
  const [submitted, setSubmitted] = useState(false)
  const [referenceId, setReferenceId] = useState('')
  const [category, setCategory] = useState('otp')
  const [details, setDetails] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    const lower = details.toLowerCase()
    if (
      lower.includes('private key') ||
      lower.includes('private_key') ||
      lower.includes('seed phrase') ||
      /0x[a-f0-9]{64}/i.test(details)
    ) {
      setError('Security Notice: Do not include private keys or seed phrases in support tickets.')
      return
    }
    if (
      lower.includes('my password') ||
      lower.includes('account password') ||
      /\b(?:password|passcode)\s*(?:is|:|=)/i.test(details)
    ) {
      setError('Security Notice: Do not include account passwords or credentials in support tickets.')
      return
    }
    if (
      /\b\d{6}\b/.test(details) ||
      /otp\s*(?:is|code|:|=)\s*\d+/i.test(details) ||
      /code\s*(?:is|:|=)\s*\d+/i.test(details)
    ) {
      setError('Security Notice: Do not include one-time password (OTP) codes or numeric verification values.')
      return
    }
    if (/rcpt-[a-z0-9]+/i.test(details)) {
      setError('Privacy Notice: Do not share your official receipt code. Receipts should remain private to preserve ballot secrecy.')
      return
    }
    if (
      lower.includes('voted for') ||
      lower.includes('vote for') ||
      lower.includes('my vote was') ||
      lower.includes('my candidate')
    ) {
      setError('Ballot Privacy Notice: Never disclose your vote choice or selected candidate in a support request.')
      return
    }

    setLoading(true)
    try {
      const res = await api.post('/public/support/report', {
        category,
        details,
      })
      if (res && res.success) {
        setReferenceId(res.reference_id || 'LOGGED')
        setSubmitted(true)
      } else {
        setError(res?.message || 'Failed to submit report. Please try again.')
      }
    } catch (err) {
      setError(err?.message || 'Network error submitting report.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-container report-problem-page">
      <div className="card">
        <span className="badge badge-accent">TECHNICAL DISPUTE & SUPPORT</span>
        <h2 className="card-title">Report an Issue or Dispute</h2>
        <p>If you encounter technical issues with email delivery, MetaMask connectivity, or camera verification, submit a report to the election committee.</p>
      </div>

      <div className="card">
        {submitted ? (
          <div className="alert-box alert-success">
            <h4>Support Request Logged</h4>
            <p>Your issue has been forwarded to the college election technical team.</p>
            {referenceId && (
              <p style={{ marginTop: '0.5rem', fontWeight: 700 }}>
                Reference Tracking ID: <span style={{ fontFamily: 'monospace', background: '#eee', padding: '2px 6px', borderRadius: '4px' }}>{referenceId}</span>
              </p>
            )}
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {error && (
              <div className="alert-box alert-danger">
                <strong>Error:</strong> {error}
              </div>
            )}
            <div>
              <label style={{ display: 'block', fontWeight: 800, marginBottom: '0.35rem' }}>Issue Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{ width: '100%', padding: '0.6rem', border: '3px solid #000', fontFamily: 'inherit', fontWeight: 700 }}
              >
                <option value="otp">Email OTP not received</option>
                <option value="usn">USN marked as ineligible or not on roll</option>
                <option value="wallet">MetaMask connection / network mismatch</option>
                <option value="camera">Camera permission denied / liveness timeout</option>
                <option value="receipt">Dispute related to vote receipt code</option>
                <option value="other">Other technical issue</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontWeight: 800, marginBottom: '0.35rem' }}>Description of Problem</label>
              <textarea
                rows={4}
                value={details}
                onChange={(e) => setDetails(e.target.value)}
                placeholder="Describe what occurred, any error messages shown, and your device/browser details..."
                style={{ width: '100%', padding: '0.6rem', border: '3px solid #000', fontFamily: 'inherit' }}
                required
              />
            </div>

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ alignSelf: 'flex-start' }}>
              {loading ? 'Submitting...' : 'Submit Technical Report'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
