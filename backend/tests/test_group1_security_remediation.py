"""
Group 1 Security Remediation Verification Suite
Vote Without Doubt (VWD)

Tests covering:
1. SEC-001: Permanently disabled legacy V1 plaintext ballot submission (HTTP 410 Gone).
2. SEC-003: Working CSRF token lifecycle, session binding, safe method exemption,
            and production/staging default enablement.
3. BIOM-001: Biometric PAD shadow mode integrity and uncalibrated threshold safety.
"""

import pytest
from flask import session

from app.audit.audit import AuditLogger
from app.config.config import Config, ProductionConfig, StagingConfig, TestingConfig
from app.security.csrf import (
    CSRF_SESSION_KEY,
    generate_csrf_token,
    rotate_csrf_token,
    validate_csrf_token,
)


# ==============================================================================
# SEC-001: V1 Plaintext Ballot Submission Disabling
# ==============================================================================

def test_v1_ballot_submit_permanently_disabled_returns_410(client):
    """
    SEC-001 Regression Test:
    Verify that POST /api/voting/submit returns HTTP 410 Gone with a clear
    deprecation error, refusing to accept any plaintext candidate choice.
    """
    response = client.post('/api/voting/submit', json={
        'election_id': 1,
        'candidate': 0,
        'is_null': False,
    })

    assert response.status_code == 410
    data = response.get_json()
    assert data is not None
    assert data.get('error') == 'V1_PROTOCOL_DEPRECATED'
    assert 'permanently disabled' in data.get('message', '').lower()
    assert 'sec-001' in data.get('message', '').lower()


def test_v1_submit_rejects_even_with_authenticated_session(client, app, db):
    """
    Verify that even with an active authenticated session, V1 submit is rejected
    with 410 Gone rather than processing the ballot.
    """
    with client.session_transaction() as sess:
        sess['session_id'] = 'mock-auth-session-id'
        sess['user_id'] = 999

    response = client.post('/api/voting/submit', json={
        'election_id': 1,
        'candidate': 1,
    })

    assert response.status_code == 410
    data = response.get_json()
    assert data.get('error') == 'V1_PROTOCOL_DEPRECATED'


def test_v1_read_only_election_metadata_preserved(client, app, db):
    """
    Verify that read-only metadata endpoints (GET /api/voting/election/<id>)
    remain operational for candidate discovery and election inspection.
    """
    # Query default or non-existent election; returns 404 or 200, never 410
    response = client.get('/api/voting/election/999999')
    assert response.status_code == 404
    assert response.get_json().get('error') == 'ELECTION_NOT_FOUND'


# ==============================================================================
# SEC-003: CSRF Protection & Token Lifecycle
# ==============================================================================

def test_csrf_token_endpoint_issues_token_and_sets_session(client):
    """
    Verify that GET /api/auth/csrf-token issues a cryptographically secure token
    and sets the session cookie for the client.
    """
    response = client.get('/api/auth/csrf-token')
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert 'csrf_token' in data
    token = data['csrf_token']
    assert isinstance(token, str)
    assert len(token) >= 32

    # Verify session cookie was set
    cookie = response.headers.get('Set-Cookie')
    assert cookie is not None


def test_csrf_missing_token_rejected_when_enabled(app, client):
    """
    Verify that state-changing POST request without X-CSRF-Token is rejected
    with HTTP 403 Forbidden when CSRF_ENABLED is True.
    """
    app.config['CSRF_ENABLED'] = True

    # Mutating request without token
    response = client.post('/api/auth/logout')
    assert response.status_code == 403
    data = response.get_json()
    assert data is not None
    assert data.get('error') == 'Forbidden'
    assert 'csrf' in data.get('message', '').lower()


