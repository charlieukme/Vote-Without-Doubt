# Consent Model & Data Subject Rights

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Implemented Consent Mechanisms

The system enforces consent boundaries across the user lifecycle:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              CONSENT LIFECYCLE                                         │
├─────────────────────┬───────────────────┬──────────────────────────────────────────────┤
│ Operational Scope   │ Technical Trigger │ Implementation Status                        │
├─────────────────────┼───────────────────┼──────────────────────────────────────────────┤
│ Account Creation    │ Registration Form │ User agrees to collegiate election terms     │
├─────────────────────┼───────────────────┼──────────────────────────────────────────────┤
│ Biometric Processing│ Camera Modal      │ Explicit opt-in flag required in API payload │
├─────────────────────┼───────────────────┼──────────────────────────────────────────────┤
│ Wallet Binding      │ MetaMask Sign     │ Explicit user confirmation in wallet modal   │
├─────────────────────┼───────────────────┼──────────────────────────────────────────────┤
│ Consent Withdrawal  │ Profile / API     │ Automated deletion of biometric template     │
└─────────────────────┴───────────────────┴──────────────────────────────────────────────┘
```

### Detailed Consent Analysis:
1. **Biometric Enrollment Consent (IMPLEMENTED):**
   - The enrollment endpoint (`POST /api/face/enroll`) strictly requires `consent=True`.
   - If `consent` is missing or false, the backend rejects the submission with `ConsentRequiredError` (HTTP 400).
   - The database records `consent_given = True`, `consent_at = NOW()`, and `consent_purpose = 'election_verification'`.
2. **Biometric Consent Withdrawal (IMPLEMENTED):**
   - The voter can invoke `POST /api/face/withdraw-consent` at any time.
   - The endpoint immediately sets `consent_given = False`, `withdrawn_at = NOW()`, and clears the ciphertext template (`encrypted_embedding = b''`).
3. **Wallet Usage Consent (IMPLEMENTED):**
   - The voter explicitly initiates the MetaMask connection and signs an EIP-191 personal challenge.
   - The wallet private key never leaves the voter's browser extension.
4. **General Election Participation Consent (REQUIRES INSTITUTIONAL POLICY):**
   - The student body election terms and participation agreements must be formally promulgated by the college election committee.

---

## 2. User Rights Implementation Matrix

| Data Principal / User Right | Statutory Intent | How the System Handles It | Implementation Status |
|:---|:---|:---|:---:|
| **Right to Access / Confirmation** | Know if personal data is being processed and view records. | `GET /api/face/status` returns enrollment state; `/api/voting/status` returns ballot state. | **SUPPORTED** |
| **Right to Rectification** | Correct inaccurate or incomplete personal information. | Electoral roll corrections require the college registrar to update the master roll. | **REQUIRES INSTITUTIONAL POLICY** |
| **Right to Erasure (Biometric)** | Demand deletion of sensitive biometric templates. | `POST /api/face/withdraw-consent` irreversibly shreds the stored embedding. | **SUPPORTED (AUTOMATED)** |
| **Right to Erasure (Account)** | Complete removal of student account and identity data. | Requires administrative database de-provisioning script. | **NOT IMPLEMENTED IN UI** |
| **Right to Erasure (Ballots)** | Demand deletion of cast voting records. | **CONSTRAINED BY DESIGN:** Cast ballots on blockchain are immutable and cannot be expunged. Ballots contain zero PII. | **EXCLUDED (BY DESIGN)** |
| **Right to Revoke Franchise** | Cancel a cast vote. | Voter can cast a **Null Revote** (`/api/voting/submit-null`), zeroing candidate tallies. | **SUPPORTED** |
| **Right to Data Portability** | Export personal data in a structured, machine-readable format. | No automated export endpoint exists for student profiles. | **NOT IMPLEMENTED IN PROTOTYPE** |
| **Right of Grievance Redressal** | File dispute regarding unrecorded or miscounted vote. | Receipt investigation endpoint (`DisputeService.investigate_receipt`) validates receipt codes. | **SUPPORTED (BACKEND API)** |

---

## 3. The Immutable Ledger Conflict: Right to Erasure vs. Election Integrity

A fundamental challenge in blockchain-anchored voting systems is the conflict between the **Right to Erasure (GDPR Art. 17 / DPDP Section 12)** and **Electoral Auditability**:
- **The Conflict:** If a voter could unilaterally delete their on-chain ballot after an election, election outcomes could be manipulated retroactively. Furthermore, EVM state cannot physically delete historical blocks.
- **The Solution (Zero-PII Architecture):**
  1. The blockchain stores **only** an HMAC-SHA256 pseudonym, candidate index, and sequence number.
  2. The pseudonym cannot be linked back to the student once per-election keys are shredded.
  3. Because no personal data exists on the blockchain, on-chain immutability does not violate the Data Principal's right to erasure of personal data.
  4. The student's personal identity records exist solely in the identity plane database, which *can* be purged institutionally.
