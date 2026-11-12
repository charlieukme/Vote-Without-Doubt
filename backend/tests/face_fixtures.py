"""
TEST-ONLY synthetic face fixtures for Phase 5.

No real person's biometric data is used anywhere in this repository. Faces are
drawn procedurally from shaded primitives with per-identity appearance
parameters (geometry, skin tone, hair, facial hair, eyewear, freckles, moles).

The geometry uses a weak-perspective head model, so a ``yaw`` parameter genuinely
displaces the facial features relative to the head outline. That is what the
landmark-based yaw estimator measures, which makes the liveness tests exercise
real image-derived measurements rather than a hardcoded flag.

Scope and honest limits
-----------------------
These fixtures are cartoon-like renderings. They let the REAL detector, REAL
landmark model and REAL ArcFace encoder run inside CI, and they let genuine
versus impostor decisions be measured on a controlled set. They are NOT
representative of human faces, and any threshold derived from them is a
FIXTURE-DOMAIN threshold, not a real-world operating point. See
docs/PHASE5_FIXTURES.md and docs/PHASE5_EVALUATION.md.
"""

import cv2
import numpy as np

# Identities used by the automated suite. Chosen because the real SCRFD
# detector fires reliably on all of them across the pose range.
FIXTURE_IDENTITIES = (0, 6, 8, 12)

# Pose values used to build a movement sequence.
NEUTRAL_YAW = 0.0
TURN_YAW = 0.35

# Acceptance threshold measured ON THIS FIXTURE SET ONLY.
#
# Measured with the real ArcFace w600k_r50 encoder over these identities:
#   genuine (same identity)      n=28  min=0.8601  mean=0.9319
#   impostor (different identity) n=84  max=0.8000  mean=0.6232
#   separation margin                   +0.0601
#   midpoint                            0.8300
#
# This is NOT a production threshold. Production sets
# FACE_SIMILARITY_THRESHOLD from a real calibration study and refuses to boot
# without it. Tests set it explicitly to this value.
FIXTURE_SIMILARITY_THRESHOLD = 0.83

# Measured pose separation with per-identity neutral calibration (real engine):
#   neutral residual max = 0.0158
#   turned  residual min = 0.1095
# The shipped defaults (center 0.03, turn 0.06) sit inside that gap.
FIXTURE_CENTER_THRESHOLD = 0.03
FIXTURE_TURN_THRESHOLD = 0.06


def _bgr(r, g, b):
    return (int(b), int(g), int(r))


class Identity:
    """Stable per-identity appearance parameters (a synthetic 'person')."""

    def __init__(self, index):
        rng = np.random.default_rng(9000 + index * 17)
        self.index = index
        self.skin = (float(rng.uniform(140, 224)),
                     float(rng.uniform(100, 178)),
                     float(rng.uniform(85, 155)))
        self.face_w = float(rng.uniform(0.172, 0.218))
        self.face_h = float(rng.uniform(0.232, 0.290))
        self.eye_dx = float(rng.uniform(0.33, 0.46))
        self.eye_r = float(rng.uniform(0.145, 0.215))
        self.eye_gap = float(rng.uniform(0.14, 0.25))
        self.eye_gap_ratio = float(rng.uniform(0.74, 0.98))
        self.nose_len = float(rng.uniform(0.13, 0.21))
        self.nose_w = float(rng.uniform(0.09, 0.17))
        self.mouth_w = float(rng.uniform(0.20, 0.40))
        self.mouth_h = float(rng.uniform(0.060, 0.130))
        self.mouth_y = float(rng.uniform(0.42, 0.54))
        self.brow_lift = float(rng.uniform(0.24, 0.36))
        self.jaw = float(rng.uniform(0.86, 1.00))
        # identity-stable appearance cues
        self.beard = int(rng.integers(0, 4))          # 0 none 1 stubble 2 moustache 3 full
        self.hair_col = (float(rng.integers(14, 88)),
                         float(rng.integers(9, 64)),
                         float(rng.integers(7, 52)))
        self.hair_len = float(rng.uniform(0.95, 1.28))
        self.hair_sides = bool(rng.integers(0, 2))
        self.glasses = bool(rng.integers(0, 2))
        self.freckles = int(rng.integers(0, 3))
        # fixed identity-specific marks, in face-relative units
        marks = rng.uniform(-0.55, 0.55, size=(int(rng.integers(2, 7)), 2))
        self.marks = [(float(a), float(b)) for a, b in marks]

    def describe(self):
        return (f'Identity({self.index}) skin={tuple(round(c) for c in self.skin)} '
                f'face={self.face_w:.3f}x{self.face_h:.3f} eye_dx={self.eye_dx:.3f} '
                f'eye_r={self.eye_r:.3f} mouth_w={self.mouth_w:.3f} beard={self.beard} '
                f'glasses={int(self.glasses)} freckles={self.freckles} '
                f'hair={tuple(round(c) for c in self.hair_col)}/{self.hair_len:.2f}')


