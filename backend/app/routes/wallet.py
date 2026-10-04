"""
Wallet Routes - Phase 4
"""

from flask import Blueprint, request, jsonify, session
from app.services.wallet_service import WalletService
from app.models import AuthSession, User

wallet_bp = Blueprint('wallet', __name__)
ws = WalletService()


def get_user_from_session():
    sid = session.get('session_id')
    if not sid:
        return None
    s = AuthSession.query.filter_by(session_id=sid, revoked=False).first()
    if not s or s.auth_state != 'AUTHORIZED':
        return None
    u = User.query.get(s.user_id)
    return u


@wallet_bp.route('/wallet/challenge', methods=['POST'])
def challenge():
    user = get_user_from_session()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    ok, ch, msg = ws.request_challenge(user.id)
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'nonce': ch.nonce, 'message': ch.message, 'expires_at': ch.expires_at.isoformat() + 'Z'}), 200


@wallet_bp.route('/wallet/bind', methods=['POST'])
def bind():
    user = get_user_from_session()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    nonce = data.get('nonce')
    signature = data.get('signature')
    wallet_address = data.get('wallet_address')
    if not nonce or not signature or not wallet_address:
        return jsonify({'error': 'Missing fields'}), 400
    ok, msg = ws.verify_and_bind(user.id, nonce, signature, wallet_address)
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg}), 200


@wallet_bp.route('/wallet/status', methods=['GET'])
def status():
    user = get_user_from_session()
    if not user:
        return jsonify({'bound': False}), 200
    from app.models import WalletBinding
    b = WalletBinding.query.filter_by(user_id=user.id).first()
    if b:
        return jsonify({'bound': True, 'wallet_address': b.wallet_address}), 200
    return jsonify({'bound': False}), 200
