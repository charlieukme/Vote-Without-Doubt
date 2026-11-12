import React from 'react'
import { useRouter } from '../../router/RouterContext'
import './Pages.css'

export function NotFoundPage() {
  const { navigate } = useRouter()
  return (
    <div className="page-container">
      <div className="card text-center" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
        <span className="badge badge-accent">ERROR 404</span>
        <h2 style={{ fontSize: '2.5rem', fontWeight: 900, margin: '1rem 0' }}>Page Not Found</h2>
        <p style={{ maxWidth: '500px', margin: '0 auto 1.5rem auto' }}>
          The requested route does not exist or has been relocated within the e-voting platform.
        </p>
        <button className="btn btn-primary" onClick={() => navigate('/')}>
          Return to Home Page
        </button>
      </div>
    </div>
  )
}

export function AccessDeniedPage() {
  const { navigate } = useRouter()
  return (
    <div className="page-container">
      <div className="card text-center" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
        <span className="badge" style={{ background: '#FF6B6B' }}>ERROR 403</span>
        <h2 style={{ fontSize: '2.5rem', fontWeight: 900, margin: '1rem 0' }}>Access Denied</h2>
        <p style={{ maxWidth: '500px', margin: '0 auto 1.5rem auto' }}>
          You do not have the required permissions to access this administrative or voter resource.
        </p>
        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
          <button className="btn btn-primary" onClick={() => navigate('/login')}>
            Student Login
          </button>
          <button className="btn btn-secondary" onClick={() => navigate('/admin/login')}>
            Admin Login
          </button>
        </div>
      </div>
    </div>
  )
}

export function MaintenancePage() {
  const { navigate } = useRouter()
  return (
    <div className="page-container">
      <div className="card text-center" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
        <span className="badge badge-accent">SYSTEM NOTICE</span>
        <h2 style={{ fontSize: '2.5rem', fontWeight: 900, margin: '1rem 0' }}>System Maintenance</h2>
        <p style={{ maxWidth: '500px', margin: '0 auto 1.5rem auto' }}>
          The election system is temporarily undergoing routine ledger synchronization or backup procedures.
          Please check back in a few minutes.
        </p>
        <button className="btn btn-secondary" onClick={() => navigate('/')}>
          Check System Status
        </button>
      </div>
    </div>
  )
}
