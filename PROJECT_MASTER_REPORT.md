# AI & Blockchain-Based Secure E-Voting System for College Elections

**Project Name:** Vote Without Doubt

---

## 1. PROJECT TITLE

AI & Blockchain-Based Secure E-Voting System for College Elections  
Product/Project Name: **Vote Without Doubt**

---

## 2. PROJECT PURPOSE

Build an academic prototype of a secure college e-voting system combining:

- Electoral-roll verification
- Password authentication
- Email OTP
- MetaMask wallet authentication/signatures
- Face verification
- Face liveness detection
- Blockchain-backed ballot integrity
- Privacy-preserving pseudonymous ballots
- Secure vote submission
- Revoting/coercion mitigation
- Hash-chained audit logging
- Election lifecycle management
- Recovery and reconciliation
- Public verification
- Security testing

This is an **academic prototype**. It is NOT a legally binding real-world election system.

---

## 3. PRODUCT CONCEPT

"Vote Without Doubt" is a secure, auditable, and privacy-preserving e-voting prototype designed specifically for college elections. It emphasizes verifiable integrity while protecting voter privacy through a strict separation of identity and ballot data, pseudonymous blockchain entries, and comprehensive audit trails.

---

## 4. ACADEMIC SCOPE

- Academic prototype for college elections
- Team size: ~2–3 students
- Focus: Security, privacy, integrity, auditability, recoverability, and usability
- Not intended for production deployment in legally binding elections
- Documented limitations are essential

---

## 5. SYSTEM ARCHITECTURE

### High-Level Architecture

```
React + Vite (Frontend)
    ↓
Flask Backend (Python)
    ↓
MySQL 8 Database
    ↓
Relayer
    ↓
Ganache (Blockchain)
    ↓
Solidity 0.8.19 Smart Contract (via Hardhat)
```

### Additional Subsystems

- Face recognition/liveness detection
- Email (SMTP/Mailpit)
- Audit logging (hash-chained)
- Reconciliation
- Admin management
- Public verifier

### Two Data Planes

**IDENTITY PLANE:** Contains voter identity, electoral roll, registration, authentication, eligibility, and participation information.

**BALLOT PLANE:** Contains pseudonymous voter identifiers, ballot information, candidate selection, ballot sequence, and blockchain submission state.

**Design Constraint:** No direct linking between identity and ballot planes via foreign keys, shared rows, shared ordering, or candidate-bearing identity records. Controlled server-side bridge only where necessary.

---

## 6. TECHNOLOGY STACK

| Component | Technology |
|---|---|
| Frontend | React + Vite |
| Backend | Python + Flask |
| Database | MySQL 8 |
| Blockchain | Ganache |
| Smart Contracts | Solidity 0.8.19 |
| Contract Development | Hardhat |
| Face Recognition (Preferred) | ArcFace / InsightFace |
| Face Recognition (Fallback) | face_recognition / dlib |
| Email | SMTP / Mailpit (dev) |

---

## 7. ASSUMPTIONS

- One election represents one contest
- Multiple posts can be represented as separate elections
- Team size ~2–3 students
- College-managed email available
- Desktop Chrome/Edge/Firefox supported
- Webcam required
- MetaMask required
- Mobile MetaMask out of scope
- Localhost/LAN development expected
- Local TLS may use mkcert
- Ganache Chain ID = 1337
- ≤500 voters
- ≤20 candidates
- Election duration: hours to days
- Backend trusted-but-audited for privacy
- Academic prototype

---

## 8. TRUST MODEL

### Privacy Holds Against
- Database-only attacker
- Blockchain observer
- Normal administrator without root/shell access
- Coercer without device control
- Attacker possessing one stolen credential

### Privacy Does NOT Fully Hold Against
- Root/backend operator with access during the election

### Integrity Resists
- Students
- Ordinary database modification
- Ordinary admin abuse

### Limitations
- A malicious relayer may not be fully preventable; behavior must be detectable via reconciliation/audit mechanisms

---

