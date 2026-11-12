# System Data Flow & Architecture Boundaries

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. High-Level Data Plane Separation Architecture

The system enforces strict structural separation between two distinct data planes:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                     IDENTITY PLANE                                     │
│  [Electoral Roll] ─── [User Account] ─── [Auth Sessions] ─── [Wallet Bind] ─── [Face]   │
│   (USN, Name, Email)    (Argon2id Hash)    (HttpOnly Cookie)  (0x Address)  (Encrypted)│
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Controlled Ephemeral Authorization Bridge
                                            │ (NO foreign keys, NO voter ID transferred)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                      BALLOT PLANE                                      │
│  [Voting Authorization] ─── [Pseudonym Generator] ─── [Ballot Queue] ─── [Relayer]    │
│    (Flags: Wallet/Face)      (HMAC per Election)      (Candidate, Seq)   (Signs Tx)   │
└───────────────────────────────────────────────────────────┬────────────────────────────┘
                                                            │ JSON-RPC Broadcast (P2P)
                                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   BLOCKCHAIN PLANE                                     │
│     [EVotingBallotBox.sol] ─── [Pseudonym Mapping] ─── [Tally Mapping] ─── [Events]     │
│       (Smart Contract)           (bytes32, Seq 1-3)     (Candidate Votes)   (BallotCast)│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Voter Registration & Multi-Factor Enrollment Flow

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Election Officer
    actor Voter as Student Voter
    participant Client as React Frontend
    participant Server as Flask Backend
    participant DB as MySQL Database
    participant SMTP as College Mail Server

    Note over Admin,DB: 1. Electoral Roll Import
    Admin->>Server: POST /api/admin/roll/import (CSV: USN, Name, Email)
    Server->>DB: Insert into electoral_roll (Canonical SHA-256 Digest)

    Note over Voter,DB: 2. Account Registration
    Voter->>Client: Enters USN, Email, Password
    Client->>Server: POST /api/auth/register
    Server->>DB: Check eligibility in electoral_roll
    Server->>DB: Create user row (Argon2id password hash)
    Server->>SMTP: Dispatch Registration OTP
    SMTP-->>Voter: Receives 6-digit OTP
    Voter->>Client: Enters OTP
    Client->>Server: POST /api/auth/verify-registration-otp
    Server->>DB: Update user: is_verified = True

    Note over Voter,DB: 3. Wallet Possession Binding
    Voter->>Client: Connects MetaMask
    Client->>Server: POST /api/wallet/challenge (requests nonce)
    Server-->>Client: Returns EIP-191 domain-separated nonce
    Client->>Client: Signs message in MetaMask
    Client->>Server: POST /api/wallet/bind (address, signature)
    Server->>DB: Stores wallet_bindings (address, verified = True)

    Note over Voter,DB: 4. Biometric Enrollment
    Voter->>Client: Grants Camera Consent
    Client->>Server: POST /api/face/challenge
    Server-->>Client: Returns Liveness Sequence (e.g. "LEFT,RIGHT")
    Client->>Client: Captures JPEG video frames
    Client->>Server: POST /api/face/enroll (multipart: frames, consent=True)
    Server->>Server: In-Memory Liveness Pose & ArcFace Analysis
    Server->>Server: Generates 512-dim embedding & Encrypts (Fernet: AES-128-CBC + HMAC-SHA256)
    Server->>DB: Stores face_enrollments (encrypted_embedding)
    Note over Server: Camera frames immediately wiped from RAM
