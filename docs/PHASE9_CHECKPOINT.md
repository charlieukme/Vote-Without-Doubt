# Phase 9 Checkpoint

## Status
Phase 0-9 COMPLETE, Phase 10=NOT STARTED

## Revoting Policy
MAX_BALLOTS=3 per voter per election. Server and contract enforce. Latest valid ballot supersedes previous; distinctVoters unchanged. Fresh authorization required per vote.

## Key Changes
- Backend: VotingService.enforce sequence (next = latest+1, max 3); reject fourth. Status includes minimal info.
- Blockchain: Already supports revote (decrement prev, increment new, sequence increment). Added revoting tests.
- Frontend: Voting UI respects limits.
- Privacy: No identity in ballot, pseudonyms never exposed, receipts privacy-preserving. Phase 8 controls preserved.

## Tests
Backend: 47 passed core+revoting
Blockchain: 11 passed (7 + 4 revoting)
Frontend: build ok