## 9. THREAT MODEL

Key threats to address (eventually tracked as THREAT → CONTROL → TEST → RESULT):

- Malicious registration, duplicate registration
- Double voting, impersonation
- Stolen credentials, stolen sessions
- OTP replay, wallet replay
- Face spoofing, face replay
- Modified frontend, direct API manipulation
- Admin abuse
- Database attacker, blockchain attacker
- MITM, DoS
- Malicious insider
- Voter-ballot correlation
- Transaction replay, election manipulation
- Coercion, vote buying, receipt abuse
- Device/session coercion
- Rogue relayer
- Revote-cap griefing

---

## 10. AUTHENTICATION ARCHITECTURE

### Registration Flow (R1–R6)
- **R1:** Voter ID / electoral-roll verification
- **R2:** Ownership verification / email OTP
- **R3:** Password creation
- **R4:** MetaMask wallet binding
- **R5:** Face enrollment + liveness
- **R6:** Registration complete

### Login
- Voter ID
- Password
- Email OTP

### Voting Authorization
- MetaMask wallet signature
- Face/liveness verification

---

## 11. OTP SECURITY

- 6-digit cryptographically secure OTP (secrets.randbelow or equivalent)
- HMAC-SHA256 with server-side pepper
- 5-minute expiry
- Max 5 attempts
- Resend cooldown ~60 seconds
- Resend limit ~5/hour
- Single use, purpose-bound, authentication/session-bound
- Never log raw OTPs
- Development via Mailpit/SMTP

---

## 12. PASSWORD SECURITY

- Never stored in plaintext
- **Argon2id** for password hashing
- Password policy enforcement
- Rate limiting
- Secure verification
- Generic authentication errors

---

## 13. SESSION SECURITY

- Opaque, cryptographically random session ID (~256-bit randomness)
- `__Host-` cookie where applicable
- HttpOnly, Secure, SameSite=Strict
- Idle timeout ~10 minutes; Absolute timeout ~2 hours
- Session rotation after OTP authentication
- One active session per voter
- Admin sessions separate with idle timeout ~15 minutes

---

## 14. METAMASK ARCHITECTURE

- MetaMask used as possession/authentication mechanism
- **Must not** submit the actual vote transaction via MetaMask
- **Candidate selection must never** be included in wallet signature
- Use `personal_sign` (or equivalent)
- Signed message must include: domain, purpose, voter, election, chain ID, contract address, nonce, issued timestamp, expiry
- Backend reconstructs and verifies exact expected message
- Nonce: single-use, session-bound, purpose-bound, replay-resistant
- No unnecessary persistence of wallet signatures

---

## 15. FACE RECOGNITION

**Preferred:** ArcFace / InsightFace  
**Fallback:** face_recognition / dlib

### Enrollment
- Explicit consent
- Quality checks
- Exactly one face
- Secure embedding storage

### Privacy/Protection
- Embeddings encrypted/protected
- Evaluation targets: FAR, FRR, ROC, DET, APCER, BPCER
- Document limitations against virtual cameras, replay, deepfakes, cooperating voters, targeted attacks

---

## 16. LIVENESS DETECTION

### Challenge-Based Liveness
- Challenges: LEFT / RIGHT movement (head-yaw)
- TTL ~20 seconds
- ~10–24 JPEG frames
- Quality checks, exactly one face
- Frames deleted immediately after processing
- Designed to mitigate spoofing/replay

---

## 17. BLOCKCHAIN ARCHITECTURE

- **Ganache** (local chain, Chain ID 1337)
- **Hardhat** (development framework)
- **Solidity 0.8.19**
- Smart Contract: `EVotingBallotBox`
- Supports multiple elections
- Roles: Officers, Relayer
- Immutable election parameters after creation (where specified)
- Mutable state: ballots by pseudonym, tally, distinct voters, cancelled state

### Key Election Parameters
- startTime, endTime
- candidateCount
- candidatesHash
- eligibleVoterCount
- rollHash
- maxBallotCount

