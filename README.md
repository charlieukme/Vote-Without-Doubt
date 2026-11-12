# Vote Without Doubt (VWD)

**AI & Blockchain-Based Secure E-Voting System for College Elections**

> **ACADEMIC PROTOTYPE — NOT A LEGALLY BINDING ELECTION SYSTEM.**
> This repository is a university/college project prototype built for study, demonstration, and academic evaluation. It is not certified, not production-hardened, and must not be relied upon to run statutory, public, or legally binding governmental elections.

---

## 1. What This Project Is

**Vote Without Doubt (VWD)** is an academic prototype of a privacy-preserving electronic voting system designed specifically for college student elections. VWD bridges modern zero-knowledge threshold cryptography with accessible campus authentication factors, providing end-to-end verifiable ballot tallying on an EVM blockchain while preserving ballot secrecy and preventing double-voting.

### Core Objectives
1. **Verifiable Tallying:** Ballots are accumulated homomorphically on-chain; anyone can verify the mathematical proof that the published tally equals the sum of certified ballots.
2. **Ballot Secrecy via Threshold Cryptography (V2):** Individual candidate choices are never stored in plaintext on disk, in databases, or on the blockchain. Ballots are encrypted under an additive threshold ElGamal scheme over the BN254 curve and decrypted only in aggregate.
3. **Robust Voter Eligibility:** Multi-factor identity verification combining electoral roll lookup, email OTP, desktop MetaMask wallet binding, and facial liveness challenges.
4. **Separation of Concerns:** Strict architectural separation between the **Identity Plane** (who is eligible to vote) and the **Ballot Plane** (encrypted votes and blockchain tallies).
5. **Dual-Officer Governance:** Election keys and decryption require cooperative action from two independent election officers using Chaum-Pedersen zero-knowledge proofs.

---

## 2. Technology Stack

| Layer | Technology | Function |
|---|---|---|
| **Frontend** | React 19, Vite 8, hash-wasm | Responsive voter portal, client-side BN254 scalar generation, CDS proof computation, MetaMask integration |
| **Backend** | Python 3.11+, Flask 3, SQLAlchemy 2 | REST API, session management, factor aggregation, relayer service, audit logging, results exports |
| **Database** | MySQL 8 (Production) / SQLite (Automated Tests) | Identity records, electoral rolls, encrypted biometric templates, ballot queues, audit logs |
| **Migrations** | Alembic / Flask-Migrate | Authoritative database versioning and schema evolution |
| **Smart Contracts** | Solidity 0.8.19, Hardhat, Ethers.js v6 | `EVotingBallotBoxV2.sol`, `BN254.sol`, `BN254CDSVerifier.sol` |
| **Blockchain** | Local EVM node (Ganache / Hardhat Node, Chain ID 1337) | On-chain homomorphic ciphertext accumulation, officer key registry, DLEQ verification |
| **Biometrics** | InsightFace 2.1 (SCRFD + ArcFace w600k_r50) | Facial landmark detection, 512-dim embedding extraction, challenge-response liveness |
| **Wallet** | MetaMask (Desktop browser extension) | EIP-191 `personal_sign` cryptographic possession proof |

---

## 3. System Architecture & Two-Plane Separation

