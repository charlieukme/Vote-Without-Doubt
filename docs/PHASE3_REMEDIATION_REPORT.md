# Phase 3 Remediation Report — Roll + Registration

**Date:** 2026-10-04
**Target:** Phase 3 "College Roll + Registration" of *Vote Without Doubt*
**Trigger:** Independent Phase 3 implementation audit, verdict `PARTIAL`
**Scope:** Phase 3 only. No Phase 4+ functionality was implemented.

---

## 1. Original Findings, Root Causes and Fixes

| # | Finding | Severity | Root cause | Fix |
|---|---------|----------|-----------|-----|
| C1 | Unauthenticated electoral-roll write defeats eligibility gating | CRITICAL | `routes/registration.py` exposed `POST /api/admin/roll/import` with no authentication, no authorization and no rate limit, and the Phase 1 rate-limit table had no `/api/admin` prefix so it was never throttled | New `app/security/admin_bootstrap.py` with an env-sourced bootstrap token, `hmac.compare_digest` comparison, fail-closed behaviour and an `admin_guard()` decorator on every `/api/admin/*` route; added `'/api/admin': (10, 300)` to `RATE_LIMIT_RULES`; production refuses to boot without `ROLL_ADMIN_TOKEN` |
| C2 | Expired registration session can still complete | HIGH | `complete_registration()` validated `state` and `email_verified` but never `expires_at` or `revoked` | Expiry and revocation are now checked before completion; an expired session is marked revoked and rejected; state machine enforced (`EMAIL_VERIFIED` only) |
| C3 | Email delivery failure reported as success | HIGH | `request_registration_otp()` discarded `send_otp()`'s boolean return | The return value is inspected; on failure the OTP hash and purpose are nulled, the code becomes unverifiable, and the caller receives `400 Unable to send OTP` |
| C4 | No electoral-roll integrity or provenance | HIGH | `electoral_roll` stored only `import_batch`; no digest, no Merkle root, no provenance record | New `RollImportBatch` table plus deterministic `compute_roll_digest()` (canonical, order-independent SHA-256); `dry_run_import` / `import_roll` / `verify_roll_integrity`; `GET /api/admin/roll/verify` recomputes and reports a mismatch |
| C5 | Registration responses allow voter enumeration | HIGH | `start_registration()` returned distinct strings: `"Not eligible or not found"` vs `"Already registered"` | A single `GENERIC_REGISTRATION_MESSAGE` is returned for unknown, ineligible and already-registered; timing equalised with a dummy Argon2id verification on the unknown path; details go only to the audit trail |
| C6 | `users.voter_id` had no database uniqueness constraint | MEDIUM | The column was indexed but not unique, so two identities could share one USN under a race | `unique=True` on the model plus Alembic revision `b71820ceaad4` creating the unique index |
| A1 | CSV validation too weak | MEDIUM | Email validated only by `'@' in email`; no USN format check; bad `Year` silently dropped | Strict shape validation: size cap, row cap, USN pattern (`^[A-Za-z0-9]{3,50}$` with at least one digit), email regex, year range 1–6 with errors, control-character rejection, ragged-row handling, rejected values never echoed back |
| A2 | Registration OTP lacked persisted purpose | MEDIUM | `registration_sessions` had no purpose column, so purpose existed only in the email subject | Added `otp_purpose` (and `otp_max_attempts`, `otp_consumed_at`, `revoked`) with migration; verification enforces `registration_email_verification` |
| A3 | Lifecycle/security integration tests largely absent | HIGH | 5 tests: 4 CSV unit tests and one asserting a `400` | 66 Phase 3 tests across two new modules covering all 40 mandatory cases |
| A4 | Frontend registration flow untested | MEDIUM | No frontend test referenced registration | `frontend/tests/registrationFlow.test.mjs` — 13 tests; `Registration.jsx` rewritten (busy states, secret clearing, resend, no Mailpit hint) |
| A5 | Documentation claimed COMPLETE | MEDIUM | Checkpoint and final report asserted completion without lifecycle evidence | This report, plus corrected `PHASE3_CHECKPOINT.md`, `PHASE3_FINAL_REPORT.md` and a new `PROJECT_BIBLE.md` §3.1 |

## 2. Files Changed

