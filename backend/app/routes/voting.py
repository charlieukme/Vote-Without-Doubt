"""
Voting Routes - Phase 7 (remediated)
Vote Without Doubt - Backend

Endpoints:
- POST /api/voting/authorize: Create election-specific authorization session.
- POST /api/voting/mark-factors: Server-side factor aggregation (never client-asserted).
- GET  /api/voting/election/<election_id>: Get active election & candidate options.
- POST /api/voting/submit: Validate authorization, candidate, sequence=1, queue & trigger relayer.
- GET  /api/voting/status: Query authoritative ballot status (no SQL model crash).
"""

from datetime import datetime
from flask import Blueprint, current_app, jsonify, request, session

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models import BallotRecord, Candidate, Election, User
from app.models.auth_session import AuthSession
from app.security.pseudonym import derive_pseudonym
from app.security.rate_limit import is_rate_limited
from app.security.sessions import is_expired, is_idle_expired
from app.services.voting_service import VotingService

bp = Blueprint('voting', __name__)


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


def _limit(key_suffix: str, max_requests: int, window_sec: int) -> bool:
    """Helper to enforce rate limiting."""
    return is_rate_limited(key_suffix, max_requests, window_sec)


def _has_valid_candidates(e):
    if not e:
        return False
    c_count = Candidate.query.filter(
        (Candidate.election_id == str(e.election_id)) | (Candidate.election_id == str(e.id))
    ).count()
    return c_count >= 2 or (getattr(e, 'candidate_count', 0) or 0) >= 2


def _resolve_default_election():
    """Find the currently open/active election with configured candidates, or latest scheduled, or newest."""
    for e in Election.query.order_by(Election.id.desc()).all():
        if e.effective_status in ('OPEN', 'ACTIVE') and _has_valid_candidates(e):
            return e
    for e in Election.query.order_by(Election.id.desc()).all():
        if e.effective_status == 'SCHEDULED' and _has_valid_candidates(e):
            return e
    for e in Election.query.order_by(Election.id.desc()).all():
        if _has_valid_candidates(e):
            return e
    return Election.query.order_by(Election.id.desc()).first()


def _resolve_election(raw_eid):
    """Resolve Election by string election_id (e.g. ELEC_...) or integer primary key."""
    if raw_eid is None or str(raw_eid).strip().lower() in ('', 'default', 'active', 'current'):
        return _resolve_default_election()
    eid_str = str(raw_eid).strip()
    return Election.query.filter(
        (Election.election_id == eid_str) | (Election.id == int(eid_str) if eid_str.isdigit() else False)
    ).first()


@bp.route('/voting/authorize', methods=['POST'])
def authorize():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401

    if _limit('RATE_LIMIT_AUTHORIZE', 30, 60):
        return jsonify({'error': 'Too many requests', 'message': 'Rate limit exceeded. Please retry later.'}), 429

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_eid = data.get('election_id')
    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404
    now = datetime.utcnow()
    if election.end_time and now > election.end_time:
        return jsonify({'error': 'ELECTION_CLOSED'}), 400
    if election.effective_status not in ('ACTIVE', 'OPEN'):
        return jsonify({'error': 'ELECTION_NOT_ACTIVE'}), 400

    va = VotingService.create_authorization(
        user_id=s.user_id,
        election_id=election.id,
        session_id=session.get('session_id'),
    )
    # Check current verified factor records so existing verified state is preserved
    va = VotingService.mark_factors(
        user_id=s.user_id,
        election_id=election.id,
        session_id=session.get('session_id'),
    ) or va

    pending = []
    if not va.wallet_verified:
        pending.append('wallet')
    if not va.face_verified:
        pending.append('face')

    AuditLogger().log('VOTING_AUTHORIZED', {'election_id': str(election.election_id)})

    return jsonify({
        'authorization_id': va.id,
        'election_id': election.election_id,
        'authorized': va.authorized,
        'wallet_verified': va.wallet_verified,
        'face_verified': va.face_verified,
        'wallet_ok': va.wallet_verified,
        'face_ok': va.face_verified,
        'factors_required': ['wallet', 'face'],
        'factors_pending': pending,
        'missing_factors': pending,
        'expires_at': va.expires_at.isoformat() + 'Z',
    }), 200


