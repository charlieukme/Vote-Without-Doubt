import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../../api/client.js'
import { useAuth } from '../../router/AuthContext'
import { useRouter } from '../../router/RouterContext'
import {
  generateClientSecureScalar,
  generateClientSchnorrPoP,
  generateClientDecryptionShares,
  pointMul,
  G,
  isInfinity,
} from '../../utils/bn254_client.js'
import {
  exportEncryptedOfficerBackup,
  importEncryptedOfficerBackup,
} from '../../utils/officerBackup.js'

const STATE_NAMES = [
  '0: Setup (Registration Pending)',
  '1: Officer 1 Registered',
  '2: Officer 2 Registered',
  '3: Key Registration Complete (Voting Ready)',
  '4: Voting Open',
  '5: Voting Closed (Awaiting Decryption Shares)',
  '6: Decryption Shares Complete (Tally Ready)',
  '7: Election Finalized (Results Certified)',
  '8: Tally Stalled (72h Deadline Expired)',
]

export default function OfficerDashboardPage() {
  const { adminAuth } = useAuth()
  const { navigate } = useRouter()

  // Election and Officer Context
  const [electionId, setElectionId] = useState('1')
  const [contractAddress, setContractAddress] = useState('')
  const [officerId, setOfficerId] = useState(() => {
    if (adminAuth?.admin_id === 'OFFICER_02') return 2
    return 1
  })
  const [officerAddress, setOfficerAddress] = useState('')

  // In-Memory Key State (NEVER persisted to localStorage or sessionStorage)
  const [privKey, setPrivKey] = useState(null) // BigInt in React memory
  const [pubKey, setPubKey] = useState(null) // {x: BigInt, y: BigInt}

  // Backup & Recovery state
  const [backupPassword, setBackupPassword] = useState('')
  const [restorePassword, setRestorePassword] = useState('')
  const [restoreFileContent, setRestoreFileContent] = useState('')
  const [backupDownloaded, setBackupDownloaded] = useState(false)

  // Status and UI state
  const [keyStatus, setKeyStatus] = useState(null)
  const [aggregateCiphertexts, setAggregateCiphertexts] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [txReceipt, setTxReceipt] = useState(null)

  // Auto-detect officer address if MetaMask is connected
  useEffect(() => {
    if (typeof window !== 'undefined' && window.ethereum) {
      window.ethereum
        .request({ method: 'eth_accounts' })
        .then((accounts) => {
          if (accounts && accounts.length > 0) {
            setOfficerAddress(accounts[0])
          }
        })
        .catch(() => {})
    }
  }, [])

  // Fetch Key Status from backend
  const fetchKeyStatus = useCallback(async () => {
    if (!electionId) return
    setError('')
    try {
      const q = new URLSearchParams({ election_id: electionId })
      if (contractAddress) q.set('contract_address', contractAddress)
      const data = await api.get(`/v2/officer/key-status?${q.toString()}`)
      setKeyStatus(data)

      // If voting closed, fetch aggregate ciphertexts for decryption
      if (data && data.state >= 5) {
        try {
          const aggData = await api.get(`/v2/officer/aggregate-ciphertexts?${q.toString()}`)
          setAggregateCiphertexts(aggData)
        } catch {
          // Aggregate might not be available if 0 votes cast or tally not initiated
        }
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch election key status')
    }
  }, [electionId, contractAddress])

  useEffect(() => {
    fetchKeyStatus()
  }, [fetchKeyStatus])

  // Connect MetaMask
  const handleConnectWallet = async () => {
    if (typeof window === 'undefined' || !window.ethereum) {
      setError('MetaMask or Web3 wallet not detected')
      return
    }
    try {
      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      if (accounts && accounts.length > 0) {
        setOfficerAddress(accounts[0])
        setSuccessMsg(`Wallet connected: ${accounts[0]}`)
      }
    } catch (err) {
      setError(err.message || 'Failed to connect wallet')
    }
  }

  // 1. Generate New BN254 Keypair in Browser Memory
  const handleGenerateKeypair = () => {
    setError('')
    setSuccessMsg('')
    try {
      const sk = generateClientSecureScalar()
      const pk = pointMul(G, sk)
      setPrivKey(sk)
      setPubKey(pk)
      setBackupDownloaded(false)
      setSuccessMsg('New BN254 keypair generated securely in browser memory. Please export an encrypted backup now!')
    } catch (err) {
      setError('Key generation error: ' + err.message)
    }
  }

  // 2. Export Encrypted Backup (PBKDF2 + AES-256-GCM)
  const handleExportBackup = async (e) => {
    e.preventDefault()
    if (!privKey) {
      setError('No private key in memory to export')
      return
    }
    if (!backupPassword || backupPassword.length < 8) {
      setError('Password must be at least 8 characters long')
      return
    }

    try {
      setLoading(true)
      const backupData = await exportEncryptedOfficerBackup(
        privKey,
        officerId,
        electionId,
        backupPassword
      )

      // Trigger browser file download
      const blob = new Blob([JSON.stringify(backupData, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `vwd_officer_${officerId}_election_${electionId}_backup.json`
      a.click()
      URL.revokeObjectURL(url)

      setBackupDownloaded(true)
      setBackupPassword('')
      setSuccessMsg('Encrypted key backup downloaded successfully! Store this file safely to decrypt election tallies.')
    } catch (err) {
      setError('Export failed: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  // 3. Restore / Import Encrypted Backup
  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (evt) => {
      setRestoreFileContent(evt.target?.result || '')
    }
    reader.readAsText(file)
  }

  const handleImportBackup = async (e) => {
    e.preventDefault()
    if (!restoreFileContent) {
      setError('Please select an encrypted backup file to import')
      return
    }
    if (!restorePassword) {
      setError('Please enter the backup password')
      return
    }

    try {
      setLoading(true)
      const recovered = await importEncryptedOfficerBackup(restoreFileContent, restorePassword)
      setPrivKey(recovered.privKey)
      setPubKey(recovered.pubKey)
      setOfficerId(recovered.officerId)
      if (recovered.electionId) setElectionId(String(recovered.electionId))
      setRestorePassword('')
      setSuccessMsg(`Successfully restored Officer ${recovered.officerId} key into browser memory!`)
    } catch (err) {
      setError('Restore failed: ' + err.message)
    } finally {
      setLoading(false)
    }
  }

  // 4. Register Officer Public Key + Client-Side Schnorr PoP
  const handleRegisterPublicKey = async () => {
    setError('')
    setSuccessMsg('')
    setTxReceipt(null)

    if (!privKey || !pubKey) {
      setError('No keypair available. Generate a keypair or import an encrypted backup first.')
      return
    }
    if (!backupDownloaded) {
      if (!window.confirm('WARNING: You have not downloaded an encrypted backup of your key yet! If you lose this key, you will NOT be able to participate in tally decryption. Continue anyway?')) {
        return
      }
    }

    try {
      setLoading(true)
      // Generate Schnorr PoP in browser
      const pop = generateClientSchnorrPoP({
        privKey,
        officerId,
        electionId,
        contractAddress: contractAddress || undefined,
        chainId: 1337,
      })

      const payload = {
        election_id: electionId,
        officer_id: officerId,
        pub_key: {
          x: '0x' + pubKey.x.toString(16).padStart(64, '0'),
          y: '0x' + pubKey.y.toString(16).padStart(64, '0'),
        },
        pop: {
          r: {
            x: '0x' + pop.r.x.toString(16).padStart(64, '0'),
            y: '0x' + pop.r.y.toString(16).padStart(64, '0'),
          },
          z: '0x' + pop.z.toString(16).padStart(64, '0'),
        },
        contract_address: contractAddress || undefined,
      }

      const res = await api.post('/v2/officer/register-key', payload)
      setTxReceipt(res)
      setSuccessMsg(`Officer ${officerId} registered on-chain successfully via relayer! Tx: ${res.tx_hash || 'Confirmed'}`)
      fetchKeyStatus()
    } catch (err) {
      setError('Registration failed: ' + (err.message || String(err)))
    } finally {
      setLoading(false)
    }
  }

  // 5. Generate & Submit Decryption Shares + DLEQ Proofs (When Voting Closed)
  const handleSubmitDecryptionShares = async () => {
    setError('')
    setSuccessMsg('')
    setTxReceipt(null)

    if (!privKey) {
      setError('Private scalar not found in memory. Please restore from your encrypted backup file.')
      return
    }
    if (!aggregateCiphertexts || !aggregateCiphertexts.aggregate_a) {
      setError('Aggregate ciphertexts not available for this election yet.')
      return
    }

    try {
      setLoading(true)
      const aggA = aggregateCiphertexts.aggregate_a.map((pt) => ({
        x: BigInt(pt.x),
        y: BigInt(pt.y),
      }))

      // Client-side DLEQ generation (handles infinity branch automatically)
      const { shares, proofs } = generateClientDecryptionShares({
        officerPrivKey: privKey,
        officerId,
        aggregateA: aggA,
        electionId,
        contractAddress: contractAddress || undefined,
        chainId: 1337,
      })

      const payload = {
        election_id: electionId,
        officer_id: officerId,
        shares,
        proofs,
        contract_address: contractAddress || undefined,
      }

      const res = await api.post('/v2/officer/submit-shares', payload)
      setTxReceipt(res)
      setSuccessMsg(`Decryption shares and Chaum-Pedersen DLEQ proofs verified and accepted on-chain! Tx: ${res.tx_hash || 'Confirmed'}`)
      fetchKeyStatus()
    } catch (err) {
      setError('Share submission failed: ' + (err.message || String(err)))
    } finally {
      setLoading(false)
    }
  }

  const role = adminAuth?.role || 'OFFICER'
  const isOfficer1Registered = keyStatus?.officer1_registered
  const isOfficer2Registered = keyStatus?.officer2_registered
  const currentStateName = keyStatus ? (STATE_NAMES[keyStatus.state] || `State ${keyStatus.state}`) : 'Loading...'

  return (
    <div className="admin-page-container officer-dashboard">
      <div className="page-header">
        <span className="badge badge-accent">FIX 3 V2 CRYPTOGRAPHIC GOVERNANCE</span>
        <h2>Election Officer Custody Console</h2>
        <p className="page-subtitle">
          Two-Officer independent threshold key generation, client-side Schnorr Proof-of-Possession,
          and verifiable Chaum-Pedersen DLEQ decryption.
        </p>
      </div>

      {/* Security Invariant Callout */}
      <div className="card security-banner" style={{ background: 'rgba(30, 41, 59, 0.7)', border: '1px solid rgba(99, 102, 241, 0.4)', marginBottom: '1.5rem', padding: '1rem 1.25rem' }}>
        <h4 style={{ color: '#818cf8', margin: '0 0 0.5rem 0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span>🛡️</span> Zero-Knowledge Officer Custody Invariants
        </h4>
        <ul style={{ margin: 0, paddingLeft: '1.25rem', color: '#cbd5e1', fontSize: '0.875rem', lineHeight: '1.5' }}>
          <li><strong>Private Key Isolation:</strong> Officer private scalar is generated in browser memory and NEVER transmitted to Flask or any backend service.</li>
          <li><strong>Storage Isolation:</strong> Plaintext private keys are NEVER written to localStorage or sessionStorage.</li>
          <li><strong>Encrypted Backup:</strong> Keys are saved offline using Argon2id (64MB, 3 iterations, 4 lanes) + AES-256-GCM with canonical AAD binding.</li>
        </ul>
      </div>

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: '1rem', padding: '0.85rem', background: '#451a1a', border: '1px solid #f87171', color: '#fca5a5', borderRadius: '6px' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {successMsg && (
        <div className="alert alert-success" role="status" style={{ marginBottom: '1rem', padding: '0.85rem', background: '#064e3b', border: '1px solid #34d399', color: '#a7f3d0', borderRadius: '6px' }}>
          {successMsg}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem', marginBottom: '1.5rem' }}>
        {/* Panel 1: Election & Contract State */}
        <div className="card" style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '8px' }}>
          <h3 style={{ marginTop: 0, borderBottom: '1px solid #334155', paddingBottom: '0.5rem' }}>
            Election Lifecycle & Status
          </h3>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Election ID:</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={electionId}
                onChange={(e) => setElectionId(e.target.value)}
                style={{ flex: 1, padding: '0.5rem', background: '#0f172a', border: '1px solid #334155', color: '#f8fafc', borderRadius: '4px' }}
              />
              <button
                className="btn btn-secondary"
                onClick={fetchKeyStatus}
                disabled={loading}
                style={{ padding: '0.5rem 1rem' }}
              >
                Refresh
              </button>
            </div>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Contract Address (Optional override):</label>
            <input
              type="text"
              placeholder="0x... (leave empty for backend default)"
              value={contractAddress}
              onChange={(e) => setContractAddress(e.target.value)}
              style={{ width: '100%', padding: '0.5rem', background: '#0f172a', border: '1px solid #334155', color: '#f8fafc', borderRadius: '4px' }}
            />
          </div>

          <div style={{ background: '#0f172a', padding: '1rem', borderRadius: '6px', fontSize: '0.9rem' }}>
            <div style={{ marginBottom: '0.5rem' }}>
              <strong>Contract State:</strong>{' '}
              <span style={{ color: '#38bdf8', fontWeight: 600 }}>{currentStateName}</span>
            </div>
            <div style={{ marginBottom: '0.5rem' }}>
              <strong>Officer 1 Registration:</strong>{' '}
              <span style={{ color: isOfficer1Registered ? '#4ade80' : '#f87171' }}>
                {isOfficer1Registered ? '✓ Registered' : 'Pending'}
              </span>
            </div>
            <div style={{ marginBottom: '0.5rem' }}>
              <strong>Officer 2 Registration:</strong>{' '}
              <span style={{ color: isOfficer2Registered ? '#4ade80' : '#f87171' }}>
                {isOfficer2Registered ? '✓ Registered' : 'Pending'}
              </span>
            </div>
            {keyStatus?.joint_public_key && (
              <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', color: '#94a3b8', wordBreak: 'break-all' }}>
                <strong>Joint Public Key (Y):</strong>
                <div>X: {keyStatus.joint_public_key.x}</div>
                <div>Y: {keyStatus.joint_public_key.y}</div>
              </div>
            )}
          </div>
        </div>

        {/* Panel 2: Officer Identity & Session */}
        <div className="card" style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '8px' }}>
          <h3 style={{ marginTop: 0, borderBottom: '1px solid #334155', paddingBottom: '0.5rem' }}>
            Officer Identity & Session
          </h3>

          <div style={{ marginBottom: '1rem', background: '#0f172a', padding: '0.75rem', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85rem', color: '#94a3b8' }}>Authenticated Session:</div>
            <div style={{ fontSize: '1rem', fontWeight: 600, color: '#38bdf8', marginTop: '0.25rem' }}>
              👤 {adminAuth?.admin_id || 'OFFICER'} ({role})
            </div>
            <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.25rem' }}>
              ✓ Gas-free execution: Blockchain transactions relayed securely by authorized relayer.
            </div>
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Designated Role Share:</label>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="officerId"
                  value={1}
                  checked={officerId === 1}
                  onChange={() => setOfficerId(1)}
                />
                Officer 1 (Chief)
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="officerId"
                  value={2}
                  checked={officerId === 2}
                  onChange={() => setOfficerId(2)}
                />
                Officer 2 (Deputy)
              </label>
            </div>
          </div>

          <div style={{ background: '#0f172a', padding: '1rem', borderRadius: '6px', fontSize: '0.9rem' }}>
            <div>
              <strong>Current Private Key Status:</strong>{' '}
              <span style={{ color: privKey ? '#4ade80' : '#fbbf24', fontWeight: 600 }}>
                {privKey ? '✓ Loaded in Browser Memory' : 'No Key in Memory'}
              </span>
            </div>
            {pubKey && (
              <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: '#94a3b8', wordBreak: 'break-all' }}>
                <strong>Public Key Share:</strong>
                <div>X: 0x{pubKey.x.toString(16)}</div>
                <div>Y: 0x{pubKey.y.toString(16)}</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Panel 3: Key Generation & Registration */}
      <div className="card" style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '8px', marginBottom: '1.5rem' }}>
        <h3 style={{ marginTop: 0, borderBottom: '1px solid #334155', paddingBottom: '0.5rem' }}>
          Step 1: Generate & Register Officer Public Key
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem', marginTop: '1rem' }}>
          {/* Action A: Generate in Browser */}
          <div style={{ background: '#0f172a', padding: '1.25rem', borderRadius: '6px' }}>
            <h4 style={{ margin: '0 0 0.5rem 0', color: '#38bdf8' }}>Option A: Generate Keypair</h4>
            <p style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '1rem' }}>
              Generates a cryptographically secure BN254 scalar using <code>window.crypto.getRandomValues</code>.
            </p>
            <button
              className="btn btn-primary"
              onClick={handleGenerateKeypair}
              disabled={loading}
              style={{ width: '100%', marginBottom: '1rem' }}
            >
              Generate New Keypair
            </button>

            {privKey && (
              <form onSubmit={handleExportBackup} style={{ borderTop: '1px solid #334155', paddingTop: '1rem' }}>
                <h5 style={{ margin: '0 0 0.5rem 0', color: '#a7f3d0' }}>Export Encrypted Backup</h5>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Passphrase (min 8 chars):</label>
                <input
                  type="password"
                  placeholder="Enter strong passphrase..."
                  value={backupPassword}
                  onChange={(e) => setBackupPassword(e.target.value)}
                  style={{ width: '100%', padding: '0.4rem', background: '#1e293b', border: '1px solid #475569', color: '#fff', borderRadius: '4px', marginBottom: '0.5rem' }}
                />
                <button
                  type="submit"
                  className="btn btn-secondary"
                  style={{ width: '100%', background: '#059669', borderColor: '#10b981', color: '#fff' }}
                  disabled={loading || !backupPassword}
                >
                  Download Encrypted Backup (.json)
                </button>
              </form>
            )}
          </div>

          {/* Action B: Restore from Backup */}
          <div style={{ background: '#0f172a', padding: '1.25rem', borderRadius: '6px' }}>
            <h4 style={{ margin: '0 0 0.5rem 0', color: '#38bdf8' }}>Option B: Restore Key From Backup</h4>
            <p style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '1rem' }}>
              Restore your private scalar from an existing encrypted backup file into browser memory.
            </p>
            <form onSubmit={handleImportBackup}>
              <div style={{ marginBottom: '0.75rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Select Backup File:</label>
                <input
                  type="file"
                  accept=".json"
                  onChange={handleFileChange}
                  style={{ width: '100%', fontSize: '0.85rem', color: '#cbd5e1' }}
                />
              </div>
              <div style={{ marginBottom: '0.75rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', color: '#94a3b8', marginBottom: '0.25rem' }}>Passphrase:</label>
                <input
                  type="password"
                  placeholder="Passphrase used during export..."
                  value={restorePassword}
                  onChange={(e) => setRestorePassword(e.target.value)}
                  style={{ width: '100%', padding: '0.4rem', background: '#1e293b', border: '1px solid #475569', color: '#fff', borderRadius: '4px' }}
                />
              </div>
              <button
                type="submit"
                className="btn btn-secondary"
                disabled={loading || !restoreFileContent || !restorePassword}
                style={{ width: '100%' }}
              >
                Restore Key into Memory
              </button>
            </form>
          </div>
        </div>

        {/* Submit Public Key + Schnorr PoP */}
        <div style={{ marginTop: '1.5rem', background: '#0f172a', padding: '1.25rem', borderRadius: '6px', textAlign: 'center' }}>
          <p style={{ fontSize: '0.9rem', color: '#cbd5e1', marginBottom: '1rem' }}>
            Computes Schnorr Proof-of-Possession <code>(R, z)</code> client-side and registers public key share on-chain.
          </p>
          <button
            className="btn btn-primary"
            onClick={handleRegisterPublicKey}
            disabled={loading || !privKey || !officerAddress}
            style={{ padding: '0.75rem 2rem', fontSize: '1rem', fontWeight: 600 }}
          >
            {loading ? 'Submitting...' : `Register Officer ${officerId} Public Key & Submit PoP`}
          </button>
        </div>
      </div>

      {/* Panel 4: Decryption Share Generation & Submission */}
      <div className="card" style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '8px' }}>
        <h3 style={{ marginTop: 0, borderBottom: '1px solid #334155', paddingBottom: '0.5rem' }}>
          Step 2: Generate & Submit Partial Decryption Shares (Tally Decryption)
        </h3>
        <p style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '1rem' }}>
          Available when election state is <strong>Voting Closed (State 5)</strong>. Generates partial decryption shares <code>D_i[j] = sk * A_agg[j]</code> and verifiable Chaum-Pedersen DLEQ NIZK proofs client-side.
        </p>

        {keyStatus?.state < 5 ? (
          <div style={{ background: '#0f172a', padding: '1rem', borderRadius: '6px', color: '#fbbf24', fontSize: '0.9rem' }}>
            ⏸ Voting is still active or key registration is in progress. Decryption share submission will unlock once the election is closed.
          </div>
        ) : (
          <div>
            <div style={{ background: '#0f172a', padding: '1rem', borderRadius: '6px', marginBottom: '1rem', fontSize: '0.85rem' }}>
              <strong>Aggregate Ciphertexts Status:</strong>{' '}
              {aggregateCiphertexts ? (
                <span style={{ color: '#4ade80' }}>
                  ✓ {aggregateCiphertexts.candidate_count} candidates loaded from blockchain
                </span>
              ) : (
                <span style={{ color: '#f87171' }}>Fetching aggregate ciphertexts...</span>
              )}
            </div>

            <button
              className="btn btn-primary"
              onClick={handleSubmitDecryptionShares}
              disabled={loading || !privKey || !aggregateCiphertexts}
              style={{ padding: '0.75rem 2rem', fontSize: '1rem', fontWeight: 600, background: '#4f46e5' }}
            >
              {loading ? 'Generating DLEQ Proofs...' : `Generate & Submit Officer ${officerId} Decryption Shares`}
            </button>
          </div>
        )}
      </div>

      {txReceipt && (
        <div className="card" style={{ marginTop: '1.5rem', background: '#0f172a', border: '1px solid #3b82f6', padding: '1rem', borderRadius: '6px' }}>
          <h4 style={{ margin: '0 0 0.5rem 0', color: '#60a5fa' }}>Transaction Receipt</h4>
          <pre style={{ margin: 0, fontSize: '0.8rem', color: '#cbd5e1', overflowX: 'auto' }}>
            {JSON.stringify(txReceipt, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