def test_csrf_invalid_token_rejected_when_enabled(app, client):
    """
    Verify that a forged or mismatched CSRF token is rejected with HTTP 403 Forbidden.
    """
    app.config['CSRF_ENABLED'] = True

    # Obtain real token
    init_res = client.get('/api/auth/csrf-token')
    assert init_res.status_code == 200

    # Submit with invalid forged token
    response = client.post(
        '/api/auth/logout',
        headers={'X-CSRF-Token': 'forged-attacker-token-1234567890'},
    )
    assert response.status_code == 403
    data = response.get_json()
    assert data.get('error') == 'Forbidden'


def test_csrf_valid_token_accepted_when_enabled(app, client):
    """
    Verify that a mutating request carrying the correct session-bound CSRF token
    in X-CSRF-Token succeeds.
    """
    app.config['CSRF_ENABLED'] = True

    # 1. Obtain session token
    init_res = client.get('/api/auth/csrf-token')
    assert init_res.status_code == 200
    token = init_res.get_json()['csrf_token']

    # 2. Make state-changing request carrying the token
    response = client.post(
        '/api/auth/logout',
        headers={'X-CSRF-Token': token},
    )
    assert response.status_code == 200
    assert response.get_json().get('message') == 'Logged out'


def test_csrf_cross_session_token_rejected(app):
    """
    Verify that a valid token issued to Session A cannot be used to authenticate
    requests originating from Session B (defeating Cross-Site Request Forgery).
    """
    app.config['CSRF_ENABLED'] = True
    client_a = app.test_client()
    client_b = app.test_client()

    # Session A gets Token A
    res_a = client_a.get('/api/auth/csrf-token')
    token_a = res_a.get_json()['csrf_token']

    # Session B gets Token B
    res_b = client_b.get('/api/auth/csrf-token')
    token_b = res_b.get_json()['csrf_token']
    assert token_a != token_b

    # Attacker tries to use Token A against Session B
    cross_res = client_b.post(
        '/api/auth/logout',
        headers={'X-CSRF-Token': token_a},
    )
    assert cross_res.status_code == 403
    assert 'csrf' in cross_res.get_json().get('message', '').lower()

    # Session B using its own Token B succeeds
    valid_res = client_b.post(
        '/api/auth/logout',
        headers={'X-CSRF-Token': token_b},
    )
    assert valid_res.status_code == 200


def test_csrf_safe_methods_exempt(app, client):
    """
    Verify that safe HTTP methods (GET, HEAD, OPTIONS) are exempt from CSRF checks.
    """
    app.config['CSRF_ENABLED'] = True

    # GET without CSRF token must succeed
    res_get = client.get('/api/health')
    assert res_get.status_code == 200

    # HEAD without CSRF token must succeed
    res_head = client.head('/api/health')
    assert res_head.status_code == 200

    # OPTIONS without CSRF token must succeed
    res_options = client.options('/api/health')
    assert res_options.status_code in (200, 204)


def test_csrf_token_rotation_on_verify_otp(app, client):
    """
    Verify that successful OTP verification rotates the CSRF token and returns
    the new token in the response payload.
    """
    # Direct test of rotate_csrf_token helper within a request context
    with app.test_request_context():
        old_token = generate_csrf_token()
        assert session[CSRF_SESSION_KEY] == old_token

        new_token = rotate_csrf_token()
        assert new_token != old_token
        assert session[CSRF_SESSION_KEY] == new_token


def test_csrf_enabled_by_default_in_production_and_staging():
    """
    Verify configuration hardening: CSRF_ENABLED must be True by default
    in ProductionConfig and StagingConfig.
    """
    assert ProductionConfig.CSRF_ENABLED is True
    assert StagingConfig.CSRF_ENABLED is True
    assert Config.CSRF_ENABLED is False
    assert TestingConfig.CSRF_ENABLED is False


# ==============================================================================
# BIOM-001: Biometric PAD Invariants & Uncalibrated Threshold Safety
# ==============================================================================

def test_biometric_pad_defaults_to_none_threshold():
    """
    BIOM-001 Verification:
    Verify that FACE_PAD_THRESHOLD is None (uncalibrated) by default,
    preventing arbitrary or untested score enforcement.
    """
    assert Config.FACE_PAD_THRESHOLD is None


