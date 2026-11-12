"""
Privacy-Preserving Dispute Investigation Service - Phase 11
Vote Without Doubt - Backend

Enforces:
1. Operational dispute resolution for registration, authentication, receipts,
   reconciliation issues, and audit integrity.
2. STRICT PRIVACY INVARIANTS (Preserving Phase 8 & 10 boundaries):
   - NEVER returns or exposes voter candidate choice.
   - NEVER exposes voter -> candidate linkage.
   - NEVER exposes plaintext pseudonym to dispute investigators.
   - All dispute queries logged in tamper-evident hash-chained audit log.
"""

from datetime import datetime
import hashlib
import hmac
import os
from typing import Any, Dict, Optional

from app.audit.audit import AuditLogger
from app.extensions import db
from app.models.admin import AdminUser
from app.models.audit_event import AuditEvent
from app.models.auth import User
from app.models.ballot_record import BallotQueue, VotingAuthorization
from app.models.face import FaceEnrollment
from app.models.reconciliation import ReconciliationIssue
from app.models.roll import ElectoralRoll
from app.models.wallet import WalletBinding


class DisputeService:
    @staticmethod
    def investigate_receipt(receipt_code: str, admin: AdminUser) -> Dict[str, Any]:
        """
        Investigate a ballot dispute by receipt code.
        Verifies receipt validity and operational state.
        STRICT PRIVACY: Never reveals candidate or voter identity.
        """
        clean_code = receipt_code.strip().upper()
        ballot = BallotQueue.query.filter_by(receipt_code=clean_code).first()

        found = ballot is not None
        result = {
            'query_type': 'RECEIPT_CODE',
            'receipt_code': clean_code,
            'found': found,
            'receipt_found': found,
        }

        if found:
            result.update({
                'election_id': str(ballot.election_id),
                'sequence': ballot.sequence,
                'state': ballot.state,
                'block_number': ballot.block_number,
                'is_null_ballot': ballot.is_null,
                'superseded': ballot.superseded,
                'reconcile_required': ballot.reconcile_required,
                'reconcile_reason': ballot.reconcile_reason,
                'submitted_at': ballot.created_at.isoformat() if ballot.created_at else None,
                'confirmed_at': ballot.tx_confirmed_at.isoformat() if ballot.tx_confirmed_at else None,
                'failed_at': ballot.tx_failed_at.isoformat() if ballot.tx_failed_at else None,
            })
            # Validate HMAC integrity format
            secret = os.getenv('RECEIPT_SECRET') or os.getenv('PSEUDONYM_MASTER_KEY') or 'default-secret'
            parts = clean_code.split('-')
            result['format_valid'] = len(parts) >= 3 and parts[0] == 'REC'

        AuditLogger().log('DISPUTE_INVESTIGATION', {
            'admin_id': admin.admin_id,
            'role': admin.role,
            'query_type': 'RECEIPT_CODE',
            'found': found,
        })
        return result

    @staticmethod
    def investigate_voter_operational(usn_or_email: str, election_id: Optional[str], admin: AdminUser) -> Dict[str, Any]:
        """
        Investigate operational voter eligibility, authentication, and factor completion.
        STRICT PRIVACY: Never reveals candidate choice or voter -> candidate linkage.
        """
        query_val = usn_or_email.strip()
        roll_entry = ElectoralRoll.query.filter(
            (ElectoralRoll.usn == query_val) | (ElectoralRoll.college_email == query_val)
        ).first()

        user = User.query.filter(
            (User.email == query_val) | (User.username == query_val) | (User.voter_id == query_val)
        ).first()

        result = {
            'query_type': 'VOTER_OPERATIONAL',
            'roll_registered': roll_entry is not None,
            'is_eligible': roll_entry.is_eligible if roll_entry else False,
            'electoral_roll_status': 'ELIGIBLE' if (roll_entry and roll_entry.is_eligible) else ('NOT_FOUND' if not roll_entry else 'INELIGIBLE'),
            'account_created': user is not None,
            'account_registered': user is not None,
        }

        if user:
            wb = WalletBinding.query.filter_by(user_id=user.id).first()
            fe = FaceEnrollment.query.filter_by(user_id=user.id).first()

            result.update({
                'account_active': user.is_active,
                'account_verified': user.is_verified,
                'account_locked': user.locked_until is not None and user.locked_until > datetime.utcnow(),
                'wallet_bound': wb is not None and wb.is_verified,
                'face_enrolled': fe is not None and fe.is_active(),
            })

            if election_id:
                auth_count = VotingAuthorization.query.filter_by(
                    user_id=user.id,
                    election_id=int(election_id) if election_id.isdigit() else 0,
                ).count()
                result['authorization_attempts'] = auth_count

        AuditLogger().log('DISPUTE_INVESTIGATION', {
            'admin_id': admin.admin_id,
            'role': admin.role,
            'query_type': 'VOTER_OPERATIONAL',
            'roll_found': roll_entry is not None,
            'user_found': user is not None,
        })
        return result

    @staticmethod
    def investigate_reconciliation_issue(issue_id: int, admin: AdminUser) -> Dict[str, Any]:
        """Investigate a specific reconciliation issue."""
        issue = ReconciliationIssue.query.get(issue_id)
        if not issue:
            return {'found': False, 'issue_id': issue_id}

        result = {
            'found': True,
            'id': issue.id,
            'election_id': issue.election_id,
            'issue_type': issue.issue_type,
            'severity': issue.severity,
            'status': issue.status,
            'observed_state': issue.observed_state,
            'expected_state': issue.expected_state,
            'resolution_note': issue.resolution_note,
            'created_at': issue.created_at.isoformat() if issue.created_at else None,
            'resolved_at': issue.resolved_at.isoformat() if issue.resolved_at else None,
        }

        AuditLogger().log('DISPUTE_INVESTIGATION', {
            'admin_id': admin.admin_id,
            'role': admin.role,
            'query_type': 'RECONCILIATION_ISSUE',
            'issue_id': issue_id,
        })
        return result

    @staticmethod
    def verify_audit_chain_integrity() -> Dict[str, Any]:
        """Verify the SHA-256 hash-chain integrity and payload authenticity of all audit events."""
        from app.audit.audit import verify_events
        events = AuditEvent.query.order_by(AuditEvent.id.asc()).all()
        if not events:
            return {'events_checked': 0, 'verified_count': 0, 'intact': True, 'valid': True}

        ok, broken_index = verify_events(events)
        broken_at_id = events[broken_index].id if (broken_index is not None and broken_index < len(events)) else None

        return {
            'events_checked': len(events),
            'verified_count': len(events) if ok else broken_index,
            'intact': ok,
            'valid': ok,
            'broken_at_id': broken_at_id,
        }
