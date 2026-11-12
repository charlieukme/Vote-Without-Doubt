"""
Face Presentation Attack Detection (PAD) Engine - Phase C.9 (Experimental)

Standalone, thread-safe service adapter for MiniFASNetV2 ONNX anti-spoofing.
This engine is completely disconnected from live authentication and voting flows.

Security & Architectural Invariants:
1. Pinned SHA-256 and file size validation before loading model weights. Fails closed
   if the model file is missing, empty, or altered.
2. Verified scale-2.7 boundary-aware cropping and BGR 80x80 float32 normalization.
3. Strict validation on input types, image dimensions, empty arrays, and edge cases.
4. CPU-only ONNX Runtime execution with thread-safe inference session locking.
5. Numerically stable softmax probability calculation with documented class mappings:
     Index 0: print_attack
     Index 1: live
     Index 2: replay_attack
6. Typed, immutable PADResult containing fine-grained probabilities and diagnostics.
7. No production threshold hardcoded or applied by default. Threshold selection remains
   deferred until controlled offline empirical evaluation (Phase C.11).
8. Strict privacy adherence: raw frames, crops, and biometric embeddings are NEVER logged.
9. No live route integration: this module is isolated and must not be imported into
   production voting or authentication pipelines until formal authorization.
"""

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

# Pinned candidate model cryptographic digests and file size
PINNED_MINIFASNET_SHA256 = "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b"
PINNED_MINIFASNET_SIZE = 1744116
DEFAULT_MODEL_FILENAME = "2.7_80x80_MiniFASNetV2.onnx"

# Documented 3-class classification mapping
CLASS_MAPPING: Dict[int, str] = {
    0: "print_attack",
    1: "live",
    2: "replay_attack",
}

EXPECTED_INPUT_NAME = "input"
EXPECTED_OUTPUT_NAME = "output"
EXPECTED_INPUT_SHAPE = (1, 3, 80, 80)
EXPECTED_OUTPUT_SHAPE = (1, 3)


# ---------------------------------------------------------------------------
# Exceptions (Fail-Closed Contract)
# ---------------------------------------------------------------------------

class PADError(Exception):
    """Base exception for all Presentation Attack Detection failures (fail closed)."""


class PADModelUnavailable(PADError):
    """Model file missing, invalid size, or SHA-256 integrity check failed."""


class PADInvalidInputError(ValueError, PADError):
    """Input frame, bounding box, or tensor is malformed, empty, or out of bounds."""


class PADInferenceError(PADError):
    """Inference execution failed or returned invalid/non-finite logits."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PADResult:
    """
    Immutable result returned by the PAD engine.
    
    Contains fine-grained class probabilities, argmax predictions, and latency metrics.
    Does NOT declare a production binary decision unless an explicit threshold is supplied.
    """
    p_print: float
    p_live: float
    p_replay: float
    p_spoof: float
    live_score: float
    spoof_score: float
    predicted_class_idx: int
    predicted_class_name: str
    latency_ms: float
    model_name: str
    model_sha256: str
    status: str = "ok"
    is_live_argmax: bool = False
    is_live: Optional[bool] = None  # None unless an explicit evaluation threshold is provided


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def compute_file_sha256(filepath: str) -> str:
    """Computes SHA-256 digest of a local file in 64 KB chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def stable_softmax(logits: np.ndarray, axis: int = -1) -> np.ndarray:
    """
    Numerically stable softmax implementation.
    Subtracts maximum logit along the target axis to prevent exponent overflow.
    """
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exp_vals = np.exp(shifted)
    sum_exp = np.sum(exp_vals, axis=axis, keepdims=True)
    return exp_vals / sum_exp


# ---------------------------------------------------------------------------
# Preprocessing and Bounding Box Expansion (MiniFASNetV2 Specification)
# ---------------------------------------------------------------------------