**Backend — implementation**
- `app/security/admin_bootstrap.py` (new) — bootstrap authorization, fail closed, constant-time compare.
- `app/services/registration_service.py` (rewritten) — digest, dry-run/apply, integrity verification, expiry/revocation enforcement, honest email handling, generic errors, timing equalisation, state machine.
- `app/routes/registration.py` (rewritten) — admin guard on all `/api/admin/*`, generic error surface, `dry-run` and `verify` endpoints.
- `app/models/roll.py` (rewritten) — `RollImportBatch`, `otp_purpose`, `revoked`, `otp_max_attempts`, `otp_consumed_at`.
- `app/models/auth.py` — `users.voter_id` now `unique=True`.
- `app/utils/csv_import.py` (rewritten) — hardened validation.
- `app/security/rate_limit.py` — `/api/admin` prefix rule.
- `app/config/config.py` — production requires `ROLL_ADMIN_TOKEN`.
- `app/schema.sql` — provenance table, new registration columns, unique `voter_id`.
- `backend/migrations/versions/b71820ceaad4_*.py` (new) — provenance table, purpose/revoked columns, unique index.
- `backend/scripts/prove_phase3_registration.py` (new) — 21-step proof harness.
- `backend/.env.example` — documents `ROLL_ADMIN_TOKEN`.

**Tests**
- `tests/test_phase3_roll_import.py` (new) — 35 tests.
- `tests/test_phase3_registration.py` (new) — 31 tests.
- `tests/conftest.py` — Phase 3 fixtures already present from Phase 2 (`RecordingEmailService`, `auth_api`, `phase2_user`).
- `tests/test_config.py` — two production-boot tests updated for the new required token; two new tests added.

**Frontend**
- `frontend/src/Registration.jsx` (rewritten).
- `frontend/tests/registrationFlow.test.mjs` (new) — 13 tests.

## 3. Security Design Decisions

1. **Smallest secure authorization.** `PROJECT_BIBLE.md` §15 marks RBAC and four-eyes as *design only, Phase 11 not started*. Building a full admin subsystem was therefore out of scope; instead the roll endpoints require a bootstrap token from `ROLL_ADMIN_TOKEN`, compared in constant time, failing closed. Phase 11 replaces it.
2. **Never trust the client.** Only the `X-Admin-Token` header is accepted. `is_admin`, `role`, `X-Admin` and JSON claims are ignored; a test proves forged headers are rejected.
3. **Fail closed everywhere.** No token configured ⇒ endpoints return `403`. Production additionally refuses to boot without one.
4. **Eligibility is server-derived.** The USN is the only caller input; the roll decides identity, eligibility and the mailbox that receives the OTP. The resulting account email is copied from the roll.
5. **One generic failure.** Unknown, ineligible and already-registered all return `Unable to continue registration`. The unknown path performs a dummy Argon2id verification to blunt timing analysis.
6. **Reuse Phase 2 crypto.** `generate_otp`, `hash_otp`, `verify_otp` and `hash_password` are imported from `app.security`, not reimplemented. The pepper is never duplicated.
7. **Structure over conventions.** `voter_id` uniqueness is a database constraint, not an application check.

## 4. Roll Integrity / Provenance Design

`canonicalize_roll()` normalises each row (`usn`, `full_name`, `college_email`, `department`, `year_of_study`, `is_eligible`), lowercases the email, sorts by USN and serialises with sorted keys and fixed separators. `compute_roll_digest()` is SHA-256 over that form.

Consequences, all covered by tests:
- The same logical roll in any order yields the same digest.
- Changing any meaningful field changes the digest.
- A digest computed at dry-run still verifies after import, because both the parsed CSV shape and the stored ORM shape canonicalise identically.
- `verify_roll_integrity()` recomputes from the live table and compares with the applied batch; a single altered email yields `409 verified: false`.

No blockchain or signature scheme was introduced; the frozen architecture places signed anchoring later, and provenance here is a verifiable digest plus an audit-visible batch record.

## 5. Authorization Design for Roll Import

```
POST /api/admin/roll/dry-run   -> validate + digest only, writes no voter row
POST /api/admin/roll/import     -> dry-run, then apply; returns batch_id + digest
GET  /api/admin/roll/verify     -> recompute digest, 200 verified / 409 mismatch
```
All three require the bootstrap token, are rate limited under `/api/admin`, and are reachable only with a valid credential. The dry-run/apply boundary from the frozen Phase 3 scope is implemented.

## 6. Registration Lifecycle

`PENDING → EMAIL_VERIFIED → REGISTERED`, enforced server-side:

```
electoral_roll (is_eligible) -> start_registration -> RegistrationSession(PENDING)
   -> request_registration_otp (entered college email verified against roll) -> HMAC(pepper, otp) + purpose, emailed to roll address
   -> verify_registration_otp -> EMAIL_VERIFIED (single-use, 5 min, 5 attempts)
   -> complete_registration -> argon2id password + User(voter_id=roll USN) -> REGISTERED
```

