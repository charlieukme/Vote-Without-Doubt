import React, { useState, useEffect } from 'react'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'

const formatOfficerRole = (adminId, name) => {
  if (name && (name.includes('Chief') || name.includes('Deputy'))) return name
  if (adminId === 'OFFICER_01') return 'Chief Election Officer'
  if (adminId === 'OFFICER_02') return 'Deputy Election Officer'
  return name || adminId || '—'
}

export default function AdminApprovalsPage() {
  const { adminAuth, adminToken } = useAuth()
  const [approvals, setApprovals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [isRateLimited, setIsRateLimited] = useState(false)
  const [success, setSuccess] = useState('')
  const [busyId, setBusyId] = useState(null)

  const isOfficer = adminAuth?.role === 'OFFICER'
  const currentAdminId = adminAuth?.admin_id

  const loadApprovals = async (silent = false) => {
    if (!adminToken) return
    if (!silent) setLoading(true)
    try {
      const res = await api.get('/admin/approvals', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setApprovals(res?.approval_requests || [])
      setIsRateLimited(false)
      setError('')
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else if (!silent) {
        setIsRateLimited(false)
        setError(err.message || 'Failed to load approvals queue.')
      }
      // Preserve existing loaded approvals if refresh fails
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    loadApprovals(false)

    // Visibility-aware auto-refresh polling every 15s
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadApprovals(true)
      }
    }, 15000)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        loadApprovals(true)
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleVisibilityChange)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleVisibilityChange)
    }
  }, [adminToken])

  const handleApprove = async (requestId, requesterId) => {
    setError('')
    setSuccess('')

    // UI-side defense against self-approval
    if (currentAdminId && requesterId && currentAdminId === requesterId) {
      setError('Four-Eyes Violation: You cannot approve a request that you initiated. A distinct officer must approve.')
      return
    }

    setBusyId(requestId)
    try {
      const res = await api.post(`/admin/approvals/${requestId}/approve`, {}, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(res?.message || 'Operation approved and executed successfully.')
      await loadApprovals()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else if (err.message && err.message.includes('FOUR_EYES_VIOLATION')) {
        setIsRateLimited(false)
        setError('Self-approval rejected by server: Requester and approver must be distinct officers.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Approval execution failed.')
      }
    } finally {
      setBusyId(null)
    }
  }

  const handleReject = async (requestId) => {
    setError('')
    setSuccess('')
    setBusyId(requestId)
    try {
      await api.post(`/admin/approvals/${requestId}/reject`, { reason: 'Rejected by reviewing officer' }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess('Approval request rejected.')
      await loadApprovals()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Rejection failed.')
      }
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="page-container admin-approvals-page">
      <div className="card">
        <span className="badge badge-accent">FOUR-EYES GOVERNANCE QUEUE</span>
        <h2 className="card-title">Two-Officer Approval Queue</h2>
        <p>
          Sensitive operations (Scheduling, Emergency Closure, Finalization, Cancellation, Audit Anchoring) strictly require
          concurrence from two independent officers: <strong>Chief Election Officer</strong> and <strong>Deputy Election Officer</strong>. Self-approval is prevented cryptographically and in the UI.
        </p>
      </div>

      {error && (
        <div className={`alert-box ${isRateLimited ? 'alert-warning' : 'alert-error'}`}>
          <strong>{isRateLimited ? 'Rate Limit Notice: ' : 'Error: '}</strong>
          {error}
        </div>
      )}
      {success && <div className="alert-box alert-success">{success}</div>}

      {!isOfficer && (
        <div className="alert-box alert-info" style={{ margin: '1rem 0' }}>
          <strong>Auditor Inspection Notice:</strong> Auditors hold read-only governance privileges. Operational approval and rejection actions are strictly restricted to commissioned Election Officers (Chief Election Officer and Deputy Election Officer).
        </div>
      )}

      <div className="card">
        <h3>Pending & Historic Requests</h3>
        {loading && approvals === null ? (
          <p>Loading approval requests...</p>
        ) : approvals === null && isRateLimited ? (
          <div className="alert-box alert-warning" style={{ marginTop: '1rem' }}>
            Rate limit exceeded. Please retry later.
          </div>
        ) : approvals === null && error ? (
          <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
            {error}
          </div>
        ) : approvals && approvals.length === 0 ? (
          isRateLimited ? (
            <div className="alert-box alert-warning" style={{ marginTop: '1rem' }}>
              Rate limit exceeded. Please retry later.
            </div>
          ) : error ? (
            <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
              {error}
            </div>
          ) : (
            <p>No approval requests found in queue.</p>
          )
        ) : approvals && approvals.length > 0 ? (
          <div style={{ overflowX: 'auto', marginTop: '1.25rem' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th style={{ padding: '0.6rem' }}>Request ID</th>
                  <th style={{ padding: '0.6rem' }}>Election ID</th>
                  <th style={{ padding: '0.6rem' }}>Action Type</th>
                  <th style={{ padding: '0.6rem' }}>Requester</th>
                  <th style={{ padding: '0.6rem' }}>Approver</th>
                  <th style={{ padding: '0.6rem' }}>Status</th>
                  <th style={{ padding: '0.6rem' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {approvals.map((req) => {
                  const isRequester = currentAdminId && req.requester === currentAdminId
                  const isPending = req.status === 'PENDING'

                  return (
                    <tr key={req.id} style={{ borderBottom: '1px solid #E5E7EB' }}>
                      <td style={{ padding: '0.6rem', fontFamily: 'monospace', fontWeight: 800 }}>#{req.id}</td>
                      <td style={{ padding: '0.6rem', fontWeight: 700 }}>
                        <div>{req.election_id}</div>
                        {req.election_title && (
                          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#374151', marginTop: '0.2rem' }}>
                            {req.election_title}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '0.6rem' }}>
                        <div style={{ fontWeight: 800, color: req.action_type === 'EMERGENCY_CLOSE' ? '#DC2626' : req.action_type === 'ANCHOR_AUDIT' ? '#047857' : req.action_type === 'FINALIZE_ELECTION' ? '#4F46E5' : '#1E3A8A' }}>
                          {req.action_type}
                        </div>
                        {req.reason && (
                          <div style={{ marginTop: '0.35rem', padding: '0.4rem 0.6rem', background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: '4px', fontSize: '0.78rem', color: '#991B1B', maxWidth: '340px', wordBreak: 'break-word' }}>
                            <strong>Justification:</strong> {req.reason}
                          </div>
                        )}
                        {req.checkpoint_hash && (
                          <div style={{ fontSize: '0.72rem', color: '#4B5563', fontFamily: 'monospace', marginTop: '0.2rem' }}>
                            Checkpoint: {req.checkpoint_hash.slice(0, 10)}...{req.checkpoint_hash.slice(-8)} (Event #{req.checkpoint_event_id || '—'})
                          </div>
                        )}
                        {req.execution && (
                          <div style={{ fontSize: '0.72rem', color: '#047857', fontFamily: 'monospace', marginTop: '0.2rem' }}>
                            Tx: {req.execution.tx_hash ? `${req.execution.tx_hash.slice(0, 10)}...` : 'Confirmed'} (Block #{req.execution.block_number || '—'})
                          </div>
                        )}
                        {((req.status === 'FAILED' || req.status === 'REJECTED') && req.rejection_reason) && (
                          <div
                            style={{
                              marginTop: '0.35rem',
                              padding: '0.35rem 0.5rem',
                              borderRadius: '4px',
                              fontSize: '0.75rem',
                              background: req.rejection_reason.startsWith('Finalization blocked:') ? '#FEF2F2' : '#FFFBEB',
                              border: `1px solid ${req.rejection_reason.startsWith('Finalization blocked:') ? '#FCA5A5' : '#FDE68A'}`,
                              color: req.rejection_reason.startsWith('Finalization blocked:') ? '#991B1B' : '#92400E',
                            }}
                          >
                            <strong>
                              {req.rejection_reason.startsWith('Finalization blocked:')
                                ? 'Precondition Check Failed:'
                                : 'Officer Rejection Reason:'}
                            </strong>{' '}
                            {req.rejection_reason}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '0.6rem' }}>
                        <div style={{ fontWeight: 700 }}>{formatOfficerRole(req.requester, req.requester_name)}</div>
                        <div style={{ fontSize: '0.75rem', color: '#6B7280', fontFamily: 'monospace' }}>{req.requester}</div>
                      </td>
                      <td style={{ padding: '0.6rem' }}>
                        {req.approver ? (
                          <>
                            <div style={{ fontWeight: 700 }}>{formatOfficerRole(req.approver, req.approver_name)}</div>
                            <div style={{ fontSize: '0.75rem', color: '#6B7280', fontFamily: 'monospace' }}>{req.approver}</div>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td style={{ padding: '0.6rem' }}>
                        <span className={`status-badge status-${req.status?.toLowerCase()}`}>{req.status}</span>
                      </td>
                      <td style={{ padding: '0.6rem' }}>
                        {isPending && isOfficer ? (
                          isRequester ? (
                            <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#D97706' }}>
                              Self-Approval Blocked (Your Request)
                            </span>
                          ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                              <div style={{ display: 'flex', gap: '0.35rem' }}>
                                <button
                                  className="btn btn-primary"
                                  onClick={() => handleApprove(req.id, req.requester)}
                                  disabled={busyId === req.id}
                                  style={{
                                    fontSize: '0.75rem',
                                    padding: '0.25rem 0.5rem',
                                    background: req.action_type === 'FINALIZE_ELECTION' ? '#4F46E5' : undefined,
                                    borderColor: req.action_type === 'FINALIZE_ELECTION' ? '#4F46E5' : undefined,
                                  }}
                                >
                                  {busyId === req.id
                                    ? 'Working...'
                                    : req.action_type === 'ANCHOR_AUDIT'
                                    ? 'Approve & Anchor On-Chain'
                                    : req.action_type === 'FINALIZE_ELECTION'
                                    ? 'Approve & Finalize'
                                    : 'Approve & Execute'}
                                </button>
                                <button
                                  className="btn btn-logout"
                                  onClick={() => handleReject(req.id)}
                                  disabled={busyId === req.id}
                                  style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                                >
                                  Reject
                                </button>
                              </div>
                              {req.action_type === 'FINALIZE_ELECTION' && (
                                <div style={{ fontSize: '0.7rem', color: '#4F46E5', fontWeight: 600 }}>
                                  Irreversible: Seals Merkle root & destroys pseudonym keys.
                                </div>
                              )}
                            </div>
                          )
                        ) : isPending && !isOfficer ? (
                          <span style={{ fontSize: '0.75rem', color: '#6B7280' }}>Auditor Read-Only</span>
                        ) : req.status === 'FAILED' ? (
                          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#DC2626' }}>Failed (Retry Eligible)</span>
                        ) : (
                          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#6B7280' }}>Resolved</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </div>
  )
}
