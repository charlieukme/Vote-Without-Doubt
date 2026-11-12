import React from 'react'
import PublicVerification from '../../components/PublicVerification'
import './Pages.css'

export default function PublicVerificationPage() {
  return (
    <div className="page-container public-verification-page">
      <div className="card">
        <span className="badge badge-accent">PUBLIC AUDIT & VERIFIER</span>
        <h2 className="card-title">Cryptographic Election Verifier</h2>
        <p>
          Independently verify election parameters, smart contract state, cryptographic candidate hashes,
          electoral-roll SHA-256 digests, and administrative audit chain anchors.
          Results are strictly withheld until the election reaches CLOSED or FINALIZED status.
        </p>
      </div>

      {/* Renders the verified PublicVerification component with tampering demo hidden from public */}
      <PublicVerification showTamperingDemo={false} />
    </div>
  )
}
