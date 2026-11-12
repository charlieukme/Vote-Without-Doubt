/**
 * Phase 2 authentication UI wiring tests.
 *
 * Run with `npm test`. These assert the properties of `src/Auth.jsx` that
 * matter for security and correctness without needing a DOM or a bundler:
 *
 * - the two-factor order is password, then request OTP, then verify OTP;
 * - the server is the only authority on authentication state;
 * - the password and OTP are never persisted to any web storage;
 * - no backend origin is hard-coded and the shared client is used;
 * - logout is wired.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const AUTH = readFileSync(join(HERE, '..', 'src', 'Auth.jsx'), 'utf8')
const CLIENT = readFileSync(join(HERE, '..', 'src', 'api', 'client.js'), 'utf8')

/**
 * Strip JSX/JS comments so negative assertions inspect executable code rather
 * than prose. Without this, a comment that merely *mentions* localStorage would
 * fail the check, which is exactly the false positive we want to avoid.
 */
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

const AUTH_CODE = stripComments(AUTH)

test('the auth UI uses the shared API client', () => {
  assert.match(AUTH, /import\s+\{\s*api\s*\}\s+from\s+'\.\/api\/client\.js'/)
  assert.doesNotMatch(AUTH, /\bfetch\(/)
})

test('the two-factor order is password, request-otp, verify-otp', () => {
  const login = AUTH.indexOf("api.post('/auth/login'")
  const request = AUTH.indexOf("api.post('/auth/request-otp'")
  const verify = AUTH.indexOf("api.post('/auth/verify-otp'")
  const logout = AUTH.indexOf("api.post('/auth/logout'")

  assert.ok(login >= 0, 'login call missing')
  assert.ok(request > login, 'request-otp must follow login')
  assert.ok(verify > request, 'verify-otp must follow request-otp')
  assert.ok(logout >= 0, 'logout call missing')
})

test('authentication state is read from the server, never set locally', () => {
  // The component must derive the flag from /auth/status, not assign it.
  assert.match(AUTH, /const authenticated = status\?\.authenticated === true/)
  assert.doesNotMatch(AUTH, /setAuthenticated\s*\(/)
  assert.doesNotMatch(AUTH, /setStatus\(\{\s*authenticated:\s*true/)
  assert.match(AUTH, /api\.get\('\/auth\/status'\)/)
})

test('secrets are never written to web storage', () => {
  assert.doesNotMatch(AUTH_CODE, /localStorage/)
  assert.doesNotMatch(AUTH_CODE, /sessionStorage/)
  assert.doesNotMatch(AUTH_CODE, /document\.cookie/)
  assert.doesNotMatch(AUTH_CODE, /setItem\(/)
})

test('the password and OTP are cleared once their step completes', () => {
  assert.match(AUTH, /setPassword\(''\)/)
  assert.match(AUTH, /setOtp\(''\)/)
})

test('no backend origin is hard-coded in the auth UI', () => {
  assert.doesNotMatch(AUTH, /https?:\/\/(localhost|127\.0\.0\.1)/)
  assert.doesNotMatch(AUTH, /localhost:\d+/)
})

test('the OTP input accepts digits only and is length bounded', () => {
  assert.match(AUTH, /inputMode="numeric"/)
  assert.match(AUTH, /maxLength=\{6\}/)
  assert.match(AUTH, /replace\(\/\\D\/g, ''\)/)
})

test('errors and status are announced to assistive technology', () => {
  assert.match(AUTH, /role="alert"/)
  assert.match(AUTH, /role="status"/)
})

test('busy states disable the submit controls', () => {
  assert.match(AUTH, /disabled=\{busy/)
})

test('the shared client sends session cookies with every request', () => {
  assert.match(CLIENT, /credentials:\s*'include'/)
})
