import React, { useState, useEffect } from 'react'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'

export default function AdminAuditPage() {
  const { adminToken } = useAuth()
  const [events, setEvents] = useState(null)
  const [chainResult, setChainResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [isRateLimited, setIsRateLimited] = useState(false)
  const [busyChain, setBusyChain] = useState(false)

  const loadAuditLogs = async () => {
    if (!adminToken) return
    setLoading(true)
    try {
      const res = await api.get('/admin/audit-logs?limit=50', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setEvents(res?.audit_events || res?.events || [])
      setIsRateLimited(false)
      setError('')
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Failed to load audit logs.')
      }
      // Preserve existing loaded events if refresh fails
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAuditLogs()
  }, [adminToken])

  const verifyChain = async () => {
    setBusyChain(true)
    try {
      const res = await api.get('/admin/audit-logs/verify-chain', {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setChainResult(res)
    } catch (err) {
      if (err?.status === 429 || err?.isRateLimited) {
        setIsRateLimited(true)
        setError('Rate limit exceeded. Please retry later.')
      } else {
        setIsRateLimited(false)
        setError(err.message || 'Hash chain verification failed.')
      }
    } finally {
      setBusyChain(false)
    }
  }

  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('ALL')

  const formatPayload = (payload) => {
    if (!payload) return <span style={{ color: '#9CA3AF' }}>—</span>
    let data = payload
    if (typeof payload === 'string') {
      try {
        data = JSON.parse(payload)
      } catch {
        return <span>{payload}</span>
      }
    }
    if (typeof data !== 'object') return <span>{String(data)}</span>

    // Render key-value pairs in clean chips, filtering out any potential sensitive fields
    const safeKeys = Object.keys(data).filter(
      (k) => !['password', 'token', 'totp', 'secret', 'private_key', 'embedding'].some((s) => k.toLowerCase().includes(s))
    )
    if (safeKeys.length === 0) return <span style={{ color: '#9CA3AF' }}>Recorded</span>

    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
        {safeKeys.map((k) => (
          <span
            key={k}
            style={{
              display: 'inline-flex',
              padding: '0.15rem 0.45rem',
              background: '#F3F4F6',
              border: '1px solid #D1D5DB',
              fontSize: '0.75rem',
              borderRadius: '2px',
            }}
          >
            <strong>{k}:</strong>&nbsp;{String(data[k])}
          </span>
        ))}
      </div>
    )
  }

  const getEventBadge = (type) => {
    const t = (type || '').toUpperCase()
    if (t.includes('SECURITY') || t.includes('FAIL') || t.includes('VIOLATION') || t.includes('AUTH')) {
      return <span className="badge badge-danger" style={{ fontSize: '0.75rem' }}>{type}</span>
    }
    if (t.includes('ELECTION') || t.includes('APPROV') || t.includes('BALLOT')) {
      return <span className="badge badge-accent" style={{ fontSize: '0.75rem' }}>{type}</span>
    }
    return <span className="badge badge-violet" style={{ fontSize: '0.75rem' }}>{type}</span>
  }

  const filteredEvents = (events || []).filter((ev) => {
    const t = (ev.event_type || '').toUpperCase()
    if (categoryFilter === 'SECURITY' && !t.includes('SECURITY') && !t.includes('AUTH') && !t.includes('VIOLATION')) return false
    if (categoryFilter === 'ELECTION' && !t.includes('ELECTION') && !t.includes('APPROV') && !t.includes('BALLOT')) return false
    if (categoryFilter === 'GOVERNANCE' && !t.includes('APPROV') && !t.includes('OFFICER') && !t.includes('TAMPER')) return false

    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    const str = `${ev.id} ${ev.event_type} ${JSON.stringify(ev.payload || {})} ${ev.details || ''}`.toLowerCase()
    return str.includes(q)
  })

  return (
    <div className="page-container admin-audit-page">
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <span className="badge badge-accent">APPEND-ONLY HASH CHAIN</span>
          <h2 className="card-title" style={{ marginTop: '0.35rem' }}>Administrative Audit Trail</h2>
          <p style={{ margin: 0, fontSize: '0.925rem', color: '#374151' }}>
            Every administrative and security-relevant event is cryptographically linked with SHA-256 digests.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" onClick={() => loadAuditLogs()} disabled={loading} style={{ fontSize: '0.85rem' }}>
            {loading ? 'Refreshing...' : '↻ Refresh Logs'}
          </button>
          <button className="btn btn-primary" onClick={verifyChain} disabled={busyChain} style={{ fontSize: '0.85rem' }}>
            {busyChain ? 'Verifying Hashes...' : 'Verify Cryptographic Hash-Chain'}
          </button>
        </div>
      </div>

      {chainResult && (() => {
        const isChainIntact = Boolean(
          chainResult.intact ?? chainResult.valid ?? chainResult.chain_intact
        )
        const eventsChecked = chainResult.events_checked ?? chainResult.total_events ?? (events ? events.length : 0)
        return (
          <div className={`alert-box ${isChainIntact ? 'alert-success' : 'alert-error'}`}>
            <h4 style={{ margin: '0 0 0.5rem 0' }}>Audit Hash-Chain Verification Result</h4>
            <p style={{ margin: 0, fontWeight: 700 }}>
              Chain Status: <strong>{isChainIntact ? '✓ INTACT & TAMPER-FREE' : '✗ COMPROMISED'}</strong>
            </p>
            <div style={{ fontSize: '0.85rem', fontFamily: 'monospace', marginTop: '0.5rem' }}>
              Total Events Audited: {eventsChecked} | Latest Root: {chainResult.latest_hash || 'Verified'}
              {!isChainIntact && chainResult.broken_at_id != null ? ` | Broken at Event #${chainResult.broken_at_id}` : ''}
            </div>
          </div>
        )
      })()}

      {error && (
        <div className={`alert-box ${isRateLimited ? 'alert-warning' : 'alert-error'}`}>
          <strong>{isRateLimited ? 'Rate Limit Notice: ' : 'Error: '}</strong>
          {error}
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
          <h3 style={{ margin: 0, fontSize: '1.2rem', textTransform: 'uppercase' }}>
            Audit Events ({filteredEvents.length} of {events ? events.length : 0})
          </h3>

          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Search by event, id, or detail..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                minHeight: '38px',
                padding: '0.4rem 0.75rem',
                fontSize: '0.85rem',
                border: '2px solid #000',
                width: '240px',
              }}
            />
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              style={{
                minHeight: '38px',
                padding: '0.4rem 0.75rem',
                fontSize: '0.85rem',
                border: '2px solid #000',
                fontWeight: 700,
                background: '#FFF',
              }}
            >
              <option value="ALL">All Categories</option>
              <option value="SECURITY">Security & Auth</option>
              <option value="ELECTION">Election Operations</option>
              <option value="GOVERNANCE">Governance & Approvals</option>
            </select>
          </div>
        </div>

        {loading && events === null ? (
          <p>Loading events...</p>
        ) : filteredEvents.length === 0 ? (
          <p style={{ color: '#4B5563', padding: '1rem 0' }}>
            {events && events.length > 0 ? 'No audit events match your search/filter.' : 'No audit events recorded.'}
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#F3F4F6', borderBottom: '3px solid #000000', textAlign: 'left' }}>
                  <th style={{ padding: '0.75rem 0.6rem', width: '90px' }}>Event ID</th>
                  <th style={{ padding: '0.75rem 0.6rem', width: '180px' }}>Timestamp</th>
                  <th style={{ padding: '0.75rem 0.6rem', width: '220px' }}>Event Classification</th>
                  <th style={{ padding: '0.75rem 0.6rem' }}>Event Payload & Non-Sensitive Details</th>
                </tr>
              </thead>
              <tbody>
                {filteredEvents.map((ev) => (
                  <tr key={ev.id} style={{ borderBottom: '1px solid #E5E7EB' }}>
                    <td style={{ padding: '0.65rem', fontFamily: 'monospace', fontWeight: 800 }}>#{ev.id}</td>
                    <td style={{ padding: '0.65rem', fontSize: '0.85rem' }}>
                      <div>{ev.created_at ? new Date(ev.created_at).toLocaleString() : 'Recent'}</div>
                      <div style={{ fontSize: '0.725rem', color: '#6B7280' }}>
                        {ev.created_at ? new Date(ev.created_at).toISOString() : ''}
                      </div>
                    </td>
                    <td style={{ padding: '0.65rem' }}>{getEventBadge(ev.event_type)}</td>
                    <td style={{ padding: '0.65rem', fontSize: '0.85rem' }}>
                      {formatPayload(ev.payload || ev.details)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
