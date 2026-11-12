/**
 * API URL construction - Phase 1 frontend foundation.
 *
 * Pure functions with no React and no browser globals, so they can be unit
 * tested directly under `node --test` without a bundler or DOM shim.
 *
 * The rules here mirror the backend's redirect allow-list discipline: the base
 * URL is normalised, paths are joined without producing `//`, and an absolute
 * path is never silently re-pointed at another origin.
 */

/** Trailing slashes are stripped so joining never yields a double slash. */
export function normalizeBaseUrl(base) {
  if (typeof base !== 'string') {
    return ''
  }
  const trimmed = base.trim()
  if (trimmed === '' || trimmed === '/') {
    return ''
  }
  return trimmed.replace(/\/+$/, '')
}

/**
 * Join the API base with an endpoint path.
 *
 * - a leading slash on `path` is optional;
 * - an absolute URL (`https://...`) is passed through untouched, which keeps an
 *   explicitly configured cross-origin base working;
 * - a protocol-relative path (`//evil.example`) is rejected, because it would
 *   leave the current origin once a browser resolves it.
 */
export function buildApiUrl(path, base) {
  const normalizedBase = normalizeBaseUrl(base)

  if (typeof path !== 'string' || path.trim() === '') {
    return normalizedBase || '/'
  }

  const trimmedPath = path.trim()

  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(trimmedPath)) {
    return trimmedPath
  }

  if (trimmedPath.startsWith('//')) {
    throw new Error(`Refusing to build a protocol-relative API URL: ${trimmedPath}`)
  }

  const suffix = trimmedPath.replace(/^\/+/, '')
  if (suffix === '') {
    return normalizedBase || '/'
  }

  return `${normalizedBase}/${suffix}`
}

/** True when the value is an absolute URL with an explicit scheme. */
export function isAbsoluteUrl(value) {
  return typeof value === 'string' && /^[a-z][a-z0-9+.-]*:\/\//i.test(value.trim())
}

/** True when the base URL points at another origin rather than this one. */
export function isCrossOriginBase(base) {
  const normalized = normalizeBaseUrl(base)
  if (normalized === '') {
    return false
  }
  if (normalized.startsWith('/')) {
    return false
  }
  return isAbsoluteUrl(normalized)
}