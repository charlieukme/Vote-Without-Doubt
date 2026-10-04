# PROJECT BIBLE - Vote Without Doubt

**Project:** AI & Blockchain-Based Secure E-Voting System for College Elections
**Product Name:** Vote Without Doubt
**Type:** Academic Prototype - NOT a legally binding election system
**Project Root:** `C:\Users\aditya prasad\Downloads\voting-sys`
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

| Phase | Title | Status |
|---|---|---|
| Phase 0 | Project Foundation | **COMPLETE** |
| Phase 1 | Backend + Database Foundation | **COMPLETE** |
| Phase 2 | Authentication Core | **COMPLETE** |
| Phase 3 | College Roll + Registration | **COMPLETE** |
| Phase 4 | MetaMask / Wallet Security | **COMPLETE** |
| Phase 5 | Face + Liveness | **COMPLETE** |
| Phase 6 | Blockchain / Smart Contract | **COMPLETE** |
| Phase 7 | Core Voting Pipeline (Milestone A) | **COMPLETE** |
| Phase 8 | Privacy Hardening | **COMPLETE** |
| Phase 9 | Revoting + Coercion Resistance (Milestone B) | **COMPLETE** |
| Phase 10 | Recovery + Reconciliation | **COMPLETE** |
| Phase 11 | Admin + Election Management | NOT STARTED |
| Phase 12 | Public Verification + Results | NOT STARTED |
| Phase 13 | Security Hardening | NOT STARTED |
| Phase 14 | Full Failure + Performance Testing | NOT STARTED |
| Phase 15 | Privacy / Legal / Documentation | NOT STARTED |
| Phase 16 | Final UI + Demo | NOT STARTED |
| Phase 17 | Final Release | NOT STARTED |

**Current phase:** Phase 10 remediation is complete; Phase 11 has NOT been started.
**Rule:** Do not begin Phase 11 or later until explicitly instructed.

### 3.1 Completion Means

A phase marked COMPLETE means phase deliverables and their phase documents exist. It does **not** by itself certify that every control in [Section 7](#7-design-baseline---security-principles) is fully implemented and independently verified. Evidence strength is recorded per item in [Section 15](#15-security-baseline-implementation-status) and in [docs/THREAT_MODEL_REGISTER.md](./docs/THREAT_MODEL_REGISTER.md).

### 3.2 Known Evidence Caveats

Recorded honestly as of the Phase 0 remediation:

- `backend/tests/test_face_api.py` fails at collection (6 errors) because it requests a `client` fixture that is not provided by the active pytest/plugin configuration. It is excluded from the passing regression set. **This is a Phase 5 test-suite defect and was deliberately NOT fixed during Phase 0 remediation.**
- `backend/tests/test_recovery.py` and `backend/tests/test_revoting.py` contain only weak/structural assertions. They are **not** sufficient evidence for the recovery and revoting guarantees they are named after. **This is a Phase 9/10 test-quality defect and was deliberately NOT fixed during Phase 0 remediation.**

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
| Face recognition | ArcFace / InsightFace preferred; face_recognition / dlib fallback | Phase 5 service scaffolding present; real model integration not evidenced |
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
| Face frame deletion / embedding protection | PARTIAL | `backend/app/security/face.py`, `backend/app/services/face_service.py`; `test_face_validation.py` covers auth-gating only |
| Hash-chained audit | IMPLEMENTED | `backend/app/audit/audit.py`; `test_audit.py` (6 tests) |
| On-chain audit anchoring | DESIGN ONLY | contract `anchorAudit` exists; no backend anchoring path evidenced |
| RBAC / four-eyes admin | DESIGN ONLY | Phase 11 not started |
| CSRF / CSP / security headers | DESIGN ONLY | Phase 9/13 scope |
| Rate limiting | DESIGN ONLY | `RATE_LIMIT_ENABLED` flag only, no limiter |
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
| Face deepfakes / virtual cameras | Medium-High | Challenge-based liveness, quality checks, documented limits; formal FAR/FRR/APCER evaluation is Phase 9/13 scope |
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
| Face library | ArcFace/InsightFace vs face_recognition/dlib (feasibility, accuracy, licence) | Phase 5 (partially resolved) / 13 |
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
- Face fixtures for matching and liveness validation
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
| [docs/THREAT_MODEL_REGISTER.md](./docs/THREAT_MODEL_REGISTER.md) | THREAT -> CONTROL -> TEST -> RESULT register |
| [docs/DEV_SETUP.md](./docs/DEV_SETUP.md) | Development environment setup |
| [docs/DATABASE_SETUP.md](./docs/DATABASE_SETUP.md) | MySQL schema and least-privilege setup |
| [docs/PHASE0..PHASE10_CHECKPOINT.md](./docs/) | Per-phase historical checkpoints |
| [docs/PHASE0..PHASE10_FINAL_REPORT.md](./docs/) | Per-phase final / retrospective reports |
| `scripts/verify_foundation.ps1` | Deterministic foundation verification |

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
