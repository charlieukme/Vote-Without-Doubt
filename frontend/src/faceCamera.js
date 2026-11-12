import { IS_DEV } from './config/env.js'

/**
 * Nuclear-simple camera helpers for single-frame face capture.
 *
 * Flow:
 *   1. getUserMedia({ video: true, audio: false })
 *   2. assign stream to <video>
 *   3. video.muted = true, video.playsInline = true
 *   4. await video.play()
 *   5. wait until video.videoWidth > 0 && video.videoHeight > 0
 *   6. on click: drawImage → toBlob → POST
 *
 * IMPORTANT: This is a simplified single-frame face-capture prototype.
 * It does NOT perform liveness detection. Biometric decisions live on the backend.
 */

/** Reasons a camera session can fail. */
export const CAMERA_ERROR = Object.freeze({
  UNSUPPORTED: 'CAMERA_UNSUPPORTED',
  PERMISSION_DENIED: 'CAMERA_PERMISSION_DENIED',
  NOT_FOUND: 'CAMERA_NOT_FOUND',
  NOT_READABLE: 'CAMERA_NOT_READABLE',
  OVERCONSTRAINED: 'CAMERA_OVERCONSTRAINED',
  TIMEOUT: 'CAMERA_TIMEOUT',
  CAPTURE_FAILED: 'CAPTURE_FAILED',
  ABORTED: 'CAPTURE_ABORTED',
})

/** Ideal camera constraints. */
export const DEFAULT_VIDEO_CONSTRAINTS = {
  audio: false,
  video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
}

/** Capture dimensions. */
export const CAPTURE_WIDTH = 640
export const CAPTURE_HEIGHT = 480

/** Default JPEG quality. */
export const DEFAULT_JPEG_QUALITY = 0.82

/** Whether this environment can attempt a camera capture. */
export function isCameraSupported(scope = globalThis) {
  const devices = scope && scope.navigator && scope.navigator.mediaDevices
  return Boolean(devices && typeof devices.getUserMedia === 'function')
}

const MESSAGES = {
  [CAMERA_ERROR.UNSUPPORTED]:
    'This browser cannot open a camera here. A secure (https) context is required.',
  [CAMERA_ERROR.PERMISSION_DENIED]:
    'Camera permission was refused. Allow camera access and try again.',
  [CAMERA_ERROR.NOT_FOUND]:
    'No camera was found on this device.',
  [CAMERA_ERROR.NOT_READABLE]:
    'The camera is already in use by another application.',
  [CAMERA_ERROR.OVERCONSTRAINED]:
    'No camera matched the requested settings. Try a different camera.',
  [CAMERA_ERROR.TIMEOUT]:
    'The camera did not start in time. Check that nothing else is holding it.',
  [CAMERA_ERROR.CAPTURE_FAILED]:
    'Could not read frames from the camera.',
  [CAMERA_ERROR.ABORTED]: 'Capture was cancelled.',
}

export function cameraErrorMessage(code) {
  return MESSAGES[code] || MESSAGES[CAMERA_ERROR.CAPTURE_FAILED]
}

export function classifyCameraError(error) {
  if (!error) return CAMERA_ERROR.CAPTURE_FAILED
  if (error.name === 'NotAllowedError' || error.name === 'SecurityError' || error.name === 'PermissionDeniedError') {
    return CAMERA_ERROR.PERMISSION_DENIED
  }
  if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError' || error.name === 'OverconstrainedError' || error.name === 'ConstraintNotSatisfiedError') {
    return CAMERA_ERROR.NOT_FOUND
  }
  if (error.name === 'NotReadableError' || error.name === 'TrackStartError') {
    return CAMERA_ERROR.NOT_READABLE
  }
  return CAMERA_ERROR.CAPTURE_FAILED
}

export class CameraError extends Error {
  constructor(code, cause = null) {
    super(cameraErrorMessage(code))
    this.name = 'CameraError'
    this.code = code
    this.cause = cause
  }
}

/** Stop every track on a stream. Idempotent. */
export function stopStream(stream) {
  if (!stream || typeof stream.getTracks !== 'function') return false
  const tracks = stream.getTracks()
  for (const track of tracks) {
    try { track.stop() } catch {}
  }
  return tracks.length > 0
}

/**
 * Open the camera and attach it to `video`.
 * Resolves with `{ stream, stop }`. `stop()` releases the device.
 */
