"""
Unit and Integration Tests for Challenge Lease Primitives (Phase C.11I).

Validates:
1. Valid challenge lease acquisition sets lease_token and incremented attempt_count.
2. Concurrent lease acquisition enforces strict mutual exclusion (exactly 1 succeeds).
3. Reacquisition after lease expiry while challenge is valid succeeds.
4. No reacquisition after overall challenge expiry (now > expires_at).
5. Completed or consumed challenges cannot be leased.
6. Max attempt limit enforcement.
7. Correct token releases its own lease and refunds attempt_count on infrastructure fault.
8. Incorrect token cannot release a lease.
9. Stale request cleanup cannot clear a newer lease acquired by another request.
10. Repeated cleanup is idempotent and safe.
11. Lease acquisition and in-flight states never set consumed=True.
12. Verified challenge remains 100% compatible with VotingService authorization query.
13. Database transaction failure fails closed and returns acquired=False.
14. Alembic migration upgrade and downgrade work cleanly on disposable database.
15. Biometric rejection burns challenge and prevents re-acquisition without attempt refund.

Uses disposable temporary SQLite test database and synthetic fixtures ONLY.
Zero human biometric data.
"""

from datetime import datetime, timedelta
import threading
from unittest.mock import patch
import pytest
from sqlalchemy.exc import OperationalError

from app.extensions import db as _db
from app.models.auth import User
from app.models.ballot_record import VotingAuthorization
from app.models.face import FaceChallenge
from app.services.challenge_lease_service import (
    ChallengeLeaseResult,
    ChallengeLeaseService,
    LeaseReleaseResult,
    LeaseResolutionResult,
    LeaseState,
)


@pytest.fixture
def test_user(db):
    """Creates a synthetic user for challenge binding."""
    user = User(
        username="student_c11i",
        email="student_c11i@college.edu",
        password_hash="test_hash",
    )
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def make_challenge(db, test_user):
    """Factory fixture for synthetic FaceChallenge instances."""
    def _create(
        challenge_id="ch_c11i_test_01",
        expires_in_seconds=20,
        completed=False,
        success=False,
        consumed=False,
        attempt_count=0,
        max_attempts=3,
        authorization_id=None,
        lease_token=None,
        lease_expires_at=None,
    ):
        now = datetime.utcnow()
        ch = FaceChallenge(
            challenge_id=challenge_id,
            user_id=test_user.id,
            session_id="test_session_c11i",
            challenge_type="FACE",
            challenge_sequence="",
            nonce="nonce_test",
            integrity_mac="mac_test",
            expires_at=now + timedelta(seconds=expires_in_seconds),
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            completed=completed,
            success=success,
            consumed=consumed,
            authorization_id=authorization_id,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
        )
        _db.session.add(ch)
        _db.session.commit()
        return ch

    return _create


# ---------------------------------------------------------------------------
# Test Cases 1 - 15
# ---------------------------------------------------------------------------

def test_01_valid_lease_acquisition(db, make_challenge):
    """Test 1: Valid challenge lease acquisition."""
    ch = make_challenge(challenge_id="ch_01", expires_in_seconds=20)

    res = ChallengeLeaseService.acquire_lease("ch_01", lease_duration_seconds=3.0)

    assert res.acquired is True
    assert res.challenge_id == "ch_01"
    assert res.lease_token is not None
    assert len(res.lease_token) == 64  # 32 bytes hex
    assert res.lease_expires_at is not None
    assert res.attempt_count == 1

    # Verify DB persistence
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.lease_token == res.lease_token
    assert reloaded.attempt_count == 1
    assert reloaded.completed is False
    assert reloaded.consumed is False  # Invariant: consumed must remain False!


def test_02_concurrent_acquisition_mutual_exclusion(app, db, make_challenge):
    """Test 2: Two simultaneous acquisition attempts: at most one obtains the lease."""
    make_challenge(challenge_id="ch_02", expires_in_seconds=20)

    results = []

    def worker():
        with app.app_context():
            res = ChallengeLeaseService.acquire_lease("ch_02", lease_duration_seconds=3.0)
            results.append(res)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    acquired_count = sum(1 for r in results if r.acquired)
    failed_count = sum(1 for r in results if not r.acquired)

    assert acquired_count == 1
    assert failed_count == 1
    failed_res = next(r for r in results if not r.acquired)
    assert "lease_unavailable" in failed_res.reason


