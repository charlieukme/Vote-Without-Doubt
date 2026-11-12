# Phase 5 Remediation Report — Face Recognition and Liveness

Replaces the pre-audit `PHASE5_FINAL_REPORT.md`, which described a stub pipeline
and is retained only as a historical record of what was claimed before the audit.

The audit that triggered this work returned **47 FAIL** across the phase and the
verdict `PHASE 5 AUDIT COMPLETE — FAIL`. This document records what was built to
close those findings, what is now verified, and what remains unproven.

---

## 1. What was wrong

The pre-remediation implementation looked complete and was not:

| Finding | Reality before remediation |
| --- | --- |
| Embedding | Literal `b'embedding_stub'` bytes; no model |
| Frame intake | JSON list of integers, replaced with a synthetic `b'frame'` placeholder |
| Detector | None; zero-face and multi-face unenforced |
| Yaw | Undocumented landmark indices from an unverified 106-point mesh |
| Challenge | Predictable order, weak binding, replayable |
| Encryption | No explicit key; silently degraded, could return ciphertext as plaintext |
| Consent | Endpoint did not exist on the backend |
| Frontend | `frames: [1, 2, 3]` and a client-sent `sequence` |
| Evaluation | Conceptual definitions with no harness |

---

## 2. Biometric engine

`backend/app/services/face_engine.py`

- **Detection**: SCRFD `det_10g.onnx`, `max_num > 1` so multi-face frames can be
  *detected* and then rejected, rather than silently cropped to one face.
- **Landmarks**: the five documented points only. An earlier attempt indexed a
  106-point mesh with indices that could not be verified; that code was deleted
  rather than guessed at.
- **Pose**: roll-invariant dimensionless nose-offset score — the horizontal
  distance from the nose tip to the eye midpoint, divided by eye-to-eye
  distance. Not degrees, and not comparable to any angular quantity.
- **Calibration**: a per-subject neutral baseline is derived from the captured
  frames at enrolment and stored *inside* the encrypted payload, so no cleartext
  column describes biometric geometry.
- **Quality gates**: JPEG magic bytes, decode, dimensions (160–1920), sharpness,
  exposure, detector confidence ≥ 0.5, exactly one face, face area ≥ 12% of frame.
- **Embedding**: ArcFace `w600k_r50`, 512-d, L2-normalised.
- **Matching**: cosine similarity against a `mean_normalise` template.
- **Failure**: missing or unloadable weights raise `FaceEngineUnavailable` and
  surface as HTTP 503. There is no permissive fallback and no implicit download.

Runtime: `insightface==2.1`, `onnxruntime==1.30.0`, `opencv-python==4.10.0.84`.

---

## 3. Challenge protocol

`POST /api/face/challenge`

- Order drawn from `secrets.SystemRandom()`; both LEFT-first and RIGHT-first
  occur (observed across 12 consecutive challenges in the proof run).
- 256-bit random challenge id; 256-bit random nonce.
- Integrity MAC over `(challenge_id, user_id, session_id, sequence, nonce, expires_at)`.
- Bound to **both** user and session; 20-second TTL; single use.
- Consumed by the first submission whether or not that submission succeeds.

Editing the stored sequence in the database breaks the MAC and is rejected
(`test_tampered_stored_sequence_fails_its_mac`).

---

## 4. Liveness

`FaceService.evaluate_liveness`

Directions are **re-derived server-side** from per-frame pose scores. The
submitted frame order is used only as the temporal index it genuinely is. A
client-sent `sequence` would be a client-asserted liveness result and is not
accepted anywhere in the API.

Required, in order:

1. A neutral pose before the first turn.
2. The server-defined direction first.
3. A return through neutral **between** the two turns.
4. The second direction, after the first.
5. Monotonic advance toward the second target of at least `FACE_TURN_THRESHOLD`.

Rejected in tests: reversed order, static pose, a single held turn, and a
constant one-direction pose.

---

## 5. Encryption

`backend/app/security/face.py`

- Explicit keys only. Unset keys raise `FaceKeyUnavailable`; no ephemeral or
  random key is ever generated.
- Versioned `VWDF1` envelope: magic, format version, key id, key version,
  ciphertext. The key id travels *in* the envelope so rotation works.
- Multi-key support via `FACE_ENCRYPTION_KEYS`; templates written under an old
  key stay readable after rotation.
- Wrong key, tampered ciphertext, malformed envelope and unknown version all
  fail closed. The old implementation could return its input on failure; that
  path is gone and is asserted against.
- Decryption failures never return partial data or the ciphertext.

---

## 6. API

