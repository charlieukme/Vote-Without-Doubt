"""
Administrative & Governance API Routes - Phase 11
Vote Without Doubt - Backend

Endpoints:
  Authentication:
    POST /api/admin/auth/login
    POST /api/admin/auth/logout
    GET  /api/admin/auth/me

  Election Lifecycle & Management:
    GET  /api/admin/elections
    POST /api/admin/elections
    GET  /api/admin/elections/<id>
    PUT  /api/admin/elections/<id>
    POST /api/admin/elections/<id>/candidates
    POST /api/admin/elections/<id>/request-approval
    POST /api/admin/elections/<id>/open
    POST /api/admin/elections/<id>/close

  Two-Officer Approvals:
    GET  /api/admin/approvals
    POST /api/admin/approvals/<id>/approve
    POST /api/admin/approvals/<id>/reject

  Audit & Dispute Handling:
    GET  /api/admin/audit-logs
    GET  /api/admin/audit-logs/verify-chain
    POST /api/admin/disputes/query
"""

from datetime import datetime
import json
from flask import Blueprint, current_app, g, jsonify, request, Response, send_file

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models.admin import AdminSession, AdminUser, ApprovalRequest, Candidate
from app.models.audit_event import AuditEvent
from app.models.ballot import Election
from app.security.admin_auth import AdminAuthService, require_admin_auth
from app.services.dispute_service import DisputeService
from app.services.export_service import ExportService
from app.services.results_service import ResultsService
from app.services.election_admin_service import (
    ElectionAdminError,
    ElectionAdminService,
    ElectionImmutabilityError,
    InvalidLifecycleTransitionError,
    TwoOfficerApprovalError,
)

admin_bp = Blueprint('admin', __name__)


# ------------------------------------------------------------------
# Admin Authentication
# ------------------------------------------------------------------