### Events
- ElectionCreated, ElectionCancelled
- BallotCast, AuditAnchored
- RelayerChanged

---

## 18. SMART CONTRACT ARCHITECTURE

### Core Functions (Conceptual)
- `createElection(...)`
- `cancelElection(...)`
- `castBallot(...)`
- `getTally(...)`
- `electionInfo(...)`
- `anchorAudit(...)`
- `setRelayer(...)`

### `castBallot` Enforcement
- Election timing (open/closed)
- Cancellation state
- Candidate bounds
- Ballot sequence
- Maximum ballots per election
- Eligible voter limit
- First ballot: increment distinct voter count, enforce eligible limit
- Revote: decrement previous tally, increment new tally

---

## 19. PSEUDONYMOUS BALLOT DESIGN

**Principle:** Do not put voter identity + candidate choice directly on blockchain.

### Pseudonym Generation (Per-Election)
```text
pseudonym = HMAC-SHA256(
  K_election,
  domain-separated(
    chainId,
    contract,
    electionId,
    voter
  )
)
```

- Per-election key is protected and encrypted in ballot storage
- Key destroyed after election finalization (per lifecycle)
- **Pseudonymous, not perfectly anonymous** — this limitation must be documented

---

## 20. VOTING FLOW

1. Election OPEN
2. Eligibility check
3. Begin authorization
4. Wallet challenge
5. MetaMask signature
6. Face/liveness verification
7. Candidate selection
8. Voter confirmation
9. Backend transactionally creates ballot submission
10. Authorization consumed
11. Ballot enters queue
12. Relayer submits blockchain transaction
13. Blockchain confirmation
14. Reconciliation
15. Privacy-preserving receipt
16. Optional notification email

**Privacy Constraint:** Candidate information must NOT appear in receipts, normal logs, status APIs, notifications, public audit UI, or public verification.

---

## 21. BALLOT STATE MACHINE

### Authorization States
- PENDING_FACTORS → AUTHORIZED → CONSUMED (or EXPIRED)

### Ballot States
- QUEUED → SUBMITTED → CONFIRMED → FINALIZED
- Failure: FAILED, RECONCILE_REQUIRED, SUPERSEDED

### Requirements
- Exactly-once enqueue
- Durable transaction intent before broadcast
- Idempotency
- Blockchain confirmation
- Crash recovery
- Reconciliation
- Safe closing cutoff

---

## 22. REVOTING

- Max 3 ballots per voter per election
- Latest valid vote counts
- Full authentication for every revote (wallet + face/liveness)
- ~2-minute cooldown
- Optional null revote
- Revote replaces previous tally on-chain

---

## 23. COERCION MITIGATION

Designed to allow a coerced voter to privately override an earlier vote. Limitations:
- Coercer physically present until deadline
- Device control
- Credential handover

These are not fully solved by this prototype.

---

## 24. RECEIPT DESIGN

**May contain:**
- Election title
- Voter ID last 4
- Minute-level time
- HMAC receipt code

**Must NOT contain:**
- Candidate/candidate choice
- Pseudonym
- Transaction hash
- Block number
- Queue ID

---

## 25. AUDIT DESIGN

- Hash-chained audit log (tamper detection)
- Supports election lifecycle auditing, security events, on-chain audit anchoring
- **Never log:** passwords, OTPs, private keys, candidate choices, unnecessary biometric data, raw pseudonyms

---

## 26. PRIVACY ARCHITECTURE

- Strict identity-ballot separation (two planes)
- Pseudonymous blockchain entries
- Minimal data disclosure (privacy-preserving receipts)
- Candidate choices excluded from logs/UI/receipts
- Embeddings protected; frames deleted after processing
- Per-election keys destroyed after finalization

---

## 27. ADMIN ARCHITECTURE

**Roles:** Election Officer, Auditor (read-only)

**Election Lifecycle States:** DRAFT → PENDING_APPROVAL → SCHEDULED → OPEN → CLOSED → FINALIZED (or CANCELLED)

