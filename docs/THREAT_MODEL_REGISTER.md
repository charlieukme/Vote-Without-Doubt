# Threat Model Register

Vote Without Doubt - AI & Blockchain-Based Secure E-Voting System for College Elections
(**Academic Prototype - not a legally binding election system**).

This register instantiates the `THREAT -> CONTROL -> TEST -> RESULT -> LIMITATION` tracking format
declared in [`../PROJECT_BIBLE.md` Section 11](../PROJECT_BIBLE.md#11-threat-model) and
[`../PROJECT_MASTER_REPORT.md` Section 9](../PROJECT_MASTER_REPORT.md).

---

## How to read this register (evidence honesty rules)

1. A test is cited **only if it exists in this repository** and is named exactly.
2. Where a phase did not produce a test, the entry says **"Not yet evidenced"** and names the
   phase that owns the gap. It is never replaced with an assumed or imagined result.
3. `RESULT` reflects only what the cited evidence actually demonstrates. A passing unit test is
   **not** the same as a verified end-to-end control.
4. This register is a **documentation and audit artefact**. No security functionality was added
   or changed to produce it.

### Test inventory this register draws on (verified present)

| Suite | File | Tests |
|---|---|---|
| App foundation | `backend/tests/test_app.py` | 4 |
| Models / plane separation | `backend/tests/test_models.py` | 5 |
| Audit chain | `backend/tests/test_audit.py` | 6 |
| Auth (password + OTP) | `backend/tests/test_auth.py` | 9 |
| Registration / CSV roll | `backend/tests/test_registration.py` | 5 |
| Wallet challenge | `backend/tests/test_wallet.py` | 3 |
| Face (auth gating) | `backend/tests/test_face_validation.py` | 4 |
| Face API | `backend/tests/test_face_api.py` | 6 - **errors during collection, not passing** |
| Voting (auth gating + pseudonym) | `backend/tests/test_voting.py` | 6 |
| Privacy | `backend/tests/test_privacy.py` | 3 |
| Revoting | `backend/tests/test_revoting.py` | 2 (structural only) |
| Recovery | `backend/tests/test_recovery.py` | 2 (structural only) |
| Contract core | `blockchain/test/EVotingBallotBox.test.js` | 7 |
| Contract revoting | `blockchain/test/EVotingBallotBox_revoting.test.js` | 4 |

Backend regression baseline observed during Phase 0 remediation: **49 passed, 6 errors**
(the 6 errors are all `test_face_api.py` collection failures).

### Evidence-strength legend

- **EVIDENCED** - a repository test directly exercises the control.
- **PARTIAL** - code exists, but the cited test only covers part of the control, or the control
  is not enforced everywhere it must be.
- **CODE ONLY** - implementation exists but no test exercises it.
- **DESIGN ONLY** - specified in the baseline documentation, not implemented.
- **NOT EVIDENCED** - no implementation and no test.

---

## A. Identity and registration threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Malicious / fraudulent registration | Electoral-roll eligibility check before registration | `backend/tests/test_registration.py::test_registration_check_not_found` | EVIDENCED (negative path only) | Happy-path registration is not tested end to end |
| Duplicate registration | Duplicate detection in roll CSV import | `backend/tests/test_registration.py::test_csv_duplicate_usn` | EVIDENCED (import-level only) | No test proves a duplicate voter cannot register twice through the API |
| CSV roll tampering / malformed roll | Required-column validation and email format validation | `test_csv_parse_missing_required`, `test_csv_invalid_email`, `test_csv_parse_valid` | EVIDENCED | Roll integrity after import (hash of roll vs. on-chain `rollHash`) not tested |
| Impersonation / identity takeover | Ownership verification by email OTP + password + wallet + face factors | `test_otp_verify_correct`, `test_otp_verify_incorrect` | PARTIAL | No test proves that registering with another person's email is impossible end to end |
| Roll import authorisation | Endpoint exists at `POST /api/admin/roll/import` | No test found | **NOT EVIDENCED** | **Gap:** the roll-import endpoint has no visible authorisation test; admin RBAC is Phase 11 (NOT STARTED) |

## B. Authentication threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Password disclosure | Argon2id hashing | `test_password_hash_not_plaintext`, `test_password_verify_correct`, `test_password_verify_incorrect`, `test_password_hash_not_reversible_as_plaintext` | EVIDENCED | Argon2id parameters not asserted in tests |
| Offline OTP brute force / OTP disclosure | OTP stored as HMAC-SHA256 with server-side pepper, never raw | `test_otp_hash_not_raw`, `test_otp_generation_six_digits` | EVIDENCED | - |
| OTP replay | Single-use, purpose-bound, session-bound OTP with expiry and attempt cap | `test_otp_verify_correct`, `test_otp_verify_incorrect` | PARTIAL | **Gap:** no test asserts single-use enforcement, attempt cap (5), or 5-minute expiry. Phase 13 |
| OTP resend abuse / rate limiting | Resend cooldown and hourly limit designed | No test found; `RATE_LIMIT_ENABLED` exists as a config flag only | **DESIGN ONLY** | **Gap:** no rate limiter is implemented. Phase 13 |
| Session hijacking | HttpOnly / SameSite=Strict cookies, rotation after OTP, idle and absolute timeouts | `backend/app/config/config.py`, `backend/app/security/sessions.py` | CODE ONLY | `SESSION_COOKIE_SECURE = False` in config; no test asserts rotation or timeout behaviour |
| Concurrent-session abuse | One active session per voter | Design baseline only | **DESIGN ONLY** | **Gap:** not implemented/evidenced |
| User enumeration | Generic authentication errors | `test_auth_status_unauthenticated` | PARTIAL | Only the unauthenticated-status path is tested; no test asserts identical error bodies for unknown-user vs. wrong-password |
| Credential stuffing | Rate limiting on auth endpoints | No test found | **DESIGN ONLY** | Phase 13 |

## C. Biometric threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Face spoofing / replay | Challenge-based liveness (LEFT / RIGHT head movement, ~20s TTL) | `backend/tests/test_face_validation.py` (4 tests) - all assert **authentication gating only** | PARTIAL | **Gap:** no test exercises actual liveness matching or spoof rejection. No genuine recognition model is evidenced in the repository |
| Unauthorised face endpoints | Auth required on all `/api/face/*` write endpoints | `test_face_status_unauth`, `test_face_consent_unauth`, `test_face_challenge_enroll_unauth`, `test_face_challenge_verify_unauth` | EVIDENCED | - |
| Raw frame retention | Frames deleted immediately after processing | `backend/app/security/face.py`, `backend/app/services/face_service.py` | CODE ONLY | No test asserts frames are not persisted |
| Embedding disclosure | Embeddings encrypted at rest | `backend/app/security/face.py` | CODE ONLY | No test asserts encryption at rest |
| Deepfake / virtual-camera attack | Documented as a known limitation | Baseline docs only | **DESIGN ONLY** | **Gap:** FAR / FRR / APCER / BPCER evaluation is STRONG/Milestone B scope and is **not complete**. No measurement artefacts exist |
| Face API regression | 6 API tests intended | `backend/tests/test_face_api.py` | **FAILING** - 6 collection errors (missing `client` fixture) | **Gap:** a Phase 5 test-suite defect, documented and deliberately not fixed during Phase 0 remediation |

## D. Wallet / MetaMask threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Signature replay | Single-use, session- and purpose-bound nonce | `backend/tests/test_wallet.py::test_nonce_generation` | PARTIAL | Generation is tested; single-use consumption is not |
| Candidate leakage via wallet | Candidate selection is never part of the signed message | `test_wallet.py::test_message_contains_nonce_and_no_candidate` | EVIDENCED | - |
| Cross-domain signature reuse | Domain separation over chain ID, contract, election, purpose | `backend/app/security/wallet.py` | CODE ONLY | No test asserts the domain-separated payload contents |
| Address normalisation / checksum bypass | Address normalisation before comparison | `test_wallet.py::test_normalize_address` | EVIDENCED | - |
| Wallet takeover (wrong owner binds) | Binding flow requires an authenticated, challenged signature | `backend/app/services/wallet_service.py` | CODE ONLY | No end-to-end binding test |
| Relayer key compromise | Admin does not hold the relayer key (design baseline) | Baseline docs only | **DESIGN ONLY** | No key-management implementation exists yet |

## E. Voting and tally integrity threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Double voting | One counted ballot per pseudonym; contract sequence enforcement | `blockchain/test/EVotingBallotBox.test.js::cast_ballot_works`, `::sequence_enforced` | EVIDENCED **at contract level** | **Gap:** no backend test proves the server refuses a duplicate submission; all `test_voting.py` cases assert only 401 gating |
| Revote cap bypass | Contract rejects `sequence > maxBallots` | `blockchain/test/EVotingBallotBox_revoting.test.js::max 3 ballots: seq 1,2,3 ok; seq 4 rejected` | EVIDENCED **at contract level** | **Gap:** the backend revote-cap path is not tested; `test_revoting.py` contains no revote-cap assertion |
| Sequence manipulation (skip / repeat) | Contract requires `sequence == previous + 1` | `EVotingBallotBox_revoting.test.js::sequence cannot skip / must increment by 1` | EVIDENCED **at contract level** | Backend does not derive sequence from an authoritative server-side source in tested code |
| Tally inflation via revote | Previous tally decremented, new tally incremented | `EVotingBallotBox_revoting.test.js::revote decrements prev tally and increments new` | EVIDENCED **at contract level** | - |
| Distinct-voter inflation via revote | `distinctVoters` increments only on a first ballot | `EVotingBallotBox_revoting.test.js::distinctVoters unchanged on revote` | EVIDENCED **at contract level** | - |
| Over-voting beyond the roll | Eligible-voter cap in contract | `EVotingBallotBox.test.js::eligible cap` | EVIDENCED **at contract level** | **Gap:** no test proves a voter outside the roll is rejected by the backend |
| Rogue relayer | `onlyRelayer` modifier | `EVotingBallotBox.test.js::only relayer can cast` | EVIDENCED | **Gap:** detection of a *malicious* (not unauthorised) relayer is not implemented; reconciliation is minimal |
| Election timing abuse | Contract enforces `start <= block.timestamp <= end` | Contract code present | **CODE ONLY** - no timing test found in either contract suite | **Gap:** no contract test covers voting before open / after close |
| Cancelled election acceptance | Contract rejects when `cancelled` | Contract code present | **CODE ONLY** - no test found | **Gap:** no test for `cancelElection` behaviour |
| Tampering with published election parameters | Immutable parameters after creation (design) | Contract fields are not mutated after `createElection` | CODE ONLY | No test asserts immutability |

## F. Privacy and correlation threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Voter identity on the blockchain | Ballot plane carries only an HMAC pseudonym | `backend/tests/test_privacy.py::test_ballot_has_no_identity_fields` (asserts `user_id`, `usn`, `email`, `wallet_address`, `session_id`, `face_id` absent) | EVIDENCED (model level) | **Gap:** the assertion checks column *names*, not whether values leak through another column |
| Cross-plane linkage via foreign key | No cross-plane FKs in the ORM models | `backend/tests/test_models.py::test_ballot_plane_separation` | PARTIAL | The test only checks that one model lacks `voter_id`; it does not enumerate FKs across all plane-paired tables. Note `voting_authorizations.user_id -> users.id` is an intentional identity-context link |
| Pseudonym cross-election correlation | Election-specific HMAC derivation | `test_privacy.py::test_pseudonyms_election_specific`, `test_voting.py::test_pseudonym_diff_election`, `test_pseudonym_diff_user` | EVIDENCED | Deterministic per (voter, election) by design, so a *global* observer holding the key could correlate |
| Pseudonym disclosure to the voter | Pseudonym never returned by the API | `test_privacy.py::test_pseudonym_not_returned_to_frontend` | PARTIAL - the test only asserts a `401` for an unauthenticated request; it does not assert absence of a pseudonym in an authenticated response |
| Receipt used as proof of vote choice | Minimal receipt content (election title, voter ID last 4, minute-level time, HMAC code) | `backend/tests/test_revoting.py::test_receipt_no_candidate` | PARTIAL | The test asserts the word `candidate` is absent from one unauthenticated error body - it does not inspect an actual receipt payload |
| Secret leakage into the audit log | Audit sanitisation of passwords, OTPs, keys, tokens, candidate choices, pseudonyms | `test_audit.py::test_audit_event_sanitizes_sensitive_data`, `::test_audit_does_not_log_sensitive_secrets` | EVIDENCED | - |
| Biometric data leakage | Frames deleted; embeddings protected | `backend/app/security/face.py` | CODE ONLY | No test |
| Metadata leakage (timing, ordering) | Shuffled batching in the relayer | `backend/app/relayer/relayer.py` (`random.shuffle`, `batch_size`) | CODE ONLY | **Gap:** no test asserts shuffling occurs or that batch bounds are respected |
| Root / backend operator during the election | Documented trust boundary - privacy does **not** hold | Baseline docs (`PROJECT_MASTER_REPORT.md` Section 8; `PROJECT_BIBLE.md` Section 10) | **DOCUMENTED LIMITATION** | Structurally unmitigated inside this trust model |

## G. Platform and API threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Unauthorised API access | Authentication gating on state-changing endpoints | `test_voting.py` (3 gating tests), `test_face_validation.py` (4 gating tests) | EVIDENCED for voting + face | No gating test for registration, wallet or roll-import endpoints |
| Information disclosure via errors | Generic 404/500 handlers | `backend/tests/test_app.py::test_404_handler` | PARTIAL | No test asserts that 500 responses never leak stack traces or DB details |
| SQL injection | SQLAlchemy parameterised queries | `backend/app/services/*` | PARTIAL | No negative/injection test exists |
| XSS | React escaping by default | `frontend/src/*.jsx` | PARTIAL | No frontend security test exists |
| CSRF | SameSite=Strict cookies | `backend/app/config/config.py` | CODE ONLY | **Gap:** no CSRF token implementation. STRONG/Milestone B scope, not complete |
| CSP / security headers | Design baseline | Not found | **DESIGN ONLY** | Phase 13 |
| MITM | Local TLS via mkcert assumed | Baseline docs | **DESIGN ONLY** | No TLS configuration exists in-repo |
| DoS | Rate limiting | Not found | **DESIGN ONLY** | Phase 13 |
| Malicious insider (DB editor) | Separation, hash-chained audit, reconciliation | `test_audit.py::test_audit_chain_integrity` | PARTIAL | Detects audit tampering; does not detect direct result-table edits |

## H. Recovery, reconciliation and lifecycle threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Duplicate transaction after crash | Write-ahead intent, idempotency, reconciliation | `backend/app/models/reconciliation.py`, `backend/app/services/recovery.py` | CODE ONLY | **Gap:** `test_recovery.py::test_recovery_idempotent` asserts only that `RecoveryService.is_idempotent_ok()` returns `True` - a tautological test that exercises no recovery logic |
| Pending / stale transaction misread as failed | `reconcile_required` state | `backend/app/services/recovery.py` | CODE ONLY | **Gap:** `test_recovery.py::test_reconcile_required_state_safe` asserts only that the string `reconcile_required` is absent from one unauthenticated error body |
| Tally mismatch DB vs. chain | Reconciliation compare | `backend/app/services/recovery.py` | **NOT EVIDENCED** | No tally comparison implementation or test was found. Phase 10 evidence is documentation-level only |
| Distinct-voter mismatch DB vs. chain | Reconciliation compare | Not found | **NOT EVIDENCED** | Not implemented in the backend |
| Sequence mismatch DB vs. chain | Reconciliation compare | Not found | **NOT EVIDENCED** | Not implemented in the backend |
| Audit hash-chain mismatch | Hash chaining with `previous_hash` / `current_hash` | `test_audit.py::test_audit_chain_integrity`, `::test_audit_chain_first_event_no_previous_hash` | EVIDENCED (in-process) | Chain is not persisted-verified against a database reload in tests |
| Audit anchor mismatch | On-chain `AuditAnchored` event | Contract function `anchorAudit` exists | **DESIGN ONLY** | **Gap:** no backend anchoring path and no anchor reconciliation exist. Phase 12 |
| Election closed with pending ballots | Closing cut-off and reconciliation before finalisation | Not found | **NOT EVIDENCED** | Not implemented |
| Reconciliation schema drift | ORM model for `reconciliation_issues` | `backend/app/models/reconciliation.py` | **DEFECT** | **Gap:** `backend/app/schema.sql` contains **no** `CREATE TABLE reconciliation_issues`. Recorded, not fixed during Phase 0 remediation |
| Duplicate `ballots` table definition | Single authoritative DDL | `backend/app/schema.sql` | **DEFECT** | **Gap:** `ballots` is declared twice with different columns (`CREATE TABLE IF NOT EXISTS`), so a fresh build applies only the Phase 1 variant, which has **no `pseudonym` and no `candidate` column**. Recorded, not fixed during Phase 0 remediation |

## I. Administrative threats

| Threat | Control | Test / Evidence | Result | Remaining limitation |
|---|---|---|---|---|
| Administrative abuse | RBAC (Officer / read-only Auditor), four-eyes, no self-approval | Design baseline only | **DESIGN ONLY** | Phase 11 NOT STARTED |
| Admin TOTP | Design baseline | Not found | **DESIGN ONLY** | Phase 11 |
| Individual vote viewing by admin | Design prohibition | Not found | **DESIGN ONLY** | Phase 11 |
| Audit deletion by admin | Design prohibition (append-only) | `audit.py` exposes append + verify only | PARTIAL | No authorisation layer around audit access |
| Election lifecycle manipulation | DRAFT -> PENDING_APPROVAL -> SCHEDULED -> OPEN -> CLOSED -> FINALIZED / CANCELLED | Contract has `cancelled` flag only | **DESIGN ONLY** | No lifecycle implementation. Phase 11 |

---

## J. Consolidated view

| Evidence class | Count of register entries |
|---|---|
| EVIDENCED | 12 |
| PARTIAL | 15 |
| CODE ONLY | 9 |
| DESIGN ONLY | 11 |
| NOT EVIDENCED | 6 |
| DEFECT (documented) | 2 |
| FAILING test suite | 1 |

The strongest evidenced controls are the **contract-level tally/sequence/eligibility rules**, the
**password and OTP hashing primitives**, the **audit sanitisation and hash chain**, and
**authentication gating on the voting and face endpoints**.

The weakest areas are **recovery/reconciliation** (documentation-level only), **rate limiting /
CSRF / security headers** (design-only), **biometric effectiveness** (no evaluation), and
**admin controls** (Phase 11, not started).

---

## K. Register maintenance rules

1. Never cite a test that does not exist in this repository.
2. Never upgrade `RESULT` without adding or pointing to concrete evidence.
3. Keep `Remaining limitation` populated even when `RESULT` is EVIDENCED.
4. Items marked DEFECT or FAILING stay in the register until the owning phase fixes them, at
   which point the fix is recorded rather than the entry being deleted.

---

**END OF THREAT MODEL REGISTER**