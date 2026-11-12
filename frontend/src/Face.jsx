import { useCallback, useEffect, useRef, useState } from 'react'
import './Face.css'
import { api } from './api/client.js'
import {
  CAMERA_ERROR,
  CameraError,
  buildFramesPayload,
  cameraErrorMessage,
  isCameraSupported,
  openCamera,
  captureFrame,
  waitForVideoDimensions,
} from './faceCamera.js'

/**
 * Face verification for voting (Phase 16).
 *
 * Single-frame biometric verification lifecycle:
 *   1. User clicks "Open Camera" -> live preview stream acquired.
 *   2. Viewfinder guide displays positioning circle and instructions.
 *   3. User positions face and clicks "Verify Face".
 *   4. Single frame captured -> challenge requested -> frame verified against enrolled template.
 *   5. On success, releases camera and advances factor status.
 *   6. On failure, keeps camera open with specific feedback so user can adjust and retry immediately.
 */
function Face({ onVerified, authorizationId, electionId } = {}) {
  const [status, setStatus] = useState({ enrolled: false, consent_given: false })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [cameraActive, setCameraActive] = useState(false)
  const [stage, setStage] = useState('idle') // idle, opening_camera, camera_ready, capturing, requesting_challenge, verifying, success, error

  const videoRef = useRef(null)
  const cameraRef = useRef(null)
  const cancelledRef = useRef(false)

  const cameraSupported = isCameraSupported()

  const getStatus = useCallback(async () => {
    try {
      setStatus(await api.get('/face/status'))
    } catch {
      setError('Could not load your face enrolment status.')
    }
  }, [])

  useEffect(() => {
    getStatus()
  }, [getStatus])

  // Clear stale verification notices/errors when election or authorization context changes
  useEffect(() => {
    setNotice('')
    setError('')
    setStage((prev) => (prev === 'success' || prev === 'error' ? 'idle' : prev))
  }, [electionId, authorizationId])

  /** Release the camera on unmount so it is never left running. */
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
  useEffect(() => {
    if (!cameraActive) return

    console.log('[SimpleFace] camera effect triggered')
    if (!videoRef.current) {
      console.error('[SimpleFace] video ref missing on camera init')
      setError('Unable to access camera: Camera element not ready. Please refresh and try again.')
      setCameraActive(false)
      setBusy(false)
      setStage('error')
      return
    }

    let isMounted = true
    cancelledRef.current = false

    ;(async () => {
      try {
        console.log('[SimpleFace] getUserMedia starting')
        const camera = await openCamera(videoRef.current)
        if (!isMounted || cancelledRef.current) {
          camera.stop()
          return
        }
        cameraRef.current = camera
        console.log('[SimpleFace] camera opened, active:', Boolean(camera?.stream?.active))

        console.log('[SimpleFace] waiting for video dimensions...')
        const dimsReady = await waitForVideoDimensions(videoRef.current)
        if (!isMounted || cancelledRef.current) {
          stopCamera()
          return
        }

        if (!dimsReady || !videoRef.current || videoRef.current.videoWidth === 0 || videoRef.current.videoHeight === 0) {
          console.error('[SimpleFace] Video dimensions check failed')
          setError('Unable to access camera: Camera did not produce a usable video frame. Please check your camera connection.')
          stopCamera()
          setCameraActive(false)
          setBusy(false)
          setStage('error')
          return
        }

        console.log(`[SimpleFace] camera ready (${videoRef.current.videoWidth}x${videoRef.current.videoHeight})`)
        setStage('camera_ready')
        setBusy(false)
      } catch (err) {
        console.error('[SimpleFace] camera initialization error:', err?.name, err?.message, err?.code)
        stopCamera()
        setCameraActive(false)
        setStage('error')
        if (err instanceof CameraError) {
          setError('Unable to access camera: ' + cameraErrorMessage(err.code))
        } else {
          setError('Unable to access camera: ' + (err?.message || 'Could not access the camera device.'))
        }
        setBusy(false)
      }
    })()

    return () => {
      isMounted = false
      if (cameraRef.current) {
        cameraRef.current.stop()
        cameraRef.current = null
      }
    }
  }, [cameraActive, stopCamera])

  /**
   * Handle the "Verify Face" button click.
   * Captures one frame, requests challenge, sends to /face/verify.
   * Keeps camera active during and after verification to avoid jarring UI teardown.
   */
  const handleVerifyClick = async () => {
    console.log('[SimpleFace] capture clicked')
    setBusy(true)
    setError('')
    setNotice('')
    setStage('capturing')

    try {
      if (!videoRef.current) {
        throw new Error('Camera is not ready. Please try again.')
      }

      const blob = await captureFrame(videoRef.current)
      if (!blob || blob.size === 0) {
        throw new Error('Could not capture a frame. Please check camera preview and try again.')
      }

      console.log(`[SimpleFace] JPEG created: ${blob.size} bytes`)

      // Keep preview running, request challenge
      setStage('requesting_challenge')
      console.log('[SimpleFace] requesting /face/challenge...')
      let issued
      if (authorizationId) {
        issued = await api.post('/face/challenge', {
          authorization_id: authorizationId,
          election_id: electionId || undefined,
        })
      } else {
        issued = await api.post('/face/challenge')
      }

      // Send verification
      setStage('verifying')
      console.log('[SimpleFace] sending /face/verify')
      const body = buildFramesPayload([blob], issued.challenge_id)
      const result = await api.post('/face/verify', body, { timeout: 30000 })

      console.log('[SimpleFace] verify response: SUCCESS')
      stopCamera()
      setCameraActive(false)
      setStage('success')
      setNotice(result?.verified ? 'Face verified successfully. You may now vote.' : 'Face verification completed.')
      await getStatus()
      if (result?.verified && typeof onVerified === 'function') {
        onVerified()
      }
    } catch (failure) {
      console.error('[SimpleFace] verify failed:', failure?.name, failure?.message, failure?.code)
      setNotice('')
      setStage('error')

      if (failure instanceof CameraError) {
        stopCamera()
        setCameraActive(false)
        setError('Unable to access camera: ' + cameraErrorMessage(failure.code))
      } else if (failure?.code === CAMERA_ERROR.ABORTED) {
        setError('Face verification was cancelled.')
      } else if (failure?.status === 429 || failure?.isRateLimited || failure?.response?.status === 429) {
        setError('Verification rate limit reached. Please wait a moment before trying again.')
      } else {
        // Biometric mismatch or quality rejection:
        // KEEP CAMERA OPEN so student can re-position face directly without reopening camera!
        const serverError = failure?.payload?.message || failure?.payload?.error || failure?.response?.data?.error || failure?.message || ''
        if (serverError === 'Face verification failed.') {
          setError('Biometric verification failed: The captured frame did not match your enrolled face template. Please ensure bright direct lighting, face the camera straight-on with a neutral expression, and try again.')
        } else if (serverError.toLowerCase().includes('no face')) {
          setError('No face detected: Please position your face clearly in the center of the camera frame.')
        } else if (serverError) {
          setError(serverError)
        } else {
          setError('Biometric face verification failed. Please check your lighting, face the camera directly, and try again.')
        }
      }
    } finally {
      setBusy(false)
    }
  }

  /**
   * Start face verification: open camera preview.
   */
  const startFaceVerification = () => {
    console.log('[SimpleFace] startFaceVerification called')
    setError('')
    setNotice('')
    setBusy(true)
    setStage('opening_camera')
    setCameraActive(true)
    cancelledRef.current = false
  }

  /**
   * Cancel verification and release camera hardware.
   */
  const handleCancel = () => {
    cancelledRef.current = true
    stopCamera()
    cameraRef.current = null
    setCameraActive(false)
    setBusy(false)
    setStage('idle')
  }

  /**
   * Withdraw biometric consent and permanently delete server-side template.
   */
  const handleWithdrawConsent = async () => {
    stopCamera()
    setCameraActive(false)
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await api.post('/face/withdraw-consent')
      await getStatus()
      setStage('idle')
      setNotice('Biometric consent withdrawn and template deleted.')
    } catch (failure) {
      if (failure?.status === 429 || failure?.isRateLimited || failure?.response?.status === 429) {
        setError('Too many requests. Please wait a moment before trying again.')
      } else {
        setError(failure?.payload?.message || failure?.payload?.error || failure?.message || 'Unable to withdraw consent right now.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="face-container">
      <h2>Biometric Face Verification</h2>

      <div className="status-box">
        <div>Enrolled: {status.enrolled ? 'Yes' : 'No'}</div>
        <div>Consent: {status.consent_given ? 'Yes' : 'No'}</div>
        {status.withdrawn_at && <div>Withdrawn: {status.withdrawn_at}</div>}
      </div>

      {!cameraSupported && (
        <div className="error" role="alert">
          {cameraErrorMessage(CAMERA_ERROR.UNSUPPORTED)}
        </div>
      )}

      {cameraSupported && status.enrolled && !cameraActive && (
        <div>
          <button
            className="btn btn-primary"
            onClick={startFaceVerification}
            disabled={busy}
          >
            {busy ? 'Opening Camera...' : 'Open Camera'}
          </button>
        </div>
      )}

      {cameraSupported && !status.enrolled && (
        <div className="notice" role="status">
          You are not enrolled yet. Please complete face enrollment first.
        </div>
      )}

      {status.enrolled && !cameraActive && (
        <button
          onClick={handleWithdrawConsent}
          disabled={busy}
        >
          Withdraw Consent and Delete Template
        </button>
      )}

      {/* Camera preview container */}
      <div
        className="face-preview-wrapper"
        style={{
          display: cameraActive ? 'flex' : 'none',
          flexDirection: 'column',
          alignItems: 'center',
          margin: '1.25rem 0',
        }}
      >
        <div style={{ position: 'relative', width: '100%', maxWidth: '440px' }}>
          <video
            ref={videoRef}
            className="face-preview"
            autoPlay
            playsInline
            muted
            loop
            aria-label="Camera preview"
            style={{
              width: '100%',
              maxWidth: '440px',
              height: '320px',
              objectFit: 'cover',
              background: '#000',
              border: '4px solid #000',
              display: 'block',
            }}
          />

          {/* Biometric viewfinder overlay frame */}
          <div
            style={{
              position: 'absolute',
              top: '15%',
              left: '20%',
              width: '60%',
              height: '70%',
              border: busy && (stage === 'verifying' || stage === 'capturing')
                ? '3px solid #10B981'
                : '3px dashed #FFD93D',
              borderRadius: '50%',
              pointerEvents: 'none',
              boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.35)',
              transition: 'border-color 0.3s ease',
            }}
          />

          {/* Loading / Verification Overlay */}
          {busy && (stage === 'verifying' || stage === 'requesting_challenge' || stage === 'capturing') && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: 'rgba(0, 0, 0, 0.75)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                padding: '1rem',
                textAlign: 'center',
                zIndex: 2,
              }}
            >
              <div
                style={{
                  width: '36px',
                  height: '36px',
                  border: '4px solid #f3f3f3',
                  borderTop: '4px solid #FFD93D',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  marginBottom: '1rem',
                }}
              />
              <div style={{ fontWeight: 800, fontSize: '1rem', marginBottom: '0.25rem' }}>
                {stage === 'capturing' && 'Capturing facial frame...'}
                {stage === 'requesting_challenge' && 'Requesting security challenge...'}
                {stage === 'verifying' && 'Comparing biometric embedding with template...'}
              </div>
              <div style={{ fontSize: '0.85rem', color: '#D1D5DB' }}>
                Please remain steady in front of the camera
              </div>
            </div>
          )}
        </div>

        {/* Live instructions banner */}
        <div style={{ textAlign: 'center', marginTop: '1rem', marginBottom: '0.5rem', width: '100%', maxWidth: '440px' }}>
          <p
            style={{
              fontWeight: 800,
              fontSize: '0.95rem',
              margin: '0 0 0.5rem 0',
              color: '#fff',
              background: '#000',
              padding: '0.5rem 1rem',
              border: '3px solid #000',
              display: 'inline-block',
            }}
          >
            Position your face inside the circle
          </p>
          <p style={{ fontSize: '0.88rem', margin: '0.25rem 0', color: '#4B5563' }}>
            Ensure bright, even front lighting. When ready, click "Verify Face".
          </p>
        </div>

        {error && (
          <div
            className="error"
            role="alert"
            style={{ marginBottom: '1rem', maxWidth: '440px', textAlign: 'center' }}
          >
            {error}
          </div>
        )}

        {/* Action buttons while camera is active */}
        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center', width: '100%', maxWidth: '440px' }}>
          <button
            className="btn btn-primary"
            onClick={handleVerifyClick}
            disabled={busy}
            style={{ flex: 1 }}
          >
            {busy ? (stage === 'capturing' ? 'Capturing...' : 'Verifying...') : (error ? 'Retry Verification' : 'Verify Face')}
          </button>
          <button
            className="btn"
            onClick={handleCancel}
            disabled={busy}
            style={{ flex: 0 }}
          >
            Close Camera
          </button>
        </div>
      </div>

      {notice && (
        <div className="notice" role="status" style={{ marginTop: '1rem' }}>
          {notice}
        </div>
      )}

      {error && !cameraActive && (
        <div className="error" role="alert" style={{ marginTop: '1rem' }}>
          {error}
          <button
            className="retry-button"
            onClick={() => {
              setError('')
              if (status.enrolled) startFaceVerification()
            }}
            disabled={busy}
            style={{ display: 'block', marginTop: '0.5rem' }}
          >
            Try Again
          </button>
        </div>
      )}
    </div>
  )
}

export default Face