**Controls:**
- Minimum two officers for sensitive actions
- No self-approval
- Auditor read-only
- No individual vote viewing
- No editing published election parameters
- No audit deletion
- Admin does not hold relayer private key
- Password + TOTP required for admin authentication

---

## 28. ELECTION LIFECYCLE

States: DRAFT, PENDING_APPROVAL, SCHEDULED, OPEN, CLOSED, FINALIZED, CANCELLED
- Lifecycle transitions controlled by authorized officers with required approvals
- Published parameters immutable after publication where specified
- Safe closing cutoff and finalization procedures

---

## 29. RECOVERY

Handles: browser crash, MetaMask failure, Flask crash, MySQL failure, Ganache failure, network interruption, relayer crash, pending transactions, election closing.

---

## 30. RECONCILIATION

Compares: queue rows, blockchain events, ballot sequence, pseudonym counts, tally, audit hash chain, audit anchors. Mismatches become visible security/reconciliation states.

---

## 31. PUBLIC VERIFICATION

After election close (no running tally UI during open election):
- Verify blockchain events, tally, duplicate acceptance, election timing
- Verify candidate hash, roll size, audit integrity, audit anchors
- **Never reveal** individual voter choices

---

## 32. SECURITY CONTROLS

Core controls: RBAC, Argon2id, secure sessions, CSRF, CORS, input validation, SQL injection prevention, XSS protection, rate limiting, OTP/wallet replay protection, face spoofing/replay protection, admin abuse prevention, audit integrity, secret management, secure headers, TLS, DB least privilege, recovery, monitoring, dependency security.

---

## 33. TESTING STRATEGY

- Unit, API, database isolation tests
- Smart contract tests + coverage (Hardhat)
- Slither for static analysis
- Frontend tests, E2E
- Face fixtures
- Security, recovery, privacy tests
- Failure injection
- Optional performance testing
- Tools: Slither, Bandit, pip-audit, npm audit, gitleaks, OWASP ZAP baseline

---

## 34. UI/DESIGN SYSTEM

**Style:** NEO-BRUTALISM

**Design Principles:** Security + Accessibility + Usability first

**Color Palette:**
- `#FFFDF5` - Cream background
- `#000000` - Black typography
- `#FF6B6B` - Red accent
- `#FFD93D` - Yellow accent
- `#C4B5FD` - Violet accent

**Guidelines:** Thick black borders, hard shadows, sharp geometric layouts, Space Grotesk or equivalent, mechanical button interactions. Avoid excessive animation/rotation/gradients/blur/glassmorphism, especially during face scanning, OTP, wallet signing, voting, confirmation.

---

## 35. OUT-OF-SCOPE FEATURES

**Not built:** Kubernetes, microservices, cloud autoscaling, custom blockchain, AI agents, mobile app, mixnets, keyless ballot box, commit-reveal, blind RSA in core, ZK voting in core, threshold crypto in core, HSM/KMS, WebAuthn, public testnet deployment.

---

## 36. FUTURE WORK

- Blind signatures, JCJ (Jonkers–Crypto–Jakobsson), ZK proofs
- Threshold keys, HSM/KMS, WebAuthn
- Cast-as-intended verification, sealed tally, public testnet

---

## 37. COMPLETE PHASE 0–17 ROADMAP