```
                    +--------------------------------------------+
                    |           React + Vite Frontend            |
                    |  - Client BN254 Curve Math (CDS Proofs)    |
                    |  - MetaMask personal_sign                  |
                    |  - Interactive Liveness Webcam Capture     |
                    +---------------------+----------------------+
                                          | HTTPS / REST + CSRF
                    +---------------------v----------------------+
                    |             Flask Backend API              |
                    |  - Session / OTP / CSRF Security           |
                    |  - ArcFace Template & Liveness Engines     |
                    |  - Atomic VotingAuthorization Service      |
                    +-------------+----------------+-------------+
                                  |                |
             +--------------------+                +--------------------+
             | (Strict Isolation)                                       |
+------------v------------+                                +------------v------------+
|     IDENTITY PLANE      |                                |       BALLOT PLANE      |
|  - Users & Sessions     |                                |  - BallotQueueV2        |
|  - Electoral Roll       |                                |  - Encrypted Ciphertexts|
|  - Wallet Bindings      |                                |  - Non-Circular Proofs  |
|  - Face Embeddings      |                                |  - Derived Pseudonyms   |
|  - VotingAuthorizations |                                |  - Audit Event Chains   |
+-------------------------+                                +------------+------------+
                                                                        |
                                                           +------------v------------+
                                                           |     Backend Relayer     |
                                                           +------------+------------+
                                                                        | JSON-RPC (1337)
                                                           +------------v------------+
                                                           | EVotingBallotBoxV2.sol  |
                                                           |  - BN254 Cryptography   |
                                                           |  - CDS Proof Verifier   |
                                                           |  - Dual-Officer Shares  |
                                                           |  - On-Chain Tally       |
                                                           +-------------------------+
```

### Architectural Principles
- **No Shared Foreign Keys:** Tables in the Identity Plane never reference tables in the Ballot Plane.
- **No Plaintext Choices:** The backend never receives, logs, or stores unencrypted vote selections.
- **V1 Deprecation:** Legacy plaintext voting (`EVotingBallotBox.sol`, `POST /api/voting/submit`) is permanently disabled with HTTP 410 Gone. The V1 relayer is locked fail-closed at the transaction boundary.

---

## 4. Student & Officer User Flows

### A. Student Registration
1. **Eligibility Check:** Student enters College ID (USN). The system validates eligibility against the pre-imported `ElectoralRoll`.
2. **Credential Setup:** Student provides password (hashed with Argon2id) and college email address.
3. **Email OTP:** Server issues a 6-digit cryptographic OTP (5-minute TTL, rate-limited).
4. **Biometric Enrollment:** Camera captures student face. SCRFD detects face landmarks, ArcFace extracts a 512-dimensional embedding vector, encrypted at rest using Fernet envelope encryption (`FACE_ENCRYPTION_KEY`).
5. **Wallet Binding:** MetaMask requests `personal_sign` on a server-issued challenge nonce. Server recovers the signer address and saves a verified `WalletBinding`.

### B. Student Voting Lifecycle (V2 Protocol)
1. **Election Selection:** Voter selects an active `OPEN` election.
2. **Authorization Request:** Client calls `POST /api/voting/authorize`. Backend verifies the user session and issues a single-use `VotingAuthorization` (5-minute TTL).
3. **Factor Verification:**
   - **Wallet Factor:** Verified server-side from `WalletBinding`.
   - **Face Factor:** Server generates an interactive random liveness sequence (e.g., `LEFT` / `RIGHT`). Student executes the motion; backend validates landmark displacement and issues a single-use `FaceChallenge` bound to the authorization.
   - Client calls `POST /api/voting/mark-factors`. The backend atomically verifies both factors and updates authorization status to `authorized = true`.
4. **Client-Side Cryptographic Ballot Generation:**
   - Client fetches candidate count ($k$) and joint election public key $Y$ from `/api/v2/voting/key-status`.
   - Client represents selection as a one-hot vector $m \in \{0, 1\}^k$ where $\sum m_j = 1$.
   - Client chooses ephemeral BN254 scalars $r_j$ and computes ElGamal ciphertexts:
     $$C_j = r_j \cdot G, \quad D_j = r_j \cdot Y + m_j \cdot G$$
   - Client computes a Non-Circular Cramer-Damgård-Schoenmakers (CDS) zero-knowledge membership proof proving each coordinate encrypts 0 or 1 and the sum of coordinates encrypts 1, without revealing the selected candidate.
5. **Ballot Submission:** Client posts encrypted ballot and CDS proof to `POST /api/v2/voting/cast-ballot`.
6. **Backend & Relayer Processing:** Backend checks that authorization is valid and unconsumed, validates sequence monotonicity, writes to `ballot_queue_v2`, and atomically consumes the authorization. The relayer submits the transaction to `EVotingBallotBoxV2.sol:castBallot()`.
7. **Receipt Issuance:** A receipt code is returned to the student for independent tracking.

