"""
Face Routes - Phase 5 / Phase 16
Vote Without Doubt - Backend

All endpoints require a live, unrevoked, unexpired ``AUTHORIZED`` session. The
caller supplies only: the challenge id, the captured JPEG frames, and (for
enrolment) the fact that the person consents. Everything that matters -- the
frame-count policy, the acceptance threshold and the stored template -- is
server-authoritative.

IMPORTANT (Phase 16): liveness detection (LEFT/RIGHT head-movement challenges,
pose thresholds and neutral-band calibration) has been removed from this
prototype. Face verification now uses biometric embedding similarity only. This
does *not* mitigate presentation attacks (photos, screens, masks, deepfakes).

Uploads are real ``multipart/form-data``. The old implementation read a JSON
list, replaced it with a single synthetic ``b'frame'`` placeholder and stored a
literal ``b'embedding_stub'``; both are gone.
"""

from datetime import datetime
import logging

from flask import Blueprint, current_app, jsonify, request, session

from app.extensions import db
from app.models import Election, User, VotingAuthorization
from app.security.rate_limit import is_rate_limited
from app.services.auth_service import AuthService
from app.services.face_service import (
    FaceEngineNotReadyError,
    FaceService,
    FaceServiceError,
    ThresholdNotConfiguredError,
)

bp = Blueprint('face', __name__)
auth_service = AuthService()
face_service = FaceService()

logger = logging.getLogger(__name__)

# One generic message for every biometric rejection, so a caller cannot use
# response differences to learn why a check failed.
GENERIC_REJECTION = 'Face verification failed.'


def _authenticate():
    """Return ``(user, session_id)`` for a live authorised session, else ``None``."""
    sid = session.get('session_id')
    if not sid:
        return None
    record = auth_service.get_session(sid)
    if not record or record.auth_state != 'AUTHORIZED':
        return None
    user = db.session.get(User, record.user_id)
    if not user:
        return None
    return user, sid


def _limit(scope: str) -> bool:
    """True when this client has exhausted the configured budget for ``scope``."""
    limit, window = current_app.config[scope]
    return bool(is_rate_limited(scope.lower(), limit, window))


def _read_frames():
    """Extract the uploaded JPEG frames as a list of bytes.

    Returns ``(payloads, error)``. ``payloads`` is empty when ``error`` is set.
    Frames are read into memory and never written to disk.
    """
    if not request.content_length:
        return [], 'No request body was received.'
    if request.content_length > int(current_app.config['FACE_MAX_UPLOAD_BYTES']):
        return [], 'The submission exceeds the total size limit.'

    uploads = request.files.getlist('frames')
    if not uploads:
        return [], 'No frames were uploaded.'

    payloads = []
    max_frame = int(current_app.config['FACE_MAX_FRAME_BYTES'])
    for storage in uploads:
        payload = storage.read()
        if not payload:
            return [], 'An uploaded frame was empty.'
        if len(payload) > max_frame:
            return [], 'A frame exceeds the permitted size.'
        payloads.append(payload)
    return payloads, None


def _fail(error: Exception):
    """Map a service failure onto a response with no internal detail."""
    if isinstance(error, (FaceEngineNotReadyError, ThresholdNotConfiguredError)):
        logger.error('Face subsystem unavailable: %s', type(error).__name__)
        return jsonify({'error': 'Face service is temporarily unavailable.'}), 503
    if isinstance(error, FaceServiceError):
        return jsonify({'error': GENERIC_REJECTION}), error.http_status
    logger.error('Unexpected face error: %r', error)
    return jsonify({'error': 'Internal error.'}), 500


