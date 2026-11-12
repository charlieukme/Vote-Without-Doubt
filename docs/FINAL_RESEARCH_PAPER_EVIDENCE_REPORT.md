# RESEARCH PAPER EVIDENCE REPORT: VOTE WITHOUT DOUBT

**Document Title:** Vote Without Doubt: Complete Academic Research Paper Evidence & Architectural Extraction  
**Target Manuscript:** *"Vote Without Doubt: A Privacy-Preserving and Auditable Blockchain-Anchored E-Voting Prototype for Collegiate Elections"*  
**System Status:** `PROJECT LOCKED — APPROVED FOR RESEARCH PAPER FINALIZATION`  
**Git Commit Hash:** `5cd31f6e0ed053e4a7006e0ea11ed8b87164c5a7`  
**Auditor / Extraction Core:** Antigravity Autonomous Security & Verification Core  
**Effective Date:** November 1, 2026  

---

## 1. Executive Summary

This report provides the exhaustive, evidence-based technical reference required to author a peer-reviewed academic manuscript for the **Vote Without Doubt (VWD)** system. 

Vote Without Doubt is an academic prototype of an electronic voting system designed for collegiate campus elections (e.g., student government councils, departmental representatives). The system addresses the classical tension in electronic voting: **strict individual voter privacy and ballot secrecy** versus **end-to-end auditability and public tally verifiability**, operating within an institutional environment susceptible to credential sharing, coercion in dormitories, and administrative tampering.

The project encompasses two distinct architectural generations:
1. **Version 1 (V1 - Auditable Anchored Relational Pipeline):** Combines multi-factor voter authentication (Password + Email OTP, ArcFace 512-dimensional facial embedding matching with interactive 3D yaw liveness, and MetaMask EIP-191 cryptographic wallet signature verification), two-plane relational database partitioning (Identity Plane vs. Ballot Plane), per-election deterministic HMAC pseudonymity with forward-secure key shredding, an asynchronous shuffling relayer, and RFC 6962 canonical binary Merkle tree commitments anchored on an Ethereum smart contract ([`EVotingBallotBox.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBox.sol)).
2. **Version 2 (V2 - On-Chain Cryptographic Threshold Protocol):** Implements a decentralized 2-of-2 threshold additive ElGamal cryptosystem over the BN254 elliptic curve group $\mathbb{G}_1$, non-circular Cramer-Damgård-Schoenmakers (CDS) zero-knowledge disjunctive 1-of-2 and vector sum-to-one ballot-validity proofs ([`BN254CDSVerifier.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/BN254CDSVerifier.sol)), atomic homomorphic revoting with sequence monotonicity, Chaum-Pedersen discrete logarithm equality (DLEQ) verified decryption shares, on-chain bounded discrete-log tally verification ([`EVotingBallotBoxV2.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBoxV2.sol)), and institutional dual-officer governance with client-side Argon2id WASM key derivation and AES-256-GCM backup recovery ([`DUAL_OFFICER_GOVERNANCE_CHARTER.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/DUAL_OFFICER_GOVERNANCE_CHARTER.md)).

All metrics and claims in this report are categorized using strict evidential classifications:
- `[VERIFIED FROM SOURCE]`: Inspected line-by-line in frozen application code or smart contracts.
- `[SUPPORTED BY TEST EVIDENCE]`: Validated through reproducible test runs and mined execution receipts.
- `[REPORTED IN DOCUMENTATION ONLY]`: Found in historical project documentation but not currently evidenced in code.
- `[INFERRED]`: Deductions logically following from system invariants.
- `[UNVERIFIED / MISSING EVIDENCE]`: Explicitly marked gaps, non-claims, or unmeasured parameters.

---

## 2. Project Overview

### 2.1 Project Identity & Institutional Scope
- **Project Name:** Vote Without Doubt (VWD) `[VERIFIED FROM SOURCE: PROJECT_BIBLE.md:L4]`
- **System Classification:** Academic E-Voting Research Prototype `[VERIFIED FROM SOURCE: PROJECT_BIBLE.md:L41-L45]`
- **Target Domain:** Collegiate Student Elections (Electoral rolls of 100 to 100,000 students) `[VERIFIED FROM SOURCE: PROJECT_DOCUMENTATION.md:L54-L57]`
- **Statutory Disclaimer:** The software is an academic engineering prototype. It is **not** certified under national statutory voting standards (e.g., US EAC VVSG 2.0 or ECI specifications) and is not intended for legally binding civil elections `[VERIFIED FROM SOURCE: docs/KNOWN_LIMITATIONS.md:L49-L53]`.

### 2.2 Core Problems Addressed
1. **Administrative Single Points of Failure:** Centralized databases permit database administrators (DBAs) to modify tallies or inject counterfeit votes unnoticed.
2. **Credential Sharing & Proxy Voting:** Simple username/password systems cannot detect credential sharing or student coercion in shared dormitories.
3. **Receipt-Free Coercion Mitigation:** Enabling voters to alter an earlier coerced vote without granting them an indisputable receipt that proves their final vote choice to an external buyer or coercer.
4. **Trust Minimization via Threshold Cryptography:** Preventing any single university administrator or student election commissioner from unilaterally inspecting cast ballots or decrypting the tally before election closure.

---

## 3. Document Inventory & Source-of-Truth Matrix

The repository contains 66 documents under `docs/` and 10 root markdown files. The following table provides the source-of-truth matrix:

| Document Path | Document Title | Milestone / Phase | Document Status | Evidence Contained | Citation in Paper | Conflict / Caveat Notes |
| :--- | :--- | :---: | :---: | :--- | :---: | :--- |
| [`docs/PHASE16_FINAL_PROJECT_FREEZE.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/PHASE16_FINAL_PROJECT_FREEZE.md) | Phase 16: Final Project Freeze & System Lock Report | Milestone 7 Lock | **AUTHORITATIVE (FINAL)** | Resolution of 6 audit findings, final test passes (476 tests), commit hash, DB hash `cac297df...` | **YES (Primary)** | Defines the authoritative frozen baseline. |
| [`docs/DUAL_OFFICER_GOVERNANCE_CHARTER.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/DUAL_OFFICER_GOVERNANCE_CHARTER.md) | Dual-Officer Institutional Governance & Identity Charter | Milestone 7 Governance | **AUTHORITATIVE (FINAL)** | Institutional eligibility, technical vs institutional identity, volatile key custody, 72h stall, non-claims | **YES (Primary)** | Corrected Nov 1, 2026; supersedes any prior mention of sessionStorage. |
| [`docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md) | Milestone 7: Independent Security & Production-Readiness Review | Milestone 7 Audit | **AUTHORITATIVE (FINAL)** | Line-by-line audit of 12 source files, 6 findings, 14 threat analyses, performance benchmarks | **YES (Primary)** | Initial verdict was "Approved with Conditions"; fully resolved in Project Freeze. |
| [`docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md) | Milestone 6: Isolated End-to-End Validation Report | Milestone 6 E2E | **AUTHORITATIVE (FINAL)** | M6 simulated election (2 officers, 5 voters, 3 candidates, 2 revotes), gas profiling, DLog verification | **YES (Primary)** | Records DB hash `0cabf5f8...` which represents an isolated snapshot (investigated in Section 16). |
| [`EXPERIMENTAL_BENCHMARK_REPORT.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/EXPERIMENTAL_BENCHMARK_REPORT.md) | Experimental Benchmark Report | Phase 15/16 Empirical | **AUTHORITATIVE (FINAL)** | Merkle construction ($N=3..500$), gas profiling (28 mined txs), relayer shuffling, auth micro-benchmarks | **YES (Primary)** | Contains empirical micro-benchmarks on Intel i7-13700H / 16GB host. |
| [`PROJECT_DOCUMENTATION.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/PROJECT_DOCUMENTATION.md) | Project Documentation: Vote Without Doubt | Phase 15 System Spec | **CURRENT ARCHITECTURE** | End-to-end V1 architecture, multi-factor gate, two-plane separation, threat analysis | **YES** | V1-centric; must be paired with V2 specifications. |
| [`PROJECT_BIBLE.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/PROJECT_BIBLE.md) | Project Bible - Vote Without Doubt | Historical Spec Baseline | **LIVING REPOSITORY SPEC** | Architectural principles, design baselines, decision logs, repository conventions | **YES (Context)** | Section 3 historically stops at Phase 10; actual code completed through Milestone 7. |
| [`PROJECT_MASTER_REPORT.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/PROJECT_MASTER_REPORT.md) | Master Report | Phase 0 Proposal | **SUPERSEDED (HISTORICAL)** | Initial proposal (claimed MySQL 8 and Ganache) | **NO (Historical only)** | Superseded by actual implementation using SQLite 3 and Hardhat. |
| [`docs/KNOWN_LIMITATIONS.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/KNOWN_LIMITATIONS.md) | Known Limitations — Do Not Misrepresent | Phase 15 Governance | **AUTHORITATIVE (FINAL)** | Explicit non-claims: biometrics unmeasured, client device out-of-scope, no receipt-freeness | **YES (Critical)** | Essential for the paper's *Threat Model & Limitations* section. |
| [`docs/RESIDUAL_RISK_REGISTER.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/RESIDUAL_RISK_REGISTER.md) | Residual Risk Register | Phase 15 Risk Audit | **AUTHORITATIVE (FINAL)** | 14 residual risks, mitigation methods, audit trails | **YES** | Corroborates threat analysis. |

---

## 4. Complete V1 Architecture

`[VERIFIED FROM SOURCE: PROJECT_DOCUMENTATION.md:L58-L89, backend/app/services/voting_service.py]`

```
+----------------------------------------------------------------------------------------------------+
|                                         V1 DATA PLANES                                             |
+---------------------------------------------------+------------------------------------------------+
|                   IDENTITY PLANE                  |                  BALLOT PLANE                  |
| (Student Identity, Enrollment, MFA Sessions)      | (Pseudonymous Ballots, Merkle Roots, Ledger)   |
|                                                   |                                                |
| - users (id, roll_number, email, password_hash)   | - ballot_records (id, election_id, sequence,   |
| - face_enrollments (user_id, embedding_vector)    |   pseudonym, candidate, commitment, nonce)     |
| - wallet_bindings (user_id, eth_address, sig)     | - audit_events (id, event_type, prev_hash,     |
| - voting_authorizations (user_id, election_id,    |   current_hash, timestamp)                    |
|   consumed, wallet_ok, face_ok)                   |                                                |
+---------------------------------------------------+------------------------------------------------+
                                           |
                    Forward-Secure Deterministic Bridge
                    P = HMAC(K_E, user_id || election_id)
                    (Key K_E permanently destroyed at election close)
                                           |
                                           v
+----------------------------------------------------------------------------------------------------+
|                                    V1 WORKFLOW PIPELINE                                            |
|                                                                                                    |
|  [Voter Browser]                                                                                   |
|         │                                                                                          |
|         ├─ 1. Credentials + Email OTP  ────────> [POST /api/auth/login]                            |
|         ├─ 2. Face Video Stream (3D Yaw) ──────> [POST /api/face/verify]                           |
|         ├─ 3. MetaMask EIP-191 Signature ──────> [POST /api/wallet/verify]                         |
|         │                                                                                          |
|         ▼                                                                                          |
|  [Server Authorizes Voting Session]                                                                |
|         │                                                                                          |
|         ├─ 4. Submits Candidate Choice ────────> [POST /api/voting/ballot]                         |
|         │     (Generates 256-bit Nonce C)        (Atomically Claims Authorization)                 |
|         │                                        (Derives Pseudonym P)                             |
|         │                                        (Inserts BallotRecord: state='QUEUED')            |
|         ▼                                                                                          |
|  [Asynchronous Relayer Worker]                                                                     |
|         │                                                                                          |
|         ├─ 5. Fetches Batch of 10 Ballots                                                          |
|         ├─ 6. Uniform Random Shuffling (Kendall-tau = 0.5022)                                      |
|         ├─ 7. Broadcasts to EVotingBallotBox.sol :: castBallot(electionId, pseudonym, cand, seq)   |
|         │                                                                                          |
|         ▼                                                                                          |
|  [Election Closure & Audit Anchoring]                                                              |
|         │                                                                                          |
|         ├─ 8. Binary RFC 6962 Merkle Tree Assembled over Sorted Commitments                        |
|         ├─ 9. Finalized Root Anchored via EVotingBallotBox.sol :: anchorAudit()                    |
|         └─ 10. Key Shredding: K_E Destroyed (Forward Secrecy Enforced)                              |
+----------------------------------------------------------------------------------------------------+
```

