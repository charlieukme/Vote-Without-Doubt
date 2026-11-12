"""
Integration Tests for Face Challenge Leasing into Real Verification Flow (Phase C.12).

Tests:
1. Successful verification resolves lease, keeps consumed=False, and remains 100% compatible with VotingService.
2. Definitive biometric match rejection burns the challenge attempt and blocks reuse.
3. Invalid/poor-quality frame admission failure burns the challenge attempt.
4. Infrastructure engine failure (503) releases lease, refunds attempt, and permits safe retry.
5. Concurrent verification requests for the same challenge enforce mutual exclusion.
6. Bounded semaphore saturation fails fast with 503, releases lease, and preserves semaphore slots.
7. Challenge expiry during inference fails closed and blocks success resolution.
8. Non-enrolled user verification burns the challenge.
9. Enrollment workflow remains on its non-lease lifecycle.
10. Route-level error handling (/api/face/verify) preserves generic error masks (400 vs 503).

Uses disposable test SQLite databases and synthetic embeddings/fixtures ONLY. Zero human biometric data.
"""

from datetime import datetime, timedelta
import threading
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from app.extensions import db as _db
from app.models import User, AuthSession
from app.models.ballot_record import VotingAuthorization
from app.models.face import FaceChallenge, FaceEnrollment
from app.security.face import (
    active_key_id,
    challenge_mac,
    encrypt_embedding,
    generate_challenge_nonce,
    generate_face_challenge_id,
)
from app.services.challenge_lease_service import ChallengeLeaseService, LeaseState
from app.services.face_engine import (
    FaceEngineError,
    FaceEngineUnavailable,
    PoseEstimate,
    FrameAnalysis,
)
from app.services.face_service import (
    ChallengeError,
    FaceEngineNotReadyError,
    FaceService,
    FrameAdmissionError,
    MatchFailedError,
    NotEnrolledError,
    get_inference_semaphore,
    set_inference_semaphore,
)


@pytest.fixture
def face_service():
    return FaceService()


@pytest.fixture
def synthetic_user(db):
    user = User(
        username="voter_c12",
        email="voter_c12@college.edu",
        password_hash="test_hash_c12",
    )
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def synthetic_session(db, synthetic_user):
    now = datetime.utcnow()
    session = AuthSession(
        user_id=synthetic_user.id,
        session_id="test_session_c12_token",
        auth_state="AUTHORIZED",
        ip_address="127.0.0.1",
        user_agent="pytest-agent",
        authenticated_at=now,
        created_at=now,
        last_activity=now,
        idle_expires_at=now + timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        revoked=False,
    )
    _db.session.add(session)
    _db.session.commit()
    return session


@pytest.fixture
def synthetic_enrollment(db, synthetic_user, monkeypatch):
    """Enrolls a known synthetic 512-d template for the user."""
    monkeypatch.setenv("FACE_ENCRYPTION_KEY", "lnM7afwMMzvIom2qb0f13DjQZSo4pFoRS0ztukO6Ay4=")
    vector = np.ones(512, dtype=np.float32)
    from app.services.face_service import _pack_metadata
    packed = vector.tobytes() + _pack_metadata(active_key_id())
    encrypted = encrypt_embedding(packed)

    enr = FaceEnrollment(
        user_id=synthetic_user.id,
        encrypted_embedding=encrypted,
        embedding_method="arcface_cosine",
        embedding_model="buffalo_l/w600k_r50",
        embedding_dim=512,
        embedding_key_id=active_key_id(),
        is_enrolled=True,
        consent_given=True,
        consent_at=datetime.utcnow(),
    )
    _db.session.add(enr)
    _db.session.commit()
    return vector


def _create_challenge(user_id, session_id, ttl=20, authorization_id=None, election_id=None):
    cid = generate_face_challenge_id()
    nonce = generate_challenge_nonce()
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)
    mac = challenge_mac(cid, user_id, session_id, "", nonce, expires_at.isoformat())

    ch = FaceChallenge(
        challenge_id=cid,
        user_id=user_id,
        session_id=session_id,
        challenge_type="FACE",
        challenge_sequence="",
        nonce=nonce,
        integrity_mac=mac,
        expires_at=expires_at,
        attempt_count=0,
        max_attempts=3,
        completed=False,
        success=False,
        consumed=False,
        authorization_id=authorization_id,
        election_id=election_id,
    )
    _db.session.add(ch)
    _db.session.commit()
    return ch