Invalid transitions are rejected: `PENDING → REGISTERED`, expired or revoked sessions, replayed OTPs, and any forged client state.

## 7. Tests Added

- `tests/test_phase3_roll_import.py` — 35 tests: anonymous/voter/forged/invalid-credential rejection, fail-closed behaviour, authorized import, rate limiting, token never echoed or hard-coded, digest determinism/order-independence/change-detection/tamper-detection, CSV validation matrix.
- `tests/test_phase3_registration.py` — 31 tests: eligibility, generic-response equality, lifecycle, state machine, expiry, revocation, OTP matrix (wrong/expired/reused/cross-session/cross-purpose/attempts), email-failure handling, Argon2id storage, no OTP in logs, plane separation, DB-level `voter_id` uniqueness.

## 8. Exact Commands and Results

| # | Command | Collected | Passed | Failed | Skipped |
|---|---------|-----------|--------|--------|---------|
| 1 | `venv/Scripts/python -m pytest tests/ -q` | 342 | 342 | 0 | 0 |
| 2 | `venv/Scripts/python -m pytest tests/test_phase3_roll_import.py tests/test_phase3_registration.py -q` | 66 | 66 | 0 | 0 |
| 3 | `venv/Scripts/python -m pytest tests/test_phase2_lifecycle.py tests/test_phase2_sessions.py tests/test_phase2_otp_security.py tests/test_phase2_password_audit.py tests/test_auth.py -q` (Phase 2 regression) | 65 | 65 | 0 | 0 |
| 4 | `venv/Scripts/python -m pytest tests/test_config.py tests/test_security_foundation.py tests/test_database.py tests/test_models.py tests/test_audit.py -q` (Phase 1 regression) | 176 | 176 | 0 | 0 |
| 5 | `venv/Scripts/python scripts/prove_phase3_registration.py` | 21 proof steps | 21 | 0 | — |
| 6 | `cd frontend && npm test` | 38 | 38 | 0 | 0 |
| 7 | `cd frontend && npm run build` | — | built in 157ms | 0 | — |
| 8 | `venv/Scripts/python -m flask --app "app:create_app" db upgrade` then `db check` | — | applied; `No new upgrade operations detected` | 0 | — |
| 9 | `venv/Scripts/python -m flake8` on Phase 3 files | — | 0 `F`/`W29`/`E9` findings | 0 | — |

Nothing is skipped or xfailed. Repo-wide flake8 retains pre-existing E501 findings and has no flake8 config; no new defect-class finding was introduced.

## 9. End-to-End Proof Results

`scripts/prove_phase3_registration.py` prints, among others:

```
anonymous POST /api/admin/roll/import   403 {'error': 'Not authorized'}
electoral_roll rows after anonymous attempt      0
wrong token                            403 {'error': 'Not authorized'}
is_admin/role headers                  403 {'error': 'Not authorized'}
POST /api/admin/roll/import            200 imported=3
roll digest stored                     116d4549...56dd  (64 hex chars)
dry-run status / roll rows             DRY_RUN / 3
OTP stored only protected              67fa5343...   raw OTP present? False
OTP purpose persisted                  registration_email_verification
OTP expires_at / attempts              ...  / 0 of 5
state transition                       EMAIL_VERIFIED email_verified=True
OTP replay rejected                    400
password hash algorithm                argon2id   plaintext in row? False
identity created                       voter_id=1CD22CS001 email=asha.rao@college.edu
username / voter_id unique constraint  True / True
unknown vs ineligible vs registered    identical True
completion on an expired session      400   user created? False
request-otp with a failing transport   400 {'error': 'Unable to send OTP'}
usable OTP left behind?                False
integrity before tampering             200 {'verified': True}
integrity after tampering              409 {'verified': False}
ballots / ballot_queue rows            0 / 0
```

## 10. Requirement A–AB Verification