### 4.1 Frontend Technologies & Responsibilities
- **Framework:** React 18.2 with Vite 5. Vanilla CSS adhering to a high-contrast Neo-Brutalist design system `[VERIFIED: frontend/package.json, frontend/src/index.css]`.
- **Biometric Capture:** HTML5 WebRTC `navigator.mediaDevices.getUserMedia` accessing local camera, rendering to `<canvas>`, extracting 3D facial landmarks for yaw tracking (`LEFT`, `RIGHT`) `[VERIFIED: frontend/src/faceCamera.js]`.
- **Web3 Wallet Provider:** `ethers.js` (v6) interfacing with `window.ethereum` (EIP-1193) for signing domain-separated challenges `[VERIFIED: frontend/src/Wallet.jsx]`.
- **Pages Implementing V1:**
  - Registration: [`frontend/src/Registration.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/Registration.jsx)
  - Authentication: [`frontend/src/Auth.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/Auth.jsx)
  - Face Verification: [`frontend/src/Face.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/Face.jsx)
  - Wallet Binding: [`frontend/src/Wallet.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/Wallet.jsx)
  - Voting & Receipt: [`frontend/src/Voting.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/Voting.jsx)
  - Public Verifier: [`frontend/src/pages/public/VerifyPage.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/pages/public/VerifyPage.jsx)

### 4.2 Backend Technologies & Responsibilities
- **Framework:** Python 3.11 with Flask, SQLAlchemy ORM, and Flask-Migrate (Alembic) `[VERIFIED: backend/requirements.txt]`.
- **Database Engine:** SQLite 3 in development/testing (PyMySQL/MySQL 8 compatible) `[VERIFIED: backend/app/config/config.py]`.
- **Modules Implementing V1:**
  - Multi-Factor Voting Service: [`backend/app/services/voting_service.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/voting_service.py)
  - Face Verification Engine: [`backend/app/services/face_engine.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/face_engine.py)
  - Pseudonym Derivation & Key Shredding: [`backend/app/security/pseudonym.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/security/pseudonym.py)
  - Merkle Inclusion Engine: [`backend/app/security/merkle.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/security/merkle.py)
  - Asynchronous Relayer Dispatcher: [`backend/app/relayer/relayer.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/relayer/relayer.py)
  - Audit Hash Chain Logger: [`backend/app/audit/audit.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/audit/audit.py)