@admin_bp.route('/auth/login', methods=['POST'])
def admin_login():
    """Admin Login: Admin ID + Password + TOTP."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    admin_id = data.get('admin_id')
    password = data.get('password')
    totp_code = data.get('totp_code')

    if not admin_id or not password:
        return jsonify({'error': 'MISSING_FIELDS', 'message': 'admin_id and password required'}), 400

    ip = request.remote_addr
    ua = request.headers.get('User-Agent', '')

    success, token, session_obj, err_code = AdminAuthService.authenticate(
        admin_id=admin_id,
        password=password,
        totp_code=totp_code,
        ip_address=ip,
        user_agent=ua,
    )

    if not success:
        status_code = 403 if err_code in ('ACCOUNT_LOCKED', 'TOTP_REPLAY_REJECTED') else 401
        return jsonify({'error': err_code, 'message': 'Authentication failed'}), status_code

    admin = session_obj.admin
    return jsonify({
        'token': token,
        'expires_at': session_obj.expires_at.isoformat(),
        'admin': {
            'admin_id': admin.admin_id,
            'name': admin.name,
            'email': admin.email,
            'role': admin.role,
        }
    }), 200


@admin_bp.route('/auth/logout', methods=['POST'])
@require_admin_auth()
def admin_logout():
    """Revoke admin session."""
    token = g.admin_session.session_token
    AdminAuthService.logout(token)
    return jsonify({'message': 'Logged out successfully'}), 200


@admin_bp.route('/auth/me', methods=['GET'])
@require_admin_auth()
def admin_me():
    """Get current admin details."""
    admin = g.admin_user
    admin_dict = {
        'admin_id': admin.admin_id,
        'name': admin.name,
        'email': admin.email,
        'role': admin.role,
    }
    return jsonify({
        **admin_dict,
        'admin': admin_dict,
    }), 200


# ------------------------------------------------------------------
# Election Management & Lifecycle
# ------------------------------------------------------------------

@admin_bp.route('/elections', methods=['GET'])
@require_admin_auth()
def list_elections():
    """List all elections (Accessible to Officers and Auditors)."""
    include_archived = request.args.get('include_archived', 'false').lower() == 'true'
    query = Election.query
    if not include_archived:
        query = query.filter(Election.is_archived == False)
    elections = query.order_by(Election.id.desc()).all()

    out = []
    now = datetime.utcnow()
    for e in elections:
        admin_status = 'CLOSED' if (e.status in ('OPEN', 'ACTIVE') and e.end_time and now >= e.end_time) else e.status
        is_expired = bool(e.end_time and now >= e.end_time)
        out.append({
            'election_id': e.election_id,
            'title': e.title,
            'status': admin_status,
            'effective_status': e.effective_status,
            'is_expired': is_expired,
            'start_time': (e.start_time.isoformat() + 'Z') if e.start_time else None,
            'end_time': (e.end_time.isoformat() + 'Z') if e.end_time else None,
            'candidate_count': e.candidate_count,
            'eligible_count': e.eligible_count,
            'max_ballots': e.max_ballots,
            'is_archived': bool(e.is_archived),
            'merkle_root': e.merkle_root,
        })
    return jsonify({'elections': out}), 200


@admin_bp.route('/elections/<election_id>', methods=['DELETE'])
@require_admin_auth(roles='OFFICER')
def delete_election(election_id):
    """Permanently delete a DRAFT election proposal with zero ballots (Officer only)."""
    try:
        ok, msg = ElectionAdminService.delete_election(election_id, g.admin_user)
        return jsonify({'message': msg, 'election_id': str(election_id)}), 200
    except (ElectionAdminError, TwoOfficerApprovalError) as err:
        return jsonify({'error': 'ADMIN_ERROR', 'message': str(err)}), 400


@admin_bp.route('/elections/<election_id>/archive', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def archive_election(election_id):
    """Archive a closed or finalized election (Officer only)."""
    try:
        ok, msg = ElectionAdminService.archive_election(election_id, g.admin_user)
        return jsonify({'message': msg, 'election_id': str(election_id)}), 200
    except (ElectionAdminError, TwoOfficerApprovalError) as err:
        return jsonify({'error': 'ADMIN_ERROR', 'message': str(err)}), 400


@admin_bp.route('/elections', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def create_election():
    """Create a new election in DRAFT state (Officer only)."""
    import secrets
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    election_id = data.get('election_id')
    if not election_id:
        election_id = f"ELEC_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(2).upper()}"
    title = data.get('title')
    description = data.get('description', '')
    start_str = data.get('start_time')
    end_str = data.get('end_time')
    try:
        eligible_count = int(data.get('eligible_count', 100))
        max_ballots = int(data.get('max_ballots', 3))
    except (ValueError, TypeError):
        return jsonify({'error': 'INVALID_NUMERIC', 'message': 'eligible_count and max_ballots must be integers'}), 400
    roll_hash = data.get('roll_hash')

    if not title or not start_str or not end_str:
        return jsonify({'error': 'MISSING_FIELDS', 'message': 'title, start_time, and end_time required'}), 400

    try:
        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        # Remove tzinfo for native db storage
        start_time = start_time.replace(tzinfo=None)
        end_time = end_time.replace(tzinfo=None)
    except Exception as exc:
        return jsonify({'error': 'INVALID_DATETIME', 'message': f'Invalid ISO format: {exc}'}), 400

    try:
        election = ElectionAdminService.create_election(
            election_id=str(election_id),
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            officer=g.admin_user,
            eligible_count=int(eligible_count),
            max_ballots=int(max_ballots),
            roll_hash=roll_hash,
        )
        elec_dict = {
            'id': election.election_id,
            'election_id': election.election_id,
            'title': election.title,
            'status': election.status,
            'effective_status': election.effective_status,
            'start_time': (election.start_time.isoformat() + 'Z') if election.start_time else None,
            'end_time': (election.end_time.isoformat() + 'Z') if election.end_time else None,
            'eligible_count': election.eligible_count,
            'roll_hash': election.roll_hash,
        }
        return jsonify({
            'message': 'Election created in DRAFT state',
            'election_id': election.election_id,
            'status': election.status,
            'effective_status': election.effective_status,
            'election': elec_dict,
        }), 201
    except ValueError as val_err:
        return jsonify({'error': 'VALIDATION_ERROR', 'message': str(val_err)}), 400
    except ElectionAdminError as admin_err:
        return jsonify({'error': 'ADMIN_ERROR', 'message': str(admin_err)}), 400


@admin_bp.route('/elections/<election_id>', methods=['GET'])
@require_admin_auth()
def get_election(election_id):
    """Get election details including candidates and lifecycle status."""
    election = Election.query.filter(
        (Election.election_id == str(election_id)) | (Election.id == int(election_id) if str(election_id).isdigit() else False)
    ).first()
    if not election:
        return jsonify({'error': 'NOT_FOUND', 'message': 'Election not found'}), 404

    candidates = Candidate.query.filter_by(
        election_id=election.election_id
    ).order_by(Candidate.candidate_index.asc()).all()

    cand_list = [
        {
            'index': c.candidate_index,
            'name': c.name,
            'department': c.department,
            'year': getattr(c, 'year', None),
            'slogan': getattr(c, 'slogan', None),
            'manifesto': getattr(c, 'manifesto', None),
            'photo_url': getattr(c, 'photo_url', None),
        }
        for c in candidates
    ]

    now = datetime.utcnow()
    admin_status = 'CLOSED' if (election.status in ('OPEN', 'ACTIVE') and election.end_time and now >= election.end_time) else election.status
    is_expired = bool(election.end_time and now >= election.end_time)
    res_dict = {
        'id': election.election_id,
        'election_id': election.election_id,
        'title': election.title,
        'description': election.description,
        'status': admin_status,
        'effective_status': election.effective_status,
        'is_expired': is_expired,
        'start_time': (election.start_time.isoformat() + 'Z') if election.start_time else None,
        'end_time': (election.end_time.isoformat() + 'Z') if election.end_time else None,
        'candidate_count': election.candidate_count,
        'eligible_count': election.eligible_count,
        'max_ballots': election.max_ballots,
        'roll_hash': election.roll_hash,
        'candidates_hash': election.candidates_hash,
        'candidates': cand_list,
        'scheduled_at': (election.scheduled_at.isoformat() + 'Z') if election.scheduled_at else None,
        'closed_at': (election.closed_at.isoformat() + 'Z') if election.closed_at else None,
        'finalized_at': election.finalized_at.isoformat() if election.finalized_at else None,
    }
    return jsonify({
        **res_dict,
        'election': res_dict,
    }), 200


@admin_bp.route('/elections/<election_id>', methods=['PUT'])
@require_admin_auth(roles='OFFICER')
def update_election(election_id):
    """
    Update draft election parameters.
    Fails closed with 409 IMMUTABLE_ELECTION if election is SCHEDULED or later.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    start_time = None
    end_time = None

    if 'start_time' in data:
        try:
            start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            return jsonify({'error': 'INVALID_DATETIME', 'message': 'Invalid start_time ISO format'}), 400
    if 'end_time' in data:
        try:
            end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            return jsonify({'error': 'INVALID_DATETIME', 'message': 'Invalid end_time ISO format'}), 400

    eligible_count = data.get('eligible_count')
    max_ballots = data.get('max_ballots')
    if eligible_count is not None:
        try:
            eligible_count = int(eligible_count)
        except (ValueError, TypeError):
            return jsonify({'error': 'INVALID_NUMERIC', 'message': 'eligible_count must be an integer'}), 400
    if max_ballots is not None:
        try:
            max_ballots = int(max_ballots)
        except (ValueError, TypeError):
            return jsonify({'error': 'INVALID_NUMERIC', 'message': 'max_ballots must be an integer'}), 400

    try:
        election = ElectionAdminService.update_draft_election(
            election_id=str(election_id),
            officer=g.admin_user,
            title=data.get('title'),
            description=data.get('description'),
            start_time=start_time,
            end_time=end_time,
            eligible_count=eligible_count,
            max_ballots=max_ballots,
            roll_hash=data.get('roll_hash'),
        )
        return jsonify({'message': 'Draft election updated', 'election_id': election.election_id}), 200
    except ElectionImmutabilityError as imm_err:
        return jsonify({'error': 'IMMUTABLE_ELECTION', 'message': str(imm_err)}), 409
    except InvalidLifecycleTransitionError as trans_err:
        return jsonify({'error': 'INVALID_STATE', 'message': str(trans_err)}), 400
    except Exception as exc:
        return jsonify({'error': 'UPDATE_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/elections/<election_id>/clear-schedule', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def clear_election_schedule(election_id):
    """Safely cancel / clear the scheduled start and end times of an election (Officer only)."""
    data = request.get_json(silent=True) or {}
    reason = data.get('reason') or 'Administrative cancellation of scheduled start'
    try:
        election = ElectionAdminService.clear_election_schedule(
            election_id=str(election_id),
            officer=g.admin_user,
            reason=reason,
        )
        return jsonify({
            'message': 'Election schedule cancelled successfully',
            'election_id': election.election_id,
            'status': election.status,
            'start_time': None,
            'end_time': None,
        }), 200
    except (ElectionAdminError, InvalidLifecycleTransitionError, ValueError) as err:
        return jsonify({'error': 'CLEAR_SCHEDULE_FAILED', 'message': str(err)}), 400
    except Exception as exc:
        return jsonify({'error': 'CLEAR_SCHEDULE_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/elections/<election_id>/candidates', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def add_candidate(election_id):
    """Add candidates to election while in DRAFT (Officer only)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    candidates_data = data.get('candidates')
    if candidates_data is None:
        if data.get('name'):
            candidates_data = [data]
        else:
            return jsonify({'error': 'MISSING_NAME', 'message': 'Candidate data required'}), 400

    added_list = []
    try:
        for c in candidates_data:
            cand = ElectionAdminService.add_candidate(
                election_id=str(election_id),
                name=c.get('name'),
                officer=g.admin_user,
                department=c.get('department') or c.get('party'),
                position=c.get('position'),
                year=c.get('year'),
                slogan=c.get('slogan') or c.get('introduction'),
                manifesto=c.get('manifesto') or c.get('agenda'),
                photo_url=c.get('photo_url') or c.get('photo_path'),
            )
            added_list.append({
                'index': cand.candidate_index,
                'name': cand.name,
                'position': cand.position,
                'department': cand.department,
                'year': cand.year,
                'slogan': cand.slogan,
                'manifesto': cand.manifesto,
                'photo_url': cand.photo_url,
            })
        return jsonify({
            'message': f'{len(added_list)} candidates added',
            'candidates': added_list,
        }), 200
    except ElectionImmutabilityError as imm_err:
        return jsonify({'error': 'IMMUTABLE_ELECTION', 'message': str(imm_err)}), 409
    except InvalidLifecycleTransitionError as trans_err:
        return jsonify({'error': 'INVALID_STATE', 'message': str(trans_err)}), 400
    except Exception as exc:
        return jsonify({'error': 'ADD_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/elections/<election_id>/candidates/<int:candidate_index>', methods=['DELETE'])
@require_admin_auth(roles='OFFICER')
def delete_candidate(election_id, candidate_index):
    """Remove candidate from election while in DRAFT (Officer only)."""
    try:
        ElectionAdminService.remove_candidate(
            election_id=str(election_id),
            candidate_index=int(candidate_index),
            officer=g.admin_user,
        )
        return jsonify({
            'success': True,
            'message': f'Candidate at index {candidate_index} removed successfully.',
            'candidate_index': candidate_index,
        }), 200
    except ElectionImmutabilityError as imm_err:
        return jsonify({'error': 'IMMUTABLE_ELECTION', 'message': str(imm_err)}), 409
    except Exception as exc:
        return jsonify({'error': 'REMOVE_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/candidates/upload-photo', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def upload_candidate_photo_standalone():
    """
    Upload candidate photo from device (Officer only).
    Validates file content, format (JPEG, PNG, WebP), size (<= 5MB),
    strips EXIF metadata, and generates a safe, unique filename.
    """
    import io
    import os
    import secrets
    from PIL import Image

    uploaded = request.files.get('photo') or request.files.get('file')
    if not uploaded:
        return jsonify({'error': 'MISSING_FILE', 'message': 'No image file provided'}), 400

    content = uploaded.read()
    if len(content) > 5 * 1024 * 1024:
        return jsonify({'error': 'FILE_TOO_LARGE', 'message': 'Photo size exceeds 5MB limit'}), 400
    if len(content) < 100:
        return jsonify({'error': 'INVALID_FILE', 'message': 'Photo file is empty or corrupted'}), 400

    try:
        image = Image.open(io.BytesIO(content))
        if image.format not in ('JPEG', 'PNG', 'WEBP'):
            return jsonify({'error': 'INVALID_FORMAT', 'message': 'Only JPEG, PNG, and WebP formats supported'}), 400

        ext = image.format.lower()
        if ext == 'jpeg':
            ext = 'jpg'
        safe_name = f"{secrets.token_hex(16)}.{ext}"
        upload_dir = os.path.join(current_app.root_path, 'uploads', 'candidates')
        os.makedirs(upload_dir, exist_ok=True)
        dest_path = os.path.join(upload_dir, safe_name)

        if image.format == 'JPEG' and image.mode != 'RGB':
            image = image.convert('RGB')

        clean_buf = io.BytesIO()
        image.save(clean_buf, format=image.format)
        with open(dest_path, 'wb') as f:
            f.write(clean_buf.getvalue())

        photo_url = f"/api/public/candidate-photo/{safe_name}"
        return jsonify({
            'message': 'Candidate photo uploaded successfully',
            'photo_url': photo_url,
            'filename': safe_name,
            'size': len(clean_buf.getvalue()),
        }), 200
    except Exception as exc:
        return jsonify({'error': 'IMAGE_PROCESSING_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/elections/<election_id>/candidates/<int:candidate_index>/photo', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def upload_candidate_photo(election_id, candidate_index):
    """Upload photo for candidate while in DRAFT (Officer only)."""
    import io
    import os
    import secrets
    from PIL import Image

    election = Election.query.filter_by(election_id=str(election_id)).first()
    if not election:
        return jsonify({'error': 'NOT_FOUND', 'message': 'Election not found'}), 404
    if election.status != 'DRAFT':
        return jsonify({'error': 'IMMUTABLE_ELECTION', 'message': 'Candidate photos cannot be modified once scheduled.'}), 409

    cand = Candidate.query.filter_by(election_id=str(election_id), candidate_index=candidate_index).first()
    if not cand:
        return jsonify({'error': 'NOT_FOUND', 'message': 'Candidate not found'}), 404

    uploaded = request.files.get('photo') or request.files.get('file')
    if not uploaded:
        return jsonify({'error': 'MISSING_FILE', 'message': 'No image file provided'}), 400

    content = uploaded.read()
    if len(content) > 5 * 1024 * 1024:
        return jsonify({'error': 'FILE_TOO_LARGE', 'message': 'Photo size exceeds 5MB limit'}), 400
    if len(content) < 100:
        return jsonify({'error': 'INVALID_FILE', 'message': 'Photo file is empty or corrupted'}), 400

    try:
        image = Image.open(io.BytesIO(content))
        if image.format not in ('JPEG', 'PNG', 'WEBP'):
            return jsonify({'error': 'INVALID_FORMAT', 'message': 'Only JPEG, PNG, and WebP formats supported'}), 400

        ext = image.format.lower()
        if ext == 'jpeg':
            ext = 'jpg'
        safe_name = f"{secrets.token_hex(16)}.{ext}"
        upload_dir = os.path.join(current_app.root_path, 'uploads', 'candidates')
        os.makedirs(upload_dir, exist_ok=True)
        dest_path = os.path.join(upload_dir, safe_name)

        if image.format == 'JPEG' and image.mode != 'RGB':
            image = image.convert('RGB')

        clean_buf = io.BytesIO()
        image.save(clean_buf, format=image.format)
        with open(dest_path, 'wb') as f:
            f.write(clean_buf.getvalue())

        photo_url = f"/api/public/candidate-photo/{safe_name}"
        cand.photo_url = photo_url
        db.session.commit()

        return jsonify({
            'message': 'Candidate photo uploaded successfully',
            'photo_url': photo_url,
            'candidate_index': candidate_index,
        }), 200
    except Exception as exc:
        return jsonify({'error': 'IMAGE_PROCESSING_FAILED', 'message': str(exc)}), 400



@admin_bp.route('/elections/<election_id>/request-approval', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def request_approval(election_id):
    """Request two-officer approval for a critical action (Officer only)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    action_type = data.get('action_type') or data.get('operation')
    reason = data.get('reason') or data.get('justification')
    if action_type != 'EMERGENCY_CLOSE' and not reason:
        reason = 'Requested by officer'

    if not action_type:
        return jsonify({'error': 'MISSING_ACTION', 'message': 'action_type required'}), 400

    if action_type == 'EMERGENCY_CLOSE' and (not reason or not reason.strip()):
        return jsonify({'error': 'MISSING_JUSTIFICATION', 'message': 'A mandatory justification reason is required for emergency election closure.'}), 400

    try:
        req = ElectionAdminService.request_approval(
            election_id=str(election_id),
            action_type=action_type,
            requester=g.admin_user,
            reason=reason,
        )
        return jsonify({
            'message': 'Two-officer approval requested',
            'request_id': req.id,
            'action_type': req.action_type,
            'status': req.status,
            'expires_at': req.expires_at.isoformat(),
            'approval_request': {
                'id': req.id,
                'action_type': req.action_type,
                'status': req.status,
            }
        }), 201
    except InvalidLifecycleTransitionError as trans_err:
        return jsonify({'error': 'INVALID_STATE', 'message': str(trans_err)}), 400
    except ValueError as val_err:
        return jsonify({'error': 'VALIDATION_ERROR', 'message': str(val_err)}), 400
    except Exception as exc:
        return jsonify({'error': 'REQUEST_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/elections/<election_id>/provision', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def provision_election(election_id):
    """Explicitly provision an approved election on-chain (Officer only)."""
    try:
        success, msg, details = ElectionAdminService.provision_election_on_chain(
            election_id=str(election_id),
            officer=g.admin_user,
        )
        return jsonify({
            'message': msg,
            'details': details,
            'election_id': str(election_id),
        }), 200
    except TwoOfficerApprovalError as appr_err:
        return jsonify({'error': 'FORBIDDEN', 'message': str(appr_err)}), 403
    except InvalidLifecycleTransitionError as trans_err:
        return jsonify({'error': 'INVALID_STATE', 'message': str(trans_err)}), 400
    except ElectionAdminError as admin_err:
        return jsonify({'error': 'PROVISIONING_FAILED', 'message': str(admin_err)}), 400
    except ValueError as val_err:
        return jsonify({'error': 'VALIDATION_ERROR', 'message': str(val_err)}), 400
    except Exception as exc:
        return jsonify({'error': 'PROVISIONING_FAILED', 'message': str(exc)}), 500


def _has_approved_schedule_request(election: Election) -> bool:
    """Return True if a distinct-officer APPROVED SCHEDULE_ELECTION ApprovalRequest exists."""
    req = ApprovalRequest.query.filter(
        ApprovalRequest.election_id.in_([str(election.election_id), str(election.id)]),
        ApprovalRequest.action_type == 'SCHEDULE_ELECTION',
        ApprovalRequest.status == 'APPROVED',
        ApprovalRequest.approver_id.isnot(None),
        ApprovalRequest.requester_id != ApprovalRequest.approver_id,
    ).first()
    return req is not None


@admin_bp.route('/elections/<election_id>/schedule', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def schedule_election(election_id):
    """Enforce two-officer Four-Eyes approval before scheduling an election."""
    election = Election.query.filter(
        (Election.election_id == str(election_id)) |
        (Election.id == int(election_id) if str(election_id).isdigit() else False)
    ).first()
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': f"Election '{election_id}' not found."}), 404

    if election.status not in ('DRAFT', 'PENDING_APPROVAL', 'SCHEDULED'):
        return jsonify({'error': 'INVALID_STATUS', 'message': f"Cannot schedule election in '{election.status}' state."}), 400

    if not _has_approved_schedule_request(election):
        return jsonify({
            'error': 'FOUR_EYES_APPROVAL_REQUIRED',
            'message': 'Scheduling requires a two-officer APPROVED SCHEDULE_ELECTION approval request.',
        }), 403

    if election.candidate_count < 2:
        return jsonify({'error': 'INSUFFICIENT_CANDIDATES', 'message': "Election must have at least 2 candidates."}), 400

    if not election.start_time or not election.end_time or election.start_time >= election.end_time:
        return jsonify({'error': 'INVALID_DATES', 'message': "Valid start_time and end_time (start < end) required."}), 400

    if election.status != 'SCHEDULED':
        election.status = 'SCHEDULED'
        election.scheduled_at = election.scheduled_at or datetime.utcnow()
        db.session.commit()

    return jsonify({
        'message': 'Election scheduled successfully.',
        'status': 'SCHEDULED',
        'election': {'status': election.status, 'id': election.election_id},
    }), 200


@admin_bp.route('/elections/<election_id>/open', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def open_election(election_id):
    """Open a Four-Eyes approved SCHEDULED election after V2 contract & checkpoint verification."""
    from app.services.v2_election_manager import V2ElectionManager
    election = Election.query.filter(
        (Election.election_id == str(election_id)) |
        (Election.id == int(election_id) if str(election_id).isdigit() else False)
    ).first()
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': f"Election '{election_id}' not found."}), 404

    if election.status != 'SCHEDULED':
        return jsonify({
            'error': 'INVALID_LIFECYCLE_TRANSITION',
            'message': f"Cannot open election from status '{election.status}'. Election must be SCHEDULED first.",
        }), 400

    if not _has_approved_schedule_request(election):
        return jsonify({
            'error': 'FOUR_EYES_APPROVAL_REQUIRED',
            'message': 'Opening requires a two-officer APPROVED SCHEDULE_ELECTION approval request.',
        }), 403

    try:
        ok, msg = V2ElectionManager.provision_and_open_election(str(election_id))
        if not ok:
            return jsonify({'error': 'OPEN_FAILED', 'message': msg}), 400

        db.session.refresh(election)
        return jsonify({
            'message': msg,
            'status': election.status,
            'election': {'status': election.status, 'id': election.election_id},
        }), 200
    except Exception as exc:
        return jsonify({'error': 'OPEN_FAILED', 'message': str(exc)}), 400


@admin_bp.route('/elections/<election_id>/close', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def close_election(election_id):
    """Close an election, automatically decrypting aggregate tallies and finalizing."""
    from app.services.v2_election_manager import V2ElectionManager
    try:
        ok, msg, details = V2ElectionManager.close_and_finalize_election(str(election_id))
        election = Election.query.filter(
            (Election.election_id == str(election_id)) |
            (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()

        if not ok:
            if details and details.get('error_code') == 'INVALID_LIFECYCLE_TRANSITION':
                return jsonify({'error': 'INVALID_LIFECYCLE_TRANSITION', 'message': msg}), 400
            # Fall back to standard close if offline
            try:
                election = ElectionAdminService.close_election(str(election_id), g.admin_user)
                return jsonify({
                    'message': 'Election is now CLOSED',
                    'status': election.status,
                    'election': {'status': election.status, 'id': election.election_id},
                }), 200
            except InvalidLifecycleTransitionError as trans_err:
                return jsonify({'error': 'INVALID_LIFECYCLE_TRANSITION', 'message': str(trans_err)}), 400
            except Exception:
                return jsonify({'error': 'CLOSE_FAILED', 'message': msg}), 400

        return jsonify({
            'message': msg,
            'status': election.status if election else 'FINALIZED',
            'details': details,
            'election': {'status': election.status if election else 'FINALIZED', 'id': election_id},
        }), 200
    except Exception as exc:
        return jsonify({'error': 'CLOSE_FAILED', 'message': str(exc)}), 400


# ------------------------------------------------------------------
# Two-Officer Approval Operations
# ------------------------------------------------------------------

@admin_bp.route('/approvals', methods=['GET'])
@require_admin_auth()
def list_approvals():
    """List approval requests (Accessible to Officers and Auditors)."""
    status_filter = request.args.get('status')
    query = ApprovalRequest.query
    if status_filter:
        query = query.filter_by(status=status_filter.upper())

    requests = query.order_by(ApprovalRequest.id.desc()).all()
    elections_map = {e.election_id: e.title for e in Election.query.all()}
    out = []
    for r in requests:
        req_item = {
            'id': r.id,
            'election_id': r.election_id,
            'election_title': elections_map.get(r.election_id),
            'action_type': r.action_type,
            'requester': r.requester.admin_id if r.requester else None,
            'approver': r.approver.admin_id if r.approver else None,
            'requester_name': r.requester.name if r.requester else None,
            'approver_name': r.approver.name if r.approver else None,
            'status': r.status,
            'rejection_reason': r.rejection_reason,
            'requested_at': r.requested_at.isoformat() if r.requested_at else None,
            'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
            'expires_at': r.expires_at.isoformat() if r.expires_at else None,
        }
        if r.payload_json:
            try:
                p_data = json.loads(r.payload_json)
                req_item['checkpoint_hash'] = p_data.get('checkpoint_hash')
                req_item['checkpoint_event_id'] = p_data.get('checkpoint_event_id')
                req_item['reason'] = p_data.get('reason')
                if 'execution' in p_data:
                    req_item['execution'] = p_data['execution']
            except Exception:
                pass
        out.append(req_item)
    return jsonify({'approval_requests': out}), 200


@admin_bp.route('/approvals/<int:request_id>/approve', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def approve_request(request_id):
    """
    Approve a pending critical action.
    Strictly requires a distinct approving officer (NO SELF-APPROVAL).
    """
    try:
        success, reason = ElectionAdminService.approve_request(
            request_id=request_id,
            approver=g.admin_user,
        )
        if not success:
            err_code = 'INVALID_APPROVAL_STATE' if ('PENDING' in reason or 'already' in reason.lower()) else 'APPROVAL_FAILED'
            return jsonify({'error': err_code, 'message': reason}), 400
        req = db.session.get(ApprovalRequest, request_id)
        election = Election.query.filter(
            (Election.election_id == req.election_id) | (Election.id == int(req.election_id) if str(req.election_id).isdigit() else False)
        ).first() if req else None

        res_payload = {
            'message': 'Operation approved and executed successfully',
            'status': req.status if req else 'APPROVED',
            'election_status': election.status if election else None,
        }
        if req and req.payload_json:
            try:
                p_data = json.loads(req.payload_json)
                if 'execution' in p_data:
                    res_payload['execution'] = p_data['execution']
            except Exception:
                pass
        return jsonify(res_payload), 200
    except TwoOfficerApprovalError as appr_err:
        return jsonify({'error': 'FOUR_EYES_VIOLATION', 'message': str(appr_err)}), 403
    except Exception as exc:
        return jsonify({'error': 'ERROR', 'message': str(exc)}), 400


@admin_bp.route('/approvals/<int:request_id>/reject', methods=['POST'])
@require_admin_auth(roles='OFFICER')
def reject_request(request_id):
    """Reject a pending approval request."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    reason = data.get('reason', 'Rejected by reviewing officer')

    try:
        success, err_msg = ElectionAdminService.reject_request(
            request_id=request_id,
            officer=g.admin_user,
            reason=reason,
        )
        if not success:
            return jsonify({'error': 'REJECT_FAILED', 'message': err_msg}), 400
        return jsonify({'message': 'Approval request rejected', 'status': 'REJECTED'}), 200
    except Exception as exc:
        return jsonify({'error': 'ERROR', 'message': str(exc)}), 400


# ------------------------------------------------------------------
# Audit & Dispute Handling
# ------------------------------------------------------------------

@admin_bp.route('/audit-logs', methods=['GET'])
@require_admin_auth()
def list_audit_logs():
    """List administrative audit events (Accessible to Officers and Auditors)."""
    raw_limit = request.args.get('limit', 50)
    try:
        limit = int(raw_limit)
        if limit < 1:
            limit = 50
    except (ValueError, TypeError):
        limit = 50
    limit = min(limit, 100)
    event_type = request.args.get('event_type')

    query = AuditEvent.query
    if event_type:
        query = query.filter_by(event_type=event_type)

    events = query.order_by(AuditEvent.id.desc()).limit(limit).all()
    out = [e.to_dict() for e in events]
    return jsonify({
        'audit_events': out,
        'events': out,
    }), 200


@admin_bp.route('/audit-logs/verify-chain', methods=['GET'])
@require_admin_auth()
def verify_audit_chain():
    """Verify cryptographic hash-chain integrity."""
    result = DisputeService.verify_audit_chain_integrity()
    return jsonify(result), 200


@admin_bp.route('/disputes/query', methods=['POST'])
@require_admin_auth()
def query_dispute():
    """
    Privacy-preserving operational dispute query.
    Strictly forbids candidate choice or voter -> candidate linkage.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    query_type = data.get('query_type')  # RECEIPT_CODE, VOTER_OPERATIONAL, RECONCILIATION_ISSUE

    if query_type in ('RECEIPT', 'RECEIPT_CODE'):
        receipt_code = data.get('receipt_code')
        if not receipt_code:
            return jsonify({'error': 'MISSING_CODE', 'message': 'receipt_code required'}), 400
        res = DisputeService.investigate_receipt(receipt_code, g.admin_user)
        return jsonify({'data': res, **res}), 200

    elif query_type in ('VOTER', 'VOTER_OPERATIONAL'):
        identifier = data.get('identifier') or data.get('voter_id') or data.get('usn')
        election_id = data.get('election_id')
        if not identifier:
            return jsonify({'error': 'MISSING_IDENTIFIER', 'message': 'USN or email identifier required'}), 400
        res = DisputeService.investigate_voter_operational(identifier, election_id, g.admin_user)
        return jsonify({'data': res, **res}), 200

    elif query_type == 'RECONCILIATION_ISSUE':
        issue_id = data.get('issue_id')
        if not issue_id:
            return jsonify({'error': 'MISSING_ISSUE_ID', 'message': 'issue_id required'}), 400
        try:
            issue_id_int = int(issue_id)
        except (ValueError, TypeError):
            return jsonify({'error': 'INVALID_ISSUE_ID', 'message': 'issue_id must be an integer'}), 400
        res = DisputeService.investigate_reconciliation_issue(issue_id_int, g.admin_user)
        return jsonify({'data': res, **res}), 200

    else:
        return jsonify({'error': 'INVALID_QUERY_TYPE', 'message': f"Unknown query type: '{query_type}'"}), 400


@admin_bp.route('/elections/<election_id>/export', methods=['GET'])
@require_admin_auth(roles=['OFFICER', 'AUDITOR'])
def export_election_results(election_id):
    """
    Administrative Election Results Export (CSV and XLSX).
    Accessible only to authorized OFFICER and AUDITOR roles.
    Strictly fail-closed against unapproved result states (OPEN, PENDING, UNDER_REVIEW).
    """
    fmt = (request.args.get('format') or 'csv').strip().lower()
    if fmt not in ('csv', 'xlsx'):
        return jsonify({
            'error': 'INVALID_FORMAT',
            'message': f"Unsupported export format '{fmt}'. Supported formats: 'csv', 'xlsx'."
        }), 400

    # Retrieve authoritative results via ResultsService
    success, reason, data = ResultsService.get_election_results(election_id)
    if not success:
        if reason == 'ELECTION_NOT_FOUND':
            return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': data.get('message')}), 404
        if reason == 'RESULTS_UNAVAILABLE':
            return jsonify({
                'error': 'RESULTS_UNAVAILABLE',
                'message': data.get('message') or 'Results export is strictly withheld while election is open or active.'
            }), 403
        if reason == 'PROCESSING_PENDING_BALLOTS':
            return jsonify({
                'error': 'PROCESSING_PENDING_BALLOTS',
                'message': data.get('message') or 'Results export is blocked while ballot queue is actively settling on blockchain.',
                'pending_ballots_count': data.get('pending_ballots_count', 0),
            }), 423
        return jsonify({'error': reason, 'message': data.get('message', 'Export blocked.')}), 403

    # State security check: Fail-closed. Only PROVISIONAL_UNFINALIZED and FINALIZED_RESULTS permitted.
    state = data.get('result_state')
    if state == 'RESULTS_UNDER_REVIEW' or data.get('is_under_review') is True:
        return jsonify({
            'error': 'RESULTS_UNDER_REVIEW',
            'message': 'Results export is strictly blocked: election is under review due to unresolved reconciliation discrepancies or blockchain mismatch.',
            'open_reconciliation_issues': data.get('open_reconciliation_issues', 0),
        }), 403

    if state not in ('PROVISIONAL_UNFINALIZED', 'FINALIZED_RESULTS'):
        return jsonify({
            'error': 'INVALID_RESULT_STATE',
            'message': f"Results export is blocked for unrecognized or uncertified result state '{state}'."
        }), 403

    # Generate complete file payload in memory FIRST
    try:
        if fmt == 'csv':
            content = ExportService.generate_results_csv(data, g.admin_user)
            mimetype = 'text/csv; charset=utf-8'
            filename = f"VWD_Results_{data['election_id']}.csv"
        else:
            buffer = ExportService.generate_results_xlsx(data, g.admin_user)
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            filename = f"VWD_Results_{data['election_id']}.xlsx"
    except Exception as exc:
        current_app.logger.error("Export generation failed for election %s: %s", election_id, exc)
        return jsonify({'error': 'EXPORT_GENERATION_FAILED', 'message': 'Failed to generate export file.'}), 500

    # Write and commit audit event ONLY after successful in-memory file preparation
    try:
        AuditLogger().log(
            event_type='ELECTION_RESULTS_EXPORTED',
            metadata={
                'election_id': str(data['election_id']),
                'format': fmt.upper(),
                'admin_id': g.admin_user.admin_id,
                'role': g.admin_user.role,
                'result_state': state,
                'officer_id': g.admin_user.admin_id,
                'state': state,
                'action': f"EXPORT_{fmt.upper()}",
            },
            commit=True,
        )
    except Exception as exc:
        current_app.logger.error("Audit logging failed during export of election %s: %s", election_id, exc)
        return jsonify({'error': 'AUDIT_LOG_FAILED', 'message': 'Export aborted due to audit logging failure.'}), 500

    # Return download stream
    if fmt == 'csv':
        return Response(
            content,
            mimetype=mimetype,
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Cache-Control': 'no-store, no-cache, must-revalidate',
            }
        )
    else:
        return send_file(
            buffer,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )
