# Phase 5 Test Fixtures — Methodology and Provenance

This document describes the synthetic frame generator used to test Phase 5 face
recognition and liveness, and states precisely what it can and cannot prove.

Every number quoted here comes from running the real SCRFD detector and the real
ArcFace embedder over the frames this renderer produces. The *pipeline* is real.
The *people* are not.

---

## 1. What the renderer is

`backend/tests/face_fixtures.py` is a deterministic, dependency-light renderer
that draws a synthetic head and rotates it about the vertical axis. It exists
because the test suite must run on machines with no camera and no human
subjects, and must produce byte-identical frames on every run so that a failure
is reproducible.

Determinism comes from explicit seeds. `render(identity, yaw, seed=N, size=S)`
depends only on its arguments; nothing is read from the clock, the filesystem
or a random source.

| Property | Value |
| --- | --- |
| Renderer | `backend/tests/face_fixtures.py` |
| Output | 360x360 BGR, encoded to JPEG by `fx.jpeg()` |
| Identities | 4 (`0`, `6`, `8`, `12`) |
| Rotation axis | vertical (yaw), `TURN_YAW = ±0.35` in renderer units |
| Detector | SCRFD `det_10g.onnx` via `insightface==2.1` |
| Embedder | ArcFace `w600k_r50.onnx`, 512-d, L2-normalised |
| Pose features | documented five-point landmarks only |

### Deliberately not implemented

The renderer does **not** attempt photorealism. There is no skin texture, no
subsurface scattering, no sensor noise model, no motion blur, no rolling
shutter, no depth-of-field, no print grain, no screen replay artefacts.

This matters for liveness. A renderer this simple is trivially detectable as
synthetic by any model trained on real photographs, and it cannot represent the
actual threat model (a printed photo or a phone screen held in front of a
camera). The synthetic liveness tests therefore demonstrate that the *liveness
state machine* rejects out-of-order and static movement. They do **not**
demonstrate that it rejects a sophisticated presentation attack, and nothing in
this repository should be read as claiming otherwise.

---

## 2. Frame families

| Helper | Yaw pattern | Purpose |
| --- | --- | --- |
| `fx.compliant_yaws(sequence, repeats)` | neutral, turn 1, neutral, turn 2, repeated | The happy path |
| `fx.reversed_yaws(sequence, repeats)` | neutral, turn 2, neutral, turn 1 | Order violation |
| `fx.static_yaws(n)` | every frame neutral | No movement at all |
| `fx.no_return_yaws(sequence, repeats)` | neutral, turn, then held | No return through neutral |

The four are the attacks the liveness state machine is designed to catch. Each
is exercised in `tests/test_phase5_face_security.py` and again in
`scripts/prove_phase5_face.py`.

---

## 3. Measured pose separation

`calibrated_yaw` is a dimensionless nose-offset score, not an angle in degrees.
It is roll-invariant: the horizontal distance between the nose tip and the
midpoint of the two eyes, divided by the eye-to-eye distance. Dividing by a
subject-relative scale makes the score comparable across subjects and across
camera distances, which is what allows one threshold to serve everyone.

Residuals are measured against a per-subject neutral baseline derived from the
captured frames themselves.

| Measurement | Value |
| --- | --- |
| Neutral residual, maximum observed | `0.0158` |
| Turned residual, minimum observed | `0.1095` |
| Separation | ~7x |
| Configured `FACE_CENTER_THRESHOLD` | `0.03` |
| Configured `FACE_TURN_THRESHOLD` | `0.06` |

Both configured thresholds sit inside the measured gap rather than on either
edge: the centre threshold is roughly double the worst neutral residual, and the
turn threshold is roughly half the weakest turn. That margin is why a genuine
subject is not rejected for involuntary head drift, and why a small genuine turn
is not mistaken for noise.

**These margins were measured on four synthetic identities.** They are a
sanity check on the pose formula, not a validated production tolerance.

---

## 4. Measured matching separation

| Measurement | Value |
| --- | --- |
| Genuine comparisons | 28 |
| Genuine minimum cosine similarity | `0.8601` |
| Genuine mean | `0.9319` |
| Impostor comparisons | 84 |
| Impostor maximum cosine similarity | `0.8000` |
| Impostor mean | `0.6232` |
| Margin (genuine min − impostor max) | `+0.0601` |
| Test threshold | `0.83` |
| Midpoint of the observed gap | `0.8301` |

The test threshold is the midpoint of the observed separation, which is why the
synthetic suite passes with `FAR = FRR = 0`.

**`0.83` is a fixture-derived value and must never be deployed.** Real ArcFace
thresholds depend on the model version, the enrolment sample count, the
operating population and the required false-accept rate. Selecting a production
threshold from four synthetic identities would be indefensible.

---

## 5. Why an explicit threshold is required in production

`FACE_SIMILARITY_THRESHOLD` has no default. If it is unset, verification returns
HTTP 503 rather than guessing, because a system that invents its own acceptance
threshold is a system whose false-accept rate nobody has measured. This is
enforced in `Config.validate_production` and tested in
`tests/test_phase5_face_security.py::test_verification_refuses_to_run_without_a_threshold`.

---

## 6. What these tests prove

For the Phase 5 baseline (before Phase 16 changes):

- SCRFD detection and ArcFace embedding run on every submission.
- The five-point-derived pose score tracks rendered rotation monotonically.
- The LEFT/RIGHT order is minted server-side from the system CSPRNG, and both
  orders occur in practice.
- Challenges are bound to user and session, expire, and are single use.
- Reversed order, static pose, held turn, non-JPEG frames, missing consent,
  multi-face frames, wrong frame counts and replayed challenges are all rejected.
- Genuine verification succeeds; every impostor identity is rejected.
- Stored templates are encrypted Fernet blobs; wrong keys and tampering fail.
- Withdrawal destroys the ciphertext and blocks further verification.
- No raw frame or cleartext embedding is persisted.

For the Phase 16 prototype:

- Face verification uses biometric embedding similarity only.
- Liveness detection (LEFT/RIGHT head-movement challenges, pose thresholds,
  neutral-band calibration) is **not enabled**.
- Presentation attacks (printed photographs, screen replays, masks, deepfakes)
  are **not mitigated**.

Not proven by these tests:

- Any real-world accuracy, false-accept rate or false-reject rate.
- Behaviour under poor lighting, motion blur, occlusion, glasses, facial hair,
  ageing or camera variation.
- Behaviour on demographic groups other than the renderer.

Real-world metrics are **NOT YET MEASURED**. See `docs/PHASE5_EVALUATION.md`.

---

## 7. Reproducing the measurements

```bash
cd backend
venv/Scripts/python scripts/prove_phase5_face.py
venv/Scripts/python scripts/evaluate_phase5_biometrics.py --fixtures
```

The first proves the pipeline end to end. The second runs the metric harness
over the fixture score matrix and labels the result `FIXTURE-ONLY /
NOT REPRESENTATIVE`. Run without arguments, the harness reports
`NOT YET MEASURED` and exits non-zero.
