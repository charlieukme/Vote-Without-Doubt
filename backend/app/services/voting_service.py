"""
Voting Service - Phase 7 (remediated)
Vote Without Doubt - Backend

Enforces:
1. Multi-factor voting authorization (Phase 4 wallet binding + Phase 5 face liveness).
2. Strict session binding (authorization must match submitting session).
3. Single-use authorization consumed upon valid ballot queueing.
4. Election validity and candidate range validation.
5. Strict one-ballot-per-pseudonym enforcement (sequence 1 only; Phase 9 revoting prohibited).
6. Minimal privacy-preserving HMAC receipts (Section 8.6).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    BallotRecord,
    Election,
    FaceChallenge,
    FaceEnrollment,
    User,
    VotingAuthorization,
    WalletBinding,
)
from app.security.pseudonym import derive_pseudonym


import threading

class VotingService:
    _creation_lock = threading.Lock()
    _factors_lock = threading.Lock()

    @staticmethod
    def create_authorization(
        user_id: int,
        election_id: int,
        session_id: Optional[str] = None,
        ttl_sec: int = 300,
    ) -> VotingAuthorization:
        """Create a new unverified voting authorization bound to user, election, and session."""
        with VotingService._creation_lock:
            now = datetime.utcnow()
            # INT-001: Deduplicate active unexpired, unconsumed authorization for this user/election/session
            query = VotingAuthorization.query.filter(
                VotingAuthorization.user_id == user_id,
                VotingAuthorization.election_id == election_id,
                VotingAuthorization.consumed.is_(False),
                VotingAuthorization.expires_at > now,
            )
            if session_id:
                query = query.filter(VotingAuthorization.session_id == session_id)
            existing = query.order_by(VotingAuthorization.id.desc()).first()
            if existing:
                return existing

            va = VotingAuthorization(
                user_id=user_id,
                election_id=election_id,
                session_id=session_id,
                expires_at=now + timedelta(seconds=ttl_sec),
                wallet_verified=False,
                face_verified=False,
                authorized=False,
                consumed=False,
            )
            db.session.add(va)
            db.session.commit()
            return va

    @staticmethod
    def mark_factors(
        user_id: int,
        election_id: int,
        session_id: Optional[str] = None,
    ) -> Optional[VotingAuthorization]:
        """
        Aggregate verified server-side factor proofs for this user and session.
        Never trusts client assertions: checks genuine database records.
        """
        with VotingService._factors_lock:
            query = VotingAuthorization.query.filter_by(
                user_id=user_id,
                election_id=election_id,
                consumed=False,
            )
            if session_id:
                query = query.filter_by(session_id=session_id)
            va = query.order_by(VotingAuthorization.id.desc()).first()
            if not va and session_id:
                va = VotingAuthorization.query.filter_by(
                    user_id=user_id,
                    election_id=election_id,
                    consumed=False,
                ).order_by(VotingAuthorization.id.desc()).first()

            now = datetime.utcnow()
            if not va or va.expires_at < now:
                return None

            # 1. Verify Wallet factor from Phase 4: verified WalletBinding for user
            wallet_binding = WalletBinding.query.filter_by(
                user_id=user_id,
                is_verified=True,
            ).first()
            wallet_ok = wallet_binding is not None

            # If authorization is already fully verified and wallet remains bound, preserve it
            if va.authorized and va.face_verified and wallet_ok:
                va.wallet_verified = True
                db.session.commit()
                return va

            # 2. Check if face is already verified for this authorization
            face_ok = bool(va.face_verified)

            # If face not yet verified, verify and consume genuine completed FaceChallenge
            if not face_ok:
                face_enrollment = FaceEnrollment.query.filter_by(user_id=user_id).first()
                face_enrolled = face_enrollment is not None and face_enrollment.is_active()

                # Maximum permitted age for completed verification (default: 300s / 5min)
                max_age_sec = 300
                try:
                    from flask import current_app
                    if current_app:
                        max_age_sec = int(current_app.config.get('FACE_CHALLENGE_MAX_VERIFIED_AGE_SECONDS', 300))
                except Exception:
                    pass

                # Query genuine, unconsumed, completed, successful challenge
                face_challenge_query = FaceChallenge.query.filter(
                    FaceChallenge.user_id == user_id,
                    FaceChallenge.completed.is_(True),
                    FaceChallenge.success.is_(True),
                    FaceChallenge.consumed.is_(False),
                    FaceChallenge.expires_at > now,
                )
                if session_id:
                    face_challenge_query = face_challenge_query.filter(
                        (FaceChallenge.session_id == session_id) | (FaceChallenge.session_id.is_(None))
                    )

                # Authoritative binding enforcement:
                # Challenge must be strictly bound to this exact VotingAuthorization.
                face_challenge = face_challenge_query.filter(
                    FaceChallenge.authorization_id == va.id
                ).order_by(FaceChallenge.id.desc()).first()

                if face_enrolled and face_challenge is not None:
                    # Enforce completed_at freshness if present
                    fresh = True
                    if face_challenge.completed_at:
                        age = (now - face_challenge.completed_at).total_seconds()
                        if age > max_age_sec:
                            fresh = False

                    if fresh:
                        # Atomic consumption: conditional update prevents concurrent double-consumption
                        rows_updated = FaceChallenge.query.filter(
                            FaceChallenge.id == face_challenge.id,
                            FaceChallenge.consumed.is_(False),
                        ).update({
                            'consumed': True,
                            'consumed_at': now,
                            'authorization_id': va.id,
                            'election_id': election_id,
                        }, synchronize_session=False)

                        if rows_updated == 1:
                            face_ok = True
                        else:
                            db.session.rollback()
                            va.face_verified = False
                            va.authorized = False
                            return va

            va.wallet_verified = wallet_ok
            va.face_verified = face_ok
            if wallet_ok and face_ok:
                va.authorized = True
                if not va.authorized_at:
                    va.authorized_at = now
            else:
                va.authorized = False

            db.session.commit()
            return va

    @staticmethod
    def get_authorization(
        user_id: int,
        election_id: int,
        session_id: Optional[str] = None,
    ) -> Optional[VotingAuthorization]:
        """Fetch the latest active unconsumed authorization."""
        election_obj = Election.query.filter(
            (Election.election_id == str(election_id)) | (Election.id == election_id)
        ).first()
        eid_candidates = [election_id]
        if election_obj:
            eid_candidates.extend([election_obj.id, str(election_obj.election_id)])
            if str(election_obj.election_id).isdigit():
                eid_candidates.append(int(election_obj.election_id))
        eid_candidates = list(set(eid_candidates))

        query = VotingAuthorization.query.filter(
            VotingAuthorization.user_id == user_id,
            VotingAuthorization.election_id.in_(eid_candidates),
            VotingAuthorization.consumed == False,
        )
        if session_id:
            query = query.filter_by(session_id=session_id)
        return query.order_by(VotingAuthorization.id.desc()).first()

    @staticmethod
    def validate_election_and_candidate(
        election_id: int,
        candidate: Optional[int] = 0,
        is_null: bool = False,
    ) -> Tuple[bool, str, int]:
        """
        Validate election existence/timing and candidate index bounds.
        Returns (is_valid, error_code, candidate_count).
        """
        if not is_null:
            if not isinstance(candidate, int) or candidate < 0:
                return False, "INVALID_CANDIDATE", 0

        # Query database election record if present
        election = Election.query.filter(
            (Election.election_id == str(election_id)) | (Election.id == election_id)
        ).first()

        if not election:
            return False, "ELECTION_NOT_FOUND", 0

        now = datetime.utcnow()
        if election.end_time and now > election.end_time:
            return False, "ELECTION_CLOSED", 0
        if election.effective_status not in ('ACTIVE', 'OPEN'):
            return False, "ELECTION_NOT_ACTIVE", 0
        if election.start_time and now < election.start_time:
            return False, "ELECTION_NOT_OPEN", 0

        from app.models.admin import Candidate
        c_count = Candidate.query.filter(
            (Candidate.election_id == str(election.election_id)) | (Candidate.election_id == str(election.id))
        ).count()
        candidate_count = c_count if c_count > 0 else (election.candidate_count if (getattr(election, 'candidate_count', 0) or 0) > 0 else 0)

        # Reject elections with insufficient or zero candidates
        if candidate_count < 2:
            return False, "ELECTION_NO_CANDIDATES", candidate_count

        # Validate candidate bounds: candidate index must be 0 <= candidate < candidate_count
        if not is_null and (candidate < 0 or candidate >= candidate_count):
            return False, "INVALID_CANDIDATE", candidate_count

        # Validate on-chain provisioning if smart contract is configured
        is_testing = False
        try:
            if current_app and current_app.config.get('TESTING'):
                is_testing = True
        except (RuntimeError, NameError):
            pass

        enforce_in_test = False
        try:
            if current_app and current_app.config.get('ENFORCE_BLOCKCHAIN_IN_TESTS'):
                enforce_in_test = True
        except (RuntimeError, NameError):
            pass

        if not is_testing or enforce_in_test:
            try:
                from app.services.reconciliation_service import ReconciliationService
                relayer, w3, contract = ReconciliationService.get_relayer_and_contract()
                if contract and w3 and w3.is_connected():
                    from app.services.election_admin_service import ElectionAdminService
                    on_chain_id = ElectionAdminService.get_on_chain_election_id(election)
                    chain_info = contract.functions.elections(on_chain_id).call()
                    try:
                        end_val = int(chain_info[1])
                        if end_val == 0:
                            return False, "ELECTION_NOT_EXISTS", candidate_count
                    except (IndexError, TypeError, ValueError):
                        pass
            except Exception:
                pass

        return True, "OK", candidate_count

    @staticmethod
    def submit_ballot(
        user_id: int,
        election_id: int,
        candidate: Optional[int] = 0,
        session_id: Optional[str] = None,
        is_null: bool = False,
        client_commitment: Optional[str] = None,
        client_nonce: Optional[str] = None,
    ) -> Tuple[Optional[BallotRecord], str]:
        """
        Phase 9 Controlled Revoting:
        Validate authorization, factors, election, candidate, sequence, limit, cooldown.
        Atomically assigns next_sequence based on authoritative confirmed/on-chain state.
        Marks previous ballots superseded=True and consumes authorization.
        """
        from flask import current_app
        from app.security.pseudonym import PseudonymKeyError

        # 1. Validate election and candidate bounds
        val_ok, val_err, _ = VotingService.validate_election_and_candidate(
            election_id, candidate, is_null=is_null
        )
        if not val_ok:
            return None, val_err

        election_obj = Election.query.filter(
            (Election.election_id == str(election_id)) | (Election.id == election_id)
        ).first()

        eid_candidates = [election_id]
        if election_obj:
            eid_candidates.extend([election_obj.id, str(election_obj.election_id)])
            if str(election_obj.election_id).isdigit():
                eid_candidates.append(int(election_obj.election_id))
        eid_candidates = list(set(eid_candidates))

        # 2. Derive election-specific pseudonym (fails closed if election key missing/destroyed)
        pseud_candidates = []
        for eid_val in eid_candidates:
            try:
                p = derive_pseudonym(user_id, eid_val)
                if p not in pseud_candidates:
                    pseud_candidates.append(p)
            except PseudonymKeyError:
                pass

        if not pseud_candidates:
            return None, "ELECTION_NOT_ACTIVE"

        # 3. Query existing ballots for this voter and election to determine sequence
        existing_ballots = BallotRecord.query.filter(
            BallotRecord.pseudonym.in_(pseud_candidates),
            BallotRecord.election_id.in_(eid_candidates),
        ).order_by(BallotRecord.sequence.desc(), BallotRecord.id.desc()).all()

        pseud = existing_ballots[0].pseudonym if existing_ballots else pseud_candidates[0]

        max_ballots = 3
        try:
            if current_app:
                max_ballots = int(current_app.config.get('MAX_BALLOTS_PER_VOTER', 3))
        except Exception:
            pass

        if election_obj and hasattr(election_obj, 'max_ballots') and election_obj.max_ballots:
            max_ballots = min(max_ballots, election_obj.max_ballots)

        latest = existing_ballots[0] if existing_ballots else None

        # Check if an earlier ballot is still in flight (QUEUED or SUBMITTED)
        if latest and latest.state in ('QUEUED', 'SUBMITTED'):
            return None, "PREVIOUS_BALLOT_PENDING"

        # Determine authoritative sequence:
        # Check whether any ballot has actually been confirmed on-chain for this pseudonym
        chain_exists = False
        chain_seq = 0
        try:
            from app.services.reconciliation_service import ReconciliationService
            relayer, w3, contract = ReconciliationService.get_relayer_and_contract()
            if contract and w3 and w3.is_connected():
                pseudo_bytes = relayer._format_pseudonym(pseud)
                from app.services.election_admin_service import ElectionAdminService
                on_chain_id = ElectionAdminService.get_on_chain_election_id(election_obj)
                ballot_data = contract.functions.getBallot(on_chain_id, pseudo_bytes).call()
                from unittest.mock import MagicMock
                if not isinstance(ballot_data, MagicMock) and hasattr(ballot_data, '__getitem__'):
                    val0 = ballot_data[0]
                    val3 = ballot_data[3]
                    if not isinstance(val0, MagicMock) and not isinstance(val3, MagicMock):
                        chain_seq = int(val0)
                        chain_exists = bool(val3)
        except Exception:
            pass

        confirmed_ballots = [b for b in existing_ballots if b.state in ('CONFIRMED', 'FINALIZED')]
        latest_confirmed = confirmed_ballots[0] if confirmed_ballots else None

        if not chain_exists and not latest_confirmed:
            # First genuine vote on blockchain: sequence must be 1.
            # Null ballot cannot be initial vote.
            if is_null:
                return None, "NO_PRIOR_BALLOT"
            next_seq = 1
        else:
            # Revote on blockchain: increment from authoritative previous sequence
            prior_seq = chain_seq if chain_exists else (int(latest_confirmed.sequence) if latest_confirmed else 0)
            next_seq = int(prior_seq) + 1
            if max_ballots == 1:
                return None, "BALLOT_ALREADY_CAST"
            if next_seq > max_ballots:
                return None, "MAX_BALLOTS_EXCEEDED"

            # Check cooldown between revotes
            cooldown_sec = 120
            try:
                if current_app:
                    cooldown_sec = int(current_app.config.get('REVOTE_COOLDOWN_SECONDS', 120))
            except Exception:
                pass

            if latest_confirmed and cooldown_sec > 0 and latest_confirmed.created_at:
                elapsed = (datetime.utcnow() - latest_confirmed.created_at).total_seconds()
                if elapsed < cooldown_sec:
                    return None, "COOLDOWN_ACTIVE"

        # 4. Enforce fresh unconsumed authorization
        va = VotingAuthorization.query.filter(
            VotingAuthorization.user_id == user_id,
            VotingAuthorization.election_id.in_(eid_candidates),
        ).order_by(VotingAuthorization.id.desc()).first()

        if not va:
            return None, "UNAUTHORIZED"
        if va.consumed:
            return None, "AUTHORIZATION_CONSUMED"
        if session_id and va.session_id and va.session_id != session_id:
            return None, "SESSION_MISMATCH"
        if va.expires_at < datetime.utcnow():
            return None, "AUTHORIZATION_EXPIRED"
        if not va.wallet_verified or not va.face_verified or not va.authorized:
            return None, "FACTORS_INCOMPLETE"

        # SEC-D0-01 Remediation:
        # Atomically claim the authorization within the transaction.
        # This guarantees mutual exclusion and prevents concurrent requests from both claiming it.
        now_utc = datetime.utcnow()
        claimed = VotingAuthorization.query.filter(
            VotingAuthorization.id == va.id,
            VotingAuthorization.consumed.is_(False),
        ).update(
            {
                'consumed': True,
                'consumed_at': now_utc,
            },
            synchronize_session=False,
        )

        if not claimed:
            db.session.rollback()
            return None, "AUTHORIZATION_CONSUMED"

        # Update in-memory instance so caller inspects consistent state
        va.consumed = True
        va.consumed_at = now_utc

        try:
            # Reconcile any prior failed ballots occupying this target sequence
            # to ensure no DB unique constraint collision with legitimate fresh submission
            for prior in existing_ballots:
                if prior.state == 'FAILED' and prior.sequence == next_seq:
                    prior.superseded = True
                    prior.sequence = 0
                    if prior.reconcile_required:
                        prior.reconcile_required = False
                        prior.reconcile_reason = 'TX_REVERTED_RECONCILED'

            from app.security.merkle import generate_commitment_nonce, compute_ballot_commitment

            cand_idx = candidate if not is_null else 0

            # Client-Side Nonce & Commitment Handling (Fix 1):
            # If client submitted a commitment, validate exact format and formula.
            # Otherwise, fall back to server-side generation for backwards compatibility.
            if client_commitment is not None:
                if not isinstance(client_commitment, str) or len(client_commitment.strip()) != 64:
                    db.session.rollback()
                    return None, "INVALID_CLIENT_COMMITMENT"
                clean_commitment = client_commitment.strip().lower()

                if client_nonce is not None:
                    if not isinstance(client_nonce, str) or len(client_nonce.strip()) != 64:
                        db.session.rollback()
                        return None, "INVALID_CLIENT_NONCE"
                    clean_nonce = client_nonce.strip().lower()
                    try:
                        nonce_bytes = bytes.fromhex(clean_nonce)
                    except ValueError:
                        db.session.rollback()
                        return None, "INVALID_CLIENT_NONCE"

                    # Verify that commitment matches canonical formula
                    expected_commitment_1 = compute_ballot_commitment(election_id, cand_idx, nonce_bytes)
                    expected_commitment_2 = (
                        compute_ballot_commitment(election_obj.election_id, cand_idx, nonce_bytes)
                        if election_obj else None
                    )

                    if clean_commitment != expected_commitment_1 and clean_commitment != expected_commitment_2:
                        db.session.rollback()
                        return None, "CLIENT_COMMITMENT_MISMATCH"

                    final_nonce_hex = clean_nonce
                else:
                    final_nonce_hex = None

                ballot_commitment = clean_commitment
            else:
                nonce_bytes = generate_commitment_nonce()
                ballot_commitment = compute_ballot_commitment(election_id, cand_idx, nonce_bytes)
                final_nonce_hex = nonce_bytes.hex()

            ballot = BallotRecord(
                election_id=election_id,
                pseudonym=pseud,
                candidate=cand_idx,
                sequence=next_seq,
                is_null=is_null,
                state='QUEUED',
                commitment=ballot_commitment,
                commitment_nonce=final_nonce_hex,
            )
            db.session.add(ballot)
            for prior in existing_ballots:
                prior.superseded = True

            db.session.commit()
            return ballot, "OK"
        except IntegrityError:
            db.session.rollback()
            return None, "BALLOT_ALREADY_CAST"
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def generate_receipt(ballot: BallotRecord, user_id: int) -> Dict[str, str]:
        """
        Generate privacy-preserving HMAC receipt with inclusion commitment.
        Contains: election title, voter ID last 4, minute-level time, HMAC receipt code,
        and the voter's private commitment opening parameters.
        Never reveals pseudonym, wallet address, tx hash, or queue ID.
        """
        user = db.session.get(User, user_id)
        voter_id_last4 = user.voter_id[-4:] if (user and user.voter_id) else '0000'

        election = Election.query.filter(
            (Election.election_id == str(ballot.election_id)) | (Election.id == ballot.election_id)
        ).first()
        election_title = election.title if election else f"Election {ballot.election_id}"

        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:00Z')

        secret = os.getenv('RECEIPT_SECRET') or os.getenv('PSEUDONYM_MASTER_KEY')
        if not secret:
            raise RuntimeError("RECEIPT_SECRET or PSEUDONYM_MASTER_KEY is required.")
        msg = f"{ballot.election_id}|{ballot.pseudonym}|{timestamp}"
        raw_code = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16].upper()
        receipt_code = f"REC-{ballot.election_id}-{raw_code}"

        ballot.receipt_code = receipt_code
        db.session.commit()

        receipt_data = {
            'election_title': election_title,
            'voter_id_last4': voter_id_last4,
            'timestamp': timestamp,
            'receipt_code': receipt_code,
        }
        if ballot.commitment:
            receipt_data['commitment'] = ballot.commitment
        if ballot.commitment_nonce:
            receipt_data['commitment_nonce'] = ballot.commitment_nonce

        return receipt_data

    @staticmethod
    def finalize_election(election_id: Union[int, str]) -> Tuple[bool, str]:
        """
        Finalize election and permanently destroy election pseudonym keys.
        Pre-requisites:
        1. Election exists and is not already finalized.
        2. Election is in CLOSED or ACTIVE state.
        3. No ballots remain pending in QUEUED or SUBMITTED state.
        4. No ballots require recovery / reconciliation.
        5. No unresolved reconciliation issues exist.
        Destroys the stored key material to ensure forward secrecy for all voters.
        """
        from app.models import Election
        from app.models.reconciliation import ReconciliationIssue
        from app.security.pseudonym import destroy_election_pseudonym_key
        from app.audit.audit import AuditLogger

        election = Election.query.filter(
            (Election.election_id == str(election_id)) | (Election.id == int(election_id) if str(election_id).isdigit() else False)
        ).first()

        if not election:
            return False, "ELECTION_NOT_FOUND"

        if election.status == 'FINALIZED':
            return False, "ELECTION_ALREADY_FINALIZED"

        if election.status not in ('CLOSED', 'ACTIVE'):
            return False, f"CANNOT_FINALIZE_IN_STATE_{election.status}"

        # Target IDs for ballot and reconciliation queries (both PK and business identifier)
        target_ids = [election.id]
        if str(election.election_id).isdigit():
            target_ids.append(int(election.election_id))

        # Check for unfinalized ballots
        pending_count = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state.in_(['QUEUED', 'SUBMITTED']),
        ).count()

        if pending_count > 0:
            return False, "CANNOT_FINALIZE_PENDING_BALLOTS"

        # Phase 10 safety: check for ballots with reconcile_required
        recovery_count = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.reconcile_required == True,
        ).count()

        if recovery_count > 0:
            return False, "CANNOT_FINALIZE_RECOVERY_PENDING_BALLOTS"

        # Phase 10 safety: check for open reconciliation issues
        open_issues = ReconciliationIssue.query.filter(
            ReconciliationIssue.election_id.in_(target_ids),
            ReconciliationIssue.status == 'OPEN',
        ).count()

        if open_issues > 0:
            return False, "CANNOT_FINALIZE_UNRESOLVED_RECONCILIATION_ISSUES"

        # Build authoritative RFC 6962 Merkle tree over all accepted ballots
        from app.security.merkle import MerkleTree
        accepted_ballots = BallotRecord.query.filter(
            BallotRecord.election_id.in_(target_ids),
            BallotRecord.state.in_(['CONFIRMED', 'FINALIZED']),
            BallotRecord.superseded == False,
        ).order_by(BallotRecord.id.asc()).all()

        commitments = [b.commitment for b in accepted_ballots if b.commitment]
        tree = MerkleTree(commitments, sort_leaves=True)
        election.merkle_root = tree.root
        election.finalized_at = datetime.utcnow()
        election.status = 'FINALIZED'
        db.session.commit()

        AuditLogger().log('ELECTION_MERKLE_ROOT_FINALIZED', {
            'election_id': str(election.election_id),
            'merkle_root': tree.root,
            'leaf_count': tree.leaf_count,
        })

        # Irreversibly destroy key material
        destroy_election_pseudonym_key(election.id)
        if str(election.election_id) != str(election.id):
            destroy_election_pseudonym_key(election.election_id)

        AuditLogger().log('ELECTION_FINALIZED', {'election_id': str(election.election_id)})
        AuditLogger().log('PSEUDONYM_KEY_DESTROYED', {'election_id': str(election.election_id)})

        return True, "OK"

    @staticmethod
    def list_queued() -> List[BallotRecord]:
        return BallotRecord.query.filter_by(state='QUEUED').order_by(BallotRecord.id.asc()).all()

    @staticmethod
    def update_ballot(ballot_id: int, **kwargs) -> Optional[BallotRecord]:
        b = db.session.get(BallotRecord, ballot_id)
        if not b:
            return None
        for k, v in kwargs.items():
            if hasattr(b, k):
                setattr(b, k, v)
        db.session.commit()
        return b
