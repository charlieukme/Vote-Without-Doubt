"""
Unit and API Tests for Ballot Status, Finalization Integrity, and Safe Retry Workflow
Vote Without Doubt
"""

import pytest
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app import create_app
from app.extensions import db
from app.models import User, Election, BallotRecord, AuthSession
from app.models.roll import ElectoralRoll
from app.security.pseudonym import derive_pseudonym
from app.security.sessions import generate_session_id


@pytest.fixture
def app_instance(tmp_path):
    temp_db = str(tmp_path / "test_status.db")
    orig_db_url = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = f'sqlite:///{temp_db}'

    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{temp_db}'
    app.config['AUTO_CREATE_SCHEMA'] = True
    app.config['REVOTE_COOLDOWN_SECONDS'] = 120
    app.config['MAX_BALLOTS_PER_VOTER'] = 3

    with app.app_context():
        db.create_all()
        # Seed user and electoral roll
        user = User(
            id=101,
            username='testvoter',
            email='voter@test.local',
            password_hash='argon2id_mock_hash',
            voter_id='1EW23CS999',
            is_active=True,
        )
        db.session.add(user)

        roll = ElectoralRoll(
            usn='1EW23CS999',
            full_name='Test Voter',
            college_email='voter@test.local',
            is_eligible=True,
        )
        db.session.add(roll)

        election = Election(
            id=99,
            election_id='ELEC_TEST_STATUS',
            title='Test Status Election',
            status='OPEN',
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=1),
            candidate_count=2,
        )
        db.session.add(election)

        sid = generate_session_id()
        sess = AuthSession(
            session_id=sid,
            user_id=101,
            auth_state='AUTHORIZED',
            expires_at=datetime.utcnow() + timedelta(hours=1),
            idle_expires_at=datetime.utcnow() + timedelta(minutes=15),
            last_activity=datetime.utcnow(),
            revoked=False,
        )
        db.session.add(sess)
        db.session.commit()

        yield app

        db.session.remove()

    if orig_db_url is not None:
        os.environ['DATABASE_URL'] = orig_db_url
    else:
        os.environ.pop('DATABASE_URL', None)


@pytest.fixture
def auth_client(app_instance):
    client = app_instance.test_client()
    with app_instance.app_context():
        sess = AuthSession.query.filter_by(user_id=101).first()
        with client.session_transaction() as flask_sess:
            flask_sess['session_id'] = sess.session_id
    return client


def _create_ballot(app_instance, state='FAILED', **kwargs):
    with app_instance.app_context():
        p = derive_pseudonym(101, 99)
        defaults = {
            'election_id': 99,
            'pseudonym': p,
            'sequence': 1,
            'state': state,
            'candidate': 1,
            'error': None if state != 'FAILED' else 'NO_CONTRACT_ADDRESS',
            'tx_hash': None,
            'tx_broadcast_at': None,
            'tx_confirmed_at': None,
            'tx_failed_at': datetime.utcnow() if state == 'FAILED' else None,
            'created_at': datetime.utcnow() - timedelta(minutes=5),
        }
        defaults.update(kwargs)
        b = BallotRecord(**defaults)
        db.session.add(b)
        db.session.commit()
        return b.id


def test_1_failed_ballot_no_tx_broadcast(auth_client, app_instance):
    """1. Failed ballot with no transaction broadcast: retry_allowed must be True."""
    _create_ballot(app_instance, state='FAILED', tx_hash=None, tx_broadcast_at=None, tx_confirmed_at=None)

    with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract') as mock_relayer:
        mock_relayer.return_value = (MagicMock(), None, None)
        res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
        assert res.status_code == 200
        data = res.get_json()
        assert data['status'] == 'FAILED'
        assert data['finalized'] is False
        assert data['retry_allowed'] is True
        assert data['retry_blocked_reason'] is None
        assert data['ballot_count'] == 0


def test_2_failed_ballot_with_tx_hash(auth_client, app_instance):
    """2. Failed ballot with a transaction hash: retry_allowed must be False."""
    _create_ballot(
        app_instance,
        state='FAILED',
        tx_hash='0x1234567890abcdef',
        tx_broadcast_at=datetime.utcnow(),
    )

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'FAILED'
    assert data['finalized'] is False
    assert data['retry_allowed'] is False
    assert data['retry_blocked_reason'] == 'TRANSACTION_IN_FLIGHT_OR_UNCERTAIN'


