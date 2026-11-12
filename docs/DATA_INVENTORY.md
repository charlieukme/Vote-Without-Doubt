# Data Inventory & Schema Classification

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  
**Repository Source of Truth:** `backend/app/models/`, `backend/app/schema.sql`, `blockchain/contracts/EVotingBallotBox.sol`  

---

## 1. Complete Personal & System Data Inventory

This inventory enumerates every data attribute handled by the system, classifying collection points, storage locations, protective controls, lifecycle retention, and whether data reaches external boundaries or the blockchain ledger.

| Data Attribute | Collection Endpoint / Source | Operational Purpose | Storage Location | Storage Format | Encryption / Protection | Access Permissions | Leaves System? | Reaches Chain? | Retention Policy | Deletion Mechanism | Privacy Sensitivity |
|:---|:---|:---|:---|:---|:---|:---|:---:|:---:|:---|:---|:---:|
| **USN / Student ID** | Admin CSV Roll Import (`/api/admin/roll/import`) | Primary voter eligibility key | `electoral_roll.usn`, `users.voter_id` | `VARCHAR(50)` | None (plain text, indexed) | Admin (Officer/Auditor), Voter (own) | No | **NO** | Active academic election cycle | Manual Institutional Purge | **HIGH (PII)** |
| **Full Student Name** | Admin CSV Roll Import | Voter verification & display | `electoral_roll.full_name` | `VARCHAR(200)` | None (plain text) | Admin (Officer/Auditor), Voter (own) | No | **NO** | Active academic election cycle | Manual Institutional Purge | **HIGH (PII)** |
| **College Email** | Admin CSV Roll Import, Registration | Email OTP delivery, account identity | `electoral_roll.college_email`, `users.email` | `VARCHAR(255)` | None (plain text, indexed) | Admin, Email Service (SMTP), Voter | Outbound SMTP | **NO** | Active academic election cycle | Manual Institutional Purge | **HIGH (PII)** |
| **Department / Year** | Admin CSV Roll Import | Eligibility filtering | `electoral_roll.department`, `year_of_study` | `VARCHAR(100)`, `INT` | None (plain text) | Admin | No | **NO** | Active academic election cycle | Manual Institutional Purge | **MEDIUM** |
| **Password Hash** | Voter Registration (`/api/auth/register`), Reset (`/api/auth/forgot-password/reset`) | Primary authentication factor | `users.password_hash` | `VARCHAR(255)` | **Argon2id** (m=65536, t=3, p=4) | System authentication engine only | No | **NO** | Account lifetime | Account deletion | **CRITICAL (Secret)** |
| **Login / Reset OTP Hash**| OTP Request (`/api/auth/login`, `/api/auth/forgot-password/request`) | Second factor / password recovery | `otps.otp_hash` | `VARCHAR(64)` | **HMAC-SHA256** with server pepper | System authentication engine only | No | **NO** | 5 minutes TTL | Auto-consumed or expired | **HIGH (Secret)** |
| **Candidate Profile** | Admin Candidate Creation / Upload (`/api/admin/elections/<id>/candidates`) | Voter candidate review & public display | `candidates.department`, `year`, `slogan`, `manifesto`, `photo_url` | `VARCHAR` / `TEXT` | Plain text (HTML-sanitized); photo EXIF stripped | Public, Voter, Admin | Client JSON / Public Image | **NO** | Academic election cycle | Database archival policy | **LOW (Public)** |
| **Support Ticket** | Student Problem Submission (`/api/public/support/report`) | Dispute handling & issue tracking | `support_tickets.reference_id`, `category`, `details` | `VARCHAR` / `TEXT` | Privacy filter applied (keywords stripped); no ballot IDs | Admin, Student (via ref) | No | **NO** | Academic audit period | Database archival policy | **LOW (Sanitized)** |
| **Session Token** | Authentication (`/api/auth/verify-otp`) | State management across requests | `auth_sessions.session_id` | `VARCHAR(64)` | CSPRNG Token; signed HttpOnly cookie | Voter browser, Server auth session | Client Cookie | **NO** | 2h absolute / 10m idle | Expired / Revoked on logout | **HIGH (Token)** |
| **Wallet Address** | Wallet Binding (`/api/wallet/bind`) | Possession factor verification | `wallet_bindings.wallet_address` | `VARCHAR(42)` | Checksum normalisation (`0x...`) | Voter (own), System | No | **NO** | Bound account lifetime | Unbind / Account deletion | **MEDIUM (Pseudonymous)** |
| **Wallet Nonce** | Wallet Challenge (`/api/wallet/challenge`) | EIP-191 replay protection | `wallet_challenges.nonce` | `VARCHAR(64)` | CSPRNG hex string | Voter client (for signing) | Client JSON | **NO** | 5 minutes TTL | Consumed on verification | **LOW (Ephemeral)** |
| **Raw Camera Frames** | Face Endpoints (`/api/face/*`) | Real-time liveness & matching | **RAM Only** (Flask request context) | In-memory JPEG bytes | Scoped to memory; immediately freed | Face engine memory space | No | **NO** | **0 seconds (Transient)** | Garbage collected post-request | **CRITICAL (Biometric)** |
| **Face Landmarks / Yaw** | Camera frame evaluation | Temporal head rotation tracking | **RAM Only** | Float arrays (NumPy) | Scoped to memory; discarded | Face engine memory space | No | **NO** | **0 seconds (Transient)** | Garbage collected post-request | **HIGH (Biometric)** |
| **Face Embedding** | Face Enrollment (`/api/face/enroll`) | Identity template for face verification | `face_enrollments.encrypted_embedding` | `LargeBinary` | **Fernet Envelope** (AES-128-CBC + HMAC-SHA256, ArcFace 512-dim vector) | Face service decryption engine only | No | **NO** | Enrollment lifetime | **Instant overwrite (`b''`)** on withdrawal | **CRITICAL (Biometric)** |
| **Biometric Challenge** | Face Challenge (`/api/face/challenge`) | Interactive liveness sequence | `face_challenges.challenge_sequence` | `VARCHAR(32)` | HMAC integrity MAC protected | Voter client (direction prompt) | Client JSON | **NO** | 60 seconds TTL | Consumed on submission | **LOW (Ephemeral)** |
| **Voting Authorization** | Factor Verification (`/api/voting/authorize`) | Ephemeral permission to cast ballot | `voting_authorizations` | Table row | Flags only (`wallet_verified`, `face_verified`) | Voting service | No | **NO** | Duration of voting session | Consumed upon ballot submit | **MEDIUM (State)** |
| **Registration Deadline** | Election Scheduling | Pre-election registration window cutoff | `elections.registration_deadline` | `DATETIME` | Authoritative UTC timestamp | Public, Voter, Admin | Client JSON | **NO** | Election lifetime | Database archival policy | **LOW (Configuration)** |
| **Election Pseudonym Key**| Backend election initialization | Key material for pseudonym hashing | `election_pseudonym_keys.key_ciphertext`| `TEXT` | **Fernet Envelope** (AES-128-CBC + HMAC) | Voting service only | No | **NO** | Active voting duration | **Permanently Shredded (`[DESTROYED]`)** on close | **CRITICAL (Secret)** |
| **Ballot Pseudonym** | Ballot Submission (`/api/voting/submit`) | Pseudonymous voter anchor | `ballot_queue.pseudonym` | `VARCHAR(128)` | **HMAC-SHA256** digest | Public, Smart Contract, Relayer | **Yes (Chain)**| **YES (`bytes32`)** | Permanent on-chain ledger | **Immutable (Cannot delete)** | **HIGH (Ballot Anchor)** |
| **Candidate Selection** | Ballot Submission (`/api/voting/submit`) | Voter electoral preference | `ballot_queue.candidate` | `INT` | Stored in ballot plane only | Relayer, Smart Contract | **Yes (Chain)**| **YES (`uint256`)** | Permanent on-chain ledger | **Immutable (Cannot delete)** | **HIGH (Ballot Choice)** |
| **Ballot Sequence** | Ballot Submission (`/api/voting/submit`) | Revote ordering (1, 2, or 3) | `ballot_queue.sequence` | `INT` | Sequential integer counter | Relayer, Smart Contract | **Yes (Chain)**| **YES (`uint256`)** | Permanent on-chain ledger | **Immutable (Cannot delete)** | **LOW (Counter)** |
| **Null Ballot Flag** | Null Revote (`/api/voting/submit-null`) | Revoking previous candidate vote | `ballot_queue.is_null` | `BOOLEAN` | Boolean flag | Relayer, Smart Contract | **Yes (Chain)**| **YES (`bool`)** | Permanent on-chain ledger | **Immutable (Cannot delete)** | **LOW (Flag)** |
| **Blockchain Tx Hash** | Relayer Broadcast (`Relayer.process_queue`) | Proof of blockchain submission | `ballot_queue.tx_hash` | `VARCHAR(128)` | Transaction hash (`0x...`) | Public verification, Admin, Voter | **Yes (Public)**| **YES (EVM receipt)** | Permanent on-chain ledger | **Immutable (Cannot delete)** | **LOW (Public Identifier)**|
| **Receipt Code** | Ballot Confirmation | Voter verification proof | `ballot_queue.receipt_code` | `VARCHAR(64)` | HMAC code (`REC-<id>-<hex>`) | Voter, Dispute Service | Client JSON | **NO** | Academic audit period | Database archival policy | **MEDIUM (Receipt)** |
| **Admin TOTP Secret** | Admin Setup (`/api/admin/bootstrap`) | Two-factor authentication for admins | `admin_users.totp_secret_encrypted` | `LargeBinary` | **Fernet Envelope** (AES-128-CBC + HMAC-SHA256) | Admin authentication engine only | No | **NO** | Admin account lifetime | Admin account deletion | **CRITICAL (Secret)** |
| **Audit Event Hash** | System audit logging (`AuditLogger.log`) | Tamper-evident operational trail | `audit_events.current_hash` | `VARCHAR(64)` | SHA-256 Hash Chaining | Auditors, System, Blockchain Anchor | **Yes (Anchor)**| **YES (`bytes32`)** | Permanent archive | Immutable audit log | **LOW (Integrity Hash)** |

