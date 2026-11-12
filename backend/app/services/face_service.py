"""
Face Service - Phase 5 / Phase 16

Orchestrates the real biometric pipeline:

    challenge -> frame admission -> per-frame analysis -> template enrolment /
    matching

Design rules enforced here:

* A challenge is bound to ``user_id`` AND ``session_id``, expires after
  ``FACE_CHALLENGE_TTL_SECONDS``, and is single use. It is consumed by the
  first submission whether or not that submission succeeds.
* A face submission must contain exactly one detectable face and a usable
  embedding. The submitted frame order is used only as the temporal index it
  genuinely is.
* No similarity score, embedding, or pose value is ever returned to a client
  or written to the response body. Failures share one generic message.
* Nothing on this path stores a raw frame.
* IMPORTANT (Phase 16): liveness detection (LEFT/RIGHT head-movement
  challenges, posed yaw thresholds and neutral-band calibration) has been
  removed from this prototype. Face verification now uses biometric embedding
  similarity only. This does *not* mitigate presentation attacks.
"""

import logging
import math
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from flask import current_app

from app.extensions import db
from app.models.face import FaceChallenge, FaceEnrollment
from app.security.face import (
    FaceCiphertextError,
    FaceKeyUnavailable,
    FaceSecurityError,
    active_key_id,
    challenge_mac,
    decrypt_embedding,
    encrypt_embedding,
    envelope_key_id,
    generate_challenge_nonce,
    generate_face_challenge_id,
    verify_challenge_mac,
)
from app.services.biometric_adapter import (
    BiometricDualGateAdapter,
    DualGateOutcome,
    DualGateVerificationResult,
    GateDecision,
    PADGateInput,
)
from app.services.challenge_lease_service import ChallengeLeaseService
from app.services.face_engine import (
    EMBEDDING_MODEL_NAME,
    FaceEngineError,
    FaceEngineUnavailable,
    calibrated_yaw,
    calibrate_neutral,
    cosine_similarity,
    mean_normalised,
    signed_direction,
    get_engine,
)
from app.services.pad_engine import (
    PADEngine,
    PADError,
    PADInferenceError,
    PADInvalidInputError,
    PADModelUnavailable,
    PADResult,
    get_pad_engine,
)

logger = logging.getLogger(__name__)

DIRECTIONS = ('LEFT', 'RIGHT')

# Bounded inference concurrency gate
DEFAULT_MAX_CONCURRENT_INFERENCES = 4
_inference_semaphore = threading.BoundedSemaphore(DEFAULT_MAX_CONCURRENT_INFERENCES)


def get_inference_semaphore() -> threading.BoundedSemaphore:
    return _inference_semaphore


def set_inference_semaphore(sem: threading.BoundedSemaphore) -> None:
    global _inference_semaphore
    _inference_semaphore = sem


# PAD and Dual-Gate Adapter Accessors (Thread-safe dependency injection for testing)
_pad_engine_instance: Optional[Any] = None
_biometric_adapter_instance: Optional[BiometricDualGateAdapter] = None


def get_pad_engine_instance() -> Optional[Any]:
    global _pad_engine_instance
    if _pad_engine_instance is not None:
        return _pad_engine_instance
    try:
        return get_pad_engine()
    except Exception as exc:
        logger.warning("PAD engine unavailable: %s", exc)
        return None


def set_pad_engine_instance(engine: Optional[Any]) -> None:
    global _pad_engine_instance
    _pad_engine_instance = engine


def get_biometric_adapter() -> BiometricDualGateAdapter:
    global _biometric_adapter_instance
    if _biometric_adapter_instance is None:
        _biometric_adapter_instance = BiometricDualGateAdapter()
    return _biometric_adapter_instance


def set_biometric_adapter(adapter: Optional[BiometricDualGateAdapter]) -> None:
    global _biometric_adapter_instance
    _biometric_adapter_instance = adapter


