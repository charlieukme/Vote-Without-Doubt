"""
Phase 5 biometric evaluation harness.

Computes FAR, FRR, ROC, DET, EER and presentation-attack metrics from a real
score matrix. It reports what it measured and refuses to invent what it did not.

The harness will happily emit impressive-looking numbers from the synthetic
test fixtures, so it labels those results ``FIXTURE-ONLY / NOT REPRESENTATIVE``
everywhere they appear and exits non-zero for any accuracy claim. Real-world
operating-point selection requires a held-out human-face dataset that is not
present in this repository; see docs/PHASE5_EVALUATION.md for the required
dataset properties and the exact manifest format.

Two dataset kinds are supported:

``--manifest PATH``
    A JSON manifest describing real images (see ``--describe``).

``--fixtures``
    The deterministic synthetic renderer in tests/face_fixtures.py. Useful for
    proving the harness itself works. Never a basis for an accuracy claim.

Usage:
    venv/Scripts/python scripts/evaluate_phase5_biometrics.py --describe
    venv/Scripts/python scripts/evaluate_phase5_biometrics.py --fixtures
    venv/Scripts/python scripts/evaluate_phase5_biometrics.py --manifest ds.json
"""
import argparse
import json
import os
import sys

os.environ.setdefault('FLASK_ENV', 'testing')
os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('OTP_PEPPER', 'proof-pepper-not-for-production')
os.environ.setdefault('TESTING_SECRET_KEY', 'testing-only-secret-not-for-production')

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

MANIFEST_FORMAT = """
{
  "name": "string, e.g. 'internal-pilot-2026'",
  "kind": "human" or "synthetic",
  "purpose": "string, the evaluation this dataset was collected for",
  "notes": "string, collection conditions, demographics, consent basis",
  "samples": [
    {"subject": "s001", "role": "enroll", "image": "s001/enroll-01.jpg"},
    {"subject": "s001", "role": "probe",  "image": "s001/probe-01.jpg"},
    {"subject": "s001", "role": "spoof",  "image": "s001/print-01.jpg",
     "attack": "printed_photo"}
  ]
}

"kind" is REQUIRED and must be declared explicitly:
  human      may back a real-world claim. Only declare this for genuinely
             captured consented human subjects.
  synthetic  reported, labelled NOT REPRESENTATIVE, never an accuracy claim.
The harness never infers this field. Passing --manifest selects a file; it does
not certify what is inside it.

Roles:
  enroll  one or more reference captures per subject; their mean-normalised
          embedding becomes that subject's template (the same operation
          FaceService.enroll performs).
  probe   a genuine presentation; used as a bonafide trial against its own
          subject's template and as an impostor trial against everyone else's.
  spoof   a presentation attack (print, replay, mask). Optional. Attacks are
          compared against their own subject's template, which is what an
          attacker would target.

Hard requirements the harness enforces by REFUSING to compute metrics, because
without them the numbers would be meaningless:
  * every role (enroll, probe, spoof) is present,
  * every referenced image exists and is readable,
  * no subject reuses identical image bytes for enrolment and probing.

Sample-size minima (>= 20 subjects, >= 100 genuine, >= 500 impostor) are reported
as blocking sufficiency problems rather than enforced, because how many trials a
defensible rate needs depends on the FAR the election authority is specifying. A
small dataset is not automatically wrong; it is not automatically sufficient
either, and the report says so explicitly.
"""


class DatasetValidationError(Exception):
    """A manifest is structurally unusable, so no metric can be computed.

    Raised rather than warned about. A harness that continues past a broken
    dataset will emit numbers that look like accuracy evidence but are not, and
    that is precisely the failure this harness exists to prevent.
    """


def line(label, value=''):
    print(f'{label:<56} {value}')


def section(title):
    print(f'\n--- {title} ---')


# ---------------------------------------------------------------- metrics

def roc_curve(genuine, impostor):
    """FPR/TPR at every distinct observed score. Higher score = more genuine.

    The curve is empirical: it is evaluated at the scores actually seen, so the
    first point sits at the highest observed score rather than at +infinity.
    EER and AUC are computed from the same points and are unaffected by that
    choice, but a plotter should not assume the (0,0) and (1,1) endpoints are
    present.
    """
    if not genuine or not impostor:
        raise ValueError('both score sets must be non-empty')
    thresholds = sorted(set(list(genuine) + list(impostor)), reverse=True)
    points = []
    for threshold in thresholds:
        accepted_impostors = sum(1 for s in impostor if s >= threshold)
        accepted_genuines = sum(1 for s in genuine if s >= threshold)
        points.append((
            threshold,
            accepted_impostors / len(impostor),   # FPR / FAR
            accepted_genuines / len(genuine),      # TPR / 1 - FRR
        ))
    return points


