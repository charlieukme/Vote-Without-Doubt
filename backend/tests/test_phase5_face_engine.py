"""
Phase 5 face engine tests - the REAL pipeline.

Every test here runs the actual InsightFace SCRFD detector, the actual
landmark estimator and the actual ArcFace w600k_r50 encoder on synthetic
fixture frames. Nothing about the biometric decision is stubbed; the only thing
mocked anywhere in Phase 5 is the browser camera API.

No test is skipped to hide a failure. If the model weights are missing,
``real_face_engine`` fails the test rather than excluding it.
"""

import numpy as np
import pytest

from app.services.face_engine import (
    EMBEDDING_DIMENSION,
    FaceCountError,
    FaceEngine,
    FaceEngineUnavailable,
    InvalidFrameError,
    QualityRejectedError,
    UnknownPoseError,
    calibrate_neutral,
    calibrated_yaw,
    cosine_similarity,
    mean_normalised,
    signed_direction,
)
from tests import face_fixtures as fx

IDENT = fx.FIXTURE_IDENTITIES[0]
CENTER = fx.FIXTURE_CENTER_THRESHOLD
TURN = fx.FIXTURE_TURN_THRESHOLD


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def test_real_engine_loads_real_models(real_face_engine):
    """The engine must come up on the real ONNX weights, not a placeholder."""
    assert isinstance(real_face_engine, FaceEngine)
    assert real_face_engine.provider_summary


def test_engine_refuses_a_missing_model_tree(tmp_path):
    """No weights directory must fail closed, not degrade."""
    with pytest.raises(FaceEngineUnavailable):
        FaceEngine(str(tmp_path / 'no-models-here'))


def test_engine_refuses_an_incomplete_model_tree(tmp_path, monkeypatch):
    """A partial weight set must fail closed too."""
    root = tmp_path / 'models' / 'buffalo_l'
    root.mkdir(parents=True)
    (root / 'det_10g.onnx').write_bytes(b'not-a-real-model')
    # w600k_r50.onnx deliberately absent.
    with pytest.raises(FaceEngineUnavailable):
        FaceEngine(str(tmp_path))


# ---------------------------------------------------------------------------
# Frame decoding and admission
# ---------------------------------------------------------------------------

def test_decode_accepts_real_jpeg(real_face_engine):
    payload = fx.jpeg(fx.render(IDENT, 0.0, seed=5))
    image = real_face_engine.decode_frame(payload)
    assert image.ndim == 3 and image.shape[2] == 3


@pytest.mark.parametrize('payload', [
    b'',
    b'not-a-jpeg-at-all',
    b'\x89PNG\r\n\x1a\n' + b'\x00' * 32,
    b'\xff\xd8\xff' + b'truncated',
])
def test_decode_rejects_non_jpeg_and_corrupt(real_face_engine, payload):
    with pytest.raises(InvalidFrameError):
        real_face_engine.decode_frame(payload)


def test_quality_rejects_undersized_frame(real_face_engine):
    """Dimension limits are enforced by the quality gate, not the decoder."""
    payload = fx.jpeg(fx.render(IDENT, 0.0, seed=5, size=64))
    with pytest.raises(InvalidFrameError):
        real_face_engine.measure_quality(real_face_engine.decode_frame(payload))


def test_quality_rejects_blurred_frame(real_face_engine):
    payload = fx.jpeg(fx.render(IDENT, 0.0, seed=5, blur=6))
    with pytest.raises(QualityRejectedError):
        real_face_engine.analyze(payload)


def test_quality_rejects_underexposed_frame(real_face_engine):
    payload = fx.jpeg(fx.render(IDENT, 0.0, seed=5, bright=0.06))
    with pytest.raises(QualityRejectedError):
        real_face_engine.analyze(payload)


def test_quality_rejects_blank_frame(real_face_engine):
    import cv2
    ok, buf = cv2.imencode('.jpg', np.zeros((360, 360, 3), np.uint8))
    assert ok
    with pytest.raises((FaceCountError, QualityRejectedError)):
        real_face_engine.analyze(buf.tobytes())


