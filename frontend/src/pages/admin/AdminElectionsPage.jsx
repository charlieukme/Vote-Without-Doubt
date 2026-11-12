import React, { useState, useEffect } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'

export default function AdminElectionsPage() {
  const { navigate } = useRouter()
  const { adminAuth, adminToken } = useAuth()

  const [elections, setElections] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [error, setError] = useState('')
  const [isRateLimited, setIsRateLimited] = useState(false)
  const [success, setSuccess] = useState('')
  const [busy, setBusy] = useState(false)

  const [emergencyModalElection, setEmergencyModalElection] = useState(null)
  const [emergencyJustification, setEmergencyJustification] = useState('')
  const [submittingEmergency, setSubmittingEmergency] = useState(false)

  const isOfficer = adminAuth?.role === 'OFFICER'

  const loadElections = async (includeArch = showArchived) => {
    if (!adminToken) return
    setLoading(true)
    try {
      const url = includeArch ? '/admin/elections?include_archived=true' : '/admin/elections'
      const res = await api.get(url, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setElections(res?.elections || [])
      setIsRateLimited(false)
      setError('')
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to load elections.')
      }
      // Preserve existing loaded elections if refresh fails
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadElections(showArchived)
  }, [adminToken, showArchived])

  const handleCreate = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setBusy(true)

    try {
      await api.post('/admin/elections', {
        title,
        description,
        start_time: startTime ? new Date(startTime).toISOString() : new Date().toISOString(),
        end_time: endTime ? new Date(endTime).toISOString() : new Date(Date.now() + 86400000).toISOString(),
        eligible_count: 500,
        max_ballots: 3,
      }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })

      setSuccess('Election draft created successfully.')
      setShowCreateModal(false)
      setTitle('')
      setDescription('')
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to create election draft.')
      }
    } finally {
      setBusy(false)
    }
  }

  const handleRequestSchedule = async (electionId) => {
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/elections/${electionId}/request-approval`, {
        action_type: 'SCHEDULE_ELECTION',
        reason: 'Officer proposed election schedule for student body voting',
      }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Two-Officer approval requested for Election ${electionId}. A distinct officer must approve it.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to request schedule approval.')
      }
    }
  }

  const handleOpen = async (electionId) => {
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/elections/${electionId}/open`, {}, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Election ${electionId} transitioned to OPEN status.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to open election. Note: Start time must have arrived.')
      }
    }
  }

  const handleClose = async (electionId) => {
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/elections/${electionId}/close`, {}, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Election ${electionId} closed successfully.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to close election. Note: End time must have arrived.')
      }
    }
  }

  const handleEmergencyCloseSubmit = async (e) => {
    e?.preventDefault()
    if (!emergencyJustification || !emergencyJustification.trim()) {
      setError('A mandatory justification reason is required for emergency election closure.')
      return
    }
    setError('')
    setSuccess('')
    setSubmittingEmergency(true)
    try {
      await api.post(`/admin/elections/${emergencyModalElection.election_id}/request-approval`, {
        action_type: 'EMERGENCY_CLOSE',
        reason: emergencyJustification.trim(),
      }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Two-officer emergency closure requested for Election ${emergencyModalElection.election_id}. A distinct officer must approve it in the Approvals queue.`)
      setEmergencyModalElection(null)
      setEmergencyJustification('')
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to request emergency election closure.')
      }
    } finally {
      setSubmittingEmergency(false)
    }
  }

  const handleRequestAnchor = async (electionId) => {
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/elections/${electionId}/request-approval`, {
        action_type: 'ANCHOR_AUDIT',
        reason: 'Officer proposed anchoring administrative audit trail to blockchain',
      }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Two-Officer audit anchor approval requested for Election ${electionId}. A distinct officer must approve it.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to request audit anchor approval.')
      }
    }
  }

  const handleRequestScheduleApproval = async (electionId) => {
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/elections/${electionId}/request-approval`, {
        action_type: 'SCHEDULE_ELECTION',
        reason: 'Officer requested two-officer approval to schedule election',
      }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Two-officer schedule approval requested for Election #${electionId}. Officer 2 (Deputy Election Officer) must approve it in the Approvals queue.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to request schedule approval.')
      }
    }
  }

  const handleDeleteDraft = async (electionId) => {
    if (!window.confirm(`Permanently delete Election Draft #${electionId}? This action cannot be undone and will only succeed if the draft has zero ballots or dependencies.`)) {
      return
    }
    setError('')
    setSuccess('')
    try {
      await api.delete(`/admin/elections/${electionId}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Election draft #${electionId} permanently deleted.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to delete election draft.')
      }
    }
  }

  const handleArchive = async (electionId, archive = true) => {
    const actionText = archive ? 'archive' : 'unarchive'
    if (!window.confirm(`Are you sure you want to ${actionText} Election #${electionId}?`)) {
      return
    }
    setError('')
    setSuccess('')
    try {
      await api.post(`/admin/elections/${electionId}/archive`, { archive }, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setSuccess(`Election #${electionId} ${actionText}d successfully.`)
      await loadElections()
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || `Failed to ${actionText} election.`)
      }
    }
  }

  return (
    <div className="page-container admin-elections-page">
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <span className="badge badge-accent">LIFECYCLE MANAGEMENT</span>
          <h2 className="card-title">Election Administration</h2>
          <p style={{ margin: 0 }}>Create, schedule, open, and close collegiate elections.</p>
        </div>

        {isOfficer && (
          <button className="btn btn-primary" onClick={() => setShowCreateModal(!showCreateModal)}>
            {showCreateModal ? 'Cancel' : '+ Create New Election Draft'}
          </button>
        )}
      </div>

      {error && (
        <div className={`alert-box ${isRateLimited ? 'alert-warning' : 'alert-error'}`}>
          <strong>{isRateLimited ? 'Rate Limit Notice: ' : 'Error: '}</strong>
          {error}
        </div>
      )}
      {success && <div className="alert-box alert-success">{success}</div>}

      {/* Create Modal Form */}
      {showCreateModal && (
        <div className="card" style={{ background: '#FFFFFF', border: '3px solid #000' }}>
          <h3>Propose New Election (DRAFT State)</h3>
          <form onSubmit={handleCreate} style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem' }}>Election Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Annual Student Council Election 2026"
                style={{ width: '100%', padding: '0.5rem', border: '2px solid #000' }}
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem' }}>Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Details and scope..."
                style={{ width: '100%', padding: '0.5rem', border: '2px solid #000' }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              <div>
                <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem' }}>Start Time</label>
                <input
                  type="datetime-local"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', border: '2px solid #000' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem' }}>End Time</label>
                <input
                  type="datetime-local"
                  value={endTime}
                  onChange={(e) => setEndTime(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', border: '2px solid #000' }}
                />
              </div>
            </div>

            <button className="btn btn-primary" type="submit" disabled={busy} style={{ alignSelf: 'flex-start', marginTop: '0.5rem' }}>
              {busy ? 'Saving Proposal...' : 'Create Draft Proposal'}
            </button>
          </form>
        </div>
      )}

      {/* Elections List Table */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1rem' }}>
          <h3 style={{ margin: 0 }}>Elections Register</h3>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 700 }}>
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              style={{ width: '1.1rem', height: '1.1rem', accentColor: '#000' }}
            />
            Show Archived Elections
          </label>
        </div>
        {loading && elections === null ? (
          <p>Loading elections...</p>
        ) : elections === null && isRateLimited ? (
          <div className="alert-box alert-warning" style={{ marginTop: '1rem' }}>
            Rate limit exceeded. Please retry later.
          </div>
        ) : elections === null && error ? (
          <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
            {error}
          </div>
        ) : elections && elections.length === 0 ? (
          isRateLimited ? (
            <div className="alert-box alert-warning" style={{ marginTop: '1rem' }}>
              Rate limit exceeded. Please retry later.
            </div>
          ) : error ? (
            <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>
              {error}
            </div>
          ) : (
            <p>No elections found.</p>
          )
        ) : elections && elections.length > 0 ? (
          <div style={{ overflowX: 'auto', marginTop: '1.25rem' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th style={{ padding: '0.6rem' }}>ID</th>
                  <th style={{ padding: '0.6rem' }}>Title</th>
                  <th style={{ padding: '0.6rem' }}>Status</th>
                  <th style={{ padding: '0.6rem' }}>Candidates</th>
                  <th style={{ padding: '0.6rem' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {elections.map((el) => {
                  const isScheduled = el.status === 'SCHEDULED'
                  const isEffectiveClosed = el.effective_status === 'CLOSED'
                  const isWindowExpired = isScheduled && (isEffectiveClosed || el.is_expired || (el.end_time && new Date(el.end_time) <= new Date()))

                  return (
                  <tr key={el.election_id} style={{ borderBottom: '1px solid #E5E7EB', opacity: el.is_archived ? 0.75 : 1 }}>
                    <td style={{ padding: '0.6rem', fontFamily: 'monospace', fontWeight: 800 }}>{el.election_id}</td>
                    <td style={{ padding: '0.6rem', fontWeight: 700 }}>
                      {el.title}
                      {el.is_archived && (
                        <span className="badge" style={{ marginLeft: '0.5rem', background: '#6B7280', color: '#FFF', fontSize: '0.7rem' }}>
                          ARCHIVED
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '0.6rem' }}>
                      {isWindowExpired ? (
                        <span className="status-badge" style={{ background: '#FEE2E2', color: '#991B1B', border: '1px solid #F87171', fontWeight: 800 }} title="Scheduled voting window has ended">
                          Scheduled window expired
                        </span>
                      ) : (
                        <span className={`status-badge status-${el.status?.toLowerCase()}`}>{el.status}</span>
                      )}
                    </td>
                    <td style={{ padding: '0.6rem' }}>{el.candidate_count || 0}</td>
                    <td style={{ padding: '0.6rem' }}>
                      <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                        {isOfficer && el.status === 'DRAFT' && (
                          <>
                            <button className="btn btn-primary" onClick={() => handleRequestScheduleApproval(el.election_id)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}>
                              Request Schedule Approval
                            </button>
                            <button className="btn btn-logout" onClick={() => handleDeleteDraft(el.election_id)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', background: '#EF4444', color: '#FFF' }}>
                              Delete Draft
                            </button>
                          </>
                        )}
                        {el.status === 'PENDING_APPROVAL' && (
                          <>
                            <button className="btn btn-secondary" onClick={() => navigate('/admin/approvals')} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', background: '#F59E0B', color: '#000', fontWeight: 700 }}>
                              Pending Officer 2 Approval &rarr;
                            </button>
                            {isOfficer && (
                              <button className="btn btn-logout" onClick={() => handleDeleteDraft(el.election_id)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', background: '#EF4444', color: '#FFF' }}>
                                Delete Draft
                              </button>
                            )}
                          </>
                        )}
                        {isOfficer && isScheduled && !isWindowExpired && (
                          <button className="btn btn-primary" onClick={() => handleOpen(el.election_id)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}>
                            Start Election
                          </button>
                        )}
                        {isOfficer && (el.status === 'OPEN' || el.status === 'ACTIVE') && (
                          <button className="btn btn-logout" onClick={() => handleClose(el.election_id)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}>
                            Close & Publish Results
                          </button>
                        )}
                        {el.status === 'FINALIZED' && (
                          <button className="btn btn-primary" onClick={() => navigate('/admin/results')} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', background: '#10B981', color: '#FFF' }}>
                            View Results
                          </button>
                        )}
                        {isOfficer && (el.status === 'CLOSED' || el.status === 'FINALIZED' || isWindowExpired) && (
                          <>
                            <button className="btn btn-secondary" onClick={() => handleRequestAnchor(el.election_id)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}>
                              Request Audit Anchor
                            </button>
                            <button
                              className="btn btn-secondary"
                              onClick={() => handleArchive(el.election_id, !el.is_archived)}
                              style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                            >
                              {el.is_archived ? 'Restore' : 'Archive'}
                            </button>
                          </>
                        )}
                        <button className="btn" onClick={() => navigate(`/admin/candidates/${el.election_id}`)} style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}>
                          Candidates
                        </button>
                      </div>
                    </td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      {/* Emergency Close Confirmation Modal */}
      {emergencyModalElection && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: '540px',
              width: '100%',
              background: '#FFFFFF',
              border: '3px solid #DC2626',
              boxShadow: '0 8px 30px rgba(0, 0, 0, 0.3)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
              <span className="badge" style={{ background: '#DC2626', color: '#FFF', fontWeight: 800 }}>
                EMERGENCY ACTION
              </span>
              <h3 style={{ margin: 0, color: '#DC2626' }}>Early Election Closure</h3>
            </div>

            <p style={{ fontSize: '0.875rem', color: '#374151', margin: '0.5rem 0' }}>
              Election <strong>{emergencyModalElection.title}</strong> (<code>{emergencyModalElection.election_id}</code>) is scheduled to end at{' '}
              <strong>{new Date(emergencyModalElection.end_time).toLocaleString()}</strong>.
            </p>

            <div
              style={{
                background: '#FEF2F2',
                borderLeft: '4px solid #DC2626',
                padding: '0.75rem',
                margin: '0.75rem 0',
                fontSize: '0.825rem',
                color: '#991B1B',
              }}
            >
              <strong>Two-Officer Four-Eyes Rule:</strong> Closing an election before its scheduled end time cannot be executed unilaterally. Submitting this form will queue an <code>EMERGENCY_CLOSE</code> request that requires independent cryptographic approval from a distinct commissioning officer before ballots are settled and voting is terminated.
            </div>

            <form onSubmit={handleEmergencyCloseSubmit}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.35rem' }}>
                  Mandatory Justification Reason <span style={{ color: '#DC2626' }}>*</span>
                </label>
                <textarea
                  value={emergencyJustification}
                  onChange={(e) => setEmergencyJustification(e.target.value)}
                  placeholder="State the security incident, administrative order, or emergency rationale..."
                  rows={4}
                  style={{
                    width: '100%',
                    padding: '0.6rem',
                    border: '2px solid #000',
                    borderRadius: '4px',
                    fontSize: '0.875rem',
                    boxSizing: 'border-box',
                  }}
                  required
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setEmergencyModalElection(null)
                    setEmergencyJustification('')
                  }}
                  disabled={submittingEmergency}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-logout"
                  disabled={submittingEmergency || !emergencyJustification.trim()}
                  style={{ background: '#DC2626', color: '#FFF' }}
                >
                  {submittingEmergency ? 'Submitting Request...' : 'Submit Emergency Close Request'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
