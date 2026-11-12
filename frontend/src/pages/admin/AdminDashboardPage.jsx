import React, { useState, useEffect } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'

export default function AdminDashboardPage() {
  const { navigate } = useRouter()
  const { adminAuth, adminToken } = useAuth()

  const [elections, setElections] = useState(null)
  const [approvals, setApprovals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [isRateLimited, setIsRateLimited] = useState(false)

  useEffect(() => {
    let mounted = true
    if (!adminToken) return

    const headers = { Authorization: `Bearer ${adminToken}` }

    setLoading(true)
    Promise.allSettled([
      api.get('/admin/elections', { headers }),
      api.get('/admin/approvals?status=PENDING', { headers }),
    ]).then(([eleResult, appResult]) => {
      if (!mounted) return

      let rateLimitHit = false
      let generalError = ''

      if (eleResult.status === 'fulfilled') {
        setElections(eleResult.value?.elections || [])
      } else {
        const err = eleResult.reason
        if (err?.status === 429 || err?.isRateLimited) {
          rateLimitHit = true
        } else {
          generalError = err?.message || 'Failed to load elections data'
        }
      }

      if (appResult.status === 'fulfilled') {
        setApprovals(appResult.value?.approval_requests || [])
      } else {
        const err = appResult.reason
        if (err?.status === 429 || err?.isRateLimited) {
          rateLimitHit = true
        } else if (!generalError) {
          generalError = err?.message || 'Failed to load approvals data'
        }
      }

      if (rateLimitHit) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else if (generalError) {
        setIsRateLimited(false)
        setError(generalError)
      } else {
        setIsRateLimited(false)
        setError('')
      }

      setLoading(false)
    })

    return () => { mounted = false }
  }, [adminToken])

  const role = adminAuth?.role || 'OFFICER'
  const isAuditor = role === 'AUDITOR'

  return (
    <div className="page-container admin-dashboard-page">
      {/* Welcome Banner */}
      <div className="card hero-section" style={{ background: isAuditor ? '#93C5FD' : '#FFD93D' }}>
        <span className="badge" style={{ background: '#000000', color: '#FFFFFF' }}>
          ROLE: {role}
        </span>
        <h2 style={{ fontSize: '2rem', fontWeight: 900, margin: '0.4rem 0' }}>
          Administrative Governance Console
        </h2>
        <p style={{ margin: 0, fontWeight: 600 }}>
          {isAuditor
            ? 'Auditor Mode: Independent cryptographic log inspection, tally verification, and tampering verification.'
            : `Officer Mode (${adminAuth?.admin_id === 'OFFICER_01' ? 'Chief Election Officer' : adminAuth?.admin_id === 'OFFICER_02' ? 'Deputy Election Officer' : (adminAuth?.name || 'Election Officer')}): Operational election lifecycle administration under strict Two-Officer Four-Eyes controls.`}
        </p>
      </div>

      {/* Error & Rate Limit Notice */}
      {error && (
        <div className={`alert-box ${isRateLimited ? 'alert-warning' : 'alert-error'}`} style={{ marginBottom: '1.25rem' }}>
          <strong>{isRateLimited ? 'Rate Limit Notice: ' : 'Error: '}</strong>
          {error}
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid-cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
        <div className="card">
          <span className="meta-label">Total Elections</span>
          <div style={{ fontSize: '2rem', fontWeight: 900, color: error && elections === null ? '#DC2626' : 'inherit' }}>
            {loading && elections === null ? '...' : elections !== null ? elections.length : '—'}
          </div>
          {error && elections === null && (
            <div style={{ fontSize: '0.75rem', color: '#DC2626', fontWeight: 700, marginTop: '0.25rem' }}>
              {isRateLimited ? 'Rate limit exceeded' : 'Failed to load'}
            </div>
          )}
          <button className="link-button" onClick={() => navigate('/admin/elections')} style={{ marginTop: '0.5rem' }}>
            Manage Elections &rarr;
          </button>
        </div>

        <div className="card">
          <span className="meta-label">Pending Two-Officer Approvals</span>
          <div style={{ fontSize: '2rem', fontWeight: 900, color: approvals?.length > 0 ? '#DC2626' : (error && approvals === null ? '#DC2626' : '#10B981') }}>
            {loading && approvals === null ? '...' : approvals !== null ? approvals.length : '—'}
          </div>
          {error && approvals === null && (
            <div style={{ fontSize: '0.75rem', color: '#DC2626', fontWeight: 700, marginTop: '0.25rem' }}>
              {isRateLimited ? 'Rate limit exceeded' : 'Failed to load'}
            </div>
          )}
          <button className="link-button" onClick={() => navigate('/admin/approvals')} style={{ marginTop: '0.5rem' }}>
            Review Approval Queue &rarr;
          </button>
        </div>

        <div className="card">
          <span className="meta-label">Audit Log Chain</span>
          <div style={{ fontSize: '1.2rem', fontWeight: 800, marginTop: '0.5rem' }}>SHA-256 Intact</div>
          <button className="link-button" onClick={() => navigate('/admin/audit')} style={{ marginTop: '0.5rem' }}>
            Verify Hash-Chain &rarr;
          </button>
        </div>

        <div className="card">
          <span className="meta-label">System Health</span>
          <div style={{ fontSize: '1.2rem', fontWeight: 800, marginTop: '0.5rem', color: '#10B981' }}>Online (Ganache)</div>
          <button className="link-button" onClick={() => navigate('/admin/health')} style={{ marginTop: '0.5rem' }}>
            Check Subsystems &rarr;
          </button>
        </div>
      </div>

      {/* Governance Workspaces */}
      <div className="section-block">
        <h3 className="section-title">Administrative Modules</h3>
        <div className="grid-cards nav-hub-grid">
          <div className="card hub-card" onClick={() => navigate('/admin/elections')}>
            <h4>Election Lifecycle</h4>
            <p>Draft new proposals, configure eligibility, and request schedule approval.</p>
            <span className="hub-link">Open Elections &rarr;</span>
          </div>

          <div className="card hub-card" onClick={() => navigate('/admin/approvals')}>
            <h4>Two-Officer Approvals</h4>
            <p>Execute Four-Eyes verification for scheduling, early closure, or finalization.</p>
            <span className="hub-link">Review Queue {approvals !== null ? `(${approvals.length})` : ''} &rarr;</span>
          </div>

          <div className="card hub-card" onClick={() => navigate('/admin/audit')}>
            <h4>Audit Trail</h4>
            <p>Examine append-only administrative logs and verify the cryptographic chain.</p>
            <span className="hub-link">Inspect Events &rarr;</span>
          </div>

          <div className="card hub-card" onClick={() => navigate('/admin/verification')}>
            <h4>Tampering Demo & Verification</h4>
            <p>Run sandboxed database reconciliation tests and view smart contract parameters.</p>
            <span className="hub-link">Open Verifier &rarr;</span>
          </div>

          <div className="card hub-card" onClick={() => navigate('/admin/review')}>
            <h4>Dispute Investigations</h4>
            <p>Privacy-preserving verification of voter status or disputed receipt codes.</p>
            <span className="hub-link">Query Disputes &rarr;</span>
          </div>

          <div className="card hub-card" onClick={() => navigate('/admin/voters')}>
            <h4>Electoral Roll</h4>
            <p>Inspect electoral roll SHA-256 digests and verify student voter eligibility lists.</p>
            <span className="hub-link">View Roll &rarr;</span>
          </div>
        </div>
      </div>
    </div>
  )
}