@bp.route('/face/challenge', methods=['POST'])
def face_challenge():
    """Issue a single-use challenge used to bind a face submission."""
    caller = _authenticate()
    if not caller:
        return jsonify({'error': 'Unauthorized'}), 401
    if _limit('FACE_RATE_LIMIT_CHALLENGE'):
        return jsonify({'error': 'Too many requests.'}), 429

    user, sid = caller

    # Server-authoritative authorization binding:
    # Resolve any active unconsumed VotingAuthorization for this authenticated session / voter.
    now = datetime.utcnow()
    data = request.get_json(silent=True) or {}
    client_aid = data.get('authorization_id') or request.args.get('authorization_id')
    client_eid = data.get('election_id') or request.args.get('election_id')

    pending_va = None
    if client_aid:
        try:
            pending_va = VotingAuthorization.query.filter_by(
                id=int(client_aid),
                user_id=user.id,
                consumed=False,
            ).filter(VotingAuthorization.expires_at > now).first()
        except (ValueError, TypeError):
            pass

    if not pending_va:
        query = VotingAuthorization.query.filter(
            VotingAuthorization.user_id == user.id,
            VotingAuthorization.consumed == False,
            VotingAuthorization.expires_at > now,
        )
        skip_va_lookup = False
        if client_eid:
            try:
                query = query.filter(VotingAuthorization.election_id == int(client_eid))
            except (ValueError, TypeError):
                e_obj = Election.query.filter_by(election_id=str(client_eid)).first()
                if e_obj:
                    query = query.filter(VotingAuthorization.election_id == e_obj.id)
                else:
                    # Unknown non-numeric election_id must not bind to an unrelated election's VA.
                    skip_va_lookup = True
        if not skip_va_lookup:
            if sid:
                query = query.filter(VotingAuthorization.session_id == sid)
            pending_va = query.order_by(VotingAuthorization.id.desc()).first()

    auth_id = pending_va.id if pending_va else (int(client_aid) if client_aid and str(client_aid).isdigit() else None)
    election_id = pending_va.election_id if pending_va else None

    try:
        payload = face_service.issue_challenge(
            user.id,
            sid,
            challenge_type='FACE',
            authorization_id=auth_id,
            election_id=election_id,
        )
    except FaceServiceError as error:
        return _fail(error)

    # Phase 16 simplified the response: challenges no longer instruct a
    # LEFT/RIGHT sequence, but existing clients still expect a deterministic
    # 'sequence' key. We keep it empty to preserve backward compatibility.
    payload['sequence'] = []
    if auth_id is not None:
        payload['authorization_id'] = auth_id
    if election_id is not None:
        payload['election_id'] = election_id
    return jsonify(payload), 200


@bp.route('/face/enroll', methods=['POST'])
def face_enroll():
    """Enrol a face template from a single captured frame."""
    caller = _authenticate()
    if not caller:
        return jsonify({'error': 'Unauthorized'}), 401
    if _limit('FACE_RATE_LIMIT_ENROLL'):
        return jsonify({'error': 'Too many requests.'}), 429

    user, sid = caller
    payloads, error = _read_frames()
    if error:
        return jsonify({'error': error}), 400

    challenge_id = request.form.get('challenge_id', '')
    consent = str(request.form.get('consent', '')).strip().lower() in ('1', 'true', 'yes')
    purpose = request.form.get('purpose') or None

    try:
        result = face_service.enroll(
            user_id=user.id, session_id=sid, challenge_id=challenge_id,
            payloads=payloads, consent_given=consent, consent_purpose=purpose,
        )
    except FaceServiceError as failure:
        db.session.rollback()
        return _fail(failure)
    return jsonify(result), 200


@bp.route('/face/verify', methods=['POST'])
def face_verify():
    """Verify a face against the enrolled template."""
    caller = _authenticate()
    if not caller:
        return jsonify({'error': 'Unauthorized'}), 401
    if _limit('FACE_RATE_LIMIT_VERIFY'):
        return jsonify({'error': 'Too many requests.'}), 429

    user, sid = caller
    payloads, error = _read_frames()
    if error:
        return jsonify({'error': error}), 400

    challenge_id = request.form.get('challenge_id', '')

    try:
        result = face_service.verify(
            user_id=user.id, session_id=sid, challenge_id=challenge_id,
            payloads=payloads,
        )
    except FaceServiceError as failure:
        db.session.rollback()
        return _fail(failure)
    return jsonify(result), 200


@bp.route('/face/status', methods=['GET'])
def face_status():
    """Report the caller's own enrolment and consent state."""
    caller = _authenticate()
    if not caller:
        return jsonify({'error': 'Unauthorized'}), 401
    user, _sid = caller
    return jsonify(face_service.get_status(user.id)), 200


@bp.route('/face/withdraw-consent', methods=['POST'])
def face_withdraw_consent():
    """Withdraw consent and irreversibly delete the stored template."""
    caller = _authenticate()
    if not caller:
        return jsonify({'error': 'Unauthorized'}), 401
    if _limit('FACE_RATE_LIMIT_ENROLL'):
        return jsonify({'error': 'Too many requests.'}), 429

    user, _sid = caller
    try:
        result = face_service.withdraw_consent(user.id)
    except FaceServiceError as failure:
        db.session.rollback()
        return _fail(failure)
    return jsonify(result), 200
