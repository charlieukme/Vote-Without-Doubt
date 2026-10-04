"""
Face Routes - Phase 5
Minimal secure endpoints
"""

from flask import Blueprint, request, jsonify, session
from app.services.face_service import FaceService
from app.services.auth_service import AuthService

bp = Blueprint('face', __name__)
auth_service = AuthService()


def _get_auth_session():
    sid = session.get('session_id')
    if not sid:
        return None
    s = auth_service.get_session(sid)
    if not s or s.revoked or getattr(s, 'auth_state', '') != 'AUTHORIZED':
        return None
    return s


@bp.route('/face/status', methods=['GET'])
def face_status():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    status = FaceService.get_status(s.user_id)
    return jsonify({'user_id': s.user_id, **status}), 200


@bp.route('/face/consent', methods=['POST'])
def face_consent():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    res = FaceService.enroll_consent(s.user_id)
    return jsonify(res), 200 if res.get('success') else 400


@bp.route('/face/challenge/enroll', methods=['POST'])
def enroll_challenge():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    res = FaceService.create_challenge(s.user_id, 'ENROLL', ttl_seconds=20)
    return jsonify(res), 200


@bp.route('/face/challenge/verify', methods=['POST'])
def verify_challenge():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    res = FaceService.create_challenge(s.user_id, 'VERIFY', ttl_seconds=20)
    return jsonify(res), 200


@bp.route('/face/enroll', methods=['POST'])
def face_enroll():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    challenge_id = data.get('challenge_id')
    frames = data.get('frames', [])
    frame_bytes = [b'frame'] if frames else []
    ch_res = FaceService.submit_challenge(s.user_id, challenge_id or '', frame_bytes, sequence_provided=data.get('sequence'))
    if not ch_res.get('success'):
        return jsonify(ch_res), 400
    emb = b'embedding_stub'
    res = FaceService.enroll_complete(s.user_id, emb)
    return jsonify(res), 200 if res.get('success') else 400


@bp.route('/face/verify', methods=['POST'])
def face_verify():
    s = _get_auth_session()
    if not s:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json(silent=True) or {}
    challenge_id = data.get('challenge_id')
    frames = data.get('frames', [])
    frame_bytes = [b'frame'] if frames else []
    ch_res = FaceService.submit_challenge(s.user_id, challenge_id or '', frame_bytes, sequence_provided=data.get('sequence'))
    if not ch_res.get('success'):
        return jsonify(ch_res), 400
    res = FaceService.verify(s.user_id, b'embedding_stub')
    return jsonify(res), 200 if res.get('success') else 400

