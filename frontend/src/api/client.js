/**
 * Centralised API client - Phase 1 frontend foundation.
 *
 * Every backend call in the app goes through this module so that the base URL,
 * credentials policy, JSON handling, timeout and error shape are defined once
 * instead of being repeated (and diverging) in each component.
 *
 * `credentials: 'include'` is required because the backend uses server-side
 * sessions; the CSRF header is attached automatically once a token has been
 * issued, matching the backend's `CSRF_ENABLED` mechanism.
 */

import { API_BASE_URL } from '../config/env.js'
import { buildApiUrl, isCrossOriginBase } from './urls.js'

/** Default request timeout. No request may hang the UI indefinitely. */
export const DEFAULT_TIMEOUT_MS = 15000

export class ApiError extends Error {
  constructor(message, { status = 0, url = '', payload = null, cause = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
    this.payload = payload
    this.cause = cause
  }

  /** True when the backend returned 429 Too Many Requests. */
  get isRateLimited() {
    return this.status === 429
  }

  /** True when the backend rejected the request rather than failing. */
  get isClientError() {
    return this.status >= 400 && this.status < 500
  }

  /** True when the request never reached the backend. */
  get isNetworkError() {
    return this.status === 0
  }
}

let csrfToken = null
let csrfFetchPromise = null

/** Record the CSRF token issued by the backend for subsequent writes. */
export function setCsrfToken(token) {
  csrfToken = typeof token === 'string' && token !== '' ? token : null
}

export function getCsrfToken() {
  return csrfToken
}

/** Ensure a valid CSRF token is present in memory before mutating requests. */
export async function ensureCsrfToken() {
  if (csrfToken) return csrfToken
  if (!csrfFetchPromise) {
    csrfFetchPromise = (async () => {
      try {
        const url = buildApiUrl('/auth/csrf-token', API_BASE_URL)
        const response = await fetch(url, {
          method: 'GET',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        })
        if (response.ok) {
          const data = await response.json().catch(() => null)
          if (data && typeof data.csrf_token === 'string') {
            csrfToken = data.csrf_token
            return csrfToken
          }
        }
      } catch (err) {
        // Log without halting: if backend has CSRF disabled, request proceeds
      } finally {
        csrfFetchPromise = null
      }
      return csrfToken
    })()
  }
  return csrfFetchPromise
}

function buildHeaders(options) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) }

  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  const method = (options.method || 'GET').toUpperCase()
  if (csrfToken && method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    headers['X-CSRF-Token'] = csrfToken
  }

  return headers
}

/**
 * Perform a request against the backend.
 *
 * Resolves with the parsed JSON body (or `null` for an empty body) and rejects
 * with an `ApiError` for transport failures, timeouts and non-2xx responses.
 */
export async function apiRequest(path, options = {}) {
  const url = buildApiUrl(path, API_BASE_URL)
  const method = (options.method || 'GET').toUpperCase()
  const timeout = options.timeout ?? DEFAULT_TIMEOUT_MS

  if (isCrossOriginBase(API_BASE_URL)) {
    console.warn(
      `[api] API base ${API_BASE_URL} is cross-origin; the backend CORS allow-list ` +
        'and cookie policy must both permit it.',
    )
  }

  // Pre-fetch CSRF token for mutating requests if not yet cached in memory
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS' && !csrfToken) {
    await ensureCsrfToken()
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  let response
  try {
    response = await fetch(url, {
      method,
      credentials: 'include',
      headers: buildHeaders({ ...options, method }),
      body:
        options.body === undefined || options.body instanceof FormData
          ? options.body
          : JSON.stringify(options.body),
      signal: controller.signal,
    })
  } catch (cause) {
    clearTimeout(timer)
    const aborted = cause && cause.name === 'AbortError'
    throw new ApiError(
      aborted
        ? `Request timed out after ${timeout}ms`
        : 'Could not reach the server. Check that the backend is running.',
      { status: 0, url, cause },
    )
  }
  clearTimeout(timer)

  const payload = await readBody(response)

  // Automatically adopt rotated or issued CSRF tokens from any API payload
  if (payload && typeof payload.csrf_token === 'string') {
    setCsrfToken(payload.csrf_token)
  }

  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('vwd:unauthorized', { detail: { url } }))
    }
    const detail =
      (payload && (payload.message || payload.error)) || `Request failed (${response.status})`

    // Retry once if CSRF validation failed due to session renewal or expired token
    const isCsrfError = response.status === 403 && (
      detail.toLowerCase().includes('csrf') || (payload?.message && payload.message.toLowerCase().includes('csrf'))
    )
    if (isCsrfError && !options._csrfRetried && method !== 'GET' && method !== 'HEAD') {
      csrfToken = null
      await ensureCsrfToken()
      return apiRequest(path, { ...options, _csrfRetried: true })
    }

    throw new ApiError(detail, { status: response.status, url, payload })
  }

  return payload
}

async function readBody(response) {
  const contentType = response.headers.get('content-type') || ''
  if (response.status === 204) {
    return null
  }
  if (!contentType.includes('application/json')) {
    const text = await response.text()
    return text === '' ? null : { raw: text }
  }
  try {
    return await response.json()
  } catch {
    return null
  }
}

/**
 * Perform a raw request returning the Fetch Response object directly.
 * Useful for binary downloads (CSV, XLSX) while preserving timeout and credentials.
 */
export async function apiRawRequest(path, options = {}) {
  const url = buildApiUrl(path, API_BASE_URL)
  const method = (options.method || 'GET').toUpperCase()
  const timeout = options.timeout ?? DEFAULT_TIMEOUT_MS

  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS' && !csrfToken) {
    await ensureCsrfToken()
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(url, {
      method,
      credentials: 'include',
      headers: buildHeaders({ ...options, method }),
      body: options.body,
      signal: controller.signal,
    })
    clearTimeout(timer)
    return response
  } catch (cause) {
    clearTimeout(timer)
    const aborted = cause && cause.name === 'AbortError'
    throw new ApiError(
      aborted
        ? `Request timed out after ${timeout}ms`
        : 'Could not reach the server. Check that the backend is running.',
      { status: 0, url, cause },
    )
  }
}

export const api = {
  get: (path, options) => apiRequest(path, { ...options, method: 'GET' }),
  post: (path, body, options) => apiRequest(path, { ...options, method: 'POST', body }),
  put: (path, body, options) => apiRequest(path, { ...options, method: 'PUT', body }),
  delete: (path, options) => apiRequest(path, { ...options, method: 'DELETE' }),
  raw: (path, options) => apiRawRequest(path, options),
}

export default api