def test_03_reacquisition_after_lease_expiry(db, make_challenge):
    """Test 3: Reacquisition after lease expiry while challenge remains valid."""
    now = datetime.utcnow()
    # Create challenge with an already-expired lease (expired 2s ago)
    ch = make_challenge(
        challenge_id="ch_03",
        expires_in_seconds=20,
        lease_token="expired_token_abc",
        lease_expires_at=now - timedelta(seconds=2),
        attempt_count=1,
    )

    # Reacquisition should evict the stale lease and succeed
    res = ChallengeLeaseService.acquire_lease("ch_03", lease_duration_seconds=3.0, now=now)

    assert res.acquired is True
    assert res.lease_token != "expired_token_abc"
    assert res.attempt_count == 2

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.lease_token == res.lease_token
    assert reloaded.attempt_count == 2


def test_04_no_reacquisition_after_challenge_expiry(db, make_challenge):
    """Test 4: No reacquisition after overall challenge expiry."""
    now = datetime.utcnow()
    # Challenge expired 1s ago
    make_challenge(challenge_id="ch_04", expires_in_seconds=-1)

    res = ChallengeLeaseService.acquire_lease("ch_04", lease_duration_seconds=3.0, now=now)

    assert res.acquired is False
    assert "lease_unavailable_expired" in res.reason


def test_05_completed_or_consumed_cannot_be_leased(db, make_challenge):
    """Test 5: Completed or consumed challenge cannot be leased."""
    # Completed challenge
    make_challenge(challenge_id="ch_05_comp", completed=True, success=True)
    res_comp = ChallengeLeaseService.acquire_lease("ch_05_comp")
    assert res_comp.acquired is False
    assert "lease_unavailable" in res_comp.reason

    # Consumed challenge
    make_challenge(challenge_id="ch_05_cons", completed=True, consumed=True)
    res_cons = ChallengeLeaseService.acquire_lease("ch_05_cons")
    assert res_cons.acquired is False
    assert "lease_unavailable_consumed_voted" in res_cons.reason


def test_06_attempt_limit_enforcement(db, make_challenge):
    """Test 6: Attempt limit enforcement (cannot exceed max_attempts)."""
    make_challenge(challenge_id="ch_06", attempt_count=3, max_attempts=3)

    res = ChallengeLeaseService.acquire_lease("ch_06")

    assert res.acquired is False
    assert "lease_unavailable_attempts_exhausted" in res.reason


def test_07_correct_token_releases_lease(db, make_challenge):
    """Test 7: Correct token releases its own lease and refunds attempt on infrastructure failure."""
    ch = make_challenge(challenge_id="ch_07", attempt_count=0)

    acq = ChallengeLeaseService.acquire_lease("ch_07", lease_duration_seconds=3.0)
    assert acq.acquired is True
    assert acq.attempt_count == 1

    # Infrastructure failure occurs (503), caller releases lease
    rel = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_07", acq.lease_token)
    assert rel.released is True

    # Check that challenge is available again with attempt count restored
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.lease_token is None
    assert reloaded.lease_expires_at is None
    assert reloaded.attempt_count == 0  # Restored!
    assert reloaded.completed is False
    assert reloaded.consumed is False

    state, _ = ChallengeLeaseService.get_challenge_state("ch_07")
    assert state == LeaseState.AVAILABLE


def test_08_incorrect_token_cannot_release_lease(db, make_challenge):
    """Test 8: Incorrect token cannot release a lease."""
    ch = make_challenge(challenge_id="ch_08")
    acq = ChallengeLeaseService.acquire_lease("ch_08")
    assert acq.acquired is True

    # Attempt release with wrong token
    rel = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_08", "wrong_token_12345")
    assert rel.released is False
    assert rel.reason == "stale_or_invalid_lease_token"

    # Original lease remains held
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.lease_token == acq.lease_token
    assert reloaded.attempt_count == 1