```

---

## 3. End-to-End Voting Flow

```mermaid
sequenceDiagram
    autonumber
    actor Voter as Student Voter
    participant Client as React Frontend
    participant Server as Flask Backend
    participant DB as MySQL Database
    participant Relayer as Relayer Worker
    participant Chain as EVotingBallotBox.sol

    Voter->>Client: Clicks "Vote Now"
    Client->>Server: POST /api/voting/authorize {election_id}
    Server->>DB: Check active election timing & create VotingAuthorization
    Server-->>Client: Authorization Granted

    Note over Client,Server: Multi-Factor Factor Verification
    Client->>Server: POST /api/wallet/verify (signs fresh nonce)
    Server->>DB: Marks VotingAuthorization.wallet_verified = True
    Client->>Server: POST /api/face/verify (submits live challenge frames)
    Server->>DB: Decrypts face template, matches live embedding ($\ge 0.65$)
    Server->>DB: Marks VotingAuthorization.face_verified = True

    Note over Client,DB: Ballot Construction & Pseudonym Derivation
    Voter->>Client: Selects Candidate
    Client->>Server: POST /api/voting/submit {election_id, candidate: 1}
    Server->>DB: Validates VotingAuthorization is verified & unconsumed
    Server->>DB: Marks VotingAuthorization.consumed = True
    Server->>Server: Decrypts per-election pseudonym key
    Server->>Server: Derives Pseudonym = HMAC(Key, "VOTE|chain|contract|election|user_id")
    Server->>DB: Inserts into ballot_queue (pseudonym, candidate, sequence: 1, state: 'QUEUED')
    Server-->>Client: Returns Masked Receipt (REC-1401-XXXX)

    Note over Relayer,Chain: Asynchronous Blockchain Submission
    Relayer->>DB: Atomically claims queued ballot (state: 'SUBMITTED')
    Relayer->>Chain: castBallot(electionId, pseudonymHash, candidate, sequence: 1)
    Chain->>Chain: Verify election active, sequence == lastSequence + 1
    Chain->>Chain: Increment tally[electionId][candidate]++
    Chain->>Chain: Record ballots[electionId][pseudonymHash]
    Chain-->>Relayer: Transaction Mined (Receipt status = 1)
    Relayer->>DB: Updates ballot_queue (state: 'FINALIZED', block_number, tx_hash)
```

---

## 4. Revoting & Coercion Resistance Flow

1. **Re-Authentication:** If a voter is coerced, they re-authenticate and request authorization.
2. **Sequence Increment:** The voting service inspects the voter's prior ballots in `ballot_queue` for this election:
   $$\text{Next Sequence} = \text{Current Highest Sequence} + 1$$
3. **Revote Cap:** Maximum 3 ballots per voter per election. If `sequence > 3`, the request is rejected with `MAX_BALLOTS_EXCEEDED`.
4. **Smart Contract State Transition:** When `castBallot` executes for `sequence = 2`:
   - Prior candidate tally is decremented: `tally[electionId][lastCandidate]--`
   - New candidate tally is incremented: `tally[electionId][newCandidate]++`
   - Prior ballot in database is updated: `superseded = True`
5. **Null Revote Option:** A voter may invoke `POST /api/voting/submit-null`. The smart contract decrements the prior candidate tally without incrementing any candidate, recording a formal null ballot while exhausting the voter's participation attempt.

---

## 5. Election Finalization & Key Destruction Flow

```mermaid
sequenceDiagram
    autonumber
    actor Officer1 as Election Officer 1
    actor Officer2 as Election Officer 2
    participant Server as Flask Backend
    participant DB as MySQL Database
    participant Chain as EVotingBallotBox.sol

    Officer1->>Server: POST /api/admin/election/finalize (initiates request)
    Server->>DB: Creates ApprovalRequest (pending second officer)
    Officer2->>Server: POST /api/admin/approval/approve {request_id}
    Server->>DB: Verifies distinct officers (Four-Eyes Principle)
    
    Note over Server,DB: Irreversible Key Destruction
    Server->>DB: Verifies all queued ballots are FINALIZED
    Server->>DB: OVERWRITES election_pseudonym_keys:
    Note over DB: key_ciphertext = '[DESTROYED]'<br/>key_hash = '00000000...0000'
    Server->>Server: Evicts active key from memory cache
    
    Note over Server,Chain: Result Tally Lock
    Server->>DB: Marks election.status = 'FINALIZED'
    Server->>Chain: Tally is now authoritative and immutable
    Note over DB,Chain: Voters and ballots are now permanently mathematically unlinkable.
```
