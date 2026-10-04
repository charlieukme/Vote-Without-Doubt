import { useState } from 'react'
import './Voting.css'

const API_BASE = 'http://localhost:5000/api'

function Voting() {
  const [step, setStep] = useState('start')
  const [candidate, setCandidate] = useState(0)
  const [receipt, setReceipt] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const begin = async () => {
    setLoading(true)
    try {
      await fetch(API_BASE + '/voting/authorize', { method:'POST', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify({election_id:1}) })
      await fetch(API_BASE + '/voting/mark-factors', { method:'POST', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify({election_id:1}) })
      setStep('select')
    } catch (e) { setError('Auth failed') }
    setLoading(false)
  }

  const submit = async () => {
    setLoading(true)
    try {
      const res = await fetch(API_BASE + '/voting/submit', { method:'POST', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify({election_id:1, candidate}) })
      if (res.ok) {
        const d = await res.json()
        setReceipt(d.receipt)
        setStep('done')
      } else { setError('Submit failed') }
    } catch (e) { setError('Submit failed') }
    setLoading(false)
  }

  return (
    <div className="voting-container">
      <h2>Voting (Phase 7 - Core)</h2>
      {step==='start' && <button onClick={begin} disabled={loading}>Begin Secure Voting</button>}
      {step==='select' && (
        <div>
          <div className="candidates">
            <label><input type="radio" checked={candidate===0} onChange={()=>setCandidate(0)} /> Candidate A</label>
            <label><input type="radio" checked={candidate===1} onChange={()=>setCandidate(1)} /> Candidate B</label>
          </div>
          <button onClick={submit} disabled={loading}>Confirm & Submit</button>
        </div>
      )}
      {step==='done' && (
        <div className="receipt">
          <div>Vote recorded</div>
          <div>Receipt: {receipt}</div>
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  )
}

export default Voting