| Phase | Title | Key Activities |
|---|---|---|
| **Phase 0** | Project Foundation | Requirements, freeze scope/threat model, repo structure, dev env, security baseline. Create PROJECT_MASTER_REPORT.md + PROJECT_BIBLE.md. **STOP after completion.** |
| **Phase 1** | Backend + Database Foundation | Flask architecture, MySQL schemas (identity/ballot planes), DB security, audit foundation, React/Vite shell, middleware, tests |
| **Phase 2** | Authentication Core | Argon2id, sessions, OTP, login, secure cookies, rate limits, tests |
| **Phase 3** | College Roll + Registration | Electoral roll, CSV import, dry-run, approval/apply, registration, ownership verification, anti-takeover, recovery, tests |
| **Phase 4** | MetaMask / Wallet Security | Binding, challenge, signature verification, nonce, replay protection, domain separation, recovery, tests |
| **Phase 5** | Face + Liveness | Enrollment/consent, matching, liveness, privacy, attack protection, evaluation |
| **Phase 6** | Blockchain / Smart Contract | Ganache, Hardhat, Solidity, elections/lifecycle/roles, ballot rules, events, security, coverage, Slither |
| **Phase 7** | Core Voting Pipeline | Eligibility, auth, wallet+face, candidate selection, pseudonym, queue, relayer, receipt, state machine, idempotency, E2E (**First major working milestone**) |
| **Phase 8** | Privacy Hardening | Strengthen separation, logging hygiene, pseudonym lifecycle hardening |
| **Phase 9** | Revoting + Coercion Mitigation | Max 3, cooldown, full re-auth, null revote, documentation |
| **Phase 10** | Recovery + Reconciliation | Crash recovery, pending tx, reconciliation logic, mismatch visibility |
| **Phase 11** | Admin + Election Management | Roles, approvals (min 2 officers), TOTP, lifecycle controls |
| **Phase 12** | Public Verification + Results | Post-close verification, audit anchors, no individual vote disclosure |
| **Phase 13** | Security Hardening | Full threat coverage, controls/tests |
| **Phase 14** | Full Failure + Performance Testing | Failure injection, recovery, stress (if needed) |
| **Phase 15** | Privacy / Legal / Documentation | Limitations, threat doc, compliance notes, user docs |
| **Phase 16** | Final UI + Demo | Polish to neo-brutalist spec, demo readiness |
| **Phase 17** | Final Release | Final packaging, cleanup, release artifacts |

**Rule:** Do not skip phases. Do not implement later phases early without explicit instruction.

---

## 38. KNOWN LIMITATIONS

- Academic prototype only (not legally binding)
- Privacy not fully guaranteed against root/backend operator during election
- Malicious relayer cannot be fully prevented; must be detectable
- Coercion resistant in limited sense (physical presence/device control issues)
- Face/liveness can be challenged by sophisticated deepfakes/virtual cameras (documented)
- Pseudonymous but not perfectly anonymous
- Local dev environment (Ganache localhost) - not production-hardened
- Limited scale (≤500 voters)

---

## 39. IMPORTANT ARCHITECTURAL DECISIONS

1. **Two-plane separation (identity vs ballot):** Enforced to minimize correlation risk. No direct cross-plane linking via schema.
2. **Blockchain stores only pseudonyms + non-identifying ballot data:** Candidate identity never co-located with voter identity on-chain.
3. **MetaMask signs challenge, not vote:** Prevents exposing candidate choice and reduces wallet-side leakage.
4. **Per-election pseudonym keys:** Domain-separated, encrypted, destroyed after finalization.
5. **Privacy-preserving receipts:** Intentionally minimal (no candidate, no tx/block/queue IDs).
6. **Hash-chained audit log:** Tamper-evident with on-chain anchoring support.
7. **Authorization consumed after use:** Prevents replay/reuse of voting authorization.
8. **Exactly-once semantics + reconciliation:** For crash/failure resilience with blockchain.
9. **Full re-auth for every revote:** Strengthens coercion mitigation at cost of UX.
10. **Neo-brutalist UI with security-first priority:** Visual clarity over effects, critical flows minimal animation.
11. **Start from zero in current directory only:** Clean implementation, no migration/copy from prior work.

---

## 40. ACADEMIC/DEMO VALUE

Demonstrates: end-to-end secure voting flow, blockchain integrity, privacy-preserving design, authentication layering (password+OTP+wallet+biometrics), auditability, revoting, and security engineering discipline with explicit documentation of limitations.

---

## 41. FROZEN SCOPE TAXONOMY (CORE / STRONG / OPTIONAL / FUTURE / DO NOT BUILD)

