import React, { useState, useEffect } from 'react'
import { useRouter } from '../../router/RouterContext'
import { api } from '../../api/client'
import { selectAuthoritativeElection } from '../../utils/electionUtils'
import '../public/Pages.css'

export default function ReceiptPage() {
  const { navigate, params } = useRouter()
  const [electionId, setElectionId] = useState(null)
  const [voteStatus, setVoteStatus] = useState(null)
  const [receipt, setReceipt] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(true)

  const loadReceipt = async () => {
    setLoading(true)
    setErrorMsg('')
    try {
      let eid = params?.election_id || (typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('election_id') : null)
      if (!eid) {
        const eleRes = await api.get('/public/elections')
        if (eleRes?.elections?.length) {
          const chosen = selectAuthoritativeElection(eleRes.elections)
          eid = chosen?.election_id || eleRes.elections[0]?.election_id
        }
      }
      if (!eid) {
        setReceipt(null)
        setVoteStatus(null)
        return
      }
      setElectionId(eid)

      let res = null
      let primaryErr = null
      try {
        res = await api.get(`/voting/status?election_id=${encodeURIComponent(eid)}`)
      } catch (err) {
        primaryErr = err
      }

      if (!res?.receipt) {
        try {
          const v2Res = await api.get(`/v2/voting/status?election_id=${encodeURIComponent(eid)}`)
          if (v2Res && (v2Res.receipt || v2Res.has_voted || v2Res.status)) {
            res = v2Res
          }
        } catch (v2Err) {
          if (!res && primaryErr) {
            throw v2Err || primaryErr
          }
        }
      }

      setVoteStatus(res || null)
      setReceipt(res?.receipt || null)
    } catch (err) {
      setErrorMsg(err?.payload?.message || err?.payload?.error || err?.message || 'Unable to load receipt status.')
      setReceipt(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadReceipt()
  }, [params?.election_id])

  const copyToClipboard = () => {
    if (receipt?.receipt_code && typeof navigator !== 'undefined') {
      navigator.clipboard.writeText(receipt.receipt_code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const downloadTextReceipt = () => {
    if (!receipt) return
    const content = `VOTE WITHOUT DOUBT - OFFICIAL VOTE RECEIPT
===========================================
Election:       ${receipt.election_title || 'Student Council Election'}
Receipt Code:   ${receipt.receipt_code}
Timestamp:      ${receipt.timestamp}
Voter ID (Last 4): ${receipt.voter_id_last4 || '****'}
-------------------------------------------
This HMAC receipt proves your ballot was finalized on the blockchain ledger.
In compliance with cryptographic privacy invariants, this receipt deliberately
omits your candidate choice, Ethereum address, transaction hash, and pseudonym.
===========================================`

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `Vote_Receipt_${receipt.receipt_code}.txt`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page-container receipt-page" style={{ maxWidth: '720px', margin: '0 auto' }}>
      <div className="card">
        <span className="badge badge-accent">OFFICIAL BALLOT RECEIPT</span>
        <h2 className="card-title">Official Voting Receipt</h2>
        <p>
          Your ballot has been safely received and recorded in the digital ballot box. Keep this receipt code to verify that your ballot is part of the election records.
        </p>

        {loading ? (
          <p style={{ marginTop: '1rem', fontWeight: 700 }}>Retrieving your official receipt...</p>
        ) : errorMsg ? (
          <div className="alert-box alert-error" style={{ marginTop: '1.5rem' }}>
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.35rem' }}>Unable to Load Receipt</h4>
            <p>{errorMsg}</p>
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
              <button className="btn btn-primary" onClick={loadReceipt}>
                Retry &#x21bb;
              </button>
              <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/my-vote?election_id=${encodeURIComponent(electionId)}` : '/my-vote')}>
                &larr; Return to My Vote
              </button>
            </div>
          </div>
        ) : receipt ? (
          <div className="card-white" style={{ marginTop: '1.75rem', border: '4px solid #000', boxShadow: '8px 8px 0px #000', padding: '2rem' }}>
            {/* Header of physical ballot slip */}
            <div style={{ textAlign: 'center', borderBottom: '3px dashed #000', paddingBottom: '1.25rem', marginBottom: '1.5rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#4B5563' }}>
                Collegiate Election Board • Official Proof of Vote
              </div>
              <h3 style={{ fontSize: '1.4rem', fontWeight: 900, textTransform: 'uppercase', margin: '0.5rem 0' }}>
                {receipt.election_title || 'Student Council Election'}
              </h3>
              <span className="badge badge-verified">
                ✓ BALLOT RECORDED
              </span>
            </div>

            {/* Receipt Code Box */}
            <div style={{ background: 'var(--neo-cream, #FFFDF5)', border: '3px solid #000', padding: '1.5rem', textAlign: 'center', marginBottom: '1.5rem', boxShadow: '4px 4px 0px #000' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 900, textTransform: 'uppercase', color: '#4B5563', letterSpacing: '0.05em' }}>
                Your Official Receipt Code
              </div>
              <div style={{ fontSize: 'clamp(1.1rem, 2.5vw, 1.4rem)', fontFamily: 'monospace', fontWeight: 900, margin: '0.75rem 0', wordBreak: 'break-all', color: '#000000' }}>
                <code>{receipt.receipt_code}</code>
              </div>
              <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', marginTop: '1rem', flexWrap: 'wrap' }}>
                <button className="btn btn-secondary" onClick={copyToClipboard}>
                  {copied ? '✓ Copied to Clipboard!' : 'Copy Receipt Code'}
                </button>
                <button className="btn btn-primary" onClick={downloadTextReceipt}>
                  Download Receipt (.txt)
                </button>
              </div>
            </div>

            {/* Receipt Meta */}
            <div className="election-meta-grid" style={{ marginBottom: '1.5rem' }}>
              <div className="meta-item">
                <span className="meta-label">Submission Timestamp</span>
                <span className="meta-value">{receipt.timestamp}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Ballot Sequence</span>
                <span className="meta-value">Submission #{receipt.sequence || 1} (Confirmed)</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Voter Scope</span>
                <span className="meta-value">ID ends in {receipt.voter_id_last4 || '****'}</span>
              </div>
            </div>

            {/* Privacy Warning */}
            <div className="alert-box alert-info" style={{ fontSize: '0.9rem', lineHeight: '1.5' }}>
              <strong>What this receipt proves:</strong> This receipt confirms your ballot was recorded in the election system.
              To protect your vote privacy and prevent coercion, this receipt deliberately <strong>omits your candidate choice</strong>.
              Inclusion in the final tally is verified after the election closes and all ballots are tallied.
            </div>

            <div style={{ display: 'flex', gap: '1rem', marginTop: '1.75rem', justifyContent: 'space-between', flexWrap: 'wrap', borderTop: '3px solid #000', paddingTop: '1.25rem' }}>
              <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/my-vote?election_id=${encodeURIComponent(electionId)}` : '/my-vote')}>
                &larr; Return to My Vote
              </button>
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                <button
                  className="btn btn-secondary"
                  onClick={() => navigate(electionId ? `/receipt-verification?election_id=${encodeURIComponent(electionId)}` : '/receipt-verification')}
                >
                  Verify This Receipt &rarr;
                </button>
                <button className="btn btn-primary" onClick={() => navigate(electionId ? `/verification?election_id=${encodeURIComponent(electionId)}` : '/verification')}>
                  Verify Election On-Chain &rarr;
                </button>
              </div>
            </div>
          </div>
        ) : ['QUEUED', 'SUBMITTED', 'PENDING', 'UNCERTAIN'].includes(String(voteStatus?.status || voteStatus?.state || '').toUpperCase()) ? (
          <div className="alert-box alert-info" style={{ marginTop: '1.5rem' }}>
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.35rem' }}>Ballot Confirmation Pending</h4>
            <p>
              Your ballot submission (status: <strong>{String(voteStatus?.status || voteStatus?.state).toUpperCase()}</strong>) has been received and is awaiting blockchain confirmation. Your official receipt code will appear here automatically once confirmed.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
              <button className="btn btn-primary" onClick={loadReceipt}>
                Refresh Status &#x21bb;
              </button>
              <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/my-vote?election_id=${encodeURIComponent(electionId)}` : '/my-vote')}>
                &larr; Return to My Vote
              </button>
            </div>
          </div>
        ) : ['FAILED', 'REVERTED'].includes(String(voteStatus?.status || voteStatus?.state || '').toUpperCase()) ? (
          <div className="alert-box alert-warning" style={{ marginTop: '1.5rem' }}>
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.35rem' }}>Previous Submission Did Not Confirm</h4>
            <p>
              Your latest submission attempt did not settle on-chain ({voteStatus?.error || String(voteStatus?.status || voteStatus?.state).toUpperCase()}). Check My Vote for retry status.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
              <button className="btn btn-primary" onClick={() => navigate(electionId ? `/my-vote?election_id=${encodeURIComponent(electionId)}` : '/my-vote')}>
                &larr; Check My Vote
              </button>
              <button className="btn btn-secondary" onClick={() => navigate(electionId ? `/vote?election_id=${encodeURIComponent(electionId)}` : '/vote')}>
                Return to Voting &rarr;
              </button>
            </div>
          </div>
        ) : (
          <div className="alert-box alert-warning" style={{ marginTop: '1.5rem' }}>
            <h4 style={{ textTransform: 'uppercase', fontWeight: 900, marginBottom: '0.35rem' }}>No Finalized Ballot Found</h4>
            <p>You have not finalized a vote in the active election yet.</p>
            <button className="btn btn-primary" onClick={() => navigate(electionId ? `/vote?election_id=${encodeURIComponent(electionId)}` : '/vote')} style={{ marginTop: '0.75rem' }}>
              Cast Your Vote &rarr;
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
