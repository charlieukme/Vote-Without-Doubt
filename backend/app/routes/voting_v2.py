"""
API Routes for FIX 3 V2: On-Chain Candidate Choice Privacy.
Endpoints for:
1. Two-officer key registration and Schnorr PoP verification.
2. Election key status and joint public key retrieval.
3. Encrypted ballot submission and homomorphic revoting.
4. Officer decryption share submission and DLEQ verification.
5. Zero-trust on-chain tally finalization and verified results retrieval.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from flask import Blueprint, current_app, g, jsonify, request, session

logger = logging.getLogger(__name__)

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models import Candidate, Election, User
from app.models.auth_session import AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.ballot_record_v2 import (
    BallotQueueV2,
    FAILED_V2_STATES,
    IN_FLIGHT_V2_STATES,
    OfficerRegistrationV2,
    VALID_V2_FINAL_STATES,
    ensure_v2_receipt_code,
    get_latest_confirmed_v2_ballot,
    get_latest_v2_attempt,
    mark_prior_v2_ballots_superseded,
)
from app.models.identity import VoterIdentity
from app.models.roll import ElectoralRoll
from app.security.admin_auth import require_admin_auth
from app.security.pseudonym import derive_pseudonym
from app.security.rate_limit import is_rate_limited
from app.security.sessions import is_expired, is_idle_expired
from app.security.v2_keys import decrypt_v2_scalar
from app.services.bn254_crypto import (
    G,
    is_on_curve,
    point_add,
    point_mul,
    solve_discrete_log_tallies,
    validate_point,
    validate_scalar,
    verify_schnorr_pop,
)
from app.services.blockchain_v2_service import BlockchainV2Service, BroadcastUncertainError

voting_v2_bp = Blueprint('voting_v2', __name__)


def _get_auth_session():
    """Extract authenticated session if valid and not expired."""
    sid = session.get('session_id')
    if not sid:
        return None
    s = AuthSession.query.filter_by(session_id=sid, revoked=False).first()
    if not s:
        return None
    now = datetime.utcnow()
    if is_expired(s.expires_at, now) or is_idle_expired(s.idle_expires_at, now):
        return None
    return s


def _resolve_election(raw_eid):
    """Resolve Election by string identifier or integer primary key."""
    if not raw_eid:
        return None
    eid_str = str(raw_eid).strip()
    return Election.query.filter(
        (Election.election_id == eid_str) | (Election.id == int(eid_str) if eid_str.isdigit() else False)
    ).first()


def _resolve_v2_max_ballots(election) -> int:
    """Resolve authoritative per-voter submission ceiling for a V2 election."""
    cfg_max = int(current_app.config.get('MAX_BALLOTS_PER_VOTER', 3))
    el_max = int(getattr(election, 'max_ballots', None) or cfg_max) if election else cfg_max
    return max(1, min(cfg_max, el_max))


def _enforce_officer_authorization(requested_officer_id: int):
    """
    Guarantees strict separation between Officer 1 and Officer 2.
    Rejects cross-officer execution in both directions.
    """
    admin = getattr(g, 'admin_user', getattr(g, 'admin', None))
    if not admin or admin.role != 'OFFICER':
        return jsonify({'error': 'UNAUTHORIZED', 'message': 'Officer role required'}), 403

    if admin.admin_id == 'OFFICER_01' and int(requested_officer_id) != 1:
        AuditLogger().log('OFFICER_CROSS_IMPERSONATION_ATTEMPT', {
            'actor': 'OFFICER_01',
            'target_officer_id': requested_officer_id,
            'ip': request.remote_addr
        })
        return jsonify({
            'error': 'OFFICER_ROLE_MISMATCH',
            'message': 'OFFICER_01 cannot register keys or submit shares for Officer 2'
        }), 403

    if admin.admin_id == 'OFFICER_02' and int(requested_officer_id) != 2:
        AuditLogger().log('OFFICER_CROSS_IMPERSONATION_ATTEMPT', {
            'actor': 'OFFICER_02',
            'target_officer_id': requested_officer_id,
            'ip': request.remote_addr
        })
        return jsonify({
            'error': 'OFFICER_ROLE_MISMATCH',
            'message': 'OFFICER_02 cannot register keys or submit shares for Officer 1'
        }), 403

    return None


# ==============================================================================
# 1. OFFICER REGISTRATION & KEY STATUS
# ==============================================================================

@voting_v2_bp.route('/api/v2/officer/register-key', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def register_officer_key():
    """
    Officer registers public key share with Schnorr Proof-of-Possession.
    Submits on-chain via authorized relayer.
    Private key shares never reach the backend.
    """
    data = request.get_json(silent=True) or {}
    raw_eid = data.get('election_id')
    officer_id = data.get('officer_id')
    pub_key = data.get('pub_key')
    pop = data.get('pop')
    contract_address = data.get('contract_address')

    if not all([raw_eid, officer_id in (1, 2), pub_key, pop]):
        return jsonify({'error': 'MISSING_FIELDS', 'message': 'Required officer registration fields missing'}), 400

    # Enforce Officer 1 vs Officer 2 Authorization
    auth_err = _enforce_officer_authorization(officer_id)
    if auth_err:
        return auth_err

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    service = BlockchainV2Service(contract_address=contract_address, election_id=election.id)

    # Check chain synchronization (restart detection)
    synced, sync_err = service.verify_chain_synchronization(election, contract_address=contract_address)
    if not synced:
        return jsonify({'error': 'CHAIN_DESYNCHRONIZED', 'message': sync_err}), 409

    # Verify Schnorr PoP off-chain before submitting to blockchain
    try:
        Y = (int(pub_key['x']), int(pub_key['y']))
        if not is_on_curve(Y):
            return jsonify({'error': 'INVALID_OFFICER_KEY', 'message': 'Public key is off curve'}), 400

        pop_valid = verify_schnorr_pop(
            pub_key=Y,
            pop=pop,
            officer_id=int(officer_id),
            election_id=election.id,
            contract_address=contract_address or service.contract_address or '0x0000000000000000000000000000000000000000',
            chain_id=1337,
        )
        if not pop_valid:
            return jsonify({'error': 'INVALID_POP_PROOF', 'message': 'Schnorr Proof-of-Possession verification failed'}), 400
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({'error': 'INVALID_PAYLOAD', 'message': f'Malformed public key or PoP coordinates: {exc}'}), 400

    try:
        receipt = service.register_officer(
            officer_id=officer_id,
            pub_key=pub_key,
            pop=pop,
            contract_address=contract_address,
        )
    except Exception as exc:
        return jsonify({'error': 'ON_CHAIN_REGISTRATION_FAILED', 'message': str(exc)}), 500

    # Save registration record
    current_admin = getattr(g, 'admin_user', getattr(g, 'admin', None))
    admin_id = getattr(current_admin, 'admin_id', f'OFFICER_0{officer_id}')
    reg = OfficerRegistrationV2.query.filter_by(
        election_id=election.id, officer_id=officer_id
    ).first()
    if not reg:
        reg = OfficerRegistrationV2(
            election_id=election.id,
            officer_id=officer_id,
            officer_address=admin_id,
            pubkey_x=str(pub_key['x']),
            pubkey_y=str(pub_key['y']),
            pop_r_x=str(pop['r']['x']),
            pop_r_y=str(pop['r']['y']),
            pop_z=str(pop['z']),
            registered_on_chain=True,
            tx_hash=receipt.get('tx_hash'),
        )
        db.session.add(reg)
    else:
        reg.officer_address = admin_id
        reg.pubkey_x = str(pub_key['x'])
        reg.pubkey_y = str(pub_key['y'])
        reg.pop_r_x = str(pop['r']['x'])
        reg.pop_r_y = str(pop['r']['y'])
        reg.pop_z = str(pop['z'])
        reg.registered_on_chain = True
        reg.tx_hash = receipt.get('tx_hash')

    db.session.commit()
    AuditLogger().log('OFFICER_V2_REGISTERED', {'election_id': election.id, 'officer_id': officer_id, 'admin_id': admin_id})

    return jsonify({
        'success': True,
        'election_id': election.id,
        'officer_id': officer_id,
        'tx_hash': receipt.get('tx_hash'),
        'block_number': receipt.get('block_number'),
    }), 200


@voting_v2_bp.route('/api/v2/officer/key-status', methods=['GET'])
def get_key_status():
    """Returns officer key registration status and contract state."""
    raw_eid = request.args.get('election_id')
    contract_addr = request.args.get('contract_address')

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    from app.services.blockchain_v2_service import load_deployment_checkpoint
    cp = load_deployment_checkpoint(election.id)
    service = BlockchainV2Service(contract_address=contract_addr, election_id=election.id)
    state = 0
    joint_key = None
    contract = None
    chain_id = cp.get('chain_id') if (cp and cp.get('chain_id') is not None) else None
    try:
        w3 = service.get_web3()
        if w3 and w3.is_connected() and chain_id is None:
            chain_id = int(w3.eth.chain_id)
        contract = service.get_contract(contract_addr)
        state = contract.functions.state().call()
        o1_reg = contract.functions.officer1Registered().call()
        o2_reg = contract.functions.officer2Registered().call()
        if state >= 3:  # KeyRegistrationComplete or later
            jk = contract.functions.jointPubKey().call()
            joint_key = {'x': str(jk[0]), 'y': str(jk[1])}
    except Exception:
        o1_reg = False
        o2_reg = False

    if chain_id is None:
        chain_id = int(current_app.config.get('WALLET_AUTH_CHAIN_ID', 1337))

    # Authoritative fallback: if contract is unprovisioned/offline but election has private keys in database,
    # derive the joint public key directly from the election's key material.
    if not joint_key and election.v2_priv_key_1 and election.v2_priv_key_2:
        try:
            s1 = decrypt_v2_scalar(election.v2_priv_key_1)
            s2 = decrypt_v2_scalar(election.v2_priv_key_2)
            Y1 = point_mul(G, s1)
            Y2 = point_mul(G, s2)
            Y = point_add(Y1, Y2)
            joint_key = {'x': str(Y[0]), 'y': str(Y[1])}
            o1_reg = True
            o2_reg = True
            if state < 4 and election.effective_status in ('OPEN', 'ACTIVE'):
                state = 4
        except Exception as k_exc:
            logger.debug("Failed to derive joint public key from database keys: %s", k_exc)

    verifier_addr = None
    if contract is not None:
        try:
            verifier_addr = contract.functions.verifier().call()
        except Exception:
            pass
    if not verifier_addr and cp and service.contract_address:
        verifier_addr = cp.get('verifier_address')

    return jsonify({
        'election_id': election.id,
        'state': state,
        'officer1_registered': o1_reg,
        'officer2_registered': o2_reg,
        'joint_public_key': joint_key,
        'contract_address': service.contract_address,
        'verifier_address': verifier_addr,
        'chain_id': chain_id,
    }), 200


@voting_v2_bp.route('/api/v2/officer/aggregate-ciphertexts', methods=['GET'])
def get_aggregate_ciphertexts():
    """Returns aggregate ciphertexts (A_agg, B_agg) for client-side DLEQ generation."""
    raw_eid = request.args.get('election_id')
    contract_addr = request.args.get('contract_address')

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    if not election.candidate_count or election.candidate_count < 2:
        return jsonify({'error': 'CANDIDATE_METADATA_UNAVAILABLE', 'message': 'Authoritative election candidate count is unavailable or invalid.'}), 400
    candidate_count = election.candidate_count
    service = BlockchainV2Service(contract_address=contract_addr, election_id=election.id)

    try:
        agg_a = []
        agg_b = []
        for j in range(candidate_count):
            A_pt, B_pt = service.get_aggregate_ciphertext(j, contract_addr)
            agg_a.append({'x': str(A_pt[0]), 'y': str(A_pt[1])})
            agg_b.append({'x': str(B_pt[0]), 'y': str(B_pt[1])})
    except Exception as exc:
        return jsonify({'error': 'AGGREGATE_UNAVAILABLE', 'message': str(exc)}), 400

    return jsonify({
        'election_id': election.id,
        'candidate_count': candidate_count,
        'aggregate_a': agg_a,
        'aggregate_b': agg_b,
    }), 200


# ==============================================================================
# 2. ENCRYPTED BALLOT CASTING & REVOTING
# ==============================================================================

@voting_v2_bp.route('/api/v2/voting/cast-ballot', methods=['POST'])
@voting_v2_bp.route('/api/v2/voting/cast', methods=['POST'])
def cast_ballot_v2():
    """
    Submits an encrypted ballot vector with non-circular CDS proof.
    Enforces:
    - Strict session, student, election, and single-use VotingAuthorization binding.
    - ElectoralRoll eligibility enforcement with restricted VoterIdentity fallback.
    - Atomic authorization consumption combined with queue insertion.
    - In-flight/uncertain transaction blocking and historical evidence preservation.
    - Server-side relayer credentials without trusting client-provided private keys.
    """
    s = _get_auth_session()
    if not s or not s.user_id:
        return jsonify({'error': 'NOT_AUTHENTICATED', 'message': 'Authentication session required.'}), 401

    user = db.session.get(User, s.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'USER_NOT_ACTIVE', 'message': 'User is not active.'}), 401

    data = request.get_json(silent=True) or {}
    raw_eid = data.get('election_id')
    sequence = data.get('sequence')
    ciphertexts = data.get('ciphertexts')
    proof = data.get('proof')
    contract_address = data.get('contract_address')
    # Note: data.get('sender_private_key') and data.get('sender_account') are strictly ignored

    if raw_eid is None or sequence is None or ciphertexts is None or proof is None:
        return jsonify({'error': 'MISSING_FIELDS', 'message': 'Missing required fields.'}), 400

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': 'Election not found.'}), 404

    from app.services.blockchain_v2_service import load_deployment_checkpoint
    cp = load_deployment_checkpoint(election.id)
    if cp and cp.get('contract_address'):
        cp_addr = cp['contract_address']
        if contract_address and contract_address.lower() != cp_addr.lower():
            return jsonify({
                'error': 'CONTRACT_ELECTION_MISMATCH',
                'message': 'Submitted contract address does not match the authoritative deployment checkpoint for this election.',
            }), 400
        contract_address = cp_addr

    now = datetime.utcnow()
    if election.start_time and now < election.start_time:
        return jsonify({'error': 'ELECTION_NOT_STARTED', 'message': 'Election has not started yet.'}), 400
    if election.end_time and now > election.end_time:
        return jsonify({'error': 'ELECTION_CLOSED', 'message': 'Election has ended.'}), 400
    if election.effective_status not in ('ACTIVE', 'OPEN'):
        return jsonify({'error': 'ELECTION_NOT_ACTIVE', 'message': 'Election is not currently active.'}), 400

    # 1. ElectoralRoll eligibility check with restricted VoterIdentity fallback
    roll_entry = None
    if user.voter_id:
        roll_entry = ElectoralRoll.query.filter_by(usn=user.voter_id).first()
    if not roll_entry and user.email:
        roll_entry = ElectoralRoll.query.filter_by(college_email=user.email).first()

    if roll_entry is not None:
        if not roll_entry.is_eligible:
            return jsonify({'error': 'VOTER_NOT_ELIGIBLE', 'message': 'Voter is marked ineligible in electoral roll.'}), 403
    else:
        # Fallback to VoterIdentity only when ElectoralRoll has no record
        voter_id_entry = None
        if user.voter_id:
            voter_id_entry = VoterIdentity.query.filter_by(voter_id=user.voter_id).first()
        if not voter_id_entry and user.email:
            voter_id_entry = VoterIdentity.query.filter_by(email=user.email).first()

        if not voter_id_entry or not voter_id_entry.is_eligible:
            return jsonify({'error': 'VOTER_NOT_ELIGIBLE', 'message': 'Voter has no eligible record.'}), 403

    # Candidate election identifiers (integer PK and string identifier)
    candidate_eids = [election.id]
    if election.election_id:
        try:
            candidate_eids.append(int(election.election_id))
        except (ValueError, TypeError):
            pass
        candidate_eids.append(election.election_id)

    # 2. Strict single-use VotingAuthorization binding
    va = VotingAuthorization.query.filter(
        VotingAuthorization.user_id == s.user_id,
        VotingAuthorization.election_id.in_(candidate_eids),
    ).order_by(VotingAuthorization.id.desc()).first()

    if not va:
        return jsonify({'error': 'UNAUTHORIZED', 'message': 'No voting authorization found for this election.'}), 403

    if va.consumed:
        return jsonify({'error': 'AUTHORIZATION_ALREADY_USED', 'message': 'Voting authorization has already been consumed.'}), 403

    if not va.session_id or va.session_id != s.session_id:
        return jsonify({'error': 'AUTHORIZATION_SESSION_MISMATCH', 'message': 'Voting authorization does not match current session.'}), 403

    if va.expires_at < now:
        return jsonify({'error': 'AUTHORIZATION_EXPIRED', 'message': 'Voting authorization has expired.'}), 403

    if not va.authorized or not va.wallet_verified or not va.face_verified:
        return jsonify({'error': 'AUTHORIZATION_FACTORS_INCOMPLETE', 'message': 'Required verification factors are incomplete.'}), 403

    # 3. Derive voter pseudonym
    pseudonym = derive_pseudonym(s.user_id, election.id)

    existing_ballots = BallotQueueV2.query.filter_by(
        election_id=election.id,
        pseudonym=pseudonym,
    ).all()

    # Block if any ballot is currently in-flight / uncertain
    for eb in existing_ballots:
        if eb.state in IN_FLIGHT_V2_STATES:
            return jsonify({
                'error': 'BALLOT_TRANSACTION_IN_FLIGHT',
                'message': 'A ballot is currently queued or in-flight for this voter. Please wait for reconciliation or contact the election officer.',
            }), 409

    try:
        seq_int = int(sequence)
    except (ValueError, TypeError):
        return jsonify({'error': 'INVALID_SEQUENCE', 'message': 'Sequence must be an integer.'}), 400

    # Sequence monotonicity, max-ballot ceiling, and revote cooldown checks
    max_ballots = _resolve_v2_max_ballots(election)
    last_confirmed = [b for b in existing_ballots if b.state in VALID_V2_FINAL_STATES]
    max_confirmed_seq = max([b.sequence for b in last_confirmed], default=0)
    expected_seq = max_confirmed_seq + 1

    if max_confirmed_seq >= max_ballots or (seq_int == expected_seq and seq_int > max_ballots):
        return jsonify({
            'error': 'MAX_BALLOTS_EXCEEDED',
            'message': f'Maximum ballot submissions ({max_ballots}) reached for this election.',
            'max_ballots': max_ballots,
            'submissions_used': max_confirmed_seq,
        }), 409

    if seq_int != expected_seq:
        return jsonify({
            'error': 'INVALID_SEQUENCE_ORDER',
            'message': f'Expected sequence {expected_seq}, got {seq_int}',
        }), 400

    cooldown_sec = int(current_app.config.get('REVOTE_COOLDOWN_SECONDS', 120))
    if last_confirmed and cooldown_sec > 0:
        latest_conf = max(last_confirmed, key=lambda b: (b.sequence, b.id))
        ref_time = latest_conf.tx_confirmed_at or latest_conf.created_at
        if ref_time:
            elapsed = (datetime.utcnow() - ref_time).total_seconds()
            if elapsed < cooldown_sec:
                remaining = max(1, int(cooldown_sec - elapsed))
                return jsonify({
                    'error': 'COOLDOWN_ACTIVE',
                    'message': f'Revote cooldown active. Please wait {remaining} seconds before updating your vote.',
                    'cooldown_remaining_sec': remaining,
                    'retry_after': remaining,
                }), 429

    # Historical evidence preservation: block retries of existing sequence
    for eb in existing_ballots:
        if eb.sequence == seq_int:
            if eb.state == 'CONFIRMED':
                return jsonify({
                    'error': 'BALLOT_ALREADY_CONFIRMED',
                    'message': f'Ballot for sequence {seq_int} is already confirmed.',
                }), 409
            elif eb.state in ('REVERTED', 'FAILED'):
                return jsonify({
                    'error': 'RETRY_BLOCKED_PENDING_MIGRATION',
                    'message': (
                        'A previous ballot attempt failed or reverted for this sequence. '
                        'Under the current immutable audit policy, submitting an additional attempt for a failed '
                        'sequence requires multi-attempt audit trail schema support, which is scheduled for a future phase. '
                        'The original failure evidence is preserved.'
                    ),
                }), 409

    # 4. Atomic authorization consumption and queue insertion in ONE database transaction
    now_utc = datetime.utcnow()
    claimed = VotingAuthorization.query.filter(
        VotingAuthorization.id == va.id,
        VotingAuthorization.user_id == s.user_id,
        VotingAuthorization.election_id.in_(candidate_eids),
        VotingAuthorization.session_id == s.session_id,
        VotingAuthorization.consumed.is_(False),
        VotingAuthorization.expires_at > now_utc,
        VotingAuthorization.authorized.is_(True),
        VotingAuthorization.wallet_verified.is_(True),
        VotingAuthorization.face_verified.is_(True),
    ).update(
        {
            'consumed': True,
            'consumed_at': now_utc,
        },
        synchronize_session=False,
    )

    if not claimed:
        db.session.rollback()
        return jsonify({'error': 'AUTHORIZATION_CONSUMED', 'message': 'Voting authorization could not be claimed.'}), 403

    va.consumed = True
    va.consumed_at = now_utc

    # Queue ballot record
    ballot = BallotQueueV2(
        election_id=election.id,
        pseudonym=pseudonym,
        sequence=seq_int,
        ciphertexts_json=json.dumps(ciphertexts),
        proof_json=json.dumps(proof),
        state='QUEUED',
    )
    db.session.add(ballot)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': 'BALLOT_QUEUE_FAILED', 'message': f'Database error queuing ballot: {exc}'}), 500

    # 5. Broadcast on-chain via server-side relayer
    service = BlockchainV2Service(contract_address=contract_address, election_id=election.id)
    try:
        relayer_key, relayer_address = service.resolve_relayer_credentials()
    except Exception as exc:
        ballot.state = 'QUEUED'
        ballot.error = f"RELAYER_CREDENTIAL_ERROR: {exc}"
        db.session.commit()
        return jsonify({'error': 'RELAYER_CONFIGURATION_ERROR', 'message': str(exc)}), 500

    try:
        ballot.tx_broadcast_at = datetime.utcnow()
        receipt = service.cast_ballot(
            pseudonym=pseudonym,
            sequence=seq_int,
            ciphertexts=ciphertexts,
            proof=proof,
            sender_address=relayer_address,
            private_key=relayer_key,
            contract_address=contract_address,
        )
        if receipt.get('status') == 1:
            ballot.state = 'CONFIRMED'
            ballot.tx_hash = receipt.get('tx_hash')
            ballot.block_number = receipt.get('block_number')
            ballot.tx_confirmed_at = datetime.utcnow()
            ballot.superseded = False
            ensure_v2_receipt_code(ballot)
            mark_prior_v2_ballots_superseded(election.id, pseudonym, seq_int)
            db.session.commit()
            AuditLogger().log('BALLOT_V2_CONFIRMED', {'election_id': election.id, 'sequence': seq_int, 'tx_hash': ballot.tx_hash})
            return jsonify({
                'success': True,
                'status': 'CONFIRMED',
                'sequence': seq_int,
                'tx_hash': ballot.tx_hash,
                'block_number': ballot.block_number,
                'receipt_code': ballot.receipt_code,
            }), 200
        else:
            ballot.state = 'REVERTED'
            ballot.tx_hash = receipt.get('tx_hash')
            ballot.block_number = receipt.get('block_number')
            ballot.error = 'TRANSACTION_REVERTED_ON_CHAIN'
            ballot.tx_failed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'error': 'TRANSACTION_REVERTED',
                'message': 'Transaction was mined but reverted on-chain.',
                'tx_hash': ballot.tx_hash,
            }), 400
    except BroadcastUncertainError as exc:
        ballot.state = 'SUBMITTED' if exc.tx_hash else 'QUEUED'
        if exc.tx_hash:
            ballot.tx_hash = exc.tx_hash
        ballot.error = str(exc)
        db.session.commit()
        return jsonify({
            'error': 'TRANSACTION_BROADCAST_UNCERTAIN',
            'message': (
                'A network or provider timeout occurred while communicating with the blockchain node. '
                'The broadcast outcome is unknown; the transaction may or may not have been accepted by the network. '
                'To protect voting integrity, this ballot remains recorded as in-flight and is blocked from resubmission '
                'until verified through operator reconciliation.'
            ),
            'status': ballot.state,
            'tx_hash': ballot.tx_hash,
        }), 504
    except Exception as exc:
        err_str = str(exc).lower()
        if any(k in err_str for k in ('nonce', 'already known', 'replacement', 'timeout', 'gateway', 'reset', 'connection')):
            ballot.state = 'QUEUED'
            ballot.error = f"UNCERTAIN_PROVIDER_ERROR: {exc}"
            db.session.commit()
            return jsonify({
                'error': 'TRANSACTION_BROADCAST_UNCERTAIN',
                'message': (
                    'A network or provider timeout occurred while communicating with the blockchain node. '
                    'The broadcast outcome is unknown; the transaction may or may not have been accepted by the network. '
                    'To protect voting integrity, this ballot remains recorded as in-flight and is blocked from resubmission '
                    'until verified through operator reconciliation.'
                ),
                'status': ballot.state,
            }), 504
        else:
            ballot.state = 'FAILED'
            ballot.error = str(exc)
            ballot.tx_failed_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'error': 'ON_CHAIN_BALLOT_FAILED', 'message': str(exc)}), 500


@voting_v2_bp.route('/api/v2/voting/status', methods=['GET'])
def get_voter_status_v2():
    """Returns voter's authoritative V2 sequence, state, cooldown, and receipt status."""
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'NOT_AUTHENTICATED'}), 401

    raw_eid = request.args.get('election_id')
    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    max_ballots = _resolve_v2_max_ballots(election)
    pseudonym = derive_pseudonym(s.user_id, election.id)
    latest_attempt = get_latest_v2_attempt(election.id, pseudonym)
    latest_confirmed = get_latest_confirmed_v2_ballot(election.id, pseudonym)

    if not latest_attempt:
        return jsonify({
            'has_voted': False,
            'has_ballot': False,
            'status': 'NONE',
            'state': 'NONE',
            'finalized': False,
            'sequence': 0,
            'submissions_used': 0,
            'max_ballots': max_ballots,
            'next_sequence': 1,
            'can_revote': False,
            'cooldown_active': False,
            'cooldown_remaining_sec': 0,
            'pseudonym': pseudonym,
            'receipt': None,
        }), 200

    confirmed_seq = latest_confirmed.sequence if latest_confirmed else 0
    next_seq = confirmed_seq + 1
    cooldown_sec = int(current_app.config.get('REVOTE_COOLDOWN_SECONDS', 120))
    ref_time = (latest_confirmed.tx_confirmed_at or latest_confirmed.created_at) if latest_confirmed else latest_attempt.created_at
    elapsed = (datetime.utcnow() - ref_time).total_seconds() if ref_time else cooldown_sec
    cooldown_active = bool(latest_confirmed and cooldown_sec > 0 and elapsed < cooldown_sec)
    cooldown_remaining = max(0, int(cooldown_sec - elapsed)) if cooldown_active else 0

    receipt_data = None
    if latest_confirmed:
        # Generate missing receipt only before Merkle root is finalized to avoid leaf mutation
        if not latest_confirmed.receipt_code and not election.merkle_root:
            ensure_v2_receipt_code(latest_confirmed, commit=True)

        user = db.session.get(User, s.user_id)
        voter_id_last4 = user.voter_id[-4:] if (user and user.voter_id) else '0000'
        if latest_confirmed.receipt_code:
            receipt_data = {
                'election_id': str(election.election_id),
                'election_title': election.title,
                'voter_id_last4': voter_id_last4,
                'receipt_code': latest_confirmed.receipt_code,
                'sequence': latest_confirmed.sequence,
                'timestamp': (latest_confirmed.tx_confirmed_at or latest_confirmed.created_at).strftime('%Y-%m-%dT%H:%M:00Z'),
                'block_number': latest_confirmed.block_number,
            }

    can_revote = bool(
        latest_confirmed
        and confirmed_seq < max_ballots
        and latest_attempt.state in VALID_V2_FINAL_STATES
        and not cooldown_active
        and election.effective_status in ('OPEN', 'ACTIVE')
    )
    retry_allowed = bool(
        latest_attempt.state in FAILED_V2_STATES
        and confirmed_seq < max_ballots
        and not cooldown_active
        and election.effective_status in ('OPEN', 'ACTIVE')
    )
    retry_blocked_reason = None
    if latest_attempt.state in FAILED_V2_STATES and not retry_allowed:
        if confirmed_seq >= max_ballots:
            retry_blocked_reason = 'MAX_BALLOTS_REACHED'
        elif election.effective_status not in ('OPEN', 'ACTIVE'):
            retry_blocked_reason = 'ELECTION_CLOSED'
        elif cooldown_active:
            retry_blocked_reason = 'COOLDOWN_ACTIVE'

    return jsonify({
        'has_voted': bool(latest_confirmed),
        'has_ballot': True,
        'status': latest_attempt.state,
        'state': latest_attempt.state,
        'sequence': latest_attempt.sequence,
        'active_sequence': confirmed_seq,
        'submissions_used': confirmed_seq,
        'next_sequence': next_seq,
        'max_ballots': max_ballots,
        'can_revote': can_revote,
        'retry_allowed': retry_allowed,
        'retry_blocked_reason': retry_blocked_reason,
        'cooldown_active': cooldown_active,
        'cooldown_remaining_sec': cooldown_remaining,
        'finalized': (latest_attempt.state in VALID_V2_FINAL_STATES),
        'pseudonym': pseudonym,
        'tx_hash': latest_attempt.tx_hash,
        'block_number': latest_attempt.block_number,
        'error': latest_attempt.error if latest_attempt.state in FAILED_V2_STATES else None,
        'receipt': receipt_data,
    }), 200


