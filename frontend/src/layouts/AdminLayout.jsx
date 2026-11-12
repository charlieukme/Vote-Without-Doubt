import React, { useEffect } from 'react'
import { useRouter } from '../router/RouterContext'
import { useAuth } from '../router/AuthContext'
import './AdminLayout.css'

export default function AdminLayout({ children }) {
  const { path, navigate } = useRouter()
  const { adminAuth, adminToken, adminLogout } = useAuth()

  useEffect(() => {
    // If not authenticated as admin, redirect to admin login
    if (!adminToken) {
      navigate('/admin/login')
    }
  }, [adminToken, navigate])

  const handleLogout = async () => {
    await adminLogout()
    navigate('/admin/login')
  }

  const role = adminAuth?.role || 'OFFICER'
  const isAuditor = role === 'AUDITOR'
  const officerTitle = adminAuth?.admin_id === 'OFFICER_01'
    ? 'Chief Election Officer'
    : adminAuth?.admin_id === 'OFFICER_02'
    ? 'Deputy Election Officer'
    : (adminAuth?.name || adminAuth?.admin_id || 'Admin')

  return (
    <div className="layout-container admin-layout">
      {/* Top Admin Banner */}
      <div className="admin-top-banner">
        <div className="banner-inner">
          <div className="admin-status-left">
            <span className={`badge-role ${isAuditor ? 'role-auditor' : 'role-officer'}`}>
              ROLE: {role}
            </span>
            <span className="admin-id-text">
              Logged in: <strong>{officerTitle}</strong>
              {adminAuth?.admin_id && <span style={{ opacity: 0.75, marginLeft: '0.35rem' }}>({adminAuth.admin_id})</span>}
            </span>
          </div>
          <div className="admin-status-right">
            <span>Governance: {isAuditor ? 'Read-Only / Cryptographic Integrity' : 'Operational Officer / Two-Officer Authorized (Chief & Deputy)'}</span>
          </div>
        </div>
      </div>

      {/* Admin Header */}
      <header className="admin-header" role="banner">
        <div className="header-brand" onClick={() => navigate('/admin/dashboard')}>
          <span className="brand-badge brand-admin">GOVERNANCE CONSOLE</span>
          <h1 className="brand-title">E-Voting Admin</h1>
        </div>

        <nav className="admin-nav" aria-label="Admin Navigation">
          <button className={`nav-link ${path === '/admin/dashboard' ? 'active' : ''}`} onClick={() => navigate('/admin/dashboard')}>
            Dashboard
          </button>
          <button className={`nav-link ${path === '/admin/elections' ? 'active' : ''}`} onClick={() => navigate('/admin/elections')}>
            Elections
          </button>
          <button className={`nav-link ${path === '/admin/approvals' ? 'active' : ''}`} onClick={() => navigate('/admin/approvals')}>
            Approvals
          </button>
          <button className={`nav-link ${path.startsWith('/admin/candidates') ? 'active' : ''}`} onClick={() => navigate('/admin/candidates')}>
            Candidates
          </button>
          <button className={`nav-link ${path === '/admin/voters' ? 'active' : ''}`} onClick={() => navigate('/admin/voters')}>
            Electoral Roll
          </button>
          <button className={`nav-link ${path === '/admin/audit' ? 'active' : ''}`} onClick={() => navigate('/admin/audit')}>
            Audit Logs
          </button>
          <button className={`nav-link ${path === '/admin/results' ? 'active' : ''}`} onClick={() => navigate('/admin/results')}>
            Results
          </button>
          <button className={`nav-link ${path === '/admin/verification' ? 'active' : ''}`} onClick={() => navigate('/admin/verification')}>
            Verification
          </button>
          <button className={`nav-link ${path === '/admin/health' ? 'active' : ''}`} onClick={() => navigate('/admin/health')}>
            Health
          </button>
        </nav>

        <div className="admin-actions">
          <button className="btn btn-logout" onClick={handleLogout}>
            Exit Console
          </button>
        </div>
      </header>

      {/* Main Admin Workspace */}
      <main className="admin-main-content" id="admin-main" role="main">
        {children}
      </main>

      {/* Footer */}
      <footer className="admin-footer" role="contentinfo">
        <div className="admin-footer-inner">
          <p>Two-Officer / Four-Eyes Principle Enforced (Chief Election Officer & Deputy Election Officer). Administrative actions are logged to SHA-256 hash-chain.</p>
          <button className="link-button" onClick={() => navigate('/')}>Return to Public Site &rarr;</button>
        </div>
      </footer>
    </div>
  )
}