### C. Officer Workflow & Two-Officer Finalization
1. **Key Generation:** Prior to voting, Officer 1 and Officer 2 independently generate BN254 private key shares $x_1, x_2 \in \mathbb{F}_q$ in their browser.
2. **On-Chain Key Registration:** Each officer registers public key $Y_i = x_i \cdot G$ on `EVotingBallotBoxV2.sol` accompanied by a Schnorr Proof of Possession (PoP). Once both register, the contract sets joint public key $Y = Y_1 + Y_2$.
3. **Election Close:** Once election closes, voting transitions to `DecryptionSharesPending`.
4. **Decryption Share Submission:** Each officer reconstructs column decryption shares $D_{i,j} = x_i \cdot C_j$ for each candidate and computes Chaum-Pedersen Discrete Log Equality (DLEQ) proofs.
5. **Contract Verification & Final Tally:** The contract verifies each DLEQ proof on-chain. When both officer shares are accepted, on-chain tallies are finalized (`State = 7`).
6. **Stall Protection:** If an officer abandons finalization, a permissionless fallback (`markTallyStalled`) can be triggered after 72 hours.

---

## 5. Results & Public Verification

- **Withholding Invariant:** Results are strictly withheld (`403 Forbidden` / `423 Locked`) while elections are `OPEN`, `SCHEDULED`, `DRAFT`, or while ballots remain in flight (`QUEUED`, `SUBMITTED`, `PENDING`, `UNCERTAIN`).
- **Audit Review Invariant:** If open reconciliation issues exist, results transition to `RESULTS_UNDER_REVIEW`, withholding official certification until officer review.
- **Public Verification Endpoint:** `/api/public/elections/<id>/verify` exposes:
  - Contract address and election identifier.
  - Certified candidate list and candidate set hash.
  - Electoral roll Merkle tree root hash.
  - Independent CLI command for off-chain proof reproduction.
- **Sanitized Exports:** Officer/Auditor CSV and Excel (XLSX) exports sanitize formula injection vectors (`=`, `+`, `-`, `@`, `\t`, `\r`) and exclude voter identities.

---

## 6. Installation & Development Setup

### Prerequisites
- **Python:** 3.11+
- **Node.js:** v20+
- **Package Managers:** `pip`, `npm`
- **Database:** MySQL 8.0 (for full deployment) or SQLite (default for testing)
- **Browser:** Desktop Chrome, Brave, Firefox, or Edge with the MetaMask extension.
- **Webcam:** Functional camera for face liveness verification.

---

### Step 1: Environment Configuration

Copy environment templates and configure local settings:

```bash
# Backend configuration
cp backend/.env.example backend/.env

# Frontend configuration
cp frontend/.env.example frontend/.env
```

Generate secure secrets for `backend/.env` (never commit real secrets or private keys):
```powershell
# In PowerShell:
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('OTP_PEPPER=' + secrets.token_hex(32))"
python -c "import secrets; print('ROLL_ADMIN_TOKEN=' + secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print('FACE_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
python -c "from cryptography.fernet import Fernet; print('PSEUDONYM_MASTER_KEY=' + Fernet.generate_key().decode())"
```

Required V2 blockchain, worker, and relayer variables in `backend/.env`:
- `HARDHAT_RPC_URL=http://127.0.0.1:8545` (and `GANACHE_HOST=127.0.0.1`, `GANACHE_PORT=8545`, `GANACHE_CHAIN_ID=1337`)
- `V2_DEPLOYER_PRIVATE_KEY=<local-node-deployer-key>` (used by V2 contract provisioning)
- `V2_RELAYER_PRIVATE_KEY=<local-node-relayer-key>` (used by the V2 relayer)
- `START_V2_LIFECYCLE_WORKER=true` (enables automatic V2 election scheduling/opening/closing)

---

### Step 2: Blockchain Environment & Contracts

