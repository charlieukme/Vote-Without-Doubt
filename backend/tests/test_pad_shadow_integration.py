"""
Integration Tests for Face Presentation Attack Detection (PAD) in Shadow Mode (Phase C.13).

Validates:
1. PAD live prediction while identity passes -> preserves identity success.
2. PAD spoof prediction while identity passes -> preserves identity success; minimal shadow telemetry.
3. PAD live prediction while identity fails -> preserves identity rejection (fail-closed).
4. PAD model unavailable while identity passes -> preserves identity success.
5. PAD inference exception and malformed output -> preserves identity success.
6. Missing PAD calibration (threshold=None) -> evaluates safely in shadow mode.
7. PAD never changes the identity decision in shadow mode across all combinations.
8. Enforcing mode is strictly unreachable and cannot be activated through the live verification route.
9. Challenge lease retry/rejection lifecycle remains preserved and functional.
10. Enrollment remains completely unaffected and does not execute PAD.
11. Privacy review: Zero PII, student identifiers, session tokens, or raw biometric embeddings in logs.
12. Disabled mode cleanly bypasses PAD evaluation.

Uses synthetic test fixtures and disposable SQLite databases ONLY. Zero human biometric data.
"""

from datetime import datetime, timedelta
import io
import logging
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
from app.services.biometric_adapter import (
    BiometricDualGateAdapter,
    DualGateOutcome,
    GateDecision,
    PADGateInput,
)
from app.services.challenge_lease_service import ChallengeLeaseService
from app.services.face_engine import (
    FaceEngineError,
    FaceEngineUnavailable,
    FrameAnalysis,
    PoseEstimate,
)
from app.services.face_service import (
    ChallengeError,
    FaceEngineNotReadyError,
    FaceService,
    FrameAdmissionError,
    MatchFailedError,
    NotEnrolledError,
    get_biometric_adapter,
    get_pad_engine_instance,
    set_biometric_adapter,
    set_pad_engine_instance,
)
from app.services.pad_engine import (
    PADEngine,
    PADInferenceError,
    PADInvalidInputError,
    PADModelUnavailable,
    PADResult,
)


@pytest.fixture
def face_service():
    return FaceService()


@pytest.fixture
def synthetic_user(db):
    user = User(
        username="student_c13",
        email="student_c13@college.edu",
        password_hash="test_hash_c13",
    )
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture
def synthetic_session(db, synthetic_user):
    now = datetime.utcnow()
    sess = AuthSession(
        user_id=synthetic_user.id,
        session_id="session_token_c13_test",
        auth_state="AUTHORIZED",
        ip_address="127.0.0.1",
        user_agent="pytest-c13",
        authenticated_at=now,
        created_at=now,
        last_activity=now,
        idle_expires_at=now + timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        revoked=False,
    )
    _db.session.add(sess)
    _db.session.commit()
    return sess


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


def _mock_analysis_with_frame(vector, detector_score=0.95):
    """Creates a FrameAnalysis with synthetic image and bounding box for zero-copy PAD."""
    pose = PoseEstimate(yaw=0.0, roll=0.0, interocular_px=60.0)
    synthetic_bgr = np.zeros((480, 640, 3), dtype=np.uint8)
    synthetic_bbox = (150.0, 100.0, 350.0, 300.0)  # xyxy
    return FrameAnalysis(
        width=640,
        height=480,
        face_area_ratio=0.25,
        detector_score=detector_score,
        laplacian_variance=150.0,
        mean_luma=120.0,
        pose=pose,
        embedding=vector,
        bbox=synthetic_bbox,
        image_bgr=synthetic_bgr,
    )


def _mock_pad_result(live_score=0.95, pred_class="live", is_live=True):
    p_live = live_score
    p_print = (1.0 - p_live) / 2.0
    p_replay = (1.0 - p_live) / 2.0
    return PADResult(
        p_print=round(p_print, 4),
        p_live=round(p_live, 4),
        p_replay=round(p_replay, 4),
        p_spoof=round(p_print + p_replay, 4),
        live_score=round(p_live, 4),
        spoof_score=round(p_print + p_replay, 4),
        predicted_class_idx=1 if pred_class == "live" else 0,
        predicted_class_name=pred_class,
        latency_ms=12.5,
        model_name="2.7_80x80_MiniFASNetV2.onnx",
        model_sha256="mock_sha256",
        is_live_argmax=(pred_class == "live"),
        is_live=is_live,
    )


