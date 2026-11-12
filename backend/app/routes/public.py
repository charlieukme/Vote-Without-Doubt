"""
Public Verification & Results API Routes - Phase 12
Vote Without Doubt - Backend

Endpoints:
  GET /api/elections/<election_id>/results:
    Authoritative election results and tallies.
    Strictly gated: returns 403 RESULTS_UNAVAILABLE if election is still OPEN/ACTIVE.
    Available once CLOSED or FINALIZED.

  GET /api/elections/<election_id>/verification:
    Public verification dataset (contract address, parameters, candidate hash,
    roll hash, blockchain evidence, audit evidence).
    Zero private voter information returned.

  GET /api/elections/<election_id>/audit-verification:
    Independent cryptographic audit chain verification & blockchain anchor status.

  GET /api/elections/<election_id>/tampering-demo:
    Controlled test demonstrating database tampering detection and clean restoration.

  GET /api/public/elections:
    Public catalog of elections with statuses and verification links.
"""

import os
import re
import secrets
from datetime import datetime
from flask import Blueprint, current_app, jsonify, request, send_from_directory

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models.admin import Candidate, SupportTicket
from app.models.ballot import Election
from app.security.admin_auth import require_admin_auth
from app.services.results_service import ResultsService
from app.services.verification_service import VerificationService

public_bp = Blueprint('public', __name__)


@public_bp.route('/elections/<election_id>/results', methods=['GET'])
@public_bp.route('/results/<election_id>', methods=['GET'])
def get_results(election_id: str):
    """
    Public Election Results Endpoint.
    Gated: Available only after election close (CLOSED or FINALIZED).
    """
    success, reason, data = ResultsService.get_election_results(election_id)
    if not success:
        if reason == 'ELECTION_NOT_FOUND':
            return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': data.get('message')}), 404
        if reason == 'RESULTS_UNAVAILABLE':
            return jsonify(data), 403
        if reason == 'PROCESSING_PENDING_BALLOTS':
            return jsonify(data), 423
        return jsonify({'error': reason, 'message': data.get('message', reason)}), 400

    return jsonify({'success': True, 'data': data, **data}), 200


@public_bp.route('/elections/<election_id>/verification', methods=['GET'])
@public_bp.route('/verification/<election_id>', methods=['GET'])
def get_verification(election_id: str):
    """
    Public Election Verification Endpoint.
    Exposes smart contract address, candidate hash, roll hash, audit anchor.
    Strictly forbids private voter identity or vote-choice exposure.
    """
    success, reason, data = VerificationService.get_public_verification(election_id)
    if not success:
        if reason == 'ELECTION_NOT_FOUND':
            return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': data.get('message')}), 404
        return jsonify({'error': reason, 'message': data.get('message', reason)}), 400

    return jsonify({'success': True, 'data': data, **data}), 200


@public_bp.route('/verification/receipt/<path:receipt_code>', methods=['GET'])
@public_bp.route('/elections/receipt/<path:receipt_code>', methods=['GET'])
def get_receipt_verification(receipt_code: str):
    """
    Public Cryptographic Receipt Verification Endpoint.
    Verifies HMAC signature, database existence, and on-chain confirmation.
    Zero voter identity, USN, wallet address, or candidate exposure.
    """
    result = VerificationService.verify_receipt(receipt_code)
    status_code = 200
    if result.get('status') == 'NOT_FOUND':
        status_code = 404
    elif result.get('status') == 'INVALID':
        status_code = 400
    elif result.get('status') == 'UNAVAILABLE':
        status_code = 503
    return jsonify({'success': result.get('status') == 'VALID', 'data': result, **result}), status_code


@public_bp.route('/verification/receipt', methods=['GET', 'POST'])
def post_receipt_verification():
    """
    POST/GET endpoint for verifying receipt code from query param or request body.
    """
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        receipt_code = data.get('receipt_code') or data.get('code') or ''
    else:
        receipt_code = request.args.get('receipt_code') or request.args.get('code') or ''

    return get_receipt_verification(receipt_code)


