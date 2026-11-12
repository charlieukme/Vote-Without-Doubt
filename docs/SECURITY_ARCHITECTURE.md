# Security Architecture & Cryptographic Primitives

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Architectural Overview & Defense-in-Depth

The security architecture of **Vote Without Doubt** implements defense-in-depth across six distinct layers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        LAYER 1: PERIMETER & TRANSPORT                  │
│    TLS/HTTPS (Production) ─── CORS Policy ─── Flask Middleware ─── CSRF│
├────────────────────────────────────────────────────────────────────────┤
│                   LAYER 2: MULTI-FACTOR AUTHENTICATION                 │
│  Password (Argon2id) + Email OTP (HMAC) + Wallet (EIP-191) + Face (CNN)│
├────────────────────────────────────────────────────────────────────────┤
│                   LAYER 3: ACCESS CONTROL & GOVERNANCE                 │
│   Two-Officer Four-Eyes Rule ─── RBAC (OFFICER/AUDITOR) ─── Admin TOTP │
├────────────────────────────────────────────────────────────────────────┤
│                   LAYER 4: PRIVACY & DATA ISOLATION                    │
│   Two-Plane Separation ─── Zero FKs ─── Per-Election Key Shredding     │
├────────────────────────────────────────────────────────────────────────┤
│                   LAYER 5: ASYNCHRONOUS RELAYER & QUEUE                │
│    Atomic SQL Claims ─── Failure Requeue ─── Blockchain Transaction    │
├────────────────────────────────────────────────────────────────────────┤
│                   LAYER 6: IMMUTABLE LEDGER & AUDIT                    │
│  Solidity Smart Contract ─── On-Chain Tally ─── Hash-Chained Audit Log │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Cryptographic Primitives Inventory

Every cryptographic primitive in the codebase is selected for standard-grade resistance and fail-closed security:

| Purpose / Operation | Cryptographic Primitive | Implementation Details | Location in Code |
|:---|:---|:---|:---|
| **Voter Password Hashing** | **Argon2id** | Memory-hard KDF ($m=65536, t=3, p=4$), random 16-byte salt | `backend/app/security/password.py` |
| **Email OTP Protection** | **HMAC-SHA256** | Keyed with server-side `OTP_PEPPER`; raw OTP never persisted | `backend/app/security/otp.py` |
| **Session Security** | **CSPRNG Tokens** | 24-byte cryptographically secure random token; URLSafe serializer | `backend/app/security/sessions.py` |
| **Wallet Possession** | **EIP-191 Personal Sign** | `\x19Ethereum Signed Message:\n<len><msg>`, domain separated | `backend/app/security/wallet.py` |
| **Biometric Template Encryption** | **Fernet (Envelope)** | Authenticated envelope (`VWDF1`), AES-128-CBC + HMAC-SHA256 | `backend/app/security/face.py` |
| **Face Feature Extraction** | **ArcFace (ResNet-50)** | Buffalo_l model, normalized 512-dimensional embedding vector | `backend/app/services/face_engine.py` |
| **Face Challenge Integrity** | **HMAC-SHA256** | MAC over `challenge_id|sequence|nonce` to prevent prompt tampering | `backend/app/security/face.py` |
| **Per-Election Key Encryption** | **Fernet (Envelope)** | AES-128-CBC + HMAC-SHA256 authenticated symmetric encryption | `backend/app/security/pseudonym.py` |
| **Pseudonym Derivation** | **HMAC-SHA256** | Keyed with per-election key; domain-separated message | `backend/app/security/pseudonym.py` |
| **Voter Receipt Generation** | **HMAC-SHA256** | Keyed with `RECEIPT_SECRET`; masked voter code (`REC-...`) | `backend/app/services/voting_service.py` |
| **Administrative 2FA** | **TOTP (RFC 6238)** | HMAC-SHA1, 30-second time step, encrypted secret at rest | `backend/app/security/totp.py` |
| **Audit Log Tamper Evidence** | **SHA-256 Hash Chain** | Block hash: $H(event\_type \parallel ts \parallel meta \parallel prev\_hash)$ | `backend/app/audit/audit.py` |
| **Blockchain Consensus** | **EVM State Machine** | Solidity 0.8.19, sequence assertions, atomic tally updates | `blockchain/contracts/EVotingBallotBox.sol`|

---

## 3. Four-Eyes Administrative Governance

To prevent administrative tyranny or unilateral tampering with election parameters:
1. **Separation of Roles:**
   - `OFFICER`: Can create elections, import rolls, and propose state transitions.
   - `AUDITOR`: Has read-only visibility into audit trails, reconciliation logs, and cryptographic verification proofs.
2. **Two-Officer Approval Workflow (`ApprovalRequest`):**
   - Critical operations (e.g., `START_ELECTION`, `FINALIZE_ELECTION`, `CANCEL_ELECTION`, `APPLY_ROLL_IMPORT`) cannot execute in a single request.
   - Officer 1 initiates the request, creating an `ApprovalRequest` record with status `PENDING`.
   - Officer 2 inspects the request parameters and calls `POST /api/admin/approval/approve`.
   - The system verifies `officer_1.id != officer_2.id` before executing the underlying state transition.

---

## 4. Tamper-Evident Audit Logging

The audit foundation (`backend/app/audit/audit.py`) guarantees that administrative and operational actions are permanently accountable:
1. **Hash Chaining:** Each `AuditEvent` stores `current_hash` and `previous_hash`. Modifying, inserting, or deleting any historical row breaks the cryptographic chain.
2. **Deny-by-Default Metadata Sanitization:** Sensitive values (passwords, biometrics, student names, wallet addresses, ballot choices) are explicitly blocked from the audit log.
3. **On-Chain Audit Anchoring:** The latest audit chain head digest is periodically anchored to the Ethereum blockchain via `EVotingBallotBox.sol::anchorAudit()`, binding database history to an immutable external ledger.