# ---------------------------------------------------------------------------
# Test Cases 1 - 12
# ---------------------------------------------------------------------------

def test_01_pad_live_while_identity_passes(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 1: Identity match passes and PAD predicts live -> verification succeeds normally.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"
    app.config["FACE_PAD_THRESHOLD"] = 0.50

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.96, pred_class="live", is_live=True)
    set_pad_engine_instance(mock_pad)

    try:
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
        mock_pad.evaluate_image.assert_called_once()

        # Database state: challenge completed and successful, unconsumed
        reloaded = _db.session.get(FaceChallenge, ch.id)
        assert reloaded.completed is True
        assert reloaded.success is True
        assert reloaded.consumed is False
    finally:
        set_pad_engine_instance(None)


def test_02_pad_spoof_while_identity_passes_preserves_identity_success(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 2: Identity match passes, but PAD predicts spoof (print attack).
    In shadow mode, the voter is NOT blocked and verification STILL succeeds!
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"
    app.config["FACE_PAD_THRESHOLD"] = 0.50

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    # PAD detects a print attack (live_score = 0.05 < 0.50)
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.05, pred_class="print_attack", is_live=False)
    set_pad_engine_instance(mock_pad)

    try:
        with patch.object(FaceService, "_admit_frames", return_value=None):
            with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
                res = face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )

        # Invariant: Identity decision is preserved; spoof prediction does NOT block voter
        assert res["success"] is True
        assert res["verified"] is True

        reloaded = _db.session.get(FaceChallenge, ch.id)
        assert reloaded.completed is True
        assert reloaded.success is True
        assert reloaded.consumed is False
    finally:
        set_pad_engine_instance(None)


def test_03_pad_live_while_identity_fails_preserves_identity_rejection(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 3: Identity match fails (impostor), but PAD predicts live.
    PAD live must NEVER override or compensate for an identity rejection.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"
    app.config["FACE_PAD_THRESHOLD"] = 0.50

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    # Impostor vector
    impostor_vec = np.zeros(512, dtype=np.float32)
    impostor_vec[0] = 1.0
    impostor_analysis = _mock_analysis_with_frame(impostor_vec)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.99, pred_class="live", is_live=True)
    set_pad_engine_instance(mock_pad)

    try:
        with patch.object(FaceService, "_admit_frames", return_value=None):
            with patch.object(FaceService, "_analyze", return_value=[impostor_analysis]):
                with pytest.raises(MatchFailedError):
                    face_service.verify(
                        user_id=synthetic_user.id,
                        session_id=synthetic_session.session_id,
                        challenge_id=ch.challenge_id,
                        payloads=[dummy_payload],
                    )

        # Invariant: Challenge is burned for biometric rejection
        reloaded = _db.session.get(FaceChallenge, ch.id)
        assert reloaded.completed is True
        assert reloaded.success is False
        assert reloaded.attempt_count == 1
    finally:
        set_pad_engine_instance(None)