# ---------------------------------------------------------------------------
# Exactly-one-face enforcement
# ---------------------------------------------------------------------------

def test_two_faces_in_one_frame_are_rejected(real_face_engine):
    """Multi-face frames must fail. This is why max_num > 1 upstream."""
    import cv2
    canvas = np.full((480, 760, 3), 120, np.uint8)
    canvas[60:420, 20:380] = fx.render(IDENT, 0.0, seed=31)
    canvas[60:420, 380:740] = fx.render(fx.FIXTURE_IDENTITIES[1], 0.0, seed=32)
    ok, buf = cv2.imencode('.jpg', canvas)
    assert ok
    with pytest.raises(FaceCountError):
        real_face_engine.analyze(buf.tobytes())


# ---------------------------------------------------------------------------
# Landmarks and head pose
# ---------------------------------------------------------------------------

def test_pose_requires_a_five_point_landmark_set():
    """An unexpected landmark count must be refused, not guessed at."""
    with pytest.raises(UnknownPoseError):
        FaceEngine.estimate_pose(None)
    with pytest.raises(UnknownPoseError):
        FaceEngine.estimate_pose(np.zeros((106, 2)))
    with pytest.raises(UnknownPoseError):
        FaceEngine.estimate_pose(np.zeros((3, 2)))


def test_pose_rejects_degenerate_landmarks():
    points = np.zeros((5, 2))
    with pytest.raises(UnknownPoseError):
        FaceEngine.estimate_pose(points)


def test_pose_is_roll_invariant():
    """Rotating the whole landmark set must not change the yaw score."""
    points = np.array([
        [-20.0, 0.0], [20.0, 0.0], [6.0, 5.0], [-15.0, 30.0], [15.0, 30.0],
    ])
    straight = FaceEngine.estimate_pose(points).yaw
    angle = np.deg2rad(25.0)
    rotation = np.array([
        [np.cos(angle), -np.sin(angle)],
        [np.sin(angle), np.cos(angle)],
    ])
    rotated = points @ rotation.T
    assert FaceEngine.estimate_pose(rotated).yaw == pytest.approx(straight, abs=1e-9)


def test_pose_sign_follows_the_nose_offset():
    """A nose shifted along the eye axis flips the sign of the score."""
    left = np.array([[-20.0, 0.0], [20.0, 0.0], [0.0, 5.0], [-15.0, 30.0], [15.0, 30.0]])
    right = left.copy()
    right[2, 0] = 8.0
    assert FaceEngine.estimate_pose(left).yaw == pytest.approx(0.0, abs=1e-9)
    assert FaceEngine.estimate_pose(right).yaw > 0.1


def test_yaw_tracks_rendered_head_rotation(real_face_engine):
    """The measured score must increase monotonically with real rotation.

    This is the property the liveness state machine depends on.
    """
    scores = []
    for yaw in (-0.35, -0.20, 0.0, 0.20, 0.35):
        payload = fx.jpeg(fx.render(IDENT, yaw=yaw, seed=int(abs(yaw) * 1000) + 7))
        scores.append(real_face_engine.analyze(payload).pose.yaw)
    assert scores == sorted(scores), scores
    assert scores[-1] - scores[0] > 2 * TURN


# ---------------------------------------------------------------------------
# Neutral calibration
# ---------------------------------------------------------------------------

def test_calibrate_neutral_averages_real_front_facing_frames(real_face_engine):
    raw = [
        real_face_engine.analyze(fx.jpeg(fx.render(IDENT, 0.0, seed=seed))).pose.yaw
        for seed in range(6)
    ]
    neutral = calibrate_neutral(raw)
    assert max(abs(r - neutral) for r in raw) < CENTER
    assert min(raw) - TURN < neutral < max(raw) + TURN


