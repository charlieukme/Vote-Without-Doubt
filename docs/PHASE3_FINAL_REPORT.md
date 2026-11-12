# PHASE 3 FINAL REPORT (RETROSPECTIVE)

**Document type:** Retrospective completion record, reconstructed during Phase 0 remediation and
**corrected after the Phase 3 implementation audit and remediation (2026-10-04)**.
For current status see `PROJECT_BIBLE.md` Section 3 and `docs/PHASE3_REMEDIATION_REPORT.md`.

- **Phase:** 3 — College Roll + Registration
- **Recorded status:** COMPLETE — **verified by execution**
- **Contemporaneous record:** `docs/PHASE3_CHECKPOINT.md`
- **Audit trail:** `docs/PHASE3_IMPLEMENTATION_AUDIT.md` (in-session verdict `PARTIAL`) →
  `docs/PHASE3_REMEDIATION_REPORT.md` (verdict `PASS`)

## 0. Correction notice

The earlier version of this document claimed Phase 3 was complete on the strength of five tests —
four CSV-parser unit tests and one assertion that an unknown USN returns `400`. An independent
audit on 2026-10-04 found the phase was not safe:

1. **CRITICAL** — `POST /api/admin/roll/import` was anonymously writable. The audit proved an
   anonymous caller could insert their own USN into the authoritative roll, become eligible and then
   register successfully. The endpoint was also not rate limited, because the rate-limit table had no
   `/api/admin` prefix.
2. **HIGH** — `complete_registration()` never checked `expires_at`, so an expired registration
   session could still create an account.
3. **HIGH** — `send_otp()`'s return value was discarded, so a failed delivery was reported to the
   voter as `OTP sent`.
4. **HIGH** — the electoral roll had no integrity or provenance mechanism at all.
5. **HIGH** — `"Already registered"` versus `"Not eligible or not found"` let an attacker enumerate
   which USNs existed and which were registered.
6. **MEDIUM** — `users.voter_id` had no uniqueness constraint, so one USN could back two accounts.

Phase 3 is COMPLETE only as of the remediation recorded below.

## 1. Scope delivered

| Area | Delivered |
|---|---|
| Roll models | `backend/app/models/roll.py` — `ElectoralRoll`, `RollImportBatch`, `RegistrationSession` |
| Provenance | Canonical order-independent SHA-256 roll digest on every import; `GET /api/admin/roll/verify` detects tampering |
| Authorization | `backend/app/security/admin_bootstrap.py` — bootstrap token, constant-time compare, fail closed |
| CSV import | `backend/app/utils/csv_import.py` — strict header, USN, email, year and duplicate validation |
| Service | `backend/app/services/registration_service.py` — dry-run/apply, eligibility, OTP issue/verify, completion, integrity verification |
| API | `backend/app/routes/registration.py` — four voter endpoints plus three guarded admin endpoints |
| Schema | `electoral_roll_imports` table, `otp_purpose`/`revoked`/`otp_max_attempts`/`otp_consumed_at` columns, unique `users.voter_id`; Alembic revision `b71820ceaad4` |
| Frontend | `frontend/src/Registration.jsx` — four-step flow via the shared client |
| Tests | `backend/tests/test_phase3_roll_import.py` (35), `backend/tests/test_phase3_registration.py` (31), `frontend/tests/registrationFlow.test.mjs` (13) |
| Proof harness | `backend/scripts/prove_phase3_registration.py` |

## 2. Verification evidence (re-executed after remediation, 2026-10-04)

| Command | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|
| `venv/Scripts/python -m pytest tests/ -q` | 342 | 342 | 0 | 0 |
| Phase 3 subset | 66 | 66 | 0 | 0 |
| `venv/Scripts/python scripts/prove_phase3_registration.py` | 21 proof steps | 21 | 0 | — |
| `cd frontend && npm test` | 38 | 38 | 0 | 0 |
| `cd frontend && npm run build` | — | built in 157ms | 0 | — |
| `flask db upgrade` + `db check` | — | applied, no drift | 0 | — |

All 40 mandatory positive and negative cases are exercised, including anonymous roll import
rejection, digest tamper detection, expired/revoked session rejection, cross-session and
cross-purpose OTP replay, email-failure handling and anti-enumeration.

## 3. Registration flow as built

`electoral_roll (is_eligible) → RegistrationSession(PENDING) → OTP emailed to the roll address →
verify (single-use, 5 min, 5 attempts, purpose-bound) → EMAIL_VERIFIED → Argon2id password →
User(voter_id = roll USN) → REGISTERED`. All state is server-authoritative and all registration data
stays in the identity plane.

## 4. Security properties as built

- The electoral roll cannot be modified anonymously; a bootstrap credential is required, compared in
  constant time, and fails closed. Production refuses to boot without one.
- A voter cannot be created without a matching, eligible roll entry; the roll also decides which
  mailbox receives the OTP.
- Roll tampering is detectable through the canonical digest.
- Registration responses cannot be used to enumerate voters.
- One USN can back at most one account, enforced by a database constraint.
- Passwords are Argon2id only; OTPs are stored only as HMAC-SHA256 under the server pepper and are
  never logged.

## 5. Limitations recorded honestly

- The bootstrap token is not RBAC: no per-officer identity and no four-eyes approval until Phase 11.
- An applied roll import has no rollback; corrections are made by re-importing.
- The digest attests the roll only, not the whole identity plane, and is a hash rather than a
  signature, so an attacker able to rewrite the roll could recompute a matching digest.
- The USN convention is inferred from the repository, since the project documents none.
- Email delivery is proven through a recording transport; CI performs no live SMTP handshake.
- The rate-limiter store is in-process, so limits are per worker.

---

**Phase 3 status:** COMPLETE — verified by execution after remediation (see `docs/PHASE3_REMEDIATION_REPORT.md`)