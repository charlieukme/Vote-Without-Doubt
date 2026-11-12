"""
Challenge Lease Service - Phase C.11I (Isolated Service Adapter)

Coordinates two-phase lease acquisition, ownership validation, and resolution
for face verification challenges to enable safe infrastructure-failure retries
without burning student attempts or overloading VotingService.consumed.

Key Invariants:
1. Strict State Segregation:
   - Does NOT touch or overload `FaceChallenge.consumed`.
   - `FaceChallenge.consumed` is reserved exclusively for VotingService ballot authorization.
2. Opaque Lease Ownership:
   - Every lease acquisition issues an opaque, cryptographically random `lease_token`.
   - Release and resolution strictly require the matching `lease_token`.
   - Stale or delayed requests cannot release or overwrite a newer lease.
3. Atomic Conditional Execution:
   - All state transitions use conditional updates checking `rowcount == 1`.
   - Zero database transactions or connection locks are held during inference.
4. Fail-Closed Boundaries:
   - Expired challenges (now > expires_at) cannot be leased or resolved as success.
   - Max attempt limits (attempt_count >= max_attempts) are strictly enforced.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging
import secrets
from typing import Optional, Tuple

from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.face import FaceChallenge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and Typed Results
# ---------------------------------------------------------------------------

class LeaseState(str, Enum):
    """Categorized lifecycle state of a FaceChallenge."""
    AVAILABLE = "available"
    IN_FLIGHT_LEASED = "in_flight_leased"
    SUCCESS_UNCONSUMED = "success_unconsumed"
    CONSUMED_VOTED = "consumed_voted"
    REJECTED_BURNED = "rejected_burned"
    EXPIRED = "expired"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ChallengeLeaseResult:
    """Result of an atomic lease acquisition attempt."""
    acquired: bool
    challenge_id: str
    lease_token: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    attempt_count: int = 0
    max_attempts: int = 3
    reason: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class LeaseReleaseResult:
    """Result of releasing a lease due to infrastructure failure."""
    released: bool
    challenge_id: str
    reason: Optional[str] = None


@dataclass(frozen=True)
class LeaseResolutionResult:
    """Result of resolving a lease to final biometric outcome."""
    resolved: bool
    challenge_id: str
    outcome: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Challenge Lease Service
# ---------------------------------------------------------------------------

class ChallengeLeaseService:
    """
    Isolated service for two-phase challenge lease management.
    """

    DEFAULT_LEASE_DURATION_SECONDS = 5.0

    @classmethod
    def acquire_lease(
        cls,
        challenge_id: str,
        lease_duration_seconds: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> ChallengeLeaseResult:
        """
        Atomically acquires a timed lease on an available FaceChallenge.

        Requirements for acquisition:
        - Challenge exists.
        - completed is False.
        - consumed is False.
        - attempt_count < max_attempts.
        - expires_at > now (challenge unexpired).
        - lease_token IS NULL OR lease_expires_at <= now (unleased or previous lease expired).

        Returns:
            ChallengeLeaseResult indicating acquisition status and owner token.
        """
        if not challenge_id or not isinstance(challenge_id, str):
            return ChallengeLeaseResult(
                acquired=False, challenge_id=str(challenge_id), reason="invalid_challenge_id"
            )

        if lease_duration_seconds is None:
            try:
                from flask import current_app
                lease_duration_seconds = float(
                    current_app.config.get('FACE_LEASE_DURATION_SECONDS', cls.DEFAULT_LEASE_DURATION_SECONDS)
                )
            except Exception:
                lease_duration_seconds = cls.DEFAULT_LEASE_DURATION_SECONDS

        now = now or datetime.utcnow()
        lease_expires_at = now + timedelta(seconds=max(0.1, float(lease_duration_seconds)))
        lease_token = secrets.token_hex(32)

        try:
            stmt = (
                update(FaceChallenge)
                .where(
                    FaceChallenge.challenge_id == challenge_id,
                    FaceChallenge.completed.is_(False),
                    FaceChallenge.consumed.is_(False),
                    FaceChallenge.attempt_count < FaceChallenge.max_attempts,
                    FaceChallenge.expires_at > now,
                    or_(
                        FaceChallenge.lease_token.is_(None),
                        FaceChallenge.lease_expires_at <= now,
                    ),
                )
                .values(
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                    attempt_count=FaceChallenge.attempt_count + 1,
                )
            )

            res = db.session.execute(stmt)
            if res.rowcount == 1:
                db.session.commit()
                # Query updated count for telemetry
                row = db.session.execute(
                    select(FaceChallenge.attempt_count, FaceChallenge.max_attempts)
                    .where(FaceChallenge.challenge_id == challenge_id)
                ).first()
                att = row[0] if row else 1
                max_att = row[1] if row else 3
                return ChallengeLeaseResult(
                    acquired=True,
                    challenge_id=challenge_id,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                    attempt_count=att,
                    max_attempts=max_att,
                )

            # rowcount == 0: Acquisition failed
            db.session.rollback()
            state, ch = cls.get_challenge_state(challenge_id, now=now)
            reason = f"lease_unavailable_{state.value}"
            return ChallengeLeaseResult(
                acquired=False,
                challenge_id=challenge_id,
                attempt_count=ch.attempt_count if ch else 0,
                max_attempts=ch.max_attempts if ch else 3,
                reason=reason,
            )

        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.error("Database error during lease acquisition for %s: %s", challenge_id, exc)
            return ChallengeLeaseResult(
                acquired=False,
                challenge_id=challenge_id,
                reason="database_error",
                error=str(exc),
            )

    @classmethod
    def release_lease_on_infrastructure_failure(
        cls,
        challenge_id: str,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> LeaseReleaseResult:
        """
        Releases an in-flight lease when a transient infrastructure fault occurs.
        Decrements attempt_count so the voter is not penalized for backend errors.

        Strict Ownership Guard:
        - Only updates if lease_token matches the caller's token.
        - Stale or mismatched cleanups safely no-op (rowcount == 0).
        """
        if not challenge_id or not lease_token:
            return LeaseReleaseResult(
                released=False, challenge_id=str(challenge_id), reason="invalid_arguments"
            )

        now = now or datetime.utcnow()

        try:
            stmt = (
                update(FaceChallenge)
                .where(
                    FaceChallenge.challenge_id == challenge_id,
                    FaceChallenge.lease_token == lease_token,
                    FaceChallenge.completed.is_(False),
                )
                .values(
                    lease_token=None,
                    lease_expires_at=None,
                    attempt_count=case(
                        (FaceChallenge.attempt_count > 0, FaceChallenge.attempt_count - 1),
                        else_=0,
                    ),
                )
            )

            res = db.session.execute(stmt)
            if res.rowcount == 1:
                db.session.commit()
                return LeaseReleaseResult(released=True, challenge_id=challenge_id)

            db.session.rollback()
            return LeaseReleaseResult(
                released=False,
                challenge_id=challenge_id,
                reason="stale_or_invalid_lease_token",
            )

        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.error("Database error releasing lease for %s: %s", challenge_id, exc)
            return LeaseReleaseResult(
                released=False, challenge_id=challenge_id, reason=f"database_error: {exc}"
            )

    @classmethod
    def resolve_lease_biometric_success(
        cls,
        challenge_id: str,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> LeaseResolutionResult:
        """
        Resolves an in-flight lease to SUCCESS.

        Invariants:
        - Sets completed=True, success=True, completed_at=now.
        - Clears lease_token and lease_expires_at.
        - Crucially leaves consumed=False so VotingService can authorize ballot casting.
        - Strictly verifies lease_token and unexpired challenge.
        """
        if not challenge_id or not lease_token:
            return LeaseResolutionResult(
                resolved=False, challenge_id=str(challenge_id), reason="invalid_arguments"
            )

        now = now or datetime.utcnow()

        try:
            stmt = (
                update(FaceChallenge)
                .where(
                    FaceChallenge.challenge_id == challenge_id,
                    FaceChallenge.lease_token == lease_token,
                    FaceChallenge.completed.is_(False),
                    FaceChallenge.expires_at > now,
                )
                .values(
                    completed=True,
                    success=True,
                    completed_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )

            res = db.session.execute(stmt)
            if res.rowcount == 1:
                db.session.commit()
                return LeaseResolutionResult(
                    resolved=True, challenge_id=challenge_id, outcome="success"
                )

            db.session.rollback()
            return LeaseResolutionResult(
                resolved=False,
                challenge_id=challenge_id,
                reason="stale_token_or_expired_challenge",
            )

        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.error("Database error resolving success for %s: %s", challenge_id, exc)
            return LeaseResolutionResult(
                resolved=False, challenge_id=challenge_id, reason=f"database_error: {exc}"
            )

    @classmethod
    def resolve_lease_biometric_rejection(
        cls,
        challenge_id: str,
        lease_token: str,
        now: Optional[datetime] = None,
    ) -> LeaseResolutionResult:
        """
        Resolves an in-flight lease to REJECTED (Biometric Failure or Malformed Frame).

        Invariants:
        - Sets completed=True, success=False, completed_at=now.
        - Clears lease_token and lease_expires_at.
        - Challenge is permanently burned; attempt_count is NOT refunded.
        - Strictly verifies lease_token.
        """
        if not challenge_id or not lease_token:
            return LeaseResolutionResult(
                resolved=False, challenge_id=str(challenge_id), reason="invalid_arguments"
            )

        now = now or datetime.utcnow()

        try:
            stmt = (
                update(FaceChallenge)
                .where(
                    FaceChallenge.challenge_id == challenge_id,
                    FaceChallenge.lease_token == lease_token,
                    FaceChallenge.completed.is_(False),
                )
                .values(
                    completed=True,
                    success=False,
                    completed_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )

            res = db.session.execute(stmt)
            if res.rowcount == 1:
                db.session.commit()
                return LeaseResolutionResult(
                    resolved=True, challenge_id=challenge_id, outcome="rejected"
                )

            db.session.rollback()
            return LeaseResolutionResult(
                resolved=False,
                challenge_id=challenge_id,
                reason="stale_or_invalid_lease_token",
            )

        except SQLAlchemyError as exc:
            db.session.rollback()
            logger.error("Database error resolving rejection for %s: %s", challenge_id, exc)
            return LeaseResolutionResult(
                resolved=False, challenge_id=challenge_id, reason=f"database_error: {exc}"
            )

    @classmethod
    def get_challenge_state(
        cls,
        challenge_id: str,
        now: Optional[datetime] = None,
    ) -> Tuple[LeaseState, Optional[FaceChallenge]]:
        """
        Diagnoses the comprehensive lifecycle state of a FaceChallenge.
        """
        now = now or datetime.utcnow()
        ch = db.session.execute(
            select(FaceChallenge).where(FaceChallenge.challenge_id == challenge_id)
        ).scalar_one_or_none()

        if ch is None:
            return LeaseState.NOT_FOUND, None

        if ch.consumed:
            return LeaseState.CONSUMED_VOTED, ch

        if ch.completed:
            if ch.success:
                return LeaseState.SUCCESS_UNCONSUMED, ch
            return LeaseState.REJECTED_BURNED, ch

        if now >= ch.expires_at:
            return LeaseState.EXPIRED, ch

        if ch.attempt_count >= ch.max_attempts:
            return LeaseState.ATTEMPTS_EXHAUSTED, ch

        if ch.lease_token is not None and ch.lease_expires_at and ch.lease_expires_at > now:
            return LeaseState.IN_FLIGHT_LEASED, ch

        return LeaseState.AVAILABLE, ch