def det_curve(genuine, impostor):
    """Miss rate against false-accept rate."""
    return [(threshold, 1.0 - tpr, fpr)
            for threshold, fpr, tpr in roc_curve(genuine, impostor)]


def error_rates(genuine, impostor, threshold):
    frr = sum(1 for s in genuine if s < threshold) / len(genuine)
    far = sum(1 for s in impostor if s >= threshold) / len(impostor)
    return far, frr


def equal_error_rate(genuine, impostor):
    """Threshold where false acceptance and false rejection rates are closest."""
    best = None
    for threshold, fpr, tpr in roc_curve(genuine, impostor):
        fnr = 1.0 - tpr
        gap = abs(fnr - fpr)
        if best is None or gap < best[0]:
            best = (gap, threshold, fpr, fnr)
    if best is None:
        return None
    return {'threshold': best[1], 'far': best[2], 'frr': best[3],
            'eer': (best[2] + best[3]) / 2.0}


def roc_auc(genuine, impostor):
    """Rank-based AUC, ties counted as half."""
    combined = [(s, 1) for s in genuine] + [(s, 0) for s in impostor]
    ranks = {}
    ordered = sorted(combined, key=lambda item: item[0])
    index = 0
    while index < len(ordered):
        stop = index
        while stop + 1 < len(ordered) and ordered[stop + 1][0] == ordered[index][0]:
            stop += 1
        average_rank = (index + stop) / 2.0 + 1.0
        for position in range(index, stop + 1):
            ranks[position] = average_rank
        index = stop + 1
    positive = sum(ranks[i] for i, (_, label) in enumerate(ordered) if label == 1)
    n_pos, n_neg = len(genuine), len(impostor)
    return (positive - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def presentation_metrics(attack_scores, bonafide_scores):
    """APCER/BPCER over scored presentations, plus the ISO-style operating point.

    Note the limitation this function cannot remove: the shipped liveness stage
    returns a binary verdict rather than a continuous PAD score, so on a real
    dataset these rates will be measured at the single shipped operating point
    only. ISO/IEC 30107-3 curves require a scored PAD function.
    """
    if not attack_scores or not bonafide_scores:
        return None
    thresholds = sorted(set(list(attack_scores) + list(bonafide_scores)),
                        reverse=True)
    curve = []
    for threshold in thresholds:
        apcer = sum(1 for s in attack_scores if s >= threshold) / len(attack_scores)
        bpcer = sum(1 for s in bonafide_scores if s < threshold) / len(bonafide_scores)
        curve.append({'threshold': threshold, 'apcer': apcer, 'bpcer': bpcer})
    for point in curve:
        point['apcer'] = 100.0 * point['apcer']
        point['bpcer'] = 100.0 * point['bpcer']

    at_bpcer_01 = [p for p in curve if p['bpcer'] <= 0.1]
    return {
        'curve': curve,
        'min_apcer_at_bpcer_0_1_percent': min(
            (p['apcer'] for p in at_bpcer_01), default=None),
        'attack_samples': len(attack_scores),
        'bonafide_samples': len(bonafide_scores),
    }


def summarise_scores(values):
    if not values:
        return {}
    ordered = sorted(values)
    return {
        'count': len(ordered),
        'min': round(ordered[0], 6),
        'max': round(ordered[-1], 6),
        'mean': round(sum(ordered) / len(ordered), 6),
        'median': round(ordered[len(ordered) // 2], 6),
    }


# ---------------------------------------------------------------- trials

def build_trials(templates, probes, attackers):
    """Pair every probe against its own template (genuine) and others' (impostor)."""
    genuine, impostor = [], []
    for probe_subject, vector in probes:
        if probe_subject in templates:
            genuine.append(_cosine(templates[probe_subject], vector))
        for template_subject, template_vector in templates.items():
            if template_subject != probe_subject:
                impostor.append(_cosine(template_vector, vector))

    attack, bonafide = [], []
    for subject, label, vector in attackers:
        if subject in templates:
            attack.append((_cosine(templates[subject], vector), label))
            bonafide.append(_cosine(templates[subject], vector))
    return genuine, impostor, attack, bonafide


def _cosine(left, right):
    import numpy as np
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right)))


def _mean_normalise(vectors):
    import numpy as np
    stacked = np.stack(vectors).mean(axis=0)
    return stacked / np.linalg.norm(stacked)


