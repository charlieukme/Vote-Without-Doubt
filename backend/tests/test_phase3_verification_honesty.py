"""
Phase 3 Stabilization Tests: Honest V2 Verification & Non-Forged Evidence.
Covers:
- Never hardcoding candidates_hash_matches=True, roll_hash_matches=True, or audit_anchor_verified=True on V2
- Offline / disconnected V2 finalized election reports UNAVAILABLE instead of VERIFIED
- Tampered candidate digest or mismatched candidateCount reports candidates_hash_matches=False and FAILED
- Valid finalized V2 election with verified tallies + Merkle root reports VERIFIED while leaving V2 unsupported fields honest
- verify_audit_anchor & get_audit_chain_for_verification skip V1 Relayer ABI calls on V2 contracts
- Effective CLOSED elections (SCHEDULED past end_time) report results_available=True cleanly
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.extensions import db
from app.models import Candidate, Election
from app.services.blockchain_v2_service import BlockchainV2Service
from app.services.bn254_crypto import generate_secure_scalar
from app.services.results_service import ResultsService
from app.services.verification_service import VerificationService


def _make_v2_election(status='FINALIZED', ended=True, merkle_root='0x' + 'a' * 64):
    now = datetime.utcnow()
    el = Election(
        election_id='ELEC_PHASE3_V2',
        title='Phase 3 Honest Verification',
        status=status,
        start_time=now - timedelta(hours=3),
        end_time=(now - timedelta(hours=1)) if ended else (now + timedelta(hours=2)),
        candidate_count=2,
        eligible_count=10,
        max_ballots=3,
        v2_priv_key_1=str(generate_secure_scalar()),
        v2_priv_key_2=str(generate_secure_scalar()),
        merkle_root=merkle_root,
    )
    db.session.add(el)
    db.session.flush()
    db.session.add(Candidate(election_id=el.election_id, candidate_index=0, name='Alice', department='CS'))
    db.session.add(Candidate(election_id=el.election_id, candidate_index=1, name='Bob', department='EC'))
    db.session.flush()
    el.candidates_hash = VerificationService.compute_candidates_hash(el.election_id)
    db.session.commit()
    return el


def test_phase3_v2_never_hardcodes_true_and_reports_offline_unavailable(app, client):
    with app.app_context():
        el = _make_v2_election(status='FINALIZED', ended=True)

        class _OfflineW3:
            def is_connected(self):
                return False

        with patch.object(BlockchainV2Service, 'get_web3', return_value=_OfflineW3()):
            ok, _code, payload = VerificationService.get_public_verification(el.election_id)
            assert ok is True
            ev = payload['blockchain_evidence']
            assert ev['protocol_version'] == 'V2'
            assert ev['audit_anchor_supported'] is False
            assert ev['candidates_hash_matches'] is None
            assert ev['roll_hash_matches'] is None
            assert ev['audit_anchor_verified'] is False
            assert payload['verification_status'] == 'UNAVAILABLE'


def test_phase3_v2_detects_tampered_candidates_and_mismatched_chain_count(app, client):
    with app.app_context():
        el = _make_v2_election(status='FINALIZED', ended=True)
        el.candidates_hash = '0x' + '0' * 64  # tampered hash vs DB Candidate rows
        db.session.commit()

        class _OfflineW3:
            def is_connected(self):
                return False

        with patch.object(BlockchainV2Service, 'get_web3', return_value=_OfflineW3()):
            ok, _code, payload = VerificationService.get_public_verification(el.election_id)
            assert ok is True
            assert payload['blockchain_evidence']['candidates_hash_matches'] is False
            assert payload['verification_status'] == 'FAILED'

        # Restore hash, simulate on-chain candidateCount mismatch
        el.candidates_hash = VerificationService.compute_candidates_hash(el.election_id)
        db.session.commit()

        class _OnlineW3:
            def is_connected(self):
                return True

        with patch('app.services.verification_service.VerificationService._resolve_target_contract', return_value='0x610178dA211FEF7D417bC0e6FeD39F05609AD788'), \
             patch.object(BlockchainV2Service, 'get_web3', return_value=_OnlineW3()), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_candidate_count', return_value=5), \
             patch.object(BlockchainV2Service, 'get_election_state', return_value=7), \
             patch.object(BlockchainV2Service, 'get_total_active_ballots', return_value=1), \
             patch.object(ResultsService, 'get_election_results', return_value=(True, 'FINALIZED_RESULTS', {
                 'total_valid_votes': 1,
                 'total_null_votes': 0,
                 'total_distinct_voters': 1,
                 'turnout_percentage': 10.0,
                 'candidates': [],
                 'winners': [],
                 'tally_matches_blockchain': True,
                 'reconciliation_clean': True,
             })):
            ok, _code, payload = VerificationService.get_public_verification(el.election_id)
            assert ok is True
            assert payload['blockchain_evidence']['candidates_hash_matches'] is False
            assert payload['verification_status'] == 'FAILED'


def test_phase3_v2_verified_and_effective_closed_consistency_and_no_v1_abi(app, client):
    with app.app_context():
        el = _make_v2_election(status='SCHEDULED', ended=True, merkle_root='0x' + 'b' * 64)

        class _OnlineW3:
            def is_connected(self):
                return True

        with patch('app.services.verification_service.VerificationService._resolve_target_contract', return_value='0x610178dA211FEF7D417bC0e6FeD39F05609AD788'), \
             patch.object(BlockchainV2Service, 'get_web3', return_value=_OnlineW3()), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_candidate_count', return_value=2), \
             patch.object(BlockchainV2Service, 'get_election_state', return_value=7), \
             patch.object(BlockchainV2Service, 'get_total_active_ballots', return_value=0), \
             patch.object(ResultsService, 'get_election_results', return_value=(True, 'PROVISIONAL_UNFINALIZED', {
                 'total_valid_votes': 0,
                 'total_null_votes': 0,
                 'total_distinct_voters': 0,
                 'turnout_percentage': 0.0,
                 'candidates': [],
                 'winners': [],
                 'tally_matches_blockchain': True,
                 'reconciliation_clean': True,
             })):
            ok, _code, payload = VerificationService.get_public_verification(el.election_id)
            assert ok is True
            assert payload['status'] == 'CLOSED'
            assert payload['results_available'] is True
            assert payload['verification_status'] == 'VERIFIED'
            assert payload['blockchain_evidence']['candidates_hash_matches'] is None
            assert payload['blockchain_evidence']['roll_hash_matches'] is None
            assert payload['blockchain_evidence']['audit_anchor_verified'] is False
            assert payload['blockchain_evidence']['audit_anchor_supported'] is False

        # Ensure verify_audit_anchor & get_audit_chain_for_verification never call V1 Relayer on V2
        with patch('app.services.verification_service.Relayer', side_effect=AssertionError('Relayer must not be called for V2')):
            anc = VerificationService.verify_audit_anchor(el.election_id)
            assert anc['protocol_version'] == 'V2'
            assert anc['v2_anchor_supported'] is False
            assert anc['checkpoint_status'] == 'V2_NO_ONCHAIN_AUDIT_ANCHOR'

            chain = VerificationService.get_audit_chain_for_verification(el.election_id)
            assert chain['protocol_version'] == 'V2'
            assert chain['v2_anchor_supported'] is False
            assert chain['is_anchored'] is False

