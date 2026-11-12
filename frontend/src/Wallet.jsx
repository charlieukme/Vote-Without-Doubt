import { useState, useEffect, useCallback } from 'react'
import './Auth.css'
import { api } from './api/client.js'

/**
 * Phase 4 wallet ownership proof.
 *
 * Security rules enforced here:
 * - the server is the only authority. This component never declares the wallet
 *   "verified"; it renders only what /wallet/status reports after the backend has
 *   recovered the signing address itself;
 * - the message that gets signed comes from the server. The browser never
 *   authors it, and any client-supplied copy is ignored server-side;
 * - no private key or seed phrase is ever requested, displayed or stored;
 * - the signature is held in component state only long enough to POST it, then
 *   dropped. It is never written to web storage;
 * - the connected network is read from MetaMask with eth_chainId and compared
 *   against the server-advertised expected chain. A mismatch stops the flow;
 * - accountsChanged, chainChanged and disconnect all reset the flow, so a
 *   challenge signed for one account or network can never be submitted under
 *   another. Listeners are removed on unmount.
 */
function Wallet({ onBound, onStatusChange } = {}) {
  const [account, setAccount] = useState(null)
  const [hasMetaMask, setHasMetaMask] = useState(false)
  const [chainId, setChainId] = useState(null)
  const [expectedChainId, setExpectedChainId] = useState(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [challenge, setChallenge] = useState(null)
  const [signature, setSignature] = useState(null)
  const [bound, setBound] = useState(false)
  const [boundAddress, setBoundAddress] = useState(null)

  const resetFlow = useCallback((reason) => {
    setChallenge(null)
    setSignature(null)
    setStatus(reason || '')
  }, [])

  const checkStatus = useCallback(async () => {
    try {
      const data = await api.get('/wallet/status')
      setBound(Boolean(data && data.bound))
      if (data && data.expected_chain_id) {
        setExpectedChainId(data.expected_chain_id)
      }
      if (Boolean(data && data.bound)) {
        const addr = data.wallet_address || null
        setBoundAddress(addr)
        setStatus('Wallet bound: ' + String(addr).slice(0, 10) + '...')
        setError('')
        if (typeof onBound === 'function') {
          onBound(addr)
        }
        if (typeof onStatusChange === 'function') {
          onStatusChange(true, addr)
        }
      } else {
        setBoundAddress(null)
        if (typeof onStatusChange === 'function') {
          onStatusChange(false, null)
        }
      }
    } catch (err) {
      // Differentiate transient rate limits (429) or network timeouts from genuine unverified state
      if (err && err.status === 429) {
        setError('Rate limit reached during status check. Please wait a moment.')
      } else if (err && err.status === 0) {
        setError('Network error checking wallet status.')
      } else {
        setBound(false)
        setBoundAddress(null)
        if (typeof onStatusChange === 'function') {
          onStatusChange(false, null)
        }
      }
    }
  }, [onBound, onStatusChange])

  const connect = useCallback(async () => {
    setError('')
    setBusy(true)
    try {
      const provider = window.ethereum
      if (!provider) {
        setError('MetaMask is not installed in this browser.')
        return
      }

      const accounts = await provider.request({ method: 'eth_requestAccounts' })
      if (!Array.isArray(accounts) || accounts.length === 0) {
        setError('No account was returned by MetaMask.')
        return
      }

      // Read the real network rather than assuming one.
      const chainHex = await provider.request({ method: 'eth_chainId' })
      const chain = parseInt(chainHex, 16)

      setAccount(accounts[0])
      setChainId(chain)
      const connectedAddr = accounts[0]
      if (boundAddress && connectedAddr.toLowerCase() === boundAddress.toLowerCase()) {
        setStatus('Wallet bound: ' + String(boundAddress).slice(0, 10) + '...')
        setError('')
      } else if (boundAddress && connectedAddr.toLowerCase() !== boundAddress.toLowerCase()) {
        setError(`Connected account (${connectedAddr.slice(0, 8)}...) does not match your registered voting wallet (${boundAddress.slice(0, 8)}...). Switch accounts in MetaMask.`)
      } else {
        resetFlow('Connected: ' + connectedAddr.slice(0, 10) + '...')
      }

      // Learn the expected chain from the backend, not from a hard-coded value.
      try {
        const info = await api.get('/wallet/status')
        if (info && info.expected_chain_id) {
          setExpectedChainId(info.expected_chain_id)
        }
      } catch {
        // Non-fatal; the challenge response also carries the expected chain.
      }
    } catch (err) {
      setError(
        (err && err.code === 4001)
          ? 'Connection request was rejected.'
          : (err && err.message) || 'Could not connect to MetaMask.'
      )
    }
    setBusy(false)
  }, [resetFlow])

  // MetaMask presence and lifecycle events.
  useEffect(() => {
    checkStatus()

    const provider = window.ethereum
    if (!provider) {
      setHasMetaMask(false)
      return undefined
    }
    setHasMetaMask(true)

    const onAccountsChanged = (accounts) => {
      const next = Array.isArray(accounts) && accounts.length ? accounts[0] : null
      if (next !== account) {
        setAccount(next)
        if (boundAddress) {
          if (next && next.toLowerCase() === boundAddress.toLowerCase()) {
            setStatus('Wallet bound: ' + String(boundAddress).slice(0, 10) + '...')
            setError('')
            if (typeof onStatusChange === 'function') {
              onStatusChange(true, boundAddress)
            }
            return
          } else if (next) {
            setError(`Connected account (${next.slice(0, 8)}...) does not match your registered voting wallet (${boundAddress.slice(0, 8)}...). Switch accounts in MetaMask.`)
            if (typeof onStatusChange === 'function') {
              onStatusChange(false, null)
            }
            return
          }
        }
        // If not already bound to an identity, reset challenge/signature on account change
        resetFlow('Account changed. Request a new challenge to continue.')
        setError('Account changed - please re-run the wallet proof.')
        if (typeof onStatusChange === 'function') {
          onStatusChange(false, null)
        }
      }
    }

    const onChainChanged = (chainHex) => {
      const chain = parseInt(chainHex, 16)
      setChainId(chain)
      resetFlow('Network changed. Request a new challenge to continue.')
      setError('Network changed - the previous challenge is no longer valid.')
      if (typeof onStatusChange === 'function') {
        onStatusChange(false, null)
      }
    }

    const onDisconnect = () => {
      setAccount(null)
      setChainId(null)
      if (boundAddress) {
        // Identity has a registered wallet on backend, but provider disconnected
        setStatus('Wallet bound: ' + String(boundAddress).slice(0, 10) + '... (MetaMask disconnected)')
        setError('MetaMask disconnected. Please reconnect your registered wallet.')
        if (typeof onStatusChange === 'function') {
          onStatusChange(false, null)
        }
      } else {
        setBound(false)
        resetFlow('Wallet disconnected.')
        setError('MetaMask disconnected.')
        if (typeof onStatusChange === 'function') {
          onStatusChange(false, null)
        }
      }
    }

    provider.on?.('accountsChanged', onAccountsChanged)
    provider.on?.('chainChanged', onChainChanged)
    provider.on?.('disconnect', onDisconnect)

    return () => {
      provider.removeListener?.('accountsChanged', onAccountsChanged)
      provider.removeListener?.('chainChanged', onChainChanged)
      provider.removeListener?.('disconnect', onDisconnect)
    }
  }, [account, resetFlow, checkStatus, onStatusChange])

  const requestChallenge = async () => {
    setError('')
    setStatus('')
    setBusy(true)
    try {
      const data = await api.post('/wallet/challenge')
      setChallenge(data)
      setSignature(null)
      setExpectedChainId(data.expected_chain_id ?? null)
      setStatus('Challenge received. Review it, then sign.')
    } catch (err) {
      setError((err && err.message) || 'Could not request a challenge.')
    }
    setBusy(false)
  }

  const sign = async () => {
    if (!challenge) return
    setError('')
    setBusy(true)
    try {
      // The exact server-issued message is what gets signed.
      const produced = await window.ethereum.request({
        method: 'personal_sign',
        params: [challenge.message, account],
      })
      setSignature(produced)

      await api.post('/wallet/bind', {
        nonce: challenge.nonce,
        signature: produced,
        wallet_address: account,
        chain_id: chainId,
      })

      // The server decides; this component only reflects the result.
      setChallenge(null)
      setSignature(null)
      setStatus('Wallet bound successfully')
      await checkStatus()
      if (typeof onBound === 'function') {
        onBound()
      }
      if (typeof onStatusChange === 'function') {
        onStatusChange(true, account)
      }
    } catch (err) {
      setSignature(null)
      setError(
        (err && err.code === 4001)
          ? 'Signature request was rejected.'
          : (err && err.message) || 'Wallet binding failed.'
      )
    }
    setBusy(false)
  }

  const networkMismatch =
    chainId !== null && expectedChainId !== null && chainId !== expectedChainId

  return (
    <div className="auth-container" style={{ marginTop: '1.5rem' }}>
      <h2 className="auth-title">Wallet Ownership Verification</h2>

      {status && <div className="auth-status" role="status">{status}</div>}

      {!hasMetaMask && (
        <div className="error" role="alert">
          MetaMask was not detected in this browser.
        </div>
      )}

      {hasMetaMask && chainId !== null && (
        <div className="auth-status">
          Network: {chainId}
          {expectedChainId !== null && ` (expected ${expectedChainId})`}
        </div>
      )}

      {networkMismatch && (
        <div className="error" role="alert">
          Wrong network. Switch MetaMask to the expected network before continuing.
        </div>
      )}

      {hasMetaMask && !bound && !account && (
        <button className="auth-btn" onClick={connect} disabled={busy}>
          {busy ? 'Working...' : 'Connect MetaMask'}
        </button>
      )}

      {account && !challenge && !bound && (
        <button
          className="auth-btn"
          onClick={requestChallenge}
          disabled={busy || networkMismatch}
        >
          {busy ? 'Working...' : 'Get Challenge'}
        </button>
      )}

      {challenge && !bound && (
        <div className="auth-form">
          <pre className="auth-hint">{challenge.message}</pre>
          <button className="auth-btn" onClick={sign} disabled={busy}>
            {busy ? 'Waiting for signature...' : 'Sign & Bind'}
          </button>
          <button
            className="auth-btn"
            type="button"
            onClick={() => {
              setChallenge(null)
              setSignature(null)
              setStatus('')
            }}
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      )}

      {bound && (
        <div className="auth-status">Wallet ownership verified by the server.</div>
      )}

      {error && <div className="error" role="alert">{error}</div>}
    </div>
  )
}

export default Wallet