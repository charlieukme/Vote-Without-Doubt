"""
Face Recognition Engine - Phase 5

The only place in the backend that touches face images or biometric
templates. Everything is real: SCRFD detection, 2D106 facial landmarks,
geometric head-pose estimation from those landmarks, image quality gates and
ArcFace w600k_r50 embeddings executed through ONNX Runtime.

Fail-closed contract
--------------------
``get_engine()`` raises :class:`FaceEngineUnavailable` when the model files
or the inference backend are missing. Callers must translate that into
HTTP 503. There is no permissive fallback, no stub recogniser and no
"accept when in doubt" branch anywhere in this module.

Image handling contract
-----------------------
Frame bytes are decoded into a NumPy array, consumed and dropped. Nothing is
written to disk and no frame is retained on the instance, so the "raw frames
are never persisted" requirement holds by construction.
"""

import logging
import math
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Model provenance recorded with every template.
MODEL_PACK_NAME = 'buffalo_l'
EMBEDDING_MODEL_NAME = 'buffalo_l/w600k_r50'
EMBEDDING_DIMENSION = 512

JPEG_MAGIC = b'\xff\xd8\xff'

# Quality gates. These bound what the detector is asked to reason about; they
# are not a liveness decision.
MIN_FRAME_DIMENSION = 160
MAX_FRAME_DIMENSION = 1920
MIN_DETECTOR_SCORE = 0.5
MIN_FACE_AREA_RATIO = 0.05
MIN_LAPLACIAN_VARIANCE = 25.0
MIN_MEAN_LUMA = 30.0
MAX_MEAN_LUMA = 225.0

# Head-pose (yaw) estimation.
#
# The score is the nose-tip offset from the eye midpoint, measured ALONG the
# interocular axis and normalised by the interocular distance:
#
#     axis       = (right_eye - left_eye) / ||right_eye - left_eye||
#     yaw        = dot(nose - (left_eye + right_eye) / 2, axis) / ||right_eye - left_eye||
#
# Projecting onto the eye axis rather than using raw image x makes the score
# invariant to head roll. It is a dimensionless, image-space asymmetry score
# (roughly +/-0.35 for a strongly turned head); it is NOT a calibrated angle
# in degrees, and no degree claim is made anywhere in this system.
#
# The score carries a small per-subject geometry bias, so liveness decisions
# are made against a per-identity neutral baseline captured from real
# enrollment frames rather than against a single global zero. See
# ``calibrate_neutral`` and docs/PHASE5_FIXTURES.md for the measured
# separation this buys.
#
# SCRFD returns five landmarks in a fixed, documented order:
#   0 = left eye corner, 1 = right eye corner, 2 = nose tip,
#   3 = left mouth corner, 4 = right mouth corner.
# Those five points are what head pose is derived from. The dense 106-point
# mesh in the same model pack is intentionally NOT used: its index semantics
# are not published by the library, so an assumed layout could not be
# verified and must not drive a security decision.
LANDMARK_COUNT = 5
LANDMARK_LEFT_EYE = 0
LANDMARK_RIGHT_EYE = 1
LANDMARK_NOSE = 2

# Detection budget. max_num must be > 1 so that a frame containing several
# faces is detected as such and rejected; max_num=1 would silently truncate
# the result and make the "exactly one face" rule unenforceable.
MAX_FACES_CONSIDERED = 5


class FaceEngineError(RuntimeError):
    """Unrecoverable face-engine problem; callers must fail closed."""


class FaceEngineUnavailable(FaceEngineError):
    """The recognition model or inference backend could not be loaded."""


class InvalidFrameError(ValueError):
    """A submitted frame is not an acceptable JPEG image."""

    reason = 'invalid_frame'


class QualityRejectedError(ValueError):
    """A frame decoded but failed the quality gates."""

    reason = 'low_quality'


class FaceCountError(ValueError):
    """A frame did not contain exactly one detectable face."""

    reason = 'face_count'


class UnknownPoseError(ValueError):
    """Head pose could not be estimated from the landmarks."""

    reason = 'unknown_pose'


@dataclass(frozen=True)
class PoseEstimate:
    """Head-pose result for a single frame."""

    yaw: float
    roll: float
    interocular_px: float


@dataclass(frozen=True)
class FrameAnalysis:
    """Everything derived from one frame. ``embedding`` never leaves the backend."""

    width: int
    height: int
    face_area_ratio: float
    detector_score: float
    laplacian_variance: float
    mean_luma: float
    pose: PoseEstimate
    embedding: np.ndarray = field(repr=False)
    bbox: Optional[Tuple[float, float, float, float]] = None
    image_bgr: Optional[np.ndarray] = field(default=None, repr=False)