| Method | Path | Change |
| --- | --- | --- |
| POST | `/api/face/challenge` | randomised, session-bound, MAC-protected |
| POST | `/api/face/enroll` | real repeated-multipart `frames` + `consent` |
| POST | `/api/face/verify` | real repeated-multipart `frames` |
| GET | `/api/face/status` | unchanged in shape |
| POST | `/api/face/withdraw-consent` | destroys the template |
| — | `/api/face/consent` | **removed** — did not exist on the backend |
| — | `/api/face/challenge/enroll` | **removed** |
| — | `/api/face/challenge/verify` | **removed** |

Removal is asserted: the superseded routes must return 404, authenticated or not,
so they cannot quietly come back.

Every endpoint requires a live, unrevoked, unexpired `AUTHORIZED` session, and
`PENDING_OTP` sessions are refused. All biometric rejections share one generic
body, so response differences cannot be used as an oracle. Successful responses
leak no similarity, score, distance, embedding, yaw, threshold or pose value.

---

## 7. Database

Migration `4f2b7c91de50` (head after `58781e8f838c`):

- `face_challenges`: adds `session_id`, `nonce`, `integrity_mac`,
  `attempt_count`, `max_attempts`; narrows `challenge_sequence` to `VARCHAR(32)`
  **and makes it `NOT NULL`**.
- Pre-existing challenges are **retired**, not given a placeholder binding they
  never had.
- `face_enrollments`: adds `embedding_model`, `embedding_dim`,
  `embedding_key_id`, `consent_purpose`, `withdrawn_at`, `template_deleted_at`.

A schema-drift bug was found and fixed during this work: the migration narrowed
the column type but omitted `nullable=False`, while the ORM declared `NOT NULL`,
so `flask db check` reported drift. The backfill now also covers rows with a NULL
sequence so the constraint cannot fail. Verified:

- fresh `upgrade` → clean
- `downgrade 58781e8f838c` → `upgrade` → clean
- `flask db check` → "No new upgrade operations detected"

---

## 8. Frontend

`frontend/src/faceCamera.js` (new, plain JS) and `frontend/src/Face.jsx`
(rewritten).

- Real `getUserMedia` capture to a `<canvas>`, JPEG-encoded per frame.
- Repeated `frames` parts in one `FormData`; the shared client already omits
  `Content-Type` so the browser sets the multipart boundary.
- Challenge is minted **before** the camera opens; frame count is clamped to the
  server-advertised window; capture is bounded by the challenge TTL minus a
  safety margin.
- Every `MediaStreamTrack` is released on success, on failure and on unmount.
- Permission denied, no device, device busy, unsupported context and capture
  failure each produce a distinct, actionable message.
- The client sends only `challenge_id` (plus `consent` on enrolment). It never
  sends a movement order, never decides an outcome, and never touches
  `localStorage`, `sessionStorage`, `indexedDB` or `document.cookie`.

---

## 9. Tests

| Suite | Count |
| --- | --- |
| `tests/test_phase5_face_engine.py` | 26 |
| `tests/test_phase5_face_security.py` | 78 |
| `tests/test_phase5_evaluation.py` | 35 |
| **Phase 5 backend total** | **139** |
| `tests/test_face_api.py`, `tests/test_face_validation.py` | removed (superseded) |
| **Full backend suite** | **542 passed** |
| `frontend/tests/faceCamera.test.mjs` | 27 |
| `frontend/tests/faceFlow.test.mjs` | 16 |
| **Full frontend suite** | **103 passed** |

No test is skipped, xfailed, or conditionally deselected. The engine and API
suites run the real ONNX models on every run.

`test_face_api.py` and `test_face_validation.py` asserted HTTP 401 on endpoints
that the remediation deliberately removed, so they were passing for the wrong
reason. They were deleted and replaced with a 404 regression test.

The camera logic was placed in a separate plain-JS module specifically so it
could be executed against mocked media devices in Node, rather than asserted by
reading source text.

---

## 10. Proof and evaluation

### Proof script

`backend/scripts/prove_phase5_face.py` — 45 labelled checks and 17 explicit
assertions, all holding, exit 0. Real provider, real embeddings, monotone pose
tracking, both challenge orders, binding, MAC tamper detection, all five attack
families, replay, cross-session rejection, genuine/impostor separation, single
generic rejection body, consent withdrawal, wrong-key and tamper rejection,
frame-count limits.

Two properties were corrected during this work and are worth recording, because
both made the script report success without proving anything:

- **Session attribution.** Attack, replay, MAC-tamper, frame-limit and
  post-withdrawal checks originally minted each challenge and then submitted the
  frames from a *fresh* session. Session binding rejects a mismatched session
  before liveness or the MAC is ever evaluated, so every one of those 400s was
  explainable by session binding alone. The submitting client is now the issuing
  client in each case, and cross-session rejection is demonstrated separately and
  on its own (check 27) with compliant frames and a live challenge.
