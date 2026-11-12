"""
V2 Simplified Election Manager
Vote Without Doubt

Automates on-chain BN254 ElGamal key provisioning, voting lifecycle,
and homomorphic tally finalization for the single-admin workflow.
Preserves complete ballot privacy (SEC-001) with zero manual officer ceremonies.
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models.admin import ApprovalRequest, Candidate
from app.models.ballot import Election
from app.models.ballot_record_v2 import (
    BallotQueueV2,
    compute_v2_ballot_leaf_hash,
    ensure_v2_receipt_code,
    get_active_v2_election_ballots,
)
from app.security.merkle import MerkleTree
from app.security.v2_keys import decrypt_v2_scalar, encrypt_v2_scalar
from app.services.blockchain_v2_service import (
    PROV_VERIFIED,
    BlockchainV2Service,
    get_provisioning_status,
    load_deployment_checkpoint,
)
from app.services.bn254_crypto import (
    generate_secure_scalar,
    generate_schnorr_pop,
    point_mul,
    G,
    generate_officer_decryption_shares,
    solve_discrete_log_tallies,
)

logger = logging.getLogger(__name__)


class V2ElectionManager:
    @staticmethod
    def _is_test_offline_bypass() -> bool:
        from flask import current_app
        try:
            if current_app and current_app.config.get('TESTING'):
                enabled = current_app.config.get('ENABLE_V2_DEPLOY_IN_TESTS', False)
                if isinstance(enabled, bool):
                    return not enabled
                return str(enabled).strip().lower() not in ('1', 'true', 'yes', 'on')
        except Exception:
            pass
        return False

    @staticmethod
    def ensure_v2_contract_deployed(
        election_id: Any,
        checkpoint_dir: Optional[str] = None,
        expected_chain_id: Optional[int] = None,
        w3_instance: Optional[Any] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Idempotently provision and verify the election-specific EVotingBallotBoxV2
        contract and checkpoint under PersistentElectionLock.
        """
        election = Election.query.filter(
            (Election.election_id == str(election_id)) |
            (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()
        if not election:
            return False, f"Election '{election_id}' not found.", None

        from app.services.election_lifecycle_worker import PersistentElectionLock
        with PersistentElectionLock(election.id, session=db.session) as acquired:
            if not acquired:
                return (
                    False,
                    "DEPLOYMENT_PENDING: Election provisioning lock is held by another worker.",
                    None,
                )

            if V2ElectionManager._is_test_offline_bypass():
                existing_cp = load_deployment_checkpoint(election.id, checkpoint_dir=checkpoint_dir)
                if existing_cp:
                    return True, PROV_VERIFIED, existing_cp
                return True, "TEST_OFFLINE_BYPASS", None

            service = BlockchainV2Service.for_election(election.id, w3_instance=w3_instance)
            try:
                ok, msg, cp = service.deploy_election_contract(
                    election,
                    checkpoint_dir=checkpoint_dir,
                    expected_chain_id=expected_chain_id,
                )
                if ok and not getattr(election, 'protocol_version', None):
                    election.protocol_version = 'V2'
                    db.session.commit()
                return ok, msg, cp
            except Exception as exc:
                logger.error("ensure_v2_contract_deployed failed for election %s: %s", election.id, exc)
                return False, f"DEPLOYMENT_FAILED: {exc}", None

    @staticmethod
    def provision_and_open_election(election_id: Any) -> Tuple[bool, str]:
        """
        Provisions BN254 threshold keys on-chain via relayer and opens voting.
        Transitions election to 'OPEN' only after dedicated V2 contract & checkpoint verify.
        """
        election = Election.query.filter(
            (Election.election_id == str(election_id)) |
            (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()
        if not election:
            return False, f"Election '{election_id}' not found."

        if election.candidate_count < 2:
            return False, "Election must have at least 2 candidates before opening."

        from app.services.election_lifecycle_worker import PersistentElectionLock
        with PersistentElectionLock(election.id, session=db.session) as acquired:
            if not acquired:
                return False, "DEPLOYMENT_PENDING: Provisioning lock is held by another process."

            # Ensure V2 private key shares exist or generate them (encrypted at rest)
            keys_updated = False
            if not election.v2_priv_key_1:
                election.v2_priv_key_1 = encrypt_v2_scalar(generate_secure_scalar())
                keys_updated = True
            if not election.v2_priv_key_2:
                election.v2_priv_key_2 = encrypt_v2_scalar(generate_secure_scalar())
                keys_updated = True
            if not getattr(election, 'protocol_version', None):
                election.protocol_version = 'V2'
                keys_updated = True
            if keys_updated:
                db.session.commit()

            s1 = decrypt_v2_scalar(election.v2_priv_key_1)
            s2 = decrypt_v2_scalar(election.v2_priv_key_2)

            # In offline unit tests without ENABLE_V2_DEPLOY_IN_TESTS, transition DB state directly
            if V2ElectionManager._is_test_offline_bypass():
                election.status = 'OPEN'
                db.session.commit()
                AuditLogger().log('ELECTION_V2_OPENED_OFFLINE', {'election_id': election.id})
                return True, "Election opened in offline/test mode."

            # Fail closed if blockchain node is unreachable or V2 contract not deployed & verified
            probe_service = BlockchainV2Service.for_election(election.id)
            try:
                w3 = probe_service.get_web3()
                is_connected = bool(w3 and w3.is_connected())
            except Exception:
                is_connected = False

            if not is_connected:
                return False, "RPC_UNAVAILABLE: Blockchain node unreachable; cannot open election without verified V2 contract."

            ok_dep, dep_msg, _ = V2ElectionManager.ensure_v2_contract_deployed(election.id)
            if not ok_dep:
                return False, dep_msg

            service = BlockchainV2Service.for_election(election.id)
            target_addr = service.contract_address
            if not target_addr or get_provisioning_status(election.id) != PROV_VERIFIED:
                return False, "DEPLOYMENT_FAILED: V2 deployment checkpoint missing or unverified after provisioning."

            ok_sync, reason_sync = service.verify_chain_synchronization(election, contract_address=target_addr)
            if not ok_sync:
                return False, reason_sync

            ok_v2, reason_v2 = service.verify_deployed_v2_contract(target_addr, election)
            if not ok_v2:
                return False, reason_v2

            contract = service.get_contract(target_addr)
            w3 = service.get_web3()
            chain_id = w3.eth.chain_id

            try:
                state = contract.functions.state().call()
                # States 0, 1, 2: Setup or partial key registration
                if state in (0, 1, 2):
                    o1_reg = contract.functions.officer1Registered().call()
                    o2_reg = contract.functions.officer2Registered().call()

                    if not o1_reg:
                        pop1 = generate_schnorr_pop(
                            priv_key=s1,
                            officer_id=1,
                            officer_address=None,
                            election_id=election.id,
                            contract_address=contract.address,
                            chain_id=chain_id,
                        )
                        service.register_officer(1, pop1['pub_key'], pop1['pop'], contract_address=contract.address)

                    if not o2_reg:
                        pop2 = generate_schnorr_pop(
                            priv_key=s2,
                            officer_id=2,
                            officer_address=None,
                            election_id=election.id,
                            contract_address=contract.address,
                            chain_id=chain_id,
                        )
                        service.register_officer(2, pop2['pub_key'], pop2['pop'], contract_address=contract.address)

                    state = contract.functions.state().call()

                # State 3: KeyRegistrationComplete -> Open Voting
                if state == 3:
                    admin_key, admin_addr = service.resolve_admin_credentials()
                    service.open_voting(admin_addr, private_key=admin_key, contract_address=contract.address)
                    state = contract.functions.state().call()

                if state == 4:
                    election.status = 'OPEN'
                    db.session.commit()
                    AuditLogger().log('ELECTION_V2_PROVISIONED_AND_OPENED', {'election_id': election.id})
                    return True, "Election successfully provisioned on-chain and voting is now OPEN."

                return False, f"Unexpected contract state after provisioning: {state}"

            except Exception as exc:
                logger.error("Failed to provision and open election on-chain: %s", exc)
                return False, f"On-chain provisioning failed: {exc}"

    @staticmethod
    def _has_approved_emergency_close(election: Election) -> bool:
        """Return True if a two-officer EMERGENCY_CLOSE approval exists for this election."""
        req = ApprovalRequest.query.filter(
            ApprovalRequest.election_id.in_([str(election.election_id), str(election.id)]),
            ApprovalRequest.action_type == 'EMERGENCY_CLOSE',
            ApprovalRequest.status == 'APPROVED',
        ).first()
        return req is not None

    @staticmethod
    def close_and_finalize_election(election_id: Any) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Closes voting, computes homomorphic decryption shares, and finalizes tally on-chain.
        Enforces scheduled end_time validation even in offline/test mode, sets closed_at
        upon closure, and never claims on-chain finalization when offline.
        """
        election = Election.query.filter(
            (Election.election_id == str(election_id)) |
            (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()
        if not election:
            return False, f"Election '{election_id}' not found.", {'permanent': True, 'error_code': 'NOT_FOUND'}

        from flask import current_app
        is_testing = False
        try:
            if current_app and current_app.config.get('TESTING'):
                is_testing = True
        except Exception:
            pass

        service = BlockchainV2Service.for_election(election.id)
        is_connected = False
        try:
            w3 = service.get_web3()
            is_connected = bool(w3 and w3.is_connected())
        except Exception:
            is_connected = False

        now = datetime.utcnow()

        def _validate_scheduled_end_time() -> Optional[Tuple[bool, str, Dict[str, Any]]]:
            if election.status in ('OPEN', 'ACTIVE'):
                if V2ElectionManager._has_approved_emergency_close(election):
                    return None
                if not election.end_time or now < election.end_time:
                    end_label = election.end_time.isoformat() if election.end_time else 'UNSET'
                    return (
                        False,
                        f"Cannot close election before end_time '{end_label}'. Current: '{now.isoformat()}'. "
                        "For early closure, two-officer EMERGENCY_CLOSE approval is required.",
                        {'error_code': 'INVALID_LIFECYCLE_TRANSITION', 'permanent': False},
                    )
            return None

        test_bypass = V2ElectionManager._is_test_offline_bypass()
        if test_bypass or not is_connected:
            if election.status == 'FINALIZED':
                return True, "Election is already finalized.", {
                    'tallies': [],
                    'finalized_on_chain': True,
                    'offline': True,
                }
            if election.status == 'CLOSED' and not test_bypass and not is_connected:
                return False, "Blockchain node unavailable; cannot finalize closed election on-chain.", {
                    'error_code': 'BLOCKCHAIN_UNAVAILABLE',
                    'permanent': False,
                    'finalized_on_chain': False,
                }
            if election.status not in ('OPEN', 'ACTIVE'):
                return False, (
                    f"Cannot close election in state '{election.status}'. Election must be OPEN."
                ), {'error_code': 'INVALID_LIFECYCLE_TRANSITION', 'permanent': False}

            blocked = _validate_scheduled_end_time()
            if blocked:
                return blocked

            election.status = 'CLOSED'
            if not election.closed_at:
                election.closed_at = now
            db.session.commit()
            AuditLogger().log('ELECTION_CLOSED_OFFLINE', {
                'election_id': str(election.election_id),
                'closed_at': election.closed_at.isoformat(),
                'finalized_on_chain': False,
            })
            return True, "Election closed in offline/test mode (not finalized on-chain).", {
                'tallies': [],
                'finalized_on_chain': False,
                'offline': True,
                'closed_at': election.closed_at.isoformat(),
            }

        contract = service.get_contract()
        relayer_key, relayer_addr = service.resolve_relayer_credentials()
        chain_id = w3.eth.chain_id

        try:
            state = contract.functions.state().call()

            # State 4: VotingOpen -> Close Voting
            if state == 4:
                if election.status not in ('OPEN', 'ACTIVE', 'CLOSED'):
                    return False, (
                        f"Cannot close election in state '{election.status}'. Election must be OPEN."
                    ), {'error_code': 'INVALID_LIFECYCLE_TRANSITION', 'permanent': False}

                blocked = _validate_scheduled_end_time()
                if blocked:
                    return blocked

                admin_key, admin_addr = service.resolve_admin_credentials()
                service.close_voting(admin_addr, private_key=admin_key, contract_address=contract.address)
                election.status = 'CLOSED'
                if not election.closed_at:
                    election.closed_at = datetime.utcnow()
                db.session.commit()
                state = contract.functions.state().call()

            # Helper: load aggregate ciphertexts and officer decryption shares/proofs cleanly
            def _load_agg_and_shares():
                s1 = decrypt_v2_scalar(election.v2_priv_key_1) if election.v2_priv_key_1 else 0
                s2 = decrypt_v2_scalar(election.v2_priv_key_2) if election.v2_priv_key_2 else 0
                if s1 == 0 or s2 == 0:
                    return None
                candidate_count = contract.functions.candidateCount().call()
                A_agg: List[Tuple[int, int]] = []
                B_agg: List[Tuple[int, int]] = []
                for j in range(candidate_count):
                    aj, bj = service.get_aggregate_ciphertext(j, contract_address=contract.address)
                    A_agg.append(aj)
                    B_agg.append(bj)
                res1 = generate_officer_decryption_shares(
                    officer_priv_key=s1,
                    officer_id=1,
                    aggregate_a=A_agg,
                    election_id=election.id,
                    contract_address=contract.address,
                    chain_id=chain_id,
                )
                res2 = generate_officer_decryption_shares(
                    officer_priv_key=s2,
                    officer_id=2,
                    aggregate_a=A_agg,
                    election_id=election.id,
                    contract_address=contract.address,
                    chain_id=chain_id,
                )
                return candidate_count, B_agg, res1, res2

            def _record_v2_finalized_state(tallies: List[int]) -> None:
                fin_now = datetime.utcnow()
                if not election.closed_at:
                    election.closed_at = fin_now
                if not election.finalized_at:
                    election.finalized_at = fin_now
                if not election.merkle_root:
                    active_ballots = get_active_v2_election_ballots(election.id)
                    for b in active_ballots:
                        ensure_v2_receipt_code(b)
                    leaf_hashes = [compute_v2_ballot_leaf_hash(b) for b in active_ballots]
                    tree = MerkleTree(leaf_hashes, sort_leaves=True)
                    election.merkle_root = tree.root
                    AuditLogger().log('ELECTION_MERKLE_ROOT_FINALIZED', {
                        'election_id': str(election.election_id),
                        'merkle_root': tree.root,
                        'leaf_count': tree.leaf_count,
                    })
                election.status = 'FINALIZED'
                db.session.commit()

            # State 5: VotingClosed -> Submit Decryption Shares
            if state == 5:
                loaded = _load_agg_and_shares()
                if not loaded:
                    return False, "Cannot finalize: Election private keys not found in database.", {
                        'permanent': True,
                        'error_code': 'V2_KEYS_MISSING',
                    }
                candidate_count, B_agg, res1, res2 = loaded

                # Submit decryption shares via relayer (resilient to partial submission)
                o1_shares = contract.functions.officerSharesSubmitted(1).call()
                o2_shares = contract.functions.officerSharesSubmitted(2).call()

                if not o1_shares:
                    service.submit_decryption_shares(1, res1['shares'], res1['proofs'], contract_address=contract.address)
                if not o2_shares:
                    service.submit_decryption_shares(2, res2['shares'], res2['proofs'], contract_address=contract.address)

                state = contract.functions.state().call()

            # State 6: DecryptionSharesComplete -> Solve discrete log & Finalize Tally
            if state == 6:
                total_active: Optional[int] = None
                if hasattr(contract.functions, 'totalActiveBallots'):
                    try:
                        total_active = int(contract.functions.totalActiveBallots().call())
                    except Exception:
                        total_active = None

                if total_active == 0:
                    candidate_count = int(contract.functions.candidateCount().call())
                    try:
                        receipt = service.finalize_zero_vote_election(
                            relayer_addr,
                            private_key=relayer_key,
                            contract_address=contract.address,
                        )
                    except Exception as zv_exc:
                        if election.status in ('OPEN', 'ACTIVE'):
                            election.status = 'CLOSED'
                        if not election.closed_at:
                            election.closed_at = datetime.utcnow()
                        db.session.commit()
                        AuditLogger().log('ELECTION_V2_ZERO_VOTE_FINALIZE_UNSUPPORTED', {
                            'election_id': str(election.election_id),
                            'db_election_id': election.id,
                            'error': str(zv_exc),
                        })
                        return False, (
                            f"Zero-vote election cannot be finalized on this deployed contract: {zv_exc}"
                        ), {
                            'permanent': True,
                            'error_code': 'ZERO_VOTES_UNSUPPORTED_BY_CONTRACT',
                            'zero_vote': True,
                            'finalized_on_chain': False,
                        }

                    tallies = [0] * candidate_count
                    _record_v2_finalized_state(tallies)
                    AuditLogger().log('ELECTION_V2_FINALIZED', {
                        'election_id': election.id,
                        'tallies': tallies,
                        'zero_vote': True,
                    })
                    return True, "Zero-vote election successfully closed and tallies verified on-chain.", {
                        'tallies': tallies,
                        'zero_vote': True,
                        'finalized_on_chain': True,
                        'tx_hash': receipt.get('tx_hash') if receipt else None,
                    }

                loaded = _load_agg_and_shares()
                if not loaded:
                    return False, "Cannot finalize: Election private keys not found in database.", {
                        'permanent': True,
                        'error_code': 'V2_KEYS_MISSING',
                    }
                candidate_count, B_agg, res1, res2 = loaded

                shares1_pts = [(int(s['x']), int(s['y'])) for s in res1['shares']]
                shares2_pts = [(int(s['x']), int(s['y'])) for s in res2['shares']]
                max_votes = 100000
                tallies = solve_discrete_log_tallies(
                    aggregate_b=B_agg,
                    shares1=shares1_pts,
                    shares2=shares2_pts,
                    candidate_count=candidate_count,
                    max_ballots=max_votes,
                )

                # Finalize on-chain
                receipt = service.finalize_tally(tallies, relayer_addr, private_key=relayer_key, contract_address=contract.address)

                _record_v2_finalized_state(tallies)
                AuditLogger().log('ELECTION_V2_FINALIZED', {'election_id': election.id, 'tallies': tallies})

                return True, "Election successfully closed and tallies verified on-chain.", {
                    'tallies': tallies,
                    'finalized_on_chain': True,
                    'tx_hash': receipt.get('tx_hash') if receipt else None
                }

            if state == 7: # Finalized
                candidate_count = contract.functions.candidateCount().call()
                tallies = [service.get_final_tally(j, contract_address=contract.address) for j in range(candidate_count)]
                _record_v2_finalized_state(tallies)
                return True, "Election is already finalized.", {'tallies': tallies, 'finalized_on_chain': True}

            return False, f"Unexpected contract state: {state}", {}

        except Exception as exc:
            err_msg = str(exc)
            logger.error("Failed to close and finalize election on-chain: %s", err_msg)
            if 'NO_BALLOTS_CAST' in err_msg.upper():
                if election.status in ('OPEN', 'ACTIVE'):
                    election.status = 'CLOSED'
                if not election.closed_at:
                    election.closed_at = datetime.utcnow()
                db.session.commit()
                return False, f"Finalization failed: {err_msg}", {
                    'permanent': True,
                    'error_code': 'ZERO_VOTES_UNSUPPORTED_BY_CONTRACT',
                    'zero_vote': True,
                    'finalized_on_chain': False,
                }
            return False, f"Finalization failed: {err_msg}", {}