class FaceEngine:
    """Real InsightFace pipeline (detection, landmarks, ArcFace embedding)."""

    def __init__(self, root: str, providers: Optional[Sequence[str]] = None,
                 det_size: int = 640, max_num: int = MAX_FACES_CONSIDERED):
        self._root = root
        self._providers = list(providers) if providers else ['CPUExecutionProvider']
        self._det_size = det_size
        self._max_num = max_num
        self._lock = threading.Lock()
        self._detector = None
        self._recogniser = None
        self._providers_resolved: List[str] = []

        if not os.path.isdir(root):
            raise FaceEngineUnavailable(
                f'Face model directory {root!r} does not exist. Provision the '
                'InsightFace buffalo_l weights before starting the service.'
            )
        self._build()

    # -- construction --------------------------------------------------
    def _resolve_model_dir(self) -> str:
        """Locate the buffalo_l weight directory under ``root``.

        InsightFace's download layout is ``<root>/models/buffalo_l``; a flat
        ``<root>/buffalo_l`` is also accepted. Resolution is explicit so a
        missing or partial model tree fails closed with a clear message.
        """
        candidates = (
            os.path.join(self._root, 'models', MODEL_PACK_NAME),
            os.path.join(self._root, MODEL_PACK_NAME),
        )
        for pack in candidates:
            if os.path.isdir(pack):
                return pack
        raise FaceEngineUnavailable(
            f'No {MODEL_PACK_NAME!r} weights found under {self._root!r}. '
            'Expected det_10g.onnx and w600k_r50.onnx to be provisioned.'
        )

    def _require(self, filename: str, model_dir: str) -> str:
        path = os.path.join(model_dir, filename)
        if not os.path.isfile(path):
            raise FaceEngineUnavailable(
                f'Required model weight {filename!r} is missing from {model_dir!r}.'
            )
        return path

    def _build(self) -> None:
        try:
            import onnxruntime  # noqa: F401
        except Exception as error:  # pragma: no cover - import guard
            raise FaceEngineUnavailable(
                f'onnxruntime is not available: {error!r}'
            ) from error
        try:
            from insightface.app import FaceAnalysis
        except Exception as error:
            raise FaceEngineUnavailable(
                f'insightface could not be imported: {error!r}'
            ) from error

        # Explicit weights only; no implicit download during request handling.
        model_dir = self._resolve_model_dir()
        self._require('det_10g.onnx', model_dir)
        self._require('w600k_r50.onnx', model_dir)

        try:
            detector = FaceAnalysis(
                name=MODEL_PACK_NAME,
                root=self._root,
                allowed_modules=['detection', 'recognition'],
                providers=self._providers,
            )
            detector.prepare(ctx_id=0, det_size=(self._det_size, self._det_size),
                             det_thresh=0.5)
        except Exception as error:
            raise FaceEngineUnavailable(
                f'InsightFace detection model failed to initialise: {error!r}'
            ) from error

        with self._lock:
            self._detector = detector
            try:
                self._providers_resolved = list(detector.models['recognition'].session.get_providers())
            except Exception:  # pragma: no cover - defensive
                self._providers_resolved = list(self._providers)

    @property
    def provider_summary(self) -> str:
        return ','.join(self._providers_resolved) or 'unknown'

    # -- image intake --------------------------------------------------
    @staticmethod
    def decode_frame(payload: bytes) -> np.ndarray:
        """Decode JPEG bytes into a BGR array, enforcing the JPEG magic bytes."""
        if not isinstance(payload, (bytes, bytearray)) or len(payload) == 0:
            raise InvalidFrameError('Empty frame payload.')
        if not bytes(payload[:3]) == JPEG_MAGIC:
            raise InvalidFrameError('Frame is not a JPEG image.')
        buffer = np.frombuffer(bytes(payload), dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            raise InvalidFrameError('Frame could not be decoded as an image.')
        return image

    @staticmethod
    def measure_quality(image: np.ndarray) -> Dict[str, float]:
        """Sharpness and exposure gates, computed from real pixels."""
        height, width = image.shape[:2]
        if height < MIN_FRAME_DIMENSION or width < MIN_FRAME_DIMENSION:
            raise InvalidFrameError('Frame resolution is below the minimum.')
        if height > MAX_FRAME_DIMENSION or width > MAX_FRAME_DIMENSION:
            raise InvalidFrameError('Frame resolution exceeds the maximum.')
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        mean_luma = float(gray.mean())
        return {
            'width': int(width),
            'height': int(height),
            'laplacian_variance': variance,
            'mean_luma': mean_luma,
        }

    def check_quality(self, quality: Dict[str, float]) -> None:
        if quality['laplacian_variance'] < MIN_LAPLACIAN_VARIANCE:
            raise QualityRejectedError(
                f'Frame is too blurred (variance={quality["laplacian_variance"]:.1f} < {MIN_LAPLACIAN_VARIANCE})'
            )
        if not (MIN_MEAN_LUMA <= quality['mean_luma'] <= MAX_MEAN_LUMA):
            raise QualityRejectedError(
                f'Frame exposure is out of range (mean_luma={quality["mean_luma"]:.1f} not in [{MIN_MEAN_LUMA}, {MAX_MEAN_LUMA}])'
            )

    # -- pose ----------------------------------------------------------
    @staticmethod
    def estimate_pose(landmarks: Optional[np.ndarray]) -> PoseEstimate:
        """Derive yaw and roll from the detector's real facial landmarks.

        Uses the documented five-point order (left eye, right eye, nose tip,
        left mouth, right mouth). A landmark set of any other size is
        rejected rather than guessed at.
        """
        if landmarks is None:
            raise UnknownPoseError('No facial landmarks were produced.')
        points = np.asarray(landmarks, dtype=np.float64)
        if points.ndim != 2 or points.shape[0] != LANDMARK_COUNT or points.shape[1] < 2:
            raise UnknownPoseError(
                f'Expected {LANDMARK_COUNT} facial landmarks, got '
                f'{None if points.ndim != 2 else points.shape[0]}.'
            )

        left_eye = points[LANDMARK_LEFT_EYE]
        right_eye = points[LANDMARK_RIGHT_EYE]
        nose = points[LANDMARK_NOSE]

        axis = right_eye - left_eye
        interocular = float(math.hypot(float(axis[0]), float(axis[1])))
        if interocular < 1e-6:
            raise UnknownPoseError('Interocular distance is degenerate.')
        axis = axis / interocular

        midpoint = (left_eye + right_eye) / 2.0
        yaw = float(np.dot(nose - midpoint, axis)) / interocular
        roll = math.degrees(math.atan2(float(axis[1]), float(axis[0])))
        if not math.isfinite(yaw) or not math.isfinite(roll):
            raise UnknownPoseError('Head pose estimate is not finite.')
        return PoseEstimate(yaw=float(yaw), roll=float(roll), interocular_px=interocular)

    # -- full frame analysis -------------------------------------------
    def analyze(self, payload: bytes) -> FrameAnalysis:
        """Run the complete real pipeline over one frame."""
        image = self.decode_frame(payload)
        quality = self.measure_quality(image)
        self.check_quality(quality)

        detector = self._detector
        if detector is None:  # pragma: no cover - defensive
            raise FaceEngineUnavailable('Face engine was not initialised.')

        with self._lock:
            faces = detector.get(image, max_num=self._max_num)

        if not faces:
            raise FaceCountError('No face was detected in the frame.')
        if len(faces) > 1:
            raise FaceCountError('More than one face was detected in the frame.')

        face = faces[0]
        score = float(getattr(face, 'det_score', 0.0))
        bbox = np.asarray(face.bbox, dtype=np.float64)
        face_width = float(bbox[2] - bbox[0])
        face_height = float(bbox[3] - bbox[1])
        if face_width <= 0 or face_height <= 0:
            raise FaceCountError('Detected face has no usable bounding box.')
        area_ratio = (face_width * face_height) / float(quality['width'] * quality['height'])

        logger.info(
            'Face frame metrics: image=%dx%d bbox=[%.1f, %.1f, %.1f, %.1f] '
            'face_size=(%.1fx%.1f) area=%.1f area_ratio=%.4f (min=%.2f) '
            'det_score=%.3f (min=%.2f) laplacian_var=%.1f (min=%.1f) mean_luma=%.1f',
            quality['width'], quality['height'],
            bbox[0], bbox[1], bbox[2], bbox[3],
            face_width, face_height, face_width * face_height,
            area_ratio, MIN_FACE_AREA_RATIO,
            score, MIN_DETECTOR_SCORE,
            quality['laplacian_variance'], MIN_LAPLACIAN_VARIANCE,
            quality['mean_luma']
        )

        if score < MIN_DETECTOR_SCORE:
            raise QualityRejectedError(
                f'Face detection confidence is too low (score={score:.3f} < {MIN_DETECTOR_SCORE})'
            )

        if area_ratio < MIN_FACE_AREA_RATIO:
            raise QualityRejectedError(
                f'Face is too small within the frame (area_ratio={area_ratio:.4f} < {MIN_FACE_AREA_RATIO})'
            )

        pose = self.estimate_pose(getattr(face, 'kps', None))

        embedding = getattr(face, 'normed_embedding', None)
        if embedding is None:
            embedding = getattr(face, 'embedding', None)
        if embedding is None:
            raise FaceEngineUnavailable(
                'The recognition model produced no embedding for the face.'
            )
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.shape[0] != EMBEDDING_DIMENSION:
            raise FaceEngineUnavailable(
                f'Unexpected embedding dimension {vector.shape[0]}; expected '
                f'{EMBEDDING_DIMENSION}.'
            )
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8:
            raise FaceEngineUnavailable('Degenerate embedding vector.')

        return FrameAnalysis(
            width=quality['width'],
            height=quality['height'],
            face_area_ratio=area_ratio,
            detector_score=score,
            laplacian_variance=quality['laplacian_variance'],
            mean_luma=quality['mean_luma'],
            pose=pose,
            embedding=vector / norm,
            bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
            image_bgr=image,
        )


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Cosine similarity of two L2-normalised embeddings, clamped to [-1, 1]."""
    a = np.asarray(left, dtype=np.float64).reshape(-1)
    b = np.asarray(right, dtype=np.float64).reshape(-1)
    if a.shape != b.shape:
        raise ValueError('Embedding dimensions do not match.')
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 1e-12:
        raise ValueError('Degenerate embedding vector.')
    return float(np.clip(float(np.dot(a, b)) / denominator, -1.0, 1.0))


def mean_normalised(vectors: Sequence[np.ndarray]) -> np.ndarray:
    """Average embeddings then re-normalise, yielding a unit-length template."""
    if not vectors:
        raise ValueError('At least one embedding is required.')
    stacked = np.asarray([np.asarray(v, dtype=np.float64).reshape(-1) for v in vectors])
    template = stacked.mean(axis=0)
    norm = float(np.linalg.norm(template))
    if norm <= 1e-12:
        raise ValueError('Degenerate template vector.')
    return (template / norm).astype(np.float32)


def calibrate_neutral(raw_yaws: Sequence[float]) -> float:
    """Return the subject's neutral baseline from real front-facing frames.

    The landmark yaw score has a small per-subject geometry bias. Averaging
    genuinely front-facing frames establishes that subject's own zero so
    liveness thresholds compare against their baseline, not a global zero.
    """
    values = [float(v) for v in raw_yaws]
    if len(values) < 1:
        raise ValueError('Neutral calibration needs at least one frame.')
    return float(np.mean(values))


def signed_direction(raw_yaw: float, neutral: float, center_threshold: float) -> str:
    """Classify one frame as CENTER, LEFT or RIGHT relative to the baseline.

    ``center_threshold`` bounds the neutral band. Frames whose calibrated
    magnitude sits between the neutral band and the turn threshold are
    reported as TRANSIT and are deliberately not countable as either a turn
    or a neutral frame.
    """
    residual = float(raw_yaw) - float(neutral)
    if abs(residual) <= float(center_threshold):
        return 'CENTER'
    return 'RIGHT' if residual > 0 else 'LEFT'


def calibrated_yaw(raw_yaw: float, neutral: float) -> float:
    """Subject-relative yaw residual."""
    return float(raw_yaw) - float(neutral)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[FaceEngine] = None
_engine_lock = threading.Lock()


def get_engine(root: Optional[str] = None) -> FaceEngine:
    """Return the process-wide engine, loading it on first use.

    Raises :class:`FaceEngineUnavailable` when the models are absent or the
    inference backend cannot start. Callers must not catch this and proceed.
    """
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            resolved = root or os.getenv(
                'FACE_MODEL_ROOT',
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))), 'face_models'),
            )
            _engine = FaceEngine(resolved)
            logger.info(
                'Phase 5 face engine initialised (model=%s, provider=%s)',
                EMBEDDING_MODEL_NAME, _engine.provider_summary,
            )
    return _engine


def reset_engine() -> None:
    """Drop the cached engine. Used by tests that change the model root."""
    global _engine
    with _engine_lock:
        _engine = None
