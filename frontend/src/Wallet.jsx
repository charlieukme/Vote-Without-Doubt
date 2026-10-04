import { useState, useEffect } from 'react'
import './Auth.css'

function Wallet() {
  const [account, setAccount] = useState(null)
  const [hasMetaMask, setHasMetaMask] = useState(false)
  const [status, setStatus] = useState('')
  const [nonce, setNonce] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (window.ethereum) setHasMetaMask(true)
    checkStatus()
  }, [])

  const checkStatus = async () => {
    try {
      const res = await fetch('/api/wallet/status', { credentials: 'include' })
      const data = await res.json()
      if (data.bound) setStatus('Wallet bound: ' + data.wallet_address.slice(0, 10) + '...')
    } catch (e) {
      // ignore
    }
  }

  const connect = async () => {
    try {
      const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' })
      setAccount(accounts[0])
      setStatus('Connected: ' + accounts[0].slice(0, 10) + '...')
    } catch (e) {
      setStatus('Connection rejected')
    }
  }

  const getChallenge = async () => {
    try {
      const res = await fetch('/api/wallet/challenge', { method: 'POST', credentials: 'include' })
      const data = await res.json()
      if (res.ok) {
        setNonce(data.nonce)
        setMessage(data.message)
        setStatus('Challenge received')
      } else {
        setStatus(data.error || 'Challenge failed')
      }
    } catch (e) {
      setStatus('Challenge failed')
    }
  }

  const sign = async () => {
    try {
      const signature = await window.ethereum.request({
        method: 'personal_sign',
        params: [message, account]
      })
      const res = await fetch('/api/wallet/bind', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ nonce, signature, wallet_address: account })
      })
      const data = await res.json()
      if (res.ok) {
        setStatus('Wallet bound successfully')
        checkStatus()
      } else {
        setStatus(data.error || 'Binding failed')
      }
    } catch (e) {
      setStatus('Signature rejected')
    }
  }

  return (
    <div className="auth-container" style={{ marginTop: '1.5rem' }}>
      <h2 className="auth-title">Wallet Auth (Phase 4)</h2>
      {status && <div className="auth-status">{status}</div>}
      {!hasMetaMask && <div>MetaMask not detected</div>}
      {hasMetaMask && !account && <button className="auth-btn" onClick={connect}>Connect MetaMask</button>}
      {account && !nonce && <button className="auth-btn" onClick={getChallenge}>Get Challenge</button>}
      {account && nonce && <button className="auth-btn" onClick={sign}>Sign & Bind</button>}
    </div>
  )
}

export default Wallet
