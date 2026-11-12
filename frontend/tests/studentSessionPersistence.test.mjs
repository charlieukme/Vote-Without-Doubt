/**
 * Regression test for Student Login Redirect Bug & Session Persistence.
 *
 * Asserts:
 * 1. AuthContext preserves student authenticated state on 429 RateLimit or transient network errors.
 * 2. handleUnauthorized does not treat credential rejection (401 on /auth/login or /auth/verify-otp) as session expiration.
 * 3. DashboardPage avoids redundant duplicate auth refresh if student is already authenticated.
 * 4. Auth component skips duplicate /auth/status call when onSuccess callback is provided.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const HERE = dirname(fileURLToPath(import.meta.url))
const AUTH_CTX = readFileSync(join(HERE, '..', 'src', 'router', 'AuthContext.jsx'), 'utf8')
const DASHBOARD = readFileSync(join(HERE, '..', 'src', 'pages', 'student', 'DashboardPage.jsx'), 'utf8')
const AUTH = readFileSync(join(HERE, '..', 'src', 'Auth.jsx'), 'utf8')

test('AuthContext refreshStudentAuth does not wipe out authenticated state on 429 or network errors', () => {
  // It must check for 401 before wiping out state, and preserve previous state on transient/rate-limit errors
  assert.match(AUTH_CTX, /if\s*\(err\?\.status\s*===\s*401\)/)
  assert.match(AUTH_CTX, /setStudentAuth\(\(prev\)\s*=>\s*prev\s*\?\?/)
})

test('handleUnauthorized ignores 401 errors from login and OTP verification attempts', () => {
  assert.match(AUTH_CTX, /url\.includes\('\/auth\/login'\)\s*\|\|\s*url\.includes\('\/auth\/verify-otp'\)/)
})

test('DashboardPage does not make redundant refreshStudentAuth calls if already authenticated', () => {
  assert.match(DASHBOARD, /if\s*\(!studentAuth\?\.authenticated\)\s*\{\s*await\s+refreshStudentAuth\(\)/)
})

test('Auth.jsx coordinates status refresh with onSuccess to prevent duplicate concurrent queries', () => {
  assert.match(AUTH, /if\s*\(onSuccess\)\s*\{\s*await\s+onSuccess\(\)\s*\}\s*else\s*\{\s*await\s+refreshStatus\(\)\s*\}/)
})