| ID | Requirement | Verdict | Evidence |
|----|-------------|---------|----------|
| A | Electoral roll CSV import | **PASS** | `routes/registration.py` import/dry-run; authorized import applied 3 rows; anonymous rejected 403; rate limited |
| B | CSV validation | **PASS** | `csv_import.py`; binary/empty/no-header rejected; per-row errors with line numbers |
| C | Required columns and data types | **PASS** | Required columns enforced; USN pattern, email regex, year range 1–6 validated |
| D | Duplicate voter detection | **PASS** | In-file duplicate dropped at parse; cross-import duplicate reported; `electoral_roll.usn` UNIQUE |
| E | Invalid/malformed row handling | **PASS** | Ragged rows, control chars, over-long names reported without echoing values |
| F | Roll hash generation/integrity | **PASS** | `compute_roll_digest`; stored on `RollImportBatch`; `verify_roll_integrity` detects a one-field change |
| G | Roll stored in identity plane | **PASS** | `electoral_roll`, `electoral_roll_imports`, `registration_sessions`; no ballot-plane FKs |
| H | Voter eligibility lookup | **PASS** | `filter_by(usn, is_eligible=True)`; ineligible rejected |
| I | Voter ID/USN uniqueness | **PASS** | `electoral_roll.usn` UNIQUE and `users.voter_id` UNIQUE (DB-enforced, verified by `IntegrityError` test) |
| J | Registration session separation from AuthSession | **PASS** | Separate `reg_session` cookie key; `AuthSession.query.count() == 0` after registration |
| K | Registration OTP ownership verification | **PASS** | OTP emailed to `electoral_roll.college_email`; account email copied from the roll |
| L | Registration OTP policy | **PASS** | `secrets` 6-digit; 5-minute TTL; 5 attempts; single-use (`otp_used`/`otp_consumed_at`); session-bound; `otp_purpose` persisted and enforced |
| M | Registration password creation | **PASS** | Password accepted only at completion, after email verification |
| N | Password stored only as Argon2id | **PASS** | `$argon2id$v=19$m=`; plaintext absent from the row |
| O | Wallet collection/binding preparation | **N/A** | No wallet code in Phase 3; Phase 4 owns binding. A frontend test asserts none is referenced |
| P | Face enrollment boundary/preparation | **N/A** | No face code in Phase 3; Phase 5 owns it |
| Q | Registration completion state | **PASS** | `PENDING → EMAIL_VERIFIED → REGISTERED`; `REGISTERED` asserted after completion |
| R | Duplicate registration prevention | **PASS** | Second check returns the generic failure; user count unchanged |
| S | Registration cannot bypass roll eligibility | **PASS** | Roll is no longer anonymously writable; unknown/ineligible rejected; identity derived from the roll only |
| T | Registration cannot create arbitrary voter identities | **PASS** | Only `usn` is accepted; caller-supplied `voter_id`/`email` ignored and asserted |
| U | Identity-plane placement | **PASS** | Registration tables carry no ballot-plane foreign keys |
| V | No ballot-plane contamination | **PASS** | After registration `ballots=0`, `ballot_queue=0` |
| W | Anti-enumeration / generic errors | **PASS** | Unknown, ineligible and registered responses are byte-identical; timing equalised on the unknown path |
| X | Abuse/rate limiting | **PASS** | `/api/registration` → `429` after 5; `/api/admin` → `429` after 10 |
| Y | Security/integration tests | **PASS** | 66 Phase 3 tests covering all 40 mandatory cases; 342 total, 0 skipped |
| Z | Frontend registration flow | **PASS** | Four-step flow via the shared client; 13 UI tests; busy states; secrets cleared |
| AA | Phase boundary enforcement | **PASS** | No wallet/face/blockchain/ballot/revoting reference in Phase 3 code or UI |
| AB | No fake/unsafe implementation | **PASS** | Every flow proven by execution against the real app, DB, service and routes |

## 11. Remaining Limitations

1. **Bootstrap token is not RBAC.** A single shared token grants roll administration to whoever holds it. There is no per-officer identity, no separation of duties and no four-eyes approval until Phase 11. Documented in `admin_bootstrap.py` and `.env.example`.
2. **No rollback of an applied import.** A bad roll is corrected by re-importing, since `electoral_roll` rows are keyed by USN. There is no "revert to previous batch" operation.
3. **Digest covers the roll only.** It does not cover `registration_sessions` or accounts, so it attests voter eligibility, not the whole identity plane.
4. **Provenance is a hash, not a signature.** Anyone able to alter the roll can recompute a matching digest. Detecting *malicious* rewriting requires an external anchor, which the frozen architecture defers.
5. **USN convention is inferred.** The project documents no format, so `^[A-Za-z0-9]{3,50}$` with at least one digit is enforced; a real convention would tighten it.
6. **Email delivery proven via a recorder.** CI performs no live SMTP handshake.
7. **`with_for_update` is advisory on SQLite**, so OTP single-use is proven logically, not under a real row lock.
8. **Rate-limiter store is in-process**, so limits are per worker.

## 12. Final Verdict

All critical and high findings are remediated and verified by execution. Anonymous roll modification is impossible, tampering is detectable, eligibility cannot be bypassed, session expiry and revocation are enforced, email failure is reported honestly, anti-enumeration holds, `users.voter_id` is database-unique, and 342 backend plus 38 frontend tests pass with nothing skipped.

**PHASE 3 REMEDIATION COMPLETE — PASS**