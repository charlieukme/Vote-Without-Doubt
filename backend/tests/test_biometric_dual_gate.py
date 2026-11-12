"""
Unit Tests for Standalone BiometricDualGateAdapter (Phase C.11C).

Validates:
1. Both gates pass -> verification succeeds.
2. Identity passes but PAD rejects -> verification fails.
3. PAD passes but identity rejects -> verification fails.
4. Both gates reject -> verification fails.
5. Missing PAD threshold fails closed in enforcing mode.
6. Invalid identity threshold fails closed.
7. NaN and infinity in either score fails closed.
8. Missing or malformed results fail closed.
9. PAD model unavailable surfaces as infrastructure error, not successful verification.
10. Inference failure remains distinct from biometric rejection.
11. Identity score cannot compensate for PAD rejection.
12. PAD score cannot compensate for identity rejection.
13. Threshold boundaries behave deterministically at exact limits.
14. Zero logging of sensitive biometric scores or student/session identifiers.
15. Shadow mode preserves identity verification while measuring PAD.
16. Disabled mode bypasses PAD gate cleanly.
17. Native interoperability with PADResult dataclass.
18. Missing identity threshold raises TypeError at API boundary.
19. Boolean values (True, False) rejected as identity threshold.
20. Boolean values (True, False) rejected as PAD threshold in enforcing mode.
21. None, non-numeric, string, NaN, Inf, and out-of-range thresholds fail closed.
22. Boolean values rejected as raw score inputs.

Synthetic numeric inputs and mocks ONLY. Zero human biometric data.
"""

import logging
import math
import os
import sys
import pytest

# Ensure backend root is on sys.path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.services.biometric_adapter import (
    BiometricDualGateAdapter,
    DualGateOutcome,
    GateDecision,
    IdentityGateInput,
    PADGateInput,
)
from app.services.pad_engine import PADResult


@pytest.fixture
def adapter():
    return BiometricDualGateAdapter()


# ---------------------------------------------------------------------------
# Required Test Cases (1 to 14)
# ---------------------------------------------------------------------------