def render(identity, yaw=0.0, seed=0, size=360, bg=None, blur=0, bright=1.0,
           noise=3.0, occlude=False):
    """Render one synthetic face frame.

    yaw: weak-perspective head rotation in roughly [-0.6, 0.6].
    occlude: simulate a hand or object covering part of the face.
    """
    ident = identity if isinstance(identity, Identity) else Identity(int(identity))
    rng = np.random.default_rng(int(abs(seed)))
    if bg is None:
        v = int(rng.integers(55, 228))
        bg = (v, v, int(max(0, min(255, v + int(rng.integers(-25, 25))))))
    img = np.full((size, size, 3), bg, np.uint8)

    cx, cy = size * 0.5, size * 0.50
    fw = size * ident.face_w
    fh = size * ident.face_h
    skin = ident.skin
    dark = _bgr(*[c * 0.42 for c in skin])

    def shade(mask):
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx - cx) / max(fw, 1e-6)
        ny = (yy - cy) / max(fh, 1e-6)
        z = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        light = np.clip(0.44 + 0.56 * (-0.42 * nx - 0.28 * ny + 0.78 * z), 0.0, 1.42)
        lit = np.clip(img.astype(np.float32) * light[..., None], 0, 255)
        m = (cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2.5) > 0.2)[..., None]
        return np.where(m, lit, img.astype(np.float32)).astype(np.uint8)

    def fx(base):
        """Feature x-position including yaw displacement."""
        return base + yaw * fw * 0.85

    # ---- shoulders / neck -------------------------------------------------
    cv2.ellipse(img, (int(cx), int(cy + fh * 0.95)),
                (int(fw * 0.48), int(fh * 0.55)), 0, 0, 360,
                _bgr(*[c * 0.84 for c in skin]), -1)
    cv2.ellipse(img, (int(cx), int(size * 1.04)),
                (int(size * 0.48), int(size * 0.32)), 0, 0, 360,
                _bgr(*[c * 0.42 for c in skin]), -1)

    # ---- hair mass (behind the head) -------------------------------------
    hc = _bgr(*ident.hair_col)
    cv2.ellipse(img, (int(cx), int(cy - fh * 0.28)),
                (int(fw * 1.12), int(fh * 0.95 * ident.hair_len)), 0, 0, 360, hc, -1)
    if ident.hair_sides:
        for sgn in (-1, 1):
            cv2.ellipse(img, (int(cx + sgn * fw * 0.95), int(cy + fh * 0.20)),
                        (int(fw * 0.42), int(fh * 0.85)), 0, 0, 360, hc, -1)

    # ---- head silhouette --------------------------------------------------
    mask = np.zeros((size, size), np.uint8)
    jaw_pts = []
    for t in np.linspace(-1.0, 1.0, 48):
        jaw_pts.append([
            int(cx + t * fw),
            int(cy + fh * (0.28 + 0.74 * np.sqrt(max(1 - t * t, 0)) * ident.jaw)),
        ])
    jaw = np.array(jaw_pts, np.int32).reshape((-1, 1, 2))
    cv2.ellipse(mask, (int(cx), int(cy - fh * 0.10)),
                (int(fw), int(fh * 1.06)), 0, 0, 360, 255, -1)
    cv2.fillConvexPoly(mask, cv2.convexHull(jaw), 255)
    cv2.ellipse(img, (int(cx), int(cy)), (int(fw), int(fh)), 0, 0, 360,
                _bgr(*skin), -1)
    cv2.fillConvexPoly(img, cv2.convexHull(jaw), _bgr(*skin))
    img = shade(mask)

    # ---- identity-stable skin marks (freckles / moles) --------------------
    if ident.freckles:
        for _ in range(28 * ident.freckles):
            u = float(rng.uniform(-0.85, 0.85))
            v = float(rng.uniform(-0.35, 0.75))
            px = fx(cx + u * fw)
            py = cy + v * fh
            if 0 <= px < size and 0 <= py < size:
                cv2.circle(img, (int(px), int(py)),
                           max(int(fw * 0.012), 1),
                           _bgr(*[c * 0.80 for c in skin]), -1)
    for u, v in ident.marks:
        px, py = fx(cx + u * fw), cy + v * fh
        if 0 <= px < size and 0 <= py < size:
            cv2.ellipse(img, (int(px), int(py)),
                        (max(int(fw * 0.045), 2), max(int(fw * 0.030), 2)),
                        0, 0, 360, _bgr(*[c * 0.34 for c in skin]), -1)

    # ---- eyes -------------------------------------------------------------
    e_dx = fw * ident.eye_dx
    e_y = cy - fh * ident.eye_gap
    er = fw * ident.eye_r
    iris = _bgr(150 + 60 * rng.random(), 70 + 60 * rng.random(), 40 + 40 * rng.random())
    for sgn in (-1, 1):
        ex = fx(cx + sgn * e_dx)
        far = sgn * yaw > 0
        ey = e_y + (fh * 0.025 if far else 0.0)
        sc = er * (1.0 - 0.20 * abs(yaw) if far else 1.0)
        cv2.ellipse(img, (int(ex), int(ey)),
                    (int(sc * 1.30), max(int(sc * 0.82 * ident.eye_gap_ratio), 1)),
                    0, 0, 360, (228, 228, 224), -1)
        cv2.circle(img, (int(ex), int(ey)), max(int(sc * 0.60), 2), (190, 192, 188), -1)
        cv2.circle(img, (int(ex), int(ey)), max(int(sc * 0.29), 2), iris, -1)
        cv2.circle(img, (int(ex), int(ey)), max(int(sc * 0.12), 1), (24, 20, 18), -1)
        cv2.circle(img, (int(ex - sc * 0.17), int(ey - sc * 0.17)),
                   max(int(sc * 0.09), 1), (250, 250, 250), -1)
        by = ey - er * (1.35 + ident.brow_lift)
        cv2.ellipse(img, (int(ex), int(by)),
                    (int(sc * 1.22), max(int(sc * 0.27), 1)),
                    0, 182, 358, _bgr(*[c * 0.48 for c in skin]),
                    max(int(sc * 0.20), 1))

    # ---- nose -------------------------------------------------------------
    nx = fx(cx + yaw * fw * 0.16)
    ny = cy + fh * ident.nose_len
    nw = fw * ident.nose_w
    cv2.ellipse(img, (int(nx), int(ny - fh * 0.04)),
                (int(nw * 0.80), int(fh * 0.16)), 0, 0, 360,
                _bgr(*[c * 0.95 for c in skin]), -1)
    cv2.ellipse(img, (int(nx - yaw * nw * 0.28), int(ny + fh * 0.06)),
                (int(nw * 0.62), int(fh * 0.10)), 0, 0, 360,
                _bgr(*[c * 0.79 for c in skin]), -1)
    cv2.ellipse(img, (int(nx), int(ny + fh * 0.11)),
                (int(nw * 1.02), int(fh * 0.045)), 0, 0, 360,
                _bgr(*[c * 0.60 for c in skin]), -1)

    # ---- mouth ------------------------------------------------------------
    mx = fx(cx)
    my = cy + fh * ident.mouth_y
    mw = fw * ident.mouth_w
    mh = fh * ident.mouth_h
    cv2.ellipse(img, (int(mx), int(my)), (int(mw), int(mh)), 0, 0, 360,
                _bgr(*[c * 0.82 for c in skin]), -1)
    cv2.ellipse(img, (int(mx), int(my - mh * 0.10)),
                (int(mw * 0.94), max(int(mh * 0.58), 1)), 0, 0, 360, (124, 72, 84), -1)
    cv2.ellipse(img, (int(mx), int(my + mh * 0.44)),
                (int(mw * 0.90), max(int(mh * 0.40), 1)), 0, 0, 360,
                _bgr(*[c * 0.70 for c in skin]), -1)

    # ---- facial hair (identity cue) --------------------------------------
    if ident.beard in (1, 3):
        region = np.zeros((size, size), np.uint8)
        cv2.ellipse(region, (int(fx(cx)), int(cy + fh * 0.30)),
                    (int(fw * (0.86 if ident.beard == 3 else 0.80)),
                     int(fh * (0.72 if ident.beard == 3 else 0.62))),
                    0, 0, 360, 255, -1)
        if ident.beard == 3:
            cv2.ellipse(img, (int(fx(cx)), int(cy + fh * 0.38)),
                        (int(mw * 1.35), int(mh * 2.0)), 0, 0, 360, dark, -1)
        m = (cv2.GaussianBlur(region.astype(np.float32), (0, 0), 1.5) > 0.25)
        tint = np.array(img, np.float32) * 0.88
        img = np.where(m[..., None], tint, img.astype(np.float32)).astype(np.uint8)
    if ident.beard in (2, 3):
        cv2.ellipse(img, (int(fx(cx)), int(my - mh * 0.85)),
                    (int(mw * 0.78), max(int(mh * 0.55), 2)), 0, 0, 360, dark, -1)

    # ---- eyewear ----------------------------------------------------------
    if ident.glasses:
        gr = max(int(er * 2.05), 6)
        gy = int(e_y)
        for sgn in (-1, 1):
            ex = int(fx(cx + sgn * e_dx))
            cv2.ellipse(img, (ex, gy), (gr, max(int(gr * 0.78), 4)), 0, 0, 360,
                        (48, 46, 44), max(int(er * 0.26), 2))
            cv2.ellipse(img, (ex, gy), (gr - 2, max(int(gr * 0.78) - 2, 2)), 0, 0, 360,
                        (168, 178, 186), -1)
        cv2.line(img, (int(fx(cx - e_dx)) + gr - 2, gy),
                 (int(fx(cx + e_dx)) - gr + 2, gy),
                 (48, 46, 44), max(int(er * 0.26), 2))

    # ---- occlusion (simulates poor capture) -------------------------------
    if occlude:
        cv2.ellipse(img, (int(cx + fw * 0.55), int(cy + fh * 0.25)),
                    (int(fw * 0.55), int(fh * 0.60)), 0, 0, 360,
                    (int(bg[0]), int(bg[1]), int(bg[2])), -1)

    # ---- capture realism --------------------------------------------------
    img = np.clip(img.astype(np.float32) * bright, 0, 255)
    if noise > 0:
        img = np.clip(img + rng.normal(0, noise, img.shape), 0, 255)
    img = img.astype(np.uint8)
    if blur:
        img = cv2.GaussianBlur(img, (blur * 2 + 1, blur * 2 + 1), 0)
    return img


