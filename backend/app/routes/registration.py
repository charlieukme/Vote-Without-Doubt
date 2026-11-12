"""
Registration Routes - Phase 3 (remediated)
Vote Without Doubt - Backend

Public surface (voter-facing, unauthenticated by design):
    POST /api/registration/check          eligibility -> registration session
    POST /api/registration/request-otp    email the OTP to the roll address
    POST /api/registration/verify-otp     verify the OTP
    POST /api/registration/complete       create the account

Administrative surface (writes the authoritative roll):
    POST /api/admin/roll/import           requires the bootstrap admin token
    POST /api/admin/roll/dry-run          parse + fingerprint only, writes no rows
    GET  /api/admin/roll/verify           recompute and compare the roll digest

Every administrative route is behind :func:`admin_guard`, which fails closed when
no bootstrap credential is configured. This is deliberately NOT the Phase 11
RBAC subsystem; it is the minimum that makes the electoral roll non-anonymous.
"""

from flask import Blueprint, request, jsonify, session

from app.security.admin_bootstrap import admin_guard
from app.services.registration_service import (
    REGISTRATION_OTP_PURPOSE,
    RegistrationService,
    mask_email,
)
from app.utils.csv_import import validate_and_parse_roll, RollImportError

reg_bp = Blueprint('registration', __name__)
reg_service = RegistrationService()


# ---------------------------------------------------------------- public API

@reg_bp.route('/registration/check', methods=['POST'])
def check_eligibility():
    """Open a registration session for an eligible, unregistered voter."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    usn = data.get('usn')
    if not usn:
        return jsonify({'error': 'USN required'}), 400

    ok, _record, message = reg_service.start_registration(usn)
    if not ok:
        # One generic message for unknown, ineligible and already-registered.
        return jsonify({'eligible': False, 'message': message}), 400
    return jsonify({'eligible': True, 'message': message}), 200


@reg_bp.route('/registration/request-otp', methods=['POST'])
def request_reg_otp():
    """Dispatch a single-use OTP to the student's entered email."""
    sid = session.get('reg_session')
    if not sid:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    entered_email = data.get('email')
    if not entered_email or not isinstance(entered_email, str):
        return jsonify({'error': 'College email required'}), 400

    ok, message = reg_service.request_registration_otp(sid, entered_email)
    if not ok:
        return jsonify({'error': message}), 400
    return jsonify({
        'message': message,
        'email_masked': mask_email(entered_email),
    }), 200


@reg_bp.route('/registration/verify-otp', methods=['POST'])
def verify_reg_otp():
    """Verify the OTP and advance PENDING -> EMAIL_VERIFIED."""
    sid = session.get('reg_session')
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    code = data.get('otp')
    if not sid or not code:
        return jsonify({'error': 'Invalid request'}), 400

    # The purpose is fixed server-side; a client-supplied purpose is ignored.
    ok, message = reg_service.verify_registration_otp(sid, code, REGISTRATION_OTP_PURPOSE)
    if not ok:
        return jsonify({'error': message}), 400
    return jsonify({'message': message}), 200


@reg_bp.route('/registration/complete', methods=['POST'])
def complete_reg():
    """Create the account. Requires a live, unrevoked, email-verified session."""
    sid = session.get('reg_session')
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    username = data.get('username')
    password = data.get('password')
    if not sid or not username or not password:
        return jsonify({'error': 'Invalid request'}), 400

    ok, _user, message = reg_service.complete_registration(sid, username, password)
    if not ok:
        return jsonify({'error': message}), 400
    return jsonify({'message': message}), 201


@reg_bp.route('/registration/status', methods=['GET'])
def registration_status():
    """Authoritative server-side verification of all registration requirements."""
    from sqlalchemy import select
    from app.extensions import db
    from app.models import AuthSession, User, ElectoralRoll, FaceEnrollment, WalletBinding

    sid = session.get('session_id')
    user = None
    if sid:
        auth_sess = db.session.execute(
            select(AuthSession).where(AuthSession.session_id == sid, AuthSession.revoked.is_(False))
        ).scalars().first()
        if auth_sess and auth_sess.auth_state == 'AUTHORIZED':
            user = db.session.get(User, auth_sess.user_id)

    if not user:
        reg_sid = session.get('reg_session')
        if reg_sid:
            reg_sess = reg_service._live_session(reg_sid)
            if reg_sess:
                return jsonify({
                    'authenticated': False,
                    'usn': reg_sess.usn,
                    'email': mask_email(reg_sess.email) if reg_sess.email else None,
                    'email_verified': bool(reg_sess.email_verified),
                    'password_created': False,
                    'face_enrolled': False,
                    'wallet_bound': False,
                    'registration_complete': False,
                    'current_step': 'PASSWORD' if reg_sess.email_verified else ('OTP' if reg_sess.otp_hash else 'EMAIL'),
                }), 200
        return jsonify({
            'authenticated': False,
            'registration_complete': False,
            'current_step': 'USN',
        }), 200

    roll = db.session.execute(
        select(ElectoralRoll).where(ElectoralRoll.usn == user.voter_id, ElectoralRoll.is_eligible.is_(True))
    ).scalars().first()
    eligibility_ok = roll is not None

    face_record = db.session.execute(
        select(FaceEnrollment).where(FaceEnrollment.user_id == user.id)
    ).scalars().first()
    face_ok = face_record is not None and face_record.is_active()

    wallet_record = db.session.execute(
        select(WalletBinding).where(WalletBinding.user_id == user.id, WalletBinding.is_verified.is_(True))
    ).scalars().first()
    wallet_ok = wallet_record is not None

    complete = bool(eligibility_ok and user.email and user.password_hash and face_ok and wallet_ok)
    if complete and not user.is_verified:
        user.is_verified = True
        db.session.commit()

    return jsonify({
        'authenticated': True,
        'user_id': user.id,
        'username': user.username,
        'usn': user.voter_id,
        'email': user.email,
        'email_masked': mask_email(user.email),
        'eligibility_ok': eligibility_ok,
        'email_verified': True,
        'password_created': True,
        'face_enrolled': face_ok,
        'wallet_bound': wallet_ok,
        'wallet_address': wallet_record.wallet_address if wallet_record else None,
        'registration_complete': complete,
        'current_step': 'COMPLETE' if complete else ('WALLET' if face_ok else 'FACE'),
    }), 200


