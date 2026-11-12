/**
 * Phase 3 registration UI wiring tests.
 *
 * Run with `npm test`. Asserts the properties of `src/Registration.jsx` that
 * matter for security and correctness without needing a DOM or bundler.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const REGISTRATION = readFileSync(join(HERE, '..', 'src', 'Registration.jsx'), 'utf8')

/** Strip comments so negative assertions inspect code, not prose. */
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const CODE = stripComments(REGISTRATION)

test('uses the shared API client and never a raw fetch', () => {
  assert.match(REGISTRATION, /import\s+\{\s*api\s*\}\s+from\s+'\.\/api\/client\.js'/)
  assert.doesNotMatch(CODE, /\bfetch\(/)
})

test('the lifecycle order is check, request-otp, verify-otp, complete', () => {
  const check = CODE.indexOf("api.post('/registration/check'")
  const request = CODE.indexOf("api.post('/registration/request-otp'")
  const verify = CODE.indexOf("api.post('/registration/verify-otp'")
  const complete = CODE.indexOf("api.post('/registration/complete'")

  assert.ok(check >= 0, 'eligibility check missing')
  assert.ok(request >= 0, 'otp request missing')
  assert.ok(verify >= 0, 'otp verification missing')
  assert.ok(complete >= 0, 'completion missing')
  assert.ok(request > check, 'otp must follow the eligibility check')
  assert.ok(verify > request, 'verification must follow the otp request')
  assert.ok(complete > verify, 'completion must follow verification')
})

test('eligibility request sends only the USN', () => {
  assert.match(CODE, /api\.post\('\/registration\/check',\s*\{\s*usn\s*\}\)/)
})

test('the UI never declares eligibility, verification or completion itself', () => {
  // No client-side authority over server state.
  assert.doesNotMatch(CODE, /setEligible\s*\(true/)
  assert.doesNotMatch(CODE, /setEmailVerified\s*\(true/)
  assert.doesNotMatch(CODE, /localStorage/)
  assert.doesNotMatch(CODE, /sessionStorage/)
  assert.doesNotMatch(CODE, /document\.cookie/)
  assert.doesNotMatch(CODE, /setItem\(/)
})

test('the caller cannot submit a voter identity or roll field', () => {
  // Only usn is sent to the eligibility endpoint; no voter_id/email override.
  const checkCall = CODE.slice(
    CODE.indexOf("api.post('/registration/check'"),
    CODE.indexOf("api.post('/registration/check'") + 120,
  )
  assert.doesNotMatch(checkCall, /voter_id/)
  assert.doesNotMatch(checkCall, /is_eligible/)
  assert.doesNotMatch(checkCall, /college_email/)
})

test('no voter identity is sent to the completion endpoint', () => {
  const completeCall = CODE.slice(
    CODE.indexOf("api.post('/registration/complete'"),
    CODE.indexOf("api.post('/registration/complete'") + 160,
  )
  assert.match(completeCall, /username/)
  assert.match(completeCall, /password/)
  assert.doesNotMatch(completeCall, /voter_id/)
  assert.doesNotMatch(completeCall, /usn/)
})

test('the password and OTP are cleared once their step completes', () => {
  assert.match(CODE, /setOtp\(''\)/)
  assert.match(CODE, /setPassword\(''\)/)
})

test('no backend origin is hard-coded', () => {
  assert.doesNotMatch(REGISTRATION, /https?:\/\/(localhost|127\.0\.0\.1)/)
  assert.doesNotMatch(REGISTRATION, /localhost:\d+/)
})

test('no Phase 4+ surface is referenced', () => {
  assert.doesNotMatch(CODE, /wallet/i)
  assert.doesNotMatch(CODE, /metamask/i)
  assert.doesNotMatch(CODE, /face|liveness/i)
  assert.doesNotMatch(CODE, /blockchain|txHash|relayer/i)
  assert.doesNotMatch(CODE, /candidate|\/vote|\/voting/i)
})

test('the OTP input is numeric, length bounded and announces state', () => {
  assert.match(CODE, /inputMode="numeric"/)
  assert.match(CODE, /maxLength=\{6\}/)
  assert.match(CODE, /role="alert"/)
  assert.match(CODE, /role="status"/)
})

test('busy states disable the controls to prevent double submission', () => {
  assert.match(CODE, /disabled=\{busy/)
})

test('a resend path exists for a lost or expired code', () => {
  assert.match(CODE, /Send a new code/)
})

test('the development-only Mailpit hint is not shown to users', () => {
  assert.doesNotMatch(CODE, /Mailpit/i)
})

test('USN check advances to email entry step before requesting OTP', () => {
  assert.match(CODE, /setStep\('email'\)/)
  // Check handler must not request OTP immediately
  const checkFn = CODE.slice(
    CODE.indexOf('const checkEligibility'),
    CODE.indexOf('const requestOtp')
  )
  assert.doesNotMatch(checkFn, /api\.post\('\/registration\/request-otp'/)
})

test('request-otp sends entered college email payload', () => {
  assert.match(CODE, /api\.post\('\/registration\/request-otp',\s*\{\s*email\s*\}\)/)
})

test('masks email for OTP display on frontend', () => {
  assert.match(CODE, /maskedEmail/)
  assert.match(CODE, /maskEmail/)
})

test('college email input is typed email, required, and has clear placeholder', () => {
  assert.match(CODE, /type="email"/)
  assert.match(CODE, /placeholder="College Email"/)
})