### 4.3 Smart Contract Architecture (V1)
- **Contract:** [`blockchain/contracts/EVotingBallotBox.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBox.sol) (187 lines, Solidity 0.8.19).
- **SHA-256 Digest:** `d4e70dd30b6469c6111a4456a2c6732fa07bf3038ee0285859f17dd6646856af` `[VERIFIED FROM SOURCE]`.
- **Functions:**
  - `createElection(uint256 electionId, uint256 candidateCount, uint256 maxVoters, uint256 endTime)`
  - `castBallot(uint256 electionId, bytes32 pseudonym, uint256 candidate, uint256 sequence)`
  - `anchorAudit(uint256 electionId, bytes32 auditRoot)`
  - `getBallot(uint256 electionId, bytes32 pseudonym)`
  - `getTally(uint256 electionId, uint256 candidate)`

---

## 5. Complete V2 Architecture

`[VERIFIED FROM SOURCE: blockchain/contracts/EVotingBallotBoxV2.sol, docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md]`

```
+----------------------------------------------------------------------------------------------------+
|                                    V2 ON-CHAIN CRYPTOGRAPHIC ARCHITECTURE                          |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [Officer 01: Student Union]                           [Officer 02: University Academic / Legal]   |
|         │                                                              │                           |
|         ├─ Samples s_1 in [1, Q-1]                                     ├─ Samples s_2 in [1, Q-1]  |
|         ├─ Computes Y_1 = s_1 * G                                      ├─ Computes Y_2 = s_2 * G   |
|         ├─ Generates Schnorr PoP (R_1, z_1)                            ├─ Generates Schnorr PoP    |
|         ├─ Argon2id + AES-256-GCM Backup                               ├─ Argon2id + AES-256-GCM   |
|         │                                                              │                           |
|         └───────────────────────► [EVotingBallotBoxV2.sol] ◄───────────┘                           |
|                                    │                                                               |
|                                    ├─ Verifies Both Schnorr PoPs on-chain                          |
|                                    ├─ Computes Joint Public Key: Y_joint = Y_1 + Y_2               |
|                                    └─ Transitions: Setup -> KeyRegistrationComplete -> VotingOpen  |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [Voter Browser: Client-Side Proof Engine]                                                         |
|         │                                                                                          |
|         ├─ Encrypts Choice Vector: (v_0, ..., v_{M-1}) in {0, 1}^M, sum(v_j) == 1                  |
|         ├─ Generates Ciphertext Vector: A_j = r_j * G, B_j = r_j * Y_joint + v_j * G               |
|         ├─ Evaluates Non-Circular CDS Validity Proof: 1-of-2 Branch Proofs + Vector Sum Proof      |
|         │                                                                                          |
|         ▼                                                                                          |
|  [EVotingBallotBoxV2.sol :: castBallot()]                                                          |
|         │                                                                                          |
|         ├─ Calls BN254CDSVerifier.sol :: verifyBallotProof()                                       |
|         ├─ Initial Vote (seq = 1): A_agg[j] += A_j, B_agg[j] += B_j                                |
|         └─ Revote (seq = seq_prev + 1): A_agg[j] += A_new - A_prev, B_agg[j] += B_new - B_prev    |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [Election Closure & Zero-Trust Threshold Tally]                                                   |
|         │                                                                                          |
|         ├─ Admin calls closeVoting() -> Initiates 72-Hour Tally Grace Period                       |
|         ├─ Officer 01 submits: D_1[j] = s_1 * A_agg[j] + Chaum-Pedersen DLEQ Proofs                |
|         ├─ Officer 02 submits: D_2[j] = s_2 * A_agg[j] + Chaum-Pedersen DLEQ Proofs                |
|         ├─ Smart Contract verifies DLEQ: log_G(Y_i) == log_{A_agg[j]}(D_i[j])                      |
|         │                                                                                          |
|         ▼                                                                                          |
|  [On-Chain Finalization: finalizeTally(t_0, ..., t_{M-1})]                                         |
|         │                                                                                          |
|         ├─ Sum constraint check: sum(t_j) == totalActiveBallots                                    |
|         ├─ Curve Point Equality: B_agg[j] - (D_1[j] + D_2[j]) == t_j * G                           |
|         └─ Transitions State -> Finalized (Zero Master Key / Zero Backdoor)                        |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

### 5.1 Modules Implementing V2
- **Smart Contracts:**
  - [`blockchain/contracts/EVotingBallotBoxV2.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBoxV2.sol) (489 lines)
  - [`blockchain/contracts/BN254.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/BN254.sol) (162 lines)
  - [`blockchain/contracts/BN254CDSVerifier.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/BN254CDSVerifier.sol) (265 lines)
- **Backend Cryptography & Services:**
  - [`backend/app/services/bn254_crypto.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/bn254_crypto.py) (631 lines)
  - [`backend/app/services/blockchain_v2_service.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/blockchain_v2_service.py) (289 lines)
  - [`backend/app/routes/voting_v2.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/routes/voting_v2.py) (456 lines)
  - [`backend/app/models/ballot_record_v2.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/models/ballot_record_v2.py) (76 lines)
- **Frontend Cryptography & Client Components:**
  - [`frontend/src/utils/bn254_client.js`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/utils/bn254_client.js) (647 lines)
  - [`frontend/src/utils/officerBackup.js`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/utils/officerBackup.js) (372 lines)
  - [`frontend/src/pages/admin/OfficerDashboardPage.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/pages/admin/OfficerDashboardPage.jsx) (680 lines)
  - [`frontend/src/components/VotingV2.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/components/VotingV2.jsx) (412 lines)
  - [`frontend/src/pages/public/ResultsV2Page.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/pages/public/ResultsV2Page.jsx) (280 lines)

---

## 6. V1 Technical Implementation

`[VERIFIED FROM SOURCE: backend/app/services/voting_service.py, backend/app/security/merkle.py, blockchain/contracts/EVotingBallotBox.sol]`

### 6.1 Ballot Submission Protocol
1. **Factor Validation:** When a voter initiates voting, `VotingService.mark_factors()` queries verified database records for `WalletBinding` (is_verified=True) and `FaceChallenge` (unconsumed challenge within 300 seconds). If valid, `VotingAuthorization` is granted `[VERIFIED: voting_service.py:L63-L115]`.
2. **Atomic Consumption:** In `VotingService.submit_ballot()`, the authorization is claimed atomically using an SQL UPDATE (`consumed = True, consumed_at = now_utc`), preventing race conditions `[VERIFIED: voting_service.py:L410-L428]`.
3. **Pseudonym Derivation:** The pseudonym is computed deterministically:
   $$P = \text{HMAC-SHA256}(K_E, \text{user\_id} \parallel \text{election\_id})$$
   where $K_E$ is a 256-bit symmetric key generated at election creation and stored in `ElectionKey`. When the election is finalized, $K_E$ is permanently shredded from the database, rendering historical pseudonyms computationally irreversible `[VERIFIED: backend/app/security/pseudonym.py:L45-L78]`.

### 6.2 Ballot Commitment Mechanism
To prevent candidate choice exposure or dictionary attacks over small candidate domains ($M \in [2, 10]$), ballots generate a 256-bit high-entropy commitment:
$$C = \text{SHA256}(\mathtt{"VWD\_BALLOT\_COMMITMENT\_V1:"} \parallel \text{election\_id} \parallel \mathtt{":"} \parallel \text{candidate\_index} \parallel \mathtt{":"} \parallel \text{nonce})$$
where $\text{nonce} \xleftarrow{\$} \{0, 1\}^{256}$ is sampled from a CSPRNG `[VERIFIED: backend/app/security/merkle.py:L43-L65]`.
In Fix 1 (`test_fix1_client_commitment.py`), the voter's browser generates the nonce and commitment locally before submission, preventing even the backend from observing the uncommitted choice prior to receipt generation.

### 6.3 RFC 6962 Binary Merkle Tree
Commitments are assembled into a binary Merkle tree following RFC 6962 Section 2.1:
- **Leaf Hash:** $H_{\text{leaf}} = \text{SHA256}(\mathtt{0x00} \parallel \text{commitment})$
- **Node Hash:** $H_{\text{node}} = \text{SHA256}(\mathtt{0x01} \parallel \text{left\_child} \parallel \text{right\_child})$
- **Odd-Node Rule:** Trees split at the largest power of 2 strictly less than $N$: $k = 2^{\lfloor \log_2(N-1) \rfloor}$. Leaves are never duplicated, preventing CVE-2012-2459 duplication attacks `[VERIFIED: backend/app/security/merkle.py:L68-L92]`.
- **Leaf Sorting:** Commitments are lexicographically sorted prior to tree assembly to eliminate submission-time correlation `[VERIFIED: backend/app/security/merkle.py:L98]`.

### 6.4 Relayer Behavior & Shuffling
The asynchronous relayer (`backend/app/relayer/relayer.py`) queries ballots in state `QUEUED`, fetches a batch of up to 10 ballots, and applies a cryptographically secure uniform random permutation using Python's `secrets.SystemRandom().shuffle()`. The relayer signs transactions from an authorized operator wallet and broadcasts them to `EVotingBallotBox.sol::castBallot()`, shielding the voter's IP address and wallet gas balance from on-chain correlation `[VERIFIED: backend/app/relayer/relayer.py:L145-L188]`.

### 6.5 Revoting Enforcement & Receipt Generation
- **Revoting Rules:** Each voter may submit up to $K$ ballots (default $K=3$, configurable via `MAX_BALLOTS_PER_VOTER`). The smart contract enforces strict sequence monotonicity: $\text{sequence} = \text{currentSeq} + 1$. A revote overwrites the previously stored candidate tally slot on-chain `[VERIFIED: EVotingBallotBox.sol:L95-L118]`.
- **Receipts:** Voters receive an HMAC receipt containing: election ID, masked voter ID (last 4 characters), timestamp (minute-level precision), and HMAC signature. The receipt **omits** candidate choice, transaction hash, and pseudonym, preventing vote buying and coercion `[VERIFIED: voting_service.py:L513-L545]`.

### 6.6 Guarantees & Honest Disclosures (V1)
- **What V1 Guarantees:** Tamper-evident ballot recording, public audit-chain anchoring, individual inclusion verification via logarithmic Merkle paths, forward secrecy post-key shredding, and mitigation of casual coercion via revoting.
- **What V1 Does NOT Guarantee:** V1 does **not** provide cryptographic ballot secrecy against a compromised backend database prior to election closure. In V1, the backend stores plaintext candidate integers in `ballot_records.candidate` to coordinate the relayer. True on-chain choice privacy is only introduced in V2.

---

## 7. V2 Cryptographic Implementation & Mathematical Equations

`[VERIFIED FROM SOURCE: blockchain/contracts/EVotingBallotBoxV2.sol, blockchain/contracts/BN254.sol, blockchain/contracts/BN254CDSVerifier.sol, backend/app/services/bn254_crypto.py]`

### 7.1 Curve Parameters & Threshold Key Generation
V2 operates over the elliptic curve group $\mathbb{G}_1$ of the **BN254 (alt_bn128)** curve defined by:
$$E(\mathbb{F}_p): Y^2 = X^3 + 3 \pmod P$$
where:
- **Base Field Modulus $P$:**
  $$P = 21888242871839275222246405745257275088696311157297823662689037894645226208583$$
- **Subgroup Prime Order $Q$ (Scalar Field):**
  $$Q = 21888242871839275222246405745257275088548364400416034343698204186575808495617$$
- **Standard Generator $G$:** $(1, 2) \in \mathbb{G}_1$
- **Point at Infinity $\mathcal{O}$:** Encoded as $(0, 0)$ per EIP-196 `[VERIFIED: BN254.sol:L13-L25]`.

#### Dual-Officer Key Setup
1. Officer $i \in \{1, 2\}$ samples a private scalar uniformly at random using CSPRNG rejection sampling:
   $$s_i \xleftarrow{\$} [1, Q-1]$$
2. Computes public key share:
   $$Y_i = s_i \cdot G \in \mathbb{G}_1$$
3. Generates a Schnorr Proof-of-Possession (PoP):
   - Samples $k_i \xleftarrow{\$} [1, Q-1]$, commits $R_i = k_i \cdot G$.
   - Computes Fiat-Shamir challenge:
     $$e_i = \text{Keccak256}(\mathtt{"VWD\_BN254\_POP\_V1"} \parallel \text{chainId} \parallel \text{contract} \parallel \text{electionId} \parallel i \parallel \text{officerAddress} \parallel Y_i \parallel R_i) \pmod Q$$
   - Solves response scalar:
     $$z_i = k_i + e_i \cdot s_i \pmod Q$$
4. On-Chain Verification (`EVotingBallotBoxV2.sol::registerOfficer`):
   $$z_i \cdot G \stackrel{?}{=} R_i + e_i \cdot Y_i$$
5. Joint Public Key: Once both officers register, the smart contract computes:
   $$Y_{\text{joint}} = Y_1 + Y_2 = (s_1 + s_2) \cdot G$$
   `[VERIFIED: EVotingBallotBoxV2.sol:L157-L195]`.

---

### 7.2 Ballot Encryption & Non-Circular CDS Zero-Knowledge Proofs
For an election with $M$ candidates ($M \in [2, 10]$), candidate selection is encoded as a one-hot vector $\mathbf{v} = (v_0, v_1, \dots, v_{M-1}) \in \{0, 1\}^M$ subject to $\sum_{j=0}^{M-1} v_j = 1$.

#### Additive ElGamal Encryption
For each candidate $j \in \{0, \dots, M-1\}$:
1. Samples ephemeral randomness $r_j \xleftarrow{\$} [1, Q-1]$.
2. Computes ciphertext pair:
   $$A_j = r_j \cdot G$$
   $$B_j = r_j \cdot Y_{\text{joint}} + v_j \cdot G$$

#### Non-Circular Fiat-Shamir CDS NIZK Construction
To prevent circular hash dependencies where challenge evaluation depends on uncommitted values, the protocol executes a strictly non-circular Fiat-Shamir transcript `[VERIFIED: BN254CDSVerifier.sol:L16-L53, bn254_crypto.py:L175-L310]`:

1. **Commitment Phase:**
   - For the real branch ($b = v_j \in \{0, 1\}$): Prover samples $w_j \xleftarrow{\$} [1, Q-1]$ and sets:
     $$T_{A, b}^{(j)} = w_j \cdot G, \quad T_{B, b}^{(j)} = w_j \cdot Y_{\text{joint}}$$
   - For the simulated branch ($1-b$): Prover samples fake challenge $c_{j, 1-b} \xleftarrow{\$} [1, Q-1]$ and fake response $z_{j, 1-b} \xleftarrow{\$} [1, Q-1]$:
     - If simulating branch 0 ($v_j = 1$, simulating $v_j=0$):
       $$T_{A, 0}^{(j)} = z_{j, 0} \cdot G - c_{j, 0} \cdot A_j$$
       $$T_{B, 0}^{(j)} = z_{j, 0} \cdot Y_{\text{joint}} - c_{j, 0} \cdot B_j$$
     - If simulating branch 1 ($v_j = 0$, simulating $v_j=1$):
       $$T_{A, 1}^{(j)} = z_{j, 1} \cdot G - c_{j, 1} \cdot A_j$$
       $$T_{B, 1}^{(j)} = z_{j, 1} \cdot Y_{\text{joint}} - c_{j, 1} \cdot (B_j - G)$$
   - For the vector sum proof: Prover samples $w_{\text{sum}} \xleftarrow{\$} [1, Q-1]$:
     $$T_{A, \text{sum}} = w_{\text{sum}} \cdot G, \quad T_{B, \text{sum}} = w_{\text{sum}} \cdot Y_{\text{joint}}$$

2. **Master Challenge Evaluation:**
   All commitments are explicitly hashed into a master transcript:
   $$c_{\text{master}} = \text{Keccak256}(\text{Header} \parallel \mathbf{A} \parallel \mathbf{B} \parallel \mathbf{T}_{\text{cand}} \parallel \mathbf{T}_{\text{sum}}) \pmod Q$$
   where $\text{Header}$ domain-separates $\mathtt{"VWD\_BN254\_CDS\_NIZK\_NONCIRCULAR\_V2"}$, chain ID, verifier address, election ID, pseudonym, and sequence.

3. **Coordinate Challenge Derivation & Real Branch Completion:**
   - Candidate challenge: $c_j = \text{Keccak256}(c_{\text{master}} \parallel j) \pmod Q$.
   - Real branch challenge solved algebraically:
     $$c_{j, b} = (c_j - c_{j, 1-b}) \pmod Q$$
   - Real branch response:
     $$z_{j, b} = (w_j + c_{j, b} \cdot r_j) \pmod Q$$
   - Sum challenge: $c_{\text{sum}} = \text{Keccak256}(c_{\text{master}} \parallel \mathtt{"SUM"}) \pmod Q$.
   - Sum response ($r_{\text{sum}} = \sum_{j=0}^{M-1} r_j \pmod Q$):
     $$z_{\text{sum}} = (w_{\text{sum}} + c_{\text{sum}} \cdot r_{\text{sum}}) \pmod Q$$

4. **On-Chain Verification Equations (`BN254CDSVerifier.sol`):**
   - Challenge sum check: $c_{j, 0} + c_{j, 1} \equiv c_j \pmod Q$
   - Branch 0 equations:
     $$z_{j, 0} \cdot G \stackrel{?}{=} T_{A, 0}^{(j)} + c_{j, 0} \cdot A_j$$
     $$z_{j, 0} \cdot Y_{\text{joint}} \stackrel{?}{=} T_{B, 0}^{(j)} + c_{j, 0} \cdot B_j$$
   - Branch 1 equations:
     $$z_{j, 1} \cdot G \stackrel{?}{=} T_{A, 1}^{(j)} + c_{j, 1} \cdot A_j$$
     $$z_{j, 1} \cdot Y_{\text{joint}} \stackrel{?}{=} T_{B, 1}^{(j)} + c_{j, 1} \cdot (B_j - G)$$
   - Sum equations ($A_{\text{sum}} = \sum A_j, B_{\text{sum}} = \sum B_j$):
     $$z_{\text{sum}} \cdot G \stackrel{?}{=} T_{A, \text{sum}} + c_{\text{sum}} \cdot A_{\text{sum}}$$
     $$z_{\text{sum}} \cdot Y_{\text{joint}} \stackrel{?}{=} T_{B, \text{sum}} + c_{\text{sum}} \cdot (B_{\text{sum}} - G)$$

---

### 7.3 Homomorphic Aggregation & Revoting Updates
`[VERIFIED FROM SOURCE: EVotingBallotBoxV2.sol:L278-L295]`

When a ballot is cast:
- **Initial Ballot ($\text{sequence} = 1$):**
  $$A_{\text{agg}}[j] \leftarrow A_{\text{agg}}[j] + A_j^{(1)}$$
  $$B_{\text{agg}}[j] \leftarrow B_{\text{agg}}[j] + B_j^{(1)}$$
  The active ballot is stored: $\text{activeBallots}[\text{pseudonym}][j] \leftarrow (A_j^{(1)}, B_j^{(1)})$, and $\text{totalActiveBallots} \leftarrow \text{totalActiveBallots} + 1$.
- **Revote ($\text{sequence} = k > 1$):**
  The contract retrieves the voter's previous ciphertext $(A_{\text{prev}}[j], B_{\text{prev}}[j])$ and executes atomic elliptic curve homomorphic subtraction and addition:
  $$A_{\text{agg}}[j] \leftarrow A_{\text{agg}}[j] - A_{\text{prev}}[j] + A_{\text{new}}[j]$$
  $$B_{\text{agg}}[j] \leftarrow B_{\text{agg}}[j] - B_{\text{prev}}[j] + B_{\text{new}}[j]$$
  $\text{totalActiveBallots}$ remains unchanged. All historical ciphertexts remain permanently immutable in transaction logs and events (`BallotCastV2`), but their contribution to the running aggregate is completely replaced.

---

### 7.4 Decryption Shares & Chaum-Pedersen DLEQ Verification
`[VERIFIED FROM SOURCE: EVotingBallotBoxV2.sol:L308-L355, bn254_crypto.py:L484-L594]`

When voting closes, the aggregate ciphertext $(A_{\text{agg}}[j], B_{\text{agg}}[j])$ represents the sum of all active votes:
$$A_{\text{agg}}[j] = \left(\sum r_i^{(j)}\right) \cdot G, \quad B_{\text{agg}}[j] = \left(\sum r_i^{(j)}\right) \cdot Y_{\text{joint}} + t_j \cdot G$$
where $t_j$ is the final vote count for candidate $j$.

1. **Share Computation:**
   Each officer $i \in \{1, 2\}$ evaluates their decryption share for each candidate $j \in \{0, \dots, M-1\}$:
   $$D_i[j] = s_i \cdot A_{\text{agg}}[j]$$
2. **Chaum-Pedersen DLEQ Proof:**
   To prove on-chain that $\log_G(Y_i) = \log_{A_{\text{agg}}[j]}(D_i[j])$ without revealing $s_i$:
   - Officer samples ephemeral scalar $t_j \xleftarrow{\$} [1, Q-1]$.
   - Commits: $U_j = t_j \cdot G$, $V_j = t_j \cdot A_{\text{agg}}[j]$.
   - Fiat-Shamir challenge:
     $$c_j = \text{Keccak256}(\mathtt{"VWD\_BN254\_DLEQ\_V1"} \parallel \text{chainId} \parallel \text{contract} \parallel \text{electionId} \parallel i \parallel j \parallel Y_i \parallel A_{\text{agg}}[j] \parallel D_i[j] \parallel U_j \parallel V_j) \pmod Q$$
   - Response: $z_j = (t_j + c_j \cdot s_i) \pmod Q$.
3. **On-Chain DLEQ Verification (`EVotingBallotBoxV2.sol::_verifyDLEQ`):**
   $$z_j \cdot G \stackrel{?}{=} U_j + c_j \cdot Y_i$$
   $$z_j \cdot A_{\text{agg}}[j] \stackrel{?}{=} V_j + c_j \cdot D_i[j]$$
4. **Aggregate Point-at-Infinity Handling:**
   If candidate $j$ received identical revote retractions resulting in $A_{\text{agg}}[j] = \mathcal{O}$, the contract requires $D_i[j] = \mathcal{O}$ and satisfies DLEQ without elliptic curve precompile faults `[VERIFIED: EVotingBallotBoxV2.sol:L336-L342]`.

---

### 7.5 On-Chain Tally Verification (Bounded Discrete Logarithm)
`[VERIFIED FROM SOURCE: EVotingBallotBoxV2.sol:L363-L401]`

Combining decryption shares yields the joint decryption factor:
$$D_{\text{joint}}[j] = D_1[j] + D_2[j] = (s_1 + s_2) \cdot A_{\text{agg}}[j] = s_{\text{joint}} \cdot \left(\sum r_i^{(j)}\right) \cdot G$$
Subtracting from $B_{\text{agg}}[j]$ cancels the blinding factor:
$$M_j = B_{\text{agg}}[j] - D_{\text{joint}}[j] = t_j \cdot G$$

The discrete logarithm $t_j = \log_G(M_j)$ is recovered off-chain in $O(\text{totalActiveBallots})$ time using precomputed lookup tables (or Baby-Step Giant-Step). The candidate tally vector $(t_0, t_1, \dots, t_{M-1})$ is submitted to `finalizeTally()`, where the smart contract autonomously verifies:
1. Individual bounds: $t_j \le \text{totalActiveBallots}$
2. Sum conservation: $\sum_{j=0}^{M-1} t_j = \text{totalActiveBallots}$
3. Group equation: $M_j \stackrel{?}{=} t_j \cdot G$ for all $j \in \{0, \dots, M-1\}$.
If candidate $j$ has 0 votes, $t_j = 0$ yields $0 \cdot G = \mathcal{O} = (0, 0)$, which is accepted natively.

---

## 8. Authentication & Identity Verification

`[VERIFIED FROM SOURCE: backend/app/services/voting_service.py, backend/app/services/face_engine.py, backend/app/security/wallet.py, EXPERIMENTAL_BENCHMARK_REPORT.md]`

```
+----------------------------------------------------------------------------------------------------+
|                                    MULTI-FACTOR AUTHENTICATION GATE                                |
+------------------------------------+--------------------------------+------------------------------+
| Factor 1: Knowledge + Ownership    | Factor 2: Biometric Inherence  | Factor 3: Possession Proof   |
| (Password + Institutional Email)   | (ArcFace Matching + 3D Yaw)    | (MetaMask EIP-191 Signature) |
|                                    |                                |                              |
| - Argon2id password hash match     | - 512-d normalized float32 ArcFace - EIP-191 ECDSA challenge   |
| - 6-digit email OTP (5-min expiry) |   cosine similarity >= 0.65    |   signature recovery         |
| - Peppered SHA-256 OTP matching    | - Interactive 3D head yaw      | - Verifies wallet possession |
|   (latency: 0.0008 ms)             |   tracking (LEFT, RIGHT)       | - Candidate is blinded       |
|                                    | - Vector dot product: 0.0053 ms| - ecrecover latency: 4.89 ms |
+------------------------------------+--------------------------------+------------------------------+
```

### 8.1 Factor 1: Password & Email OTP
- **Password Security:** Hashed using Argon2id (`argon2-cffi`) with per-user unique salt.
- **OTP Delivery:** 6-digit numeric OTP delivered to verified institutional student email (`@college.edu`). Valid for 300 seconds (5 minutes). Hashed with server-side pepper and verified using constant-time comparison `hmac.compare_digest`. Compute latency: **0.0008 ms** `[VERIFIED: EXPERIMENTAL_BENCHMARK_REPORT.md:L239]`.

### 8.2 Factor 2: ArcFace Facial Recognition & Liveness Protocol
- **Feature Extraction:** InsightFace with ArcFace `buffalo_l` backbone producing 512-dimensional normalized float32 feature embeddings `[VERIFIED: backend/app/services/face_engine.py:L142-L175]`.
- **Cosine Matching Threshold:** Cosine similarity threshold enforced at $\ge 0.65$:
  $$\text{sim}(\mathbf{u}, \mathbf{v}) = \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\|_2 \|\mathbf{v}\|_2} \ge 0.65$$
  Empirical vector dot-product matching compute latency: **0.0053 ms** `[VERIFIED: EXPERIMENTAL_BENCHMARK_REPORT.md:L238]`.
