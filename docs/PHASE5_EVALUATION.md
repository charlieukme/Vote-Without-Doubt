# Phase 5 Biometric Evaluation — Methodology and Status

**Status: real-world biometric performance is NOT YET MEASURED.**

No approved human-face dataset exists in this repository. Every real-world
figure required to operate a face-verification system in an election is
therefore unavailable, and this document says exactly what is missing, what has
been measured instead, and what would be required to measure it.

Nothing in this repository should be read as a claim about recognition accuracy.

---

## 1. Why this is not measured

The verification pipeline is real: SCRFD detection, five-point landmarks,
server-derived pose, ArcFace `buffalo_l/w600k_r50` embeddings, encrypted
templates, cosine matching. What cannot be produced without human subjects is any
statement about error rates on people.

Available in this repository:

| Asset | Status |
| --- | --- |
| Real SCRFD + ArcFace models | Present, checksums recorded in §7 |
| Real inference pipeline | Present, exercised on every test run |
| Synthetic frame renderer | Present, `backend/tests/face_fixtures.py` |
| Real human-face dataset | **Absent** |
| Real presentation-attack samples | **Absent** |
| Real print/replay/mask captures | **Absent** |

A four-identity synthetic renderer can validate that the *code path* is correct.
It cannot validate that the *system* works on voters, because there are no voters
in it.

---

## 2. What the fixture run does and does not show

`scripts/evaluate_phase5_biometrics.py --fixtures` computes a complete score
matrix over the synthetic identities. It reports, from that matrix:

```
genuine  n=12  min=0.8401  max=0.9592  mean=0.9007
impostor n=36  min=0.4381  max=0.8120  mean=0.5926
ROC AUC = 1.000000    EER = 0.000000
FAR@0.83 = 0.0        FRR@0.83 = 0.0
```

These figures are a self-test of the harness. They are labelled
`FIXTURE-ONLY / NOT REPRESENTATIVE` in every code path that emits them, and the
script exits with the conclusion `Real-world FAR / FRR / ROC / EER / APCER /
BPCER: NOT YET MEASURED`.

### An important negative finding

In the same run, the harness reports:

```
APCER at operating threshold 0.83   1.0
min APCER at BPCER <= 0.1%         100.0
```

Read that carefully before drawing a conclusion. These numbers score the
**matcher alone**, with the liveness stage bypassed. A static replay of an
enrolled frame produces an embedding that the matcher scores above threshold,
so **the matcher by itself offers no presentation-attack resistance whatsoever**.

In the deployed system those presentations are rejected earlier, by the liveness
state machine, because a static pose cannot satisfy a randomised LEFT/RIGHT
sequence. `scripts/prove_phase5_face.py` demonstrates that end-to-end rejection.

The consequence for deployment: **the liveness stage is not an optional
additional check.** Removing it, weakening it, or letting an operator bypass it
would immediately expose the system to trivially scored replay attacks. This is
the single most important architectural property of Phase 5.

---

## 3. Metrics that must be measured, and their definitions

### Recognition (matching)

| Metric | Definition | Operational relevance |
| --- | --- | --- |
| FAR | Fraction of impostor trials accepted | Someone else votes as you |
| FRR | Fraction of genuine trials rejected | A registered voter is denied the right |
| ROC | TPR against FPR across all thresholds | Trade-off shape |
| DET | FRR against FAR across all thresholds | Operating-region view |
| EER | Threshold where FAR = FRR | Threshold-selection sanity check |
| CMC / rank-1 | Top-1 identification accuracy | Useful for galleries, not this design |

This system performs **verification** (1:1), not identification (1:N), so FAR is
the security-critical figure and FRR is the accessibility/turnout-critical one.

For a voting system, an election authority typically specifies the maximum
tolerable FAR and then reports the FRR that threshold implies. Any defensible
target requires a published requirement to measure against; this repository
contains no such requirement, so none is invented here.

### Presentation attack detection

| Metric | Definition |
| --- | --- |
| APCER | Attack Presentation Classification Error Rate — fraction of attacks accepted |
| BPCER | Bona fide Presentation Classification Error Rate — fraction of bona fide presentations rejected |
| min APCER @ BPCER ≤ 0.1% | Operating point conventionally referenced for PAD (ISO/IEC 30107-3) |

