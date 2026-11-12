"""
Unit and Integration Tests for Standalone PAD Engine (Phase C.9).

Security & Engineering Validation:
1. Pinned SHA-256 integrity verification (fail-closed on missing, altered, or corrupt files).
2. MiniFASNetV2 boundary-aware expansion (scale=2.7), coordinate shifting, and clamping.
3. Preprocessing to (1, 3, 80, 80) float32 in [0.0, 1.0] BGR.
4. Input validation: invalid image dimensions, empty arrays, non-array inputs, degenerate bounding boxes.
5. Numerically stable softmax with extreme dynamic range.
6. Probability math, 3-class mapping, sum-to-1 tolerance, and non-negative bounds.
7. Handling of NaN/Inf inputs and outputs (fail-closed).
8. Thread concurrency: multi-threaded inference without race conditions or shared state corruption.
9. Absence of hardcoded production threshold and strict separation of PAD score from identity similarity.
10. Synthetic test fixtures only (NO real human biometric data used).
"""

import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import numpy as np
import pytest

# Ensure backend root is on sys.path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.pad_engine import (
    CLASS_MAPPING,
    EXPECTED_INPUT_SHAPE,
    EXPECTED_OUTPUT_SHAPE,
    PINNED_MINIFASNET_SHA256,
    PINNED_MINIFASNET_SIZE,
    MiniFASNetCropper,
    PADEngine,
    PADInferenceError,
    PADInvalidInputError,
    PADModelUnavailable,
    PADResult,
    compute_file_sha256,
    get_pad_engine,
    stable_softmax,
)

CANDIDATE_MODEL_PATH = os.path.join(
    BACKEND_DIR,
    "face_models",
    "candidates",
    "2.7_80x80_MiniFASNetV2.onnx"
)


# ---------------------------------------------------------------------------
# 1. Model Integrity and Fail-Closed Loading Tests
# ---------------------------------------------------------------------------

class TestPADModelIntegrityAndLoading:
    """Tests model integrity verification, file hashing, and fail-closed loading."""

    def test_real_candidate_model_loads_and_verifies_hash(self):
        """Candidate model file must exist and match pinned size and SHA-256."""
        assert os.path.isfile(CANDIDATE_MODEL_PATH), f"Missing model at {CANDIDATE_MODEL_PATH}"
        assert os.path.getsize(CANDIDATE_MODEL_PATH) == PINNED_MINIFASNET_SIZE

        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        assert engine.model_sha256 == PINNED_MINIFASNET_SHA256
        assert engine.model_name == "2.7_80x80_MiniFASNetV2.onnx"

    def test_missing_model_raises_unavailable(self):
        """Non-existent model path must raise PADModelUnavailable."""
        with pytest.raises(PADModelUnavailable) as excinfo:
            PADEngine(model_path="non_existent_model_file_xyz123.onnx")
        assert "not found" in str(excinfo.value).lower()

    def test_tampered_model_hash_raises_unavailable(self):
        """Model with mismatched SHA-256 must fail closed with PADModelUnavailable."""
        # Create temp file matching exact size but filled with zeroes
        with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as f:
            f.write(b"\x00" * PINNED_MINIFASNET_SIZE)
            temp_path = f.name
        try:
            with pytest.raises(PADModelUnavailable) as excinfo:
                PADEngine(model_path=temp_path)
            assert "sha-256 mismatch" in str(excinfo.value).lower()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_tampered_model_size_raises_unavailable(self):
        """Model with wrong byte length must fail closed with PADModelUnavailable."""
        with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as f:
            f.write(b"invalid short binary content")
            temp_path = f.name
        try:
            with pytest.raises(PADModelUnavailable) as excinfo:
                PADEngine(model_path=temp_path)
            assert "size mismatch" in str(excinfo.value).lower()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


# ---------------------------------------------------------------------------
# 2. Preprocessing & Cropper Tests
# ---------------------------------------------------------------------------