- **Interactive Challenge Liveness:** Server issues interactive challenge (`LEFT`, `RIGHT`) with a short-lived lease token (60 seconds). Yaw angle is evaluated from 3D facial landmarks:
  $$\text{Yaw} > +20^\circ \implies \text{RIGHT}, \quad \text{Yaw} < -20^\circ \implies \text{LEFT}$$
- **Presentation Attack Detection (PAD / Anti-Spoofing):** Active runtime configuration operates in **`FACE_PAD_MODE = 'shadow'`**. Telemetry models execute in the background without actively rejecting presentation attacks. **No empirical APCER or BPCER is claimed** `[VERIFIED: docs/KNOWN_LIMITATIONS.md:L16-L24, EXPERIMENTAL_BENCHMARK_REPORT.md:L242-L245]`.

### 8.3 Factor 3: MetaMask Wallet Signature
- **Challenge Message:** Voter signs a domain-separated string via MetaMask (EIP-191):
  $$\mathtt{"Vote\ Without\ Doubt\ Auth:\ " \parallel electionId \parallel ":" \parallel userId \parallel ":" \parallel timestamp}$$
- **Privacy Assurance:** The signature message binds voter identity and election session, but **never includes candidate choice or ballot contents**. ECDSA message recovery latency (`ecrecover` on secp256k1): **4.89 ms** `[VERIFIED: EXPERIMENTAL_BENCHMARK_REPORT.md:L240]`.

---

## 9. Dual-Officer Governance & Key Custody

`[VERIFIED FROM SOURCE: docs/DUAL_OFFICER_GOVERNANCE_CHARTER.md, frontend/src/utils/officerBackup.js, frontend/src/pages/admin/OfficerDashboardPage.jsx]`

### 9.1 Institutional Separation of Roles
The governance charter codifies institutional separation to mitigate collusion risks:
- **Officer 01 (Voter Representation):** Appointed by the **Student Government / Student Union** (e.g., Chief Election Commissioner of Student Council). Primary mandate: protect voter privacy and prevent administrative coercion. Uses institutional student email (`@student.college.edu`).
- **Officer 02 (Institutional Oversight):** Appointed by the **University Board of Trustees / Academic Council** (e.g., Faculty Dean or University Legal Counsel). Primary mandate: enforce institutional bylaws and audit computational transparency. Uses administrative email (`@faculty.college.edu`).

### 9.2 Technical Identity vs. Institutional Identity
The charter explicitly delineates four distinct tiers of identity:
1. **Distinct Ethereum Wallet Addresses:** Technical cryptographic keypairs enforced on-chain (`officer1 != officer2` and `officer != admin`).
2. **Distinct Authenticated Accounts:** Identity-provider credentials verified at the application layer.
3. **Distinct Legal Persons:** Individual natural persons verified through real-world identity vetting.
4. **Independent Institutional Appointment Authorities:** Separate governing bodies exercising independent oversight.

> *Smart contract enforcement of distinct wallet addresses prevents the same address from occupying both officer seats. It does not establish that the addresses belong to different legal persons or independent institutions. Institutional identity verification, appointment records and conflict-of-interest checks are governance responsibilities and must be performed outside the cryptographic protocol. Neither email domains nor Ethereum wallet addresses constitute cryptographic proof of institutional independence.* `[VERIFIED: DUAL_OFFICER_GOVERNANCE_CHARTER.md:L50]`

### 9.3 Client-Side Key Custody & Volatile Memory
- **Private Key Custody:** The private scalar $s_i$ is held exclusively in **volatile browser component memory** (React `useState(null)` in `OfficerDashboardPage.jsx:L42`). It is never written to `localStorage`, `sessionStorage`, or cookies, and never transmitted over HTTP. Upon component destruction or page reload, $s_i$ is cleared `[VERIFIED: DUAL_OFFICER_GOVERNANCE_CHARTER.md:L68]`.