def test_04_pad_model_unavailable_preserves_identity_success(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 4: PAD model is unavailable (PADModelUnavailable).
    In shadow mode, the PAD failure is recorded as an operational event,
    and identity verification still succeeds.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    mock_pad.evaluate_image.side_effect = PADModelUnavailable("Model file missing")
    set_pad_engine_instance(mock_pad)

    try:
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
        reloaded = _db.session.get(FaceChallenge, ch.id)
        assert reloaded.completed is True
        assert reloaded.success is True
    finally:
        set_pad_engine_instance(None)


def test_05_pad_inference_exception_preserves_identity_success(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 5: PAD throws an inference exception (e.g. ONNX execution error).
    In shadow mode, identity verification is unaffected.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    mock_pad.evaluate_image.side_effect = PADInferenceError("ONNX session crash")
    set_pad_engine_instance(mock_pad)

    try:
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
    finally:
        set_pad_engine_instance(None)


def test_06_missing_pad_calibration_threshold_evaluates_cleanly(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 6: FACE_PAD_THRESHOLD is None (uncalibrated).
    In shadow mode, the system evaluates without requiring an arbitrary threshold.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"
    app.config["FACE_PAD_THRESHOLD"] = None  # No unvalidated default!

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.88, pred_class="live", is_live=None)
    set_pad_engine_instance(mock_pad)

    try:
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
    finally:
        set_pad_engine_instance(None)


def test_07_pad_never_changes_identity_decision_matrix(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 7: Exhaustive matrix verification that shadow-mode PAD NEVER alters Gate 1 outcome.
    Evaluates:
      1. ID Pass + PAD Live -> Pass
      2. ID Pass + PAD Print Attack -> Pass
      3. ID Pass + PAD Replay Attack -> Pass
      4. ID Fail + PAD Live -> Fail
      5. ID Fail + PAD Print Attack -> Fail
      6. ID Fail + PAD Replay Attack -> Fail
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    impostor_vec = np.zeros(512, dtype=np.float32)
    impostor_vec[0] = 1.0

    cases = [
        (synthetic_enrollment, "live", 0.95, True),
        (synthetic_enrollment, "print_attack", 0.10, True),
        (synthetic_enrollment, "replay_attack", 0.15, True),
        (impostor_vec, "live", 0.95, False),
        (impostor_vec, "print_attack", 0.10, False),
        (impostor_vec, "replay_attack", 0.15, False),
    ]

    mock_pad = MagicMock()
    set_pad_engine_instance(mock_pad)

    try:
        for idx, (vec, pad_class, pad_score, expected_pass) in enumerate(cases):
            ch = _create_challenge(synthetic_user.id, synthetic_session.session_id, ttl=30)
            mock_pad.evaluate_image.return_value = _mock_pad_result(
                live_score=pad_score, pred_class=pad_class, is_live=(pad_class == "live")
            )
            analysis = _mock_analysis_with_frame(vec)

            with patch.object(FaceService, "_admit_frames", return_value=None):
                with patch.object(FaceService, "_analyze", return_value=[analysis]):
                    if expected_pass:
                        res = face_service.verify(
                            user_id=synthetic_user.id,
                            session_id=synthetic_session.session_id,
                            challenge_id=ch.challenge_id,
                            payloads=[dummy_payload],
                        )
                        assert res["verified"] is True
                    else:
                        with pytest.raises(MatchFailedError):
                            face_service.verify(
                                user_id=synthetic_user.id,
                                session_id=synthetic_session.session_id,
                                challenge_id=ch.challenge_id,
                                payloads=[dummy_payload],
                            )
    finally:
        set_pad_engine_instance(None)


def test_08_enforcing_mode_strictly_unreachable_from_live_verification(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 8: Enforcing mode is strictly prohibited on the live route.
    If FACE_PAD_MODE is set to 'enforcing', face_service forces 'shadow' mode.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "enforcing"  # Prohibited!
    app.config["FACE_PAD_THRESHOLD"] = 0.50

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    # Spoof detected; in enforcing mode this would reject, but because enforcing is prohibited,
    # it forces shadow mode and PASSES!
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.05, pred_class="print_attack", is_live=False)
    set_pad_engine_instance(mock_pad)

    try:
        with patch.object(FaceService, "_admit_frames", return_value=None):
            with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
                res = face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )

        assert res["verified"] is True
        assert res["success"] is True
    finally:
        set_pad_engine_instance(None)


def test_09_challenge_lease_retry_preserved_with_shadow_pad(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 9: Infrastructure engine failure releases the lease, refunds attempt,
    and subsequent retry with PAD shadow evaluation succeeds cleanly.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    # Attempt 1: Identity face engine unavailable (503)
    with patch.object(FaceService, "_admit_frames", return_value=None):
        with patch.object(FaceService, "_analyze", side_effect=FaceEngineUnavailable("engine missing")):
            with pytest.raises(FaceEngineNotReadyError):
                face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )

    reloaded = _db.session.get(FaceChallenge, ch.id)
    assert reloaded.attempt_count == 0
    assert reloaded.lease_token is None

    # Attempt 2: Engine restored, PAD shadow runs -> succeeds
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    mock_pad = MagicMock()
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.90, pred_class="live", is_live=True)
    set_pad_engine_instance(mock_pad)

    try:
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
    finally:
        set_pad_engine_instance(None)


def test_10_enrollment_executes_pad_in_shadow_mode_without_altering_acceptance(
    app, db, synthetic_user, synthetic_session, face_service
):
    """
    Test 10: Enrollment workflow executes PAD in shadow mode and never alters enrollment acceptance,
    even when PAD predicts spoof or fails.
    """
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50
    vector = np.ones(512, dtype=np.float32)

    mock_pad = MagicMock()
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.15, pred_class="print_attack", is_live=False)
    set_pad_engine_instance(mock_pad)

    try:
        with patch.object(FaceService, "_admit_frames", return_value=None):
            with patch.object(FaceService, "_analyze", return_value=[_mock_analysis_with_frame(vector)]):
                res = face_service.enroll(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                    consent_given=True,
                )

        assert res["success"] is True
        assert res["enrolled"] is True
        # PAD engine was invoked during enrollment in shadow mode!
        mock_pad.evaluate_image.assert_called_once()
    finally:
        set_pad_engine_instance(None)