```bash
cd blockchain
npm install
npx hardhat compile
```

Run tests to verify the cryptographic library and smart contracts:
```bash
npm test
```

Run a persistent local Hardhat EVM node (chain ID `1337`, port `8545`):
```bash
npx hardhat node
```

V2 election contracts (`BN254CDSVerifier.sol` and `EVotingBallotBoxV2.sol`) are provisioned automatically per election when Officer 2 approves a scheduled election via the Four-Eyes governance workflow (or manually via `blockchain/scripts/deploy_v2_election*.js` if needed).

---

### Step 3: Backend Setup

```bash
cd backend
python -m venv venv

# Windows PowerShell:
venv\Scripts\Activate.ps1
# Linux/macOS:
# source venv/bin/activate

pip install -r requirements.txt

# Apply database migrations (Alembic HEAD: f1a2b3c4d5e6)
flask db upgrade

# Run backend development server (starts API + V2 lifecycle worker when START_V2_LIFECYCLE_WORKER=true)
python run.py
```
Backend API will be accessible at `http://127.0.0.1:5000`.

> On Windows PowerShell, `scripts/start_vwd_services.ps1` can also be used to coordinate local Hardhat, backend, and frontend startup.

---

### Step 4: Frontend Setup

```bash
cd frontend
npm install

# Run frontend development server
npm run dev
```
Frontend application will be accessible at `http://localhost:5173`.

---

## 7. Running the Test Suites

Vote Without Doubt contains three comprehensive test suites across the stack:

### 1. Backend Pytest Suite (96 Tests)
Executes database migration checks, security remediation tests, V2 cryptographic backend tests, hardening concurrency tests, export safety tests, and integration gates:
```bash
python -m pytest backend/tests/test_database.py backend/tests/test_group1_security_remediation.py backend/tests/test_fix3_v2_backend_integration.py backend/tests/test_v2_backend_hardening.py backend/tests/test_results_export.py backend/tests/test_group2_integration_remediation.py -v
```

### 2. Frontend Test Suite (278 Tests)
Executes UI lifecycle tests, client-side BN254 math tests, CDS proof tests, API client CSRF validation, and voter component tests:
```bash
npm --prefix frontend test
```

### 3. Smart Contract Test Suite (137 Tests)
Executes BN254 mathematical precompile checks, non-circular CDS transcript verification, `EVotingBallotBoxV2` lifecycle tests, and gas benchmarking:
```bash
npm --prefix blockchain test
```

### Production Build Verification
Verify that the frontend builds cleanly for production distribution:
```bash
npm --prefix frontend run build
```

---

## 8. Known Limitations & Research Disclosure

As an academic prototype, VWD explicitly documents its design boundaries and threat model limitations:

1. **Not a Statutory Voting System:** Built for university study and campus elections. Not certified for municipal, state, or federal elections.
2. **Biometric Presentation Attack Detection (PAD):** Biometric liveness currently operates in **shadow logging mode**. Face embeddings use real SCRFD detection and ArcFace embeddings, but empirical APCER/BPCER thresholds require field calibration with consented collegiate datasets.
3. **Desktop Extension Requirement:** MetaMask wallet verification requires a desktop browser extension; mobile mobile-wallet deep-linking is unsupported.
4. **Relayer Trust Boundary:** The backend relayer submits transactions on behalf of voters. While the relayer cannot forge zero-knowledge proofs or decrypt ballots, it could theoretically delay or censor a transaction. This is detected by audit event hash chains and reconciliation checks.
5. **Operator Reconciliation Recovery:** Automated recovery for ambiguous broadcast states (`UNCERTAIN`) is intentionally not automated to prevent double-counting. Operator inspection via reconciliation logs is required.

---

## 9. Academic Integrity & Responsible Disclosure

This project is submitted for university capstone evaluation. Claims of "unconditional anonymity", "military-grade security", or "production readiness" are inaccurate and unsupported by this repository. VWD provides verifiable integrity and homomorphic secrecy under explicitly documented trust assumptions.
