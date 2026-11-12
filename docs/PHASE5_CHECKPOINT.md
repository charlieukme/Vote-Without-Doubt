# Phase 5 Checkpoint

## Status

```
PHASE 0 = COMPLETE
PHASE 1 = COMPLETE
PHASE 2 = COMPLETE
PHASE 3 = COMPLETE
PHASE 4 = COMPLETE
PHASE 5 = REMEDIATED — PARTIAL
PHASE 6 = NOT STARTED
```

Verdict: **`PHASE 5 REMEDIATION COMPLETE — PARTIAL`**

PARTIAL, not PASS. Every audit finding is closed and the biometric pipeline is
real and end-to-end verified, but the performance evidence an election
deployment depends on is absent.

---

## Correction (after independent audit and remediation)

The original checkpoint claimed COMPLETE with a stub embedding, placeholder
frames and 36 tests. An audit of that implementation returned **47 FAIL** and the
verdict `PHASE 5 AUDIT COMPLETE — FAIL`. This section records the corrected
state.

### Built

- **Real engine**: SCRFD `det_10g` detection, documented five-point landmarks,
  roll-invariant server-derived pose, per-subject neutral calibration, ArcFace
  `w600k_r50` 512-d embeddings, cosine matching. No stubs, no fallback.
- **Challenge protocol**: CSPRNG-randomised LEFT/RIGHT order, 256-bit id and
  nonce, integrity MAC over the whole tuple, bound to user *and* session,
  20-second TTL, single use.
- **Server-side liveness**: directions re-derived from pixels; neutral start,
  correct order, mandatory return through neutral, monotonic advance. Reversed
  order, static pose, held turn and constant-direction poses all rejected.
- **Encryption**: explicit keys, versioned `VWDF1` envelope carrying its key id,
  rotation support, fail-closed on wrong key / tamper / malformed / unknown
  version. Never returns ciphertext as plaintext.
- **Consent lifecycle**: explicit opt-in required to enrol; withdrawal destroys
  the ciphertext and blocks verification.
- **Real multipart API** at `/face/challenge`, `/face/enroll`, `/face/verify`,
  `/face/status`, `/face/withdraw-consent`, all authenticated, all rate limited.
- **Frontend**: real `getUserMedia` capture, repeated `frames` parts, camera
  released on every exit path, no client-asserted order, no browser storage.
- **Migration** `4f2b7c91de50`, verified upgrade / downgrade / re-upgrade with no
  drift.
- **Proof script** (45 checks) and **evaluation harness** (ROC, DET, EER, FAR,
  FRR, AUC, APCER/BPCER).

### Verified

| Claim | Status |
| --- | --- |
| Pipeline is real, no stub embedding or placeholder frame | VERIFIED |
| Detection, pose and embedding run real ONNX models every run | VERIFIED |
| Both challenge orders occur; order is server-authoritative | VERIFIED |
| Challenge bound to user and session; replay and cross-session rejected | VERIFIED |
| Five attack families rejected end to end | VERIFIED |
| Wrong key / tampered template / unreadable template fail closed (503) | VERIFIED |
| Withdrawal destroys the template and blocks verification | VERIFIED |
| Every biometric rejection returns one generic body | VERIFIED |
| Success responses leak no score, threshold, yaw or embedding | VERIFIED |
| Backend suite | **542 passed** |
| Frontend suite | **103 passed** |
| Frontend build | CLEAN |
| Frontend lint | Exit 0. 4 `oxlint` warnings, all `set-state-in-effect` in mount-time status fetches (`Face.jsx`, plus pre-existing `Auth.jsx`/`Wallet.jsx`) and one unused local in `Wallet.jsx`. No errors. |
| Schema drift, upgrade, downgrade | CLEAN |

### Not verified — the reason for PARTIAL

| Claim | Status |
| --- | --- |
| Real-world FAR | **NOT YET MEASURED** |
| Real-world FRR | **NOT YET MEASURED** |
| Real-world ROC / DET / EER | **NOT YET MEASURED** |
| Real-world APCER / BPCER | **NOT YET MEASURED** |
| ISO/IEC 30107-3 PAD curves | **NOT DERIVABLE** from the current binary-verdict design |
| Production threshold selection | **BLOCKED** — no dataset, no authority requirement |
| Print / replay / mask / deepfake resistance | **NOT MEASURED** |

There is no approved human-face dataset in this repository. The available frame
source is a four-identity synthetic renderer, which validates the code path and
says nothing about human performance. The fixture threshold `0.83` is the
midpoint of four synthetic identities and must never be deployed.

One measured finding deserves emphasis: with the liveness stage bypassed, the
matcher accepts a static replay (APCER 1.0). **All presentation-attack
resistance lives in the liveness stage.** That stage is strictly load-bearing.

---

## Supporting documents

- `docs/PHASE5_FINAL_REPORT.md` — full remediation report
- `docs/PHASE5_FIXTURES.md` — fixture methodology, provenance, measured separation
- `docs/PHASE5_EVALUATION.md` — evaluation methodology, dataset requirements,
  model checksums, threshold policy
- `PROJECT_BIBLE.md` — authoritative project status

## Next phase

Phase 6 remains NOT STARTED. Work required before Phase 5 could be called PASS,
and which must precede any real deployment:

1. Obtain an approved human-face dataset with a lawful basis and written consent.
2. Obtain the authority's maximum tolerable FAR.
3. Measure FAR/FRR/ROC/EER and select the production threshold from that data.
4. Measure APCER/BPCER per attack type; convert liveness to a scored PAD
   function if ISO/IEC 30107-3 curves are required.