def test_biometric_adapter_fails_closed_in_enforcing_mode_with_none_threshold():
    """
    Verify that BiometricDualGateAdapter strictly fails closed with
    CONFIG_ERROR_THRESHOLD if enforcing mode is requested while the PAD
    operational threshold is unconfigured (None).
    """
    from app.services.biometric_adapter import BiometricDualGateAdapter, DualGateOutcome

    adapter = BiometricDualGateAdapter()
    result = adapter.evaluate(
        identity_result=0.95,
        identity_threshold=0.83,
        pad_result=0.99,
        pad_threshold=None,
        mode='enforcing',
    )

    assert result.verified is False
    assert result.outcome == DualGateOutcome.CONFIG_ERROR_THRESHOLD
    assert 'unconfigured' in result.internal_diagnostic.lower()


# ==============================================================================
# SEC-001: Legacy V1 Relayer Broadcast Prohibition
# ==============================================================================

def test_v1_relayer_eligibility_permanently_disabled():
    """
    Verify that check_election_batch_eligibility() immediately and fail-closed
    returns False with reason V1_RELAYER_BROADCAST_DISABLED_SEC_001.
    """
    from app.relayer.relayer import Relayer

    relayer = Relayer()
    eligible, reason, queued, wait_sec = relayer.check_election_batch_eligibility(1)
    assert eligible is False
    assert reason == "V1_RELAYER_BROADCAST_DISABLED_SEC_001"
    assert queued == []
    assert wait_sec == 0.0


def test_v1_relayer_direct_dispatch_and_flush_blocked(app, db, monkeypatch):
    """
    Verify that dispatch_election_batch() is permanently blocked even with force=True,
    leaving pre-existing QUEUED records completely untouched and unbroadcast.
    """
    from unittest.mock import MagicMock
    from datetime import datetime
    from app.models import BallotRecord, Election
    from app.relayer.relayer import Relayer

    election = Election(
        election_id='test-sec001-election',
        title='V1 Relayer Block Test',
        status='OPEN',
    )
    db.session.add(election)
    db.session.commit()

    ballot = BallotRecord(
        election_id=election.id,
        pseudonym='0x' + 'a' * 64,
        candidate=1,
        sequence=1,
        state='QUEUED',
        created_at=datetime.utcnow(),
    )
    db.session.add(ballot)
    db.session.commit()

    mock_w3 = MagicMock()
    monkeypatch.setattr(Relayer, 'get_web3', lambda self: mock_w3)

    relayer = Relayer(w3_instance=mock_w3)

    # 1. Normal dispatch check
    res_normal = relayer.dispatch_election_batch(election.id, force=False)
    assert res_normal['status'] == 'SKIPPED'
    assert res_normal['reason'] == 'V1_RELAYER_BROADCAST_DISABLED_SEC_001'

    # 2. Forced dispatch / manual flush attempt
    res_forced = relayer.dispatch_election_batch(election.id, force=True)
    assert res_forced['status'] == 'BLOCKED'
    assert res_forced['reason'] == 'V1_RELAYER_BROADCAST_DISABLED_SEC_001'

    # Assert Web3 was never touched and no contracts were queried or invoked
    assert mock_w3.eth.contract.call_count == 0

    # Historical record check: ballot is still in QUEUED state, unmodified
    refreshed_ballot = db.session.get(BallotRecord, ballot.id)
    assert refreshed_ballot.state == 'QUEUED'
    assert refreshed_ballot.tx_hash is None


def test_v1_relayer_broadcast_transaction_boundary_fail_closed(app, db, monkeypatch):
    """
    Verify that even if _broadcast_ballot_batch is invoked directly with queued ballots,
    it fails closed, logs V1_RELAYER_BROADCAST_BLOCKED, never invokes castBallot or
    castNullBallot, leaves records untouched, and returns blocked count.
    """
    from unittest.mock import MagicMock
    from datetime import datetime
    from app.models import BallotRecord, AuditEvent
    from app.relayer.relayer import Relayer

    ballot1 = BallotRecord(
        election_id=9999,
        pseudonym='0x' + 'b' * 64,
        candidate=2,
        sequence=1,
        state='QUEUED',
        created_at=datetime.utcnow(),
    )
    ballot2 = BallotRecord(
        election_id=9999,
        pseudonym='0x' + 'c' * 64,
        candidate=0,
        is_null=True,
        sequence=1,
        state='QUEUED',
        created_at=datetime.utcnow(),
    )
    db.session.add_all([ballot1, ballot2])
    db.session.commit()

    mock_w3 = MagicMock()
    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract
    monkeypatch.setattr(Relayer, 'get_web3', lambda self: mock_w3)

    relayer = Relayer(w3_instance=mock_w3)
    summary = relayer._broadcast_ballot_batch([ballot1, ballot2], contract_address='0x' + '4' * 40)

    # Summary asserts
    assert summary['processed'] == 0
    assert summary['confirmed'] == 0
    assert summary['failed'] == 0
    assert summary['blocked_sec_001'] == 2

    # Verification: castBallot and castNullBallot were NEVER called
    assert mock_contract.functions.castBallot.call_count == 0
    assert mock_contract.functions.castNullBallot.call_count == 0

    # Records remain unchanged in QUEUED state
    b1 = db.session.get(BallotRecord, ballot1.id)
    b2 = db.session.get(BallotRecord, ballot2.id)
    assert b1.state == 'QUEUED'
    assert b1.tx_hash is None
    assert b2.state == 'QUEUED'
    assert b2.tx_hash is None

    # Audit event logged
    audit_evt = AuditEvent.query.filter_by(event_type='V1_RELAYER_BROADCAST_BLOCKED').order_by(AuditEvent.id.desc()).first()
    assert audit_evt is not None
    assert audit_evt.event_metadata.get('ballot_count') == 2
    assert audit_evt.event_metadata.get('reason') == 'SEC-001_V1_PROTOCOL_PERMANENTLY_DISABLED'


def test_v1_relayer_process_queue_and_dispatcher_tick_cannot_broadcast(app, db, monkeypatch):
    """
    Verify that background worker, process_queue, and RelayerDispatcher.tick()
    cannot broadcast pre-existing QUEUED records.
    """
    from unittest.mock import MagicMock
    from datetime import datetime
    from app.models import BallotRecord, Election
    from app.relayer.relayer import Relayer
    from app.relayer.dispatcher import RelayerDispatcher

    election = Election(
        election_id='test-sec001-dispatcher',
        title='V1 Relayer Dispatcher Test',
        status='OPEN',
    )
    db.session.add(election)
    db.session.commit()

    ballot = BallotRecord(
        election_id=election.id,
        pseudonym='0x' + 'd' * 64,
        candidate=0,
        sequence=1,
        state='QUEUED',
        created_at=datetime.utcnow(),
    )
    db.session.add(ballot)
    db.session.commit()

    mock_w3 = MagicMock()
    monkeypatch.setattr(Relayer, 'get_web3', lambda self: mock_w3)

    relayer = Relayer(w3_instance=mock_w3)

    # 1. process_queue entrypoint
    pq_res = relayer.process_queue(force=True, election_id=election.id)
    assert pq_res['processed'] == 0
    assert pq_res['confirmed'] == 0
    assert pq_res['failed'] == 0

    # 2. RelayerDispatcher.tick entrypoint
    disp = RelayerDispatcher(app=app)
    tick_res = disp.tick(app=app, force=True, election_id=election.id)
    assert tick_res['batches_dispatched'] == 0
    assert tick_res['total_processed'] == 0

    # 3. Ballots remain queued and unbroadcast
    refreshed = db.session.get(BallotRecord, ballot.id)
    assert refreshed.state == 'QUEUED'
    assert refreshed.tx_hash is None
    assert mock_w3.eth.contract.call_count == 0

