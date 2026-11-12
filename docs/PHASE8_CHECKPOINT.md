> **HISTORICAL RECORD.** This document records the state of the project at the time
> this phase was checkpointed. It is not the current status. The authoritative
> current phase status is PROJECT_BIBLE.md Section 3.

# Phase 8 Checkpoint (Remediated)

## Status
- Phases 0, 1, 2, 3, 4, 6, 7: PASS
- Phase 5: PARTIAL (governance rule: synthetic fixtures only, human trials absent)
- Phase 8: REMEDIATION COMPLETE — READY FOR INDEPENDENT RE-AUDIT
- Phase 9+: NOT STARTED

## Summary of Remediated Findings
- **F-8.1:** Per-election 32-byte keys generated via `secrets.token_bytes(32)`, envelope-encrypted with Fernet, stored in `election_pseudonym_keys`. Fail-closed on missing master key.
- **F-8.2:** Election finalization key destruction implemented (`VotingService.finalize_election`). Stored key shredded with `[DESTROYED]` sentinels; subsequent derivations fail closed with `PseudonymKeyError`.
- **F-8.3:** Decoupled relayer from `/voting/submit`. HTTP endpoint returns `202 QUEUED` immediately. Independent batch runner with cryptographic shuffling (`secrets.SystemRandom`).
- **F-8.4:** Removed `tx_hash` and `block_number` from voter-facing submit and status responses. Privacy-preserving Section 8.6 HMAC receipt.
- **F-8.5:** Comprehensive 14-test suite in `test_privacy.py` and 30-check live proof script `prove_phase8_privacy.py` against live Ganache.
- **F-8.6:** Documentation corrected; Phase 5 confirmed PARTIAL.
- **F-8.7:** Wired `RecoveryService.startup_recover()` into application boot sequence.
