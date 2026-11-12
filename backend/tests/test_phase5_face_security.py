"""
Phase 5 face security tests: encryption, challenge binding and the API surface.

These exercise the real service against the real engine. Where a test needs to
observe internals (for example the MAC over a stored challenge row) it inspects
genuine persisted state rather than replacing the biometric logic.
"""

import os
from datetime import datetime, timedelta

import numpy as np
import pytest
from cryptography.fernet import Fernet

from app.models import AuthSession, FaceChallenge, FaceEnrollment
from app.security.face import (
    FaceCiphertextError,
    FaceKeyUnavailable,
    FaceSecurityError,
    challenge_mac,
    decrypt_embedding,
    encrypt_embedding,
    envelope_key_id,
    generate_challenge_nonce,
    generate_face_challenge_id,
    verify_challenge_mac,
)
from tests import face_fixtures as fx
from tests.conftest import _seed_authorized_session, post_frames

ME = fx.FIXTURE_IDENTITIES[0]
OTHER = fx.other_identity(exclude=(ME,))
KEY = 'lnM7afwMMzvIom2qb0f13DjQZSo4pFoRS0ztukO6Ay4='


# ===========================================================================
# Template encryption
# ===========================================================================

def test_encrypt_round_trips():
    payload = np.linspace(-1, 1, 512, dtype=np.float32).tobytes()
    blob = encrypt_embedding(payload)
    assert blob != payload
    assert decrypt_embedding(blob) == payload


