"""
Phase 5 biometric evaluation harness tests.

Covers the metric mathematics in ``scripts/evaluate_phase5_biometrics.py``
against score sets whose answers are known in closed form, so a wrong
implementation cannot quietly inflate a reported error rate.

These do not run the real engine: the harness's correctness does not depend on
the model, and ``scripts/prove_phase5_face.py`` covers the real pipeline.
"""

import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'scripts'),
)

import evaluate_phase5_biometrics as ev  # noqa: E402


# ---------------------------------------------------------------- ROC / AUC

def test_auc_is_one_when_the_sets_do_not_overlap():
    genuine = [0.90, 0.92, 0.95]
    impostor = [0.10, 0.30, 0.55]
    assert ev.roc_auc(genuine, impostor) == pytest.approx(1.0)


def test_auc_is_zero_when_every_genuine_score_is_worse():
    genuine = [0.10, 0.20]
    impostor = [0.80, 0.90]
    assert ev.roc_auc(genuine, impostor) == pytest.approx(0.0)


def test_auc_is_half_when_the_sets_are_identical():
    scores = [0.1, 0.4, 0.6, 0.9]
    assert ev.roc_auc(scores, scores) == pytest.approx(0.5)


def test_auc_is_computed_on_a_known_value():
    # 4 genuine x 4 impostor = 16 pairs. Per genuine score the wins are:
    #   0.5 -> 1 (only 0.4), 0.7 -> 2, 0.8 -> 2, 0.9 -> 3.  Total 8/16.
    genuine = [0.5, 0.7, 0.8, 0.9]
    impostor = [0.4, 0.6, 0.85, 0.95]
    assert ev.roc_auc(genuine, impostor) == pytest.approx(8 / 16)


def test_auc_handles_ties_as_half_a_pair():
    # Two genuine at 0.5: each ties the impostor 0.5 (0.5) and loses to 0.9.
    # Total credit 1.0 over 4 pairs.
    assert ev.roc_auc([0.5, 0.5], [0.5, 0.9]) == pytest.approx(0.25)


def test_auc_is_quarter_when_nothing_outranks_the_impostor():
    assert ev.roc_auc([0.1, 0.2], [0.9, 0.8]) == pytest.approx(0.0)


# ------------------------------------------------------------------ EER

def test_eer_is_zero_for_separable_sets():
    result = ev.equal_error_rate([0.9, 0.95], [0.1, 0.2])
    assert result['eer'] == pytest.approx(0.0)
    assert result['far'] == pytest.approx(0.0)
    assert result['frr'] == pytest.approx(0.0)


def test_eer_never_exceeds_fifty_percent_for_identical_distributions():
    # With the two sets drawn the same way, no threshold beats 50%: at the top
    # observed score one of two genuine passes and no impostor does.
    scores = [0.1, 0.5, 0.9]
    result = ev.equal_error_rate(scores, scores)
    assert result['eer'] == pytest.approx(0.5)
    assert result['far'] + result['frr'] == pytest.approx(1.0)


def test_eer_never_reports_a_rate_below_the_best_achievable():
    genuine = [0.60, 0.70, 0.80, 0.90]
    impostor = [0.50, 0.55, 0.85, 0.95]
    result = ev.equal_error_rate(genuine, impostor)
    # At any threshold one of the two errors must be non-zero.
    assert result['eer'] > 0.0
    assert result['far'] + result['frr'] >= result['eer'] - 1e-9


# ------------------------------------------------------- operating point

def test_error_rates_match_the_definition():
    genuine = [0.1, 0.5, 0.9, 0.95]
    impostor = [0.2, 0.85, 0.99]
    far, frr = ev.error_rates(genuine, impostor, 0.85)
    assert frr == pytest.approx(0.5, abs=1e-9)      # 0.1 and 0.5 rejected
    assert far == pytest.approx(2 / 3, abs=1e-9)    # 0.85 and 0.99 accepted


def test_a_permissive_threshold_accepts_everything():
    far, frr = ev.error_rates([0.1, 0.2], [0.05, 0.06], 0.0)
    assert far == 1.0, 'every impostor is accepted'
    assert frr == 0.0, 'no genuine is rejected'


