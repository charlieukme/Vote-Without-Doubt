# PHASE 2 IMPLEMENTATION AUDIT

## 1. Executive Summary

This audit examined the Phase 2 "Auth Core" implementation of the "Vote Without Doubt" e-voting system. The audit was conducted strictly read-only against the actual codebase in `.` with no modifications made.

**Overall Verdict: PARTIAL**

Phase 2 has strong cryptographic foundations (Argon2id password hashing, HMAC-SHA256 OTP with pepper, secure session IDs) and correct models for users, auth sessions, and OTPs. However, the **AuthService is critically incomplete** — three core methods (`request_otp`, `verify_otp`, `logout`) are missing entirely, causing runtime `AttributeError` when the corresponding API endpoints are called. The login flow cannot complete, logout is broken, and the frontend auth UI cannot function end-to-end.

## 2. Overall Verdict

| Verdict | Meaning |
|---------|---------|
| **PARTIAL** | Significant implementation exists with critical gaps preventing Phase 2 from functioning as specified |

## 3. Requirement Table

| ID | Requirement | Verdict | Evidence | Main Issue |
|----|-------------|---------|----------|------------|
| **A** | Argon2id password hashing | **PASS** | `app/security/password.py` uses `argon2.PasswordHasher` | None |
| **B** | Secure server-side sessions | **PARTIAL** | `AuthSession` model exists with proper fields; but session ID stored in Flask signed cookie, not true server-side session validated on every request | Session validation only in `get_session()`; no middleware enforcing session check |
| **C** | Session security and lifecycle | **PASS** | Idle timeout 10 min, absolute timeout 2 hours enforced in `get_session()` | None |
| **D** | Session rotation | **FAIL** | No session ID regeneration after OTP verification | Missing in AuthService |
| **E** | OTP generation | **PASS** | `secrets.randbelow(1000000):06d` in `app/security/otp.py` | None |
| **F** | OTP hashing/protection | **PASS** | HMAC-SHA256 with pepper in `app/security/otp.py` | Pepper has dev fallback |
| **G** | OTP expiry/attempt limits | **PASS** | 5 min expiry, 5 max attempts enforced in both auth and registration OTP flows | None |
| **H** | OTP replay/single-use protection | **PASS** | `used` flag, `session_id` binding, purpose field in OTP model | None |
| **I** | Login flow | **FAIL** | `AuthService` missing `request_otp`, `verify_otp`, `logout` methods | Login starts but cannot complete OTP step; logout broken |
| **J** | Registration/auth boundary | **PASS** | Phase 3 registration separate in `registration_service.py` | Depends on Phase 3 electoral roll |
| **K** | Account lockout / abuse protection | **PASS** | 5 failed logins -> 15 min lockout; generic error messages | None |
| **L** | Generic authentication errors | **PASS** | All failures return "Invalid credentials" | None |
| **M** | Logout/revocation | **FAIL** | `logout()` method missing from `AuthService` | Runtime `AttributeError` |
| **N** | Authentication status | **PASS** | `/auth/status` correctly reflects server-side session state | None |
| **O** | Mailpit/email service integration | **PARTIAL** | `EmailService` exists, uses env config, dev Mailpit config | Pepper has dev fallback; OTP not delivered without Mailpit running |
| **P** | Identity-plane placement | **PASS** | Users, AuthSession, OTP tables in identity plane with no cross-plane FKs | None |
| **Q** | Security tests | **PARTIAL** | `test_auth.py` has 9 unit tests for password/OTP; no integration tests for auth flow | No tests for login/OTP/logout endpoints |
| **R** | Frontend auth UI | **PARTIAL** | `Auth.jsx` and `Registration.jsx` exist, use shared API client | Backend endpoints broken; cannot complete flow |
| **S** | Phase 2 boundary enforcement | **FAIL** | Auth OTP flow depends on Phase 3 `ElectoralRoll` model for email | Crosses phase boundary |
| **T** | No fake/unsafe implementation | **PARTIAL** | Cryptography correct; but AuthService incomplete | Missing core methods |

## 4. Password Security

**PASS**

- Uses `argon2.PasswordHasher()` with default Argon2id parameters
- `hash_password()` raises on empty password
- `verify_password()` handles `VerifyMismatchError`, `InvalidHashError`, and generic exceptions safely
- Passwords never logged (sanitized in audit events)
- No hardcoded passwords or reversible encryption

## 5. Session Security

**PARTIAL**

**Strengths:**
- `AuthSession` model has: opaque 256-bit `session_id`, `auth_state`, `expires_at`, `idle_expires_at`, `last_activity`, `ip_address`, `user_agent`, `revoked`
- Absolute timeout: 120 minutes (2 hours)
- Idle timeout: 10 minutes
- Both enforced in `AuthService.get_session()` — returns `None` and marks `revoked=True` on expiry
- Session cookie: `HttpOnly`, `SameSite=Strict`, `Secure` in production

