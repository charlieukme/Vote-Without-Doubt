"""
Phase 4 Stabilization Tests: Results Publication & DB/On-Chain Consistency.
Covers:
- 0-ballot automated V2 elections detected as V2 (via keys/checkpoint) rather than falling back to V1
- Effective CLOSED elections (SCHEDULED past end_time) handled identically by ResultsService
- Cross-check discrepancy detection (finalTallies sum vs totalActiveBallots vs DB confirmed voters)
- Fail-closed behavior if get_total_active_ballots throws (never faking tally_matches_blockchain=True)
- /api/v2/voting/results state gating, contract election mismatch check, in-flight block, and candidate mapping
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.extensions import db
from app.models import Candidate, Election
from app.models.ballot_record_v2 import BallotQueueV2
from app.services.blockchain_v2_service import BlockchainV2Service
from app.services.bn254_crypto import generate_secure_scalar
from app.services.results_service import ResultsService


def _create_v2_results_election(eid_str='ELEC_PHASE4_V2', status='FINALIZED', ended=True):
    now = datetime.utcnow()
    el = Election(
        election_id=eid_str,
        title='Phase 4 V2 Results Election',
        status=status,
        start_time=now - timedelta(hours=3),
        end_time=(now - timedelta(hours=1)) if ended else (now + timedelta(hours=2)),
        candidate_count=2,
        eligible_count=10,
        max_ballots=3,
        v2_priv_key_1=str(generate_secure_scalar()),
        v2_priv_key_2=str(generate_secure_scalar()),
    )
    db.session.add(el)
    db.session.flush()
    db.session.add(Candidate(election_id=el.election_id, candidate_index=0, name='Alice', department='CS'))
    db.session.add(Candidate(election_id=el.election_id, candidate_index=1, name='Bob', department='EC'))
    db.session.commit()
    return el


def test_phase4_zero_ballot_automated_v2_detected_as_v2(app, client):
    with app.app_context():
        el = _create_v2_results_election('ELEC_P4_ZERO', status='SCHEDULED', ended=True)

        with patch.object(BlockchainV2Service, 'get_election_state', return_value=7), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_final_tally', side_effect=[0, 0]), \
             patch.object(BlockchainV2Service, 'get_total_active_ballots', return_value=0):
            ok, code, data = ResultsService.get_election_results(el.election_id, contract_address='0x610178dA211FEF7D417bC0e6FeD39F05609AD788')
            assert ok is True, (code, data)
            assert data['v2_protocol'] is True
            assert data['status'] == 'CLOSED'
            assert data['result_state'] == 'FINALIZED_RESULTS'
            assert data['tally_matches_blockchain'] is True
            assert data['total_valid_votes'] == 0


def test_phase4_tally_discrepancy_and_rpc_failure_fail_closed(app, client):
    with app.app_context():
        el = _create_v2_results_election('ELEC_P4_MISMATCH', status='FINALIZED', ended=True)
        # 1 confirmed distinct voter in DB
        db.session.add(
            BallotQueueV2(
                election_id=el.id,
                pseudonym='0x' + '1' * 64,
                sequence=1,
                ciphertexts_json='[]',
                proof_json='{}',
                state='CONFIRMED',
                superseded=False,
            )
        )
        db.session.commit()

        # Contract says totalActiveBallots = 2 while DB distinct = 1 and tallies = [1, 1] -> mismatch
        with patch.object(BlockchainV2Service, 'get_election_state', return_value=7), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_final_tally', side_effect=[1, 1]), \
             patch.object(BlockchainV2Service, 'get_total_active_ballots', return_value=2):
            ok, _code, data = ResultsService.get_election_results(el.election_id, contract_address='0x610178dA211FEF7D417bC0e6FeD39F05609AD788')
            assert ok is True
            assert data['tally_matches_blockchain'] is False
            assert data['result_state'] == 'RESULTS_UNDER_REVIEW'
            assert data['official_results'] is False

        # RPC failure on get_total_active_ballots must NOT fake True
        with patch.object(BlockchainV2Service, 'get_election_state', return_value=7), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_final_tally', side_effect=[1, 0]), \
             patch.object(BlockchainV2Service, 'get_total_active_ballots', side_effect=RuntimeError('RPC down')):
            ok, _code, data = ResultsService.get_election_results(el.election_id, contract_address='0x610178dA211FEF7D417bC0e6FeD39F05609AD788')
            assert ok is True
            assert data['tally_matches_blockchain'] is False
            assert data['result_state'] == 'RESULTS_UNDER_REVIEW'


def test_phase4_v2_results_endpoint_gates_state_mismatch_and_maps_candidates(app, client):
    with app.app_context():
        el = _create_v2_results_election('ELEC_P4_ENDPOINT', status='OPEN', ended=False)

        class _FakeW3:
            def is_connected(self):
                return True

        # State 4 (VotingOpen) rejected cleanly when chain connected
        with patch.object(BlockchainV2Service, 'get_web3', return_value=_FakeW3()), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_election_state', return_value=4):
            r_open = client.get(f'/api/v2/voting/results?election_id={el.id}')
            assert r_open.status_code == 400
            assert r_open.get_json()['error'] == 'RESULTS_UNAVAILABLE'

        # Wrong election ID on contract rejected
        with patch.object(BlockchainV2Service, 'get_web3', return_value=_FakeW3()), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=9999):
            r_mis = client.get(f'/api/v2/voting/results?election_id={el.id}')
            assert r_mis.status_code == 400
            assert r_mis.get_json()['error'] == 'CONTRACT_ELECTION_MISMATCH'

        # Finalized state 7 returns mapped candidates & tallies cleanly
        db.session.add(
            BallotQueueV2(
                election_id=el.id,
                pseudonym='0x' + '2' * 64,
                sequence=1,
                ciphertexts_json='[]',
                proof_json='{}',
                state='CONFIRMED',
                superseded=False,
            )
        )
        db.session.commit()

        with patch.object(BlockchainV2Service, 'get_web3', return_value=_FakeW3()), \
             patch.object(BlockchainV2Service, 'get_election_id', return_value=el.id), \
             patch.object(BlockchainV2Service, 'get_election_state', return_value=7), \
             patch.object(BlockchainV2Service, 'get_total_active_ballots', return_value=1), \
             patch.object(BlockchainV2Service, 'get_final_tally', side_effect=[0, 1]):
            r_ok = client.get(f'/api/v2/voting/results?election_id={el.id}')
            assert r_ok.status_code == 200
            j = r_ok.get_json()
            assert j['tallies'] == [0, 1]
            assert j['candidates'][0]['name'] == 'Alice'
            assert j['candidates'][1]['name'] == 'Bob'
            assert j['candidates'][1]['votes'] == 1
            assert j['tally_matches_blockchain'] is True