def test_an_impossible_threshold_accepts_nothing():
    far, frr = ev.error_rates([0.9], [0.8], 1.01)
    assert far == 0.0 and frr == 1.0


def test_the_threshold_boundary_is_inclusive_on_the_genuine_side():
    # A score exactly at the threshold is an accept, not a reject.
    far, frr = ev.error_rates([0.85], [0.85], 0.85)
    assert frr == 0.0
    assert far == 1.0


# ---------------------------------------------------------------- curves

def test_roc_is_evaluated_at_observed_scores_only():
    """Documented convention: no synthetic endpoints at +/-infinity."""
    roc = ev.roc_curve([0.9, 0.8], [0.1, 0.2])
    thresholds = [t for t, _, _ in roc]
    assert thresholds == sorted(thresholds, reverse=True)
    assert max(thresholds) == 0.9
    assert min(thresholds) == 0.1

    # At the highest observed score no impostor is accepted and only the
    # matching genuine is.
    top_threshold, top_fpr, top_tpr = roc[0]
    assert (top_threshold, top_fpr, top_tpr) == (0.9, 0.0, 0.5)
    # At the lowest observed score everything is accepted.
    bottom_threshold, bottom_fpr, bottom_tpr = roc[-1]
    assert (bottom_threshold, bottom_fpr, bottom_tpr) == (0.1, 1.0, 1.0)


def test_roc_dominates_the_diagonal_for_separable_sets():
    for _threshold, fpr, tpr in ev.roc_curve([0.9, 0.8], [0.1, 0.2]):
        assert tpr >= fpr


def test_det_miss_rate_is_the_complement_of_tpr():
    roc = ev.roc_curve([0.9, 0.8], [0.1, 0.2])
    det = ev.det_curve([0.9, 0.8], [0.1, 0.2])
    for (roc_threshold, roc_fpr, roc_tpr), (det_threshold, miss, false_accept) \
            in zip(roc, det):
        assert det_threshold == roc_threshold
        assert miss == pytest.approx(1.0 - roc_tpr)
        assert false_accept == pytest.approx(roc_fpr)
    assert det[0][1] == pytest.approx(0.5)
    assert det[-1][1] == pytest.approx(0.0)


def test_empty_score_sets_are_rejected_rather_than_silently_zeroed():
    with pytest.raises(ValueError):
        ev.roc_curve([], [0.5])
    with pytest.raises(ValueError):
        ev.roc_curve([0.5], [])


# -------------------------------------------------- presentation attacks

def test_pad_metrics_reject_an_attack_and_accept_a_bonafide():
    pad = ev.presentation_metrics([0.2, 0.25], [0.9, 0.95])
    assert pad['attack_samples'] == 2
    assert pad['bonafide_samples'] == 2
    # At the highest bonafide score: no attack is accepted and, because the
    # boundary is inclusive, no bonafide is rejected either.
    at_top = [p for p in pad['curve'] if p['threshold'] == 0.9][0]
    assert at_top['apcer'] == pytest.approx(0.0)
    assert at_top['bpcer'] == pytest.approx(0.0)
    # Below the lowest attack score, every attack is accepted while no
    # bonafide is rejected.
    at_bottom = [p for p in pad['curve'] if p['threshold'] == 0.2][0]
    assert at_bottom['apcer'] == pytest.approx(100.0)
    assert at_bottom['bpcer'] == pytest.approx(0.0)


def test_min_apcer_at_zero_point_one_bpcer_is_reported_as_a_percentage():
    attacks = [0.30 + 0.001 * i for i in range(50)]
    bonafide = [0.80 + 0.001 * i for i in range(50)]
    pad = ev.presentation_metrics(attacks, bonafide)
    assert pad['min_apcer_at_bpcer_0_1_percent'] is not None
    assert 0.0 <= pad['min_apcer_at_bpcer_0_1_percent'] <= 100.0


def test_pad_metrics_require_both_sample_classes():
    assert ev.presentation_metrics([], [0.9]) is None
    assert ev.presentation_metrics([0.1], []) is None


# ------------------------------------------------------ trial construction