@bp.route('/voting/factors-status', methods=['GET'])
@bp.route('/voting/authorization-status', methods=['GET'])
def get_factors_status():
    """Authoritative server-side factor verification state for active voter and election."""
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401

    raw_eid = request.args.get('election_id')
    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    va = VotingService.mark_factors(
        user_id=s.user_id,
        election_id=election.id,
        session_id=session.get('session_id'),
    )
    if not va:
        va = VotingService.get_authorization(
            user_id=s.user_id,
            election_id=election.id,
            session_id=session.get('session_id'),
        )

    wallet_ok = bool(va and va.wallet_verified)
    face_ok = bool(va and va.face_verified)
    authorized = bool(va and va.authorized)

    missing = []
    if not wallet_ok:
        missing.append('wallet')
    if not face_ok:
        missing.append('face')

    return jsonify({
        'authorized': authorized,
        'status': 'AUTHORIZED' if authorized else 'PENDING_FACTORS',
        'wallet_ok': wallet_ok,
        'face_ok': face_ok,
        'wallet_verified': wallet_ok,
        'face_verified': face_ok,
        'authorization_id': va.id if va else None,
        'election_id': election.election_id,
        'missing_factors': missing,
    }), 200


@bp.route('/voting/mark-factors', methods=['POST'])
def mark_factors():
    """
    CRITICAL FIX #1:
    Server inspects genuine factor records (wallet binding from Phase 4,
    face challenge from Phase 5). A client request CANNOT assert wallet_ok=true.
    """
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    raw_eid = data.get('election_id')
    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    va = VotingService.mark_factors(
        user_id=s.user_id,
        election_id=election.id,
        session_id=session.get('session_id'),
    )
    if not va:
        return jsonify({'error': 'INVALID_OR_EXPIRED_AUTH'}), 400

    if va.authorized:
        AuditLogger().log('VOTING_FACTORS_VERIFIED', {'election_id': str(election.election_id)})

    missing = []
    if not va.wallet_verified:
        missing.append('wallet')
    if not va.face_verified:
        missing.append('face')

    return jsonify({
        'authorized': va.authorized,
        'status': 'AUTHORIZED' if va.authorized else 'PENDING_FACTORS',
        'wallet_ok': va.wallet_verified,
        'face_ok': va.face_verified,
        'wallet_verified': va.wallet_verified,
        'face_verified': va.face_verified,
        'authorization_id': va.id,
        'election_id': election.election_id,
        'missing_factors': missing,
    }), 200


@bp.route('/voting/submit', methods=['POST'])
def submit():
    """Legacy V1 ballot submission endpoint - Permanently Disabled (SEC-001).

    Insecure V1 plaintext ballot submission has been permanently disabled in
    accordance with security remediation SEC-001. All voting must use the V2
    zero-knowledge threshold ElGamal protocol via /api/v2/voting/cast-ballot.
    """
    AuditLogger().log('V1_BALLOT_SUBMISSION_REJECTED', {
        'endpoint': '/api/voting/submit',
        'reason': 'V1_PROTOCOL_DEPRECATED_SEC_001',
    })
    return jsonify({
        'error': 'V1_PROTOCOL_DEPRECATED',
        'message': 'Legacy V1 plaintext ballot submission is permanently disabled for security and ballot privacy (SEC-001). Please use the V2 threshold ElGamal voting protocol (/api/v2/voting/cast-ballot).'
    }), 410