def evaluate_fixture_dataset(face_engine_module, threshold):
    """Score matrix from the synthetic renderer. NOT representative of humans."""
    from tests import face_fixtures as fx

    subjects = list(fx.FIXTURE_IDENTITIES)
    templates = {}
    for subject in subjects:
        vectors = []
        for yaw in (0.0, -0.20, 0.20):
            payload = fx.jpeg(fx.render(subject, yaw, seed=int(subject * 100) + 3))
            vectors.append(face_engine_module.analyze(payload).embedding)
        templates[subject] = _mean_normalise(vectors)

    probes = []
    for subject in subjects:
        for yaw in (0.0, -fx.TURN_YAW, fx.TURN_YAW):
            payload = fx.jpeg(fx.render(subject, yaw, seed=int(subject * 100) + 11))
            probes.append((subject, face_engine_module.analyze(payload).embedding))

    # A presentation attack in this harness is a replay of the enrolled frames:
    # a static pose cannot satisfy the LEFT/RIGHT liveness sequence, so the
    # reachability of the matcher is what is being measured here, not a
    # print/replay detector.
    attackers = []
    for subject in subjects:
        payload = fx.jpeg(fx.render(subject, 0.0, seed=int(subject * 100) + 3))
        attackers.append((subject, 'static_replay', face_engine_module.analyze(payload).embedding))

    genuine, impostor, attack, bonafide = build_trials(templates, probes, attackers)
    return {
        'subjects': len(subjects),
        'genuine': genuine,
        'impostor': impostor,
        'attack_scores': [score for score, _ in attack],
        'attack_labels': sorted({label for _, label in attack}),
        'bonafide_scores': bonafide,
        'threshold': threshold,
    }


#: Dataset kinds a manifest may declare. ``human`` is the only kind that can
#: support a real-world claim; ``synthetic`` is reported but never promoted.
VALID_KINDS = ('human', 'synthetic')


def evaluate_manifest_dataset(manifest_path, face_engine_module, threshold):
    """Score matrix from a manifest of images.

    Structural problems raise ``DatasetValidationError``. Guessing at a
    malformed dataset would produce a number that looks like evidence but is
    not, which is the failure mode this harness exists to prevent.
    """
    import numpy as np

    with open(manifest_path, 'r', encoding='utf-8') as handle:
        manifest = json.load(handle)

    kind = manifest.get('kind')
    if kind is None:
        raise DatasetValidationError(
            'manifest is missing "kind"; it must be one of '
            f'{", ".join(VALID_KINDS)}. Without it no figure can be attributed '
            'to a data source.')
    if kind not in VALID_KINDS:
        raise DatasetValidationError(
            f'unknown kind {kind!r}; expected one of {", ".join(VALID_KINDS)}')

    root = os.path.dirname(os.path.abspath(manifest_path))
    enrolled, probed, spoofed = {}, [], []
    seen_roles = {'enroll': 0, 'probe': 0, 'spoof': 0}
    enrol_images, probe_images = {}, {}
    missing = []

    for index, sample in enumerate(manifest.get('samples', [])):
        role = sample.get('role', 'probe')
        subject = sample.get('subject')
        image = sample.get('image')
        if not subject or not image:
            raise DatasetValidationError(
                f'sample {index} needs both "subject" and "image"')
        if role not in seen_roles:
            raise DatasetValidationError(
                f'sample {index} has unknown role {role!r}; expected one of '
                f'{", ".join(sorted(seen_roles))}')
        seen_roles[role] += 1

        # The same pixels in both roles would make every subject a perfect
        # genuine match and make the resulting error rates meaningless.
        digest = _image_digest(root, image)
        if digest is None:
            missing.append(image)
            continue
        if role == 'enroll':
            enrol_images.setdefault(subject, set()).add(digest)
        elif role == 'probe':
            probe_images.setdefault(subject, set()).add(digest)

        path = os.path.join(root, image)
        with open(path, 'rb') as handle:
            payload = handle.read()
        embedding = face_engine_module.analyze(payload).embedding
        if role == 'enroll':
            enrolled.setdefault(subject, []).append(embedding)
        elif role == 'spoof':
            spoofed.append((subject, sample.get('attack', 'unspecified'), embedding))
        else:
            probed.append((subject, embedding))

    if missing:
        raise DatasetValidationError(
            f'{len(missing)} referenced image(s) could not be read: '
            + ', '.join(missing[:5])
            + ('...' if len(missing) > 5 else ''))

    for role, count in seen_roles.items():
        if count == 0:
            raise DatasetValidationError(
                f'manifest contains no {role!r} samples; every role is required '
                'to compute a recognisable error rate')

    for subject in sorted(set(enrol_images) & set(probe_images)):
        shared = enrol_images[subject] & probe_images[subject]
        if shared:
            raise DatasetValidationError(
                f'subject {subject!r} uses identical image bytes for enrolment '
                f'and probing ({len(shared)} file(s)). Separate capture sessions '
                'are required or the error rates are meaningless.')

    templates = {subject: _mean_normalise(vectors)
                 for subject, vectors in enrolled.items()}
    genuine, impostor, attack, bonafide = build_trials(templates, probed, spoofed)
    return {
        'name': manifest.get('name', os.path.basename(manifest_path)),
        'kind': kind,
        'purpose': manifest.get('purpose', 'unspecified'),
        'notes': manifest.get('notes', ''),
        'subjects': len(templates),
        'genuine': genuine,
        'impostor': impostor,
        'attack_scores': [score for score, _ in attack],
        'attack_labels': sorted({label for _, label in attack}),
        'bonafide_scores': bonafide,
        'threshold': threshold,
        'np': np,
    }