def test_envelope_records_its_key_id(monkeypatch):
    """The envelope names the key it was written with, so it can be rotated."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv('FACE_ENCRYPTION_KEY', key)
    monkeypatch.setenv('FACE_ENCRYPTION_KEY_ID', 'v3')
    blob = encrypt_embedding(b'x' * 64)
    assert envelope_key_id(blob) == 'v3'
    assert decrypt_embedding(blob) == b'x' * 64


def test_encryption_requires_an_explicit_key(monkeypatch):
    """No random/ephemeral key may be generated when none is configured."""
    monkeypatch.delenv('FACE_ENCRYPTION_KEY', raising=False)
    monkeypatch.delenv('FACE_ENCRYPTION_KEYS', raising=False)
    with pytest.raises(FaceKeyUnavailable):
        encrypt_embedding(b'payload')


def test_decryption_fails_closed_without_a_key(monkeypatch):
    blob = encrypt_embedding(b'secret-template')
    monkeypatch.delenv('FACE_ENCRYPTION_KEY', raising=False)
    monkeypatch.delenv('FACE_ENCRYPTION_KEYS', raising=False)
    with pytest.raises(FaceKeyUnavailable):
        decrypt_embedding(blob)


def test_decryption_rejects_a_wrong_key(monkeypatch):
    blob = encrypt_embedding(b'secret-template')
    monkeypatch.setenv('FACE_ENCRYPTION_KEY', Fernet.generate_key().decode())
    with pytest.raises(FaceCiphertextError):
        decrypt_embedding(blob)


def test_decryption_rejects_tampered_ciphertext():
    blob = bytearray(encrypt_embedding(b'secret-template'))
    blob[-1] ^= 0x01
    with pytest.raises(FaceCiphertextError):
        decrypt_embedding(bytes(blob))


def test_decryption_rejects_a_malformed_envelope():
    for bad in (b'', b'nope', b'VWDF1', b'VWDF9' + b'x' * 40,
                b'XXXX1' + bytes([1, 2]) + b'v1' + b'y' * 30):
        with pytest.raises(FaceCiphertextError):
            decrypt_embedding(bad)


def test_decryption_rejects_an_unknown_envelope_version():
    blob = bytearray(encrypt_embedding(b'secret'))
    blob[5] = 9
    with pytest.raises(FaceCiphertextError):
        decrypt_embedding(bytes(blob))


def test_decryption_never_returns_the_ciphertext():
    """The old implementation returned its input on failure."""
    blob = encrypt_embedding(b'secret')
    try:
        out = decrypt_embedding(blob)
    except FaceSecurityError:
        return
    assert out == b'secret'


def test_encrypt_rejects_empty_and_non_bytes():
    with pytest.raises(FaceSecurityError):
        encrypt_embedding(b'')
    with pytest.raises(FaceSecurityError):
        encrypt_embedding('not bytes at all')


def test_key_rotation_accepts_an_old_template(monkeypatch):
    """A template written under v1 must stay readable after rotating to v2."""
    original = 'lnM7afwMMzvIom2qb0f13DjQZSo4pFoRS0ztukO6Ay4='
    rotated = Fernet.generate_key().decode()
    monkeypatch.setenv('FACE_ENCRYPTION_KEY', original)
    monkeypatch.setenv('FACE_ENCRYPTION_KEY_ID', 'v1')
    blob = encrypt_embedding(b'template-v1')

    monkeypatch.setenv('FACE_ENCRYPTION_KEY_ID', 'v2')
    monkeypatch.setenv('FACE_ENCRYPTION_KEY', rotated)
    with pytest.raises(FaceKeyUnavailable):
        decrypt_embedding(blob)

    monkeypatch.setenv('FACE_ENCRYPTION_KEYS',
                       '{"v1": "%s", "v2": "%s"}' % (original, rotated))
    assert decrypt_embedding(blob) == b'template-v1'
    new_blob = encrypt_embedding(b'template-v2')
    assert envelope_key_id(new_blob) == 'v2'


# ===========================================================================
# Challenge material
# ===========================================================================

def test_challenge_identifiers_are_256_bit_and_unique():
    ids = {generate_face_challenge_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(value) == 64 for value in ids)
    nonces = {generate_challenge_nonce() for _ in range(200)}
    assert len(nonces) == 200


def test_challenge_mac_detects_tampering():
    base = challenge_mac('cid', 1, 'sid', 'LEFT,RIGHT', 'nonce',
                         '2026-01-01T00:00:00')
    assert verify_challenge_mac(base, base)
    for changed in (
        challenge_mac('cid2', 1, 'sid', 'LEFT,RIGHT', 'nonce', '2026-01-01T00:00:00'),
        challenge_mac('cid', 2, 'sid', 'LEFT,RIGHT', 'nonce', '2026-01-01T00:00:00'),
        challenge_mac('cid', 1, 'sid2', 'LEFT,RIGHT', 'nonce', '2026-01-01T00:00:00'),
        challenge_mac('cid', 1, 'sid', 'RIGHT,LEFT', 'nonce', '2026-01-01T00:00:00'),
        challenge_mac('cid', 1, 'sid', 'LEFT,RIGHT', 'nonce2', '2026-01-01T00:00:00'),
        challenge_mac('cid', 1, 'sid', 'LEFT,RIGHT', 'nonce', '2026-01-02T00:00:00'),
    ):
        assert not verify_challenge_mac(base, changed)
    assert not verify_challenge_mac(base, '')


# ===========================================================================
# Authentication boundary
# ===========================================================================

@pytest.mark.parametrize('path,method', [
    ('/api/face/challenge', 'post'),
    ('/api/face/enroll', 'post'),
    ('/api/face/verify', 'post'),
    ('/api/face/status', 'get'),
    ('/api/face/withdraw-consent', 'post'),
])
def test_every_face_endpoint_requires_a_session(app, db, path, method):
    """No face endpoint may act on an anonymous request."""
    client = app.test_client()
    response = getattr(client, method)(path)
    assert response.status_code == 401, (path, response.get_json())


@pytest.mark.parametrize('path,method', [
    # Routes from the pre-remediation implementation that must not come back.
    ('/api/face/consent', 'post'),
    ('/api/face/challenge/enroll', 'post'),
    ('/api/face/challenge/verify', 'post'),
    ('/api/face/challenge/status', 'get'),
    ('/api/face/withdraw', 'post'),
    ('/api/face/delete', 'post'),
])
def test_superseded_face_endpoints_are_gone(app, db, path, method):
    """Legacy biometric routes must stay absent, authenticated or not."""
    client = app.test_client()
    response = getattr(client, method)(path)
    assert response.status_code == 404, (path, response.status_code)


def test_face_endpoints_reject_a_pending_session(app, db, face_user, signed_cookie_for):
    """A live but not AUTHORIZED session must not reach biometric code."""
    record = _seed_authorized_session(db, face_user, auth_state='PENDING_OTP')
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                      signed_cookie_for(record.session_id))
    assert client.get('/api/face/status').status_code == 401


def test_face_endpoints_reject_a_revoked_session(app, db, face_user,
                                                 signed_cookie_for):
    record = _seed_authorized_session(db, face_user)
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                      signed_cookie_for(record.session_id))
    assert client.get('/api/face/status').status_code == 200
    AuthSession.query.filter_by(session_id=record.session_id).first().revoked = True
    db.session.commit()
    assert client.get('/api/face/status').status_code == 401


def test_face_endpoints_reject_an_expired_session(app, db, face_user,
                                                 signed_cookie_for):
    """Session expiry must be honoured, not just revocation."""
    record = _seed_authorized_session(db, face_user)
    record.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                      signed_cookie_for(record.session_id))
    assert client.get('/api/face/status').status_code == 401


def test_face_endpoints_reject_an_idle_expired_session(app, db, face_user,
                                                       signed_cookie_for):
    record = _seed_authorized_session(db, face_user)
    record.idle_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                      signed_cookie_for(record.session_id))
    assert client.get('/api/face/status').status_code == 401


# ===========================================================================
# Challenge issuance
# ===========================================================================

def test_challenge_is_randomised_and_bound(face_client, db, face_user, face_session):
    challenges = set()
    for _ in range(12):
        response = face_client.post('/api/face/challenge')
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload['sequence'] == []
        challenges.add(payload['challenge_id'])
        assert payload['min_frames'] == 1
        assert payload['max_frames'] == 5
        assert payload['expires_in_seconds'] <= 20
    assert len(challenges) == 12, 'the server must issue unique randomised challenge IDs'


def test_challenge_row_is_bound_to_user_and_session(face_client, db, face_user,
                                                    face_session):
    face_client.post('/api/face/challenge')
    row = FaceChallenge.query.filter_by(user_id=face_user.id).one()
    assert row.session_id == face_session.session_id
    assert len(row.nonce) == 64
    assert row.integrity_mac
    assert row.attempt_count == 0
    assert row.max_attempts >= 1


def test_challenge_ids_are_unique(face_client, db, face_user):
    ids = {face_client.post('/api/face/challenge').get_json()['challenge_id']
           for _ in range(10)}
    assert len(ids) == 10


def test_challenge_expires(face_client, db, face_user):
    challenge = face_client.post('/api/face/challenge').get_json()
    row = FaceChallenge.query.filter_by(
        challenge_id=challenge['challenge_id']).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    response = post_frames(
        face_client, '/api/face/verify',
        fx.compliant_frames(ME, challenge['sequence']), challenge['challenge_id'])
    assert response.status_code == 400


def test_challenge_cannot_be_used_by_another_user(app, db, face_client, face_user,
                                                  other_face_user, second_face_session,
                                                  signed_cookie_for):
    challenge = face_client.post('/api/face/challenge').get_json()
    other_record = _seed_authorized_session(db, other_face_user)
    intruder = app.test_client()
    intruder.set_cookie(app.config['SESSION_COOKIE_NAME'],
                        signed_cookie_for(other_record.session_id))
    response = post_frames(
        intruder, '/api/face/enroll',
        fx.compliant_frames(ME, challenge['sequence']), challenge['challenge_id'],
        consent=True)
    assert response.status_code == 400


def test_challenge_cannot_be_used_from_another_session(app, db, face_user,
                                                       face_session,
                                                       second_face_session,
                                                       signed_cookie_for):
    """Session binding: same user, different session, still rejected."""
    face_client = app.test_client()
    face_client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                           signed_cookie_for(face_session.session_id))
    challenge = face_client.post('/api/face/challenge').get_json()

    other = app.test_client()
    other.set_cookie(app.config['SESSION_COOKIE_NAME'],
                     signed_cookie_for(second_face_session.session_id))
    response = post_frames(
        other, '/api/face/enroll',
        fx.compliant_frames(ME, challenge['sequence']), challenge['challenge_id'],
        consent=True)
    assert response.status_code == 400


def test_unknown_challenge_is_rejected(face_client):
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, ['LEFT', 'RIGHT']),
                           '0' * 64)
    assert response.status_code == 400


def test_missing_challenge_is_rejected(face_client):
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, ['LEFT', 'RIGHT']), '')
    assert response.status_code == 400


def test_tampered_stored_sequence_fails_its_mac(face_client, db, face_user):
    """Editing the expected order in the database must be detected."""
    challenge = face_client.post('/api/face/challenge').get_json()
    row = FaceChallenge.query.filter_by(
        challenge_id=challenge['challenge_id']).one()
    row.challenge_sequence = 'TAMPERED_SEQUENCE'
    db.session.commit()
    response = post_frames(
        face_client, '/api/face/enroll',
        fx.compliant_frames(ME), challenge['challenge_id'],
        consent=True)
    assert response.status_code == 400
    assert FaceEnrollment.query.count() == 0


# ===========================================================================
# Enrolment
# ===========================================================================

def _enrol(client, identity=ME, consent=True, frame_count=3):
    challenge = client.post('/api/face/challenge').get_json()
    frames = fx.compliant_frames(identity)[:frame_count]
    return post_frames(client, '/api/face/enroll', frames,
                       challenge['challenge_id'], consent=consent), challenge


def test_enrolment_stores_a_real_encrypted_template(face_client, db, face_user):
    response, _ = _enrol(face_client)
    assert response.status_code == 200, response.get_json()
    row = FaceEnrollment.query.filter_by(user_id=face_user.id).one()
    assert row.is_enrolled and row.consent_given
    assert row.consent_purpose
    assert row.consent_at is not None
    assert row.embedding_dim == 512
    assert row.embedding_model == 'buffalo_l/w600k_r50'
    assert row.embedding_method == 'arcface_cosine'
    blob = bytes(row.encrypted_embedding)
    assert blob[:5] == b'VWDF1'
    assert len(blob) > 512 * 4
    assert b'embedding_stub' not in blob
    # The decrypted payload must be a real unit-length 512-d vector.
    from app.security.face import decrypt_embedding
    plaintext = decrypt_embedding(blob)
    vector = np.frombuffer(plaintext[:512 * 4], dtype=np.float32)
    assert vector.shape == (512,)
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-4)


def test_no_raw_frame_or_embedding_is_persisted(face_client, db, face_user):
    """Frames live only in memory; nothing biometric is left in a file."""
    import glob
    import tempfile
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), '*.jpg')))
    _enrol(face_client)
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), '*.jpg')))
    assert before == after
    row = FaceEnrollment.query.filter_by(user_id=face_user.id).one()
    blob = bytes(row.encrypted_embedding)
    marker = fx.jpeg(fx.render(ME, 0.0, seed=0))
    assert marker[:64] not in blob
    assert marker not in blob


def test_enrolment_requires_consent(face_client, db, face_user):
    response, _ = _enrol(face_client, consent=False)
    assert response.status_code == 400
    assert FaceEnrollment.query.count() == 0


def test_enrolment_rejects_the_wrong_movement_order(face_client, db, face_user):
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.build_frames(ME, fx.reversed_yaws(challenge['sequence'], repeats=4))
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400
    assert FaceEnrollment.query.count() == 0


def test_enrolment_rejects_a_static_photo_pose(face_client, db, face_user):
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.build_frames(ME, fx.static_yaws(16))
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400
    assert FaceEnrollment.query.count() == 0


def test_enrolment_rejects_a_held_single_turn(face_client, db, face_user):
    """Turning once and holding never satisfies the second target."""
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.build_frames(ME, fx.no_return_yaws(challenge['sequence'], repeats=4))
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400


def test_enrolment_rejects_frames_without_the_required_movement(
        face_client, db, face_user):
    """All frames turned the same way: no neutral return, so no liveness."""
    challenge = face_client.post('/api/face/challenge').get_json()
    turn = fx.TURN_YAW
    frames = fx.build_frames(ME, [turn] * 16)
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400


@pytest.mark.parametrize('count', [0, 6, 9, 25, 40])
def test_enrolment_enforces_the_frame_count_policy(face_client, db, face_user, count):
    challenge = face_client.post('/api/face/challenge').get_json()
    pool = fx.build_frames(ME, fx.compliant_yaws(None, 12))
    assert len(pool) > 40
    response = post_frames(face_client, '/api/face/enroll', pool[:count],
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400, count
    assert FaceEnrollment.query.count() == 0


def test_enrolment_rejects_non_jpeg_payloads(face_client, db, face_user):
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = [b'GIF89a-not-a-frame' for _ in range(12)]
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400


def test_enrolment_rejects_a_frame_with_two_faces(face_client, db, face_user):
    import cv2
    challenge = face_client.post('/api/face/challenge').get_json()
    canvas = np.full((480, 760, 3), 120, np.uint8)
    canvas[60:420, 20:380] = fx.render(ME, 0.0, seed=31)
    canvas[60:420, 380:740] = fx.render(OTHER, 0.0, seed=32)
    ok, buf = cv2.imencode('.jpg', canvas)
    assert ok
    frames = [buf.tobytes() for _ in range(12)]
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400


def test_enrolment_is_single_use(face_client, db, face_user):
    response, challenge = _enrol(face_client)
    assert response.status_code == 200
    replay = post_frames(
        face_client, '/api/face/enroll',
        fx.compliant_frames(ME, challenge['sequence']), challenge['challenge_id'],
        consent=True)
    assert replay.status_code == 400


def test_failed_enrolment_still_consumes_the_challenge(face_client, db, face_user):
    """A burnt challenge cannot be retried after a failure."""
    challenge = face_client.post('/api/face/challenge').get_json()
    bad = fx.build_frames(ME, fx.static_yaws(16))
    first = post_frames(face_client, '/api/face/enroll', bad,
                        challenge['challenge_id'], consent=True)
    assert first.status_code == 400
    second = post_frames(
        face_client, '/api/face/enroll',
        fx.compliant_frames(ME, challenge['sequence']), challenge['challenge_id'],
        consent=True)
    assert second.status_code == 400
    assert FaceEnrollment.query.count() == 0


def test_attempt_count_is_recorded(face_client, db, face_user):
    challenge = face_client.post('/api/face/challenge').get_json()
    post_frames(face_client, '/api/face/enroll',
                fx.build_frames(ME, fx.static_yaws(16)),
                challenge['challenge_id'], consent=True)
    row = FaceChallenge.query.filter_by(
        challenge_id=challenge['challenge_id']).one()
    assert row.attempt_count == 1
    assert row.completed is True


def test_enrolment_can_be_redone_by_the_same_user(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    first = bytes(FaceEnrollment.query.filter_by(user_id=face_user.id).one()
                  .encrypted_embedding)
    assert _enrol(face_client)[0].status_code == 200
    assert FaceEnrollment.query.count() == 1
    second = bytes(FaceEnrollment.query.filter_by(user_id=face_user.id).one()
                   .encrypted_embedding)
    assert first != second, 'a fresh template must be produced'


# ===========================================================================
# Verification
# ===========================================================================

def test_genuine_verification_succeeds(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.compliant_frames(ME, challenge['sequence'], repeats=4)
    response = post_frames(face_client, '/api/face/verify', frames,
                           challenge['challenge_id'])
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['verified'] is True


def test_impostor_is_rejected(face_client, db, face_user):
    assert _enrol(face_client, identity=ME)[0].status_code == 200
    for impostor in fx.FIXTURE_IDENTITIES:
        if impostor == ME:
            continue
        challenge = face_client.post('/api/face/challenge').get_json()
        frames = fx.compliant_frames(impostor, challenge['sequence'], repeats=4)
        response = post_frames(face_client, '/api/face/verify', frames,
                               challenge['challenge_id'])
        assert response.status_code == 400, impostor


def test_verification_without_enrolment_is_rejected(face_client, db, face_user):
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.compliant_frames(ME, challenge['sequence'], repeats=4)
    response = post_frames(face_client, '/api/face/verify', frames,
                           challenge['challenge_id'])
    assert response.status_code == 400


def test_static_photo_pose_cannot_verify(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.build_frames(ME, fx.static_yaws(16)),
                           challenge['challenge_id'])
    assert response.status_code == 400


def test_wrong_movement_order_cannot_verify(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(
        face_client, '/api/face/verify',
        fx.build_frames(ME, fx.reversed_yaws(challenge['sequence'], repeats=4)),
        challenge['challenge_id'])
    assert response.status_code == 400


def test_verification_is_single_use(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.compliant_frames(ME, challenge['sequence'], repeats=4)
    assert post_frames(face_client, '/api/face/verify', frames,
                       challenge['challenge_id']).status_code == 200
    assert post_frames(face_client, '/api/face/verify', frames,
                       challenge['challenge_id']).status_code == 400


def test_failure_responses_leak_no_biometric_detail(face_client, db, face_user):
    """Every rejection shares one generic body."""
    assert _enrol(face_client)[0].status_code == 200
    bodies = set()
    for build in (
        lambda seq: fx.compliant_frames(OTHER),
        lambda seq: fx.build_frames(ME, fx.static_yaws(16)),
        lambda seq: fx.build_frames(OTHER, fx.static_yaws(16)),
    ):
        challenge = face_client.post('/api/face/challenge').get_json()
        response = post_frames(face_client, '/api/face/verify',
                               build(challenge['sequence']),
                               challenge['challenge_id'])
        assert response.status_code == 400
        bodies.add(response.get_data(as_text=True))
    assert len(bodies) == 1, bodies


def test_successful_response_leaks_no_scores(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    body = response.get_data(as_text=True).lower()
    for forbidden in ('similarity', 'score', 'distance', 'embedding', 'yaw',
                      '0.9', 'threshold', 'pose'):
        assert forbidden not in body, forbidden


# ===========================================================================
# Threshold and key fail-closed behaviour
# ===========================================================================

def test_verification_refuses_to_run_without_a_threshold(face_client, db, face_user,
                                                         app):
    assert _enrol(face_client)[0].status_code == 200
    app.config['FACE_SIMILARITY_THRESHOLD'] = None
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    assert response.status_code == 503


@pytest.mark.parametrize('bad', [0.0, 1.0, -0.5, 2.5])
def test_verification_refuses_an_out_of_range_threshold(face_client, db, face_user,
                                                        app, bad):
    assert _enrol(face_client)[0].status_code == 200
    app.config['FACE_SIMILARITY_THRESHOLD'] = bad
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    assert response.status_code == 503


def test_enrolment_refuses_to_store_without_a_key(face_client, db, face_user,
                                                   monkeypatch):
    monkeypatch.delenv('FACE_ENCRYPTION_KEY', raising=False)
    monkeypatch.delenv('FACE_ENCRYPTION_KEYS', raising=False)
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/enroll',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 503
    assert FaceEnrollment.query.count() == 0


def test_verification_refuses_when_the_template_cannot_be_decrypted(
        face_client, db, face_user, monkeypatch):
    assert _enrol(face_client)[0].status_code == 200
    monkeypatch.setenv('FACE_ENCRYPTION_KEY', Fernet.generate_key().decode())
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    assert response.status_code == 503


def test_verification_refuses_a_tampered_template(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    row = FaceEnrollment.query.filter_by(user_id=face_user.id).one()
    blob = bytearray(bytes(row.encrypted_embedding))
    blob[-5] ^= 0xFF
    row.encrypted_embedding = bytes(blob)
    db.session.commit()
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    assert response.status_code == 503


def test_engine_unavailable_is_reported_as_such(face_client, db, face_user,
                                               monkeypatch):
    """Missing/failed weights must be 503, never a biometric rejection."""
    from app.services import face_engine as engine_module
    from app.services import face_service

    assert _enrol(face_client)[0].status_code == 200

    def boom():
        raise engine_module.FaceEngineUnavailable('weights are gone')

    monkeypatch.setattr(face_service, 'get_engine', boom)
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    assert response.status_code == 503


def test_engine_unavailable_blocks_enrolment(face_client, db, face_user,
                                            monkeypatch):
    """A dead engine must not leave a half-written enrolment behind."""
    from app.services import face_engine as engine_module
    from app.services import face_service

    def boom():
        raise engine_module.FaceEngineUnavailable('weights are gone')

    monkeypatch.setattr(face_service, 'get_engine', boom)
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/enroll',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 503
    assert FaceEnrollment.query.count() == 0


# ===========================================================================
# Consent lifecycle
# ===========================================================================

def test_status_reports_the_callers_own_state(face_client, db, face_user):
    before = face_client.get('/api/face/status').get_json()
    assert before == {'enrolled': False, 'consent_given': False,
                      'consent_purpose': None}
    assert _enrol(face_client)[0].status_code == 200
    after = face_client.get('/api/face/status').get_json()
    assert after['enrolled'] is True
    assert after['consent_given'] is True
    assert after['consent_purpose']


def test_withdrawal_deletes_the_template(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    row = FaceEnrollment.query.filter_by(user_id=face_user.id).one()
    assert bytes(row.encrypted_embedding)

    response = face_client.post('/api/face/withdraw-consent')
    assert response.status_code == 200
    db.session.expire_all()
    row = FaceEnrollment.query.filter_by(user_id=face_user.id).one()
    assert row.consent_given is False
    assert row.is_enrolled is False
    assert row.withdrawn_at is not None
    assert row.template_deleted_at is not None
    assert bytes(row.encrypted_embedding) == b''


def test_verification_fails_after_withdrawal(face_client, db, face_user):
    assert _enrol(face_client)[0].status_code == 200
    assert face_client.post('/api/face/withdraw-consent').status_code == 200
    challenge = face_client.post('/api/face/challenge').get_json()
    response = post_frames(face_client, '/api/face/verify',
                           fx.compliant_frames(ME, challenge['sequence'], repeats=4),
                           challenge['challenge_id'])
    assert response.status_code == 400


def test_withdrawal_without_an_enrolment_is_reported(face_client):
    assert face_client.post('/api/face/withdraw-consent').status_code == 400


# ===========================================================================
# Rate limiting and upload bounds
# ===========================================================================

def test_rate_limits_actually_engage(app, db, face_client):
    """The shipped budgets must bite; the suite relaxes them elsewhere."""
    from app.security.rate_limit import InMemoryRateLimiter
    app.config['FACE_RATE_LIMIT_CHALLENGE'] = (3, 60)
    app.config['FACE_RATE_LIMIT_ENROLL'] = (2, 300)
    app.config['FACE_RATE_LIMIT_VERIFY'] = (2, 300)
    app.extensions['rate_limiter'] = InMemoryRateLimiter()

    codes = [face_client.post('/api/face/challenge').status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]


def test_oversized_upload_is_refused(app, db, face_client):
    app.config['FACE_MAX_UPLOAD_BYTES'] = 2048
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.compliant_frames(ME, challenge['sequence'], repeats=4)
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400


def test_oversized_single_frame_is_refused(app, db, face_client):
    app.config['FACE_MAX_FRAME_BYTES'] = 512
    challenge = face_client.post('/api/face/challenge').get_json()
    frames = fx.compliant_frames(ME, challenge['sequence'], repeats=4)
    response = post_frames(face_client, '/api/face/enroll', frames,
                           challenge['challenge_id'], consent=True)
    assert response.status_code == 400


def test_empty_upload_is_refused(face_client):
    response = post_frames(face_client, '/api/face/enroll', [], 'x' * 64, consent=True)
    assert response.status_code == 400