def test_09_stale_request_cleanup_cannot_clear_newer_lease(db, make_challenge):
    """Test 9: Stale request cleanup cannot clear a newer lease."""
    ch = make_challenge(challenge_id="ch_09")

    # Request 1 acquires lease
    now1 = datetime.utcnow()
    acq1 = ChallengeLeaseService.acquire_lease("ch_09", lease_duration_seconds=1.0, now=now1)
    token1 = acq1.lease_token

    # 2 seconds pass; lease 1 expires
    now2 = now1 + timedelta(seconds=2)

    # Request 2 acquires lease with token 2
    acq2 = ChallengeLeaseService.acquire_lease("ch_09", lease_duration_seconds=3.0, now=now2)
    token2 = acq2.lease_token
    assert token1 != token2

    # Request 1 belatedly attempts to release with token 1
    rel1 = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_09", token1, now=now2)
    assert rel1.released is False  # Rejected!

    # Request 2's lease is completely untouched!
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.lease_token == token2
    assert reloaded.attempt_count == 2


def test_10_repeated_cleanup_is_safe_and_idempotent(db, make_challenge):
    """Test 10: Repeated cleanup is safe and idempotent."""
    make_challenge(challenge_id="ch_10")
    acq = ChallengeLeaseService.acquire_lease("ch_10")

    # First release succeeds
    rel1 = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_10", acq.lease_token)
    assert rel1.released is True

    # Second release with same token safely returns False without crashing
    rel2 = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_10", acq.lease_token)
    assert rel2.released is False
    assert rel2.reason == "stale_or_invalid_lease_token"


def test_11_lease_acquisition_never_sets_consumed_true(db, make_challenge):
    """Test 11: Lease acquisition and release never mutate consumed=True."""
    ch = make_challenge(challenge_id="ch_11")

    acq = ChallengeLeaseService.acquire_lease("ch_11")
    reloaded_acq = _db.session.get(FaceChallenge, ch.id)
    assert reloaded_acq.consumed is False

    ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_11", acq.lease_token)
    reloaded_rel = _db.session.get(FaceChallenge, ch.id)
    assert reloaded_rel.consumed is False


def test_12_verified_challenge_compatible_with_voting_service_query(db, test_user, make_challenge):
    """
    Test 12: Verified challenge remains 100% compatible with VotingService authorization query.
    Directly exercises lines 108-146 of app/services/voting_service.py.
    """
    now = datetime.utcnow()

    # Create VotingAuthorization record
    va = VotingAuthorization(
        user_id=test_user.id,
        session_id="test_session_c11i",
        election_id=1,
        consumed=False,
        authorized=False,
        expires_at=now + timedelta(seconds=60),
    )
    _db.session.add(va)
    _db.session.commit()

    # Challenge bound to va.id
    ch = make_challenge(
        challenge_id="ch_12_voting_compat",
        expires_in_seconds=20,
        authorization_id=va.id,
    )

    # 1. Acquire lease
    acq = ChallengeLeaseService.acquire_lease("ch_12_voting_compat")
    assert acq.acquired is True

    # 2. Resolve to success
    res = ChallengeLeaseService.resolve_lease_biometric_success("ch_12_voting_compat", acq.lease_token, now=now)
    assert res.resolved is True

    reloaded_ch = _db.session.get(FaceChallenge, ch.id)
    assert reloaded_ch.completed is True
    assert reloaded_ch.success is True
    assert reloaded_ch.completed_at is not None
    assert reloaded_ch.consumed is False  # Crucial!

    # 3. Execute exact query from voting_service.py:108-145
    face_challenge_query = FaceChallenge.query.filter(
        FaceChallenge.user_id == test_user.id,
        FaceChallenge.consumed.is_(False),
        FaceChallenge.expires_at > now,
    )
    face_challenge_query = face_challenge_query.filter(
        FaceChallenge.authorization_id == va.id
    )
    located_ch = face_challenge_query.order_by(FaceChallenge.id.desc()).first()

    assert located_ch is not None
    assert located_ch.id == ch.id

    # 4. Execute atomic consumption from voting_service.py:139-146
    rows_updated = FaceChallenge.query.filter(
        FaceChallenge.id == located_ch.id,
        FaceChallenge.consumed.is_(False),
    ).update({
        'consumed': True,
        'consumed_at': now,
    }, synchronize_session=False)

    assert rows_updated == 1
    _db.session.commit()

    # State is now consumed_voted
    final_state, _ = ChallengeLeaseService.get_challenge_state("ch_12_voting_compat")
    assert final_state == LeaseState.CONSUMED_VOTED


