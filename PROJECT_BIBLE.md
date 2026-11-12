# PROJECT BIBLE - Vote Without Doubt

**Project:** AI & Blockchain-Based Secure E-Voting System for College Elections
**Product Name:** Vote Without Doubt
**Type:** Academic Prototype - NOT a legally binding election system
**Project Root:** . (repository root)
**Master Specification:** [PROJECT_MASTER_REPORT.md](./PROJECT_MASTER_REPORT.md)
**Encoding:** UTF-8

---

## TABLE OF CONTENTS

1. [Project Identity](#1-project-identity)
2. [How To Read This Document](#2-how-to-read-this-document)
3. [Current Phase Status (AUTHORITATIVE)](#3-current-phase-status-authoritative)
4. [Architecture](#4-architecture)
5. [Technology Stack](#5-technology-stack)
6. [Frozen Scope Taxonomy](#6-frozen-scope-taxonomy)
7. [Design Baseline - Security Principles](#7-design-baseline---security-principles)
8. [Design Baseline - Privacy Principles](#8-design-baseline---privacy-principles)
9. [Design Principles](#9-design-principles)
10. [Trust Model](#10-trust-model)
11. [Threat Model](#11-threat-model)
12. [Decisions Log](#12-decisions-log)
13. [Development Environment (Frozen)](#13-development-environment-frozen)
14. [Repository Structure (Actual)](#14-repository-structure-actual)
15. [Security Baseline Implementation Status](#15-security-baseline-implementation-status)
16. [Known Risks](#16-known-risks)
17. [Known Limitations](#17-known-limitations)
18. [Open Decisions](#18-open-decisions)
19. [Testing Requirements](#19-testing-requirements)
20. [Documentation Index](#20-documentation-index)
21. [Maintenance Rules](#21-maintenance-rules)

---

## 1. PROJECT IDENTITY

- **Product Name:** Vote Without Doubt
- **Type:** College E-Voting System (Academic Prototype)
- **Purpose:** Demonstrate secure, privacy-preserving, auditable electronic voting
- **Start Mode:** Clean slate from zero, in the project root only. No migration or copy from any other project.
- **Binding Disclaimer:** This system is an academic prototype. It is **not** a legally binding real-world election system and is not certified for any statutory election use.

---

## 2. HOW TO READ THIS DOCUMENT

This Bible mixes two different kinds of statement. They are labelled explicitly and must not be confused:

| Label | Meaning |
|---|---|
| **DESIGN BASELINE** | A requirement agreed during Phase 0 (or a later phase) as the target design. Stating it here does **not** mean it is implemented. |
| **IMPLEMENTATION STATUS** | What actually exists in the repository right now, verified against files and tests. |

Authoritative current phase status lives in **one place only**: [Section 3](#3-current-phase-status-authoritative). No other section of this document, and no other file, may declare a competing "current phase".

Historical records (per-phase checkpoints and final reports under `docs/`) intentionally describe the project **as it was at the time that phase finished**. Those are historical statements, not current status.

---

## 3. CURRENT PHASE STATUS (AUTHORITATIVE)

**This is the single authoritative source of current phase status for the project.**

Phase 5 carries an independent audit and remediation. The original Phase 5
implementation was found to be a stub and returned **47 FAIL**
(`PHASE 5 AUDIT COMPLETE — FAIL`); it has since been rebuilt against real SCRFD
and ArcFace models. Its current status is **REMEDIATED — PARTIAL**, not
COMPLETE: the pipeline is real and verified end to end, but real-world FAR, FRR,
APCER and BPCER are **NOT YET MEASURED** because no human-face dataset exists in
this repository. See `docs/PHASE5_CHECKPOINT.md` and `docs/PHASE5_EVALUATION.md`.
The Phase 6-10 rows below are the historical record of what those phases claimed
and are not themselves re-audited.

| Phase | Title | Status |
|---|---|---|
| Phase 0 | Project Foundation | **COMPLETE** |
| Phase 1 | Backend + Database Foundation | **COMPLETE** |
| Phase 2 | Authentication Core | **COMPLETE** |
| Phase 3 | College Roll + Registration | **COMPLETE** |
| Phase 4 | MetaMask / Wallet Security | **COMPLETE** |
| Phase 5 | Face + Liveness | **REMEDIATED — PARTIAL** |
| Phase 6 | Blockchain / Smart Contract | **COMPLETE** |
| Phase 7 | Core Voting Pipeline (Milestone A) | **COMPLETE** |
| Phase 8 | Privacy Hardening | **COMPLETE** |
| Phase 9 | Revoting + Coercion Resistance (Milestone B) | **COMPLETE** |
| Phase 10 | Recovery + Reconciliation | **REMEDIATION IMPLEMENTED — READY FOR RE-AUDIT** |
| Phase 11 | Admin + Election Management | NOT STARTED |
| Phase 12 | Public Verification + Results | NOT STARTED |
| Phase 13 | Security Hardening | NOT STARTED |
| Phase 14 | Full Failure + Performance Testing | NOT STARTED |
| Phase 15 | Privacy / Legal / Documentation | NOT STARTED |
| Phase 16 | Final UI + Demo | NOT STARTED |
| Phase 17 | Final Release | NOT STARTED |

**Current phase:** Phase 10 remediation is implemented and prepared for independent security re-audit. Phase 11 has NOT been started.
**Rule:** Do not begin Phase 11 or later until explicitly instructed.

### 3.0 Phase 2 Verification Status (updated 2026-10-04)

Phase 2 was audited independently on 2026-10-04 and returned **PARTIAL**: `AuthService.request_otp`,
`.verify_otp` and `.logout` did not exist, so the OTP and logout endpoints failed with
`AttributeError`, password + OTP could never reach `AUTHORIZED`, no session could be revoked, and
session rotation after OTP verification was absent.

Phase 2 was then remediated and **verified by execution** (not by documentation):

| Evidence | Result |
|---|---|
| `backend/` full suite (`pytest tests/ -q`) | 274 collected, 274 passed, 0 failed, 0 skipped |
| Phase 2 subset (4 Phase 2 modules + `test_auth.py`) | 65 passed |
| `backend/scripts/prove_phase2_auth.py` | 18/18 proof steps |
| `frontend` (`npm test`) | 25 passed |
| Requirements A–T | all PASS on implementation **and** executed evidence |

Full evidence, per-requirement table and remaining limitations:
`docs/PHASE2_REMEDIATION_REPORT.md`. Audit of record: `docs/PHASE2_IMPLEMENTATION_AUDIT.md`.

Note: the original audit asserted that Phase 2 depended on the Phase 3 electoral roll. Re-audit
confirmed **no such dependency** — `auth_service.py`, `routes/auth.py` and `app/security/*` contain
no reference to the roll. Account creation is Phase 3's responsibility; the unsafe Phase 2
`POST /api/auth/register` route, which accepted a caller-supplied `voter_id`, has been removed.

### 3.1 Phase 3 Verification Status (updated 2026-10-04)

Phase 3 was audited independently on 2026-10-04 and returned **PARTIAL**: the authoritative
electoral roll was anonymously writable (`POST /api/admin/roll/import` had no authentication and no
rate limit, so an anonymous caller could add their own USN and register), expired registration
sessions could still complete, email delivery failure was reported as success, the roll had no
integrity mechanism, responses enabled voter enumeration, and `users.voter_id` was not unique.

Phase 3 was then remediated and **verified by execution**:

| Evidence | Result |
|---|---|
| `backend/` full suite (`pytest tests/ -q`) | 342 collected, 342 passed, 0 failed, 0 skipped |
| Phase 3 subset (2 new modules) | 66 passed |
| `backend/scripts/prove_phase3_registration.py` | 21/21 proof steps |
| `frontend` (`npm test`) | 38 passed |
| `flask db upgrade` + `db check` | applied, no schema drift |
| Requirements A–AB | all PASS on implementation **and** executed evidence |

Key Phase 3 additions: `app/security/admin_bootstrap.py` (fail-closed bootstrap authorization for
roll administration, explicitly **not** Phase 11 RBAC), `electoral_roll_imports` with a canonical
order-independent SHA-256 roll digest plus dry-run/apply/verify endpoints, persisted
`registration_sessions.otp_purpose`, and a database-level unique constraint on `users.voter_id`.

Full evidence, per-requirement table and remaining limitations:
`docs/PHASE3_REMEDIATION_REPORT.md`.

### 3.2 Phase 4 Verification Status (updated 2026-10-04)

Phase 4 was audited independently on 2026-10-04 and returned **FAIL**: `eth_account` was neither
installed nor declared, so `verify_signature()` always returned `(False, None)` and no wallet could
ever be bound — and the failure was silent. The signed message also lacked the election identifier
and any contract address, the chain ID was never validated against the wallet's real network, and
there were no integration or frontend wallet tests.

Phase 4 was then remediated and **verified by real cryptographic execution**:

| Evidence | Result |
|---|---|
| `backend/` full suite (`pytest tests/ -q`) | 409 collected, 409 passed, 0 failed, 0 skipped, 0 xfailed |
| Phase 4 subset | 70 passed, using real `eth-account` recovery (never mocked) |
| `backend/scripts/prove_phase4_wallet.py` | 26/26 proof steps |
| `frontend` (`npm test`) | 60 passed |
| `flask db upgrade` + `db check` | applied, no schema drift |
| Requirements A–AG | all PASS on implementation **and** executed evidence |

Key Phase 4 facts: MetaMask `personal_sign` compatibility is preserved and verified with
`encode_defunct` + `Account.recover_message`; the challenge message binds domain, purpose, voter id,
election id, chain id, contract context, nonce, issued-at and expires-at, and never contains vote
data; each challenge is bound to the user, the server-side session and the purpose, is single-use,
expires after 10 minutes and burns after 5 invalid attempts. `eth-account==0.13.7` is pinned and
production refuses to boot without working Ethereum verification.

Full evidence, per-requirement table and remaining limitations:
`docs/PHASE4_REMEDIATION_REPORT.md`.

### 3.3 Phase 6 Verification Status (updated 2026-10-05)

Phase 6 was audited independently on 2026-10-05 against a real local Ganache node and returned **FAIL**:
the Solidity smart contract (EVotingBallotBox.sol) allowed revoting by accepting advancing sequence numbers and adjusting tallies (Phase 9 revoting logic had leaked into Phase 6), audit anchoring was event-only with no authoritative state stored on chain or queryable via view function, and the backend relayer (relayer.py) was a stub that fabricated fake transaction hashes (0xstub) and block numbers (0).

Phase 6 was remediated and **verified by real Ganache execution**:

| Evidence | Result |
|---|---|
| Hardhat contract test suite (npm test in blockchain/) | 9 passing, 0 failing |
| Real Ganache proof (backend/scripts/prove_phase6_blockchain.py) | 119/119 assertions held against real Ganache (chainId 1337) |
| Backend relayer test suite (pytest tests/test_relayer.py) | 8 passing (cryptographic shuffle, fail-closed behavior, live Ganache processing) |
| backend/ full suite (pytest tests/ -q) | 550 collected, 550 passed, 0 failed |
| frontend (npm test) | 103 passed |
| Frontend production build (npm run build) | Vite build clean (0 errors) |

Key Phase 6 remediation outcomes:
- One counted ballot per pseudonym is strictly enforced. Revoting is strictly deferred to Phase 9.
- Authoritative on-chain audit anchoring implemented via auditAnchors, auditAnchorBlocks, auditAnchorCount and directly queryable via getAuditAnchor(uint256).
- Backend relayer implemented with cryptographic queue shuffling (secrets.SystemRandom().shuffle), live Web3 JSON-RPC broadcast, and authentic transaction receipt verification (QUEUED -> SUBMITTED -> CONFIRMED -> FINALIZED).
- Blank/zero pseudonyms rejected (INVALID_PSEUDONYM) and redundant relayer rotation rejected (RELAYER_UNCHANGED).

Full evidence and per-finding documentation: docs/PHASE6_REMEDIATION_REPORT.md.

### 3.4 Phase 7 Verification Status (updated 2026-10-05)

Phase 7 was audited independently on 2026-10-05 and returned **FAIL** due to 10 findings: factor bypass in `/voting/mark-factors`, disconnected relayer pipeline and fake finalization, status endpoint SQL model crash, revoting logic leakage from Phase 9, voting component missing from `App.jsx`, hollow tests, premature receipts, missing candidate/election validation, missing rate limits/audit logging, and a missing unique constraint on `(election_id, pseudonym)`.

Phase 7 was remediated and **verified by real Ganache execution**:

| Evidence | Result |
|---|---|
| Real Ganache proof (`backend/scripts/prove_phase7_voting.py`) | 19/19 checks passed against real Ganache (Chain ID 1337) |
| Backend Phase 7 integration suite (`pytest tests/test_voting.py`) | 21 passed, 0 failed |
| `backend/` full suite (`pytest tests/ -q`) | 565 collected, 565 passed, 0 failed |
| Frontend Phase 7 flow tests (`frontend/tests/votingFlow.test.mjs`) | 16 passed, 0 failed |
| `frontend` full suite (`npm test`) | 119 passed, 0 failed |
| Frontend production build (`npm run build`) | Clean Vite production build (0 errors) |
| Hardhat contract suite (`npx hardhat test`) | 9 passed, 0 failed |
| Phase 6 real Ganache proof (`prove_phase6_blockchain.py`) | 119/119 assertions held (Phase 6 remains PASS) |
| Database migration & schema check (`test_database.py`) | 13 passed, 0 schema drift (`flask db check` clean) |

Key Phase 7 remediation outcomes:
- Multi-factor authorization enforces server-authoritative Phase 4 wallet and Phase 5 face liveness verification. Client factor assertions are rejected. Session binding is strictly enforced.
- Real Phase 6 Relayer executes cryptographic queue shuffling and broadcasts transactions to Ganache. State transitions to `FINALIZED` only upon mined receipt confirmation (`status == 1`). Reverted transactions transition to `FAILED` and never finalize.
- Status endpoint crash resolved (`BallotRecord.id.desc()`) and authoritative across all lifecycle states.
- Revoting strictly prohibited: Phase 6 boundary (`sequence == 1`) enforced; duplicates rejected with 409 `BALLOT_ALREADY_CAST`.
- Frontend fully integrated: `Voting.jsx` rendered in `App.jsx`, dynamic candidates loaded, live status polling, and receipt displayed only after finalization.
- Section 8.6 HMAC receipt issued only on `FINALIZED`, preserving privacy (no candidate, pseudonym, or wallet leaked).

Full evidence and per-finding documentation: `docs/PHASE7_REMEDIATION_REPORT.md`.

### 3.5 Phase 8 Verification Status (updated 2026-10-05)

Phase 8 was remediated and verified:
- Per-election pseudonym keys with Fernet envelope encryption at rest (`PSEUDONYM_MASTER_KEY`).
- Irreversible key destruction upon election finalization (`[DESTROYED]` sentinels).
- Asynchronous relayer with cryptographic queue shuffling (`secrets.SystemRandom().shuffle`).
- Strict privacy preservation: submit/status/receipt responses never leak tx_hash, candidate, or pseudonym.
- Verified by live Ganache execution: `prove_phase8_privacy.py` (30/30 passed).

### 3.6 Phase 9 Verification Status (updated 2026-10-05)

Phase 9 was remediated and verified:
- Controlled revoting with sequence `1 -> 2 -> 3`, maximum 3 ballots enforced.
- Latest-vote-wins semantics and null revote coercion mitigation on chain.
- 120-second server-side cooldown and fresh MFA per revote.
- Verified by live Ganache execution: `prove_phase9_revoting.py` (28/28 passed).

### 3.7 Phase 10 Verification Status (updated 2026-10-06)

Phase 10 was audited independently on 2026-10-06 and returned **FAIL** due to incomplete recovery of interrupted transactions and hollow tests.

Phase 10 was then remediated and **verified by real Ganache execution**:

| Evidence | Result |
|---|---|
| Real Ganache proof (`backend/scripts/prove_phase10_recovery.py`) | 48/48 checks passed across all 13 test scenarios on live Ganache (Chain ID 1337) |
| Backend Phase 10 unit/integration suite (`pytest tests/test_recovery.py`) | 11 passed, 0 failed |
| Backend full suite (`pytest tests/`) | 599 collected, 599 passed, 0 failed |
| Frontend suite (`npm test` in frontend/) | 119 passed, 0 failed |
| Hardhat contract suite (`npx hardhat test`) | 14 passed, 0 failed |
| Phase 6 live Ganache proof (`prove_phase6_blockchain.py`) | 119/119 assertions held (Phase 6 preserved) |
| Phase 7 live Ganache proof (`prove_phase7_voting.py`) | 20/20 checks passed (Phase 7 preserved) |
| Phase 8 live Ganache proof (`prove_phase8_privacy.py`) | 30/30 checks passed (Phase 8 preserved) |
| Phase 9 live Ganache proof (`prove_phase9_revoting.py`) | 28/28 checks passed (Phase 9 preserved) |
| Database migration & schema check (`test_database.py`) | 13 passed, 0 schema drift (`flask db check` clean) |

Key Phase 10 remediation outcomes:
- **Crash Recovery**: `SUBMITTED` ballots are recovered across crash and restart boundaries. Mined receipts (`status == 1`) finalize to `CONFIRMED` / `FINALIZED`; reverted receipts (`status == 0`) transition to `FAILED` with `TX_REVERTED`; unbroadcast ballots (`tx_hash == NULL`) are safely requeued to `QUEUED` with incremented retry count.
- **Pending Safety**: Unmined / mempool transactions are kept recoverable in `SUBMITTED` (`TX_PENDING`) and never falsely finalized or prematurely dropped.
- **Genuine Idempotency**: Dual-pass stability verified (`is_idempotent_ok()` genuinely proves pass 2 produces 0 mutations).
- **Reconciliation Engine**: `ReconciliationService` performs real-time bidirectional auditing of candidate tallies, distinct active voter counts, and per-voter sequence consistency against `EVotingBallotBox.sol`. Discrepancies are logged as `ReconciliationIssue` records with deduplication and audit event emissions.
- **Relayer Concurrency Protection**: Atomic DB row updates prevent multi-worker duplicate transaction submissions.
- **Preserved Boundaries**: Phase 6, 7, 8, and 9 invariants are 100% preserved.

Full evidence and per-finding documentation: `docs/PHASE10_REMEDIATION_REPORT.md`.

### 3.8 Completion Means

A phase marked COMPLETE means phase deliverables and their phase documents exist. It does **not** by itself certify that every control in [Section 7](#7-design-baseline---security-principles) is fully implemented and independently verified. Evidence strength is recorded per item in [Section 15](#15-security-baseline-implementation-status) and in [docs/THREAT_MODEL_REGISTER.md](./docs/THREAT_MODEL_REGISTER.md).

### 3.9 Known Evidence Caveats

Recorded honestly as of Phase 10 remediation:

- `backend/tests/test_face_api.py` failed at collection (6 errors, missing `client` fixture), so the face HTTP surface had **no passing test evidence**. **RESOLVED during Phase 5 remediation:** that file and `test_face_validation.py` were deleted and replaced by `test_phase5_face_engine.py` (26), `test_phase5_face_security.py` (78) and `test_phase5_evaluation.py` (27).
- `backend/tests/test_recovery.py` and `backend/tests/test_revoting.py` previously contained only weak/structural assertions. **RESOLVED during Phase 9 & Phase 10 remediations:** both suites have been completely replaced with real, substantive assertions and live Ganache proof scripts (`prove_phase9_revoting.py` with 28 checks and `prove_phase10_recovery.py` with 48 checks).

---

## 4. ARCHITECTURE

### 4.1 Target Architecture

```
React + Vite (Frontend)
    |
Flask Backend (Python) - modular monolith
    |
MySQL 8 Database (IDENTITY plane + BALLOT plane)
    |
Relayer worker  +  Reconciler
    |
Ganache (Blockchain, chain ID 1337)
    |
Solidity 0.8.19 via Hardhat (EVotingBallotBox)
```

Subsystems: face recognition + challenge liveness, SMTP/Mailpit email, hash-chained audit log with on-chain anchoring, reconciliation, admin management, public verifier.

### 4.2 Two Data Planes

**IDENTITY PLANE** - voter identity, electoral roll, registration, authentication, eligibility, participation.

**BALLOT PLANE** - pseudonymous voter identifiers, ballot records, candidate selection, ballot sequence, blockchain submission state.

**DESIGN BASELINE - separation constraint:** No direct linking between the planes via foreign keys, shared rows, shared ordering, or candidate-bearing identity records. A controlled server-side bridge is permitted only where operationally necessary, and must never create a durable voter -> pseudonym -> candidate mapping.

### 4.3 Core Architectural Constraints (DESIGN BASELINE)

1. **Two data planes**, strictly separated.
2. **No direct cross-linking** between planes.
3. **Pseudonymous on-chain data only** - HMAC-SHA256 pseudonyms plus non-identifying ballot data.
4. **Signature separation** - MetaMask signs a challenge, never a vote or candidate selection.
5. **Controlled bridge** - cross-plane linkage only via controlled server-side logic when necessary.
6. **Exactly-once semantics** - durable transaction intent persisted before broadcast, plus idempotency and reconciliation.
7. **Uncertainty is never guessed** - when the database and chain cannot be reconciled safely, the state is `RECONCILE_REQUIRED`, never silently overwritten.

---

## 5. TECHNOLOGY STACK

| Layer | Technology | Implementation status |
|---|---|---|
| Frontend | React + Vite | Present (`frontend/`) |
| Backend | Python + Flask (modular monolith) | Present (`backend/`) |
| Database | MySQL 8 | Configured (`backend/app/schema.sql`, `.env.example`) |
| Blockchain | Ganache (chain ID 1337) | Configured (`blockchain/hardhat.config.js`) |
| Smart contracts | Solidity 0.8.19 | Present (`blockchain/contracts/EVotingBallotBox.sol`) |
| Contract development | Hardhat | Present (`blockchain/`) |
| Face recognition | ArcFace / InsightFace preferred; face_recognition / dlib fallback | **InsightFace integrated and exercised** — SCRFD `det_10g` detection, five-point landmarks, ArcFace `w600k_r50` 512-d embeddings, cosine matching, explicit pre-provisioned weights (no runtime download). Accuracy on real people **NOT YET MEASURED** |
| Email (dev) | SMTP / Mailpit | Present (`backend/app/email/service.py`) |

---

## 6. FROZEN SCOPE TAXONOMY

The scope is frozen into five categories. Full lists live in
[PROJECT_MASTER_REPORT.md Section 35 (Out-of-Scope) and Section 36 (Future Work)](./PROJECT_MASTER_REPORT.md);
the authoritative category definitions are in `PROJECT_MASTER_REPORT.md` "Scope Taxonomy" and are
summarised here.

| Category | Meaning | Phase mapping |
|---|---|---|
| **CORE / Milestone A** | The minimum demonstrable secure-voting capability. First working end-to-end milestone. | Phases 1-7 |
| **STRONG / Milestone B** | Hardening that materially improves security, privacy and verifiability beyond Milestone A. | Phases 8-10 |
| **OPTIONAL** | Architecture-defined optional capabilities. Not required for a Milestone A or B demonstration. | As defined in the master report |
| **FUTURE** | Advanced research-grade cryptography and deployment targets explicitly deferred beyond the prototype. | Post-prototype |
| **DO NOT BUILD** | Explicitly excluded. Will not be built in this project at any phase. | Never |

### 6.1 CORE / Milestone A

CSV roll import; registration roll check; email OTP; password authentication; wallet binding;
face + liveness; login; server-side sessions; election/candidate/time smart contract;
one counted ballot per pseudonym; eligible-voter cap; tally; pseudonymous ballots; relayer;
privacy-preserving receipt; hash-chained audit; basic admin; reconciliation;
unit / integration / negative tests; scripted attack demonstration.

### 6.2 STRONG / Milestone B

Revoting cap 3; shuffled batching; vote-cast email notification; startup recovery / stale
transaction handling; on-chain audit anchors; closing audit plus pseudonym-key destruction;
public verifier; face FAR/FRR/APCER evaluation; admin TOTP; CSRF/CSP/security headers;
privacy / consent / terms; Slither plus coverage; OWASP ZAP baseline; failure injection.

### 6.3 OPTIONAL

Architecture-defined optional capabilities only, as listed in the master report scope taxonomy
(for example: optional notification email, optional null revote, optional performance testing).

### 6.4 FUTURE

Blind signatures, JCJ (Jonkers-Crypto-Jakobsson) voting, zero-knowledge proofs, threshold keys,
HSM/KMS, WebAuthn, cast-as-intended verification, sealed tally, public testnet deployment.

### 6.5 DO NOT BUILD

Kubernetes; microservices; AI agents; custom ML; mixnets; keyless ballot box; commit-reveal;
mobile application; cloud autoscaling; custom blockchain.

**Scope freeze:** Frozen. Changes only with explicit user instruction and a documented architectural justification.

---

## 7. DESIGN BASELINE - SECURITY PRINCIPLES

These are **requirements**, not claims of implementation. Actual status is in
[Section 15](#15-security-baseline-implementation-status).

1. **Argon2id** password hashing; never plaintext.
2. **Secure server-side sessions** - HttpOnly, Secure, SameSite=Strict, `__Host-` prefix where applicable, rotation after OTP, idle and absolute timeouts, one active session per voter.
3. **Email OTP** - 6-digit cryptographically secure value, HMAC-SHA256 with server-side pepper, short expiry, attempt cap, resend cooldown, single-use, purpose-bound and session-bound.
4. **Wallet challenge signing** - single-use nonce, domain separation (chain ID, contract, election, purpose), expiry, exact-message reconstruction and verification, replay-resistant.
5. **Face/liveness protection** - frames deleted immediately after processing; embeddings encrypted at rest; no unnecessary biometric retention.
6. **Audit hash chain** - append-only, hash-chained, tamper-detectable, with on-chain anchoring.
7. **RBAC and four-eyes** - Election Officer and read-only Auditor; minimum two officers for sensitive actions; no self-approval; no individual vote viewing; no audit deletion.
8. **CSRF / CORS / input validation** on all state-changing endpoints.
9. **SQL injection and XSS defences** - parameterised queries, output encoding, safe headers.
10. **Rate limiting** on authentication, OTP and resend paths.
11. **Reconciliation** - mismatch detection and visibility, never silent correction.
12. **Authorization consumption** - voting authorization factors are consumed after use and cannot be replayed.
13. **Secrets management** - no secrets in source control; environment variables only; `.env.example` holds placeholders.
14. **TLS** - local TLS via mkcert assumed for realistic local deployment.
15. **Database least privilege** - application DB user restricted to the application schema.
16. **Dependency security awareness** - pinned dependency manifests; security tooling planned (Phase 13).

---

## 8. DESIGN BASELINE - PRIVACY PRINCIPLES

1. **Strict identity/ballot separation** - two planes, no direct linkage.
2. **No voter identity on the blockchain** - pseudonymous entries only.
3. **Election-specific pseudonyms** - domain-separated HMAC derivation, keys destroyed after finalization.
4. **Pseudonymous is NOT perfectly anonymous** - this limitation must always be stated.
5. **Candidate never in a wallet signature.**
6. **Privacy-preserving receipts** - election title, voter ID last 4, minute-level time, HMAC receipt code only.
7. **No unnecessary candidate leakage** - candidate must not appear in receipts, logs, status APIs, notifications, audit UI or public verification.
8. **Trusted-backend limitation** - privacy does not hold against root/backend operator access during an election.
9. **Biometric limitations** - documented risk from deepfakes and virtual cameras.

---

## 9. DESIGN PRINCIPLES

1. Security > Privacy > Integrity > Recoverability > Auditability > Usability > Visual Polish.
2. Security, accessibility and usability first in the UI.
3. Neo-brutalist aesthetic: hard edges, thick borders, high contrast.
4. No excessive motion during sensitive flows (face scan, OTP, wallet signing, voting, confirmation).
5. Defence in depth; fail safe; detect malicious behaviour rather than assume good faith.
6. Document limitations explicitly - never overstate guarantees.
7. Academic honesty about trust boundaries.

---

## 10. TRUST MODEL

**Privacy holds against (DESIGN BASELINE):**
- Database-only attacker
- Blockchain observer
- Normal administrator without root/shell access
- Coercer without device control
- Attacker possessing one stolen credential

**Privacy does NOT fully hold against:**
- Root/backend operator with access during the election

**Integrity resists (DESIGN BASELINE):**
- Students
- Ordinary database modification
- Ordinary administrative abuse

**Integrity limitation:**
- A malicious relayer cannot be fully prevented; its behaviour must be *detectable* via reconciliation and audit anchoring.

---

## 11. THREAT MODEL

Threat classes tracked by this project:

- **Identity:** malicious registration, duplicate registration, impersonation, identity takeover
- **Authentication:** stolen credentials, stolen sessions, OTP replay, wallet replay
- **Biometric:** face spoofing, face replay, deepfakes, virtual cameras
- **Voting:** double voting, ballot tampering, voter-ballot correlation, coercion, vote buying, receipt abuse
- **Platform:** modified frontend, direct API manipulation, MITM, DoS, malicious insider
- **Blockchain / Relayer:** rogue relayer, transaction replay, event manipulation, election manipulation
- **Lifecycle:** closing and finalisation abuse, revote-cap griefing

**Tracking format:** THREAT -> CONTROL -> TEST/EVIDENCE -> RESULT -> REMAINING LIMITATION.

**Concrete register:** [docs/THREAT_MODEL_REGISTER.md](./docs/THREAT_MODEL_REGISTER.md)
This register never claims a test exists unless the test actually exists in the repository.

---

## 12. DECISIONS LOG

Historical architectural decisions are preserved verbatim in intent.

| Decision | Rationale | Status |
|---|---|---|
| Start from zero in the project root only | Clean slate; no migration or copy from prior work | DECIDED (Phase 0) |
| Two-plane identity/ballot separation | Minimise voter-ballot correlation | DECIDED (Phase 0) |
| Pseudonyms via HMAC-SHA256 (per-election key, domain separated) | Non-identifying on-chain data | DECIDED (Phase 0) |
| MetaMask signs a challenge only, never the vote | Prevent candidate leakage | DECIDED (Phase 0) |
| Challenge-based liveness (LEFT/RIGHT, ~10-24 frames, ~20s TTL) | Mitigate basic spoof/replay | DECIDED (Phase 0) |
| Privacy-preserving minimal receipts | Prevent receipt-based proof of choice | DECIDED (Phase 0) |
| Hash-chained audit plus on-chain anchoring | Tamper-evident auditability | DECIDED (Phase 0) |
| Max 3 ballots, full re-auth per revote, cooldown | Coercion mitigation balance | DECIDED (Phase 0) / implemented Phase 9 |
| Neo-brutalist UI, security first | Clarity, minimal distraction in critical flows | DECIDED (Phase 0) |
| Ganache chain ID 1337, Solidity 0.8.19, Hardhat | Local academic stack | DECIDED (Phase 0) |
| ArcFace/InsightFace preferred; face_recognition/dlib fallback | Practical flexibility | DECIDED (Phase 0) |
| Blockchain directory named `blockchain/` (contracts live in `blockchain/contracts/`) | Matches actual repository layout | DECIDED (Phase 0 remediation) |
| Git initialised locally with no remote | Repository integrity and history without publishing | DECIDED (Phase 0 remediation) |

---

## 13. DEVELOPMENT ENVIRONMENT (FROZEN)

### 13.1 Required Floors

| Component | Requirement |
|---|---|
| Python | **3.11+** |
| MySQL | **8.0** |
| Node.js | **20+** |
| Solidity | **0.8.19** (pinned in `blockchain/hardhat.config.js`) |
| Contract framework | **Hardhat** |
| Local chain | **Ganache**, chain ID **1337** |
| Frontend | **React + Vite** |
| Local TLS | **mkcert** (assumed available for realistic local HTTPS) |
| Browser | Desktop **Chrome / Edge / Firefox** |
| Hardware | **Webcam** required for face/liveness |
| Wallet | **MetaMask desktop extension** |
| Mobile | **Mobile MetaMask is out of scope** |

### 13.2 Verified Local Environment

Recorded for traceability only. A newer version does not lower the floor above.

| Component | Verified version |
|---|---|
| Python | 3.11.9 |
| Node.js | v24.19.0 (satisfies the 20+ floor) |
| npm | 11.17.0 |
| Git | 2.55.0.windows.3 |

### 13.3 Local Services

- MySQL 8 on `localhost:3306`, database `voting_sys`, least-privilege user `voting_sys_user`.
- Ganache on `127.0.0.1:8545`, chain ID 1337.
- Mailpit / SMTP on `localhost:1025` for development email.
- Flask backend on `localhost:5000`.
- Vite dev server on `localhost:5173`.

Setup detail: [docs/DEV_SETUP.md](./docs/DEV_SETUP.md), [docs/DATABASE_SETUP.md](./docs/DATABASE_SETUP.md).
Environment variables: `backend/.env.example` (placeholders only; never commit a real `.env`).

---

## 14. REPOSITORY STRUCTURE (ACTUAL)

```
voting-sys/
|-- README.md                     # project entry point
|-- PROJECT_MASTER_REPORT.md      # authoritative specification
|-- PROJECT_BIBLE.md              # this file - living engineering source of truth
|-- .gitignore
|-- backend/
|   |-- app/
|   |   |-- __init__.py           # app factory + blueprints
|   |   |-- extensions.py
|   |   |-- schema.sql            # MySQL schema (both planes + audit)
|   |   |-- config/               # environment-based configuration
|   |   |-- models/               # SQLAlchemy models (identity / ballot / audit)
|   |   |-- routes/               # HTTP blueprints
|   |   |-- services/             # business logic
|   |   |-- security/             # password, otp, sessions, wallet, face, pseudonym
|   |   |-- audit/                # hash-chained audit
|   |   |-- relayer/              # relayer worker
|   |   |-- email/                # SMTP / Mailpit delivery
|   |   `-- utils/                # CSV roll import
|   |-- tests/                    # pytest suite
|   |-- requirements.txt
|   |-- run.py
|   |-- .env.example
|   `-- README.md
|-- frontend/
|   |-- src/                      # React components (Auth, Registration, Wallet, Face, Voting)
|   |-- package.json
|   |-- vite.config.js
|   `-- README.md
|-- blockchain/
|   |-- contracts/EVotingBallotBox.sol
|   |-- test/                     # Hardhat tests
|   |-- scripts/                  # deploy.js, relayer.js
|   |-- hardhat.config.js
|   `-- package.json
|-- docs/                         # phase documents, setup guides, threat register
`-- scripts/                      # verify_foundation.ps1
```

Note the correct paths: the Solidity sources are in **`blockchain/contracts/`**. There is no
top-level `contracts/` directory.

---

## 15. SECURITY BASELINE IMPLEMENTATION STATUS

Status legend: **IMPLEMENTED** = code exists and is exercised by at least one repository test.
**PARTIAL** = code exists but coverage or enforcement is incomplete.
**DESIGN ONLY** = specified, not implemented.

| Control | Implementation status | Evidence |
|---|---|---|
| Argon2id password hashing | IMPLEMENTED | `backend/app/security/password.py`; `backend/tests/test_auth.py` |
| Secure sessions (HttpOnly/SameSite/rotation) | PARTIAL | `backend/app/config/config.py`, `backend/app/security/sessions.py`; `SESSION_COOKIE_SECURE = False` in config |
| Email OTP + pepper, expiry, attempts, single-use | IMPLEMENTED | `backend/app/security/otp.py`; `test_auth.py` (4 OTP tests) |
| Wallet nonce + domain separation | IMPLEMENTED | `backend/app/security/wallet.py`; `test_wallet.py::test_message_contains_nonce_and_no_candidate` |
| Face frame deletion / embedding protection | IMPLEMENTED (2026-10-05) | `backend/app/security/face.py`, `backend/app/services/face_service.py`; versioned Fernet envelope with key rotation, fail-closed on wrong key/tamper, frames never persisted; `test_phase5_face_security.py` (78 tests, real model stack) |
| Face challenge integrity (randomised order, session binding, MAC, single use) | IMPLEMENTED (2026-10-05) | `backend/app/services/face_service.py`, `app/security/face.py`; replay, cross-session and stored-sequence-tamper rejection asserted |
| Face liveness (server-derived LEFT/RIGHT order) | IMPLEMENTED (2026-10-05) | Reversed order, static pose, held turn and constant-direction poses rejected; client cannot assert the sequence |
| Real-world face accuracy (FAR/FRR/APCER/BPCER) | **NOT YET MEASURED** | No approved human-face dataset in this repository; see `docs/PHASE5_EVALUATION.md`. Must not be treated as PASS |
| Hash-chained audit | IMPLEMENTED | `backend/app/audit/audit.py`; `test_audit.py` (6 tests) |
| On-chain audit anchoring | DESIGN ONLY | contract `anchorAudit` exists; no backend anchoring path evidenced |
| RBAC / four-eyes admin | DESIGN ONLY | Phase 11 not started |
| CSRF / CSP / security headers | DESIGN ONLY | Phase 9/13 scope |
| Rate limiting | PARTIAL | Face endpoints have real per-identity budgets (`FACE_RATE_LIMIT_*`, enforced in `backend/app/routes/face.py`); no limiter for the remaining endpoints |
| SQLi / XSS defences | PARTIAL | SQLAlchemy parameterisation; no dedicated tests |
| Reconciliation | PARTIAL | `backend/app/services/recovery.py` is minimal; weak tests |
| Authorization consumption | PARTIAL | consumed in `voting_service.py`; not covered by an explicit test |
| Secrets management | IMPLEMENTED | `.gitignore` + `.env.example`; no committed secrets |
| TLS | DESIGN ONLY | mkcert assumed, not configured in-repo |
| DB least privilege | PARTIAL | documented in `docs/DATABASE_SETUP.md`, not enforced by tooling |
| Dependency security | PARTIAL | pinned manifests; `pip-audit` / `npm audit` not yet run |

---

## 16. KNOWN RISKS

| Risk | Impact | Mitigation (planned / present) |
|---|---|---|
| Face deepfakes / virtual cameras | Medium-High | Challenge-based liveness with server-derived order, quality gates, documented limits. **APCER with liveness bypassed measured at 1.0 — all attack resistance lives in the liveness stage, which is strictly load-bearing.** Formal FAR/FRR/APCER evaluation on real people is **NOT YET MEASURED** (`docs/PHASE5_EVALUATION.md`) |
| Malicious relayer | Medium | Detect via reconciliation, audit anchors, event comparison, mismatch surfacing (partially implemented) |
| Coercer persistence | High | Max 3 ballots, full re-auth per revote; documented as **limited**, not absolute |
| Root/backend operator during election | High | Trust boundary documented; not solvable inside this trust model |
| Correlation risk if planes are linked | High | Enforce separation, schema discipline, controlled bridge only |
| Receipt abuse | Medium | Minimal receipt content, HMAC code only, no candidate |
| Crash / recovery complexity | Medium | State machine + durable intent + idempotency + reconciliation (partially implemented) |
| Local-only deployment assumptions | Low | Explicitly out of scope for production hardening |
| Weak recovery / revoting test coverage | Medium | Recorded in Section 3.2; must be strengthened in the owning phase |

---

## 17. KNOWN LIMITATIONS

- Academic prototype only - **not legally binding**.
- Privacy **does not fully hold** against a root/backend operator with access during the election.
- Malicious relayer **not fully preventable** (only detectable).
- Coercion resistance is **limited** (physical presence, device control, credential handover).
- Biometrics are **vulnerable to sophisticated attacks** (deepfakes, virtual cameras).
- Anonymity is **pseudonymous, not perfect anonymity**.
- Scale assumption: **<= 500 voters, <= 20 candidates**.
- Voting windows of hours to days; desktop-first; localhost/LAN development only.
- Not production-hardened.

---

## 18. OPEN DECISIONS

| Area | Question | Owning phase |
|---|---|---|
| Face library | ArcFace/InsightFace vs face_recognition/dlib (feasibility, accuracy, licence) | **DECIDED in Phase 5 remediation** — InsightFace `2.1` (SCRFD + ArcFace `buffalo_l`), weights pre-provisioned with recorded SHA-256 digests, no runtime download. Real-world accuracy question remains open to Phase 13 |
| Mailpit vs real SMTP | Development email delivery detail | Resolved in Phase 2 (Mailpit) |
| Admin TOTP granularity | Admin 2FA implementation detail (RFC 6238) | Phase 11 |
| Audit anchoring frequency | Per event / per batch / phase end | Phase 12 |
| Null revote semantics | Exact behaviour and UI | Phase 9 (specified, not built) |
| Null revote + cooldown | Cooldown enforcement location | Phase 9 |
| Reconciliation policy | Auto-retry vs manual officer review on mismatch | Phase 10 (partially resolved) / 11 |
| Recovery test depth | Replace weak structural tests with real failure-injection tests | Phase 14 |

---

## 19. TESTING REQUIREMENTS

**DESIGN BASELINE**

- Unit / integration / API tests with database isolation (Flask)
- Smart contract tests + coverage (Hardhat)
- Frontend component and E2E tests
- Security tooling: Bandit, pip-audit, npm audit, gitleaks, OWASP ZAP baseline
- Slither static analysis
- Dedicated privacy, recovery and failure-injection test classes
- Face fixtures for matching and liveness validation — present as a **deterministic four-identity synthetic renderer** (`backend/tests/face_fixtures.py`). Sufficient to validate the code path; **not** a substitute for a consented human dataset. See `docs/PHASE5_FIXTURES.md`.
- Reconciliation mismatch scenarios
- Scripted attack demonstration

**Current state:** see [Section 3.2](#32-known-evidence-caveats) and `docs/THREAT_MODEL_REGISTER.md`.

**Principle:** verify when possible; never assume a test framework or script exists - check the
repository first.

---

## 20. DOCUMENTATION INDEX

| Document | Purpose |
|---|---|
| [README.md](./README.md) | Project entry point |
| [PROJECT_MASTER_REPORT.md](./PROJECT_MASTER_REPORT.md) | Authoritative specification and architecture |
| [PROJECT_BIBLE.md](./PROJECT_BIBLE.md) | This file - living source of truth |
| [docs/PHASE0_CHECKPOINT.md](./docs/PHASE0_CHECKPOINT.md) | Phase 0 baseline checkpoint (historical) |
| [docs/PHASE0_FINAL_REPORT.md](./docs/PHASE0_FINAL_REPORT.md) | Phase 0 final / remediation report |
| [docs/PHASE0_FOUNDATION_AUDIT.md](./docs/PHASE0_FOUNDATION_AUDIT.md) | Phase 0 implementation audit |
| [docs/PHASE1_IMPLEMENTATION_AUDIT.md](./docs/PHASE1_IMPLEMENTATION_AUDIT.md) | Phase 1 implementation audit |
| [docs/PHASE1_REMEDIATION_REPORT.md](./docs/PHASE1_REMEDIATION_REPORT.md) | Phase 1 remediation report |
| [docs/PHASE2_IMPLEMENTATION_AUDIT.md](./docs/PHASE2_IMPLEMENTATION_AUDIT.md) | Phase 2 implementation audit (verdict PARTIAL) |
| [docs/PHASE2_REMEDIATION_REPORT.md](./docs/PHASE2_REMEDIATION_REPORT.md) | Phase 2 remediation report + A–T verification |
| [docs/PHASE3_REMEDIATION_REPORT.md](./docs/PHASE3_REMEDIATION_REPORT.md) | Phase 3 remediation report + A–AB verification |
| [docs/PHASE4_REMEDIATION_REPORT.md](./docs/PHASE4_REMEDIATION_REPORT.md) | Phase 4 remediation report + A–AG verification |
| [docs/THREAT_MODEL_REGISTER.md](./docs/THREAT_MODEL_REGISTER.md) | THREAT -> CONTROL -> TEST -> RESULT register |
| [docs/DEV_SETUP.md](./docs/DEV_SETUP.md) | Development environment setup |
| [docs/DATABASE_SETUP.md](./docs/DATABASE_SETUP.md) | MySQL schema and least-privilege setup |
| [docs/PHASE0..PHASE10_CHECKPOINT.md](./docs/) | Per-phase historical checkpoints |
| [docs/PHASE0..PHASE10_FINAL_REPORT.md](./docs/) | Per-phase final / retrospective reports |
| `scripts/verify_foundation.ps1` | Deterministic foundation verification |
| `backend/scripts/prove_phase2_auth.py` | Phase 2 end-to-end authentication proof harness |
| `backend/scripts/prove_phase3_registration.py` | Phase 3 end-to-end registration proof harness |
| `backend/scripts/prove_phase4_wallet.py` | Phase 4 end-to-end wallet ownership proof harness |

---

## 21. MAINTENANCE RULES

1. **Single source of phase status.** Only Section 3 of this Bible declares current phase status. Per-phase documents are historical.
2. **No blind appends.** Status changes are made by editing Section 3, never by appending text to the end of this file.
3. **UTF-8 only.** Write plain UTF-8. Do not introduce escaped-newline formatting or re-encode the file.
4. **Label design vs implementation.** Every control claim is either DESIGN BASELINE or IMPLEMENTED/PARTIAL with evidence.
5. **No false completion.** A phase is COMPLETE only when its deliverables exist and its documents exist. Evidence strength is stated separately.
6. **No fabricated tests.** The threat register may only cite tests that exist in the repository.
7. **Privacy separation is inviolable.** No change may introduce an identity-to-ballot mapping.
8. **Actual paths only.** Documentation must use `blockchain/` and `blockchain/contracts/`, never a top-level `contracts/`.
9. **Boundary rule.** Do not begin a new phase without explicit instruction.

---

**END OF PROJECT BIBLE**
