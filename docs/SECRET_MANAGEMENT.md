# Secret Management & Cryptographic Key Lifecycle

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Secrets Inventory & Storage Locations

Every secret utilized across the system is strictly categorized by operational scope, storage medium, rotation requirements, and failure modes:

| Secret Name | Operational Purpose | Expected Location | Storage Format | Rotation Frequency | Compromise Impact |
|:---|:---|:---|:---|:---|:---|
| `SECRET_KEY` | Flask session cookie signing & CSRF | Environment Variable | 64-character hex | Annual / Per-deploy | Session forgery, CSRF bypass |
| `PSEUDONYM_MASTER_KEY`| Fernet master envelope for election keys | Environment Variable | 32-byte Base64 key | Annual / Per-deploy | Decryption of unfinalized election keys |
| `FACE_EMBEDDING_KEY` | Fernet key for ArcFace templates (AES-128-CBC + HMAC) | Environment Variable | 32-byte Base64 key | Semi-Annual | Decryption of stored face embeddings |
| `RECEIPT_SECRET` | HMAC key for masked voter receipt generation | Environment Variable | 64-character hex | Per-election | Forgery of voter receipt codes |
| `OTP_PEPPER` | HMAC key for Email OTP verification | Environment Variable | 64-character hex | Semi-Annual | Offline dictionary attacks on OTPs |
| `RELAYER_PRIVATE_KEY`| Ethereum private key for relayer gas & txs | Environment Variable | 64-character hex | Per-election / Incident| Unauthorized smart contract transactions |
| `DATABASE_URL` | MySQL administrative credentials | Environment Variable | Connection URI | Quarterly / Incident | Direct SQL data access / alteration |
| `Admin TOTP Secrets` | 2FA for administrative officers | Database (`admin_users`) | Encrypted Fernet Envelope | Per-admin reset | Admin 2FA bypass |
| `Election Key ($K_e$)`| Per-election HMAC pseudonym derivation key | Database (`election_keys`)| Fernet Ciphertext | Destroyed at finalization | Unlinkability compromise before shredding |

---

## 2. Key Lifecycle Workflows

### A. Election-Specific Pseudonym Key Lifecycle
The per-election key ($K_e$) has the most sensitive privacy lifecycle in the system:
1. **Generation:** When an election is initialized, the backend generates a random 32-byte key:
   $$K_e \leftarrow \text{CSPRNG}(32)$$
2. **Envelope Encryption:** $K_e$ is encrypted using `PSEUDONYM_MASTER_KEY` via Fernet and stored in `election_pseudonym_keys`.
3. **Usage:** Cached ephemerally in server RAM (`_ACTIVE_KEY_CACHE`) during the active voting window to derive pseudonyms:
   $$\text{Pseudonym} = \text{HMAC-SHA256}(K_e, \text{"VOTE|chain|contract|election|user\_id"})$$
4. **Destruction (Shredding):** Upon Two-Officer election finalization:
   - The database ciphertext is overwritten with `'[DESTROYED]'`.
   - The key hash is overwritten with `'00000000...0000'`.
   - The in-memory cache entry is popped and cleared.
   - **Post-destruction state:** No party, including database administrators, can ever reconstruct the pseudonym from a voter ID.

### B. Relayer Key Management & Emergency Rotation
1. **Deployment:** The relayer account must be pre-funded with sufficient ETH/gas to execute anticipated ballot transactions.
2. **Access Limitation:** Only the background worker process requires access to `RELAYER_PRIVATE_KEY`.
3. **Emergency Rotation:** If the key is compromised:
   - The Election Officer calls `EVotingBallotBox.sol::setRelayer(newRelayerAddress)` from the contract deployer address.
   - The relayer worker environment is updated with the new private key and restarted.
   - All subsequent broadcasts originate from the new address.

---

## 3. Strict Prohibitions

> [!CAUTION]
> **Rules for Secret Handling:**
> 1. **NEVER Commit Secrets:** Do not commit `.env`, private keys, seed phrases, or database passwords to Git repositories. Ensure `.gitignore` explicitly includes `.env`, `*.key`, `*.pem`, and `*.db`.
> 2. **NO Hardcoded Fallbacks:** Production services fail closed if an environment secret is missing or empty. The system must never fall back to default development strings like `"dev-secret-key"`.
> 3. **Redaction in Logs:** Audit loggers and exception handlers must never print environment variables, connection URIs, or private keys to stdout or log files.