### 9.4 Encrypted Backup Protocol
Officers must export an offline encrypted backup JSON (`vwd-officer-backup-election-<id>-officer-<i>.json`):
- **Key Derivation Function:** **Argon2id WASM** (`hash-wasm`) with parameters:
  - Memory: $m = 65,536\text{ KiB}$ ($64\text{ MiB}$)
  - Iterations: $t = 3$
  - Parallelism: $p = 4$
  - Salt: 16 cryptographically secure random bytes `[VERIFIED: officerBackup.js:L23-L31]`
- **Cipher:** **AES-256-GCM** with 96-bit (12-byte) random IV and 128-bit (16-byte) authentication tag.
- **Canonical AAD Binding:** `abi.encode(uint256 electionId, uint256 officerId)` (64 bytes) is bound as Additional Authenticated Data. Any attempt to restore a backup under a different election ID or officer seat fails cryptographic decryption `[VERIFIED: officerBackup.js:L59-L70]`.
- **Pre-Allocation Metadata Validation:** To prevent browser memory exhaustion, the backup parser validates all KDF headers before allocating 64 MB of RAM `[VERIFIED: officerBackup.js:L175-L210]`.

### 9.5 Key Loss & 72-Hour TallyStalled Escape Hatch
If either officer permanently loses their device key and backup passphrase:
- **No Backdoor:** No administrative bypass, master key, escrow backdoor, or superuser override exists in the smart contract or backend.
- **Permissionless Lockout:** After voting closes, a 72-hour grace period begins (`tallyDeadline = block.timestamp + 72 hours`). If decryption shares are not submitted within 72 hours, any account may call `markTallyStalled()`. The election transitions to `TallyStalled`, irreversibly locking all shares and tallies. The election is declared void and must be re-run `[VERIFIED: EVotingBallotBoxV2.sol:L406-L415]`.

---

## 10. Database & API Design

`[VERIFIED FROM SOURCE: backend/app/models/, backend/app/routes/voting_v2.py, backend/migrations/versions/86592d28e4c4_fix3_v2_ballot_and_officer_tables.py]`

### 10.1 Database Schema & Entity Relationships
The relational database enforces structural two-plane partitioning across 24 tables. Key tables include:

```
[IDENTITY PLANE]
  ├── users (id, roll_number, email, password_hash, is_active, created_at)
  ├── auth_sessions (id, session_id, user_id, expires_at, idle_expires_at, revoked)
  ├── face_enrollments (id, user_id, embedding_blob, status, is_active)
  ├── wallet_bindings (id, user_id, eth_address, is_verified, signature)
  ├── electoral_rolls (id, student_id, email, is_registered)
  └── voting_authorizations (id, user_id, election_id, session_id, consumed, wallet_verified, face_verified)

[BALLOT PLANE]
  ├── elections (id, election_id, title, candidate_count, start_time, end_time, status)
  ├── candidates (id, election_id, candidate_index, name, position)
  ├── ballot_records [V1] (id, election_id, pseudonym, candidate, sequence, commitment, nonce, state)
  ├── ballot_queue_v2 [V2] (id, election_id, pseudonym, sequence, ciphertexts_json, proof_json, state, tx_hash)
  ├── officer_registrations_v2 [V2] (id, election_id, officer_id, officer_address, pubkey_x, pubkey_y, pop_r_x, pop_r_y, pop_z)
  └── audit_events (id, event_type, actor, details_json, prev_hash, current_hash, timestamp)
```

- **Constraints & Indexes:**
  - `ballot_queue_v2`: Unique constraint on `(election_id, pseudonym, sequence)` `[VERIFIED: ballot_record_v2.py:L18]`.
  - `officer_registrations_v2`: Unique constraint on `(election_id, officer_id)` `[VERIFIED: ballot_record_v2.py:L54]`.
  - Zero foreign keys bridge the Identity Plane (`users`) and the Ballot Plane (`ballot_records` / `ballot_queue_v2`).

### 10.2 API Endpoint Inventory (V2 Focus)

| HTTP Method | Route | Authorization | Purpose / Responsibility |
| :--- | :--- | :---: | :--- |
| `POST` | `/api/v2/officer/register-key` | Officer Address | Registers officer public key share with Schnorr PoP `[VERIFIED: voting_v2.py:L66]` |
| `GET` | `/api/v2/officer/key-status` | Public | Returns registration status and on-chain joint public key `[VERIFIED: voting_v2.py:L146]` |
| `GET` | `/api/v2/officer/aggregate-ciphertexts` | Public | Returns $(A_{\text{agg}}, B_{\text{agg}})$ for client DLEQ share generation `[VERIFIED: voting_v2.py:L180]` |
| `POST` | `/api/v2/voting/cast-ballot` | Authenticated Session | Submits encrypted ballot vector with CDS validity proof `[VERIFIED: voting_v2.py:L215]` |
| `GET` | `/api/v2/voting/status` | Authenticated Session | Returns voter's active sequence and ballot confirmation status `[VERIFIED: voting_v2.py:L312]` |
| `POST` | `/api/v2/officer/submit-decryption-shares`| Officer Address | Submits partial decryption shares and DLEQ proofs `[VERIFIED: voting_v2.py:L356]` |
| `POST` | `/api/v2/tally/finalize` | Admin / Relayer | Recovers DLog tallies off-chain and finalizes on-chain `[VERIFIED: voting_v2.py:L398]` |
| `GET` | `/api/v2/tally/results` | Public | Returns verified on-chain candidate tallies `[VERIFIED: voting_v2.py:L430]` |

---

## 11. Threat Model & Security Analysis

`[VERIFIED FROM SOURCE: docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md:L91-L109, docs/RESIDUAL_RISK_REGISTER.md]`

| Threat Scenario | Defense Classification | Existing Mitigation Mechanism | Defense Type | Residual Risk & Limitations | Test / Code Evidence |
| :--- | :---: | :--- | :---: | :--- | :--- |
| **1. Malicious Administrator** | **PREVENTS & DETECTS** | Admin possesses zero private keys; cannot forge CDS proofs or alter encrypted tallies. | Cryptographic | Admin can delay opening/closing election within governance bounds. | `EVotingBallotBoxV2.sol:L109`, `test_admin.py` |
| **2. One Compromised Officer** | **PREVENTS** | 2-of-2 threshold ElGamal requires both shares $s_1, s_2$ to decrypt. A single officer cannot decrypt ballots. | Cryptographic | Compromised officer can refuse to submit shares (handled by 72-hour `TallyStalled`). | `Milestone6_E2E_Validation.test.js:L152` |
| **3. Two Colluding Officers** | **CANNOT PREVENT** | If both officers pool private keys ($s_{\text{joint}} = s_1 + s_2$), they can decrypt individual ciphertexts. | Procedural / Governance | **Architectural Limitation:** Requires appointing mutually adversarial stakeholders. | `DUAL_OFFICER_GOVERNANCE_CHARTER.md:L18` |
| **4. Officer Key Loss** | **MITIGATES** | Offline Argon2id WASM backup allows scalar recovery from encrypted storage token. | Cryptographic / Operational | If both device memory and backup passphrase are lost, election stalls after 72h. | `officerBackup.js`, `test_milestone6_e2e_frontend.test.mjs` |
| **5. Compromised Voter Device** | **CANNOT PREVENT** | Malware with root/DOM access can observe candidate choices before client-side encryption. | Operational Boundary | **Universal Client Boundary:** General-purpose browsers cannot defend against host OS compromise. | `docs/KNOWN_LIMITATIONS.md:L42-L46` |
| **6. Compromised MetaMask** | **PREVENTS** | Voter wallet signature signs strictly $(electionId, pseudonym, nonce)$, **never candidate choice**. | Cryptographic | Compromised extension could refuse to sign challenge, causing denial of service. | `test_wallet.py`, `Voting.jsx` |
| **7. Network Observer / ISP** | **PREVENTS** | HTTPS/TLS encrypts transport. Ciphertext $(A, B)$ is indistinguishable from random under DDH. | Cryptographic | Packet timing correlation could link IP to submission timestamp. | `test_privacy.py` |
| **8. Timing Correlation** | **MITIGATES** | Asynchronous queueing (`BallotQueueV2`) and relayer batch shuffling break temporal ordering. | Operational | Low-traffic elections with sparse votes may permit statistical correlation. | `EXPERIMENTAL_BENCHMARK_REPORT.md:L217` |
| **9. Voter Coercion** | **CANNOT PREVENT** | A voter who deliberately exports their ElGamal randomness $r_j$ can prove their vote to a coercer. | Protocol Boundary | **No Receipt-Freeness Claim:** The protocol guarantees choice confidentiality, not coercion resistance. | `docs/KNOWN_LIMITATIONS.md:L69` |
| **10. Observable Revoting** | **MITIGATES** | Homomorphic subtraction/addition replaces prior vote. A coerced voter can overwrite their vote later. | Cryptographic | A coercer maintaining continuous physical custody until election close can compel the vote. | `EVotingBallotBoxV2.sol:L288` |
| **11. Malicious Backend Operator**| **PREVENTS & DETECTS** | Backend cannot alter ciphertexts without invalidating CDS ZK proofs. Smart contract rejects forged proofs. | Cryptographic | Malicious operator could drop requests (detected by voter receipt verification). | `test_phase12_tampering_security.py` |
| **12. Database Compromise** | **PREVENTS** | `BallotQueueV2` stores strictly ciphertexts and proofs; zero plaintext candidate choices exist in database. | Cryptographic | Attacker learns submission timestamps and pseudonyms. | `ballot_record_v2.py` |
| **13. Transaction Monitoring** | **PREVENTS** | On-chain ciphertexts are indistinguishable from random BN254 curve points under DDH. | Cryptographic | Transaction gas profiling or block timestamps reveal voting activity volume. | `BN254.sol`, `test_fix3_candidate_privacy.py`|
| **14. Denial of Service (DoS)** | **MITIGATES** | Per-IP rate limiting, session-bound submission, sequence monotonicity enforcement. | Architectural | Volumetric L7 DDoS attacks require upstream cloud WAF/CDN mitigations. | `test_admin_rate_limit_isolation.py` |

---

## 12. Milestone 6 Validation Evidence

`[VERIFIED FROM SOURCE: docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md, blockchain/test/Milestone6_E2E_Validation.test.js]`

Milestone 6 executed a full end-to-end simulated election scenario on an isolated ephemeral Hardhat EVM (`chainId: 1337`).

### 12.1 Simulated Election Configuration
- **Election ID:** `9999` (Contract) / `ELEC_V2_M6_001` (Backend)
- **Candidate Slate ($M = 3$):** Candidate 0, Candidate 1, Candidate 2
- **Officer 01 Address:** `0x70997970C51812dc3A010C7d01b50e0d17dc79C8`
- **Officer 02 Address:** `0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC`
- **Total Simulated Voters:** 5 unique voters ($p_1, \dots, p_5$)
- **Initial Ballots (Sequence 1):**
  - Voter 1 $\to$ Cand 0; Voter 2 $\to$ Cand 1; Voter 3 $\to$ Cand 0; Voter 4 $\to$ Cand 2; Voter 5 $\to$ Cand 1
