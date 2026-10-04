"""
Registration Routes - Phase 3
"""

from flask import Blueprint, request, jsonify, session
from app.services.registration_service import RegistrationService
from app.utils.csv_import import validate_and_parse_roll, RollImportError
from app.extensions import db

reg_bp = Blueprint('registration', __name__)
reg_service = RegistrationService()


@reg_bp.route('/registration/check', methods=['POST'])
def check_eligibility():
    data = request.get_json(silent=True) or {}
    usn = data.get('usn')
    if not usn:
        return jsonify({'error': 'USN required'}), 400
    ok, rs, msg = reg_service.start_registration(usn)
    if not ok:
        return jsonify({'eligible': False, 'message': msg}), 400
    return jsonify({'eligible': True, 'message': msg}), 200


@reg_bp.route('/registration/request-otp', methods=['POST'])
def request_reg_otp():
    sid = session.get('reg_session')
    if not sid:
        return jsonify({'error': 'No registration session'}), 401
    ok, msg = reg_service.request_registration_otp(sid)
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg}), 200


@reg_bp.route('/registration/verify-otp', methods=['POST'])
def verify_reg_otp():
    sid = session.get('reg_session')
    data = request.get_json(silent=True) or {}
    otp = data.get('otp')
    if not sid or not otp:
        return jsonify({'error': 'Invalid request'}), 400
    ok, msg = reg_service.verify_registration_otp(sid, otp)
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg}), 200


@reg_bp.route('/registration/complete', methods=['POST'])
def complete_reg():
    sid = session.get('reg_session')
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    if not sid or not username or not password:
        return jsonify({'error': 'Invalid request'}), 400
    ok, user, msg = reg_service.complete_registration(sid, username, password)
    if not ok:
        return jsonify({'error': msg}), 400
    return jsonify({'message': msg}), 201


@reg_bp.route('/admin/roll/import', methods=['POST'])
def import_roll():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    f = request.files['file']
    try:
        content = f.read()
        rows, errors = validate_and_parse_roll(content)
        imported, imp_errors = reg_service.import_roll(rows)
        all_errs = errors + imp_errors
        return jsonify({
            'imported': imported,
            'errors': all_errs,
            'total_rows': len(rows)
        }), 200
    except RollImportError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        return jsonify({'error': 'Import failed'}), 400