class FaceServiceError(RuntimeError):
    """Client-correctable face operation failure. ``http_status`` drives the reply."""

    reason = 'face_error'
    http_status = 400


class ChallengeError(FaceServiceError):
    reason = 'challenge_rejected'
    http_status = 400


class FrameAdmissionError(FaceServiceError):
    reason = 'frame_rejected'
    http_status = 400


class NotEnrolledError(FaceServiceError):
    reason = 'not_enrolled'
    http_status = 400


class ConsentRequiredError(FaceServiceError):
    reason = 'consent_required'
    http_status = 400


class MatchFailedError(FaceServiceError):
    reason = 'match_failed'
    http_status = 400


class ThresholdNotConfiguredError(FaceServiceError):
    """No calibrated acceptance threshold. Biometric comparison must not run."""

    reason = 'threshold_not_configured'
    http_status = 503


class FaceEngineNotReadyError(FaceServiceError):
    reason = 'engine_unavailable'
    http_status = 503


def _cfg(name: str):
    return current_app.config[name]


class FaceService:
    """Phase 5 face operations. Stateless; safe to instantiate per request."""

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    @property
    def similarity_threshold(self) -> float:
        value = _cfg('FACE_SIMILARITY_THRESHOLD')
        if value is None:
            raise ThresholdNotConfiguredError(
                'FACE_SIMILARITY_THRESHOLD is not configured.'
            )
        try:
            threshold = float(value)
        except (TypeError, ValueError):
            raise ThresholdNotConfiguredError(
                'FACE_SIMILARITY_THRESHOLD is not a number.'
            )
        if not 0.0 < threshold < 1.0:
            raise ThresholdNotConfiguredError(
                'FACE_SIMILARITY_THRESHOLD must be strictly between 0 and 1.'
            )
        return threshold

    # ------------------------------------------------------------------
    # Challenges
    # ------------------------------------------------------------------
    def issue_challenge(self, user_id: int, session_id: str,
                        challenge_type: str = 'FACE',
                        authorization_id: Optional[int] = None,
                        election_id: Optional[int] = None) -> Dict:
        """Mint a single-use, session-bound challenge.

        The challenge is used to bind a face submission and prevent replay.
        When issued during voting authorization, it records authorization_id and election_id.
        """
        import secrets

        if not session_id:
            raise ChallengeError('An authenticated session is required.')

        challenge_id = generate_face_challenge_id()
        nonce = generate_challenge_nonce()
        ttl = int(_cfg('FACE_CHALLENGE_TTL_SECONDS'))
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        mac = challenge_mac(challenge_id, user_id, session_id, '',
                            nonce, expires_at.isoformat())

        challenge = FaceChallenge(
            challenge_id=challenge_id,
            user_id=user_id,
            session_id=session_id,
            challenge_type=challenge_type,
            challenge_sequence='',
            nonce=nonce,
            integrity_mac=mac,
            expires_at=expires_at,
            attempt_count=0,
            max_attempts=int(_cfg('FACE_MAX_ATTEMPTS')),
            completed=False,
            success=False,
            authorization_id=authorization_id,
            election_id=election_id,
            consumed=False,
        )
        db.session.add(challenge)
        db.session.commit()

        return {
            'challenge_id': challenge_id,
            'expires_in_seconds': ttl,
            'min_frames': int(_cfg('FACE_MIN_FRAMES')),
            'max_frames': int(_cfg('FACE_MAX_FRAMES')),
        }

    def _consume_challenge(self, challenge_id: str, user_id: int,
                           session_id: str) -> Tuple[FaceChallenge, str]:
        """Load, authenticate and consume a challenge.

        Consuming marks the row so the challenge cannot be replayed, including
        when the submission it consumed fails.
        """
        if not challenge_id or not isinstance(challenge_id, str):
            raise ChallengeError('A challenge id is required.')

        challenge = db.session.execute(
            select_challenge(challenge_id)
        ).scalar_one_or_none()

        if challenge is None:
            raise ChallengeError('Unknown or expired challenge.')

        if challenge.completed:
            raise ChallengeError('This challenge has already been used.')

        if challenge.attempt_count >= challenge.max_attempts:
            raise ChallengeError('This challenge has no attempts remaining.')

        if datetime.utcnow() > challenge.expires_at:
            challenge.completed = True
            db.session.commit()
            raise ChallengeError('This challenge has expired.')

        if int(challenge.user_id) != int(user_id):
            raise ChallengeError('This challenge belongs to another user.')

        if not session_id or challenge.session_id != session_id:
            raise ChallengeError('This challenge belongs to another session.')

        expected_mac = challenge_mac(
            challenge.challenge_id, challenge.user_id, challenge.session_id,
            challenge.challenge_sequence, challenge.nonce,
            challenge.expires_at.isoformat(),
        )
        if not verify_challenge_mac(expected_mac, challenge.integrity_mac):
            challenge.completed = True
            db.session.commit()
            raise ChallengeError('This challenge failed its integrity check.')

        # Consume now. A failure from here on still burns the challenge.
        challenge.attempt_count += 1
        challenge.completed = True
        db.session.commit()
        return challenge, str(challenge.challenge_sequence or '')

    def _consume_challenge_allow_empty_sequence(self, challenge_id: str,
                                                user_id: int,
                                                session_id: str) -> Tuple[FaceChallenge, str]:
        """Load, authenticate and consume a challenge that may have an empty
        expected sequence.

        Phase 16 removed the LEFT/RIGHT obligation from this prototype, so some
        challenges do not carry a movement sequence.
        """
        if not challenge_id or not isinstance(challenge_id, str):
            raise ChallengeError('A challenge id is required.')

        challenge = db.session.execute(
            select_challenge(challenge_id)
        ).scalar_one_or_none()

        if challenge is None:
            raise ChallengeError('Unknown or expired challenge.')

        if challenge.completed:
            raise ChallengeError('This challenge has already been used.')

        if challenge.attempt_count >= challenge.max_attempts:
            raise ChallengeError('This challenge has no attempts remaining.')

        if datetime.utcnow() > challenge.expires_at:
            challenge.completed = True
            db.session.commit()
            raise ChallengeError('This challenge has expired.')

        if int(challenge.user_id) != int(user_id):
            raise ChallengeError('This challenge belongs to another user.')

        if not session_id or challenge.session_id != session_id:
            raise ChallengeError('This challenge belongs to another session.')

        expected_mac = challenge_mac(
            challenge.challenge_id, challenge.user_id, challenge.session_id,
            challenge.challenge_sequence, challenge.nonce,
            challenge.expires_at.isoformat(),
        )
        if not verify_challenge_mac(expected_mac, challenge.integrity_mac):
            challenge.completed = True
            db.session.commit()
            raise ChallengeError('This challenge failed its integrity check.')

        # Allow empty sequences; they mean "no movement required".
        if challenge.challenge_sequence:
            sequence = [part for part in str(challenge.challenge_sequence).split(',')
                        if part]
            if sorted(sequence) != sorted(DIRECTIONS):
                challenge.completed = True
                db.session.commit()
                raise ChallengeError('Stored challenge sequence is invalid.')

        # Consume now. A failure from here on still burns the challenge.
        challenge.attempt_count += 1
        challenge.completed = True
        db.session.commit()
        return challenge, str(challenge.challenge_sequence or '')

    def _validate_challenge_for_verification(self, challenge_id: str,
                                             user_id: int,
                                             session_id: str) -> FaceChallenge:
        """Load, authenticate and validate a challenge for verification without consuming it.

        Validates session binding, user ownership, expiration, attempt budget, and MAC.
        Lease acquisition and attempt counting are managed atomically by ChallengeLeaseService.
        """
        if not challenge_id or not isinstance(challenge_id, str):
            raise ChallengeError('A challenge id is required.')

        challenge = db.session.execute(
            select_challenge(challenge_id)
        ).scalar_one_or_none()

        if challenge is None:
            raise ChallengeError('Unknown or expired challenge.')

        if challenge.completed:
            raise ChallengeError('This challenge has already been used.')

        if challenge.consumed:
            raise ChallengeError('This challenge has already been used.')

        if challenge.attempt_count >= challenge.max_attempts:
            raise ChallengeError('This challenge has no attempts remaining.')

        now = datetime.utcnow()
        if now > challenge.expires_at:
            challenge.completed = True
            db.session.commit()
            raise ChallengeError('This challenge has expired.')

        if int(challenge.user_id) != int(user_id):
            raise ChallengeError('This challenge belongs to another user.')

        if not session_id or challenge.session_id != session_id:
            raise ChallengeError('This challenge belongs to another session.')

        expected_mac = challenge_mac(
            challenge.challenge_id, challenge.user_id, challenge.session_id,
            challenge.challenge_sequence, challenge.nonce,
            challenge.expires_at.isoformat(),
        )
        if not verify_challenge_mac(expected_mac, challenge.integrity_mac):
            challenge.completed = True
            db.session.commit()
            raise ChallengeError('This challenge failed its integrity check.')

        # Allow empty sequences; they mean "no movement required".
        if challenge.challenge_sequence:
            sequence = [part for part in str(challenge.challenge_sequence).split(',')
                        if part]
            if sorted(sequence) != sorted(DIRECTIONS):
                challenge.completed = True
                db.session.commit()
                raise ChallengeError('Stored challenge sequence is invalid.')

        return challenge

    # ------------------------------------------------------------------
    def _admit_frames(self, payloads: Sequence[bytes]) -> None:
        """Reject the batch before any inference work happens."""
        minimum = int(_cfg('FACE_MIN_FRAMES'))
        maximum = int(_cfg('FACE_MAX_FRAMES'))
        if not minimum <= len(payloads) <= maximum:
            raise FrameAdmissionError(
                f'Submit between {minimum} and {maximum} frames.'
            )
        max_frame = int(_cfg('FACE_MAX_FRAME_BYTES'))
        max_total = int(_cfg('FACE_MAX_UPLOAD_BYTES'))
        total = 0
        for payload in payloads:
            if len(payload) > max_frame:
                raise FrameAdmissionError('A frame exceeds the permitted size.')
            total += len(payload)
        if total > max_total:
            raise FrameAdmissionError('The submission exceeds the total size limit.')

    def _analyze(self, payloads: Sequence[bytes]):
        """Run the real engine over every frame.

        Propagates engine-level errors unchanged so an unavailable model
        surfaces as 503 rather than as a biometric rejection.
        """
        try:
            engine = get_engine()
        except FaceEngineUnavailable as error:
            logger.error('Face engine unavailable: %s', error)
            raise FaceEngineNotReadyError(str(error))

        analyses = []
        for payload in payloads:
            try:
                analyses.append(engine.analyze(payload))
            except FaceEngineUnavailable:
                raise
            except FaceEngineError as error:
                logger.info('Face frame rejected by the engine: %s', type(error).__name__)
                raise FrameAdmissionError(str(error))
            except ValueError as error:
                # InvalidFrameError / QualityRejectedError / FaceCountError /
                # UnknownPoseError all surface as ValueError subclasses.
                logger.info('Face frame rejected: %s (%s)', type(error).__name__, str(error))
                raise FrameAdmissionError(str(error))
        return analyses

    # ------------------------------------------------------------------
    # Enrolment
    # ------------------------------------------------------------------
    def enroll(self, user_id: int, session_id: str, challenge_id: str,
               payloads: Sequence[bytes], consent_given: bool,
               consent_purpose: Optional[str] = None) -> Dict:
        """Enrol a face template from the submitted frames."""
        if not consent_given:
            raise ConsentRequiredError(
                'Explicit consent is required before a face template is stored.'
            )

        challenge, _sequence = self._consume_challenge_allow_empty_sequence(
            challenge_id, user_id, session_id)
        self._admit_frames(payloads)
        analyses = self._analyze(payloads)

        # Evaluate PAD in non-enforcing shadow mode on enrollment frame(s)
        # Guarantees:
        # - Evaluated on the existing analyzed frame(s); zero-copy, no re-upload.
        # - Shadow mode only; never alters enrollment outcome or changes accept/reject decisions.
        # - Any exceptions/model errors are safely non-blocking telemetry events.
        try:
            if analyses:
                self._evaluate_pad_shadow(
                    frame_analysis=analyses[0],
                    identity_score=1.0,
                    identity_threshold=self.similarity_threshold or 0.83,
                )
        except Exception as pad_err:
            logger.info("Non-blocking PAD shadow evaluation exception during enrollment: %s", pad_err)

        # Use an ensemble of the accepted frames so enrolment is more stable
        # than a single frame, but do not require liveness motion to enrol.
        template = mean_normalised([a.embedding for a in analyses])

        # Embedding provenance travels inside the encrypted payload, so nothing
        # about the biometric template sits in a cleartext column.
        metadata = _pack_metadata(active_key_id())
        try:
            blob = encrypt_embedding(template.tobytes() + metadata)
        except (FaceKeyUnavailable, FaceSecurityError) as error:
            logger.error('Face template encryption failed: %s', type(error).__name__)
            raise FaceEngineNotReadyError('Template encryption failed.')
        key_id = envelope_key_id(blob)

        existing = db.session.execute(
            select_enrollment(user_id)
        ).scalar_one_or_none()
        purpose = consent_purpose or _cfg('FACE_CONSENT_PURPOSE')

        if existing is None:
            existing = FaceEnrollment(user_id=user_id)
            db.session.add(existing)

        existing.encrypted_embedding = blob
        existing.embedding_method = 'arcface_cosine'
        existing.embedding_model = EMBEDDING_MODEL_NAME
        existing.embedding_dim = int(template.shape[0])
        existing.embedding_key_id = key_id
        existing.is_enrolled = True
        existing.consent_given = True
        existing.consent_at = datetime.utcnow()
        existing.consent_purpose = purpose
        existing.withdrawn_at = None
        existing.template_deleted_at = None

        db.session.commit()
        logger.info('Face enrolment completed for user_id=%s challenge=%s',
                    user_id, challenge.challenge_id)

        return {
            'success': True,
            'message': 'Face enrolment completed.',
            'enrolled': True,
            'consent_purpose': purpose,
        }

    # ------------------------------------------------------------------
    # Shadow-Mode PAD Evaluation
    # ------------------------------------------------------------------
    def _evaluate_pad_shadow(
        self,
        frame_analysis: Any,
        identity_score: float,
        identity_threshold: float,
    ) -> Optional[DualGateVerificationResult]:
        """
        Evaluates Face Presentation Attack Detection in non-enforcing shadow mode.

        Guarantees:
        - NEVER alters the identity verification decision in shadow mode.
        - Enforcing mode is strictly prohibited and unreachable on the live route.
        - Emits minimal, privacy-preserving operational telemetry (NO PII, embeddings, or session IDs).
        - Model unavailability or inference exceptions are treated as non-blocking telemetry events.
        """
        # 1. Enforce mode restrictions: Enforcing mode is strictly prohibited in Phase C.13
        configured_mode = str(_cfg('FACE_PAD_MODE') or 'shadow').strip().lower()
        if configured_mode not in ('shadow', 'disabled'):
            logger.warning(
                "Prohibited or invalid FACE_PAD_MODE '%s' detected; forcing 'shadow' mode.",
                configured_mode,
            )
            mode = 'shadow'
        else:
            mode = configured_mode

        adapter = get_biometric_adapter()

        # 2. Disabled mode: bypass PAD evaluation completely
        if mode == 'disabled':
            return adapter.evaluate(
                identity_result=identity_score,
                identity_threshold=identity_threshold,
                pad_result=None,
                pad_threshold=None,
                mode='disabled',
            )

        # 3. Shadow mode: execute PAD inference on the same frame used for identity verification
        pad_threshold = _cfg('FACE_PAD_THRESHOLD')
        pad_input_or_result = None

        if getattr(frame_analysis, 'image_bgr', None) is None or getattr(frame_analysis, 'bbox', None) is None:
            pad_input_or_result = PADGateInput(
                live_score=0.0,
                status="missing_input",
                error_details="No decoded image or bounding box available on FrameAnalysis",
            )
        else:
            try:
                engine = get_pad_engine_instance()
                if engine is None:
                    pad_input_or_result = PADGateInput(
                        live_score=0.0,
                        status="model_unavailable",
                        error_details="PAD engine is not available",
                    )
                else:
                    pad_input_or_result = engine.evaluate_image(
                        image_bgr=frame_analysis.image_bgr,
                        bbox=frame_analysis.bbox,
                        bbox_format="xyxy",
                        threshold=pad_threshold,
                    )
            except PADModelUnavailable as err:
                logger.info("PAD model unavailable during shadow evaluation: %s", err)
                pad_input_or_result = PADGateInput(
                    live_score=0.0,
                    status="model_unavailable",
                    error_details=str(err),
                )
            except (PADInferenceError, PADInvalidInputError) as err:
                logger.info("PAD inference error during shadow evaluation: %s", err)
                pad_input_or_result = PADGateInput(
                    live_score=0.0,
                    status="inference_error",
                    error_details=str(err),
                )
            except Exception as err:
                logger.warning("Unexpected error during PAD shadow evaluation: %s", err)
                pad_input_or_result = PADGateInput(
                    live_score=0.0,
                    status="inference_error",
                    error_details=str(err),
                )

        # 4. Evaluate through BiometricDualGateAdapter in shadow mode
        dual_gate_res = adapter.evaluate(
            identity_result=identity_score,
            identity_threshold=identity_threshold,
            pad_result=pad_input_or_result,
            pad_threshold=pad_threshold,
            mode='shadow',
        )

        # 5. Emit minimal, privacy-preserving operational telemetry (NO PII, embeddings, or IDs)
        pad_gate = dual_gate_res.pad_gate
        latency = getattr(pad_input_or_result, 'latency_ms', 0.0) if pad_input_or_result else 0.0
        is_live_argmax = getattr(pad_input_or_result, 'is_live_argmax', False) if pad_input_or_result else False

        logger.info(
            "PAD shadow telemetry: status=%s decision=%s category=%s latency_ms=%.2f is_live_argmax=%s",
            pad_gate.category,
            pad_gate.decision.value,
            pad_gate.category,
            latency,
            is_live_argmax,
        )

        return dual_gate_res

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def _load_active_enrollment(self, user_id: int) -> FaceEnrollment:
        enrollment = db.session.execute(
            select_enrollment(user_id)
        ).scalar_one_or_none()
        if enrollment is None or not enrollment.is_active():
            # Not distinguishing "never enrolled" from "withdrawn" in the
            # message keeps enrolment state from becoming an oracle.
            raise NotEnrolledError('Face verification failed.')
        return enrollment

    def verify(self, user_id: int, session_id: str, challenge_id: str,
               payloads: Sequence[bytes]) -> Dict:
        """Verify a face against the enrolled template using challenge leasing."""
        threshold = self.similarity_threshold

        # Step 1: Pre-validate challenge ownership, session, MAC, and unexpired state
        self._validate_challenge_for_verification(challenge_id, user_id, session_id)

        # Step 2: Atomically acquire lease (short transaction, immediately committed)
        lease_res = ChallengeLeaseService.acquire_lease(challenge_id)
        if not lease_res.acquired:
            reason = lease_res.reason or ""
            if "in_flight_leased" in reason:
                raise ChallengeError("This challenge is currently being processed.")
            elif "attempts_exhausted" in reason:
                raise ChallengeError("This challenge has no attempts remaining.")
            elif "expired" in reason:
                raise ChallengeError("This challenge has expired.")
            elif "database_error" in reason:
                raise FaceEngineNotReadyError("Database unavailable.")
            else:
                raise ChallengeError("This challenge has already been used.")

        lease_token = lease_res.lease_token

        # Step 3: Load enrollment and template
        try:
            enrollment = self._load_active_enrollment(user_id)
        except NotEnrolledError:
            ChallengeLeaseService.resolve_lease_biometric_rejection(challenge_id, lease_token)
            raise

        try:
            plaintext = decrypt_embedding(bytes(enrollment.encrypted_embedding))
            template = _unpack_template(plaintext)
        except (FaceCiphertextError, FaceKeyUnavailable, FaceSecurityError) as error:
            logger.error('Face template could not be decrypted: %s', type(error).__name__)
            ChallengeLeaseService.release_lease_on_infrastructure_failure(challenge_id, lease_token)
            raise FaceEngineNotReadyError('Stored template is unreadable.')
        except ValueError as error:
            logger.error('Stored face template is malformed: %s', error)
            ChallengeLeaseService.release_lease_on_infrastructure_failure(challenge_id, lease_token)
            raise FaceEngineNotReadyError('Stored template is unreadable.')

        # Step 4: Bounded concurrency admission gate (non-blocking Semaphore)
        sem = get_inference_semaphore()
        if not sem.acquire(blocking=False):
            logger.warning("Inference capacity saturated for challenge %s", challenge_id)
            ChallengeLeaseService.release_lease_on_infrastructure_failure(challenge_id, lease_token)
            raise FaceEngineNotReadyError("Face verification service is at capacity. Please retry.")

        # Step 5: Frame admission & Inference (protected by semaphore; NO DB connection held)
        try:
            self._admit_frames(payloads)
            analyses = self._analyze(payloads)

            # Select best matching identity frame
            best = -1.0
            best_analysis = None
            for a in analyses:
                sim = cosine_similarity(template['vector'], a.embedding)
                if sim > best:
                    best = sim
                    best_analysis = a

            # Evaluate PAD in non-enforcing shadow mode on the same frame used for identity
            if best_analysis is not None:
                self._evaluate_pad_shadow(
                    frame_analysis=best_analysis,
                    identity_score=best,
                    identity_threshold=threshold,
                )

            logger.info(
                'Face match evaluation for user_id=%s: best_similarity=%.4f threshold=%.4f delta=%.4f (verdict=%s)',
                user_id, best, threshold, best - threshold, 'ACCEPTED' if best >= threshold else 'REJECTED'
            )

            if best < threshold:
                logger.info('Face match rejected for user_id=%s (score=%.4f < threshold=%.4f)', user_id, best, threshold)
                raise MatchFailedError('Face verification failed.')
            else:
                logger.info('Face match accepted for user_id=%s (score=%.4f >= threshold=%.4f)', user_id, best, threshold)
        except (MatchFailedError, FrameAdmissionError):
            # Client or biometric failure: burn challenge attempt
            ChallengeLeaseService.resolve_lease_biometric_rejection(challenge_id, lease_token)
            raise
        except (FaceEngineUnavailable, FaceEngineNotReadyError) as error:
            # Infrastructure failure: release lease so student can retry
            ChallengeLeaseService.release_lease_on_infrastructure_failure(challenge_id, lease_token)
            if isinstance(error, FaceEngineUnavailable):
                raise FaceEngineNotReadyError(str(error)) from error
            raise
        except Exception as error:
            # Unexpected system error: fail closed safely and release lease
            logger.error('Unexpected inference error for challenge=%s: %r', challenge_id, error)
            ChallengeLeaseService.release_lease_on_infrastructure_failure(challenge_id, lease_token)
            raise FaceEngineNotReadyError('Internal inference error.') from error
        finally:
            sem.release()

        # Step 6: Biometric success -> resolve lease
        res = ChallengeLeaseService.resolve_lease_biometric_success(challenge_id, lease_token)
        if not res.resolved:
            logger.error("Failed to resolve lease success for %s: %s", challenge_id, res.reason)
            if res.reason and "database_error" in res.reason:
                raise FaceEngineNotReadyError("Database unavailable.")
            raise ChallengeError("Face verification challenge expired during processing.")

        logger.info('Face verification succeeded for user_id=%s', user_id)
        return {
            'success': True,
            'verified': True,
            'message': 'Face verification succeeded.',
        }

    # ------------------------------------------------------------------
    # Consent lifecycle
    # ------------------------------------------------------------------
    def get_status(self, user_id: int) -> Dict:
        """Report the caller's own enrolment/consent state."""
        enrollment = db.session.execute(
            select_enrollment(user_id)
        ).scalar_one_or_none()
        if enrollment is None:
            return {
                'enrolled': False,
                'consent_given': False,
                'consent_purpose': None,
            }
        return {
            'enrolled': enrollment.is_active(),
            'consent_given': bool(enrollment.consent_given
                                  and enrollment.withdrawn_at is None),
            'consent_purpose': enrollment.consent_purpose,
            'withdrawn_at': enrollment.withdrawn_at.isoformat()
            if enrollment.withdrawn_at else None,
        }

    def withdraw_consent(self, user_id: int) -> Dict:
        """Withdraw consent and irreversibly destroy the stored template."""
        enrollment = db.session.execute(
            select_enrollment(user_id)
        ).scalar_one_or_none()
        if enrollment is None:
            raise FaceServiceError('No face enrolment exists to withdraw.')

        now = datetime.utcnow()
        enrollment.consent_given = False
        enrollment.withdrawn_at = now
        enrollment.is_enrolled = False
        enrollment.template_deleted_at = now
        # Blank the ciphertext so no recoverable copy of the template remains
        # in the row once consent is withdrawn.
        enrollment.encrypted_embedding = b''
        db.session.commit()

        logger.info('Face consent withdrawn for user_id=%s', user_id)
        return {
            'success': True,
            'enrolled': False,
            'message': 'Face template deleted and consent withdrawn.',
        }


