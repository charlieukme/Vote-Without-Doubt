/**
 * Runtime configuration - Phase 1 frontend foundation.
 *
 * The API base URL is read from the build-time environment instead of being
 * hard-coded in components. The default is the relative path `/api`, which the
 * Vite dev server proxies to the Flask backend (see `vite.config.js`) and which
 * is also correct behind a reverse proxy in a deployment.
 *
 * `import.meta.env` is undefined under plain Node (used by the dependency-free
 * tests), so it is read defensively.
 */

const metaEnv = (typeof import.meta !== 'undefined' && import.meta.env) || {}

/** Default base: same-origin relative path, proxied in dev and in deployment. */
export const DEFAULT_API_BASE_URL = '/api'

export const API_BASE_URL =
  (typeof metaEnv.VITE_API_BASE_URL === 'string' && metaEnv.VITE_API_BASE_URL.trim()) ||
  DEFAULT_API_BASE_URL

export const IS_DEV = Boolean(metaEnv.DEV)
export const IS_PROD = Boolean(metaEnv.PROD)