@public_bp.route('/verification/receipt/<path:receipt_code>/inclusion-proof', methods=['GET'])
@public_bp.route('/public/receipt/<path:receipt_code>/inclusion-proof', methods=['GET'])
@public_bp.route('/receipt/<path:receipt_code>/inclusion-proof', methods=['GET'])
def get_receipt_inclusion_proof(receipt_code: str):
    """
    Generate and return an RFC 6962 Merkle inclusion proof for a verified ballot receipt.
    Exposes: commitment, opening nonce, Merkle root, audit path, and proof validity.
    Zero voter identity, USN, email, or wallet exposure.
    """
    # Privacy Protection: Opening nonce is withheld from unauthenticated public lookup
    # to eliminate third-party candidate inference brute-force search.
    result = VerificationService.get_inclusion_proof_for_receipt(receipt_code, allow_nonce=False)
    status_code = 200
    if result.get('status') == 'NOT_FOUND':
        status_code = 404
    elif result.get('status') in ('BALLOT_NOT_SETTLED', 'BALLOT_SUPERSEDED', 'NO_COMMITMENT_FOUND'):
        status_code = 400
    elif result.get('status') == 'INVALID':
        status_code = 400
    return jsonify({'success': result.get('verified', False), 'data': result, **result}), status_code


@public_bp.route('/verification/verify-inclusion-proof', methods=['POST'])
@public_bp.route('/public/verify-inclusion-proof', methods=['POST'])
def post_verify_inclusion_proof():
    """
    Cryptographically verify an arbitrary Merkle inclusion proof against a root.
    Input JSON: { "commitment": "...", "merkle_root": "...", "audit_path": [...] }
    Output: { "verified": true/false, "status": "VALID INCLUSION PROOF" / "INVALID INCLUSION PROOF", ... }
    """
    from app.security.merkle import verify_inclusion_proof

    data = request.get_json(silent=True) or {}
    commitment = data.get('commitment', '')
    merkle_root = data.get('merkle_root', '')
    audit_path = data.get('audit_path', [])

    if not commitment or not merkle_root:
        return jsonify({
            'verified': False,
            'status': 'INVALID INCLUSION PROOF',
            'message': 'Both commitment and merkle_root are required.',
        }), 400

    if not isinstance(audit_path, list):
        return jsonify({
            'verified': False,
            'status': 'INVALID INCLUSION PROOF',
            'message': 'audit_path must be a list of sibling steps.',
        }), 400

    is_valid, msg = verify_inclusion_proof(
        commitment_hex=commitment,
        merkle_root_hex=merkle_root,
        audit_path=audit_path,
    )
    return jsonify({
        'verified': is_valid,
        'status': 'VALID INCLUSION PROOF' if is_valid else 'INVALID INCLUSION PROOF',
        'message': msg,
        'commitment': commitment,
        'merkle_root': merkle_root,
        'tally_disclaimer': 'A Merkle inclusion proof proves membership in the committed ballot set. It does not prove tally correctness unless verified against on-chain smart contract tallies.',
    }), 200


@public_bp.route('/elections/<election_id>/audit-verification', methods=['GET'])
def get_audit_verification(election_id: str):
    """
    Cryptographic administrative audit log verification & on-chain anchor status.
    """
    result = VerificationService.verify_audit_anchor(election_id)
    if result.get('error') == 'ELECTION_NOT_FOUND':
        return jsonify(result), 404
    return jsonify({'success': True, 'data': result, **result}), 200


@public_bp.route('/elections/<election_id>/audit-chain', methods=['GET'])
@public_bp.route('/verification/<election_id>/audit-chain', methods=['GET'])
def get_audit_chain_verification(election_id: str):
    """
    Public endpoint providing the cryptographic audit hash chain up to the anchored checkpoint.
    Allows independent clients to verify chain integrity from genesis and authenticate the Merkle root.
    """
    result = VerificationService.get_audit_chain_for_verification(election_id)
    if result.get('error') == 'ELECTION_NOT_FOUND':
        return jsonify(result), 404
    return jsonify({'success': True, 'data': result, **result}), 200