### A structural limitation to record now

The shipped liveness stage returns a **binary verdict**, not a continuous
presentation-attack score. Consequently:

- APCER and BPCER can be measured at the single shipped operating point.
- **Full ISO/IEC 30107-3 APCER/BPCER curves are not derivable** from this
  implementation, because there is no score to sweep a threshold over.
- `min APCER at BPCER ≤ 0.1%` is computed by the harness, but for this system it
  would only be meaningful if liveness were converted to a scored PAD function.

Producing the minimum-APCER-at-target-BPCER figure that a PAD evaluation needs
requires a design change to the liveness stage, not just new data. That work is
**out of scope for Phase 5** and is recorded here so the gap is visible rather
than implied.

---

## 4. Dataset requirements

An evaluation is only worth running on a dataset that satisfies all of the
following. The harness enforces the trial-count minimums in code
(`check_dataset_sufficiency`) and reports every shortfall as a blocking issue.

### Subjects and trials

| Requirement | Minimum | Rationale |
| --- | --- | --- |
| Distinct subjects | 20 | Below this, impostor-pair counts collapse |
| Genuine trials | 100 | Needed for a stable FRR estimate |
| Impostor trials | 500 | Needed for a stable FAR estimate |
| Enrolment captures per subject | ≥ 2 | Mirrors real enrolment variability |

With 20 subjects and 2 probes each there are 40 genuine and 760 impostor trials
automatically. Larger populations are strongly preferred: an election authority
should expect to specify FAR in the region of 1e-4 to 1e-6, and estimating a
1e-6 FAR requires on the order of 1e6 impostor comparisons.

### Capture conditions that must vary

- Camera: at least several devices, including a low-cost one.
- Lighting: indoor, outdoor, low light, backlit.
- Demographics: age range, gender balance, and — for any public-sector
  deployment — a documented plan for measuring across groups, since face
  recognition error rates are known to vary across demographics.
- Headwear, glasses, facial hair.
- Distance and framing: subjects must fill a realistic fraction of the frame.

### Separation

Enrolment and probe sessions for a subject **must** be separate captures, taken
at different times if possible. Using the same image for enrolment and
verification manufactures a near-perfect score and makes every error rate
meaningless. The harness relies on this being honoured; it cannot detect a
violation in a manifest that lies about it.

### Presentation attacks

For APCER/BPCER, per attack type per subject:

- Printed photograph.
- Screen replay (phone or tablet displaying a photo or video).
- Mask or 3D-printed face.
- Replay of a video of the genuine subject (deepfake), where in scope.

Each attack must target its own subject's enrolled template, which is what a real
attacker would do.

### Ethics and consent

Collecting facial biometrics for an election requires a lawful basis and
informed written consent from every subject, an approved retention and deletion
schedule, and a documented DPIA. A dataset gathered without that basis cannot be
used, and its derived error rates cannot be published. This is a prerequisite,
not paperwork to be filed afterwards.

---

## 5. Manifest format

Generate the format with:

```bash
cd backend
venv/Scripts/python scripts/evaluate_phase5_biometrics.py --describe
```

Shape:

```json
{
  "name": "internal-pilot-2026",
  "kind": "human",
  "purpose": "threshold selection for the 2026 pilot",
  "notes": "conditions, demographics, consent reference",
  "samples": [
    {"subject": "s001", "role": "enroll", "image": "s001/enroll-01.jpg"},
    {"subject": "s001", "role": "probe",  "image": "s001/probe-01.jpg"},
    {"subject": "s001", "role": "spoof",  "image": "s001/print-01.jpg",
     "attack": "printed_photo"}
  ]
}
```

Then run:

```bash
venv/Scripts/python scripts/evaluate_phase5_biometrics.py \
    --manifest ds.json --json-out report.json
```

The script builds templates with the same `mean_normalise` operation
`FaceService.enroll` uses, scores every genuine and impostor pair, and prints
ROC, DET, EER, FAR, FRR and PAD figures — with every blocking insufficiency
listed.

### What the harness refuses to do

