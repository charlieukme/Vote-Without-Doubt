import React from 'react'
import PublicVerification from '../../components/PublicVerification'
import '../public/Pages.css'

export default function AdminVerificationPage() {
  return (
    <div className="page-container admin-verification-page">
      <div className="card">
        <span className="badge badge-accent">ADMIN / AUDITOR VERIFICATION CONSOLE</span>
        <h2 className="card-title">Cryptographic Evidence & Tampering Demo</h2>
        <p>
          Inspect blockchain smart contract hashes and electoral-roll SHA-256 digests.
          Authenticated administrators may execute the controlled sandboxed tampering test below to verify that reconciliation triggers properly.
        </p>
      </div>

      {/* Renders PublicVerification with showTamperingDemo=true for authorized admins */}
      <PublicVerification showTamperingDemo={true} />
    </div>
  )
}