- **Revotes (Sequence 2):**
  - Voter 1 revotes: Cand 0 $\to$ Cand 2
  - Voter 3 revotes: Cand 0 $\to$ Cand 1
- **Active Ballot Distribution:**
  - Voters 1 & 3: Sequence 2
  - Voters 2, 4, 5: Sequence 1
  - Total Active Ballots: 5

### 12.2 Tally Decryption & Mathematical Match
An independent Python / JS test oracle computed expected tallies and compared them coordinate-by-coordinate with on-chain decryption:

| Candidate | Oracle Expected Tally | Contract Decrypted Tally | Point Equation Status | Result |
| :---: | :---: | :---: | :---: | :---: |
| **Candidate 0** | **0** | **0** | $0 \cdot G = \mathcal{O}$ (Point at Infinity `(0, 0)`) | **EXACT MATCH** |
| **Candidate 1** | **3** | **3** | $3 \cdot G = M_1$ (On-Curve Point) | **EXACT MATCH** |
| **Candidate 2** | **2** | **2** | $2 \cdot G = M_2$ (On-Curve Point) | **EXACT MATCH** |
| **Total Sum** | **5** | **5** | $\sum t_j = 5 \equiv \text{totalActiveBallots}$ | **100% CONSERVED** |

### 12.3 Mined Transaction Gas Profile (Milestone 6 Test Run)

| Operation | Target Function | Block | Gas Consumed | Transaction Hash |
| :---: | :--- | :---: | :---: | :--- |
| **1** | `registerOfficer(Officer 1)` | 368 | 141,407 | `0x12f0b3f0852dfbe01f270eeeb4596571081bea3ec98d6c00efbb2033b176ba87` |
| **2** | `registerOfficer(Officer 2)` | 373 | 160,281 | `0xb115007ae9da99dba44753c8d9af4cea20b1f6e7db189ea952641dd1889ed718` |
| **3** | `openVoting()` | 376 | 28,194 | `0x3da3a2f4b5517989833a5d0e8f15ad7fc37ed4815296f0e19fb4592be5b1a1fd` |
| **4** | `castBallot(Voter 1, Seq 1, Cand 0)` | 378 | 1,023,584 | `0x627fe235eaba006f7bd0ecde2c48cd11df8ca73f13f6df9f003f32849db0f36e` |
| **5** | `castBallot(Voter 2, Seq 1, Cand 1)` | 379 | 806,012 | `0x2c6740f3ce7b4546de9967e5171bfd9cc1fb1f25239ad15b70b722479d1c7752` |
| **6** | `castBallot(Voter 3, Seq 1, Cand 0)` | 380 | 806,072 | `0x1dc03b74e1fe63d7aaedc692affe608ea9040468abd2e8600e1c08000ca8c164` |
| **7** | `castBallot(Voter 4, Seq 1, Cand 2)` | 381 | 806,036 | `0xe803e08d491d7be27d1cdf37668efa649ffa0d44efc2d729c94fe56528372b42` |
| **8** | `castBallot(Voter 5, Seq 1, Cand 1)` | 382 | 806,024 | `0xe3a60121ccb17fec2208c99c1281bc39fb26cc69715b7179d99cf56f208cc929` |
| **9** | `castBallot(Voter 1 Revote: Cand 0 -> Cand 2, Seq 2)` | 388 | 556,122 | `0xb6ba0867661fabf10309c04b79b194b7a43583a3a740ebe3e56f94ecbd832782` |
| **10** | `castBallot(Voter 3 Revote: Cand 0 -> Cand 1, Seq 2)` | 389 | 556,122 | `0xbca0880c99b3e55a79b512176cf16c18b7e43c286a76bac90ee49a7e5c2428fe` |
| **11** | `closeVoting()` | 390 | 73,089 | `0xb62f6a840bfc73e5231c5595068a24bcd124cfcb9c33fcc9153171e73d0eb4b5` |
| **12** | `submitDecryptionShares(Officer 1)` | 392 | 343,540 | `0x83b411d713d5298d43c5704853bdd2cad1d196644f9e79ef384c02138b41aec8` |
| **13** | `submitDecryptionShares(Officer 2)` | 396 | 347,793 | `0x57d610e78369c2da81fdc8f2e567dc491369758ca320359e326f1ec042ea0619` |
| **14** | `finalizeTally([0, 3, 2])` | 400 | 152,048 | `0x3fdf7dbc1a24faf067313a1bffbbb2f0d24b8ab3c990144ffe02e9182ff21c5e` |
| **15** | `markTallyStalled()` (72h test branch) | 410 | 30,242 | `0x8a13a8cceda2eedb9c3e6110d24aac2639a9f10421770dcb06547b413b256fa3` |

---

## 13. Milestone 7 Security Review & Remediation

`[VERIFIED FROM SOURCE: docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md, docs/PHASE16_FINAL_PROJECT_FREEZE.md]`

### 13.1 Audit Findings & Remediations

| Finding ID | Component | Severity | Root Cause Description | Remediation Implemented | Verification Evidence |
| :---: | :--- | :---: | :--- | :--- | :--- |
| **SEC-01** | Database Migrations | **Medium** | Missing Alembic migration revision for V2 tables (`ballot_queue_v2`, `officer_registrations_v2`). | Created revision `86592d28e4c4`. Verified upgrade, downgrade, and re-upgrade cycles. | Both migration tests passed: `test_initial_migration_creates_the_full_schema` & `test_migration_and_orm_schemas_agree` |
| **SEC-02** | Frontend Viewport | **Low** | Mobile iPhone 14 (390px) horizontal layout overflow of 47px. | Applied `overflow-x: hidden; max-width: 100vw;` in `index.css` and clamped containers in `Pages.css`. | Playwright test `test_step4_responsive_viewports_no_overflow` confirmed 0px overflow across 320px–430px. |
| **SEC-03** | Test Harness | **Low** | `test_on_chain_provisioning_and_recovery.py` mock return type was raw `MagicMock` instead of transaction dict. | Specified `.build_transaction()` mock return value as transaction dictionary. | All 12 provisioning and recovery tests passed cleanly. |
| **SEC-04** | Test Fixture | **Low** | `test_phase12_tampering_security.py` checked sandbox election against live RPC node on port 8545. | Decoupled isolated sandbox test from live node via unittest patch. | All 6 tampering detection tests passed cleanly. |
| **SEC-05** | Dependencies | **Low** | Missing production WSGI server (`waitress`) in test environment. | Verified `waitress==3.0.0` in `requirements.txt` and active virtualenv. | All 17 WSGI proxy tests passed cleanly. |
| **SEC-06** | Gas Bounds | **Info** | Candidate count scalability bound on standard EVM layers ($M \le 10$). | Formally documented gas limits in benchmarks; enforced contract check $M \le 10$. | Architecturally mitigated and codified in `BN254CDSVerifier.sol:L21`. |

### 13.2 Nature of the Security Review
The security review was an **agent-assisted, autonomous comprehensive audit** conducted by the Antigravity Autonomous Security Core. It was **not** an external third-party commercial audit (e.g., Trail of Bits, OpenZeppelin). This distinction must be transparently reported in the research paper's methodology section.

---

## 14. Experimental Setup & Performance Results

`[VERIFIED FROM SOURCE: EXPERIMENTAL_BENCHMARK_REPORT.md, docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md:L112-L153]`

### 14.1 Hardware & Environment Configuration
- **Host OS:** Windows 11 Enterprise (Version 10.0.26200-SP0)
- **CPU:** Intel64 Family 6 Model 186 Stepping 2 (Intel Core i7-13700H, 8 Performance + 6 Efficient Cores, 20 Logical Threads @ 2.50 GHz base)
- **System Memory:** 16.00 GB DDR5 RAM
- **Runtimes:** Python 3.11.9 (64-bit AMD64), Node.js v24.19.0, Solidity 0.8.19 (Hardhat 2.29.1)
- **Blockchain:** Local Hardhat EVM (`chainId: 1337`), automining enabled `[VERIFIED: EXPERIMENTAL_BENCHMARK_REPORT.md:L37-L54]`.

### 14.2 Performance Measurement Summary

#### A. Client-Side Cryptographic Latency (Browser Proof Engine, $M = 3$ Candidates)
- **Mean Proof Generation Time:** **42.01 ms** (Median: 44.04 ms, p95: 51.31 ms, $n=25$)
- **Memory Allocation:** $< 12\text{ MB}$ transient heap during proof generation.

#### B. Off-Chain Merkle Tree Construction Performance (RFC 6962 Binary Tree)
- $N = 3$ leaves: **0.0071 ms** ($\text{median } 0.0049\text{ ms}$)
- $N = 10$ leaves: **0.0167 ms** ($\text{median } 0.0163\text{ ms}$)
- $N = 50$ leaves: **0.0815 ms** ($\text{median } 0.0803\text{ ms}$)
- $N = 100$ leaves: **0.1665 ms** ($\text{median } 0.1588\text{ ms}$)
- $N = 500$ leaves: **0.8984 ms** ($\text{median } 0.8368\text{ ms}$, sub-millisecond at scale)

#### C. Merkle Inclusion Proofs ($N = 500$ Leaves, Tree Depth 9)
- **Proof Generation Latency:** **0.4381 ms**
- **Client Verification Latency:** **0.0158 ms** (15.8 microseconds)
- **Tamper Rejection Rate:** **100% (150/150)** across mutated siblings, fake commitments, and altered roots.

#### D. Smart Contract Gas Consumption Summary

| Function | Conditions | Gas (Mean) | Gas (Median) |
| :--- | :--- | :---: | :---: |
| `EVotingBallotBox.sol::castBallot` (V1) | First vote (cold storage initialization) | 135,459 | 135,459 |
| `EVotingBallotBox.sol::castBallot` (V1) | Revote (warm storage update) | 101,259 | 101,259 |
| `EVotingBallotBox.sol::anchorAudit` (V1) | Checkpoint commit | 85,218 | 95,445 |
| `EVotingBallotBoxV2.sol::registerOfficer` | Officer 1 (Setup) | 141,407 | 141,407 |
| `EVotingBallotBoxV2.sol::registerOfficer` | Officer 2 (Completes key) | 160,281 | 160,281 |
| `EVotingBallotBoxV2.sol::castBallot` (V2) | Initial vote ($M=3$, 3 CDS + 1 Sum proof) | 849,512 | 806,036 |
| `EVotingBallotBoxV2.sol::castBallot` (V2) | Revote ($M=3$, subtraction + addition) | 555,109 | 556,122 |
| `EVotingBallotBoxV2.sol::submitDecryptionShares` | Officer shares + 3 DLEQ proofs | 345,667 | 345,667 |
| `EVotingBallotBoxV2.sol::finalizeTally` | 3 candidates (incl. inf check) | 152,048 | 152,048 |

#### E. Bounded Discrete Logarithm Recovery Latency ($M_j = t_j \cdot G$)
- $N = 5$ voters: **0.21 ms**
- $N = 100$ voters: **6.98 ms**
- $N = 1,000$ voters: **57.79 ms**
- $N = 10,000$ voters: **659.36 ms** (Sub-second recovery for 10,000 votes)

#### F. Backend Submission & Relayer Shuffling
- **Backend Ballot Queueing Latency:** **47.48 ms** ($\text{median } 46.00\text{ ms}$, $n=35$)
- **Relayer Permutation Latency (Batch of 10):** **0.0194 ms**
- **Normalized Inversion Distance:** **0.5022** (Matches theoretical uniform random permutation of $0.5000$).

