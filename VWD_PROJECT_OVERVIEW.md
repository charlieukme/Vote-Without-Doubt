# VOTE WITHOUT DOUBT (VWD)
## Executive Project Overview

---

### What is Vote Without Doubt?
**Vote Without Doubt (VWD)** is a verifiable, anti-coercion, privacy-preserving electronic voting system designed for college campuses and academic institutions. It combines **multi-factor biometric and wallet identity verification**, **gasless Ethereum smart contracts**, and **tamper-evident audit logging** to deliver an election platform that voters and administrators can mathematically trust.

```mermaid
graph LR
    Student[Student / Voter] -->|1. Biometric & Wallet Auth| App[VWD Web Application]
    App -->|2. Gasless Ballot Queue| Relayer[Backend Relayer]
    Relayer -->|3. Signed EVM Transaction| Blockchain[(Hardhat Smart Contract)]
    Blockchain -->|4. Immutable On-Chain Tallies| Public[Public & Independent Auditors]
```

---

## 1. Key Value Propositions

| Feature | Conventional Web Voting | Vote Without Doubt (VWD) |
|---|---|---|
| **Identity Verification** | Username + Password only | College USN + Email OTP + Facial Liveness (PAD) + MetaMask EIP-191 Signature. |
| **Ballot Storage** | Central database (mutable by admin) | Ethereum Smart Contract (`EVotingBallotBox.sol`) — append-only, immutable. |
| **Voter Privacy** | Real name or email tied to database row | Deterministic cryptographic pseudonyms ($P = \text{HMAC-SHA256}(K, \text{user} \parallel \text{election})$). |
| **Voter Coercion Defense** | Single vote only; forced votes are permanent | Anti-coercion revoting protocol (up to 3 submissions; newest replaces prior vote). |
| **Administrative Governance** | Single superuser can change anything | Two-Officer Four-Eyes Governance (`OFFICER_01` & `OFFICER_02`); self-approval blocked. |
| **Verifiability** | "Thank you for voting" message only | Cryptographic receipts with transaction hashes, block numbers, and Merkle proofs. |

---

## 2. Core Architectural Components

1. **Frontend (React 18 & Vite):**
   - Single-page interface for student registration, face enrollment, wallet signing, candidate showcases, and ballot submission.
   - Dedicated administrative dashboards for election creation, candidate curation, and two-officer approvals.
2. **Backend (Python 3.11 & Flask):**
   - Orchestrates multi-factor authentication, biometric feature extraction, and facial liveness detection (PAD).
   - Manages the transaction relayer queue and maintains a tamper-evident, hash-chained audit log.
3. **Database (SQLite 3 & SQLAlchemy):**
   - Stores user credentials (hashed with Argon2id), electoral eligibility rolls, facial embeddings, and audit history.
4. **Blockchain (Hardhat EVM Local Node, Chain ID 1337):**
   - Smart contract `EVotingBallotBox.sol` deployed at `0x5FbDB2315678afecb367f032d93F642f64180aa3`.
   - Records ballots, validates submission sequences ($1 \le s \le 3$), updates tallies, and anchors audit proofs.
5. **Advanced Prototype (V2):**
   - `EVotingBallotBoxV2.sol` featuring homomorphic exponential ElGamal encryption over the BN254 elliptic curve, Cramer-Damgård-Schoenmakers (CDS) zero-knowledge proofs, and 2-of-2 threshold decryption.

---

## 3. High-Level Workflows

### The Student Workflow
1. **Eligibility:** Student enters University Seat Number (USN); system verifies presence in electoral roll.
2. **Verification:** Student verifies college email via 6-digit OTP and creates an Argon2id password.
3. **Biometrics:** Student enrolls live facial embeddings via webcam with Presentation Attack Detection.
4. **Wallet Binding:** Student binds their personal Ethereum address by signing a nonce in MetaMask.
5. **Voting:** Student enters the voting booth, selects a candidate, and confirms submission.
6. **Confirmation:** The backend Relayer broadcasts the ballot to the smart contract; the student receives an immutable cryptographic receipt.
7. **Revoting (if coerced):** If coerced, the student can recast their vote up to 3 times before election close; the smart contract automatically replaces prior selections.

### The Administrative Workflow
1. **Creation:** Officer 1 drafts an election and attaches candidate profiles, manifestos, and photos.
2. **Two-Officer Review:** Officer 1 submits a schedule request; Officer 2 inspects and executes the approval.
3. **On-Chain Provisioning:** The backend deploys candidate hashes and parameters to the smart contract.
4. **Lifecycle Management:** The election opens and closes automatically based on UTC timestamps.
5. **Audit Anchoring:** Following election close, officers anchor the ballot Merkle root and audit log hash directly to the blockchain.

---

## 4. Quick-Start Guide (3 Terminals)

```bash
# Terminal 1 — Blockchain Node & Setup
cd blockchain
npx hardhat node
# (In a second prompt: deploy contract and authorize relayer)
npx hardhat run scripts/deploy.js --network localhost
npm run authorize:relayer

# Terminal 2 — Flask Backend
cd backend
python run.py

# Terminal 3 — React Frontend
cd frontend
npm run dev
```

Run the automated health diagnostic:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_vwd_services.ps1
```

---

## 5. Summary Document Reference
For exhaustive technical details, line-by-line algorithm descriptions, database entity diagrams, and security proofs, consult the comprehensive documentation:
- **Primary Technical Document:** [`VWD_COMPLETE_PROJECT_TECHNICAL_DOCUMENTATION.md`](file:///c:/Users/aditya%20prasad/Downloads/voting-sys/VWD_COMPLETE_PROJECT_TECHNICAL_DOCUMENTATION.md)