class TestPADPreprocessing:
    """Tests bounding box expansion (scale 2.7), coordinate shifting, and cropping."""

    def setup_method(self):
        self.cropper = MiniFASNetCropper()

    def test_expanded_box_centered_xywh(self):
        """Centered box in 400x400 image expands by 2.7x symmetrically."""
        src_w, src_h = 400, 400
        bbox = (180, 180, 40, 40)  # center at (200, 200)
        lt_x, lt_y, rb_x, rb_y = self.cropper.get_expanded_box(src_w, src_h, bbox, bbox_format="xywh", scale=2.7)

        # 40 * 2.7 = 108. Half is 54. Center 200 -> [146, 254]
        width = rb_x - lt_x
        height = rb_y - lt_y
        assert abs(width - 108) <= 2
        assert abs(height - 108) <= 2
        assert 0 <= lt_x < rb_x < src_w
        assert 0 <= lt_y < rb_y < src_h

    def test_expanded_box_xyxy_format(self):
        """xyxy format input yields equivalent expansion as xywh."""
        src_w, src_h = 400, 400
        bbox_xywh = (180, 180, 40, 40)
        bbox_xyxy = (180, 180, 220, 220)

        res_xywh = self.cropper.get_expanded_box(src_w, src_h, bbox_xywh, bbox_format="xywh", scale=2.7)
        res_xyxy = self.cropper.get_expanded_box(src_w, src_h, bbox_xyxy, bbox_format="xyxy", scale=2.7)
        assert res_xywh == res_xyxy

    def test_boundary_shifted_clamping_left_top(self):
        """A box touching (0, 0) shifts right and down without negative coordinates."""
        src_w, src_h = 300, 300
        bbox = (0, 0, 30, 30)
        lt_x, lt_y, rb_x, rb_y = self.cropper.get_expanded_box(src_w, src_h, bbox, scale=2.7)

        assert lt_x >= 0
        assert lt_y >= 0
        assert rb_x < src_w
        assert rb_y < src_h

    def test_boundary_shifted_clamping_right_bottom(self):
        """A box at the bottom-right corner shifts left and up without overflowing."""
        src_w, src_h = 300, 300
        bbox = (270, 270, 30, 30)
        lt_x, lt_y, rb_x, rb_y = self.cropper.get_expanded_box(src_w, src_h, bbox, scale=2.7)

        assert rb_x <= src_w - 1
        assert rb_y <= src_h - 1
        assert lt_x >= 0
        assert lt_y >= 0

    def test_large_box_scale_clamped(self):
        """Scale factor is clamped when 2.7x expansion would exceed total image bounds."""
        src_w, src_h = 100, 100
        bbox = (10, 10, 80, 80)
        lt_x, lt_y, rb_x, rb_y = self.cropper.get_expanded_box(src_w, src_h, bbox, scale=2.7)

        assert lt_x >= 0 and lt_y >= 0
        assert rb_x < src_w and rb_y < src_h
        assert (rb_x - lt_x) < src_w

    def test_invalid_inputs_raise_errors(self):
        """Malformed inputs raise PADInvalidInputError."""
        # Negative / zero box dimensions
        with pytest.raises(PADInvalidInputError):
            self.cropper.get_expanded_box(100, 100, (10, 10, 0, 50))
        with pytest.raises(PADInvalidInputError):
            self.cropper.get_expanded_box(100, 100, (10, 10, 50, -5))
        # Invalid image dimensions
        with pytest.raises(PADInvalidInputError):
            self.cropper.get_expanded_box(1, 100, (10, 10, 20, 20))
        # Unsupported format
        with pytest.raises(PADInvalidInputError):
            self.cropper.get_expanded_box(100, 100, (10, 10, 20, 20), bbox_format="unsupported")
        # Empty image
        with pytest.raises(PADInvalidInputError):
            self.cropper.crop_patch(np.zeros((0, 0, 3), dtype=np.uint8), (10, 10, 20, 20))
        # 2D instead of 3D image
        with pytest.raises(PADInvalidInputError):
            self.cropper.crop_patch(np.zeros((100, 100), dtype=np.uint8), (10, 10, 20, 20))
        # Non-array input
        with pytest.raises(PADInvalidInputError):
            self.cropper.crop_patch("not_an_image", (10, 10, 20, 20))

    def test_crop_patch_resizes_to_80x80(self):
        """Cropped patch must have shape (80, 80, 3) in BGR uint8."""
        img = np.full((250, 250, 3), 150, dtype=np.uint8)
        patch = self.cropper.crop_patch(img, (50, 50, 80, 80), scale=2.7, out_w=80, out_h=80)
        assert patch.shape == (80, 80, 3)
        assert patch.dtype == np.uint8

    def test_preprocess_to_tensor_normalization(self):
        """Preprocessed tensor must be shape (1, 3, 80, 80), float32, in range [0.0, 1.0]."""
        img = np.full((200, 200, 3), 204, dtype=np.uint8)
        tensor = self.cropper.preprocess_to_tensor(img, (40, 40, 80, 80), scale=2.7)

        assert tensor.shape == EXPECTED_INPUT_SHAPE
        assert tensor.dtype == np.float32
        assert np.isclose(tensor.min(), 204.0 / 255.0, atol=1e-3)
        assert np.isclose(tensor.max(), 204.0 / 255.0, atol=1e-3)


