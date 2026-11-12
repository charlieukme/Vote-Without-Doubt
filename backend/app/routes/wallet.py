"""
Wallet Routes - Phase 4 (remediated)
Vote Without Doubt - Backend

All endpoints require a live ``AUTHORIZED`` server-side session. The caller
supplies only: the challenge nonce, the signature it produced, the wallet address
it claims, and the chain id MetaMask is on. Everything else - user id, session id,
election, chain expectation, contract context, nonce, timestamps and purpose - is
server-authoritative.

No ballot, candidate or vote data is accepted, stored or signed here.
"""

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models import AuthSession, User, WalletBinding
from app.security.wallet import WalletVerificationUnavailable
from app.services.wallet_service import WalletService

wallet_bp = Blueprint('wallet', __name__)
ws = WalletService()


def get_user_from_session():
    """Return the authenticated user, or ``None``.

    Requires a live, unrevoked, AUTHORIZED session. Frontend state is never
    consulted.
    """
    sid = session.get('session_id')
    if not sid:
        return None
    record = AuthSession.query.filter_by(session_id=sid, revoked=False).first()
    if not record or record.auth_state != 'AUTHORIZED':
        return None
    return db.session.get(User, record.user_id)


def current_session_id():
    return session.get('session_id')


@wallet_bp.route('/wallet/challenge', methods=['POST'])
def challenge():
    """Issue an ownership-proof challenge bound to this user and session."""
    user = get_user_from_session()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    ok, record, message = ws.request_challenge(user.id, current_session_id())
    if not ok:
        return jsonify({'error': message}), 400

    return jsonify({
        'nonce': record.nonce,
        'message': record.message,
        'purpose': record.purpose,
        'chain_id': record.chain_id,
        'election_id': record.election_id,
        'contract': record.contract_address,
        'expires_at': record.expires_at.isoformat() + 'Z',
        'expected_chain_id': app_expected_chain(),
    }), 200


def app_expected_chain():
    from flask import current_app
    return int(current_app.config['WALLET_AUTH_CHAIN_ID'])


@wallet_bp.route('/wallet/bind', methods=['POST'])
def bind():
    """Verify the ownership proof and bind the wallet to the identity."""
    user = get_user_from_session()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    nonce = data.get('nonce')
    signature = data.get('signature')
    wallet_address = data.get('wallet_address')
    chain_id = data.get('chain_id')

    if not nonce or not signature or not wallet_address:
        return jsonify({'error': 'Missing fields'}), 400

    # A client-supplied message or user id is ignored entirely: the server
    # verifies against the stored, server-generated message.
    try:
        ok, message = ws.verify_and_bind(
            user.id,
            current_session_id(),
            nonce,
            signature,
            wallet_address,
            chain_id=chain_id,
        )
    except WalletVerificationUnavailable:
        # Operator-visible failure, never presented as a user error.
        return jsonify({
            'error': 'Wallet verification is temporarily unavailable',
            'code': 'WALLET_VERIFICATION_UNAVAILABLE',
        }), 503

    if not ok:
        return jsonify({'error': message}), 400
    return jsonify({'message': message}), 200


@wallet_bp.route('/wallet/status', methods=['GET'])
def status():
    """Report whether the caller has a verified wallet binding."""
    user = get_user_from_session()
    if not user:
        # Stay non-enumerating: an unauthenticated caller learns nothing.
        return jsonify({'bound': False}), 200

    binding = WalletBinding.query.filter_by(user_id=user.id).first()
    if binding:
        return jsonify({
            'bound': True,
            'wallet_address': binding.wallet_address,
            'verified': binding.is_verified,
        }), 200
    return jsonify({'bound': False}), 200