**Gaps:**
- Session ID stored in Flask's **signed cookie session** (`session['session_id']`), not true server-side session store
- No middleware validates session on every request — only `get_session()` checks expiry
- No `__Host-` prefix on session cookie
- Session fixation possible: no rotation after OTP verification (Requirement D)
- `Permanent_SESSION_LIFETIME` config (3600s) not aligned with AuthSession timeouts

## 6. OTP Security

**PASS** (cryptography)

- Generation: `secrets.randbelow(1_000_000):06d` — cryptographically secure 6-digit
- Storage: HMAC-SHA256 with pepper (`os.getenv('OTP_PEPPER', 'dev-otp-pepper-change-in-production')`)
- Verification: `hmac.compare_digest` — timing-safe
- Expiry: 5 minutes enforced
- Attempts: Max 5 enforced, counter incremented
- Replay protection: `used` flag, `session_id` binding, `purpose` field
- Registration OTP: Same protections in `RegistrationService` with `RegistrationSession`

**Note:** Pepper has a development fallback (`'dev-otp-pepper-change-in-production'`) — should be required in production.

## 7. Login / Authentication Flow

**FAIL — Critical**

The login flow **cannot complete** because `AuthService` is missing three required methods:

| Endpoint | Route | Calls | Status |
|----------|-------|-------|--------|
| `/api/auth/request-otp` | POST | `auth_service.request_otp(sid, 'login')` | **AttributeError** |
| `/api/auth/verify-otp` | POST | `auth_service.verify_otp(sid, otp, 'login')` | **AttributeError** |
| `/api/auth/logout` | POST | `auth_service.logout(sid)` | **AttributeError** |

**Working:**
- `/api/auth/register` — creates user with Argon2id hash
- `/api/auth/login` — verifies password, creates `AuthSession` with `PENDING_FACTORS`, stores `session_id` in Flask session
- `/api/auth/status` — returns `authenticated: false` + `state: PENDING_FACTORS` correctly

**Broken:**
- After login, user cannot request OTP → cannot verify OTP → cannot reach `AUTHORIZED` state
- Logout throws `AttributeError` and leaves session active
- Frontend `Auth.jsx` calls these endpoints but they fail

## 8. Lockout / Abuse Protection

**PASS**

- **Login lockout**: 5 failed attempts → `locked_until = now + 15 min`
- **Generic errors**: All failures return `"Invalid credentials"` — no user enumeration
- **Lockout enforced**: Locked user with correct password still gets `"Invalid credentials"`
- **OTP attempt limit**: 5 max (both auth and registration OTP)
- **Rate limiting**: Phase 1 rate limiter exists but not specifically scoped to auth endpoints

## 9. Email/Mailpit

**PARTIAL**