def test_case_1_both_gates_pass(adapter):
    """Test 1: Verification succeeds when both identity and PAD pass thresholds."""
    res = adapter.evaluate(
        identity_result=0.75,
        pad_result=0.92,
        identity_threshold=0.45,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res.verified is True
    assert res.outcome == DualGateOutcome.SUCCESS
    assert res.identity_gate.passed is True
    assert res.identity_gate.decision == GateDecision.PASSED
    assert res.pad_gate.passed is True
    assert res.pad_gate.decision == GateDecision.PASSED
    assert res.is_infrastructure_failure is False
    assert res.can_retry_challenge is False


def test_case_2_identity_passes_pad_rejects(adapter):
    """Test 2: Verification fails when identity matches but PAD flags a spoof."""
    res = adapter.evaluate(
        identity_result=0.88,
        pad_result=0.25,  # Suspected print attack
        identity_threshold=0.45,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res.verified is False
    assert res.outcome == DualGateOutcome.BIOMETRIC_REJECT_PAD
    assert res.identity_gate.passed is True
    assert res.pad_gate.passed is False
    assert res.pad_gate.decision == GateDecision.REJECTED
    assert res.is_infrastructure_failure is False
    assert res.can_retry_challenge is True


def test_case_3_pad_passes_identity_rejects(adapter):
    """Test 3: Verification fails when presentation is live but identity does not match."""
    res = adapter.evaluate(
        identity_result=0.20,  # Below 0.45 threshold
        pad_result=0.95,        # High liveness
        identity_threshold=0.45,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res.verified is False
    assert res.outcome == DualGateOutcome.BIOMETRIC_REJECT_IDENTITY
    assert res.identity_gate.passed is False
    assert res.pad_gate.passed is True
    assert res.is_infrastructure_failure is False
    assert res.can_retry_challenge is True


def test_case_4_both_gates_reject(adapter):
    """Test 4: Verification fails when both identity and PAD fail."""
    res = adapter.evaluate(
        identity_result=0.15,
        pad_result=0.10,
        identity_threshold=0.45,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res.verified is False
    assert res.outcome == DualGateOutcome.BIOMETRIC_REJECT_BOTH
    assert res.identity_gate.passed is False
    assert res.pad_gate.passed is False
    assert res.is_infrastructure_failure is False
    assert res.can_retry_challenge is True


def test_case_5_missing_pad_threshold_fails_closed(adapter):
    """Test 5: In enforcing mode, missing or None PAD threshold fails closed."""
    res = adapter.evaluate(
        identity_result=0.85,
        pad_result=0.95,
        identity_threshold=0.45,
        pad_threshold=None,  # Unconfigured threshold
        mode="enforcing"
    )
    assert res.verified is False
    assert res.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD
    assert res.is_infrastructure_failure is True
    assert res.can_retry_challenge is True
    assert "unconfigured" in res.internal_diagnostic.lower()


def test_case_6_invalid_identity_threshold_fails_closed(adapter):
    """Test 6: Invalid or non-finite identity thresholds fail closed."""
    for bad_thresh in [-0.5, 0.0, 1.0, 1.5, float('nan'), float('inf')]:
        res = adapter.evaluate(
            identity_result=0.75,
            pad_result=0.90,
            identity_threshold=bad_thresh,
            pad_threshold=0.80,
            mode="enforcing"
        )
        assert res.verified is False
        assert res.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD
        assert res.is_infrastructure_failure is True


def test_case_7_nan_and_inf_scores_fail_closed(adapter):
    """Test 7: NaN and Infinite scores on either gate fail closed."""
    # Identity score NaN/Inf
    res_nan_id = adapter.evaluate(
        identity_result=float('nan'),
        identity_threshold=0.45,
        pad_result=0.90,
        pad_threshold=0.80
    )
    assert res_nan_id.verified is False
    assert res_nan_id.outcome == DualGateOutcome.INVALID_INPUT

    res_inf_id = adapter.evaluate(
        identity_result=float('inf'),
        identity_threshold=0.45,
        pad_result=0.90,
        pad_threshold=0.80
    )
    assert res_inf_id.verified is False
    assert res_inf_id.outcome == DualGateOutcome.INVALID_INPUT

    # PAD score NaN/Inf
    res_nan_pad = adapter.evaluate(
        identity_result=0.70,
        identity_threshold=0.45,
        pad_result=float('nan'),
        pad_threshold=0.80
    )
    assert res_nan_pad.verified is False
    assert res_nan_pad.outcome == DualGateOutcome.INVALID_INPUT

    res_inf_pad = adapter.evaluate(
        identity_result=0.70,
        identity_threshold=0.45,
        pad_result=float('inf'),
        pad_threshold=0.80
    )
    assert res_inf_pad.verified is False
    assert res_inf_pad.outcome == DualGateOutcome.INVALID_INPUT


def test_case_8_missing_or_malformed_results(adapter):
    """Test 8: Missing, None, or unsupported types fail closed with INVALID_INPUT."""
    res_none_pad = adapter.evaluate(
        identity_result=0.70,
        identity_threshold=0.45,
        pad_result=None,
        pad_threshold=0.80
    )
    assert res_none_pad.verified is False
    assert res_none_pad.outcome == DualGateOutcome.INVALID_INPUT

    res_bad_type_id = adapter.evaluate(
        identity_result="invalid_string",
        identity_threshold=0.45,
        pad_result=0.90,
        pad_threshold=0.80
    )
    assert res_bad_type_id.verified is False
    assert res_bad_type_id.outcome == DualGateOutcome.INFRASTRUCTURE_ERROR_IDENTITY

    res_bad_type_pad = adapter.evaluate(
        identity_result=0.70,
        identity_threshold=0.45,
        pad_result=["invalid_list"],
        pad_threshold=0.80
    )
    assert res_bad_type_pad.verified is False
    assert res_bad_type_pad.outcome == DualGateOutcome.INVALID_INPUT


def test_case_9_pad_model_unavailable_infrastructure_outcome(adapter):
    """Test 9: Model unavailability is recognized as an infrastructure failure, not verification success."""
    pad_input = PADGateInput(live_score=0.0, status="model_unavailable", error_details="Weights missing")
    res = adapter.evaluate(
        identity_result=0.90,
        identity_threshold=0.45,
        pad_result=pad_input,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res.verified is False
    assert res.outcome == DualGateOutcome.INFRASTRUCTURE_ERROR_PAD
    assert res.is_infrastructure_failure is True
    assert res.can_retry_challenge is True
    assert res.pad_gate.decision == GateDecision.INFRASTRUCTURE_ERROR


def test_case_10_inference_failure_distinct_from_biometric_rejection(adapter):
    """Test 10: Inference exceptions (numerical fault, timeout) are distinct from spoof rejection."""
    pad_fault = PADGateInput(live_score=0.0, status="inference_error", error_details="ONNX session runtime error")
    res_fault = adapter.evaluate(
        identity_result=0.70,
        identity_threshold=0.45,
        pad_result=pad_fault,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res_fault.verified is False
    assert res_fault.outcome == DualGateOutcome.INFRASTRUCTURE_ERROR_PAD
    assert res_fault.is_infrastructure_failure is True

    # Compare with spoof rejection
    pad_spoof = PADGateInput(live_score=0.15, status="ok", predicted_class="print_attack")
    res_spoof = adapter.evaluate(
        identity_result=0.70,
        identity_threshold=0.45,
        pad_result=pad_spoof,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res_spoof.verified is False
    assert res_spoof.outcome == DualGateOutcome.BIOMETRIC_REJECT_PAD
    assert res_spoof.is_infrastructure_failure is False


def test_case_11_identity_score_cannot_compensate_for_pad_rejection(adapter):
    """Test 11: Near-perfect identity scores cannot compensate for low liveness score."""
    for high_id in [0.80, 0.90, 0.95, 0.99, 0.9999]:
        res = adapter.evaluate(
            identity_result=high_id,
            pad_result=0.10,  # Severe spoof
            identity_threshold=0.45,
            pad_threshold=0.80,
            mode="enforcing"
        )
        assert res.verified is False
        assert res.outcome == DualGateOutcome.BIOMETRIC_REJECT_PAD


def test_case_12_pad_score_cannot_compensate_for_identity_rejection(adapter):
    """Test 12: Near-perfect liveness scores cannot compensate for identity mismatch."""
    for high_pad in [0.80, 0.90, 0.95, 0.99, 0.9999]:
        res = adapter.evaluate(
            identity_result=0.40,  # Below 0.45
            pad_result=high_pad,
            identity_threshold=0.45,
            pad_threshold=0.80,
            mode="enforcing"
        )
        assert res.verified is False
        assert res.outcome == DualGateOutcome.BIOMETRIC_REJECT_IDENTITY


def test_case_13_threshold_boundaries_behave_deterministically(adapter):
    """Test 13: Exact threshold boundary values behave deterministically."""
    # Identity exact boundary at 0.45
    res_id_exact = adapter.evaluate(identity_result=0.45, pad_result=0.80, identity_threshold=0.45, pad_threshold=0.80)
    assert res_id_exact.identity_gate.passed is True
    assert res_id_exact.verified is True

    res_id_below = adapter.evaluate(identity_result=0.449999, pad_result=0.80, identity_threshold=0.45, pad_threshold=0.80)
    assert res_id_below.identity_gate.passed is False
    assert res_id_below.verified is False

    # PAD exact boundary at 0.80
    res_pad_exact = adapter.evaluate(identity_result=0.50, pad_result=0.80, identity_threshold=0.45, pad_threshold=0.80)
    assert res_pad_exact.pad_gate.passed is True
    assert res_pad_exact.verified is True

    res_pad_below = adapter.evaluate(identity_result=0.50, pad_result=0.799999, identity_threshold=0.45, pad_threshold=0.80)
    assert res_pad_below.pad_gate.passed is False
    assert res_pad_below.verified is False


def test_case_14_no_unexpected_logging_of_sensitive_data(adapter, caplog):
    """Test 14: Adapter execution generates zero logs containing biometric scores or identifiers."""
    with caplog.at_level(logging.DEBUG):
        adapter.evaluate(
            identity_result=IdentityGateInput(similarity_score=0.85),
            pad_result=PADGateInput(live_score=0.92, predicted_class="live"),
            identity_threshold=0.45,
            pad_threshold=0.80,
            mode="enforcing"
        )
    # The adapter must remain completely silent
    assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# Additional Mode and Interoperability Tests
# ---------------------------------------------------------------------------

def test_case_15_shadow_mode_behavior(adapter):
    """Test 15: Shadow mode evaluates PAD without overriding Gate 1 identity pass."""
    res = adapter.evaluate(
        identity_result=0.60,  # Identity passes
        pad_result=0.15,        # Spoof detected
        identity_threshold=0.45,
        pad_threshold=0.80,
        mode="shadow"
    )
    # In shadow mode, verified outcome matches identity gate
    assert res.verified is True
    assert res.outcome == DualGateOutcome.SUCCESS
    assert res.identity_gate.passed is True
    # But PAD gate accurately records failure for telemetry
    assert res.pad_gate.passed is False
    assert res.pad_gate.decision == GateDecision.REJECTED


def test_case_16_disabled_mode_behavior(adapter):
    """Test 16: Disabled mode bypasses PAD evaluation completely."""
    res = adapter.evaluate(
        identity_result=0.65,
        pad_result=None,
        identity_threshold=0.45,
        pad_threshold=None,
        mode="disabled"
    )
    assert res.verified is True
    assert res.outcome == DualGateOutcome.SUCCESS
    assert res.pad_gate.decision == GateDecision.BYPASSED


def test_case_17_pad_result_dataclass_interoperability(adapter):
    """Test 17: Adapter inter-operates natively with PADResult from pad_engine.py."""
    pad_res = PADResult(
        p_print=0.01,
        p_live=0.98,
        p_replay=0.01,
        p_spoof=0.02,
        live_score=0.98,
        spoof_score=0.02,
        predicted_class_idx=1,
        predicted_class_name="live",
        latency_ms=14.5,
        model_name="2.7_80x80_MiniFASNetV2.onnx",
        model_sha256="d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b",
        status="ok",
        is_live_argmax=True,
        is_live=None,
    )

    res = adapter.evaluate(
        identity_result=0.75,
        identity_threshold=0.45,
        pad_result=pad_res,
        pad_threshold=0.80,
        mode="enforcing"
    )
    assert res.verified is True
    assert res.outcome == DualGateOutcome.SUCCESS
    assert res.pad_gate.score == 0.98
    assert res.pad_gate.passed is True


# ---------------------------------------------------------------------------
# Phase C.11E Threshold Invariant and Type Hardening Tests (18 to 22)
# ---------------------------------------------------------------------------

def test_case_18_missing_identity_threshold_raises_type_error(adapter):
    """Test 18: Calling evaluate() without identity_threshold fails at the API boundary."""
    # Keyword arguments omitting identity_threshold
    with pytest.raises(TypeError) as excinfo:
        adapter.evaluate(
            identity_result=0.75,
            pad_result=0.90,
            pad_threshold=0.80,
            mode="enforcing"
        )
    assert "identity_threshold" in str(excinfo.value)

    # Positional argument omitting identity_threshold
    with pytest.raises(TypeError) as excinfo_pos:
        adapter.evaluate(0.75)
    assert "identity_threshold" in str(excinfo_pos.value)


def test_case_19_boolean_identity_threshold_rejected(adapter):
    """Test 19: True and False are explicitly rejected as identity thresholds."""
    for bool_val in [True, False]:
        res = adapter.evaluate(
            identity_result=0.75,
            identity_threshold=bool_val,
            pad_result=0.90,
            pad_threshold=0.80,
            mode="enforcing"
        )
        assert res.verified is False
        assert res.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD
        assert res.is_infrastructure_failure is True
        assert res.identity_gate.decision == GateDecision.UNCONFIGURED
        assert res.identity_gate.threshold is None  # Sanitized


def test_case_20_boolean_pad_threshold_rejected(adapter):
    """Test 20: True and False are explicitly rejected as PAD thresholds in enforcing mode."""
    for bool_val in [True, False]:
        res = adapter.evaluate(
            identity_result=0.75,
            identity_threshold=0.45,
            pad_result=0.90,
            pad_threshold=bool_val,
            mode="enforcing"
        )
        assert res.verified is False
        assert res.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD
        assert res.is_infrastructure_failure is True
        assert res.pad_gate.decision == GateDecision.UNCONFIGURED
        assert res.pad_gate.threshold is None  # Sanitized


def test_case_21_none_non_numeric_and_out_of_range_thresholds(adapter):
    """Test 21: NaN, Inf, None, strings, and out-of-range thresholds fail closed."""
    # None as identity threshold
    res_none_id = adapter.evaluate(
        identity_result=0.75,
        identity_threshold=None,
        pad_result=0.90,
        pad_threshold=0.80
    )
    assert res_none_id.verified is False
    assert res_none_id.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD

    # String as identity threshold
    res_str_id = adapter.evaluate(
        identity_result=0.75,
        identity_threshold="0.45",
        pad_result=0.90,
        pad_threshold=0.80
    )
    assert res_str_id.verified is False
    assert res_str_id.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD

    # Out-of-bounds identity threshold
    for bad_id in [-1.0, 0.0, 1.0, 2.5]:
        res_oob_id = adapter.evaluate(
            identity_result=0.75,
            identity_threshold=bad_id,
            pad_result=0.90,
            pad_threshold=0.80
        )
        assert res_oob_id.verified is False
        assert res_oob_id.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD

    # String and non-finite PAD thresholds in enforcing mode
    for bad_pad in ["0.80", float('nan'), float('inf'), float('-inf'), -0.1, 0.0, 1.0, 1.5]:
        res_bad_pad = adapter.evaluate(
            identity_result=0.75,
            identity_threshold=0.45,
            pad_result=0.90,
            pad_threshold=bad_pad,
            mode="enforcing"
        )
        assert res_bad_pad.verified is False
        assert res_bad_pad.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD


def test_case_22_boolean_score_inputs_rejected(adapter):
    """Test 22: Boolean score inputs are rejected rather than silently treated as 1.0 or 0.0."""
    # Boolean identity score
    res_bool_id = adapter.evaluate(
        identity_result=True,
        identity_threshold=0.45,
        pad_result=0.90,
        pad_threshold=0.80
    )
    assert res_bool_id.verified is False
    assert res_bool_id.outcome == DualGateOutcome.INFRASTRUCTURE_ERROR_IDENTITY

    # Boolean PAD score
    res_bool_pad = adapter.evaluate(
        identity_result=0.75,
        identity_threshold=0.45,
        pad_result=True,
        pad_threshold=0.80
    )
    assert res_bool_pad.verified is False
    assert res_bool_pad.outcome == DualGateOutcome.INVALID_INPUT