A structurally broken manifest is rejected outright; the script exits 2 and
computes nothing. Rejected cases:

| Condition | Why it is refused |
| --- | --- |
| Missing `kind` | No way to tell captured humans from synthetic frames; figures would be unattributable |
| Unknown `kind` | Same |
| Missing role (no probe, no spoof, no enroll) | No computable error rate |
| Unreferenced / unreadable image | Silent sample loss |
| **Same image bytes used for a subject's enrolment and probing** | Manufactures a perfect score from a dataset that measured nothing |
| Unknown role or a sample missing `subject`/`image` | Uninterpretable manifest |

`"kind"` is never inferred. Passing `--manifest` selects a file; it does not
certify what is inside. Only `"kind": "human"` is reported as representative, and
even then the harness cannot verify the claim was consented, lawful and captured
in separate sessions. That part is the collection process's responsibility, and
it is a precondition for trusting anything the harness prints.

Sample-size minima (20 subjects, 100 genuine, 500 impostor) are reported as
blocking sufficiency problems rather than refused, because how many trials a
defensible rate needs depends on the FAR an authority is specifying. A small
dataset is not automatically wrong, and it is not automatically sufficient.

---

## 6. Threshold selection policy

`FACE_SIMILARITY_THRESHOLD` has no default and is validated on startup:

- Unset → verification returns HTTP 503.
- Non-numeric → HTTP 503.
- Outside the open interval (0, 1) → HTTP 503.

Production value selection:

1. Choose the maximum tolerable FAR from an election-authority requirement.
2. Read the corresponding FRR from the measured ROC on held-out data.
3. Confirm the FRR is acceptable for turnout, with demographic breakdowns.
4. Set the threshold; the system applies it verbatim, with no per-request
   override and no client influence.
5. Re-measure after any change to the model, preprocessing or enrolment flow.

Do **not** carry the fixture threshold `0.83` into any deployment. Its only
meaning is "midpoint of four synthetic identities".

---

## 7. Model provenance

Weights are not on PyPI and are deliberately never downloaded at runtime;
`FaceEngine._build()` fails closed with HTTP 503 when they are absent. Provision
`buffalo_l` under `backend/face_models/` before starting the service.

SHA-256 digests of the verified local pack:

| File | SHA-256 | Bytes |
| --- | --- | --- |
| `det_10g.onnx` | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` | 16,923,827 |
| `w600k_r50.onnx` | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` | 174,383,860 |

Only these two files are loaded. The remaining pack contents are present in the
upstream archive but unused:

| File | SHA-256 | Bytes |
| --- | --- | --- |
| `1k3d68.onnx` | `df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc` | 143,607,619 |
| `2d106det.onnx` | `f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf` | 5,030,888 |
| `genderage.onnx` | `4fde69b1c810857b88c64a335084f1c3fe8f01246c9a191b48c7bb756d6652fb` | 1,322,532 |
| `buffalo_l.zip` | `80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f` | 288,621,354 |

Runtime stack: `insightface==2.1`, `onnxruntime==1.30.0` (CPUExecutionProvider),
`opencv-python==4.10.0.84`.

Verify before deploying:

```bash
cd backend/face_models/models/buffalo_l
sha256sum det_10g.onnx w600k_r50.onnx
```

A digest mismatch means the weights are not the ones this system was tested
against. Do not proceed on the assumption that it is probably fine.

---

## 8. Summary

| Metric | Status |
| --- | --- |
| Recognition pipeline is real and exercised | **VERIFIED** |
| Pose/liveness logic correct on synthetic frames | **VERIFIED** |
| Liveness is load-bearing against trivial replay | **VERIFIED** |
| Fixture score separation measured | **VERIFIED** (fixture only) |
| Real-world FAR | **NOT YET MEASURED** |
| Real-world FRR | **NOT YET MEASURED** |
| Real-world ROC / DET / EER | **NOT YET MEASURED** |
| Real-world APCER / BPCER | **NOT YET MEASURED** |
| ISO/IEC 30107-3 PAD curves | **NOT DERIVABLE** from the current binary-verdict design |
| Production threshold selection | **BLOCKED** pending a dataset and an authority requirement |