@bp.route('/voting/status', methods=['GET'])
def status():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401

    raw_eid = request.args.get('election_id')
    election = _resolve_election(raw_eid)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    eid_candidates = [raw_eid, election.id, str(election.election_id)]
    if str(election.election_id).isdigit():
        eid_candidates.append(int(election.election_id))
    eid_candidates = list(set(eid_candidates))

    from app.security.pseudonym import PseudonymKeyError
    pseud_candidates = []
    for eid_val in eid_candidates:
        try:
            p = derive_pseudonym(s.user_id, eid_val)
            if p not in pseud_candidates:
                pseud_candidates.append(p)
        except PseudonymKeyError:
            pass

    b = BallotRecord.query.filter(
        BallotRecord.election_id.in_(eid_candidates),
        BallotRecord.pseudonym.in_(pseud_candidates) if pseud_candidates else False,
    ).order_by(BallotRecord.sequence.desc(), BallotRecord.id.desc()).first()

    # If ballot is currently in SUBMITTED state, check if on-chain receipt just confirmed
    if b and b.state == 'SUBMITTED' and b.tx_hash:
        try:
            from app.services.recovery import RecoveryService
            RecoveryService.startup_recover()
            db.session.refresh(b)
        except Exception:
            pass

    if not b:
        # Check V2 encrypted ballot queue (isolated V2 architecture)
        from app.models.ballot_record_v2 import (
            BallotQueueV2,
            FAILED_V2_STATES,
            VALID_V2_FINAL_STATES,
            ensure_v2_receipt_code,
            get_latest_confirmed_v2_ballot,
            get_latest_v2_attempt,
        )
        v2_eids = [election.id]
        if str(election.election_id).isdigit():
            v2_eids.append(int(election.election_id))
        v2_pseudo = pseud_candidates[0] if pseud_candidates else derive_pseudonym(s.user_id, election.id)

        latest_attempt = None
        latest_confirmed = None
        for p_cand in (pseud_candidates or [v2_pseudo]):
            att = get_latest_v2_attempt(election.id, p_cand, eid_candidates=v2_eids)
            if att and (latest_attempt is None or (att.sequence, att.id) > (latest_attempt.sequence, latest_attempt.id)):
                latest_attempt = att
            conf = get_latest_confirmed_v2_ballot(election.id, p_cand, eid_candidates=v2_eids)
            if conf and (latest_confirmed is None or (conf.sequence, conf.id) > (latest_confirmed.sequence, latest_confirmed.id)):
                latest_confirmed = conf

        if latest_attempt:
            max_ballots = int(current_app.config.get('MAX_BALLOTS_PER_VOTER', election.max_ballots or 3))
            confirmed_seq = latest_confirmed.sequence if latest_confirmed else 0
            cooldown_sec = int(current_app.config.get('REVOTE_COOLDOWN_SECONDS', 120))
            ref_time = (latest_confirmed.tx_confirmed_at or latest_confirmed.created_at) if latest_confirmed else latest_attempt.created_at
            elapsed = (datetime.utcnow() - ref_time).total_seconds() if ref_time else cooldown_sec
            cooldown_active = bool(latest_confirmed and elapsed < cooldown_sec)
            cooldown_remaining = max(0, int(cooldown_sec - elapsed)) if cooldown_active else 0
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

            receipt_data = None
            if latest_confirmed:
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

            return jsonify({
                'has_ballot': True,
                'has_voted': bool(latest_confirmed),
                'status': latest_attempt.state,
                'state': latest_attempt.state,
                'sequence': latest_attempt.sequence,
                'active_sequence': confirmed_seq,
                'submissions_used': confirmed_seq,
                'next_sequence': confirmed_seq + 1,
                'max_ballots': max_ballots,
                'finalized': (latest_attempt.state in VALID_V2_FINAL_STATES),
                'receipt': receipt_data,
                'can_revote': can_revote,
                'retry_allowed': retry_allowed,
                'retry_blocked_reason': retry_blocked_reason,
                'cooldown_active': cooldown_active,
                'cooldown_remaining_sec': cooldown_remaining,
                'tx_hash': latest_attempt.tx_hash,
                'block_number': latest_attempt.block_number,
                'error': latest_attempt.error if latest_attempt.state in FAILED_V2_STATES else None,
                'pseudonym': latest_attempt.pseudonym,
            }), 200

        va = VotingService.get_authorization(
            user_id=s.user_id,
            election_id=election.id,
            session_id=session.get('session_id'),
        )
        return jsonify({
            'has_ballot': False,
            'status': 'NONE',
            'state': 'NONE',
            'finalized': False,
            'authorized': va.authorized if va else False,
            'factors': {
                'wallet': va.wallet_verified if va else False,
                'face': va.face_verified if va else False,
            },
        }), 200

    # Build receipt payload if finalized
    receipt_data = None
    if b.state == 'FINALIZED':
        if b.receipt_code:
            user = db.session.get(User, s.user_id)
            voter_id_last4 = user.voter_id[-4:] if (user and user.voter_id) else '0000'
            election = Election.query.filter(
                (Election.election_id == str(b.election_id)) | (Election.id == b.election_id)
            ).first()
            receipt_data = {
                'election_id': str(election.election_id if election else b.election_id),
                'election_title': election.title if election else f"Election {b.election_id}",
                'voter_id_last4': voter_id_last4,
                'receipt_code': b.receipt_code,
                'sequence': b.sequence,
                'timestamp': (b.tx_confirmed_at or b.created_at).strftime('%Y-%m-%dT%H:%M:00Z'),
            }
        else:
            receipt_data = VotingService.generate_receipt(b, s.user_id)
            if receipt_data:
                receipt_data['election_id'] = str(b.election_id)
                receipt_data['sequence'] = b.sequence

    cfg_max = int(current_app.config.get('MAX_BALLOTS_PER_VOTER', 3))
    el_max = int(getattr(election, 'max_ballots', None) or cfg_max) if election else cfg_max
    max_ballots = max(1, min(cfg_max, el_max))
    cooldown_sec = int(current_app.config.get('REVOTE_COOLDOWN_SECONDS', 120))
    ref_time = (b.tx_confirmed_at or b.created_at) if b else None
    elapsed = (datetime.utcnow() - ref_time).total_seconds() if ref_time else cooldown_sec
    cooldown_active = bool(cooldown_sec > 0 and elapsed < cooldown_sec)
    cooldown_remaining = max(0, int(cooldown_sec - elapsed)) if cooldown_active else 0
    can_revote = (b.sequence < max_ballots and b.state in ('FINALIZED', 'CONFIRMED') and not cooldown_active)

    # Authoritative verification of retry eligibility for FAILED ballots
    retry_allowed = False
    retry_blocked_reason = None

    if b.state == 'FAILED':
        if b.tx_hash or getattr(b, 'tx_broadcast_at', None):
            retry_allowed = False
            retry_blocked_reason = 'TRANSACTION_IN_FLIGHT_OR_UNCERTAIN'
        elif getattr(b, 'tx_confirmed_at', None):
            retry_allowed = False
            retry_blocked_reason = 'BALLOT_ALREADY_CONFIRMED'
        else:
            election_open = False
            if hasattr(election, 'effective_status'):
                election_open = election.effective_status in ('OPEN', 'ACTIVE')
            elif hasattr(election, 'status'):
                election_open = election.status in ('OPEN', 'ACTIVE')

            if not election_open:
                retry_allowed = False
                retry_blocked_reason = 'ELECTION_NOT_OPEN'
            else:
                on_chain_has_ballot = False
                try:
                    from app.services.reconciliation_service import ReconciliationService
                    relayer, w3, contract = ReconciliationService.get_relayer_and_contract()
                    if contract and w3 and w3.is_connected():
                        from app.services.election_admin_service import ElectionAdminService
                        on_chain_id = ElectionAdminService.get_on_chain_election_id(election)
                        pseudo_bytes = relayer._format_pseudonym(b.pseudonym)
                        ballot_data = contract.functions.getBallot(on_chain_id, pseudo_bytes).call()
                        if ballot_data and hasattr(ballot_data, '__getitem__') and len(ballot_data) >= 4:
                            on_chain_has_ballot = bool(ballot_data[3])
                except Exception as exc:
                    current_app.logger.warning("Error verifying on-chain ballot during status check: %s", exc)

                if on_chain_has_ballot:
                    retry_allowed = False
                    retry_blocked_reason = 'ON_CHAIN_BALLOT_EXISTS'
                else:
                    user = db.session.get(User, s.user_id)
                    from app.models.roll import ElectoralRoll
                    roll = ElectoralRoll.query.filter_by(usn=user.voter_id, is_eligible=True).first() if (user and user.voter_id) else None
                    if not roll:
                        retry_allowed = False
                        retry_blocked_reason = 'VOTER_INELIGIBLE'
                    else:
                        retry_allowed = True
                        retry_blocked_reason = None

    return jsonify({
        'has_ballot': True,
        'status': b.state,
        'state': b.state,
        'sequence': b.sequence,
        'ballot_count': b.sequence if b.state in ('FINALIZED', 'CONFIRMED') else 0,
        'vote_count': b.sequence if b.state in ('FINALIZED', 'CONFIRMED') else 0,
        'max_ballots': max_ballots,
        'can_revote': can_revote,
        'retry_allowed': retry_allowed,
        'retry_blocked_reason': retry_blocked_reason,
        'cooldown_active': cooldown_active,
        'cooldown_remaining_sec': cooldown_remaining,
        'is_null': getattr(b, 'is_null', False),
        'finalized': b.state == 'FINALIZED',
        'receipt': receipt_data,
        'opening': {
            'candidate_index': b.candidate if not getattr(b, 'is_null', False) else None,
            'commitment': b.commitment,
            'commitment_nonce': b.commitment_nonce,
        } if b.state in ('FINALIZED', 'QUEUED', 'SUBMITTED', 'CONFIRMED') else None,
        'error': b.error if b.state == 'FAILED' else None,
    }), 200