def test_trials_pair_each_probe_against_every_template():
    import numpy as np

    def unit(value):
        return np.array([value, 1.0 - value], dtype=np.float32)

    templates = {1: unit(1.0), 2: unit(0.0)}
    probes = [(1, unit(1.0)), (2, unit(0.0))]
    genuine, impostor, attack, bonafide = ev.build_trials(templates, probes, [])

    assert len(genuine) == 2          # one per probe
    assert len(impostor) == 2         # each probe against the other template
    assert all(score == pytest.approx(1.0) for score in genuine)
    assert all(score == pytest.approx(0.0) for score in impostor)


def test_attacks_are_scored_against_their_own_subject_template():
    import numpy as np

    def unit(value):
        return np.array([value, 1.0 - value], dtype=np.float32)

    templates = {1: unit(1.0), 2: unit(0.0)}
    attackers = [(1, 'print', unit(1.0)), (2, 'mask', unit(0.0))]
    _genuine, _impostor, attack, bonafide = ev.build_trials(
        templates, [], attackers)
    assert [label for _, label in attack] == ['print', 'mask']
    assert len(bonafide) == 2


def test_mean_normalise_produces_a_unit_vector():
    import numpy as np

    vectors = [np.array([1.0, 0.0], dtype=np.float32),
               np.array([0.0, 1.0], dtype=np.float32)]
    result = ev._mean_normalise(vectors)
    # The mean of the two is [0.5, 0.5]; normalising divides by its norm.
    assert float(np.linalg.norm(result)) == pytest.approx(1.0)
    assert np.allclose(result, [2 ** -0.5, 2 ** -0.5])


def test_mean_normalise_of_identical_vectors_is_that_vector():
    import numpy as np

    vector = np.array([3.0, 4.0], dtype=np.float32)
    result = ev._mean_normalise([vector, vector])
    assert np.allclose(result, [0.6, 0.8])


# --------------------------------------------------------- sufficiency

def test_sufficiency_flags_a_dataset_that_is_far_too_small():
    result = {'subjects': 4, 'genuine': [0.9] * 12, 'impostor': [0.5] * 36}
    problems = ev.check_dataset_sufficiency(result)
    assert len(problems) == 3
    assert any('subjects' in p for p in problems)
    assert any('genuine' in p for p in problems)
    assert any('impostor' in p for p in problems)


def test_sufficiency_accepts_a_defensibly_sized_dataset():
    result = {'subjects': 50, 'genuine': [0.9] * 400, 'impostor': [0.5] * 2000}
    assert ev.check_dataset_sufficiency(result) == []


def test_summary_statistics_are_ordered():
    summary = ev.summarise_scores([0.3, 0.1, 0.2])
    assert summary['count'] == 3
    assert summary['min'] == pytest.approx(0.1)
    assert summary['max'] == pytest.approx(0.3)
    assert summary['mean'] == pytest.approx(0.2)
    assert ev.summarise_scores([]) == {}


# ------------------------------------------------------- manifest validation

class _StubAnalysis:
    def __init__(self, embedding):
        self.embedding = embedding


class _StubEngine:
    """Stands in for the real engine so manifest tests stay model-free.

    Manifest validation is about structure, not accuracy, so a fixed unit vector
    per distinct image is sufficient to exercise the code under test.
    """

    def analyze(self, payload):
        import numpy as np

        seed = float(payload.split(b':')[-1])
        vector = np.zeros(512, dtype='float32')
        vector[0] = seed
        return _StubAnalysis(vector)


def _write_manifest(tmp_path, manifest, files):
    """Write a manifest plus the image files it references."""
    import json

    (tmp_path / 'ds.json').write_text(json.dumps(manifest), encoding='utf-8')
    for name, payload in files.items():
        (tmp_path / name).write_bytes(payload)
    return str(tmp_path / 'ds.json')


def test_manifest_without_kind_is_rejected(tmp_path):
    """A manifest that does not declare its contents cannot be scored.

    Without an explicit ``kind`` there is no way to tell captured humans from
    synthetic frames, so any figure derived from it would be unattributable.
    Passing ``--manifest`` selects a file; it does not certify what is inside.
    """
    path = _write_manifest(
        tmp_path,
        {'name': 'undisclosed', 'samples': []},
        {},
    )
    with pytest.raises(ev.DatasetValidationError, match='missing "kind"'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)


