import React, { useEffect } from 'react'
import Auth from '../../Auth'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import '../public/Pages.css'

export default function LoginPage() {
  const { navigate } = useRouter()
  const { studentAuth, refreshStudentAuth } = useAuth()

  useEffect(() => {
    if (studentAuth?.authenticated) {
      navigate('/dashboard')
    }
  }, [studentAuth, navigate])

  const handleSuccess = async () => {
    await refreshStudentAuth()
    navigate('/dashboard')
  }

  return (
    <div className="page-container login-page" style={{ maxWidth: '600px', margin: '0 auto' }}>
      <div className="card">
        <span className="badge badge-accent">STUDENT PORTAL</span>
        <h2 className="card-title">Sign In to Vote Without Doubt</h2>
        <div style={{ margin: '0.5rem 0 1.25rem 0', color: '#4B5563', fontWeight: 600, fontSize: '0.95rem', lineHeight: 1.5 }}>
          Sign in using your two-step student verification:
          <div style={{ marginTop: '0.4rem', paddingLeft: '0.5rem' }}>
            <div><strong>Step 1:</strong> Enter your Student ID (USN) and password</div>
            <div><strong>Step 2:</strong> Enter the 6-digit verification code sent to your college email</div>
          </div>
        </div>

        {/* Existing verified Auth component */}
        <Auth onSuccess={handleSuccess} />

        <div style={{ marginTop: '1.5rem', borderTop: '2px solid #000', paddingTop: '1rem', textAlign: 'center' }}>
          <p style={{ fontSize: '0.875rem', fontWeight: 600 }}>
            New student voter?{' '}
            <button className="link-button" onClick={() => navigate('/register')} style={{ fontWeight: 800 }}>
              Register using your college USN &rarr;
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