@bp.route('/voting/election/<election_id>', methods=['GET'])
def get_election(election_id):
    """Return election metadata and candidate list."""
    s = _get_auth_session()

    election = _resolve_election(election_id)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND'}), 404

    # Query real candidate records if configured
    cand_eids = {str(election.id), str(election.election_id)}
    if election_id:
        cand_eids.add(str(election_id).strip())
    db_candidates = Candidate.query.filter(
        Candidate.election_id.in_(list(cand_eids))
    ).order_by(Candidate.candidate_index.asc()).all()

    if db_candidates:
        candidates = [
            {
                'id': c.id,
                'index': c.candidate_index,
                'candidate_index': c.candidate_index,
                'name': c.name,
                'position': getattr(c, 'position', None) or c.department or 'Candidate',
                'department': c.department or '',
                'party': c.department or getattr(c, 'position', None) or '',
                'affiliation': c.department or getattr(c, 'position', None) or '',
                'year': getattr(c, 'year', None) or '',
                'slogan': getattr(c, 'slogan', None) or '',
                'manifesto': getattr(c, 'manifesto', None) or '',
                'photo_url': getattr(c, 'photo_url', None),
            }
            for c in db_candidates
        ]
        candidate_count = len(candidates)
    else:
        candidates = []
        candidate_count = 0

    now_utc = datetime.utcnow()
    return jsonify({
        'id': election.id,
        'election_id': election.election_id,
        'title': election.title,
        'description': election.description,
        'status': election.effective_status,
        'candidate_count': candidate_count,
        'candidates': candidates,
        'start_time': (election.start_time.isoformat() + 'Z') if election.start_time else None,
        'end_time': (election.end_time.isoformat() + 'Z') if election.end_time else None,
        'server_time': now_utc.isoformat() + 'Z',
    }), 200