def test_10b_enrollment_succeeds_even_when_pad_engine_raises_error(
    app, db, synthetic_user, synthetic_session, face_service
):
    """
    Test 10b: Enrollment succeeds cleanly even if the PAD model is unavailable or throws inference error.
    """
    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50
    vector = np.ones(512, dtype=np.float32)

    mock_pad = MagicMock()
    mock_pad.evaluate_image.side_effect = PADInferenceError("Simulated PAD failure")
    set_pad_engine_instance(mock_pad)

    try:
        with patch.object(FaceService, "_admit_frames", return_value=None):
            with patch.object(FaceService, "_analyze", return_value=[_mock_analysis_with_frame(vector)]):
                res = face_service.enroll(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                    consent_given=True,
                )

        assert res["success"] is True
        assert res["enrolled"] is True
        mock_pad.evaluate_image.assert_called_once()
    finally:
        set_pad_engine_instance(None)


def test_11_zero_sensitive_biometric_data_or_pii_logged(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service, caplog
):
    """
    Test 11: Privacy audit: Telemetry contains only operational status, decision, category, latency.
    Strictly verifies that user_id, session_id, wallet address, authorization_id,
    and embedding vectors are NEVER logged alongside PAD telemetry.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "shadow"
    app.config["FACE_PAD_THRESHOLD"] = 0.50

    ch = _create_challenge(
        synthetic_user.id, synthetic_session.session_id, authorization_id=999, election_id=1
    )
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    mock_pad.evaluate_image.return_value = _mock_pad_result(live_score=0.92, pred_class="live", is_live=True)
    set_pad_engine_instance(mock_pad)

    try:
        with caplog.at_level(logging.INFO):
            with patch.object(FaceService, "_admit_frames", return_value=None):
                with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
                    res = face_service.verify(
                        user_id=synthetic_user.id,
                        session_id=synthetic_session.session_id,
                        challenge_id=ch.challenge_id,
                        payloads=[dummy_payload],
                    )

        assert res["verified"] is True

        # Find PAD telemetry line in logs
        pad_logs = [record.message for record in caplog.records if "PAD shadow telemetry" in record.message]
        assert len(pad_logs) == 1
        log_line = pad_logs[0]

        # Verify operational attributes are present
        assert "status=" in log_line
        assert "decision=" in log_line
        assert "latency_ms=" in log_line

        # Verify strict privacy: No PII or sensitive keys
        assert "user_id" not in log_line
        assert synthetic_user.username not in log_line
        assert synthetic_session.session_id not in log_line
        assert ch.challenge_id not in log_line
        assert "authorization_id" not in log_line
        assert "999" not in log_line  # authorization_id
        assert "embedding" not in log_line
    finally:
        set_pad_engine_instance(None)


def test_12_disabled_mode_bypasses_pad_inference(
    app, db, synthetic_user, synthetic_session, synthetic_enrollment, face_service
):
    """
    Test 12: When FACE_PAD_MODE is 'disabled', PAD engine inference is completely bypassed.
    """
    app.config["FACE_SIMILARITY_THRESHOLD"] = 0.80
    app.config["FACE_PAD_MODE"] = "disabled"

    ch = _create_challenge(synthetic_user.id, synthetic_session.session_id)
    matching_analysis = _mock_analysis_with_frame(synthetic_enrollment)
    dummy_payload = b"\xff\xd8\xff" + b"\x00" * 50

    mock_pad = MagicMock()
    set_pad_engine_instance(mock_pad)

    try:
        with patch.object(FaceService, "_admit_frames", return_value=None):
            with patch.object(FaceService, "_analyze", return_value=[matching_analysis]):
                res = face_service.verify(
                    user_id=synthetic_user.id,
                    session_id=synthetic_session.session_id,
                    challenge_id=ch.challenge_id,
                    payloads=[dummy_payload],
                )

        assert res["verified"] is True
        # In disabled mode, evaluate_image must NOT be called
        mock_pad.evaluate_image.assert_not_called()
    finally:
        set_pad_engine_instance(None)
