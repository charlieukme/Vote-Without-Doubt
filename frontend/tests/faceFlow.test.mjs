/**
 * Phase 5 face flow UI wiring tests.
 *
 * `src/faceCamera.js` is covered behaviourally in `faceCamera.test.mjs`.
 * `Face.jsx` is JSX and cannot be imported without a bundler, so the properties
 * asserted here are read from the source, matching the convention used by the
 * registration, wallet and auth flow tests.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const FACE = readFileSync(join(HERE, '..', 'src', 'Face.jsx'), 'utf8')

/** Strip comments so negative assertions inspect code, not prose. */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const CODE = stripComments(FACE)

test('uses the shared API client and never a raw fetch', () => {
  assert.match(FACE, /import\s+\{\s*api\s*\}\s+from\s+'\.\/api\/client\.js'/)
  assert.doesNotMatch(CODE, /\bfetch\(/)
})

test('calls only endpoints that the remediated backend actually exposes', () => {
  const literal = [...CODE.matchAll(/api\.(?:get|post)\(\s*'([^']+)'/g)].map((m) => m[1])
  assert.ok(literal.includes('/face/status'))
  assert.ok(literal.includes('/face/challenge'))
  assert.ok(literal.includes('/face/verify'))
})

test('the removed mock endpoints are gone', () => {
  for (const stale of [
    /\/face\/consent/,
    /\/face\/challenge\/enroll/,
    /\/face\/challenge\/verify/,
    /\/face\/withdraw(?!-consent)/,
  ]) {
    assert.doesNotMatch(CODE, stale, String(stale))
  }
  assert.doesNotMatch(CODE, /Mock/)
})

test('the client never sends a movement order or any liveness verdict', () => {
  assert.doesNotMatch(CODE, /sequence:\s*\[/)
  assert.doesNotMatch(CODE, /sequence:\s*['"]/)
  assert.doesNotMatch(CODE, /append\(\s*['"]sequence['"]/)
  assert.doesNotMatch(CODE, /\b(livenessPassed|liveness_passed|yaw|pose)\b\s*[:=]\s*(true|false|\[)/i)
})

test('frames are uploaded as multipart FormData built by the camera module', () => {
  assert.match(FACE, /buildFramesPayload\s*,?/)
  assert.match(CODE, /api\.post\(\s*'\/face\/verify'\s*,\s*body\b/)
  assert.doesNotMatch(CODE, /frames:\s*\[\s*\d/)
  assert.doesNotMatch(CODE, /frames:\s*\[[\d\s,]+\]/)
})

test('the camera is opened through the tested helper, never raw getUserMedia', () => {
  assert.match(FACE, /\bopenCamera\(/)
  assert.doesNotMatch(CODE, /getUserMedia\(/)
})

test('every camera track is released on success, failure and unmount', () => {
  assert.match(CODE, /useEffect\(\s*\(\s*\)\s*=>\s*\{[\s\S]*?cameraRef\.current\.stop\(\)/)
  assert.match(CODE, /stopCamera\(\)/)
  assert.ok((CODE.match(/stopCamera\(\)/g) || []).length >= 2)
})

test('an aborted or unmounted capture cannot keep grabbing frames', () => {
  assert.match(CODE, /cancelledRef/)
})

test('consent status is rendered from server state', () => {
  assert.match(CODE, /status\.consent_given/)
})

test('the UI never persists a biometric frame or reads client storage', () => {
  assert.doesNotMatch(CODE, /localStorage/)
  assert.doesNotMatch(CODE, /sessionStorage/)
  assert.doesNotMatch(CODE, /document\.cookie/)
  assert.doesNotMatch(CODE, /indexedDB|caches\./)
  assert.doesNotMatch(CODE, /dataURL|toDataURL/)
})

test('the UI never decides enrolment or verification outcomes itself', () => {
  assert.doesNotMatch(CODE, /setStatus\(\{[^}]*enrolled:\s*true/)
  assert.doesNotMatch(CODE, /setVerified\(true\)/)
  assert.doesNotMatch(CODE, /verified:\s*true/)
  assert.match(CODE, /await api\.get\('\/face\/status'\)/)
})

test('consent can be withdrawn and the template deleted', () => {
  assert.match(CODE, /Withdraw Consent and Delete Template/)
})

test('camera failure modes are surfaced to the user', () => {
  assert.match(CODE, /cameraErrorMessage/)
  assert.match(CODE, /CAMERA_ERROR\.UNSUPPORTED/)
  assert.match(CODE, /instanceof CameraError/)
  assert.match(CODE, /role=["']alert["']/)
})

test('a challenge is requested before frame upload', () => {
  const challenge = CODE.indexOf("api.post('/face/challenge')")
  const upload = CODE.indexOf("api.post('/face/verify'")
  assert.ok(challenge >= 0 && upload >= 0)
  assert.ok(challenge < upload, 'the challenge must be minted before verification upload')
})

test('the capture is bounded by frame budget', () => {
  assert.match(CODE, /captureFrame/)
  assert.match(CODE, /buildFramesPayload/)
})


test('the camera preview is a muted inline video so autoplay is permitted', () => {
  assert.match(CODE, /<video/)
  assert.match(CODE, /ref=\{videoRef\}/)
  assert.match(CODE, /muted/)
  assert.match(CODE, /playsInline/)
})