export async function openCamera(video, options = {}) {
  const {
    scope = globalThis,
    constraints = DEFAULT_VIDEO_CONSTRAINTS,
  } = options

  if (!isCameraSupported(scope)) {
    throw new CameraError(CAMERA_ERROR.UNSUPPORTED)
  }

  // Release any stream already attached to this video element.
  const previous = video ? video.srcObject : null
  if (previous) {
    stopStream(previous)
    if (video) video.srcObject = null
  }

  let stream
  try {
    stream = await scope.navigator.mediaDevices.getUserMedia(constraints)
  } catch (error) {
    throw new CameraError(classifyCameraError(error), error)
  }

  if (!stream) {
    throw new CameraError(CAMERA_ERROR.CAPTURE_FAILED)
  }

  const videoTracks =
    stream.getVideoTracks != null
      ? stream.getVideoTracks()
      : stream.getTracks().filter((t) => t.kind === 'video')
  if (videoTracks.length === 0) {
    stopStream(stream)
    throw new CameraError(CAMERA_ERROR.NOT_FOUND, stream)
  }

  if (video) {
    video.srcObject = stream
    video.muted = true
    video.playsInline = true
    video.loop = true
    if (typeof video.play === 'function') {
      try { await video.play() } catch {}
    }
  }

  console.log('[SimpleFace] camera opened')
  return {
    stream,
    stop() {
      stopStream(stream)
      if (video) video.srcObject = null
    },
  }
}

/**
 * Wait until the video element has real dimensions.
 * Returns true when videoWidth/videoHeight are both > 0.
 */
export function waitForVideoDimensions(video, timeoutMs = 5000) {
  if (!video) return false
  if (video.videoWidth > 0 && video.videoHeight > 0) {
    console.log(`[SimpleFace] video ready ${video.videoWidth}x${video.videoHeight}`)
    return true
  }
  if (typeof video.addEventListener !== 'function') {
    return video.srcObject != null
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs)
    const check = () => {
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        clearTimeout(timer)
        console.log(`[SimpleFace] video ready ${video.videoWidth}x${video.videoHeight}`)
        resolve(true)
      }
    }
    video.addEventListener('loadedmetadata', check, { once: true })
    video.addEventListener('canplay', check, { once: true })
    video.addEventListener('loadeddata', check, { once: true })
    const poll = setInterval(() => {
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        clearTimeout(timer)
        clearInterval(poll)
        console.log(`[SimpleFace] video ready ${video.videoWidth}x${video.videoHeight}`)
        resolve(true)
      }
    }, 100)
  }) || false
}

/**
 * Capture a single JPEG frame from a live <video> element.
 * Returns a Blob or null. Uses a timeout so toBlob can never hang indefinitely.
 */
export function captureFrame(video, timeoutMs = 5000) {
  console.log('[SimpleFace] capture clicked')
  if (!video) {
    console.warn('[SimpleFace] captureFrame: no video element')
    return null
  }
  const vw = video.videoWidth || CAPTURE_WIDTH
  const vh = video.videoHeight || CAPTURE_HEIGHT

  const canvas = document.createElement('canvas')
  canvas.width = vw
  canvas.height = vh

  const context = canvas.getContext('2d')
  if (!context) {
    console.warn('[SimpleFace] captureFrame: no 2d context')
    return null
  }

  try {
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
  } catch (error) {
    console.warn('[SimpleFace] captureFrame: drawImage failed', error && error.message)
    return null
  }

  return new Promise((resolve) => {
    let cleared = false
    const timer = setTimeout(() => {
      if (!cleared) {
        cleared = true
        console.warn('[SimpleFace] captureFrame: toBlob timed out after', timeoutMs, 'ms')
        resolve(null)
      }
    }, timeoutMs)

    canvas.toBlob((result) => {
      if (!cleared) {
        cleared = true
        clearTimeout(timer)
        if (result) {
          console.log('[SimpleFace] JPEG created', result.size, 'bytes')
        } else {
          console.warn('[SimpleFace] captureFrame: toBlob returned null/empty')
        }
        resolve(result || null)
      }
    }, 'image/jpeg', DEFAULT_JPEG_QUALITY)
  })
}

/**
 * Build a multipart body for a face capture submission.
 * Carries the captured frames plus optional extra fields.
 */
export function buildFramesPayload(frames, challengeOrExtra = {}, extraFields = {}) {
  if (!Array.isArray(frames) || frames.length === 0) {
    throw new CameraError(CAMERA_ERROR.CAPTURE_FAILED)
  }

  const form = new FormData()
  frames.forEach((blob, index) => {
    form.append('frames', blob, `frame-${index}.jpg`)
  })

  let mergedFields = {}
  if (typeof challengeOrExtra === 'string') {
    mergedFields.challenge_id = challengeOrExtra
    if (extraFields && typeof extraFields === 'object') {
      mergedFields = { ...mergedFields, ...extraFields }
    }
  } else if (challengeOrExtra && typeof challengeOrExtra === 'object') {
    mergedFields = { ...challengeOrExtra, ...extraFields }
  }

  for (const [key, value] of Object.entries(mergedFields)) {
    if (value === undefined || value === null || value === '') continue
    form.append(key, String(value))
  }

  return form
}
