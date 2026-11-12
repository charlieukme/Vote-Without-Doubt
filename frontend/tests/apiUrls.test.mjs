/**
 * Frontend foundation tests - Phase 1 remediation.
 *
 * Run with `npm test`. Uses only the Node built-in test runner, so there is no
 * test-framework dependency and no DOM or bundler shim required.
 *
 * These cover the defect found in the Phase 1 audit: the frontend hard-coded
 * `http://localhost:5000/api` in two components, so any deployment on another
 * origin, port or path silently contacted the developer's own machine.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  buildApiUrl,
  isAbsoluteUrl,
  isCrossOriginBase,
  normalizeBaseUrl,
} from '../src/api/urls.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC_DIR = join(HERE, '..', 'src')

// ------------------------------------------------------------ normalizeBaseUrl

test('normalizeBaseUrl strips trailing slashes', () => {
  assert.equal(normalizeBaseUrl('/api/'), '/api')
  assert.equal(normalizeBaseUrl('/api///'), '/api')
  assert.equal(normalizeBaseUrl('/api'), '/api')
})

test('normalizeBaseUrl treats empty and root values as no prefix', () => {
  assert.equal(normalizeBaseUrl(''), '')
  assert.equal(normalizeBaseUrl('   '), '')
  assert.equal(normalizeBaseUrl('/'), '')
  assert.equal(normalizeBaseUrl(undefined), '')
  assert.equal(normalizeBaseUrl(null), '')
})

// ------------------------------------------------------------------ buildApiUrl

test('buildApiUrl joins base and path without doubling slashes', () => {
  assert.equal(buildApiUrl('/health', '/api'), '/api/health')
  assert.equal(buildApiUrl('health', '/api'), '/api/health')
  assert.equal(buildApiUrl('/health', '/api/'), '/api/health')
})

test('buildApiUrl supports an empty base (same-origin paths)', () => {
  assert.equal(buildApiUrl('/api/health', ''), '/api/health')
  assert.equal(buildApiUrl('/api/health', '/'), '/api/health')
})

test('buildApiUrl preserves query strings and nested paths', () => {
  assert.equal(buildApiUrl('/auth/verify-otp?step=2', '/api'), '/api/auth/verify-otp?step=2')
  assert.equal(buildApiUrl('/a/b/c', '/api'), '/api/a/b/c')
})

test('buildApiUrl handles empty and missing paths', () => {
  assert.equal(buildApiUrl('', '/api'), '/api')
  assert.equal(buildApiUrl('/', '/api'), '/api')
  assert.equal(buildApiUrl(undefined, '/api'), '/api')
  assert.equal(buildApiUrl(null, ''), '/')
})

test('buildApiUrl supports an absolute cross-origin base', () => {
  assert.equal(
    buildApiUrl('/auth/status', 'https://api.example.com/api'),
    'https://api.example.com/api/auth/status',
  )
})

test('buildApiUrl passes an absolute URL through untouched', () => {
  assert.equal(
    buildApiUrl('https://other.example.com/thing', '/api'),
    'https://other.example.com/thing',
  )
})

test('buildApiUrl refuses a protocol-relative path', () => {
  assert.throws(() => buildApiUrl('//evil.example/steal', '/api'), /protocol-relative/)
  assert.throws(() => buildApiUrl('///evil.example', '/api'), /protocol-relative/)
})

// ----------------------------------------------------------------- URL helpers

test('isAbsoluteUrl requires an explicit scheme', () => {
  assert.equal(isAbsoluteUrl('https://example.com'), true)
  assert.equal(isAbsoluteUrl('HTTP://example.com'), true)
  assert.equal(isAbsoluteUrl('/api/health'), false)
  assert.equal(isAbsoluteUrl('//example.com'), false)
  assert.equal(isAbsoluteUrl(''), false)
  assert.equal(isAbsoluteUrl(undefined), false)
})

test('isCrossOriginBase distinguishes relative bases from remote ones', () => {
  assert.equal(isCrossOriginBase('/api'), false)
  assert.equal(isCrossOriginBase(''), false)
  assert.equal(isCrossOriginBase('https://api.example.com/api'), true)
})

// ------------------------------------------------- no hard-coded backend origins

function sourceFiles(dir, extensions = ['.js', '.jsx']) {
  const found = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      found.push(...sourceFiles(full, extensions))
    } else if (extensions.some((ext) => entry.name.endsWith(ext))) {
      found.push(full)
    }
  }
  return found
}

test('no component hard-codes a backend origin', () => {
  const offenders = []
  for (const file of sourceFiles(SRC_DIR)) {
    const contents = readFileSync(file, 'utf8')
    // Allow the client module and env module to *mention* cross-origin examples
    // in comments; any actual fetch target must come from the API client.
    if (basename(file) === 'client.js') continue
    if (/https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(contents)) {
      offenders.push(file.replace(SRC_DIR, 'src'))
    }
  }
  assert.deepEqual(offenders, [])
})

test('components use the shared API client instead of raw fetch', () => {
  const components = sourceFiles(SRC_DIR, ['.jsx']).filter(
    (file) => basename(file) !== 'ErrorBoundary.jsx',
  )
  const offenders = components.filter((file) => /\bfetch\(/.test(readFileSync(file, 'utf8')))
  assert.deepEqual(offenders.map((f) => f.replace(SRC_DIR, 'src')), [])
})

test('the app is wrapped in an error boundary', () => {
  const main = readFileSync(join(SRC_DIR, 'main.jsx'), 'utf8')
  assert.match(main, /ErrorBoundary/)
  assert.match(main, /<App \/>/)
})

test('vite proxies the API path in dev and preview', () => {
  const config = readFileSync(join(HERE, '..', 'vite.config.js'), 'utf8')
  assert.match(config, /'\/api'/)
  assert.match(config, /VITE_DEV_API_TARGET/)
})