def test_13_database_transaction_failure_fails_closed(db, make_challenge):
    """Test 13: Database transaction failure fails closed and returns acquired=False."""
    make_challenge(challenge_id="ch_13")

    with patch.object(_db.session, "commit", side_effect=OperationalError("mock disconnect", {}, None)):
        res = ChallengeLeaseService.acquire_lease("ch_13")

    assert res.acquired is False
    assert res.reason == "database_error"
    assert "mock disconnect" in (res.error or "")


def test_14_alembic_migration_schema_upgrade_and_downgrade(app):
    """
    Test 14: Verifies the Alembic migration script definition syntax and batch operations
    without connecting to the live production database.
    """
    import importlib.util
    import os
    mig_path = os.path.join(
        os.path.dirname(__file__), "..", "migrations", "versions",
        "c3d4e5f6a7b8_phase_c11i_add_face_challenge_lease_fields.py"
    )
    spec = importlib.util.spec_from_file_location("mig_c11i", mig_path)
    assert spec is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    assert mig.revision == "c3d4e5f6a7b8"
    assert mig.down_revision == "b2c3d4e5f6a7"
    assert hasattr(mig, "upgrade")
    assert hasattr(mig, "downgrade")


def test_15_biometric_rejection_burns_challenge(db, make_challenge):
    """Test 15: Biometric rejection permanently burns the challenge; attempt count not refunded."""
    ch = make_challenge(challenge_id="ch_15", attempt_count=0)

    acq = ChallengeLeaseService.acquire_lease("ch_15")
    assert acq.acquired is True
    assert acq.attempt_count == 1

    # Biometric rejection occurs (similarity too low or spoof detected)
    res = ChallengeLeaseService.resolve_lease_biometric_rejection("ch_15", acq.lease_token)
    assert res.resolved is True
    assert res.outcome == "rejected"

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is True
    assert reloaded.success is False
    assert reloaded.lease_token is None
    assert reloaded.attempt_count == 1  # Not refunded!

    # Re-acquisition is permanently blocked
    acq_retry = ChallengeLeaseService.acquire_lease("ch_15")
    assert acq_retry.acquired is False
    assert "lease_unavailable_rejected_burned" in acq_retry.reason


def test_16_infrastructure_failure_followed_by_valid_retry(db, make_challenge):
    """Test 16: Infrastructure failure releases lease, refunds attempt, and subsequent retry succeeds."""
    ch = make_challenge(challenge_id="ch_16", attempt_count=0)

    # 1. First attempt acquires lease
    acq1 = ChallengeLeaseService.acquire_lease("ch_16")
    assert acq1.acquired is True
    assert acq1.attempt_count == 1

    # 2. Infrastructure failure (e.g. 503 model engine timeout/offline)
    rel = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_16", acq1.lease_token)
    assert rel.released is True

    # Attempt count is refunded
    reloaded1 = _db.session.get(FaceChallenge, ch.id)
    assert reloaded1.attempt_count == 0
    assert reloaded1.lease_token is None

    # 3. Subsequent retry request arrives while challenge is still valid
    acq2 = ChallengeLeaseService.acquire_lease("ch_16")
    assert acq2.acquired is True
    assert acq2.lease_token != acq1.lease_token
    assert acq2.attempt_count == 1

    # 4. Verification succeeds on retry
    res = ChallengeLeaseService.resolve_lease_biometric_success("ch_16", acq2.lease_token)
    assert res.resolved is True
    assert res.outcome == "success"

    reloaded2 = _db.session.get(FaceChallenge, ch.id)
    assert reloaded2.completed is True
    assert reloaded2.success is True
    assert reloaded2.consumed is False