def _mock_analysis(vector, detector_score=0.95):
    pose = PoseEstimate(yaw=0.0, roll=0.0, interocular_px=60.0)
    return FrameAnalysis(
        width=640,
        height=480,
        face_area_ratio=0.25,
        detector_score=detector_score,
        laplacian_variance=150.0,
        mean_luma=120.0,
        pose=pose,
        embedding=vector,
    )


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_01_successful_verification_resolves_lease_and_preserves_consumed_false(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 1: Successful face verification resolves the lease, keeps consumed=False,
    and remains compatible with the VotingService authorization query.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80

    va = VotingAuthorization(
        user_id=synthetic_user.id,
        session_id=synthetic_session.session_id,
        election_id=1,
        consumed=False,
        authorized=False,
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    _db.session.add(va)
    _db.session.commit()

    ch = _create_challenge(
        synthetic_user.id, synthetic_session.session_id, ttl=20, authorization_id=va.id, election_id=1
    )

    # Mock analyze to return matching enrolled vector
    matching_analysis = _mock_analysis(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
            res = face_service.verify(
                user_id=synthetic_user.id,
                session_id=synthetic_session.session_id,
                challenge_id=ch.challenge_id,
                payloads=[dummy_payload],
            )

    assert res["success"] is True
    assert res["verified"] is True

    # Inspect DB record
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is True
    assert reloaded.success is True
    assert reloaded.completed_at is not None
    assert reloaded.consumed is False  # Must remain unconsumed for VotingService!
    assert reloaded.lease_token is None  # Lease cleared!
    assert reloaded.lease_expires_at is None
    assert reloaded.attempt_count == 1

    # Verify VotingService query directly
    now = datetime.utcnow()
    query = FaceChallenge.query.filter(
        FaceChallenge.user_id == synthetic_user.id,
        FaceChallenge.completed.is_(True),
        FaceChallenge.success.is_(True),
        FaceChallenge.consumed.is_(False),
        FaceChallenge.expires_at > now,
        FaceChallenge.authorization_id == va.id,
    )
    located = query.order_by(FaceChallenge.id.desc()).first()
    assert located is not None
    assert located.id == ch.id


def test_02_biometric_rejection_burns_challenge_attempt(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 2: When facial similarity is below threshold, MatchFailedError is raised,
    and the challenge is permanently burned (completed=True, success=False) with no refund.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)

    # Impostor vector orthogonal to enrolled vector
    impostor_vec = np.zeros(512, dtype=np.float32)
    impostor_vec[0] = 1.0  # Cosine similarity will be very low
    impostor_analysis = _mock_analysis(impostor_vec)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", return_value=[impostor_analysis]):
            with pytest.raises(MatchFailedError):
                face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is True
    assert reloaded.success is False
    assert reloaded.lease_token is None
    assert reloaded.attempt_count == 1  # Not refunded!

    # Re-use attempt is rejected
    with pytest.raises(ChallengeError) as exc_info:
        face_service.verify(
            user_id=synthetic_user.id,
            session_id=synthetic_session.session_id,
            challenge_id=ch.challenge_id,
            payloads=[dummy_payload],
        )
    assert "already been used" in str(exc_info.value)


def test_03_invalid_frame_admission_burns_challenge(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 3: Defective frame quality or frame count rejection burns the challenge attempt.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    with patch.object(FaceService, "_admit_frames", side_effect=FrameAdmissionError("Too many frames")):
        with pytest.raises(FrameAdmissionError):
            face_service.verify(
                user_id=synthetic_user.id,
                session_id=synthetic_session.session_id,
                challenge_id=ch.challenge_id,
                payloads=[dummy_payload],
            )

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is True
    assert reloaded.success is False
    assert reloaded.attempt_count == 1


def test_04_inference_engine_unavailable_releases_lease_and_allows_retry(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 4: Transient infrastructure failure (FaceEngineUnavailable / 503) releases lease,
    refunds attempt_count, and allows the genuine student to retry.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    # Attempt 1: Engine unavailable
    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", side_effect=FaceEngineUnavailable("GPU out of memory")):
            with pytest.raises(FaceEngineNotReadyError):
                face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )

    # Verify attempt was refunded and challenge remains available
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is False
    assert reloaded.lease_token is None
    assert reloaded.attempt_count == 0  # Refunded!

    # Attempt 2: Engine restored -> verification succeeds with same challenge!
    matching_analysis = _mock_analysis(synthetic_enrollment)
    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
            res = face_service.verify(
                user_id=synthetic_user.id,
                session_id=synthetic_session.session_id,
                challenge_id=ch.challenge_id,
                payloads=[dummy_payload],
            )

    assert res["verified"] is True
    reloaded2 = _db.session.get(FaceChallenge, ch.id)
    assert reloaded2.completed is True
    assert reloaded2.success is True
    assert reloaded2.attempt_count == 1


def test_05_concurrent_verification_mutual_exclusion(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 5: Two simultaneous verification requests for the same challenge enforce mutual exclusion.
    At most one acquires the lease and processes inference.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    results = []
    errors = []

    # Slow down analyze to ensure overlap
    def slow_analyze(*args, **kwargs):
        import time
        time.sleep(0.1)
        return [_mock_analysis(synthetic_enrollment)]

    def worker():
        with app.app_context():
            try:
                res = face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )
                results.append(res)
            except Exception as exc:
                errors.append(exc)

    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", side_effect=slow_analyze):
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)

            t1.start()
            t2.start()
            t1.join()
            t2.join()

    # Exactly one succeeded and one was rejected with ChallengeError
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ChallengeError)
    assert "currently being processed" in str(errors[0]) or "already been used" in str(errors[0])


def test_06_semaphore_saturation_fails_fast_and_releases_lease(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 6: When inference semaphore is saturated, verification fails fast with 503,
    releases the lease immediately, and guarantees semaphore recovery.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    # Set semaphore capacity to 1 and exhaust it
    test_sem = threading.BoundedSemaphore(1)
    test_sem.acquire()  # Saturated!
    set_inference_semaphore(test_sem)

    try:
        with pytest.raises(FaceEngineNotReadyError) as exc_info:
            face_service.verify(
                user_id=synthetic_user.id,
                session_id=synthetic_session.session_id,
                challenge_id=ch.challenge_id,
                payloads=[dummy_payload],
            )
        assert "at capacity" in str(exc_info.value)

        # Challenge lease was released and attempt count refunded
        reloaded = _db.session.get(FaceChallenge, ch.id)
        assert reloaded.completed is False
        assert reloaded.lease_token is None
        assert reloaded.attempt_count == 0

    finally:
        # Reset semaphore to default
        set_inference_semaphore(threading.BoundedSemaphore(4))


def test_07_challenge_expiry_during_inference_fails_closed(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 7: If the challenge TTL expires during long inference, resolution as success
    fails closed with ChallengeError and does NOT mark completed=True with success=True.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    # Challenge expires in 1 second
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id, ttl=1)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    def slow_inference(*args, **kwargs):
        import time
        time.sleep(1.2)  # Wait past challenge expiry
        return [_mock_analysis(synthetic_enrollment)]

    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", side_effect=slow_inference):
            with pytest.raises(ChallengeError) as exc_info:
                face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )
            assert "expired during processing" in str(exc_info.value)

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.success is False


def test_08_not_enrolled_user_burns_challenge(
    app, db, synthetic_session, face_service
):
    """
    Test 8: If a user is not enrolled, verification burns the challenge as biometric rejection.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    # Create user without enrollment
    unenrolled_user = User(
        username="unenrolled_c12",
        email="unenrolled_c12@college.edu",
        password_hash="hash",
    )
    _db.session.add(unenrolled_user)
    _db.session.commit()

    ch = _create_challenge(unenrolled_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    with pytest.raises(NotEnrolledError):
        face_service.verify(
            user_id=unenrolled_user.id,
            session_id=synthetic_session.session_id,
            challenge_id=ch.challenge_id,
            payloads=[dummy_payload],
        )

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is True
    assert reloaded.success is False
    assert reloaded.attempt_count == 1


def test_09_enrollment_preserves_non_lease_lifecycle(
    app, db, synthetic_user, synthetic_session, face_service
):
    """
    Test 9: Enrolment preserves its existing non-lease lifecycle and burns challenge.
    """
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50
    vector = np.ones(512, dtype=np.float32)

    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", return_value=[_mock_analysis(vector)]):
            res = face_service.enroll(
                user_id=synthetic_user.id,
                session_id=synthetic_session.session_id,
                challenge_id=ch.challenge_id,
                payloads=[dummy_payload],
                consent_given=True,
            )

    assert res["success"] is True
    assert res["enrolled"] is True

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is True
    assert reloaded.attempt_count == 1
    assert reloaded.lease_token is None


def test_10_route_level_error_masks_preserve_generic_rejection(
    app, client, db, synthetic_user, synthetic_session, synthetic_enrollment, signed_cookie_for
):
    """
    Test 10: In /api/face/verify route, client receives HTTP 400 with generic mask
    on biometric/frame failure, and HTTP 503 on engine unavailability.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], signed_cookie_for(synthetic_session.session_id))

    ch1 = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50
    import io

    # Biometric failure -> 400 generic rejection
    impostor_vec = np.zeros(512, dtype=np.float32)
    impostor_vec[0] = 1.0
    impostor_analysis = _mock_analysis(impostor_vec)
    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", return_value=[impostor_analysis]):
            resp = client.post(
                "/api/face/verify",
                data={"challenge_id": ch1.challenge_id, "frames": (io.BytesIO(dummy_payload), "frame1.jpg")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "Face verification failed."

    # Infrastructure failure -> 503 unavailable
    ch2 = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", side_effect=FaceEngineUnavailable("engine missing")):
            resp2 = client.post(
                "/api/face/verify",
                data={"challenge_id": ch2.challenge_id, "frames": (io.BytesIO(dummy_payload), "frame1.jpg")},
                content_type="multipart/form-data",
            )
            assert resp2.status_code == 503
            assert resp2.get_json()["error"] == "Face service is temporarily unavailable."


def test_11_database_failure_during_success_resolution_fails_closed_and_raises_503(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 11: If a database error occurs during biometric success resolution,
    verify() fails closed, does not mark success, and raises FaceEngineNotReadyError (503).
    """
    from sqlalchemy.exc import OperationalError

    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
            # Simulate DB failure during resolve_lease_biometric_success
            with patch.object(_db.session, "commit", side_effect=OperationalError("mock db error", {}, None)):
                with pytest.raises(FaceEngineNotReadyError) as exc_info:
                    face_service.verify(
                        user_id=synthetic_user.id,
                        session_id=synthetic_session.session_id,
                        challenge_id=ch.challenge_id,
                        payloads=[dummy_payload],
                    )
                assert "Database unavailable" in str(exc_info.value)

    # Invariant: Challenge must NOT be marked success!
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.success is False


def test_12_stale_request_rejection_cannot_burn_newer_request_lease(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 12: In an end-to-end verification scenario, if Request 1's lease expires during processing
    and Request 2 acquires the lease, Request 1's biometric failure cannot burn Request 2's lease.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id, ttl=20)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    # Request 1 acquires lease
    now1 = datetime.utcnow()
    acq1 = ChallengeLeaseService.acquire_lease(ch.challenge_id, lease_duration_seconds=1.0, now=now1)
    assert acq1.acquired is True
    token1 = acq1.lease_token

    # 2 seconds pass; lease 1 expires
    now2 = now1 + timedelta(seconds=2)

    # Request 2 acquires lease with token 2
    acq2 = ChallengeLeaseService.acquire_lease(ch.challenge_id, lease_duration_seconds=5.0, now=now2)
    assert acq2.acquired is True
    token2 = acq2.lease_token
    assert token1 != token2

    # Request 1 encounters biometric mismatch and tries to reject
    res1 = ChallengeLeaseService.resolve_lease_biometric_rejection(ch.challenge_id, token1, now=now2)
    assert res1.resolved is False
    assert res1.reason == "stale_or_invalid_lease_token"

    # Request 2's active lease and challenge are completely uncorrupted
    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.completed is False
    assert reloaded.success is False
    assert reloaded.lease_token == token2
    assert reloaded.attempt_count == 2

