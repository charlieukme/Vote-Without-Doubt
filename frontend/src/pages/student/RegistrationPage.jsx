import React, { useState, useEffect, useRef, useCallback } from 'react'
import Registration from '../../Registration'
import { useRouter } from '../../router/RouterContext'
import { useAuth } from '../../router/AuthContext'
import { api } from '../../api/client'
import {
  isCameraSupported,
  openCamera,
  captureFrame,
  waitForVideoDimensions,
  buildFramesPayload,
  cameraErrorMessage,
  CameraError,
  CAMERA_ERROR,
} from '../../faceCamera'
import '../public/Pages.css'
import '../../Auth.css'

export default function RegistrationPage() {
  const { navigate } = useRouter()
  const { studentAuth, refreshStudentAuth } = useAuth()

  // Stages: R1_R4 (USN -> Email -> OTP -> Password), R5_FACE, R6_WALLET, REVIEW_COMPLETE
  const [currentStage, setCurrentStage] = useState('R1_R4')
  const [regStatus, setRegStatus] = useState(null)
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [globalError, setGlobalError] = useState('')
  const [notice, setNotice] = useState('')

  // R5 Face Enrollment state
  const [faceConsent, setFaceConsent] = useState(false)
  const [faceStarted, setFaceStarted] = useState(false)
  const [faceChallenge, setFaceChallenge] = useState(null)
  const [faceBusy, setFaceBusy] = useState(false)
  const [faceStage, setFaceStage] = useState('idle') // 'idle' | 'opening_camera' | 'ready' | 'taking_photo' | 'requesting_challenge' | 'uploading' | 'processing' | 'success' | 'error'
  const [faceError, setFaceError] = useState('')
  const [faceSuccess, setFaceSuccess] = useState(false)

  // Camera refs
  const videoRef = useRef(null)
  const cameraRef = useRef(null)
  const cancelledRef = useRef(false)

  // R6 MetaMask Binding state
  const [walletAccount, setWalletAccount] = useState(null)
  const [walletChainId, setWalletChainId] = useState(null)
  const [walletExpectedChain, setWalletExpectedChain] = useState(null)
  const [walletChallenge, setWalletChallenge] = useState(null)
  const [walletBusy, setWalletBusy] = useState(false)
  const [walletError, setWalletError] = useState('')
  const [walletSuccess, setWalletSuccess] = useState(false)

  // Completion state
  const [finalizing, setFinalizing] = useState(false)
  const [finalStatus, setFinalStatus] = useState(null)

  // Check authoritative registration status from backend
  const checkStatus = useCallback(async () => {
    try {
      const data = await api.get('/registration/status')
      setRegStatus(data)
      if (data?.authenticated) {
        if (!data.face_enrolled) {
          setCurrentStage('R5_FACE')
          setNotice('Resuming registration: Account created. Face enrollment required.')
        } else if (!data.wallet_bound) {
          setCurrentStage('R6_WALLET')
          setNotice('Resuming registration: Face enrolled. MetaMask wallet binding required.')
        } else if (data.registration_complete) {
          setCurrentStage('REVIEW_COMPLETE')
        }
      }
    } catch {
      // Unauthenticated / clean start
    } finally {
      setLoadingStatus(false)
    }
  }, [])

  useEffect(() => {
    checkStatus()
  }, [checkStatus])

  // Camera cleanup on unmount
  useEffect(() => {
    return () => {
      cancelledRef.current = true
      if (cameraRef.current) {
        cameraRef.current.stop()
        cameraRef.current = null
      }
    }
  }, [])

  const stopCamera = useCallback(() => {
    if (cameraRef.current) {
      cameraRef.current.stop()
      cameraRef.current = null
    }
  }, [])

  // Initialize the camera AFTER React has committed the DOM with the video ref.
  // This runs when faceStarted becomes true, guaranteeing videoRef.current exists.
  useEffect(() => {
    if (!faceStarted) return

    console.log('[SimpleFace] camera effect triggered')
    const videoExists = Boolean(videoRef.current)
    console.log('[SimpleFace] video ref exists:', videoExists)

    if (!videoRef.current) {
      console.error('[SimpleFace] video ref missing on camera init — video element not mounted')
      setFaceError('Camera element not ready. Please refresh and try again.')
      setFaceStarted(false)
      setFaceBusy(false)
      setFaceStage('error')
      return
    }

    let isMounted = true
    cancelledRef.current = false
    setFaceStage('opening_camera')

    ;(async () => {
      try {
        console.log('[SimpleFace] getUserMedia starting')
        const camera = await openCamera(videoRef.current)
        if (!isMounted || cancelledRef.current) {
          camera.stop()
          return
        }
        cameraRef.current = camera
        console.log('[SimpleFace] camera opened')
        console.log('[SimpleFace] stream active:', Boolean(camera?.stream?.active))

        console.log('[SimpleFace] waiting for video dimensions...')
        const dimsReady = await waitForVideoDimensions(videoRef.current)
        if (!isMounted || cancelledRef.current) {
          stopCamera()
          return
        }

        if (!dimsReady || !videoRef.current || videoRef.current.videoWidth === 0 || videoRef.current.videoHeight === 0) {
          console.error('[SimpleFace] Video dimensions check failed')
          setFaceError('Camera connected but did not produce video frames. Please check webcam permissions and settings.')
          stopCamera()
          setFaceStarted(false)
          setFaceBusy(false)
          setFaceStage('error')
          return
        }

        console.log('[SimpleFace] video.play succeeded')
        console.log(`[SimpleFace] video dimensions: ${videoRef.current.videoWidth}x${videoRef.current.videoHeight}`)
        console.log('[SimpleFace] camera ready')
        setFaceBusy(false)
        setFaceStage('ready')
      } catch (err) {
        console.error('[SimpleFace] camera initialization error:', err?.name, err?.message, err?.code)
        stopCamera()
        if (err instanceof CameraError) {
          setFaceError(cameraErrorMessage(err.code))
        } else {
          setFaceError(err?.message || 'Camera initialization failed. Please try again.')
        }
        setFaceStarted(false)
        setFaceBusy(false)
        setFaceStage('error')
      }
    })()

    return () => {
      isMounted = false
      if (cameraRef.current) {
        cameraRef.current.stop()
        cameraRef.current = null
      }
    }
  }, [faceStarted, stopCamera])

  // Callback when R4 Password is created
  const handlePasswordCreated = async ({ username }) => {
    setGlobalError('')
    setNotice(`Credentials created for ${username}. Continuing to mandatory Face Verification.`)
    await checkStatus()
    setCurrentStage('R5_FACE')
  }

  // --- R5 Face Capture Flow ---
  const startFaceCapture = () => {
    if (!faceConsent) {
      setFaceError('Biometric privacy consent is required to proceed.')
      return
    }
    console.log('[SimpleFace] startFaceCapture called')
    setFaceError('')
    setFaceBusy(true)
    setFaceStage('opening_camera')
    setFaceStarted(true)
    cancelledRef.current = false
    console.log('[SimpleFace] faceStarted=true')
  }

  /**
   * Handle the "Capture Face" button click.
   * Granularly transitions: taking_photo -> requesting_challenge -> uploading -> processing -> success.
   */
  const handleCaptureClick = async () => {
    console.log('[SimpleFace] capture clicked')
    setFaceBusy(true)
    setFaceStage('taking_photo')
    setFaceError('')

    try {
      if (!videoRef.current) {
        throw new Error('Camera is not ready. Please try again.')
      }

      const blob = await captureFrame(videoRef.current)
      if (!blob || blob.size === 0) {
        throw new Error('Could not capture a valid photo. Please try again.')
      }
      console.log(`[SimpleFace] JPEG created: ${blob.size} bytes`)

      // Release camera hardware immediately
      stopCamera()

      // Request server challenge
      setFaceStage('requesting_challenge')
      console.log('[SimpleFace] requesting /face/challenge...')
      const issued = await api.post('/face/challenge')
      setFaceChallenge(issued)
      console.log('[SimpleFace] challenge received:', issued?.challenge_id)

      // Upload frame
      setFaceStage('uploading')
      console.log('[SimpleFace] sending /face/enroll')
      const body = buildFramesPayload([blob], issued.challenge_id, { consent: 'true' })
      
      // We are waiting for server biometric processing
      setFaceStage('processing')
      const res = await api.post('/face/enroll', body, { timeout: 35000 })
      console.log('[SimpleFace] enroll response:', res?.success || res?.enrolled ? '200' : 'SUCCESS')

      setFaceStage('success')
      setFaceSuccess(true)
      setFaceChallenge(null)
      setNotice('Face template enrolled successfully.')
      await checkStatus()
      setTimeout(() => {
        setCurrentStage('R6_WALLET')
      }, 1200)
    } catch (err) {
      console.error('[SimpleFace] capture/enroll error:', err?.name, err?.message, err?.code)
      stopCamera()
      setFaceStage('error')
      if (err instanceof CameraError) {
        setFaceError(cameraErrorMessage(err.code))
      } else if (err?.response?.status === 429) {
        setFaceError('Too many attempts. Please wait a moment and try again.')
      } else if (err?.response?.status === 401) {
        setFaceError('Authentication session expired or invalid. Please refresh the page.')
      } else {
        setFaceError(err?.message || 'Face enrollment failed. Registration remains incomplete.')
      }
      setFaceStarted(false)
    } finally {
      setFaceBusy(false)
    }
  }

  /**
   * Cancel the face capture and release the camera.
   */
  const handleCancel = () => {
    console.log('[SimpleFace] capture cancelled by user')
    cancelledRef.current = true
    stopCamera()
    setFaceStarted(false)
    setFaceBusy(false)
    setFaceStage('idle')
  }

  // --- R6 MetaMask Flow ---
  const connectMetaMask = async () => {
    setWalletError('')
    setWalletBusy(true)
    try {
      const provider = window.ethereum
      if (!provider) {
        setWalletError('MetaMask is not installed. Please install MetaMask to bind your voting wallet.')
        setWalletBusy(false)
        return
      }

      const accounts = await provider.request({ method: 'eth_requestAccounts' })
      if (!Array.isArray(accounts) || accounts.length === 0) {
        setWalletError('No Ethereum account selected in MetaMask.')
        setWalletBusy(false)
        return
      }

      const chainHex = await provider.request({ method: 'eth_chainId' })
      const chain = parseInt(chainHex, 16)
      setWalletAccount(accounts[0])
      setWalletChainId(chain)

      // Request server challenge
      const chal = await api.post('/wallet/challenge')
      setWalletChallenge(chal)
      setWalletExpectedChain(chal.expected_chain_id ?? 1337)

      // Sign with MetaMask personal_sign (Candidate choice is NOT included)
      const sig = await provider.request({
        method: 'personal_sign',
        params: [chal.message, accounts[0]],
      })

      // Submit binding
      await api.post('/wallet/bind', {
        nonce: chal.nonce,
        signature: sig,
        wallet_address: accounts[0],
        chain_id: chain,
      })

      setWalletSuccess(true)
      setNotice('MetaMask wallet cryptographically bound successfully.')
      await checkStatus()
      setTimeout(() => {
        finalizeAndComplete()
      }, 1000)
    } catch (err) {
      if (err?.code === 4001) {
        setWalletError('MetaMask connection or signature request was rejected by user.')
      } else {
        setWalletError(err?.message || 'MetaMask wallet binding failed. Registration remains incomplete.')
      }
    } finally {
      setWalletBusy(false)
    }
  }

  // --- Finalize & Authoritative Completion ---
  const finalizeAndComplete = async () => {
    setFinalizing(true)
    setGlobalError('')
    try {
      const res = await api.post('/registration/finalize')
      setFinalStatus(res)
      setCurrentStage('REVIEW_COMPLETE')
    } catch (err) {
      setGlobalError(err.message || 'Registration could not be finalized. Please ensure all factors are completed.')
    } finally {
      setFinalizing(false)
    }
  }

  return (
    <div className="page-container registration-page" style={{ maxWidth: '680px', margin: '0 auto' }}>
      {/* Neo-brutalist Stepper Header */}
      <div className="card" style={{ marginBottom: '1.5rem', background: '#FFFDF5', border: '4px solid #000' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <span className="badge badge-accent">AUTHORITATIVE REGISTRATION</span>
          <span style={{ fontSize: '0.8rem', fontWeight: 800 }}>MANDATORY MULTI-FACTOR ENROLMENT</span>
        </div>

        <div className="reg-stepper" aria-label="Registration Steps">
          <div className={`reg-step-pill ${currentStage === 'R1_R4' ? 'active' : 'completed'}`}>
            R1-R4 IDENTITY
          </div>
          <div className={`reg-step-pill ${currentStage === 'R5_FACE' ? 'active' : currentStage === 'R6_WALLET' || currentStage === 'REVIEW_COMPLETE' ? 'completed' : ''}`}>
            R5 FACE ENROLMENT
          </div>
          <div className={`reg-step-pill ${currentStage === 'R6_WALLET' ? 'active' : currentStage === 'REVIEW_COMPLETE' ? 'completed' : ''}`}>
            R6 METAMASK BINDING
          </div>
          <div className={`reg-step-pill ${currentStage === 'REVIEW_COMPLETE' ? 'active' : ''}`}>
            REVIEW & COMPLETE
          </div>
        </div>

        {notice && (
          <div className="auth-status" role="status" style={{ marginBottom: '0.5rem' }}>
            {notice}
          </div>
        )}
        {globalError && (
          <div className="error" role="alert" style={{ marginBottom: '0.5rem' }}>
            {globalError}
          </div>
        )}
      </div>

      {/* STAGE 1: Identity, Email, OTP & Password */}
      {currentStage === 'R1_R4' && (
        <div className="card" style={{ border: '4px solid #000' }}>
          <span className="badge badge-accent">STEP 1: STUDENT ID & ACCOUNT</span>
          <h2 className="card-title" style={{ marginTop: '0.5rem' }}>Student Identification & Account Setup</h2>
          <p style={{ fontSize: '0.9rem', color: '#374151' }}>
            Enter your college USN to verify your voter eligibility.
            You will then confirm your email with a 6-digit verification code, followed by creating your password.
          </p>

          <Registration onPasswordCreated={handlePasswordCreated} />

          <div style={{ marginTop: '1.5rem', borderTop: '2px solid #000', paddingTop: '1rem', textAlign: 'center' }}>
            <p style={{ fontSize: '0.875rem' }}>
              Already created your credentials?{' '}
              <button className="link-button" onClick={() => navigate('/login')} style={{ fontWeight: 800 }}>
                Sign in to complete verification &rarr;
              </button>
            </p>
          </div>
        </div>
      )}

      {/* STAGE 2: Biometric Face Consent & Capture */}
      {currentStage === 'R5_FACE' && (
        <div className="card" style={{ border: '4px solid #000' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="badge" style={{ background: 'var(--neo-violet, #C4B5FD)', color: '#000' }}>
              STEP 2: FACE VERIFICATION
            </span>
          </div>
          <h2 className="card-title" style={{ marginTop: '0.5rem' }}>Face Verification</h2>

          {/* Video element is permanently mounted outside all conditionals so videoRef.current is always available.
              Controlled via CSS display property. */}
          <div
            style={{
              display: faceStarted ? 'block' : 'none',
              textAlign: 'center',
              marginBottom: '1rem',
            }}
          >
            <div style={{ position: 'relative', display: 'inline-block', border: '4px solid #000', background: '#000', overflow: 'hidden' }}>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                style={{
                  width: '100%',
                  maxWidth: '420px',
                  height: '300px',
                  objectFit: 'cover',
                  background: '#000',
                  display: 'block',
                }}
              />
              {faceBusy && (
                <div style={{
                  position: 'absolute',
                  bottom: 0,
                  left: 0,
                  right: 0,
                  background: 'rgba(0,0,0,0.82)',
                  color: '#FFF',
                  padding: '0.6rem',
                  fontWeight: 800,
                  fontSize: '0.85rem',
                  textAlign: 'center',
                  letterSpacing: '0.5px'
                }}>
                  {faceStage === 'opening_camera' && 'Opening camera...'}
                  {faceStage === 'taking_photo' && 'Capturing photo...'}
                  {faceStage === 'requesting_challenge' && 'Requesting enrollment challenge...'}
                  {faceStage === 'uploading' && 'Uploading frame...'}
                  {faceStage === 'processing' && 'Processing biometric template (please wait)...'}
                  {faceStage === 'success' && '✓ Enrollment complete!'}
                  {(!faceStage || faceStage === 'idle') && 'Processing...'}
                </div>
              )}
            </div>
          </div>

          {!faceStarted ? (
            <div>
              <div style={{ padding: '1rem', background: '#FEF3C7', border: '3px solid #000', marginBottom: '1.25rem' }}>
                <h4 style={{ margin: '0 0 0.5rem 0', fontWeight: 900 }}>Step 1: Biometric Privacy & Consent</h4>
                <p style={{ fontSize: '0.875rem', lineHeight: 1.5, margin: '0 0 0.75rem 0' }}>
                  This is a simplified single-frame face-capture prototype.
                  You will be asked to capture one face image from your webcam.
                  Your biometric face template is encrypted and stored on the identity plane,
                  never published to the blockchain or tied to your ballot.
                  This guided capture is NOT a robust liveness check — it does not protect
                  against photos, screens, masks, or deepfakes.
                </p>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, cursor: 'pointer', fontSize: '0.9rem' }}>
                  <input
                    type="checkbox"
                    checked={faceConsent}
                    onChange={(e) => setFaceConsent(e.target.checked)}
                    style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                  />
                  I understand and consent to face verification for voter identity enrollment.
                </label>
              </div>

              <div style={{ marginBottom: '1.5rem' }}>
                <h4 style={{ margin: '0 0 0.35rem 0', fontWeight: 900 }}>Camera Permission Guidance:</h4>
                <p style={{ fontSize: '0.875rem', color: '#4B5563', margin: 0 }}>
                  When prompted by your browser, grant camera access. You will capture one face image to enroll.
                </p>
              </div>

              {faceError && <div className="error" role="alert" style={{ marginBottom: '1rem' }}>{faceError}</div>}

              <button
                className="btn btn-primary"
                onClick={startFaceCapture}
                disabled={!faceConsent || faceBusy}
                style={{ width: '100%', padding: '0.75rem' }}
              >
                {faceBusy ? 'Opening Camera...' : 'Continue to Camera & Capture'}
              </button>
            </div>
          ) : (
            <div>
              {/* Capture UI shown only when camera is active */}
              <div style={{ textAlign: 'center', marginBottom: '1rem' }}>
                <p style={{ fontWeight: 800, fontSize: '0.95rem', margin: '0 0 0.5rem 0', color: '#fff', background: '#000', padding: '0.5rem 1rem', border: '3px solid #000', display: 'inline-block' }}>
                  Position your face inside the camera
                </p>
                <p style={{ fontSize: '0.9rem', margin: '0.25rem 0 0.5rem 0', color: '#4B5563' }}>
                  When ready, click "Capture Face" to take a single photo.
                </p>
              </div>

              {faceError && (
                <div className="error" role="alert" style={{ marginBottom: '1rem', textAlign: 'center' }}>
                  {faceError}
                </div>
              )}

              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center', marginTop: '1rem' }}>
                <button
                  className="btn btn-primary"
                  onClick={handleCaptureClick}
                  disabled={faceBusy}
                  style={{ flex: 1 }}
                >
                  {faceBusy
                    ? (faceStage === 'taking_photo'
                        ? 'Capturing Photo...'
                        : faceStage === 'uploading'
                        ? 'Uploading Image...'
                        : faceStage === 'processing'
                        ? 'Enrolling Biometrics...'
                        : 'Processing...')
                    : 'Capture Face'}
                </button>
                <button
                  className="btn"
                  onClick={handleCancel}
                  disabled={faceBusy}
                  style={{ flex: 0 }}
                >
                  Cancel
                </button>
              </div>

              {faceSuccess && (
                <div className="auth-status" role="status" style={{ marginBottom: '1rem', background: '#A7F3D0' }}>
                  ✓ Face enrollment completed! Advancing to wallet binding...
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* STAGE 3: MetaMask Wallet Connection */}
      {currentStage === 'R6_WALLET' && (
        <div className="card" style={{ border: '4px solid #000' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="badge" style={{ background: 'var(--neo-yellow, #FFD93D)', color: '#000' }}>
              STEP 3: CONNECT METAMASK WALLET
            </span>
          </div>
          <h2 className="card-title" style={{ marginTop: '0.5rem' }}>Connect Wallet</h2>

          <div style={{ padding: '1rem', background: '#FFFDF5', border: '3px solid #000', marginBottom: '1.25rem' }}>
            <p style={{ fontSize: '0.925rem', lineHeight: 1.5, margin: '0 0 0.5rem 0', fontWeight: 700 }}>
              Connect your MetaMask wallet to link your voter key. Your candidate choices are never signed or visible in MetaMask.
            </p>
            <p style={{ fontSize: '0.85rem', color: '#4B5563', margin: 0 }}>
              Click below to connect MetaMask and sign a verification challenge to confirm your wallet.
            </p>
          </div>

          {walletError && (
            <div className="error" role="alert" style={{ marginBottom: '1rem' }}>
              {walletError}
            </div>
          )}

          {walletSuccess && (
            <div className="auth-status" role="status" style={{ marginBottom: '1rem', background: '#A7F3D0' }}>
              ✓ Wallet bound: {walletAccount ? walletAccount.slice(0, 10) + '...' : ''}. Finalizing registration...
            </div>
          )}

          <button
            className="btn btn-primary"
            onClick={connectMetaMask}
            disabled={walletBusy || walletSuccess}
            style={{ width: '100%', padding: '0.75rem', fontSize: '1rem', fontWeight: 900 }}
          >
            {walletBusy ? 'Connecting MetaMask...' : 'CONNECT METAMASK'}
          </button>
        </div>
      )}

      {/* STAGE 4: Authoritative Review & Completion */}
      {currentStage === 'REVIEW_COMPLETE' && (
        <div className="card" style={{ border: '4px solid #000', background: '#FFF' }}>
          <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
            <span className="badge" style={{ background: '#10B981', color: '#FFF', fontSize: '0.9rem', padding: '0.4rem 1rem' }}>
              ✓ REGISTRATION COMPLETE
            </span>
            <h2 className="card-title" style={{ marginTop: '0.75rem' }}>Student Voter Verified</h2>
            <p style={{ fontSize: '0.95rem', color: '#374151', margin: '0.25rem 0 0 0' }}>
              All 5 server-side requirements have been validated and recorded.
            </p>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', marginBottom: '1.5rem', background: '#F9FAFB', padding: '1rem', border: '3px solid #000' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, color: '#047857' }}>
              <span>✓</span> USN eligibility verified on electoral roll
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, color: '#047857' }}>
              <span>✓</span> Email verified via single-use OTP
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, color: '#047857' }}>
              <span>✓</span> Password secured with Argon2id cryptographic hashing
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, color: '#047857' }}>
              <span>✓</span> Biometric face enrollment cryptographically secured
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800, color: '#047857' }}>
              <span>✓</span> Wallet bound ({regStatus?.wallet_address ? regStatus.wallet_address.slice(0, 10) + '...' : 'Verified'})
            </div>
          </div>

          <button
            className="btn btn-action"
            onClick={async () => {
              await refreshStudentAuth()
              navigate('/dashboard')
            }}
            style={{ width: '100%', padding: '0.85rem', fontSize: '1.05rem', fontWeight: 900 }}
          >
            PROCEED TO VOTER DASHBOARD &rarr;
          </button>
        </div>
      )}
    </div>
  )
}
