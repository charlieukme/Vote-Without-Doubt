import React, { useState } from 'react'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import '../public/Pages.css'

export default function AdminReviewPage() {
  const { params } = useRouter()
  const { adminToken } = useAuth()
  const [queryType, setQueryType] = useState('RECEIPT_CODE')
  const [receiptCode, setReceiptCode] = useState('')
  const [identifier, setIdentifier] = useState('')
  const initialElectionId = params?.election_id || params?.electionId || params?.id || ''
  const [electionId, setElectionId] = useState(initialElectionId)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const handleQuery = async (e) => {
    e.preventDefault()
    setError('')
    setResult(null)

    try {
      const payload = { query_type: queryType }
      if (queryType === 'RECEIPT_CODE') {
        payload.receipt_code = receiptCode.trim()
      } else {
        const trimmedEid = electionId.trim()
        if (!trimmedEid || !/^\d+$/.test(trimmedEid) || parseInt(trimmedEid, 10) <= 0) {
          setError('A valid positive numeric Election ID is required for voter operational dispute queries.')
          return
        }
        payload.identifier = identifier.trim()
        payload.election_id = trimmedEid
      }

      setBusy(true)
      const res = await api.post('/admin/disputes/query', payload, {
        headers: { Authorization: `Bearer ${adminToken}` },
      })
      setResult(res)
    } catch (err) {
      setError(err.message || 'Dispute query failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page-container admin-review-page">
      <div className="card">
        <span className="badge badge-accent">DISPUTE & DISCREPANCY AUDIT</span>
        <h2 className="card-title">Privacy-Preserving Dispute Console</h2>
        <p>
          Investigate disputed receipts or voter operational status without disclosing candidate choices.
          In accordance with cryptographic privacy invariants, voter-to-candidate linkage is impossible.
        </p>
      </div>

      <div className="card">
        <form onSubmit={handleQuery} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
              Investigation Mode
            </label>
            <select
              value={queryType}
              onChange={(e) => setQueryType(e.target.value)}
              style={{ width: '100%', padding: '0.6rem', border: '3px solid #000', fontFamily: 'inherit', fontWeight: 700 }}
            >
              <option value="RECEIPT_CODE">Investigate Official Receipt Code</option>
              <option value="VOTER_OPERATIONAL">Investigate Voter Operational Status (USN / Voter ID)</option>
            </select>
          </div>

          {queryType === 'RECEIPT_CODE' ? (
            <div>
              <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                Receipt Code
              </label>
              <input
                type="text"
                placeholder="e.g. REC-1-A1B2C3D4E5F67890"
                value={receiptCode}
                onChange={(e) => setReceiptCode(e.target.value)}
                style={{ width: '100%', padding: '0.6rem', border: '2px solid #000', fontFamily: 'monospace' }}
                required
              />
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="dispute-election-id" style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                  Election ID (Numeric)
                </label>
                <input
                  id="dispute-election-id"
                  type="number"
                  min="1"
                  step="1"
                  placeholder="e.g. 1"
                  value={electionId}
                  onChange={(e) => setElectionId(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', border: '2px solid #000' }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontWeight: 800, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                  Student USN or Voter Identifier
                </label>
                <input
                  type="text"
                  placeholder="e.g. 1RV22CS001"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  style={{ width: '100%', padding: '0.6rem', border: '2px solid #000' }}
                  required
                />
              </div>
            </>
          )}

          <button className="btn btn-primary" type="submit" disabled={busy} style={{ alignSelf: 'flex-start' }}>
            {busy ? 'Investigating...' : 'Execute Dispute Audit'}
          </button>
        </form>

        {error && <div className="alert-box alert-error" style={{ marginTop: '1rem' }}>{error}</div>}

        {result && (
          <div className="alert-box alert-success" style={{ marginTop: '1.25rem' }}>
            <h4>Dispute Investigation Findings</h4>
            <pre style={{ margin: '0.5rem 0 0 0', padding: '0.75rem', background: '#000', color: '#FFF', overflowX: 'auto', fontSize: '0.8rem' }}>
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
