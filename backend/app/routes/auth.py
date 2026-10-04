"""
Auth Routes - Phase 2
"""

from flask import Blueprint, request, jsonify, session
from app.services.auth_service import AuthService
from app.extensions import db

auth_bp = Blueprint('auth', __name__)
auth_service = AuthService()


@auth_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    voter_id = data.get('voter_id')
    if not username or not email or not password:
        return jsonify({'error': 'Missing required fields'}), 400
    try:
        user = auth_service.register_user(username, email, password, voter_id)
        return jsonify({'message': 'User registered', 'username': user.username}), 201
    except Exception as e:
        return jsonify({'error': 'Registration failed'}), 400


@auth_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    ip = request.remote_addr
    ua = request.headers.get('User-Agent', '')
    if not username or not password:
        return jsonify({'error': 'Invalid credentials'}), 401
    ok, sess, msg = auth_service.authenticate(username, password, ip, ua)
    if not ok:
        return jsonify({'error': msg or 'Invalid credentials'}), 401
    return jsonify({'message': 'Authentication started', 'state': 'PENDING_FACTORS'}), 200


@auth_bp.route('/auth/request-otp', methods=['POST'])
def request_otp():
    sid = session.get('session_id')
    if not sid:
        return jsonify({'error': 'No active session'}), 401
    ok, msg = auth_service.request_otp(sid, 'login')
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg}), 200


@auth_bp.route('/auth/verify-otp', methods=['POST'])
def verify_otp():
    sid = session.get('session_id')
    data = request.get_json(silent=True) or {}
    otp = data.get('otp')
    if not sid or not otp:
        return jsonify({'error': 'Invalid request'}), 400
    ok, msg = auth_service.verify_otp(sid, otp, 'login')
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg, 'state': 'AUTHORIZED'}), 200


@auth_bp.route('/auth/logout', methods=['POST'])
def logout():
    sid = session.get('session_id')
    auth_service.logout(sid)
    return jsonify({'message': 'Logged out'}), 200


@auth_bp.route('/auth/status', methods=['GET'])
def status():
    sid = session.get('session_id')
    if not sid:
        return jsonify({'authenticated': False}), 200
    s = auth_service.get_session(sid)
    if not s or s.revoked:
        return jsonify({'authenticated': False}), 200
    return jsonify({'authenticated': s.auth_state == 'AUTHORIZED', 'state': s.auth_state}), 200