def jpeg(img, quality=88):
    """Encode a rendered frame as JPEG bytes."""
    ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError('JPEG encode failed')
    return buf.tobytes()


# ----------------------------------------------------------------------
# Movement-sequence builders
# ----------------------------------------------------------------------

# A negative yaw renders the face turned toward image-left. The service maps a
# positive calibrated residual to RIGHT, so the rendered sign is inverted here
# to keep the fixture semantics readable.
_DIRECTION_YAW = {'LEFT': -TURN_YAW, 'RIGHT': +TURN_YAW}


def compliant_yaws(sequence=None, repeats=3):
    """Yaw values that genuinely satisfy ``sequence`` (a LEFT/RIGHT order).

    Produces, per repeat: a neutral start, the first turn, a return through
    neutral, then the second turn. Every frame carries a distinct seed so no two
    frames are byte-identical.
    """
    if not sequence or len(sequence) < 2:
        sequence = ('LEFT', 'RIGHT')
    first, second = sequence[0], sequence[1]
    cycle = [NEUTRAL_YAW, _DIRECTION_YAW[first], NEUTRAL_YAW, _DIRECTION_YAW[second]]
    return cycle * int(repeats)


def reversed_yaws(sequence=None, repeats=3):
    """Yaw values performing the two turns in the OPPOSITE order.

    Used to prove the service enforces its own server-generated order rather
    than accepting any movement.
    """
    if not sequence or len(sequence) < 2:
        sequence = ('LEFT', 'RIGHT')
    first, second = sequence[0], sequence[1]
    cycle = [NEUTRAL_YAW, _DIRECTION_YAW[second], NEUTRAL_YAW, _DIRECTION_YAW[first]]
    return cycle * int(repeats)


