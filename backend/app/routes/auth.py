"""
Auth Routes - Phase 2 (Auth Core)
Vote Without Doubt - Backend

Endpoint contract:

* ``POST /api/auth/login``         password only; opens a ``PENDING_FACTORS``
                                   session. Never returns ``AUTHORIZED``.
* ``POST /api/auth/request-otp``   issues and emails a session-bound OTP.
* ``POST /api/auth/verify-otp``    verifies the OTP and, on success, rotates the
                                   session id and returns ``AUTHORIZED``.
* ``GET  /api/auth/status``        coarse authentication state, safe to call
                                   without a session.
* ``GET  /api/auth/session``       protected: requires a live ``AUTHORIZED``
                                   session.
* ``POST /api/auth/logout``        revokes the server-side session; idempotent.

There is deliberately no ``/auth/register`` here. Creating an account is Phase 3
work and must be gated on the electoral roll and verified email; Phase 2 only
consumes accounts that already exist. Exposing an open self-registration route
here would let a caller assert an arbitrary ``voter_id`` and bypass Phase 3.
"""

from flask import Blueprint, request, jsonify, session

from app.security.csrf import generate_csrf_token, rotate_csrf_token
from app.services.auth_service import AuthService

auth_bp = Blueprint('auth', __name__)
auth_service = AuthService()

#: Only these service messages may reach a client. Anything else is replaced by
#: a generic string so an unexpected internal message cannot leak internals.
SAFE_MESSAGES = {
    'Invalid credentials',
    'No active session',
    'Authentication required',
    'Authentication started',
    'OTP sent',
    'Unable to send OTP',
    'Invalid or expired OTP',
    'Invalid OTP purpose',
    'Authentication successful',
    'Logged out',
}

GENERIC = 'Request could not be completed'


def _safe(message: str) -> str:
    return message if message in SAFE_MESSAGES else GENERIC


@auth_bp.route('/auth/csrf-token', methods=['GET'])
def get_csrf_token():
    """Issue or retrieve session-bound CSRF token for frontend mutating requests."""
    token = generate_csrf_token()
    return jsonify({'csrf_token': token}), 200


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    """Verify a password and open a pending session. Requires an existing account."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Invalid credentials'}), 401

    ok, _sess, message = auth_service.authenticate(
        username, password, request.remote_addr, request.headers.get('User-Agent', ''),
    )
    if not ok:
        return jsonify({'error': _safe(message)}), 401

    return jsonify({
        'message': _safe(message),
        'state': 'PENDING_FACTORS',
        'csrf_token': generate_csrf_token(),
    }), 200


@auth_bp.route('/auth/request-otp', methods=['POST'])
def request_otp():
    """Issue and email a single-use OTP bound to the pending session."""
    sid = session.get('session_id')
    if not sid:
        return jsonify({'error': 'Authentication required'}), 401

    ok, message = auth_service.request_otp(sid, 'login')
    if not ok:
        return jsonify({'error': _safe(message)}), 400
    return jsonify({'message': _safe(message)}), 200


@auth_bp.route('/auth/verify-otp', methods=['POST'])
def verify_otp():
    """Verify the OTP, then rotate the session and mark it AUTHORIZED."""
    sid = session.get('session_id')
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    otp = data.get('otp')
    if not sid or not otp:
        return jsonify({'error': 'Invalid or expired OTP'}), 400

    ok, message = auth_service.verify_otp(sid, otp, 'login')
    if not ok:
        return jsonify({'error': _safe(message)}), 400

    # The session cookie changes here; rotate CSRF token for the authenticated session
    new_csrf_token = rotate_csrf_token()
    return jsonify({
        'message': _safe(message),
        'state': 'AUTHORIZED',
        'csrf_token': new_csrf_token,
    }), 200


@auth_bp.route('/auth/status', methods=['GET'])
def status():
    """Coarse authentication state. Never reveals identifiers."""
    token = generate_csrf_token()
    sid = session.get('session_id')
    if not sid:
        return jsonify({'authenticated': False, 'csrf_token': token}), 200

    auth_session = auth_service.get_session(sid)
    if not auth_session or auth_session.revoked:
        return jsonify({'authenticated': False, 'csrf_token': token}), 200

    return jsonify({
        'authenticated': auth_session.auth_state == 'AUTHORIZED',
        'state': auth_session.auth_state,
        'csrf_token': token,
    }), 200


@auth_bp.route('/auth/session', methods=['GET'])
def session_info():
    """Protected endpoint: requires a live AUTHORIZED server-side session."""
    sid = session.get('session_id')
    auth_session = auth_service.get_session(sid) if sid else None

    if not auth_session or auth_session.revoked or auth_session.auth_state != 'AUTHORIZED':
        return jsonify({'error': 'Not authenticated'}), 401

    # Deliberately excludes user id, username, email, IP and session id.
    return jsonify({
        'state': auth_session.auth_state,
        'authenticated_at': auth_session.authenticated_at.isoformat() + 'Z'
        if auth_session.authenticated_at else None,
        'expires_at': auth_session.expires_at.isoformat() + 'Z',
        'idle_expires_at': auth_session.idle_expires_at.isoformat() + 'Z',
        'csrf_token': generate_csrf_token(),
    }), 200


@auth_bp.route('/auth/logout', methods=['POST'])
def logout():
    """Revoke the server-side session and clear the client cookie. Idempotent."""
    auth_service.logout(session.get('session_id'))
    rotate_csrf_token()
    return jsonify({'message': 'Logged out'}), 200


@auth_bp.route('/auth/forgot-password/request', methods=['POST'])
@auth_bp.route('/auth/forgot-password', methods=['POST'])
def forgot_password_request():
    """
    Request password reset OTP for USN / username.
    Sends code to official college email associated with account.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    identifier = data.get('identifier') or data.get('username') or data.get('usn')
    if not identifier:
        return jsonify({'error': 'Identifier required'}), 400

    ok, reset_token, message = auth_service.request_password_reset(identifier)
    if not ok:
        return jsonify({'error': message}), 400

    return jsonify({
        'message': message,
        'reset_token': reset_token,
    }), 200


@auth_bp.route('/auth/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    """
    Verify reset OTP and set new password.
    Invalidates all existing sessions for the account.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    reset_token = data.get('reset_token')
    otp = data.get('otp')
    new_password = data.get('new_password') or data.get('password')

    if not reset_token or not otp or not new_password:
        return jsonify({'error': 'Missing required fields'}), 400

    ok, message = auth_service.reset_password(reset_token, otp, new_password)
    if not ok:
        return jsonify({'error': message}), 400

    return jsonify({'message': message}), 200