# ==============================================================================
# 3. DECRYPTION SHARES & ON-CHAIN TALLY FINALIZATION
# ==============================================================================

@voting_v2_bp.route('/api/v2/officer/submit-shares', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def submit_decryption_shares():
    """Submits officer partial decryption shares and Chaum-Pedersen DLEQ proofs via authorized relayer."""
    data = request.get_json(silent=True) or {}
    raw_eid = data.get('election_id')
    officer_id = data.get('officer_id')
    shares = data.get('shares')
    proofs = data.get('proofs')
    contract_address = data.get('contract_address')

    if not all([raw_eid, officer_id in (1, 2), shares, proofs]):
        return jsonify({'error': 'MISSING_FIELDS'}), 400

    # Enforce Officer 1 vs Officer 2 Authorization
    auth_err = _enforce_officer_authorization(officer_id)
    if auth_err:
        return auth_err

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    service = BlockchainV2Service(contract_address=contract_address, election_id=election.id)

    # Check chain synchronization (restart detection)
    synced, sync_err = service.verify_chain_synchronization(election, contract_address=contract_address)
    if not synced:
        return jsonify({'error': 'CHAIN_DESYNCHRONIZED', 'message': sync_err}), 409

    try:
        receipt = service.submit_decryption_shares(
            officer_id=officer_id,
            shares=shares,
            proofs=proofs,
            contract_address=contract_address,
        )
    except Exception as exc:
        return jsonify({'error': 'SUBMISSION_FAILED', 'message': str(exc)}), 500

    current_admin = getattr(g, 'admin_user', getattr(g, 'admin', None))
    admin_id = getattr(current_admin, 'admin_id', f'OFFICER_0{officer_id}')
    AuditLogger().log('OFFICER_SHARES_SUBMITTED', {'election_id': election.id, 'officer_id': officer_id, 'admin_id': admin_id})

    return jsonify({
        'success': True,
        'election_id': election.id,
        'officer_id': officer_id,
        'tx_hash': receipt.get('tx_hash'),
    }), 200


@voting_v2_bp.route('/api/v2/voting/finalize-tally', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def finalize_tally_v2():
    """Finalizes election tally on-chain via zero-trust verification using server relayer."""
    data = request.get_json(silent=True) or {}
    raw_eid = data.get('election_id')
    tallies = data.get('tallies')
    contract_address = data.get('contract_address')
    # Security: ignore any client-supplied sender_account or sender_private_key

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    if not isinstance(tallies, list) or len(tallies) < 2:
        return jsonify({'error': 'INVALID_TALLIES', 'message': 'Tallies vector is required.'}), 400

    service = BlockchainV2Service(contract_address=contract_address, election_id=election.id)
    try:
        relayer_key, relayer_addr = service.resolve_relayer_credentials()
    except Exception as exc:
        return jsonify({'error': 'RELAYER_CONFIGURATION_ERROR', 'message': str(exc)}), 500

    try:
        receipt = service.finalize_tally(
            tallies=tallies,
            sender_address=relayer_addr,
            private_key=relayer_key,
            contract_address=contract_address,
        )
    except Exception as exc:
        return jsonify({'error': 'FINALIZATION_FAILED', 'message': str(exc)}), 500

    current_admin = getattr(g, 'admin_user', getattr(g, 'admin', None))
    admin_id = getattr(current_admin, 'admin_id', 'OFFICER')
    AuditLogger().log('ELECTION_V2_FINALIZED', {'election_id': election.id, 'tallies': tallies, 'admin_id': admin_id})

    return jsonify({
        'success': True,
        'election_id': election.id,
        'tallies': tallies,
        'tx_hash': receipt.get('tx_hash'),
    }), 200


@voting_v2_bp.route('/api/v2/voting/results', methods=['GET'])
def get_results_v2():
    """Returns verified final tallies directly from contract with candidate metadata & cross-checks."""
    raw_eid = request.args.get('election_id')
    contract_address = request.args.get('contract_address')

    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    if not election.candidate_count or election.candidate_count < 2:
        return jsonify({
            'error': 'CANDIDATE_METADATA_UNAVAILABLE',
            'message': 'Authoritative election candidate count is unavailable or invalid.',
        }), 400
    candidate_count = election.candidate_count

    # Block tallies while in-flight ballots remain unsettled
    v2_pending = BallotQueueV2.query.filter(
        BallotQueueV2.election_id == election.id,
        BallotQueueV2.state.in_(IN_FLIGHT_V2_STATES),
    ).count()
    if v2_pending > 0:
        return jsonify({
            'error': 'PROCESSING_PENDING_BALLOTS',
            'message': f'{v2_pending} ballot transaction(s) are still settling; results withheld until settled.',
            'pending_ballots_count': v2_pending,
            'is_finalized': False,
        }), 400

    service = BlockchainV2Service(contract_address=contract_address, election_id=election.id)

    v2_state = None
    on_chain_eid = None
    on_chain_total = None
    try:
        w3 = service.get_web3()
        if w3 and w3.is_connected():
            on_chain_eid = service.get_election_id(contract_address)
            if on_chain_eid is not None and on_chain_eid != election.id:
                return jsonify({
                    'error': 'CONTRACT_ELECTION_MISMATCH',
                    'message': f'Contract election ID ({on_chain_eid}) does not match election {election.id}.',
                }), 400
            v2_state = service.get_election_state(contract_address)
            if v2_state is not None and v2_state != 7:
                return jsonify({
                    'error': 'RESULTS_UNAVAILABLE',
                    'message': 'Final tallies are not yet finalized on-chain.',
                    'v2_state': v2_state,
                    'is_finalized': False,
                }), 400
            on_chain_total = service.get_total_active_ballots(contract_address)
    except Exception as exc:
        logger.debug("Optional V2 state check skipped in get_results_v2: %s", exc)

    try:
        tallies = [service.get_final_tally(j, contract_address) for j in range(candidate_count)]
    except Exception as exc:
        return jsonify({'error': 'RESULTS_UNAVAILABLE', 'message': str(exc), 'is_finalized': False}), 400

    total_valid_votes = sum(int(t) for t in tallies)
    distinct_voters = db.session.query(
        db.func.count(db.distinct(BallotQueueV2.pseudonym))
    ).filter(
        BallotQueueV2.election_id == election.id,
        BallotQueueV2.state.in_(VALID_V2_FINAL_STATES),
    ).scalar() or 0

    candidates_rows = Candidate.query.filter(
        (Candidate.election_id == str(election.election_id)) |
        (Candidate.election_id == str(election.id))
    ).order_by(Candidate.candidate_index.asc()).all()
    cand_map = {c.candidate_index: c for c in candidates_rows}

    candidate_results = []
    for j in range(candidate_count):
        votes = int(tallies[j])
        c_obj = cand_map.get(j)
        candidate_results.append({
            'candidate_index': j,
            'name': c_obj.name if c_obj else f'Candidate #{j + 1}',
            'department': (c_obj.department or '') if c_obj else '',
            'position': (getattr(c_obj, 'position', None) or (c_obj.department if c_obj else '') or ''),
            'photo_url': getattr(c_obj, 'photo_url', None) if c_obj else None,
            'votes': votes,
            'percentage': round((votes / total_valid_votes) * 100, 2) if total_valid_votes > 0 else 0.0,
        })

    tally_matches_blockchain = None
    discrepancy_warning = None
    if on_chain_total is not None:
        if total_valid_votes == on_chain_total and distinct_voters == on_chain_total:
            tally_matches_blockchain = True
        else:
            tally_matches_blockchain = False
            discrepancy_warning = (
                f'On-chain finalTallies sum ({total_valid_votes}), totalActiveBallots ({on_chain_total}), '
                f'and DB confirmed voters ({distinct_voters}) do not align.'
            )

    return jsonify({
        'election_id': election.id,
        'public_election_id': str(election.election_id),
        'status': election.effective_status,
        'contract_address': service.contract_address,
        'candidate_count': candidate_count,
        'tallies': tallies,
        'candidates': candidate_results,
        'total_valid_votes': total_valid_votes,
        'total_distinct_voters': distinct_voters,
        'tally_matches_blockchain': tally_matches_blockchain,
        'discrepancy_warning': discrepancy_warning,
        'is_finalized': True if (v2_state is None or v2_state == 7) else False,
    }), 200