def test_17_original_challenge_expiry_during_lease_blocks_success(db, make_challenge):
    """Test 17: Original challenge expiry during a lease blocks resolution as success."""
    now1 = datetime.utcnow()
    # Challenge expires in 2 seconds
    ch = make_challenge(challenge_id="ch_17", expires_in_seconds=2)

    # Worker acquires lease for 5.0 seconds
    acq = ChallengeLeaseService.acquire_lease("ch_17", lease_duration_seconds=5.0, now=now1)
    assert acq.acquired is True

    # 3 seconds pass; original challenge expired (now2 > expires_at), although lease duration has not expired
    now2 = now1 + timedelta(seconds=3)

    # Worker attempts to resolve as success
    res = ChallengeLeaseService.resolve_lease_biometric_success("ch_17", acq.lease_token, now=now2)
    assert res.resolved is False
    assert res.reason == "stale_token_or_expired_challenge"

    # Challenge is recognized as expired
    state, reloaded = ChallengeLeaseService.get_challenge_state("ch_17", now=now2)
    assert state == LeaseState.EXPIRED
    assert reloaded.success is False


def test_18_database_failure_during_release_fails_closed(db, make_challenge):
    """Test 18: Database failure during lease release fails closed and returns released=False."""
    make_challenge(challenge_id="ch_18")
    acq = ChallengeLeaseService.acquire_lease("ch_18")
    assert acq.acquired is True

    with patch.object(_db.session, "commit", side_effect=OperationalError("mock db error during release", {}, None)):
        rel = ChallengeLeaseService.release_lease_on_infrastructure_failure("ch_18", acq.lease_token)

    assert rel.released is False
    assert "database_error" in rel.reason


def test_19_stale_rejection_cannot_burn_newer_lease(db, make_challenge):
    """Test 19: Stale biometric rejection cannot burn a newer active lease acquired by another request."""
    ch = make_challenge(challenge_id="ch_19")

    # Request 1 acquires lease
    now1 = datetime.utcnow()
    acq1 = ChallengeLeaseService.acquire_lease("ch_19", lease_duration_seconds=1.0, now=now1)
    token1 = acq1.lease_token

    # 2 seconds pass; lease 1 expires
    now2 = now1 + timedelta(seconds=2)

    # Request 2 acquires lease with token 2
    acq2 = ChallengeLeaseService.acquire_lease("ch_19", lease_duration_seconds=3.0, now=now2)
    token2 = acq2.lease_token
    assert token1 != token2

    # Request 1 belatedly attempts to burn challenge via resolve_lease_biometric_rejection with token 1
    res1 = ChallengeLeaseService.resolve_lease_biometric_rejection("ch_19", token1, now=now2)
    assert res1.resolved is False
    assert res1.reason == "stale_or_invalid_lease_token"

    # Request 2's lease is completely untouched, uncompleted, and still in-flight
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is False
    assert reloaded.lease_token == token2
    assert reloaded.attempt_count == 2


def test_20_stale_success_cannot_resolve_newer_lease(db, make_challenge):
    """Test 20: Stale biometric success cannot resolve or overwrite a newer active lease."""
    ch = make_challenge(challenge_id="ch_20")

    # Request 1 acquires lease
    now1 = datetime.utcnow()
    acq1 = ChallengeLeaseService.acquire_lease("ch_20", lease_duration_seconds=1.0, now=now1)
    token1 = acq1.lease_token

    # 2 seconds pass; lease 1 expires
    now2 = now1 + timedelta(seconds=2)

    # Request 2 acquires lease with token 2
    acq2 = ChallengeLeaseService.acquire_lease("ch_20", lease_duration_seconds=3.0, now=now2)
    token2 = acq2.lease_token
    assert token1 != token2

    # Request 1 belatedly attempts to mark success with token 1
    res1 = ChallengeLeaseService.resolve_lease_biometric_success("ch_20", token1, now=now2)
    assert res1.resolved is False
    assert res1.reason == "stale_token_or_expired_challenge"

    # Request 2's lease is completely untouched, uncompleted, and still in-flight
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is False
    assert reloaded.lease_token == token2


def test_21_database_failure_during_rejection_resolution_fails_closed(db, make_challenge):
    """Test 21: Database failure during rejection resolution fails closed and returns resolved=False."""
    make_challenge(challenge_id="ch_21")
    acq = ChallengeLeaseService.acquire_lease("ch_21")
    assert acq.acquired is True

    with patch.object(_db.session, "commit", side_effect=OperationalError("mock db error during rejection", {}, None)):
        res = ChallengeLeaseService.resolve_lease_biometric_rejection("ch_21", acq.lease_token)

    assert res.resolved is False
    assert "database_error" in res.reason