# ----------------------------------------------------------------------
# Payload layout helpers
# ----------------------------------------------------------------------
# Encrypted payload = template vector bytes followed by a small fixed header.
# Keeping the neutral baseline inside the ciphertext means no cleartext column
# ever describes the subject's biometric geometry.

_METADATA_HEADER = b'VWM1'
_TEMPLATE_BYTES = 512 * 4  # float32 x 512


def _pack_metadata(key_id: str) -> bytes:
    return _METADATA_HEADER + key_id.encode('utf-8')


def _unpack_template(plaintext: bytes) -> Dict:
    if not isinstance(plaintext, (bytes, bytearray)):
        raise ValueError('template payload is not bytes')
    raw = bytes(plaintext)
    if len(raw) < _TEMPLATE_BYTES + len(_METADATA_HEADER) + 1:
        raise ValueError('template payload is too short')
    vector_bytes = raw[:_TEMPLATE_BYTES]
    header_at = _TEMPLATE_BYTES
    if raw[header_at:header_at + len(_METADATA_HEADER)] != _METADATA_HEADER:
        raise ValueError('template metadata header is missing')
    key_id = raw[header_at + len(_METADATA_HEADER):].decode('utf-8', 'strict').split('\x00')[0]
    vector = np.frombuffer(vector_bytes, dtype=np.float32).copy()
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError('template vector is degenerate')
    return {'vector': vector / norm, 'key_id': key_id}


def select_challenge(challenge_id: str):
    from sqlalchemy import select

    return select(FaceChallenge).where(
        FaceChallenge.challenge_id == challenge_id)


def select_enrollment(user_id: int):
    from sqlalchemy import select

    return select(FaceEnrollment).where(FaceEnrollment.user_id == user_id)


face_service = FaceService()
