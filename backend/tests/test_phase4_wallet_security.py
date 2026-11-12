"""Phase 4 wallet integration and security tests.

Drives the REAL backend verification path (real Flask app, real database, real
WalletService, real Ethereum signature recovery) with a deterministic TEST-ONLY
key. ``verify_signature`` is never mocked.

TEST-ONLY key: it controls nothing, holds no funds, and is not a personal wallet.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    Ballot,
    BallotQueue,
    User,
    WalletBinding,
    WalletChallenge,
)
from app.security.wallet import (
    MAX_SIGNATURE_ATTEMPTS,
    WALLET_AUTH_PURPOSE,
    create_auth_message,
)
from tests.conftest import PHASE2_PASSWORD, PHASE2_USERNAME

#: TEST-ONLY deterministic key for the suite. No funds, no real wallet.
TEST_ONLY_PRIVATE_KEY = '0x' + '44' * 32
TEST_ACCOUNT = Account.from_key(TEST_ONLY_PRIVATE_KEY)
OTHER_KEY = '0x' + '55' * 32
OTHER_ACCOUNT = Account.from_key(OTHER_KEY)


def sign(message: str, key: str = TEST_ONLY_PRIVATE_KEY) -> str:
    """A real personal_sign-compatible signature over ``message``."""
    return Account.sign_message(
        encode_defunct(text=message), private_key=key).signature.hex()


@pytest.fixture
def wallet_client(app, db, email_service, auth_api, phase2_user):
    """An AUTHORIZED Phase 2 session, which wallet endpoints require."""
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})
    assert auth_api.get('/api/auth/session').status_code == 200
    return auth_api


def issue(client):
    response = client.post('/api/wallet/challenge')
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def bind(client, nonce, signature, address, chain_id=1337, extra=None):
    payload = {'nonce': nonce, 'signature': signature,
               'wallet_address': address, 'chain_id': chain_id}
    if extra:
        payload.update(extra)
    return client.post('/api/wallet/bind', json=payload)


# ------------------------------------------------------- authorization

def test_wallet_endpoints_require_authentication(app, db):
    client = app.test_client()
    assert client.post('/api/wallet/challenge').status_code == 401
    assert client.post('/api/wallet/bind', json={}).status_code == 401


def test_challenge_requires_authorized_session(app, db, auth_api, phase2_user,
                                               email_service):
    """A PENDING_FACTORS session is not enough."""
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    assert auth_api.post('/api/wallet/challenge').status_code == 401


# ------------------------------------------------------------- happy path

def test_real_signature_binds_the_wallet(wallet_client, db):
    challenge = issue(wallet_client)
    assert len(challenge['nonce']) == 64
    assert challenge['purpose'] == WALLET_AUTH_PURPOSE
    assert challenge['chain_id'] == 1337

    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    TEST_ACCOUNT.address)
    assert response.status_code == 200
    assert response.get_json()['message'] == 'Wallet bound successfully'

    binding = WalletBinding.query.one()
    assert binding.wallet_address == TEST_ACCOUNT.address.lower()
    assert binding.is_verified is True
    assert binding.binding_method == 'personal_sign'
    assert wallet_client.get('/api/wallet/status').get_json()['bound'] is True


def test_challenge_is_fully_bound_to_server_side_state(wallet_client, db):
    challenge = issue(wallet_client)
    record = WalletChallenge.query.one()
    assert record.session_id is not None
    assert record.purpose == WALLET_AUTH_PURPOSE
    assert record.election_id == challenge['election_id']
    assert record.chain_id == challenge['chain_id']
    assert record.message == challenge['message']
    assert record.nonce == challenge['nonce']
    assert record.attempts == 0


def test_message_contains_all_required_context(wallet_client, db):
    message = issue(wallet_client)['message']
    for field in ('Domain:', 'Purpose:', 'UserID:', 'ElectionID:', 'ChainId:',
                  'Contract:', 'Nonce:', 'IssuedAt:', 'ExpiresAt:'):
        assert field in message
    assert 'candidate' not in message.lower()
    assert 'ballot' not in message.lower()
    assert 'Do NOT sign this to vote' in message


# ---------------------------------------------------------- negative cases

def test_wrong_wallet_signature_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    OTHER_ACCOUNT.address)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid signature'
    assert WalletBinding.query.count() == 0


def test_modified_message_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    tampered = challenge['message'].replace('ElectionID: GENERAL',
                                            'ElectionID: GENERAL-OTHER')
    response = bind(wallet_client, challenge['nonce'], sign(tampered),
                    TEST_ACCOUNT.address)
    assert response.status_code == 400
    assert WalletBinding.query.count() == 0


def test_modified_election_context_is_rejected(wallet_client, db, monkeypatch):
    """H1: a signature made for Election A must not authenticate under Election B."""
    config = wallet_client.application.config
    monkeypatch.setitem(config, 'WALLET_AUTH_ELECTION_ID', 'ELECTION-A')

    under_a = issue(wallet_client)
    assert 'ElectionID: ELECTION-A' in under_a['message']
    signature_for_a = sign(under_a['message'])

    monkeypatch.setitem(config, 'WALLET_AUTH_ELECTION_ID', 'ELECTION-B')
    under_b = issue(wallet_client)
    assert 'ElectionID: ELECTION-B' in under_b['message']

    # The Election-A signature presented against the Election-B nonce must fail,
    # because the stored message the server verifies is the Election-B one.
    response = bind(wallet_client, under_b['nonce'], signature_for_a, TEST_ACCOUNT.address)
    assert response.status_code == 400
    assert WalletBinding.query.count() == 0

    # And the Election-A signature still works for its own nonce.
    assert bind(wallet_client, under_a['nonce'], signature_for_a,
                TEST_ACCOUNT.address).status_code == 200


def test_modified_chain_context_is_rejected(wallet_client, db, monkeypatch):
    """H3/W: a signature bound to one chain cannot bind under another."""
    challenge = issue(wallet_client)
    signature = sign(challenge['message'])
    monkeypatch.setitem(wallet_client.application.config, 'WALLET_AUTH_CHAIN_ID', 1)
    second = issue(wallet_client)
    assert second['chain_id'] == 1
    stale = bind(wallet_client, second['nonce'], signature, TEST_ACCOUNT.address)
    assert stale.status_code == 400
    assert WalletBinding.query.count() == 0


def test_modified_contract_context_is_rejected(wallet_client, db, monkeypatch):
    """H2: a signature bound to one contract context cannot bind under another."""
    challenge = issue(wallet_client)
    signature = sign(challenge['message'])
    monkeypatch.setitem(wallet_client.application.config, 'WALLET_AUTH_CONTRACT_ADDRESS',
                        '0x1111111111111111111111111111111111111111')
    second = issue(wallet_client)
    assert '0x1111111111111111111111111111111111111111' in second['message']
    stale = bind(wallet_client, second['nonce'], signature, TEST_ACCOUNT.address)
    assert stale.status_code == 400


def test_wrong_chain_id_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    TEST_ACCOUNT.address, chain_id=1)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Unsupported network'
    assert WalletBinding.query.count() == 0


def test_expired_challenge_is_rejected(wallet_client, db):
    from datetime import datetime, timedelta
    challenge = issue(wallet_client)
    record = WalletChallenge.query.one()
    record.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    TEST_ACCOUNT.address)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Challenge expired'
    assert WalletBinding.query.count() == 0


def test_replay_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    signature = sign(challenge['message'])
    assert bind(wallet_client, challenge['nonce'], signature,
                TEST_ACCOUNT.address).status_code == 200
    replay = bind(wallet_client, challenge['nonce'], signature, TEST_ACCOUNT.address)
    assert replay.status_code == 400
    assert replay.get_json()['error'] == 'Invalid challenge'
    assert WalletBinding.query.count() == 1


def test_cross_user_challenge_is_rejected(app, db, email_service, auth_api,
                                         phase2_user, wallet_client):
    challenge = issue(wallet_client)
    other = app.test_client()
    other.set_cookie(app.config['SESSION_COOKIE_NAME'],
                     auth_api.get_cookie(app.config['SESSION_COOKIE_NAME']).value)
    # Same session, so this exercises the user filter through a second account.
    db.session.add(User(username='other', email='o@c.edu',
                        password_hash=phase2_user.password_hash,
                        is_active=True, is_verified=True))
    db.session.commit()
    record = WalletChallenge.query.one()
    record.user_id = record.user_id + 100
    db.session.commit()
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    TEST_ACCOUNT.address)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid challenge'


def test_cross_session_challenge_is_rejected(app, db, email_service, auth_api,
                                             phase2_user, wallet_client):
    """M5: User A / Session A must not be usable from User A / Session B."""
    challenge = issue(wallet_client)
    signature = sign(challenge['message'])

    # A second, independent authorized session for the same user.
    second = app.test_client()
    second.post('/api/auth/login',
                json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    second.post('/api/auth/request-otp', json={})
    second.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})
    assert second.get('/api/auth/session').status_code == 200

    response = second.post('/api/wallet/bind', json={
        'nonce': challenge['nonce'], 'signature': signature,
        'wallet_address': TEST_ACCOUNT.address, 'chain_id': 1337})
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid challenge'
    assert WalletBinding.query.count() == 0


def test_logout_invalidates_the_challenge(wallet_client, db, email_service, app):
    challenge = issue(wallet_client)
    signature = sign(challenge['message'])
    wallet_client.post('/api/auth/logout', json={})
    response = wallet_client.post('/api/wallet/bind', json={
        'nonce': challenge['nonce'], 'signature': signature,
        'wallet_address': TEST_ACCOUNT.address, 'chain_id': 1337})
    assert response.status_code == 401


def test_cross_purpose_challenge_is_rejected(wallet_client, db):
    """M6: purpose is part of the lookup, so another purpose cannot be used."""
    challenge = issue(wallet_client)
    record = WalletChallenge.query.one()
    record.purpose = 'SOMETHING_ELSE'
    db.session.commit()
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    TEST_ACCOUNT.address)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid challenge'


def test_attempt_limit_is_enforced(wallet_client, db):
    """M7: a bounded number of invalid signatures burns the challenge."""
    challenge = issue(wallet_client)
    bogus = sign('a completely different message')

    for attempt in range(MAX_SIGNATURE_ATTEMPTS):
        response = bind(wallet_client, challenge['nonce'], bogus, TEST_ACCOUNT.address)
        assert response.status_code == 400, attempt

    assert WalletChallenge.query.one().attempts == MAX_SIGNATURE_ATTEMPTS
    # Even the correct signature is now refused.
    final = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                 TEST_ACCOUNT.address)
    assert final.status_code == 400
    assert WalletBinding.query.count() == 0


def test_malformed_signature_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    for bogus in ('0x', 'not-a-signature', '0x' + 'ab' * 5, ''):
        response = bind(wallet_client, challenge['nonce'], bogus, TEST_ACCOUNT.address)
        assert response.status_code == 400


@pytest.mark.parametrize('address', [
    'not-an-address', '0x123', '0xZZ' + '11' * 19, '0x' + '11' * 19 + 'extra',
])
def test_invalid_wallet_address_is_rejected(wallet_client, db, address):
    challenge = issue(wallet_client)
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']), address)
    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid wallet address'
    assert WalletBinding.query.count() == 0


def test_empty_wallet_address_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']), '')
    assert response.status_code == 400
    assert WalletBinding.query.count() == 0


def test_caller_supplied_message_is_ignored(wallet_client, db):
    """The client may not define the signed message."""
    challenge = issue(wallet_client)
    response = bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                    TEST_ACCOUNT.address,
                    extra={'message': 'a fake message of my choosing'})
    assert response.status_code == 200
    assert WalletBinding.query.count() == 1


def test_caller_supplied_wallet_without_proof_is_rejected(wallet_client, db):
    challenge = issue(wallet_client)
    response = bind(wallet_client, challenge['nonce'], '0x' + 'cd' * 65,
                    TEST_ACCOUNT.address)
    assert response.status_code == 400
    assert WalletBinding.query.count() == 0


def test_fake_frontend_state_grants_nothing(wallet_client, db):
    """Frontend claims cannot create a binding."""
    challenge = issue(wallet_client)
    response = wallet_client.post('/api/wallet/bind', json={
        'nonce': challenge['nonce'], 'signatureVerified': True,
        'walletConnected': True, 'wallet_address': TEST_ACCOUNT.address,
        'chain_id': 1337})
    assert response.status_code == 400
    assert WalletBinding.query.count() == 0


def test_wallet_uniqueness_is_enforced(app, db, email_service, auth_api,
                                       phase2_user, wallet_client):
    """One wallet cannot back two accounts (database constraint)."""
    challenge = issue(wallet_client)
    assert bind(wallet_client, challenge['nonce'], sign(challenge['message']),
                TEST_ACCOUNT.address).status_code == 200

    second = User(username='u2', email='u2@c.edu',
                  password_hash=phase2_user.password_hash, is_active=True, is_verified=True)
    db.session.add(second)
    db.session.commit()
    db.session.add(WalletBinding(user_id=second.id,
                                 wallet_address=TEST_ACCOUNT.address.lower()))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_second_challenge_refused_once_bound(wallet_client, db):
    challenge = issue(wallet_client)
    bind(wallet_client, challenge['nonce'], sign(challenge['message']),
         TEST_ACCOUNT.address)
    assert wallet_client.post('/api/wallet/challenge').status_code == 400


# ------------------------------------------------------------- separation

def test_wallet_stays_in_the_identity_plane(wallet_client, db):
    challenge = issue(wallet_client)
    bind(wallet_client, challenge['nonce'], sign(challenge['message']),
         TEST_ACCOUNT.address)
    assert Ballot.query.count() == 0
    assert BallotQueue.query.count() == 0
    for model in (WalletBinding, WalletChallenge):
        for column in model.__table__.columns:
            for fk in column.foreign_keys:
                assert fk.column.table.name not in (
                    'ballots', 'ballot_queue', 'elections',
                    'election_pseudonym_keys', 'reconciliation_issues')


def test_no_private_key_is_ever_stored(wallet_client, db):
    challenge = issue(wallet_client)
    bind(wallet_client, challenge['nonce'], sign(challenge['message']),
         TEST_ACCOUNT.address)
    blob = repr(WalletBinding.query.one().__dict__) + repr(WalletChallenge.query.one().__dict__)
    assert TEST_ONLY_PRIVATE_KEY not in blob
    assert '0x' + '44' * 32 not in blob


def test_raw_signature_is_not_logged(wallet_client, db, caplog):
    import logging
    challenge = issue(wallet_client)
    with caplog.at_level(logging.DEBUG):
        bind(wallet_client, challenge['nonce'], '0x' + 'ab' * 65, TEST_ACCOUNT.address)
    assert sign(challenge['message']) not in caplog.text


def test_status_does_not_leak_to_unauthenticated_callers(app, db):
    response = app.test_client().get('/api/wallet/status')
    assert response.status_code == 200
    assert response.get_json() == {'bound': False}