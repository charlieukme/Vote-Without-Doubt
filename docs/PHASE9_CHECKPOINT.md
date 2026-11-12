# Phase 9 Checkpoint: Controlled Revoting & Coercion Mitigation

## Status
- **Phase 0–8**: COMPLETE (Intact & Preserved)
- **Phase 9**: REMEDIATION IMPLEMENTED — PREPARED FOR INDEPENDENT RE-AUDIT
- **Phase 10+**: NOT STARTED (Strictly Deferred)

## Authoritative Phase 9 Specifications
1. **Sequence Model**: Authoritative server sequence progression ($1 \to 2 \to 3$). Sequence 4 is strictly rejected with HTTP 409 `MAX_BALLOTS_EXCEEDED`. Client-asserted sequence parameters are completely ignored.
2. **Latest-Vote-Wins Semantics**:
   - Distinct voter count incremented on sequence 1, invariant on subsequent revotes.
   - Smart contract dynamically decrements the previous active candidate tally and increments the new candidate tally.
   - Historical ballots are marked `superseded=True` in the database.
3. **Coercion Mitigation / Null Revotes**:
   - Voters may submit protocol-level Null Revotes (`is_null = True` / `castNullBallot`).
   - Retracts candidate choice: decrements previous active candidate tally to 0 without increasing any candidate tally.
   - Initial ballot cannot be null (`NO_PRIOR_BALLOT`).
4. **Server-Side Cooldown Enforcement**:
   - Authoritative 120-second cooldown enforced server-side between consecutive ballot submissions for the same voter.
   - Immediate revotes return HTTP 429 `COOLDOWN_ACTIVE`.
5. **Fresh Multi-Factor Authentication Per Revote**:
   - Single-use `VotingAuthorization` records consumed atomically upon ballot queueing.
   - Revotes require re-authenticating and passing fresh biometric and wallet verification factors. Reusing a consumed authorization returns HTTP 403 `AUTHORIZATION_CONSUMED`.
6. **Privacy & Cryptographic Guarantees (Preserving Phase 8)**:
   - Zero leakage of voter identity, candidate choices, transaction hashes, or internal pseudonyms in voter-facing endpoints or HMAC receipts.
   - Asynchronous relayer shuffling preserves pseudonym sequence ordering while interleaving across distinct voters.
   - Fail-closed election finalization shreds per-election pseudonym keys, blocking post-finalization revotes.

## Coercion Mitigation Limitations
- Does not protect against persistent physical coercion where an attacker remains present until election closing.
- Does not protect against device/credential confiscation or endpoint compromise.
- Cooldown period interacts with election close time; revotes cannot be cast after election closure.