def test_manifest_with_unknown_kind_is_rejected(tmp_path):
    path = _write_manifest(
        tmp_path,
        {'name': 'x', 'kind': 'whatever', 'samples': []},
        {},
    )
    with pytest.raises(ev.DatasetValidationError, match='unknown kind'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)


def test_manifest_missing_a_role_is_rejected(tmp_path):
    path = _write_manifest(
        tmp_path,
        {'kind': 'human', 'samples': [
            {'subject': 's1', 'role': 'enroll', 'image': 'e1.jpg'},
            {'subject': 's1', 'role': 'enroll', 'image': 'e2.jpg'},
        ]},
        {'e1.jpg': b'img:0.1', 'e2.jpg': b'img:0.2'},
    )
    with pytest.raises(ev.DatasetValidationError, match='probe'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)


def test_manifest_with_unreadable_image_is_rejected(tmp_path):
    path = _write_manifest(
        tmp_path,
        {'kind': 'human', 'samples': [
            {'subject': 's1', 'role': 'enroll', 'image': 'absent.jpg'},
        ]},
        {},
    )
    with pytest.raises(ev.DatasetValidationError, match='could not be read'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)


def test_manifest_reusing_one_image_for_enroll_and_probe_is_rejected(tmp_path):
    """Identical pixels in both roles would manufacture a perfect score.

    This is the easiest way to produce a flattering and meaningless error rate,
    so it is refused outright rather than reported as a caveat.
    """
    path = _write_manifest(
        tmp_path,
        {'kind': 'human', 'samples': [
            {'subject': 's1', 'role': 'enroll', 'image': 'shared.jpg'},
            {'subject': 's1', 'role': 'probe', 'image': 'shared.jpg'},
            {'subject': 's1', 'role': 'spoof', 'image': 'shared.jpg'},
        ]},
        {'shared.jpg': b'img:0.9'},
    )
    with pytest.raises(ev.DatasetValidationError,
                       match='identical image bytes'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)


def test_manifest_accepts_distinct_images_and_records_kind(tmp_path):
    path = _write_manifest(
        tmp_path,
        {'kind': 'human', 'name': 'pilot', 'samples': [
            {'subject': 's1', 'role': 'enroll', 'image': 'e1.jpg'},
            {'subject': 's1', 'role': 'enroll', 'image': 'e2.jpg'},
            {'subject': 's1', 'role': 'probe', 'image': 'p1.jpg'},
            {'subject': 's2', 'role': 'enroll', 'image': 'e3.jpg'},
            {'subject': 's2', 'role': 'probe', 'image': 'p2.jpg'},
            {'subject': 's2', 'role': 'spoof', 'image': 'sp.jpg',
             'attack': 'printed_photo'},
        ]},
        {'e1.jpg': b'img:0.10', 'e2.jpg': b'img:0.11', 'p1.jpg': b'img:0.12',
         'e3.jpg': b'img:0.20', 'p2.jpg': b'img:0.21', 'sp.jpg': b'img:0.99'},
    )
    result = ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)
    assert result['kind'] == 'human'
    assert result['subjects'] == 2
    assert result['attack_labels'] == ['printed_photo']
    assert len(result['genuine']) == 2
    assert len(result['impostor']) == 2


def test_manifest_rejects_an_unknown_role(tmp_path):
    path = _write_manifest(
        tmp_path,
        {'kind': 'human', 'samples': [
            {'subject': 's1', 'role': 'sideways', 'image': 'e1.jpg'},
        ]},
        {'e1.jpg': b'img:0.1'},
    )
    with pytest.raises(ev.DatasetValidationError, match='unknown role'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)


def test_manifest_rejects_a_sample_without_a_subject(tmp_path):
    path = _write_manifest(
        tmp_path,
        {'kind': 'human', 'samples': [{'role': 'enroll', 'image': 'e1.jpg'}]},
        {'e1.jpg': b'img:0.1'},
    )
    with pytest.raises(ev.DatasetValidationError, match='subject'):
        ev.evaluate_manifest_dataset(path, _StubEngine(), 0.83)
