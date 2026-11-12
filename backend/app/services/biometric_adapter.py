"""
Biometric Dual-Gate Adapter - Phase C.11C (Isolated Service Adapter)

Coordinates already-computed Gate 1 (Identity Similarity) and Gate 2 (Presentation
Attack Detection) results using strict non-compensatory decision logic.

Architectural and Security Invariants:
1. Pure Logic Adapter: Does NOT decode images, run ONNX inference, access the
   database, consume challenges, or call live routes.
2. Strict Non-Compensatory Logic:
       Verified <==> (Identity Gate Passed AND PAD Gate Passed)
   Scores are NEVER averaged, weighted, or combined. A high score on one gate
   cannot compensate for a failure on the other.
3. Independent Thresholds:
   Identity threshold (tau_id) and PAD threshold (tau_pad) are completely decoupled.
   Both thresholds are strictly required to be explicitly configured numeric values in (0.0, 1.0).
   Boolean values are strictly rejected before numeric inspection.
4. Fail-Closed on Unconfigured Threshold:
   Neither gate defaults silently to an arbitrary threshold. The identity threshold
   must be explicitly supplied to evaluate(); omitting it raises a TypeError at the
   API boundary. If None or invalid, it fails closed (CONFIG_ERROR_THRESHOLD).
   If the PAD threshold is None, uncalibrated, or invalid in enforcing mode, the
   adapter fails closed (CONFIG_ERROR_THRESHOLD). It never silently defaults to
   an uncalibrated threshold.
5. Fail-Closed on Malformed Input / Infrastructure Faults:
   NaN, Inf, missing inputs, model unavailability, and inference faults are
   treated as non-success. Infrastructure failures are classified separately
   from biometric rejections so challenge-consumption policies can distinguish them.
6. Zero Biometric Logging:
   Does NOT log biometric scores, facial features, embeddings, landmarks, session IDs,
   student names, or roll numbers.
7. Disconnected from Live Routes:
   This module is completely isolated and is not imported by live face-verification routes.
"""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Dict, Optional, Tuple, Union

# Optional import of PADResult for native type interoperability
try:
    from app.services.pad_engine import PADResult
except ImportError:
    PADResult = None  # type: ignore


# ---------------------------------------------------------------------------
# Enums and Structured Outcomes
# ---------------------------------------------------------------------------

class GateDecision(str, Enum):
    """Evaluation status of an individual gate."""
    PASSED = "passed"
    REJECTED = "rejected"
    BYPASSED = "bypassed"
    UNCONFIGURED = "unconfigured"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    INVALID_INPUT = "invalid_input"


class DualGateOutcome(str, Enum):
    """Categorized overall outcome of dual-gate evaluation."""
    SUCCESS = "success"
    BIOMETRIC_REJECT_IDENTITY = "biometric_reject_identity"
    BIOMETRIC_REJECT_PAD = "biometric_reject_pad"
    BIOMETRIC_REJECT_BOTH = "biometric_reject_both"
    CONFIG_ERROR_THRESHOLD = "config_error_threshold"
    INFRASTRUCTURE_ERROR_PAD = "infrastructure_error_pad"
    INFRASTRUCTURE_ERROR_IDENTITY = "infrastructure_error_identity"
    INVALID_INPUT = "invalid_input"


# ---------------------------------------------------------------------------
# Typed Input Structs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IdentityGateInput:
    """Already-computed identity matching result."""
    similarity_score: float
    status: str = "ok"
    error_details: Optional[str] = None


@dataclass(frozen=True)
class PADGateInput:
    """Already-computed presentation attack detection result."""
    live_score: float
    status: str = "ok"
    predicted_class: Optional[str] = None
    error_details: Optional[str] = None


# ---------------------------------------------------------------------------
# Typed Result Structs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SingleGateSummary:
    """Immutable evaluation summary for one gate."""
    passed: bool
    score: Optional[float]
    threshold: Optional[float]
    decision: GateDecision
    category: str


@dataclass(frozen=True)
class DualGateVerificationResult:
    """
    Immutable comprehensive result of dual-gate evaluation.
    Provides typed outcomes for caller-level error and challenge mapping.
    """
    verified: bool
    outcome: DualGateOutcome
    identity_gate: SingleGateSummary
    pad_gate: SingleGateSummary
    mode: str
    is_infrastructure_failure: bool
    can_retry_challenge: bool
    internal_diagnostic: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BiometricAdapterError(Exception):
    """Base exception for biometric adapter configuration or validation errors."""


class ThresholdConfigurationError(BiometricAdapterError):
    """Operational threshold is unconfigured, None, or out of bounds."""


