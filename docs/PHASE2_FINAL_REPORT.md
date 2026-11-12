# PHASE 2 FINAL REPORT (RETROSPECTIVE)

**Document type:** Retrospective completion record, first reconstructed during Phase 0 remediation
and **corrected after the Phase 2 implementation audit and remediation (2026-10-04)**.
For current status see `PROJECT_BIBLE.md` Section 3 and
`docs/PHASE2_REMEDIATION_REPORT.md`.

- **Phase:** 2 — Auth Core
- **Recorded status:** COMPLETE — **verified by execution, not by assertion**
- **Contemporaneous record:** `docs/PHASE2_CHECKPOINT.md`
- **Audit trail:** `docs/PHASE2_IMPLEMENTATION_AUDIT.md` (verdict `PARTIAL`) →
  `docs/PHASE2_REMEDIATION_REPORT.md` (verdict `PASS`)

## 0. Correction notice

The earlier version of this document claimed Phase 2 was complete on the strength of nine unit tests
over helper functions. An independent audit on 2026-10-04 found the authentication flow was not
implemented end to end: `AuthService.request_otp`, `AuthService.verify_otp` and
`AuthService.logout` did not exist, so `POST /api/auth/request-otp`, `/api/auth/verify-otp` and
`/api/auth/logout` all failed with `AttributeError`. Password + OTP could never reach
`AUTHORIZED`, and no session could be revoked. The original audit also asserted that Phase 2
depended on the Phase 3 electoral roll; that assertion was incorrect and is documented in
`docs/PHASE2_REMEDIATION_REPORT.md` §14.

Phase 2 is COMPLETE only as of the remediation recorded below.

## 1. Scope delivered

| Area | Delivered |
|---|---|
| Password hashing | `backend/app/security/password.py` — Argon2id via `argon2.PasswordHasher` |
| Sessions | `backend/app/security/sessions.py` — 256-bit opaque ids, 10-minute sliding idle, 2-hour absolute cap; `backend/app/models/auth_session.py` is the authoritative server-side record |
| Rotation | `AuthService._rotate_session()` — new id on OTP success, previous row revoked (fixation defence) |
| OTP | `backend/app/security/otp.py` — `secrets.randbelow` 6-digit codes, HMAC-SHA256 under a server pepper, 5-minute TTL, 5 attempts, single use, session and purpose binding |
| Pepper policy | No production fallback; `Config.validate()` refuses to boot production without `OTP_PEPPER` |
| Email | `backend/app/email/service.py` — environment-driven SMTP for Mailpit in development |
| Service | `backend/app/services/auth_service.py` — `authenticate`, `request_otp`, `verify_otp`, `logout`, `get_session` |
| API | `backend/app/routes/auth.py` — `login`, `request-otp`, `verify-otp`, `status`, `session` (protected), `logout`. `/auth/register` was **removed**: it accepted a caller-supplied `voter_id` and bypassed Phase 3 roll gating |
| Models | `backend/app/models/auth.py` — `User`, `OTP` (identity plane only) |
| Schema | auth tables in `backend/app/schema.sql` and the Alembic migrations |
| Frontend | `frontend/src/Auth.jsx`, `frontend/src/Auth.css` — server-authoritative state, secrets cleared after use, no web storage |
| Audit trail | Authentication lifecycle events recorded without identifiers |
| Tests | `backend/tests/test_phase2_lifecycle.py`, `test_phase2_sessions.py`, `test_phase2_otp_security.py`, `test_phase2_password_audit.py`, `frontend/tests/authFlow.test.mjs` |
| Proof harness | `backend/scripts/prove_phase2_auth.py` |

## 2. Verification evidence (re-executed after remediation, 2026-10-04)

| Command | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|
| `venv/Scripts/python -m pytest tests/ -q` | 274 | 274 | 0 | 0 |
| Phase 2 subset (four Phase 2 files + `test_auth.py`) | 65 | 65 | 0 | 0 |
| `python scripts/prove_phase2_auth.py` | 18 proof steps | 18 | 0 | — |
| `cd frontend && npm test` | 25 | 25 | 0 | 0 |

All 36 mandatory positive and negative cases are exercised, including session rotation with
old-identifier rejection, logout revocation, OTP replay, cross-session replay, cross-purpose
replay, attempt exhaustion, expiry, cookie tampering, and anti-enumeration.

## 3. Security properties as built

- Passwords are Argon2id hashed, never stored or compared in plaintext, and never returned by an API.
- Sessions are opaque 256-bit server-side records; the cookie is HttpOnly, SameSite=Strict, and
  `__Host-`-prefixed with `Secure` and `Path=/` in production.
- A password alone never authorises; the emailed OTP is mandatory and the session id is rotated when
  it succeeds.
- OTPs are stored only as HMAC-SHA256 under a server-side pepper, expire in 5 minutes, allow 5
  attempts, are single-use, and are bound to both session and purpose.
- Authentication failures are indistinguishable from each other, and unknown accounts pay the same
  Argon2id cost as real ones.
- Five failed passwords lock the account for 15 minutes; `/api/auth` is additionally rate limited.
- Nothing identifying is written to logs: session identifiers are never logged, and the audit
  sanitiser is deny-by-default.

## 4. Limitations recorded honestly

- `AuthService` methods that set the Flask session require a request context, so they are not
  callable from a background worker.
- The rate limiter store is in-process; a multi-worker deployment needs a shared backend.
- `SELECT ... FOR UPDATE` on the OTP row is honoured by MySQL and ignored by SQLite, so the test
  suite exercises the logic but not the row lock.
- Email delivery is proven through a recording transport and honest failure handling; CI performs no
  live SMTP handshake.
- Pre-existing Phase 4 inconsistency, left untouched as out of scope: `GET /api/wallet/status`
  answers `200 {'bound': false}` rather than `401` when unauthenticated. It discloses nothing.

---

**Phase 2 status:** COMPLETE — verified by execution after remediation (see `docs/PHASE2_REMEDIATION_REPORT.md`)