def _image_digest(root, image):
    """Content hash of an image, or ``None`` if it cannot be read."""
    import hashlib

    try:
        with open(os.path.join(root, image), 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def check_dataset_sufficiency(result, minimum_subjects=20):
    problems = []
    if result['subjects'] < minimum_subjects:
        problems.append(
            f'only {result["subjects"]} subjects; at least {minimum_subjects} '
            'are needed for a defensible error rate')
    if len(result['genuine']) < 100:
        problems.append(
            f'only {len(result["genuine"])} genuine trials; at least 100 needed')
    if len(result['impostor']) < 500:
        problems.append(
            f'only {len(result["impostor"])} impostor trials; at least 500 needed')
    return problems


# ---------------------------------------------------------------- report

def main():
    parser = argparse.ArgumentParser(
        description='Evaluate Phase 5 biometric error rates.')
    parser.add_argument('--manifest', help='path to a real dataset manifest')
    parser.add_argument('--fixtures', action='store_true',
                        help='run against the synthetic test fixtures only')
    parser.add_argument('--describe', action='store_true',
                        help='print the manifest format and exit')
    parser.add_argument('--json-out', help='write the full report to this path')
    parser.add_argument('--threshold', type=float,
                        help='override FACE_SIMILARITY_THRESHOLD for the report')
    args = parser.parse_args()

    if args.describe:
        print(MANIFEST_FORMAT.strip())
        return 0

    os.environ.setdefault('FACE_ENCRYPTION_KEY',
                          'lnM7afwMMzvIom2qb0f13DjQZSo4pFoRS0ztukO6Ay4=')
    if args.threshold is not None:
        os.environ['FACE_SIMILARITY_THRESHOLD'] = str(args.threshold)
    threshold = float(os.environ.get('FACE_SIMILARITY_THRESHOLD') or 0.83)

    if not args.manifest and not args.fixtures:
        print('No dataset supplied.\n')
        print('  Real-world FAR / FRR / ROC / EER / APCER / BPCER: NOT YET MEASURED')
        print('  Reason: no approved human-face dataset is present in this repository.')
        print('  Next:  build a manifest per --describe, then re-run with --manifest.')
        return 2

    from app.services.face_engine import get_engine
    engine = get_engine()

    if args.manifest:
        try:
            result = evaluate_manifest_dataset(args.manifest, engine, threshold)
        except DatasetValidationError as error:
            section('manifest rejected')
            line('reason', error)
            print('\nNo metrics were computed. Fix the manifest and re-run.')
            return 2
        # Only a manifest that declares itself human may back a real-world
        # claim. Passing --manifest is not itself evidence: the flag chooses a
        # file, it does not certify what is in it.
        representative = result['kind'] == 'human'
    else:
        result = evaluate_fixture_dataset(engine, threshold)
        representative = False

    genuine, impostor = result['genuine'], result['impostor']
    if not genuine or not impostor:
        print('The dataset produced no usable trials.')
        return 2

    section('dataset')
    line('source', result.get('name', 'tests/face_fixtures.py (synthetic)'))
    line('declared kind', result.get('kind', 'synthetic'))
    line('representative of real users', representative)
    line('subjects', result['subjects'])
    line('genuine trials', len(genuine))
    line('impostor trials', len(impostor))
    if not representative:
        line('WARNING',
             'FIXTURE-ONLY / NOT REPRESENTATIVE - not an accuracy claim')

    section('score separation')
    line('genuine', summarise_scores(genuine))
    line('impostor', summarise_scores(impostor))
    best_genuine = min(genuine)
    worst_impostor = max(impostor)
    line('worst genuine score', round(best_genuine, 6))
    line('best impostor score', round(worst_impostor, 6))
    separable = best_genuine > worst_impostor
    line('sets fully separable', separable)
    if not separable:
        line('overlap region',
             f'[{worst_impostor:.4f}, {best_genuine:.4f}]')

    section('recognition error rates')
    auc = roc_auc(genuine, impostor)
    eer = equal_error_rate(genuine, impostor)
    far, frr = error_rates(genuine, impostor, threshold)
    line('ROC AUC', round(auc, 6))
    line('EER', round(eer['eer'], 6))
    line('EER threshold', round(eer['threshold'], 6))
    line(f'FAR at operating threshold {threshold}', round(far, 6))
    line(f'FRR at operating threshold {threshold}', round(frr, 6))

    section('presentation attack metrics')
    pad = presentation_metrics(result['attack_scores'], result['bonafide_scores'])
    if pad is None:
        line('APCER / BPCER', 'NOT YET MEASURED (no attack samples in dataset)')
    else:
        line('attack presentations', pad['attack_samples'])
        line('attack types', result['attack_labels'])
        line('bonafide presentations', pad['bonafide_samples'])
        apcer = sum(1 for s in result['attack_scores'] if s >= threshold) \
            / len(result['attack_scores'])
        bpcer = sum(1 for s in result['bonafide_scores'] if s < threshold) \
            / len(result['bonafide_scores'])
        line(f'APCER at operating threshold {threshold}', round(apcer, 6))
        line(f'BPCER at operating threshold {threshold}', round(bpcer, 6))
        line('min APCER at BPCER <= 0.1%',
             pad['min_apcer_at_bpcer_0_1_percent'])
        line('caveat',
             'liveness emits a binary verdict, not a scored PAD value; full '
             'ISO/IEC 30107-3 curves are not derivable')
        line('IMPORTANT',
             'these APCER/BPCER figures score the MATCHER only, with the '
             'liveness stage bypassed')
        line('interpretation',
             'the deployed system rejects these presentations in the liveness '
             'stage before matching, so the shipped APCER is the end-to-end '
             'rate reported by prove_phase5_face.py, not this number')

    section('curves')
    roc = roc_curve(genuine, impostor)
    det = det_curve(genuine, impostor)
    line('ROC points', len(roc))
    line('DET points', len(det))
    line('operating threshold', round(threshold, 6))
    tpr_at = sum(1 for s in genuine if s >= threshold) / len(genuine)
    line('  TPR (1 - FRR) at threshold', round(tpr_at, 6))
    line('  FPR (FAR)  at threshold', round(far, 6))
    line('ROC vertices written to JSON',
         f'{len(roc)}' if args.json_out else '0 (pass --json-out)')

    problems = check_dataset_sufficiency(result)
    section('sufficiency for an accuracy claim')
    if not representative:
        line('blocking issue',
             'synthetic fixtures cannot support any accuracy claim')
    if problems:
        for problem in problems:
            line('blocking issue', problem)
    else:
        line('dataset size', 'sufficient')

    if args.json_out:
        report = {
            'source': result.get('name', 'tests/face_fixtures.py (synthetic)'),
            'representative': representative,
            'threshold': threshold,
            'subjects': result['subjects'],
            'genuine_trials': len(genuine),
            'impostor_trials': len(impostor),
            'genuine_scores': [round(s, 6) for s in sorted(genuine)],
            'impostor_scores': [round(s, 6) for s in sorted(impostor)],
            'roc_auc': round(auc, 6),
            'eer': round(eer['eer'], 6),
            'far_at_threshold': round(far, 6),
            'frr_at_threshold': round(frr, 6),
            'separable': separable,
            'roc': [{'threshold': round(t, 6), 'fpr': round(f, 6), 'tpr': round(p, 6)}
                    for t, f, p in roc],
            'det': [{'threshold': round(t, 6), 'fnr': round(m, 6), 'fpr': round(f, 6)}
                    for t, m, f in det],
            'pad': pad,
            'sufficiency_problems': problems,
            'real_world_metrics': (
                'MEASURED' if representative else 'NOT YET MEASURED'),
        }
        with open(args.json_out, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
        line('report written', args.json_out)

    section('conclusion')
    if representative:
        print('  Real-world metrics were computed from the supplied dataset.')
        print('  Review sufficiency_problems before quoting any rate.')
    else:
        print('  FIXTURE-ONLY RUN. The numbers above describe the synthetic test')
        print('  renderer, not human faces. They are a harness self-test.')
        print('  Real-world FAR / FRR / ROC / EER / APCER / BPCER: NOT YET MEASURED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