class BiometricInputError(ValueError, BiometricAdapterError):
    """Provided score or result is NaN, Inf, empty, or malformed."""


# ---------------------------------------------------------------------------
# Standalone BiometricDualGateAdapter
# ---------------------------------------------------------------------------

class BiometricDualGateAdapter:
    """
    Standalone Dual-Gate Verification Adapter.
    Enforces non-compensatory Boolean AND logic between Identity and PAD gates.
    """

    SUPPORTED_MODES = ("enforcing", "shadow", "disabled")

    @staticmethod
    def _extract_identity_data(
        raw_input: Union[float, int, IdentityGateInput, Dict[str, Any]]
    ) -> Tuple[Optional[float], str, Optional[str]]:
        """Extracts (score, status, error_details) from diverse identity inputs."""
        if isinstance(raw_input, bool):
            return None, "invalid_type", "Identity input cannot be boolean"

        if isinstance(raw_input, (float, int)):
            return float(raw_input), "ok", None

        if isinstance(raw_input, IdentityGateInput):
            return raw_input.similarity_score, raw_input.status, raw_input.error_details

        if isinstance(raw_input, dict):
            score = raw_input.get("similarity_score", raw_input.get("score"))
            status = raw_input.get("status", "ok")
            error = raw_input.get("error_details", raw_input.get("error"))
            if isinstance(score, bool):
                return None, "invalid_type", "Identity score in dict cannot be boolean"
            return (float(score) if score is not None else None), str(status), (str(error) if error else None)

        return None, "invalid_type", f"Unsupported identity input type: {type(raw_input)}"

    @staticmethod
    def _extract_pad_data(
        raw_input: Union[float, int, PADGateInput, Any, Dict[str, Any], None]
    ) -> Tuple[Optional[float], str, Optional[str], Optional[str]]:
        """Extracts (live_score, status, predicted_class, error_details) from diverse PAD inputs."""
        if raw_input is None:
            return None, "missing_input", None, "PAD input is None"

        if isinstance(raw_input, bool):
            return None, "invalid_type", None, "PAD input cannot be boolean"

        if isinstance(raw_input, (float, int)):
            return float(raw_input), "ok", None, None

        if isinstance(raw_input, PADGateInput):
            return raw_input.live_score, raw_input.status, raw_input.predicted_class, raw_input.error_details

        # Interoperability with PADResult dataclass from pad_engine.py
        if PADResult is not None and isinstance(raw_input, PADResult):
            return raw_input.live_score, raw_input.status, raw_input.predicted_class_name, None

        if isinstance(raw_input, dict):
            score = raw_input.get("live_score", raw_input.get("score", raw_input.get("p_live")))
            status = raw_input.get("status", "ok")
            pred_class = raw_input.get("predicted_class_name", raw_input.get("predicted_class"))
            error = raw_input.get("error_details", raw_input.get("error"))
            if isinstance(score, bool):
                return None, "invalid_type", None, "PAD score in dict cannot be boolean"
            return (float(score) if score is not None else None), str(status), (str(pred_class) if pred_class else None), (str(error) if error else None)

        # Generic duck-typing fallback for dataclasses with live_score
        if hasattr(raw_input, "live_score") and hasattr(raw_input, "status"):
            score = getattr(raw_input, "live_score")
            status = getattr(raw_input, "status")
            pred_class = getattr(raw_input, "predicted_class_name", None) or getattr(raw_input, "predicted_class", None)
            if isinstance(score, bool):
                return None, "invalid_type", None, "PAD score cannot be boolean"
            return (float(score) if score is not None else None), str(status), (str(pred_class) if pred_class else None), None

        return None, "invalid_type", None, f"Unsupported PAD input type: {type(raw_input)}"

    def evaluate(
        self,
        identity_result: Union[float, int, IdentityGateInput, Dict[str, Any]],
        identity_threshold: float,
        pad_result: Union[float, int, PADGateInput, Any, Dict[str, Any], None] = None,
        pad_threshold: Optional[float] = None,
        mode: str = "enforcing"
    ) -> DualGateVerificationResult:
        """
        Evaluates already-computed identity and PAD results against thresholds.

        Args:
            identity_result: Float cosine similarity or IdentityGateInput.
            pad_result: Float live_score, PADResult, PADGateInput, or None.
            identity_threshold: Cosine similarity threshold (strictly between 0.0 and 1.0).
            pad_threshold: Liveness probability threshold (strictly between 0.0 and 1.0).
                           Required in enforcing mode.
            mode: 'enforcing' (both gates required), 'shadow' (identity enforced, PAD measured),
                  or 'disabled' (identity only, PAD bypassed).

        Returns:
            DualGateVerificationResult with typed outcome and retry guidance.
        """
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode '{mode}'; expected one of {self.SUPPORTED_MODES}")

        # -------------------------------------------------------------------
        # 1. Identity Threshold Validation
        # -------------------------------------------------------------------
        # Reject booleans explicitly (since bool subclasses int in Python), None,
        # non-numeric, NaN, and infinite values.
        if (
            isinstance(identity_threshold, bool)
            or not isinstance(identity_threshold, (int, float))
            or not math.isfinite(identity_threshold)
        ):
            return self._build_config_error(
                msg=f"Identity threshold must be a finite number (boolean and non-numeric values rejected, got {type(identity_threshold).__name__})",
                id_thresh=None, pad_thresh=pad_threshold, mode=normalized_mode
            )

        id_thresh = float(identity_threshold)
        if not (0.0 < id_thresh < 1.0):
            return self._build_config_error(
                msg=f"Identity threshold out of bounds (must be strictly in (0.0, 1.0), got {id_thresh})",
                id_thresh=id_thresh, pad_thresh=pad_threshold, mode=normalized_mode
            )

        # -------------------------------------------------------------------
        # 2. Extract and Validate Identity Input (Gate 1)
        # -------------------------------------------------------------------
        id_score, id_status, id_err = self._extract_identity_data(identity_result)

        if id_status != "ok":
            return DualGateVerificationResult(
                verified=False,
                outcome=DualGateOutcome.INFRASTRUCTURE_ERROR_IDENTITY,
                identity_gate=SingleGateSummary(
                    passed=False, score=id_score, threshold=id_thresh,
                    decision=GateDecision.INFRASTRUCTURE_ERROR, category=id_status
                ),
                pad_gate=SingleGateSummary(
                    passed=False, score=None, threshold=pad_threshold,
                    decision=GateDecision.UNCONFIGURED, category="not_evaluated"
                ),
                mode=normalized_mode,
                is_infrastructure_failure=True,
                can_retry_challenge=True,
                internal_diagnostic=f"Identity gate infrastructure fault: {id_err or id_status}"
            )

        if id_score is None or not math.isfinite(id_score):
            return DualGateVerificationResult(
                verified=False,
                outcome=DualGateOutcome.INVALID_INPUT,
                identity_gate=SingleGateSummary(
                    passed=False, score=id_score, threshold=id_thresh,
                    decision=GateDecision.INVALID_INPUT, category="non_finite_or_missing"
                ),
                pad_gate=SingleGateSummary(
                    passed=False, score=None, threshold=pad_threshold,
                    decision=GateDecision.UNCONFIGURED, category="not_evaluated"
                ),
                mode=normalized_mode,
                is_infrastructure_failure=False,
                can_retry_challenge=False,
                internal_diagnostic="Identity score is NaN, Infinite, or missing"
            )

        id_passed = bool(id_score >= id_thresh)
        id_summary = SingleGateSummary(
            passed=id_passed,
            score=round(float(id_score), 6),
            threshold=id_thresh,
            decision=GateDecision.PASSED if id_passed else GateDecision.REJECTED,
            category="match_success" if id_passed else "similarity_too_low"
        )

        # -------------------------------------------------------------------
        # 3. Mode: Disabled (Identity Gate Only)
        # -------------------------------------------------------------------
        if normalized_mode == "disabled":
            pad_summary = SingleGateSummary(
                passed=True, score=None, threshold=None,
                decision=GateDecision.BYPASSED, category="mode_disabled"
            )
            return DualGateVerificationResult(
                verified=id_passed,
                outcome=DualGateOutcome.SUCCESS if id_passed else DualGateOutcome.BIOMETRIC_REJECT_IDENTITY,
                identity_gate=id_summary,
                pad_gate=pad_summary,
                mode=normalized_mode,
                is_infrastructure_failure=False,
                can_retry_challenge=not id_passed,
                internal_diagnostic="Verification evaluated in disabled mode (Identity only)"
            )

        # -------------------------------------------------------------------
        # 4. Mode: Shadow or Enforcing -> Validate PAD Threshold & Input
        # -------------------------------------------------------------------
        # In enforcing mode, PAD threshold is strictly required and must be in (0.0, 1.0).
        # Reject booleans explicitly, non-numeric, NaN, infinite, and out-of-range values.
        pad_thresh: Optional[float] = None
        if pad_threshold is not None:
            if (
                isinstance(pad_threshold, bool)
                or not isinstance(pad_threshold, (int, float))
                or not math.isfinite(pad_threshold)
                or not (0.0 < float(pad_threshold) < 1.0)
            ):
                if normalized_mode == "enforcing":
                    return self._build_config_error(
                        msg=f"PAD threshold out of bounds or invalid (must be strictly in (0.0, 1.0) and non-boolean, got {pad_threshold})",
                        id_thresh=id_thresh, pad_thresh=None, mode=normalized_mode
                    )
            else:
                pad_thresh = float(pad_threshold)
        elif normalized_mode == "enforcing":
            # Strict fail-closed: Enforcing mode refuses to evaluate without a calibrated threshold
            return self._build_config_error(
                msg="PAD operational threshold is unconfigured (None) in enforcing mode",
                id_thresh=id_thresh, pad_thresh=None, mode=normalized_mode
            )

        # Extract and validate PAD input
        pad_score, pad_status, pad_pred_class, pad_err = self._extract_pad_data(pad_result)

        # Check for infrastructure errors on PAD gate
        if pad_status in ("model_unavailable", "service_unavailable", "pad_unavailable"):
            if normalized_mode == "enforcing":
                return DualGateVerificationResult(
                    verified=False,
                    outcome=DualGateOutcome.INFRASTRUCTURE_ERROR_PAD,
                    identity_gate=id_summary,
                    pad_gate=SingleGateSummary(
                        passed=False, score=None, threshold=pad_thresh,
                        decision=GateDecision.INFRASTRUCTURE_ERROR, category=pad_status
                    ),
                    mode=normalized_mode,
                    is_infrastructure_failure=True,
                    can_retry_challenge=True,
                    internal_diagnostic=f"PAD model unavailable: {pad_err or pad_status}"
                )
            # In shadow mode, record infrastructure failure on PAD without blocking identity pass
            pad_summary = SingleGateSummary(
                passed=False, score=None, threshold=pad_thresh,
                decision=GateDecision.INFRASTRUCTURE_ERROR, category=pad_status
            )
            return DualGateVerificationResult(
                verified=id_passed,
                outcome=DualGateOutcome.SUCCESS if id_passed else DualGateOutcome.BIOMETRIC_REJECT_IDENTITY,
                identity_gate=id_summary,
                pad_gate=pad_summary,
                mode=normalized_mode,
                is_infrastructure_failure=False,
                can_retry_challenge=not id_passed,
                internal_diagnostic=f"Shadow mode: Identity outcome preserved despite PAD fault ({pad_status})"
            )

        if pad_status in ("inference_error", "timeout", "numerical_fault"):
            if normalized_mode == "enforcing":
                return DualGateVerificationResult(
                    verified=False,
                    outcome=DualGateOutcome.INFRASTRUCTURE_ERROR_PAD,
                    identity_gate=id_summary,
                    pad_gate=SingleGateSummary(
                        passed=False, score=pad_score, threshold=pad_thresh,
                        decision=GateDecision.INFRASTRUCTURE_ERROR, category=pad_status
                    ),
                    mode=normalized_mode,
                    is_infrastructure_failure=True,
                    can_retry_challenge=True,
                    internal_diagnostic=f"PAD inference failure: {pad_err or pad_status}"
                )
            pad_summary = SingleGateSummary(
                passed=False, score=pad_score, threshold=pad_thresh,
                decision=GateDecision.INFRASTRUCTURE_ERROR, category=pad_status
            )
            return DualGateVerificationResult(
                verified=id_passed,
                outcome=DualGateOutcome.SUCCESS if id_passed else DualGateOutcome.BIOMETRIC_REJECT_IDENTITY,
                identity_gate=id_summary,
                pad_gate=pad_summary,
                mode=normalized_mode,
                is_infrastructure_failure=False,
                can_retry_challenge=not id_passed,
                internal_diagnostic=f"Shadow mode: Identity outcome preserved despite PAD fault ({pad_status})"
            )

        # Validate PAD score numerical bounds
        if pad_score is None or not math.isfinite(pad_score) or pad_score < 0.0 or pad_score > 1.0:
            if normalized_mode == "enforcing":
                return DualGateVerificationResult(
                    verified=False,
                    outcome=DualGateOutcome.INVALID_INPUT,
                    identity_gate=id_summary,
                    pad_gate=SingleGateSummary(
                        passed=False, score=pad_score, threshold=pad_thresh,
                        decision=GateDecision.INVALID_INPUT, category="score_out_of_bounds_or_non_finite"
                    ),
                    mode=normalized_mode,
                    is_infrastructure_failure=False,
                    can_retry_challenge=False,
                    internal_diagnostic=f"PAD score is invalid, non-finite, or out of [0, 1] range: {pad_score}"
                )
            pad_summary = SingleGateSummary(
                passed=False, score=pad_score, threshold=pad_thresh,
                decision=GateDecision.INVALID_INPUT, category="score_out_of_bounds"
            )
            return DualGateVerificationResult(
                verified=id_passed,
                outcome=DualGateOutcome.SUCCESS if id_passed else DualGateOutcome.BIOMETRIC_REJECT_IDENTITY,
                identity_gate=id_summary,
                pad_gate=pad_summary,
                mode=normalized_mode,
                is_infrastructure_failure=False,
                can_retry_challenge=not id_passed,
                internal_diagnostic="Shadow mode: Invalid PAD score ignored"
            )

        # Evaluate PAD Gate
        pad_passed = bool(pad_thresh is not None and pad_score >= pad_thresh)
        pad_category = "genuine_live" if pad_passed else (pad_pred_class or "suspected_spoof")
        pad_summary = SingleGateSummary(
            passed=pad_passed,
            score=round(float(pad_score), 6),
            threshold=pad_thresh,
            decision=GateDecision.PASSED if pad_passed else GateDecision.REJECTED,
            category=pad_category
        )

        # -------------------------------------------------------------------
        # 5. Final Decision Synthesis
        # -------------------------------------------------------------------
        if normalized_mode == "shadow":
            # Shadow telemetry mode: verification is driven by Gate 1, but PAD is fully measured
            return DualGateVerificationResult(
                verified=id_passed,
                outcome=DualGateOutcome.SUCCESS if id_passed else DualGateOutcome.BIOMETRIC_REJECT_IDENTITY,
                identity_gate=id_summary,
                pad_gate=pad_summary,
                mode=normalized_mode,
                is_infrastructure_failure=False,
                can_retry_challenge=not id_passed,
                internal_diagnostic="Shadow mode: Gate 1 enforced; Gate 2 measured for telemetry"
            )

        # Enforcing Mode: Strict Non-Compensatory Boolean AND Logic
        overall_verified = bool(id_passed and pad_passed)

        if overall_verified:
            outcome = DualGateOutcome.SUCCESS
            diag = "Dual-gate verification succeeded (Identity and PAD passed)"
        elif not id_passed and pad_passed:
            outcome = DualGateOutcome.BIOMETRIC_REJECT_IDENTITY
            diag = "Biometric rejection: Identity similarity below threshold"
        elif id_passed and not pad_passed:
            outcome = DualGateOutcome.BIOMETRIC_REJECT_PAD
            diag = f"Biometric rejection: PAD classified as spoof ({pad_category})"
        else:
            outcome = DualGateOutcome.BIOMETRIC_REJECT_BOTH
            diag = "Biometric rejection: Both Identity and PAD failed"

        return DualGateVerificationResult(
            verified=overall_verified,
            outcome=outcome,
            identity_gate=id_summary,
            pad_gate=pad_summary,
            mode=normalized_mode,
            is_infrastructure_failure=False,
            can_retry_challenge=not overall_verified,
            internal_diagnostic=diag
        )

    @staticmethod
    def _build_config_error(
        msg: str,
        id_thresh: Optional[float],
        pad_thresh: Optional[float],
        mode: str
    ) -> DualGateVerificationResult:
        """Helper to build consistent config error result with sanitized thresholds."""
        clean_id_thresh = (
            float(id_thresh)
            if (isinstance(id_thresh, (int, float)) and not isinstance(id_thresh, bool) and math.isfinite(id_thresh))
            else None
        )
        clean_pad_thresh = (
            float(pad_thresh)
            if (isinstance(pad_thresh, (int, float)) and not isinstance(pad_thresh, bool) and math.isfinite(pad_thresh))
            else None
        )
        return DualGateVerificationResult(
            verified=False,
            outcome=DualGateOutcome.CONFIG_ERROR_THRESHOLD,
            identity_gate=SingleGateSummary(
                passed=False, score=None, threshold=clean_id_thresh,
                decision=GateDecision.UNCONFIGURED, category="threshold_config_error"
            ),
            pad_gate=SingleGateSummary(
                passed=False, score=None, threshold=clean_pad_thresh,
                decision=GateDecision.UNCONFIGURED, category="threshold_config_error"
            ),
            mode=mode,
            is_infrastructure_failure=True,
            can_retry_challenge=True,
            internal_diagnostic=msg
        )