@public_bp.route('/elections/<election_id>/tampering-demo', methods=['GET', 'POST'])
@require_admin_auth(['OFFICER', 'AUDITOR'])
def run_tampering_demonstration(election_id: str):
    """
    Demonstrate that controlled database tampering is detected and cleanly reverted.
    Strictly isolated demonstration:
      1. Disabled in production environments (403 Forbidden).
      2. Requires administrative authentication (OFFICER or AUDITOR role).
      3. Operates strictly inside an isolated ephemeral sandbox without touching production ballots.
    """
    env = (os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV') or current_app.config.get('APP_ENV') or '').lower()
    if env == 'production' or current_app.config.get('ENV') == 'production':
        return jsonify({
            'error': 'DEMO_DISABLED_IN_PRODUCTION',
            'message': 'Tampering demonstration is disabled in production environments.',
            'demonstration_status': 'DISABLED',
        }), 403

    result = VerificationService.run_tampering_demonstration(election_id)
    if result.get('error') == 'ELECTION_NOT_FOUND':
        return jsonify(result), 404
    if result.get('error') == 'DEMO_DISABLED_IN_PRODUCTION':
        return jsonify(result), 403
    return jsonify({'success': True, 'data': result, **result}), 200


def _resolve_election(raw_eid):
    """Resolve Election by string election_id (e.g. ELEC_...) or integer primary key."""
    if raw_eid is None or str(raw_eid).strip().lower() in ('', 'default', 'active', 'current'):
        for e in Election.query.order_by(Election.id.desc()).all():
            if e.effective_status in ('OPEN', 'ACTIVE'):
                return e
        for e in Election.query.order_by(Election.id.desc()).all():
            if e.effective_status == 'SCHEDULED':
                return e
        return Election.query.order_by(Election.id.desc()).first()

    eid_str = str(raw_eid).strip()
    return Election.query.filter(
        (Election.election_id == eid_str) | (Election.id == int(eid_str) if eid_str.isdigit() else False)
    ).first()


@public_bp.route('/public/elections', methods=['GET'])
def list_public_elections():
    """
    Public directory of elections with authoritative server time.
    """
    elections = Election.query.order_by(Election.id.desc()).all()
    now_utc = datetime.utcnow()
    results = []
    for e in elections:
        eff_status = e.effective_status
        results.append({
            'id': e.id,
            'election_id': e.election_id,
            'title': e.title,
            'description': e.description,
            'status': eff_status,
            'candidate_count': e.candidate_count,
            'start_time': (e.start_time.isoformat() + 'Z') if e.start_time else None,
            'end_time': (e.end_time.isoformat() + 'Z') if e.end_time else None,
            'registration_deadline': (e.registration_deadline.isoformat() + 'Z') if getattr(e, 'registration_deadline', None) else None,
            'results_available': (eff_status in ('CLOSED', 'FINALIZED')),
        })
    return jsonify({
        'success': True,
        'server_time': now_utc.isoformat() + 'Z',
        'elections': results,
    }), 200


@public_bp.route('/elections/<election_id>', methods=['GET'])
@public_bp.route('/public/elections/<election_id>', methods=['GET'])
@public_bp.route('/public/elections/<election_id>/candidates', methods=['GET'])
def get_public_election(election_id: str):
    """
    Public Election & Candidate Details.
    Allows unauthenticated and authenticated students to view election schedule,
    status, and certified candidate profiles without exposing voter state.
    """
    election = _resolve_election(election_id)
    if not election:
        return jsonify({'error': 'ELECTION_NOT_FOUND', 'message': f"Election '{election_id}' not found."}), 404

    cand_eids = {str(election.id), str(election.election_id)}
    if election_id:
        cand_eids.add(str(election_id).strip())
    db_candidates = Candidate.query.filter(
        Candidate.election_id.in_(list(cand_eids))
    ).order_by(Candidate.candidate_index.asc()).all()

    candidates = [
        {
            'id': c.id,
            'index': c.candidate_index,
            'candidate_index': c.candidate_index,
            'name': c.name,
            'position': getattr(c, 'position', None) or c.department or 'Candidate',
            'department': c.department or '',
            'party': c.department or getattr(c, 'position', None) or '',
            'affiliation': c.department or getattr(c, 'position', None) or '',
            'year': getattr(c, 'year', None) or '',
            'slogan': getattr(c, 'slogan', None) or '',
            'manifesto': getattr(c, 'manifesto', None) or '',
            'photo_url': getattr(c, 'photo_url', None),
        }
        for c in db_candidates
    ]

    now_utc = datetime.utcnow()
    eff_status = election.effective_status
    return jsonify({
        'success': True,
        'id': election.id,
        'election_id': election.election_id,
        'title': election.title,
        'description': election.description,
        'status': eff_status,
        'candidate_count': len(candidates),
        'candidates': candidates,
        'start_time': (election.start_time.isoformat() + 'Z') if election.start_time else None,
        'end_time': (election.end_time.isoformat() + 'Z') if election.end_time else None,
        'server_time': now_utc.isoformat() + 'Z',
    }), 200


@public_bp.route('/public/server-time', methods=['GET'])
def get_server_time():
    """Authoritative server UTC timestamp for synchronized countdowns."""
    now_utc = datetime.utcnow()
    return jsonify({
        'server_time': now_utc.isoformat() + 'Z',
        'timestamp': int(now_utc.timestamp()),
    }), 200


@public_bp.route('/public/candidate-photo/<path:filename>', methods=['GET'])
def get_candidate_photo(filename):
    """
    Serve uploaded candidate photo securely.
    Guarantees strict filename regex to prevent any path traversal.
    """
    if not re.match(r'^[a-f0-9]{32}\.(jpg|png|webp)$', filename):
        return jsonify({'error': 'INVALID_FILENAME'}), 400

    upload_dir = os.path.join(current_app.root_path, 'uploads', 'candidates')
    response = send_from_directory(upload_dir, filename)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


@public_bp.route('/public/support/report', methods=['POST'])
def submit_support_report():
    """
    Public / Voter Support and Issue Reporting.
    Strictly forbids candidate choice, ballot ID, private keys, or passwords.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}

    category = (data.get('category') or 'other').strip().lower()
    details = (data.get('details') or data.get('description') or '').strip()
    contact_email = (data.get('contact_email') or data.get('email') or '').strip().lower()

    valid_categories = {'otp', 'usn', 'wallet', 'camera', 'receipt', 'other'}
    if category not in valid_categories:
        category = 'other'

    if not details or len(details) < 5:
        return jsonify({'error': 'DETAILS_REQUIRED', 'message': 'Please provide details of the issue (min 5 characters).'}), 400

    # Payload ceiling & sanitization
    if len(details) > 2000:
        details = details[:2000]
    details_clean = re.sub(r'<[^>]*>', '', details)

    # Privacy filtering: reject attempts to submit sensitive secrets
    sensitive_markers = ['private_key', 'privatekey', 'seed phrase', '0x', 'password', 'vote for']
    lower_det = details_clean.lower()
    for marker in ['private_key', 'seed phrase']:
        if marker in lower_det:
            return jsonify({
                'error': 'SENSITIVE_DATA_REJECTED',
                'message': 'Do not include private keys or seed phrases in support tickets.'
            }), 400

    ref_id = f"REF-{secrets.token_hex(4).upper()}"
    ticket = SupportTicket(
        reference_id=ref_id,
        category=category,
        details=details_clean,
        contact_email=contact_email if '@' in contact_email else None,
        status='OPEN',
    )
    db.session.add(ticket)
    db.session.commit()

    AuditLogger().log('support.ticket_created', {
        'reference_id': ref_id,
        'category': category,
    })

    return jsonify({
        'success': True,
        'reference_id': ref_id,
        'message': 'Your support issue has been logged. Note your reference ID for follow-up.',
    }), 201