---

## 15. Test Results & Quality Assurance

`[VERIFIED FROM SOURCE: docs/PHASE16_FINAL_PROJECT_FREEZE.md:L42-L60]`

### 15.1 Regression Verification Matrix
Following the final remediation pass, all test suites were executed cleanly:

| Test Suite Scope | Test Runner Command | Total Tests | Passed | Failed | Execution Time |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Frontend Unit & Integration** | `node --test tests/*.test.mjs` | 225 | **225** | 0 | 33.25s |
| **Smart Contracts (V1 + V2)** | `npx hardhat test` | 137 | **137** | 0 | 21.00s |
| **V2 Backend Cryptography & Integration** | `pytest test_milestone6_e2e_backend.py test_fix3_v2_crypto.py test_fix3_v2_backend_integration.py` | 26 | **26** | 0 | 18.95s |
| **Database Migrations** | `pytest test_database.py` | 13 | **13** | 0 | 24.82s |
| **Provisioning & Recovery** | `pytest test_on_chain_provisioning_and_recovery.py` | 12 | **12** | 0 | 11.89s |
| **Sandboxed Tampering Detection** | `pytest test_phase12_tampering_security.py` | 6 | **6** | 0 | 8.09s |
| **WSGI Proxy & Server Hardening** | `pytest test_wsgi_proxy_logging_hardening.py` | 17 | **17** | 0 | 1.15s |
| **Playwright E2E Isolation** | `pytest test_phase14_e2e_playwright.py -k test_e2e_14_03_null_revote` | 1 | **1** | 0 | 5.66s |
| **Mobile Viewport Overflow E2E** | `pytest test_phase16_step4_browser_e2e.py -k test_step4_responsive_viewports_no_overflow` | 1 | **1** | 0 | 17.33s |
| **Milestone 6 Isolated Full Lifecycle** | `npx hardhat test test/Milestone6_E2E_Validation.test.js` | 38 | **38** | 0 | 4.00s |
| **TOTAL VERIFIED REGRESSION TESTS** | **Full System Cross-Layer** | **476** | **476** | **0** | **146.14s** |

### 15.2 Note on Test Totals
The **476 tests** reported above represent the targeted, verified regression suites executed during Milestone 7 freeze. When executing the entire historical collection of all unit, legacy Phase 1–15 tests across the repository (`pytest tests/ -q`), 1,051 tests are collected `[VERIFIED: docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md:L254]`.

---

## 16. Database Hash Discrepancy Investigation

`[VERIFIED FROM SOURCE: Physical File Inspection, PowerShell Get-FileHash & Get-Item]`

### 16.1 The Discrepancy
A discrepancy was identified between the database SHA-256 hashes recorded in the Milestone 6 report and the Milestone 7 / Project Freeze reports:
- **Milestone 6 Report (`docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md:L15-L18`):**
  - Recorded Size: `565,248 bytes`
  - Recorded SHA-256: `0cabf5f8a29e94070ac34dbde8a0008785a1aa0375666828e3c2da4b3356dea7`
- **Milestone 7 / Project Freeze Report (`docs/PHASE16_FINAL_PROJECT_FREEZE.md:L138`):**
  - Recorded Size: `520,192 bytes`
  - Recorded SHA-256: `cac297df78d6961ff190c2be16d480f49bcde8ab10fdc9abd2013b0089432ca9`

### 16.2 Empirical Findings from Filesystem Forensics
1. **Actual On-Disk State of `backend/instance/voting.db`:**
   - Physical File Path: `backend\instance\voting.db`
   - File Size: **520,192 bytes**
   - Current SHA-256 Hash: **`CAC297DF78D6961FF190C2BE16D480F49BCDE8AB10FDC9ABD2013B0089432CA9`**
   - Creation Timestamp: `2026-10-07 14:59:48 UTC`
   - Last Modification Timestamp: **`2026-10-29 01:49:27 UTC`**
2. **Analysis of File Timestamps:**
   The last modification timestamp of `backend/instance/voting.db` is **October 29, 2026**. Milestone 6 and Milestone 7 were both conducted on **November 1, 2026**. 
   Therefore, the physical file `backend/instance/voting.db` was **never written to or modified** at any time during Milestone 6 or Milestone 7.
3. **Root Cause Analysis:**
   - In Milestone 6, all backend integration tests were configured in `conftest.py` to create isolated ephemeral SQLite databases (`tempfile.mkstemp(prefix='votest_')`).
   - The hash `0cabf5f8...` and file size `565,248 bytes` recorded in the Milestone 6 report represent an **ephemeral test database snapshot** measured during automated testing that was erroneously transcribed as the baseline hash for `voting.db`.
   - The true underlying V1 development database (`voting.db`, 520,192 bytes) has remained completely immutable since October 29, 2026, with genuine SHA-256 hash `cac297df...`.
   - **Conclusion:** There was no tampering or corruption of the V1 database. The discrepancy was an artifact of test database snapshot recording in the Milestone 6 documentation.

---

## 17. Literature & Related Work

`[VERIFIED BIBLIOGRAPHIC REFERENCES]`

The following verified academic publications and technical standards form the theoretical foundation of Vote Without Doubt:

1. **RFC 6962 (Certificate Transparency):**
   - B. Laurie, A. Langley, and E. Kasper, "Certificate Transparency," *IETF RFC 6962*, June 2013. DOI: `10.17487/RFC6962`.
   - *Relevance to VWD:* Dictates binary Merkle tree construction rules ($\mathtt{0x00}$ leaf prefix, $\mathtt{0x01}$ internal node prefix, and power-of-two odd-leaf splitting rule without leaf duplication).
2. **Cramer-Damgård-Schoenmakers (CDS) Disjunctive Proofs:**
   - R. Cramer, I. Damgård, and B. Schoenmakers, "Proofs of Partial Knowledge and Simplified Design of Witness Hiding Protocols," in *Advances in Cryptology — CRYPTO '94*, Springer LNCS vol. 839, pp. 174–187, 1994. DOI: `10.1007/3-540-48329-2_13`.
   - *Relevance to VWD:* Underpins the 1-of-2 disjunctive zero-knowledge validity proofs ensuring encrypted ballot bits are $v_j \in \{0, 1\}$.
3. **Chaum-Pedersen Discrete Logarithm Equality (DLEQ):**
   - D. Chaum and T. P. Pedersen, "Wallet Databases with Observers," in *Advances in Cryptology — CRYPTO '92*, Springer LNCS vol. 740, pp. 89–105, 1993. DOI: `10.1007/3-540-48071-4_7`.
   - *Relevance to VWD:* Protocol for officer partial decryption share verification ($\log_G(Y_i) = \log_{A_{\text{agg}}[j]}(D_i[j])$).
4. **Schnorr Identification / Proof-of-Possession:**
   - C. P. Schnorr, "Efficient Signature Generation by Smart Cards," *Journal of Cryptology*, vol. 4, no. 3, pp. 161–174, 1991. DOI: `10.1007/BF00196725`.
   - *Relevance to VWD:* Prevents rogue-key attacks during officer public key registration ($z \cdot G = R + e \cdot Y$).
5. **Additive ElGamal Cryptosystem:**
   - T. ElGamal, "A Public Key Cryptosystem and a Signature Scheme Based on Discrete Logarithms," *IEEE Transactions on Information Theory*, vol. 31, no. 4, pp. 469–472, 1985. DOI: `10.1109/TIT.1985.1057074`.
   - *Relevance to VWD:* Homomorphic encryption enabling tally aggregation via elliptic curve point addition.
6. **ArcFace Biometric Representation:**
   - J. Deng, J. Guo, N. Xue, and S. Zafeiriou, "ArcFace: Additive Angular Margin Loss for Deep Face Recognition," in *IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)*, 2019, pp. 4690–4699. DOI: `10.1109/CVPR.2019.00482`.
   - *Relevance to VWD:* Generates 512-dimensional vector embeddings for student biometric matching.
7. **Argon2 Key Derivation Function:**
   - A. Biryukov, D. Dinu, and A. Khovratovich, "Argon2: New Generation of Memory-Hard Functions for Password Hashing and Key Derivation," in *IEEE European Symposium on Security and Privacy (EuroS&P)*, 2016, pp. 292–302. DOI: `10.1109/EuroSP.2016.31`.
   - *Relevance to VWD:* Applied in client-side officer backup encryption ($m=64\text{ MiB}, t=3, p=4$).
8. **Helios Voting System:**
   - B. Adida, "Helios: Web-based Open-Audit Voting," in *17th USENIX Security Symposium*, 2008, pp. 335–348.
   - *Relevance to VWD:* Foundational reference for web-based verifiable voting; VWD extends this model by moving homomorphic revoting directly on-chain.
9. **Belenios Verifiable Voting:**
   - V. Cortier, P. Gaudry, and S. Glondu, "Belenios: A Verifiable Voting System," in *Design, Codes and Cryptography*, vol. 77, pp. 663–679, 2015. DOI: `10.1007/s10623-015-0097-4`.
   - *Relevance to VWD:* Baseline for threshold mixnet architectures; contrasted with VWD's on-chain homomorphic revoting approach.

---

## 18. Defensible Research Contributions

Based on the implemented and tested codebase, the following contributions are defensible for an IEEE or ACM manuscript:

1. **Integrated Multi-Factor Biometric and Blockchain Identity Gate:** A practical demonstration of combining institutional password+OTP credentials, ArcFace deep facial embedding matching with interactive 3D yaw liveness tracking, and Ethereum EIP-191 signatures into a unified server-authoritative gate for collegiate voting.
2. **Forward-Secure Dual-Plane Relational Architecture:** Demonstrating strict Identity Plane vs. Ballot Plane isolation with per-election deterministic HMAC pseudonyms, where forward secrecy is mathematically established by shredding the symmetric election key $K_E$ at election closure.
3. **Atomic Homomorphic Revoting with Sequence Monotonicity:** A novel on-chain smart contract pattern where revoted ballots atomically subtract prior encrypted choices and add new choices ($C_{\text{agg}} \leftarrow C_{\text{agg}} - C_{\text{prev}} + C_{\text{new}}$), ensuring the on-chain tally reflects only the voter's latest choice while maintaining sequence monotonicity.
4. **Canonical Non-Circular CDS Ballot Proofs on BN254:** Complete implementation of non-circular Cramer-Damgård-Schoenmakers zero-knowledge 1-of-2 validity and vector sum-to-one proofs on the BN254 elliptic curve, executing within standard EVM gas limits ($\approx 806,000$ gas for $M=3$).
5. **Institutional Dual-Officer Threshold Governance:** A complete operational protocol balancing student representation and faculty oversight, enforcing 2-of-2 threshold ElGamal tallying with verified Chaum-Pedersen DLEQ proofs, bounded discrete-log recovery, client-side Argon2id backups with canonical ABI AAD binding, and a permissionless 72-hour `TallyStalled` lockout.
6. **Empirical Open-Source Evaluation:** Concrete reproducible benchmarks measuring Merkle tree generation, inclusion verification, gas consumption across 28 mined transactions, relayer permutation entropy, and authentication latency.

---

## 19. Limitations & Explicit Non-Claims

`[HONEST ACADEMIC DISCLOSURES]`

To maintain high scientific integrity, the manuscript must explicitly disclose the following limitations:

1. **No Complete Receipt-Freeness or Coercion Resistance:**
   Under client-side threshold ElGamal encryption, any voter who deliberately retains their encryption randomness $r_j$ can mathematically prove their choice to an external party. **The protocol does not claim receipt-freeness or complete coercion resistance.** Coercion mitigation is provided strictly by **revoting sequence monotonicity**, allowing voters to overwrite a coerced vote later, provided the coercer does not maintain continuous physical custody until election closure `[VERIFIED: DUAL_OFFICER_GOVERNANCE_CHARTER.md:L114]`.
2. **Unmeasured Biometric Accuracy Metrics:**
   While the ArcFace pipeline and interactive 3D head yaw tracking are fully implemented and verified in code, **empirical False Acceptance Rate (FAR), False Rejection Rate (FRR), and Equal Error Rate (EER) were NOT measured** due to the absence of an ethically gathered, multi-subject collegiate evaluation dataset.
3. **Presentation Attack Detection (PAD) in Shadow Mode:**
   Anti-spoofing models operate in telemetry mode (`FACE_PAD_MODE = 'shadow'`) and do not actively reject spoofing attacks. No Attack Presentation Classification Error Rate (APCER) or Bona Fide Presentation Classification Error Rate (BPCER) is claimed `[VERIFIED: EXPERIMENTAL_BENCHMARK_REPORT.md:L242-L245]`.
4. **Endpoint Device Security Boundary:**
   Malware or rootkits on the voter's device with screen recording or DOM inspection capabilities can observe candidate choices prior to encryption. General-purpose client hardware remains an unavoidable trust boundary `[VERIFIED: docs/KNOWN_LIMITATIONS.md:L42-L46]`.
5. **Dual-Officer Collusion:**
   If Officer 01 and Officer 02 deliberately pool their private scalars ($s_{\text{joint}} = s_1 + s_2$), they can decrypt individual ciphertexts on-chain. Cryptographic threshold enforcement prevents unilateral decryption, but cannot mathematically prevent mutual collusion between both keyholders `[VERIFIED: DUAL_OFFICER_GOVERNANCE_CHARTER.md:L113]`.
6. **Candidate Count Gas Scalability:**
   On-chain proof verification costs scale linearly with candidate count $M$ ($\sim 806,000$ gas for $M=3$, approaching $\sim 2.4\text{M}$ gas for $M=10$). The contract enforces $M \le 10$. Larger candidate slates must be partitioned or deployed on Layer-2 rollups `[VERIFIED: BN254CDSVerifier.sol:L21]`.
7. **Local EVM Evaluation Host:**
   All gas measurements and smart contract interactions reflect mined transactions on a local Hardhat RPC node. Public peer-to-peer network propagation, transaction memory-pool bidding, and chain reorganizations were not present `[VERIFIED: EXPERIMENTAL_BENCHMARK_REPORT.md:L278]`.

---

## 20. Recommended Research Paper Structure

For an IEEE Transactions, IEEE Access, or ACM conference submission, the following 8-section manuscript structure is recommended:

- **Section I: Introduction**
  - Collegiate civic context, challenges of paper ballots and opaque web portals.
  - The security/privacy trilemma in campus elections.
  - High-level overview of Vote Without Doubt (V1 + V2).
  - Summary of contributions and paper organization.
- **Section II: Related Work & Background**
  - Evolution of verifiable e-voting: Helios, Belenios, Civitas.
  - Multi-factor authentication & biometrics in e-governance.
  - Threshold cryptography and non-interactive zero-knowledge proofs.
  - Blockchain smart contracts as verifiable state machines.
- **Section III: Threat Model & System Goals**
  - Adversarial model (malicious admins, compromised endpoints, curious officers, network eavesdroppers).
  - Security definitions: Ballot Secrecy, Individual Verifiability, Universal Verifiability, Eligibility, Forward Secrecy.
  - Explicit non-claims (receipt-freeness, biometric error rates).
- **Section IV: System Architecture & Multi-Factor Gate**
  - Two-plane relational partitioning (Identity vs. Ballot Planes).
  - Three-factor gate: Password+OTP, ArcFace cosine matching, MetaMask EIP-191.
  - Asynchronous relayer shuffling (Kendall-tau entropy evaluation).
  - V1 audit-chain anchoring and RFC 6962 Merkle tree proofs.
- **Section V: V2 Cryptographic Protocol (Threshold ElGamal & CDS Proofs)**
  - Curve parameters over BN254 $\mathbb{G}_1$.
  - Dual-officer key generation with Schnorr PoP.
  - Non-circular Fiat-Shamir CDS 1-of-2 and vector sum-to-one NIZK proofs.
  - Atomic homomorphic revoting equation ($C_{\text{agg}} \leftarrow C_{\text{agg}} - C_{\text{prev}} + C_{\text{new}}$).
  - Chaum-Pedersen DLEQ share verification and bounded discrete-log recovery.
- **Section VI: Governance & Operational Key Custody**
  - Student Union vs. Academic Oversight institutional separation.
  - Technical identity vs. institutional identity boundaries.
  - Volatile browser memory custody and Argon2id WASM AES-256-GCM backups with canonical AAD binding.
  - 72-hour `TallyStalled` permissionless lockout.
- **Section VII: Implementation & Experimental Evaluation**
  - Implementation breakdown (Solidity, Python Flask, React Vite).
  - Milestone 6 E2E validation results (5 voters, 3 candidates, 2 revotes).
  - Micro-benchmarks: Merkle construction, inclusion proofs, DLog lookup scaling, auth latency.
  - Gas consumption analysis from mined transactions.
  - Database forensic analysis and resolution of hash discrepancy.
- **Section VIII: Discussion, Limitations & Conclusion**
  - Discussion of trade-offs: on-chain verification gas vs. off-chain bulletin boards.
  - Honest disclosure of unmeasured biometrics and lack of receipt-freeness.
  - Future work: Layer-2 rollups, post-quantum threshold schemes, hardware enclave integration.
  - Concluding remarks.

---

## 21. Missing Evidence & Items Requiring Human Confirmation

The external research paper writer should be aware of the following items that cannot be derived from code alone and require human confirmation:

1. **Formal Institution & Campus Identity:** The repository uses synthetic student USNs and institutional placeholders (`@student.college.edu`, `@faculty.college.edu`). The human authors must confirm whether the paper will name a specific academic institution or describe the deployment as an anonymized collegiate campus.
2. **Author Names, Affiliations, and Funding Acknowledgments:** Author metadata, institutional email addresses, grant numbers, or student department details must be supplied by the human research team.
3. **Biometric Evaluation Plans:** If the target journal insists on empirical biometric accuracy numbers (FAR/FRR/EER), the authors must state whether an ethical IRB-approved human face trial is planned as future work or if the current scope is strictly algorithmic latency profiling.
4. **Target Publication Venue Formatting:** Formatting templates (IEEE Tran LaTeX vs. ACM Master Template) must be chosen by the authors before manuscript rendering.

---

## 22. Exact Source File & Document Paths

The following repository files contain the primary evidence supporting this report:

### Smart Contracts
- [`blockchain/contracts/EVotingBallotBox.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBox.sol) (V1 Contract, 187 lines, SHA256: `d4e70dd30b6469c6111a4456a2c6732fa07bf3038ee0285859f17dd6646856af`)
- [`blockchain/contracts/EVotingBallotBoxV2.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/EVotingBallotBoxV2.sol) (V2 Threshold Ballot Box, 489 lines)
- [`blockchain/contracts/BN254.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/BN254.sol) (BN254 G1 Elliptic Curve Library, 162 lines)
- [`blockchain/contracts/BN254CDSVerifier.sol`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/blockchain/contracts/BN254CDSVerifier.sol) (Non-Circular CDS NIZK Verifier, 265 lines)

### Backend Cryptography, Services & Models
- [`backend/app/services/bn254_crypto.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/bn254_crypto.py) (BN254 Python Engine, 631 lines)
- [`backend/app/services/blockchain_v2_service.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/blockchain_v2_service.py) (Web3 V2 Contract Interface, 289 lines)
- [`backend/app/routes/voting_v2.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/routes/voting_v2.py) (V2 API Endpoints, 456 lines)
- [`backend/app/models/ballot_record_v2.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/models/ballot_record_v2.py) (V2 Database Models, 76 lines)
- [`backend/app/services/voting_service.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/voting_service.py) (V1 Multi-Factor Voting Service, 660 lines)
- [`backend/app/security/merkle.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/security/merkle.py) (RFC 6962 Binary Merkle Tree, 236 lines)
- [`backend/app/security/pseudonym.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/security/pseudonym.py) (Forward-Secure Pseudonym Derivation, 84 lines)
- [`backend/app/services/face_engine.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/services/face_engine.py) (ArcFace & 3D Yaw Liveness Engine, 285 lines)
- [`backend/app/relayer/relayer.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/app/relayer/relayer.py) (Asynchronous Shuffling Relayer, 342 lines)
- [`backend/migrations/versions/86592d28e4c4_fix3_v2_ballot_and_officer_tables.py`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/backend/migrations/versions/86592d28e4c4_fix3_v2_ballot_and_officer_tables.py) (Alembic V2 Migration Revision)

### Frontend Cryptography & Components
- [`frontend/src/utils/bn254_client.js`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/utils/bn254_client.js) (Client BN254 & CDS Proof Generator, 647 lines)
- [`frontend/src/utils/officerBackup.js`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/utils/officerBackup.js) (Argon2id WASM AES-256-GCM Backup Engine, 372 lines)
- [`frontend/src/pages/admin/OfficerDashboardPage.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/pages/admin/OfficerDashboardPage.jsx) (Officer Dashboard & Volatile Custody, 680 lines)
- [`frontend/src/components/VotingV2.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/components/VotingV2.jsx) (Client Voting Component, 412 lines)
- [`frontend/src/pages/public/ResultsV2Page.jsx`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/frontend/src/pages/public/ResultsV2Page.jsx) (Verified Public Results Interface, 280 lines)

### Authoritative Documentation & Audit Reports
- [`docs/PHASE16_FINAL_PROJECT_FREEZE.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/PHASE16_FINAL_PROJECT_FREEZE.md) (Final Freeze & System Lock Report)
- [`docs/DUAL_OFFICER_GOVERNANCE_CHARTER.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/DUAL_OFFICER_GOVERNANCE_CHARTER.md) (Dual-Officer Institutional Governance Charter)
- [`docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/PHASE16_MILESTONE7_SECURITY_REVIEW.md) (Milestone 7 Independent Security Review)
- [`docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/PHASE16_MILESTONE6_VALIDATION_REPORT.md) (Milestone 6 Isolated Validation Report)
- [`EXPERIMENTAL_BENCHMARK_REPORT.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/EXPERIMENTAL_BENCHMARK_REPORT.md) (Empirical Benchmark Report)
- [`docs/KNOWN_LIMITATIONS.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/KNOWN_LIMITATIONS.md) (Catalog of Known Limitations & Terminology Guide)
- [`docs/RESIDUAL_RISK_REGISTER.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/docs/RESIDUAL_RISK_REGISTER.md) (Residual Risk Register)

---

**FINAL STATUS:**  
`RESEARCH PAPER EVIDENCE EXTRACTION COMPLETE — AWAITING MANUSCRIPT PREPARATION`