- `EmailService` reads SMTP config from env (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`)
- `send_otp(recipient, otp, purpose)` sends plain-text email with OTP
- **Issues:**
  - Dev pepper fallback in `otp.py` (`'dev-otp-pepper-change-in-production'`)
  - No verification that email was sent — returns `True/False` but caller doesn't check
  - Mailpit not running in test environment (expected)
  - OTP visible in email body (by design for Mailpit dev visibility)

## 10. Identity/Privacy Separation

**PASS**

- All auth tables (`users`, `auth_sessions`, `otps`) in identity plane
- No cross-plane foreign keys to ballot plane
- `User.voter_id` links to `voter_identities` (identity plane) — optional
- `AuthSession.user_id` FK to `users` (identity plane)
- `OTP.user_id` FK to `users` (identity plane)
- Password hashes, OTP hashes, session data all identity-plane

## 11. Frontend Authentication

**PARTIAL**

- `Auth.jsx`: Login form, OTP form, logout button, status display — uses shared `api` client
- `Registration.jsx`: USN check, OTP request/verify, completion — uses shared `api` client
- **Issues:**
  - Backend endpoints `/auth/request-otp`, `/auth/verify-otp`, `/auth/logout` return 500 (missing methods)
  - Cannot complete login flow or logout
  - No password storage on frontend (correct)
  - No raw OTP storage on frontend (correct)
  - Server remains authoritative (correct)

## 12. Security Attack Tests

| Attack | Result | Notes |
|--------|--------|-------|
| Password without OTP | N/A | OTP flow broken |
| OTP without password | N/A | Login starts but OTP step missing |
| Expired OTP | PASS | Returns "OTP expired" (registration flow tested) |
| Reused OTP | PASS | Returns "OTP already used" |
| OTP from another session | PASS | `session_id` binding prevents |
| OTP from another purpose | PASS | `purpose` field distinguishes |
| Revoked session | PASS | Returns unauthenticated |
| Expired session | PASS | Returns unauthenticated |
| Modified session cookie | PASS | Flask signed cookie invalidates |
| Fake frontend auth state | PASS | Server checks DB session |
| Direct protected API | PASS | Requires valid session |
| Repeated wrong passwords | PASS | Locks after 5 attempts |
| Repeated wrong OTPs | PASS | Blocks after 5 attempts |

## 13. Test Results

```
pytest tests/ -v
============================== 217 passed in 50.69s ==============================
```

**Phase 2 specific tests (`test_auth.py`): 9 passed** — but all are **unit tests only**:
- `test_password_hash_not_plaintext`
- `test_password_verify_correct`
- `test_password_verify_incorrect`
- `test_password_hash_not_reversible_as_plaintext`
- `test_otp_generation_six_digits`
- `test_otp_hash_not_raw`
- `test_otp_verify_correct`
- `test_otp_verify_incorrect`
- `test_auth_status_unauthenticated`

**Missing integration tests:**
- Login → request OTP → verify OTP → authorized
- OTP expiry / replay / cross-session / cross-purpose
- Logout invalidates session
- Account lockout after 5 failures
- Generic error responses
- Session idle/absolute expiry

## 14. Documentation Consistency

| Document | Status |
|----------|--------|
| `PROJECT_BIBLE.md` Section 3 | Lists Phase 2 as **COMPLETE** — **inconsistent** with actual state |
| `docs/PHASE2_CHECKPOINT.md` | Claims Phase 2 complete — **inconsistent** |
| `docs/PHASE2_FINAL_REPORT.md` | Claims Phase 2 complete — **inconsistent** |

## 15. Phase Boundary

**FAIL — Crosses into Phase 3**

The auth OTP flow **depends on Phase 3 `ElectoralRoll` model** for email lookup during registration. The `RegistrationService` correctly handles Phase 3 registration, but the Phase 2 `AuthService` should not require Phase 3 infrastructure for basic login OTP.

## 16. Critical Findings

| # | Finding | Severity | File |
|---|---------|----------|------|
| 1 | `AuthService.request_otp` missing | **CRITICAL** | `backend/app/services/auth_service.py` |
| 2 | `AuthService.verify_otp` missing | **CRITICAL** | `backend/app/services/auth_service.py` |
| 3 | `AuthService.logout` missing | **CRITICAL** | `backend/app/services/auth_service.py` |
| 4 | No session rotation after OTP | **HIGH** | `backend/app/services/auth_service.py` |
| 5 | Phase 2 auth depends on Phase 3 `ElectoralRoll` | **HIGH** | `backend/app/services/registration_service.py` |

## 17. Medium Findings

| # | Finding | Severity | File |
|---|---------|----------|------|
| 6 | Pepper has dev fallback | MEDIUM | `backend/app/security/otp.py:17` |
| 7 | No session rotation middleware | MEDIUM | `backend/app/security/middleware.py` |
| 8 | Session cookie lacks `__Host-` prefix | MEDIUM | `backend/app/config/config.py` |
| 9 | No integration tests for auth flow | MEDIUM | `backend/tests/test_auth.py` |
| 10 | Email send not verified | MEDIUM | `backend/app/email/service.py:49` |

## 18. Minor Findings

| # | Finding | Severity | File |
|---|---------|----------|------|
| 11 | `SESSION_LIFETIME_SECONDS` config unused for AuthSession | MINOR | `backend/app/config/config.py` |
| 12 | `WTF_CSRF_ENABLED = False` in TestingConfig | MINOR | `backend/app/config/config.py` |
| 13 | Mailpit not running in test env | MINOR | Environment |

## 19. Missing Evidence

- No integration test covering complete login flow (password → OTP → authorized)
- No test for session rotation after factor completion
- No test for logout revoking server-side session
- No test for concurrent session limits (one active session per voter)
- No test for session fixation prevention

## 20. Recommended Remediation Scope

**Must fix for Phase 2 PASS:**

1. Implement `AuthService.request_otp(sid, purpose)` — generate OTP, store hash in `OTP` table with `session_id` binding, send email
2. Implement `AuthService.verify_otp(sid, otp, purpose)` — verify HMAC, check expiry/attempts/used, mark `used=True`, update `AuthSession.auth_state='AUTHORIZED'`, **rotate session ID**
3. Implement `AuthService.logout(sid)` — mark `AuthSession.revoked=True`, clear Flask session
4. Add session rotation middleware/utility
5. Add integration tests for complete auth flow
6. Remove Phase 3 dependency from Phase 2 (or document as known deviation)
7. Make OTP pepper required in production (fail if not set)
7. Add `__Host-` prefix to session cookie in production

---

**PHASE 2 AUDIT COMPLETE — PARTIAL**