def test_calibrated_neutral_separates_front_facing_from_turned(real_face_engine):
    """The measured separation that the shipped thresholds sit inside."""
    neutral_raw = [
        real_face_engine.analyze(fx.jpeg(fx.render(i, 0.0, seed=s))).pose.yaw
        for i in fx.FIXTURE_IDENTITIES for s in range(4)
    ]
    neutral = calibrate_neutral(neutral_raw)
    worst_front = max(abs(calibrated_yaw(v, neutral)) for v in neutral_raw)

    worst_turn = 9.9
    for i in fx.FIXTURE_IDENTITIES:
        for yaw in (-0.35, 0.35):
            value = real_face_engine.analyze(
                fx.jpeg(fx.render(i, yaw=yaw, seed=int(yaw * 100) + 3))).pose.yaw
            worst_turn = min(worst_turn, abs(calibrated_yaw(value, neutral)))

    assert worst_front < CENTER
    assert worst_turn > TURN


def test_signed_direction_classification():
    assert signed_direction(0.010, 0.0, CENTER) == 'CENTER'
    assert signed_direction(0.10, 0.0, CENTER) == 'RIGHT'
    assert signed_direction(-0.10, 0.0, CENTER) == 'LEFT'


# ---------------------------------------------------------------------------
# Embeddings and similarity
# ---------------------------------------------------------------------------

def test_embedding_is_a_real_512d_unit_vector(real_face_engine):
    payload = fx.jpeg(fx.render(IDENT, 0.0, seed=3))
    vector = real_face_engine.analyze(payload).embedding
    assert vector.shape == (EMBEDDING_DIMENSION,)
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-5)


def test_same_identity_scores_above_different_identities(real_face_engine):
    """Genuine comparisons must separate from impostor ones on real features."""
    templates = {}
    for i in fx.FIXTURE_IDENTITIES:
        vectors = [
            real_face_engine.analyze(
                fx.jpeg(fx.render(i, yaw=y, seed=int(y * 100) + 21))).embedding
            for y in (-0.20, 0.0, 0.20)
        ]
        templates[i] = mean_normalised(vectors)

    genuine, impostor = [], []
    for i in fx.FIXTURE_IDENTITIES:
        for y in (-0.35, -0.20, 0.0, 0.20, 0.35):
            vector = real_face_engine.analyze(
                fx.jpeg(fx.render(i, yaw=y, seed=int(y * 100) + 21))).embedding
            genuine.append(cosine_similarity(templates[i], vector))
            for j in fx.FIXTURE_IDENTITIES:
                if j != i:
                    impostor.append(cosine_similarity(templates[j], vector))

    assert min(genuine) > fx.FIXTURE_SIMILARITY_THRESHOLD
    assert max(impostor) < fx.FIXTURE_SIMILARITY_THRESHOLD
    assert min(genuine) > max(impostor)


def test_similarity_is_symmetric_and_bounded(real_face_engine):
    a = real_face_engine.analyze(fx.jpeg(fx.render(IDENT, 0.0, seed=1))).embedding
    b = real_face_engine.analyze(
        fx.jpeg(fx.render(fx.FIXTURE_IDENTITIES[2], 0.1, seed=2))).embedding
    forward = cosine_similarity(a, b)
    assert forward == pytest.approx(cosine_similarity(b, a), abs=1e-9)
    assert -1.0 <= forward <= 1.0


def test_similarity_rejects_mismatched_dimensions():
    with pytest.raises(ValueError):
        cosine_similarity(np.zeros(512), np.zeros(256))


def test_mean_normalised_requires_vectors_and_stays_unit_length(real_face_engine):
    with pytest.raises(ValueError):
        mean_normalised([])
    vectors = [
        real_face_engine.analyze(fx.jpeg(fx.render(IDENT, y, seed=int(y * 50) + 9))).embedding
        for y in (0.0, 0.1)
    ]
    template = mean_normalised(vectors)
    assert float(np.linalg.norm(template)) == pytest.approx(1.0, abs=1e-5)
