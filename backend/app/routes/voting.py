"""
Voting Routes - Phase 7
Core voting pipeline
"""

from flask import Blueprint, request, jsonify, session
from app.services.auth_service import AuthService
from app.services.face_service import FaceService
from app.services.voting_service import VotingService
from app.security.pseudonym import derive_pseudonym
from app.extensions import db
from app.models import Ballot, VotingAuthorization, BallotRecord

bp = Blueprint('voting', __name__)
auth_service = AuthService()


def _get_auth_session():
    sid = session.get('session_id')
    if not sid:
        return None
    s = auth_service.get_session(sid)
    if not s or s.revoked or getattr(s, 'auth_state', '') != 'AUTHORIZED':
        return None
    return s


@bp.route('/voting/authorize', methods=['POST'])
def authorize():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    election_id = data.get('election_id', 1)
    va = VotingService.create_authorization(s.user_id, int(election_id), sid=session.get('session_id'))
    return jsonify({'authorized': True, 'authorization_id': va.id}), 200


@bp.route('/voting/mark-factors', methods=['POST'])
def mark_factors():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    election_id = int(data.get('election_id', 1))
    va = VotingService.mark_factors(s.user_id, election_id, wallet_ok=True, face_ok=True)
    if not va:
        return jsonify({'error': 'INVALID_AUTH'}), 400
    return jsonify({'authorized': va.authorized, 'wallet_verified': va.wallet_verified, 'face_verified': va.face_verified}), 200


@bp.route('/voting/submit', methods=['POST'])
def submit():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    election_id = int(data.get('election_id', 1))
    candidate = int(data.get('candidate', 0))
    ballot, msg = VotingService.submit_ballot(s.user_id, election_id, candidate)
    if not ballot:
        return jsonify({'error': msg}), 400
    import secrets
    receipt = secrets.token_hex(16)
    ballot.receipt_code = receipt
    db.session.commit()
    return jsonify({'success': True, 'state': ballot.state, 'receipt': receipt}), 200


@bp.route('/voting/status', methods=['GET'])
def status():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    election_id = request.args.get('election_id', 1)
    pseud = derive_pseudonym(s.user_id, int(election_id))
    b = BallotRecord.query.filter_by(election_id=int(election_id), pseudonym=pseud).order_by(Ballot.id.desc()).first()
    if not b:
        va = VotingService.get_authorization(s.user_id, int(election_id))
        return jsonify({'has_ballot': False, 'authorized': va.authorized if va else False}), 200
    count = BallotRecord.query.filter_by(election_id=int(election_id), pseudonym=pseud).count()
    return jsonify({'has_ballot': True, 'state': b.state, 'receipt': b.receipt_code, 'vote_count': count}), 200