---

## 2. On-Chain Smart Contract Inventory (`EVotingBallotBox.sol`)

The Ethereum smart contract stores the minimal verifiable dataset necessary for decentralized tallying and audit verification:

```solidity
struct Election {
    uint256 start;              // Epoch start timestamp
    uint256 end;                // Epoch end timestamp
    uint256 candidateCount;     // Number of eligible candidates
    bytes32 candidatesHash;     // SHA-256 digest of candidate manifest
    uint256 eligibleCount;      // Number of voters on authorized roll
    bytes32 rollHash;           // Canonical SHA-256 digest of roll import
    uint256 maxBallots;         // Max ballots allowed per voter (3)
    uint256 distinctVoters;     // Cumulative distinct pseudonyms seen
    bool cancelled;             // Administrative cancellation flag
}

struct BallotInfo {
    uint256 sequence;           // Latest valid ballot sequence (1, 2, 3)
    uint256 lastCandidate;      // Latest candidate choice index
    bool isNull;                // True if latest ballot was a null vote
}
```

### What Reaches the Blockchain:
- **Election Manifest:** `candidatesHash`, `rollHash`, start/end times.
- **Ballot Submissions:** `bytes32 pseudonym`, `uint256 candidate`, `uint256 sequence`, `bool isNull`.
- **Audit Anchors:** `bytes32 auditHash` anchoring administrative audit-trail head blocks.

### What NEVER Reaches the Blockchain:
- **No Student Names**
- **No USNs / Roll Numbers**
- **No College Email Addresses**
- **No Passwords or OTPs**
- **No Wallet Addresses (Personal)**
- **No Raw Face Frames or Biometric Embeddings**
- **No IP Addresses or Browser User-Agents**