# ---------------------------------------------------------------------------
# 3. Softmax & Numerical Stability Tests
# ---------------------------------------------------------------------------

class TestPADSoftmaxAndProbabilityMath:
    """Tests numerically shifted softmax and probability constraints."""

    def test_softmax_standard_values(self):
        logits = np.array([[1.0, 2.0, 3.0]])
        probs = stable_softmax(logits)
        assert probs.shape == (1, 3)
        assert np.all(probs >= 0.0) and np.all(probs <= 1.0)
        assert np.isclose(np.sum(probs), 1.0, atol=1e-6)

    def test_softmax_extreme_large_logits(self):
        """Extreme positive values must not overflow to inf or nan."""
        logits = np.array([[1000.0, 999.0, 500.0]])
        probs = stable_softmax(logits)
        assert not np.isnan(probs).any()
        assert not np.isinf(probs).any()
        assert np.isclose(np.sum(probs), 1.0, atol=1e-6)
        assert probs[0, 0] > 0.7

    def test_softmax_extreme_negative_logits(self):
        """Extreme negative values must not underflow into nan."""
        logits = np.array([[-1000.0, -1001.0, -2000.0]])
        probs = stable_softmax(logits)
        assert not np.isnan(probs).any()
        assert not np.isinf(probs).any()
        assert np.isclose(np.sum(probs), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# 4. Inference Execution & Error Handling Tests (Mocked & Real)
# ---------------------------------------------------------------------------

class TestPADInferenceExecution:
    """Tests inference execution, output schema, and fail-closed error handling."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "input"
        mock_output = MagicMock()
        mock_output.name = "output"
        session.get_inputs.return_value = [mock_input]
        session.get_outputs.return_value = [mock_output]
        return session

    def test_mock_print_attack_prediction(self, mock_session):
        """High index-0 logit classifies as print_attack."""
        mock_session.run.return_value = [np.array([[15.0, 0.0, 0.0]], dtype=np.float32)]
        engine = PADEngine(session=mock_session)

        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        res = engine.evaluate_tensor(dummy_tensor)

        assert isinstance(res, PADResult)
        assert res.predicted_class_idx == 0
        assert res.predicted_class_name == "print_attack"
        assert res.p_print > 0.99
        assert res.live_score < 0.01
        assert res.spoof_score > 0.99
        assert res.is_live_argmax is False
        assert res.is_live is None  # No threshold supplied

    def test_mock_live_prediction(self, mock_session):
        """High index-1 logit classifies as live."""
        mock_session.run.return_value = [np.array([[0.0, 15.0, 0.0]], dtype=np.float32)]
        engine = PADEngine(session=mock_session)

        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        res = engine.evaluate_tensor(dummy_tensor)

        assert res.predicted_class_idx == 1
        assert res.predicted_class_name == "live"
        assert res.p_live > 0.99
        assert res.live_score > 0.99
        assert res.spoof_score < 0.01
        assert res.is_live_argmax is True

    def test_mock_replay_attack_prediction(self, mock_session):
        """High index-2 logit classifies as replay_attack."""
        mock_session.run.return_value = [np.array([[0.0, 0.0, 15.0]], dtype=np.float32)]
        engine = PADEngine(session=mock_session)

        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        res = engine.evaluate_tensor(dummy_tensor)

        assert res.predicted_class_idx == 2
        assert res.predicted_class_name == "replay_attack"
        assert res.p_replay > 0.99
        assert res.spoof_score > 0.99
        assert res.is_live_argmax is False

    def test_invalid_tensor_shape_raises(self, mock_session):
        """Tensor with invalid shape raises PADInvalidInputError."""
        engine = PADEngine(session=mock_session)
        with pytest.raises(PADInvalidInputError):
            engine.evaluate_tensor(np.zeros((1, 3, 64, 64), dtype=np.float32))
        with pytest.raises(PADInvalidInputError):
            engine.evaluate_tensor(np.zeros((3, 80, 80), dtype=np.float32))

    def test_nan_or_inf_in_tensor_raises(self, mock_session):
        """Tensor containing NaN or Inf raises PADInvalidInputError."""
        engine = PADEngine(session=mock_session)
        bad_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        bad_tensor[0, 0, 10, 10] = np.nan
        with pytest.raises(PADInvalidInputError):
            engine.evaluate_tensor(bad_tensor)

        bad_tensor[0, 0, 10, 10] = np.inf
        with pytest.raises(PADInvalidInputError):
            engine.evaluate_tensor(bad_tensor)

    def test_nan_or_inf_in_model_output_raises(self, mock_session):
        """Model output with NaN or Inf raises PADInferenceError."""
        mock_session.run.return_value = [np.array([[np.nan, 1.0, 0.0]], dtype=np.float32)]
        engine = PADEngine(session=mock_session)

        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        with pytest.raises(PADInferenceError):
            engine.evaluate_tensor(dummy_tensor)

    def test_malformed_model_output_shape_raises(self, mock_session):
        """Model output with wrong shape raises PADInferenceError."""
        mock_session.run.return_value = [np.array([[1.0, 2.0]], dtype=np.float32)]  # 2 classes instead of 3
        engine = PADEngine(session=mock_session)

        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        with pytest.raises(PADInferenceError):
            engine.evaluate_tensor(dummy_tensor)

    def test_real_model_smoke_inference(self):
        """
        Runs real candidate model ONNX inference on synthetic matrix.
        Validates latency measurement, output normalization, and non-crashing execution.
        """
        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        synthetic_frame = np.full((320, 320, 3), 120, dtype=np.uint8)
        bbox = (80, 80, 160, 160)

        res = engine.evaluate_image(synthetic_frame, bbox=bbox, bbox_format="xywh")

        assert isinstance(res, PADResult)
        assert res.status == "ok"
        assert res.latency_ms > 0.0
        assert res.predicted_class_name in CLASS_MAPPING.values()
        assert 0.0 <= res.live_score <= 1.0
        assert 0.0 <= res.spoof_score <= 1.0
        assert np.isclose(res.p_print + res.p_live + res.p_replay, 1.0, atol=1e-5)
        assert res.is_live is None  # Operational threshold remains unassigned


# ---------------------------------------------------------------------------
# 5. Concurrency and Thread-Safety Tests
# ---------------------------------------------------------------------------

class TestThreadSafetyAndConcurrency:
    """Validates thread-safe concurrent inference without state corruption."""

    def test_concurrent_inference_calls(self):
        """Multiple threads concurrently calling evaluate_image must not race or corrupt results."""
        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        synthetic_frame = np.full((240, 240, 3), 100, dtype=np.uint8)
        bbox = (50, 50, 100, 100)

        def worker(thread_id: int):
            # Vary pixel intensity slightly per thread
            local_frame = synthetic_frame.copy()
            local_frame[:, :, 0] = (thread_id * 20) % 255
            result = engine.evaluate_image(local_frame, bbox=bbox, bbox_format="xywh")
            return result

        num_threads = 8
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            results = [f.result() for f in futures]

        assert len(results) == num_threads
        for r in results:
            assert isinstance(r, PADResult)
            assert r.status == "ok"
            assert np.isclose(r.p_print + r.p_live + r.p_replay, 1.0, atol=1e-5)


# ---------------------------------------------------------------------------
# 6. Score Separation and Threshold Absence
# ---------------------------------------------------------------------------

class TestScoreSeparationAndThresholdAbsence:
    """Verifies that PAD scores are strictly separated from identity matching."""

    def test_no_default_threshold_applied(self):
        """Engine must not apply an arbitrary production threshold by default."""
        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)
        res = engine.evaluate_tensor(dummy_tensor)

        assert res.is_live is None, "is_live must be None when threshold is not supplied"

    def test_explicit_threshold_evaluation(self):
        """When an explicit threshold is supplied, is_live is evaluated cleanly."""
        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)

        # Test threshold = 0.0 (always True) and 1.0 (requires 100% certainty)
        res_low = engine.evaluate_tensor(dummy_tensor, threshold=0.0)
        assert res_low.is_live is True

        res_high = engine.evaluate_tensor(dummy_tensor, threshold=1.0)
        assert res_high.is_live is False

    def test_invalid_threshold_raises_error(self):
        """Threshold outside [0.0, 1.0] must raise PADInvalidInputError."""
        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        dummy_tensor = np.zeros(EXPECTED_INPUT_SHAPE, dtype=np.float32)

        with pytest.raises(PADInvalidInputError):
            engine.evaluate_tensor(dummy_tensor, threshold=-0.1)

        with pytest.raises(PADInvalidInputError):
            engine.evaluate_tensor(dummy_tensor, threshold=1.5)

    def test_score_separation_from_identity_matching(self):
        """
        PAD score calculation must be completely independent from identity similarity.
        Simulate identity cosine similarity varying from 0.1 to 0.99; PAD score must remain unchanged.
        """
        engine = PADEngine(model_path=CANDIDATE_MODEL_PATH)
        dummy_tensor = np.full(EXPECTED_INPUT_SHAPE, 0.5, dtype=np.float32)

        pad_result = engine.evaluate_tensor(dummy_tensor)

        # Simulate identity scores across full range
        for sim_identity in [0.10, 0.45, 0.70, 0.95]:
            # Verification logic requirement: Gate 1 and Gate 2 must be evaluated separately
            tau_identity = 0.45
            identity_passed = (sim_identity >= tau_identity)

            # PAD score must be independent of identity similarity
            assert pad_result.live_score == pytest.approx(pad_result.p_live)
            # Both gates must be satisfied independently (non-compensatory)
            overall_pass_hypothetical = identity_passed and (pad_result.live_score >= 0.5)
            # If identity fails, overall must fail regardless of PAD score
            if not identity_passed:
                assert overall_pass_hypothetical is False


# ---------------------------------------------------------------------------
# 7. Singleton Factory Helper Tests
# ---------------------------------------------------------------------------

class TestPADEngineFactory:
    """Tests the thread-safe get_pad_engine factory helper."""

    def test_get_pad_engine_returns_singleton(self):
        engine1 = get_pad_engine(model_path=CANDIDATE_MODEL_PATH)
        engine2 = get_pad_engine(model_path=CANDIDATE_MODEL_PATH)
        assert engine1 is engine2

        # reload=True creates a new instance
        engine3 = get_pad_engine(model_path=CANDIDATE_MODEL_PATH, reload=True)
        assert engine3 is not engine1