@reg_bp.route('/registration/finalize', methods=['POST'])
def finalize_registration():
    """Verify all 5 conditions and mark voter registration completed."""
    from sqlalchemy import select
    from app.extensions import db
    from app.models import AuthSession, User, ElectoralRoll, FaceEnrollment, WalletBinding

    sid = session.get('session_id')
    user = None
    if sid:
        auth_sess = db.session.execute(
            select(AuthSession).where(AuthSession.session_id == sid, AuthSession.revoked.is_(False))
        ).scalars().first()
        if auth_sess and auth_sess.auth_state == 'AUTHORIZED':
            user = db.session.get(User, auth_sess.user_id)

    if not user:
        return jsonify({'error': 'Active session required'}), 401

    roll = db.session.execute(
        select(ElectoralRoll).where(ElectoralRoll.usn == user.voter_id, ElectoralRoll.is_eligible.is_(True))
    ).scalars().first()
    if not roll:
        return jsonify({'error': 'USN not eligible on electoral roll'}), 400

    face_record = db.session.execute(
        select(FaceEnrollment).where(FaceEnrollment.user_id == user.id)
    ).scalars().first()
    face_ok = face_record is not None and face_record.is_active()

    wallet_record = db.session.execute(
        select(WalletBinding).where(WalletBinding.user_id == user.id, WalletBinding.is_verified.is_(True))
    ).scalars().first()
    wallet_ok = wallet_record is not None

    if not face_ok or not wallet_ok:
        missing = []
        if not face_ok:
            missing.append('Face Verification')
        if not wallet_ok:
            missing.append('MetaMask Wallet Binding')
        return jsonify({
            'registration_complete': False,
            'error': f'Registration incomplete: missing {", ".join(missing)}',
            'missing': missing
        }), 400

    user.is_verified = True
    db.session.commit()
    return jsonify({
        'registration_complete': True,
        'message': 'Registration complete! You are now eligible to vote.',
        'user_id': user.id,
        'username': user.username,
        'usn': user.voter_id,
        'wallet_address': wallet_record.wallet_address,
    }), 200


# --------------------------------------------------------- admin surface

@reg_bp.route('/admin/roll/dry-run', methods=['POST'])
@admin_guard()
def dry_run_roll():
    """Validate and fingerprint a roll without writing any voter row."""
    uploaded = request.files.get('file')
    if uploaded is None:
        return jsonify({'error': 'No file uploaded'}), 400
    try:
        rows, errors = validate_and_parse_roll(uploaded.read())
    except RollImportError as error:
        return jsonify({'error': str(error)}), 400

    batch = reg_service.dry_run_import(rows, uploaded.filename, errors)
    return jsonify({
        'batch_id': batch.batch_id,
        'status': batch.status,
        'roll_digest': batch.roll_digest,
        'valid_rows': batch.row_count,
        'errors': errors,
    }), 200


@reg_bp.route('/admin/roll/import', methods=['POST'])
@admin_guard()
def import_roll():
    """Import the electoral roll. Requires the bootstrap admin credential."""
    uploaded = request.files.get('file')
    if uploaded is None:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        rows, errors = validate_and_parse_roll(uploaded.read())
    except RollImportError as error:
        return jsonify({'error': str(error)}), 400

    batch = reg_service.dry_run_import(rows, uploaded.filename, errors)
    inserted, import_errors = reg_service.import_roll(
        rows, batch.batch_id, batch.roll_digest, errors)
    return jsonify({
        'batch_id': batch.batch_id,
        'status': 'APPLIED',
        'roll_digest': batch.roll_digest,
        'imported': inserted,
        'total_rows': len(rows),
        'errors': import_errors,
    }), 200


@reg_bp.route('/admin/roll/verify', methods=['GET'])
@admin_guard()
def verify_roll():
    """Recompute the roll digest and report whether the roll was modified.

    Returns only the verdict and the batch reference - never voter rows.
    """
    batch_id = request.args.get('batch_id')
    ok, message = reg_service.verify_roll_integrity(batch_id)
    if not ok:
        return jsonify({'verified': False, 'message': message}), 409
    return jsonify({'verified': True, 'message': message}), 200