def test_3_queued_ballot(auth_client, app_instance):
    """3. Queued ballot: retry_allowed=False, finalized=False, can_revote=False."""
    _create_ballot(app_instance, state='QUEUED')

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'QUEUED'
    assert data['finalized'] is False
    assert data['retry_allowed'] is False
    assert data['can_revote'] is False


def test_4_submitted_unconfirmed_ballot(auth_client, app_instance):
    """4. Submitted but unconfirmed ballot: retry_allowed=False, finalized=False."""
    _create_ballot(
        app_instance,
        state='SUBMITTED',
        tx_hash='0xabc123',
        tx_broadcast_at=datetime.utcnow(),
    )

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'SUBMITTED'
    assert data['finalized'] is False
    assert data['retry_allowed'] is False
    assert data['can_revote'] is False


def test_5_confirmed_ballot(auth_client, app_instance):
    """5. Confirmed ballot: state='CONFIRMED', can_revote=True after cooldown."""
    _create_ballot(
        app_instance,
        state='CONFIRMED',
        tx_hash='0xabc123',
        created_at=datetime.utcnow() - timedelta(seconds=200),
    )

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'CONFIRMED'
    assert data['can_revote'] is True
    assert data['retry_allowed'] is False


def test_6_finalized_ballot(auth_client, app_instance):
    """6. Finalized ballot: finalized=True, retry_allowed=False."""
    _create_ballot(
        app_instance,
        state='FINALIZED',
        tx_confirmed_at=datetime.utcnow(),
    )

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'FINALIZED'
    assert data['finalized'] is True
    assert data['retry_allowed'] is False


def test_7_cooldown_active(auth_client, app_instance):
    """7. Cooldown active: elapsed < 120s -> cooldown_active=True, can_revote=False."""
    _create_ballot(
        app_instance,
        state='FINALIZED',
        created_at=datetime.utcnow() - timedelta(seconds=30),
    )

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['cooldown_active'] is True
    assert data['cooldown_remaining_sec'] > 0
    assert data['can_revote'] is False


def test_8_cooldown_expired(auth_client, app_instance):
    """8. Cooldown expired: elapsed >= 120s -> cooldown_active=False, can_revote=True."""
    _create_ballot(
        app_instance,
        state='FINALIZED',
        created_at=datetime.utcnow() - timedelta(seconds=130),
    )

    res = auth_client.get('/api/voting/status?election_id=ELEC_TEST_STATUS')
    assert res.status_code == 200
    data = res.get_json()
    assert data['cooldown_active'] is False
    assert data['cooldown_remaining_sec'] == 0
    assert data['can_revote'] is True


def test_9_retry_reconciliation_workflow(app_instance):
    """9. Retry after a safely retryable failure supersedes prior failed ballot."""
    bid = _create_ballot(
        app_instance,
        state='FAILED',
        sequence=1,
        tx_hash=None,
        tx_broadcast_at=None,
        tx_confirmed_at=None,
    )

    with app_instance.app_context():
        from app.services.voting_service import VotingService
        from app.models import VotingAuthorization

        # Seed authorization
        auth = VotingAuthorization(
            user_id=101,
            election_id=99,
            session_id='test_sess_token',
            wallet_verified=True,
            face_verified=True,
            authorized=True,
            consumed=False,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.session.add(auth)
        db.session.commit()

        with patch('app.services.reconciliation_service.ReconciliationService.get_relayer_and_contract') as mock_rel:
            mock_rel.return_value = (MagicMock(), None, None)
            new_ballot, err = VotingService.submit_ballot(
                user_id=101,
                election_id=99,
                candidate=1,
                session_id='test_sess_token',
            )

        assert err in ('', None, 'OK')
        assert new_ballot is not None
        assert new_ballot.sequence == 1
        assert new_ballot.state == 'QUEUED'

        # Prior failed ballot must now be superseded with sequence 0
        b = db.session.get(BallotRecord, bid)
        assert b.superseded is True
        assert b.sequence == 0