def static_yaws(count=14, yaw=NEUTRAL_YAW):
    """A held pose repeated. A print-out/photo attack shape."""
    return [yaw] * int(count)


def no_return_yaws(sequence=None, repeats=3):
    """Turn one way and hold there, never returning through neutral."""
    if not sequence or len(sequence) < 1:
        sequence = ('LEFT', 'RIGHT')
    first = sequence[0]
    return [NEUTRAL_YAW, _DIRECTION_YAW[first], _DIRECTION_YAW[first]] * int(repeats)


def build_frames(identity, yaws, seed_base=0, size=360, **render_kwargs):
    """Render ``yaws`` for ``identity`` into a list of JPEG byte strings."""
    return [
        jpeg(render(identity, yaw=y, seed=seed_base + index * 977 + 13,
                    size=size, **render_kwargs))
        for index, y in enumerate(yaws)
    ]


def compliant_frames(identity, sequence=None, repeats=1, max_frames=3, **kwargs):
    frames = build_frames(identity, compliant_yaws(sequence, repeats), **kwargs)
    if max_frames is not None:
        return frames[:max_frames]
    return frames


def other_identity(index=None, exclude=()):
    """Pick a fixture identity different from ``exclude`` (for impostor tests)."""
    if index is not None:
        return index
    for candidate in FIXTURE_IDENTITIES:
        if candidate not in exclude:
            return candidate
    raise ValueError('no alternate identity available')