The project scope is frozen into exactly five categories. No feature may be moved between
categories without explicit user instruction and a documented architectural justification.

### 41.1 CORE / MILESTONE A

The minimum demonstrable secure-voting capability. Delivered across Phases 1-7; Phase 7 is the
first major working milestone.

- CSV electoral-roll import
- Registration roll check (eligibility verification against the roll)
- Email OTP (ownership verification)
- Password authentication
- Wallet (MetaMask) binding
- Face recognition + liveness
- Login
- Server-side secure sessions
- Election / candidate / timing enforcement in the smart contract
- One counted ballot per pseudonym
- Eligible-voter cap
- Tally
- Pseudonymous ballots
- Relayer
- Privacy-preserving receipt
- Hash-chained audit
- Basic admin
- Reconciliation
- Unit / integration / negative tests
- Scripted attack demonstration

### 41.2 STRONG / MILESTONE B

Hardening that materially improves security, privacy and verifiability beyond Milestone A.
Delivered across Phases 8-10.

- Revoting cap 3
- Shuffled batching (relayer)
- Vote-cast email notification
- Startup recovery / stale transaction handling
- On-chain audit anchors
- Closing audit + pseudonym key destruction
- Public verifier
- Face FAR / FRR / APCER evaluation
- Admin TOTP
- CSRF / CSP / security headers
- Privacy / consent / terms
- Slither + coverage
- OWASP ZAP baseline
- Failure injection

### 41.3 OPTIONAL

Architecture-defined optional capabilities. Not required for a Milestone A or Milestone B
demonstration.

- Optional vote-cast notification email (Section 20, step 16)
- Optional null revote (Section 22)
- Optional performance testing (Section 33)
- Optional local TLS via mkcert for realistic local HTTPS (Section 7)

### 41.4 FUTURE

Advanced research-grade cryptography and deployment targets, explicitly deferred beyond this
prototype (Section 36).

- Blind signatures
- JCJ (Jonkers-Crypto-Jakobsson) voting
- Zero-knowledge proofs
- Threshold keys
- HSM / KMS
- WebAuthn
- Cast-as-intended verification
- Sealed tally
- Public testnet deployment

### 41.5 DO NOT BUILD

Explicitly excluded from this project at every phase. Never to be built.

- Kubernetes
- Microservices
- AI agents
- Custom ML
- Mixnets
- Keyless ballot box
- Commit-reveal
- Mobile application
- Cloud autoscaling
- Custom blockchain

---

## 42. FROZEN DEVELOPMENT ENVIRONMENT

### 42.1 Required Floors

| Component | Requirement |
|---|---|
| Python | 3.11+ |
| MySQL | 8.0 |
| Node.js | 20+ |
| Solidity | 0.8.19 (pinned in `blockchain/hardhat.config.js`) |
| Contract framework | Hardhat |
| Local chain | Ganache, chain ID 1337 |
| Frontend | React + Vite |
| Local TLS | mkcert assumed available |
| Browser | Desktop Chrome / Edge / Firefox |
| Hardware | Webcam required |
| Wallet | MetaMask desktop extension |
| Mobile | Mobile MetaMask out of scope |

### 42.2 Verified Local Environment

Traceability record only. A newer installed version does not lower the floor above.

| Component | Verified version |
|---|---|
| Python | 3.11.9 |
| Node.js | v24.19.0 (satisfies the 20+ floor) |
| npm | 11.17.0 |
| Git | 2.55.0.windows.3 |

### 42.3 Local Services

MySQL 8 on `localhost:3306` (database `voting_sys`, least-privilege user `voting_sys_user`);
Ganache on `127.0.0.1:8545` (chain ID 1337); Mailpit / SMTP on `localhost:1025`;
Flask backend on `localhost:5000`; Vite dev server on `localhost:5173`.

### 42.4 Repository Path Convention

Solidity sources live in `blockchain/contracts/`. There is no top-level `contracts/` directory.
Documentation must use these actual paths.

---

**END OF PROJECT MASTER REPORT**