class MiniFASNetCropper:
    """
    Source-verified face crop and expansion preprocessor for MiniFASNetV2.
    Mirrors minivision-ai/Silent-Face-Anti-Spoofing patch generation logic.
    """

    @staticmethod
    def get_expanded_box(
        src_w: int,
        src_h: int,
        bbox: Sequence[Union[int, float]],
        bbox_format: str = "xywh",
        scale: float = 2.7
    ) -> Tuple[int, int, int, int]:
        """
        Expands the face detection bounding box by the scale factor, applying
        boundary-shifting and clipping to keep the patch within image boundaries.

        Args:
            src_w: Width of the source image in pixels.
            src_h: Height of the source image in pixels.
            bbox: Sequence of 4 coordinates.
            bbox_format: 'xywh' (x, y, w, h) or 'xyxy' (x1, y1, x2, y2).
            scale: Context expansion scale factor (default: 2.7).

        Returns:
            Tuple (left_top_x, left_top_y, right_bottom_x, right_bottom_y) in integer pixel coords.
        """
        if src_w <= 1 or src_h <= 1:
            raise PADInvalidInputError(f"Invalid source image dimensions: {src_w}x{src_h}")

        if not hasattr(bbox, "__len__") or len(bbox) < 4:
            raise PADInvalidInputError(f"Bounding box must contain at least 4 coordinates, got {bbox}")

        fmt = bbox_format.strip().lower()
        if fmt == "xywh":
            x, y, box_w, box_h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        elif fmt == "xyxy":
            x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
            x, y, box_w, box_h = x1, y1, x2 - x1, y2 - y1
        else:
            raise PADInvalidInputError(f"Unsupported bbox_format '{bbox_format}'; expected 'xywh' or 'xyxy'")

        if box_w <= 0 or box_h <= 0:
            raise PADInvalidInputError(f"Invalid bounding box dimensions: w={box_w}, h={box_h}")

        # Clamping scale so expanded box never exceeds total image width/height
        scale = min((src_h - 1) / float(box_h), min((src_w - 1) / float(box_w), float(scale)))

        new_width = box_w * scale
        new_height = box_h * scale
        center_x = box_w / 2.0 + x
        center_y = box_h / 2.0 + y

        left_top_x = center_x - new_width / 2.0
        left_top_y = center_y - new_height / 2.0
        right_bottom_x = center_x + new_width / 2.0
        right_bottom_y = center_y + new_height / 2.0

        # Boundary shifting (exact upstream MiniFASNet logic)
        if left_top_x < 0:
            right_bottom_x -= left_top_x
            left_top_x = 0.0

        if left_top_y < 0:
            right_bottom_y -= left_top_y
            left_top_y = 0.0

        if right_bottom_x > src_w - 1:
            left_top_x -= (right_bottom_x - src_w + 1)
            right_bottom_x = float(src_w - 1)

        if right_bottom_y > src_h - 1:
            left_top_y -= (right_bottom_y - src_h + 1)
            right_bottom_y = float(src_h - 1)

        # Final safety bounds and integer conversion
        lt_x = max(0, min(src_w - 1, int(left_top_x)))
        lt_y = max(0, min(src_h - 1, int(left_top_y)))
        rb_x = max(lt_x + 1, min(src_w - 1, int(right_bottom_x)))
        rb_y = max(lt_y + 1, min(src_h - 1, int(right_bottom_y)))

        return lt_x, lt_y, rb_x, rb_y

    def crop_patch(
        self,
        image_bgr: np.ndarray,
        bbox: Sequence[Union[int, float]],
        bbox_format: str = "xywh",
        scale: float = 2.7,
        out_w: int = 80,
        out_h: int = 80
    ) -> np.ndarray:
        """
        Crops face patch using scale expansion and resizes to (out_w, out_h) in BGR.
        """
        if not isinstance(image_bgr, np.ndarray):
            raise PADInvalidInputError(f"Input image must be a numpy ndarray, got {type(image_bgr)}")

        if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
            raise PADInvalidInputError(
                f"Input image must have shape (H, W, 3), got ndim={image_bgr.ndim}, shape={image_bgr.shape}"
            )

        if image_bgr.size == 0:
            raise PADInvalidInputError("Input image is empty (size 0)")

        src_h, src_w, _ = image_bgr.shape
        lt_x, lt_y, rb_x, rb_y = self.get_expanded_box(src_w, src_h, bbox, bbox_format=bbox_format, scale=scale)

        patch = image_bgr[lt_y:rb_y + 1, lt_x:rb_x + 1]
        if patch.size == 0 or patch.shape[0] == 0 or patch.shape[1] == 0:
            raise PADInvalidInputError(f"Cropped patch is empty for bbox {bbox} in image {src_w}x{src_h}")

        dst = cv2.resize(patch, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        return dst

    def preprocess_to_tensor(
        self,
        image_bgr: np.ndarray,
        bbox: Sequence[Union[int, float]],
        bbox_format: str = "xywh",
        scale: float = 2.7
    ) -> np.ndarray:
        """
        Preprocesses a raw BGR image and bounding box into an ONNX-ready float32 tensor
        of shape (1, 3, 80, 80) normalized to [0.0, 1.0].
        """
        patch_bgr = self.crop_patch(image_bgr, bbox, bbox_format=bbox_format, scale=scale, out_w=80, out_h=80)
        # Convert HWC -> CHW
        chw = np.transpose(patch_bgr, (2, 0, 1)).astype(np.float32)
        # Normalization to [0.0, 1.0]
        chw = chw / 255.0
        # Expand batch dimension -> (1, 3, 80, 80)
        tensor = np.expand_dims(chw, axis=0)
        return np.ascontiguousarray(tensor, dtype=np.float32)


# ---------------------------------------------------------------------------
# Standalone PAD Engine Service Adapter
# ---------------------------------------------------------------------------

class PADEngine:
    """
    Standalone Face Presentation Attack Detection Service Adapter.
    
    Thread-safe, CPU-only ONNX inference with pinned hash verification.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        expected_sha256: str = PINNED_MINIFASNET_SHA256,
        expected_size: int = PINNED_MINIFASNET_SIZE,
        num_threads: int = 2,
        session: Optional[ort.InferenceSession] = None
    ):
        """
        Initializes the PAD Engine.

        Args:
            model_path: Absolute or relative path to the candidate ONNX file.
            expected_sha256: Expected SHA-256 hash digest (fails closed if mismatched).
            expected_size: Expected model file size in bytes (fails closed if mismatched).
            num_threads: Number of intra-op CPU threads for inference.
            session: Optional pre-initialized or mocked ONNX InferenceSession (for testing).
        """
        self._expected_sha256 = expected_sha256.lower()
        self._expected_size = expected_size
        self._num_threads = max(1, num_threads)
        self._cropper = MiniFASNetCropper()
        self._lock = threading.Lock()

        if model_path is None:
            # Resolve relative to standard candidate location
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            model_path = os.path.join(base_dir, "face_models", "candidates", DEFAULT_MODEL_FILENAME)

        self._model_path = os.path.abspath(model_path)
        self._model_name = os.path.basename(self._model_path)

        if session is not None:
            self._session = session
            self._verified_sha256 = self._expected_sha256
        else:
            self._verify_model_file()
            self._session = self._init_onnx_session()

        # Validate and record I/O metadata
        try:
            inputs = self._session.get_inputs()
            outputs = self._session.get_outputs()
            self._input_name = inputs[0].name
            self._output_name = outputs[0].name
        except Exception as e:
            raise PADModelUnavailable(f"Failed to query ONNX session I/O metadata: {e}") from e

    def _verify_model_file(self) -> None:
        """Validates existence, file size, and SHA-256 hash of the candidate model file."""
        if not os.path.isfile(self._model_path):
            raise PADModelUnavailable(f"PAD model file not found at: {self._model_path}")

        actual_size = os.path.getsize(self._model_path)
        if actual_size != self._expected_size:
            raise PADModelUnavailable(
                f"PAD model size mismatch: expected {self._expected_size} bytes, got {actual_size} bytes"
            )

        actual_sha256 = compute_file_sha256(self._model_path)
        if actual_sha256 != self._expected_sha256:
            raise PADModelUnavailable(
                f"PAD model SHA-256 mismatch! Expected {self._expected_sha256}, got {actual_sha256}"
            )
        self._verified_sha256 = actual_sha256

    def _init_onnx_session(self) -> ort.InferenceSession:
        """Instantiates CPU-only ONNX Runtime InferenceSession with optimizations."""
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self._num_threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            return ort.InferenceSession(
                self._model_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"]
            )
        except Exception as e:
            raise PADModelUnavailable(f"Failed to initialize ONNX Runtime session: {e}") from e

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_sha256(self) -> str:
        return self._verified_sha256

    def evaluate_tensor(
        self,
        tensor: np.ndarray,
        threshold: Optional[float] = None
    ) -> PADResult:
        """
        Runs inference on a preprocessed float32 tensor of shape (1, 3, 80, 80).

        Args:
            tensor: Input numpy array of shape (1, 3, 80, 80).
            threshold: Optional operational threshold for liveness evaluation.
                       If None, is_live is set to None (experimental default).

        Returns:
            PADResult dataclass.
        """
        if not isinstance(tensor, np.ndarray):
            raise PADInvalidInputError(f"Input tensor must be a numpy ndarray, got {type(tensor)}")

        if tensor.ndim != 4 or tensor.shape != EXPECTED_INPUT_SHAPE:
            raise PADInvalidInputError(
                f"Input tensor must have shape {EXPECTED_INPUT_SHAPE}, got {tensor.shape}"
            )

        if not np.issubdtype(tensor.dtype, np.floating):
            raise PADInvalidInputError(f"Input tensor dtype must be floating point, got {tensor.dtype}")

        if np.isnan(tensor).any() or np.isinf(tensor).any():
            raise PADInvalidInputError("Input tensor contains NaN or Infinite values")

        tensor_f32 = np.ascontiguousarray(tensor, dtype=np.float32)

        start_time = time.perf_counter()
        try:
            with self._lock:
                outputs = self._session.run([self._output_name], {self._input_name: tensor_f32})
        except Exception as e:
            raise PADInferenceError(f"ONNX inference session execution failed: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if not outputs or len(outputs) == 0:
            raise PADInferenceError("ONNX session returned empty output list")

        logits = outputs[0]
        if not isinstance(logits, np.ndarray) or logits.shape != EXPECTED_OUTPUT_SHAPE:
            raise PADInferenceError(
                f"Unexpected model output shape: expected {EXPECTED_OUTPUT_SHAPE}, got {getattr(logits, 'shape', None)}"
            )

        if np.isnan(logits).any() or np.isinf(logits).any():
            raise PADInferenceError("Model inference produced NaN or Infinite logits")

        # Numerically stable softmax
        probs = stable_softmax(logits, axis=-1)[0]

        # Sanity check probability bounds
        if np.any(probs < 0.0) or np.any(probs > 1.0):
            raise PADInferenceError(f"Softmax probabilities out of [0, 1] range: {probs}")

        prob_sum = float(np.sum(probs))
        if not np.isclose(prob_sum, 1.0, atol=1e-5):
            raise PADInferenceError(f"Softmax probabilities do not sum to 1.0 (sum={prob_sum})")

        p_print = float(probs[0])
        p_live = float(probs[1])
        p_replay = float(probs[2])
        p_spoof = float(p_print + p_replay)

        pred_idx = int(np.argmax(probs))
        pred_name = CLASS_MAPPING.get(pred_idx, "unknown")
        is_live_argmax = bool(pred_idx == 1)

        # Operational decision logic: only evaluated when caller supplies an explicit threshold
        is_live_decision: Optional[bool] = None
        if threshold is not None:
            if not (0.0 <= threshold <= 1.0):
                raise PADInvalidInputError(f"Threshold must be in [0.0, 1.0], got {threshold}")
            is_live_decision = bool(p_live >= threshold)

        return PADResult(
            p_print=round(p_print, 6),
            p_live=round(p_live, 6),
            p_replay=round(p_replay, 6),
            p_spoof=round(p_spoof, 6),
            live_score=round(p_live, 6),
            spoof_score=round(p_spoof, 6),
            predicted_class_idx=pred_idx,
            predicted_class_name=pred_name,
            latency_ms=round(latency_ms, 3),
            model_name=self._model_name,
            model_sha256=self._verified_sha256,
            status="ok",
            is_live_argmax=is_live_argmax,
            is_live=is_live_decision,
        )

    def evaluate_image(
        self,
        image_bgr: np.ndarray,
        bbox: Sequence[Union[int, float]],
        bbox_format: str = "xywh",
        scale: float = 2.7,
        threshold: Optional[float] = None
    ) -> PADResult:
        """
        End-to-end preprocessing, bounding-box expansion, and liveness scoring.

        Args:
            image_bgr: Full frame numpy array in BGR channel layout.
            bbox: Bounding box coordinates (4-element sequence).
            bbox_format: 'xywh' or 'xyxy'.
            scale: Expansion scale factor (default: 2.7).
            threshold: Optional operational threshold.

        Returns:
            PADResult dataclass.
        """
        tensor = self._cropper.preprocess_to_tensor(
            image_bgr=image_bgr,
            bbox=bbox,
            bbox_format=bbox_format,
            scale=scale
        )
        return self.evaluate_tensor(tensor, threshold=threshold)


# ---------------------------------------------------------------------------
# Thread-Safe Factory / Singleton Helper
# ---------------------------------------------------------------------------

_global_engine: Optional[PADEngine] = None
_global_engine_lock = threading.Lock()


def get_pad_engine(model_path: Optional[str] = None, reload: bool = False) -> PADEngine:
    """
    Thread-safe factory function returning the shared PADEngine instance.
    Lazy-loads the model on first call.
    """
    global _global_engine
    with _global_engine_lock:
        if _global_engine is None or reload:
            _global_engine = PADEngine(model_path=model_path)
        return _global_engine