- **Assertions.** The script printed results without checking them. It now
  asserts expected outcomes — including that check 25's *first* submission
  succeeds before its replay fails — and exits 1 on any mismatch.

### Evaluation harness

`backend/scripts/evaluate_phase5_biometrics.py` — ROC, DET, EER, FAR, FRR,
AUC, APCER/BPCER, min-APCER-at-BPCER, manifest support, sufficiency checking,
JSON export. With no dataset it prints `NOT YET MEASURED` and exits 2.

Three honesty defects were fixed here:

- Any manifest passed with `--manifest` was previously labelled representative of
  real users regardless of its contents. It now requires an explicit
  `"kind"`, and only `"kind": "human"` may back a real-world claim. Selecting a
  file is not certifying what is in it.
- Structural defects (missing role, unreadable image, and a subject reusing
  identical image bytes for enrolment and probing) now raise
  `DatasetValidationError` and the script exits 2 with no metrics, instead of
  computing numbers from a broken dataset. The enrolment/probe duplicate check
  is the important one: it is the easiest way to manufacture a perfect error
  rate.
- The embedded manifest documentation claimed the harness "enforces" sample-size
  minima. It reports them as blocking sufficiency problems instead, because how
  many trials a defensible rate needs depends on the FAR an authority
  specifies. The documentation now matches the behaviour.

---

## 11. Remaining limitations

These are stated so they are not mistaken for solved:

1. **No real-world accuracy measurement.** No approved human-face dataset exists
   in this repository. FAR, FRR, ROC, DET, EER, APCER and BPCER are **NOT YET
   MEASURED** for real users.
2. **The fixture threshold `0.83` is not deployable.** It is the midpoint of the
   observed gap between four synthetic identities.
3. **Liveness returns a binary verdict, not a PAD score.** ISO/IEC 30107-3
   APCER/BPCER curves are therefore not derivable without a design change.
4. **The matcher alone has no presentation-attack resistance.** Measured APCER
   with liveness bypassed is 1.0. All attack resistance lives in the liveness
   stage, which makes that stage strictly load-bearing.
5. **The synthetic renderer is not a print/replay/mask detector.** It cannot
   represent the real threat model.
6. **Posture/geometry limitation.** A roll-invariant nose-offset score does not
   distinguish yaw from a lateral head translation of similar magnitude. This is
   acceptable for a seated, roughly frontal voting kiosk but would need a
   3D-capable method for a moving subject.
7. **No duplicate-enrolment or 1:N identification check.** Phase 5 is 1:1
   verification only.

---

## 12. Verification commands

```bash
cd backend
venv/Scripts/python -m pytest -q                                  # 542 passed
venv/Scripts/python scripts/prove_phase5_face.py                  # 45 checks, 17 assertions
venv/Scripts/python scripts/evaluate_phase5_biometrics.py         # NOT YET MEASURED, exit 2
venv/Scripts/python scripts/evaluate_phase5_biometrics.py --fixtures
venv/Scripts/python -m pyflakes app/services/face_engine.py app/services/face_service.py \
    app/routes/face.py app/security/face.py app/models/face.py scripts tests

cd ../frontend
npm test                                                          # 103 passed
npm run lint                                                      # exit 0, 4 warnings
npm run build                                                     # clean
```

`pyflakes` reports no findings in any Phase 5 file. The one hit in
`face_engine.py` is the deliberate `onnxruntime` availability probe, which is
imported to fail closed with a clear message and already carries `# noqa: F401`.
Remaining repo-wide findings are pre-existing unused imports in Phase 0-4 files,
outside this phase's scope.

`npm run lint` warnings are all in code that fetches status on mount (a genuine
external-system synchronisation, which is what effects are for) plus one unused
local in `Wallet.jsx`. Exit code 0, no errors.

---

## 13. Phase status

```
PHASE 0 = COMPLETE
PHASE 1 = COMPLETE
PHASE 2 = COMPLETE
PHASE 3 = COMPLETE
PHASE 4 = COMPLETE
PHASE 5 = REMEDIATED — see verdict
PHASE 6 = NOT STARTED
```

## 14. Final verdict

**PHASE 5 REMEDIATION COMPLETE — PARTIAL**

Every audit FAIL is closed and the pipeline is real, end-to-end tested against
real models, and fails closed. The phase is **not** marked PASS because the
performance claims that an election deployment depends on — FAR, FRR, APCER and
BPCER on real people — are **NOT YET MEASURED**, and no dataset exists in this
repository with which to measure them. The implementation is complete; the
evidence that it works on humans is not.
