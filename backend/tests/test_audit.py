"""
Audit foundation tests - Phase 1 (remediated)
Vote Without Doubt - Backend

Covers the four defects found in the independent Phase 1 audit:

* non-deterministic chain verification (an untampered chain failed 31/300 runs);
* no persistence (events lived in a process-local list);
* incomplete sanitisation (identity/credential/wallet/ballot values leaked);
* no verification of deletion or reordering.
"""

import json
from datetime import datetime, timedelta

import pytest

from app.audit.audit import (
    REDACTED,
    AuditEvent,
    AuditLogger,
    compute_event_hash,
    contains_redacted_marker,
    has_sensitive_keys,
    sanitize_metadata,
    verify_events,
)
from app.extensions import db
from app.models import AuditEvent as MappedAuditEvent

EVENTS = [
    'system.start',
    'election.created',
    'ballot.queued',
]


# ---------------------------------------------------------------- persistence

def test_audit_event_is_mapped_to_the_audit_events_table():
    """The ORM model must map the existing audit_events table, not a new one."""
    assert MappedAuditEvent is AuditEvent
    assert AuditEvent.__tablename__ == 'audit_events'
    columns = {c.name for c in AuditEvent.__table__.columns}
    assert {'id', 'event_type', 'created_at', 'metadata',
            'previous_hash', 'current_hash'} <= columns


def test_audit_logger_persists_events(audit_logger):
    audit_logger.log('system.start', {'phase': 'Phase 1'})
    audit_logger.log('election.created', {'election_id': 'E-1'})

    rows = db.session.execute(
        db.select(AuditEvent).order_by(AuditEvent.id)
    ).scalars().all()

    assert len(rows) == 2
    assert rows[0].event_type == 'system.start'
    assert rows[1].previous_hash == rows[0].current_hash
    assert all(row.current_hash for row in rows)


def test_audit_chain_survives_logger_recreation(app, db):
    """Chain state must live in the database, not in a process-local object."""
    first = AuditLogger()
    for event_type in EVENTS:
        first.log(event_type, {'phase': 'Phase 1'})

    db.session.remove()

    second = AuditLogger()
    assert len(second.load_chain()) == 3
    assert second.verify_chain() is True

    second.log('system.restart', {'phase': 'Phase 1'})
    assert second.verify_chain() is True
    assert len(second.load_chain()) == 4


def test_two_logger_instances_extend_the_same_chain(db, audit_logger):
    """Independent instances must not fork private chains."""
    other = AuditLogger()
    audit_logger.log('system.start', {'phase': 'Phase 1'})
    other.log('system.check', {'status': 'ok'})

    assert other.verify_chain() is True
    assert len(other.load_chain()) == 2


# ---------------------------------------------------------------- determinism

def test_untampered_chain_verifies_repeatedly(audit_logger):
    """Regression: the pre-remediation verifier failed ~10% of untampered runs."""
    for _ in range(50):
        for event_type in EVENTS:
            audit_logger.log(event_type, {'phase': 'Phase 1', 'status': 'ok'})

    logger = AuditLogger()
    for _ in range(100):
        assert logger.verify_chain() is True


def test_verification_does_not_depend_on_the_system_clock(audit_logger, monkeypatch):
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    from app.audit import audit as audit_module

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2000, 1, 1)

    monkeypatch.setattr(audit_module, 'datetime', FrozenDatetime)

    logger = AuditLogger()
    assert logger.verify_chain() is True

    event = logger.load_chain()[0]
    assert event.is_intact() is True


def test_verification_does_not_mutate_the_event(audit_logger):
    audit_logger.log('system.start', {'phase': 'Phase 1'})
    logger = AuditLogger()
    event = logger.load_chain()[0]

    before = (event.current_hash, event.previous_hash,
              json.dumps(event.event_metadata, sort_keys=True))
    logger.verify_chain()
    logger.verify_chain()
    event.compute_hash()

    after = (event.current_hash, event.previous_hash,
             json.dumps(event.event_metadata, sort_keys=True))
    assert before == after


def test_hash_is_reproducible_from_persisted_fields(audit_logger):
    audit_logger.log('system.start', {'phase': 'Phase 1'})
    event = AuditLogger().load_chain()[0]

    expected = compute_event_hash(
        event.event_type, event.created_at, event.event_metadata, event.previous_hash,
    )
    assert expected == event.current_hash


def test_first_event_has_no_previous_hash(audit_logger):
    first = audit_logger.log('system.start', {'phase': 'Phase 1'})
    assert first.previous_hash is None
    assert audit_logger.verify_chain() is True


# ------------------------------------------------------------------ tamper

@pytest.mark.parametrize('field,value', [
    ('event_type', 'system.hacked'),
    ('current_hash', 'f' * 64),
    ('previous_hash', 'a' * 64),
])
def test_tampering_with_hashed_fields_is_detected(audit_logger, field, value):
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    event = AuditLogger().load_chain()[1]
    setattr(event, field, value)
    db.session.commit()

    assert AuditLogger().verify_chain() is False


def test_tampering_with_metadata_is_detected(audit_logger):
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    event = AuditLogger().load_chain()[1]
    event.event_metadata = {'phase': 'Phase 1', 'status': 'exfiltrated'}
    db.session.commit()

    assert AuditLogger().verify_chain() is False


def test_tampering_with_the_timestamp_is_detected(audit_logger):
    """Pre-remediation the verifier reassigned `timestamp`; a changed stored
    timestamp must now be detected rather than silently overwritten."""
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    event = AuditLogger().load_chain()[1]
    event.created_at = event.created_at + timedelta(days=1)
    db.session.commit()

    assert AuditLogger().verify_chain() is False


def test_deleted_event_breaks_the_chain(audit_logger):
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    middle = AuditLogger().load_chain()[1]
    db.session.delete(middle)
    db.session.commit()

    assert AuditLogger().verify_chain() is False


def test_reordered_events_break_the_chain(audit_logger):
    """Swap two events' hashes: both individual hashes and the linkage must fail."""
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    events = AuditLogger().load_chain()
    events[0].current_hash, events[1].current_hash = (
        events[1].current_hash, events[0].current_hash,
    )
    db.session.commit()

    assert AuditLogger().verify_chain() is False


def test_removed_first_event_is_detected(audit_logger):
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    first = AuditLogger().load_chain()[0]
    db.session.delete(first)
    db.session.commit()

    assert AuditLogger().verify_chain() is False


def test_verify_events_reports_the_first_failing_index(audit_logger):
    for event_type in EVENTS:
        audit_logger.log(event_type, {'phase': 'Phase 1'})

    events = AuditLogger().load_chain()
    events[2].current_hash = 'b' * 64

    ok, index = verify_events(events)
    assert ok is False
    assert index == 2


def test_empty_chain_verifies():
    assert verify_events([]) == (True, None)


# ----------------------------------------------------------------- privacy

@pytest.mark.parametrize('metadata', [
    {'voter_id': 'V-001'},
    {'user_id': 7},
    {'email': 'voter@example.com'},
    {'full_name': 'Test Voter'},
    {'phone_number': '+15550100'},
    {'wallet_address': '0xabc123'},
    {'signature': 'deadbeef'},
    {'user_password': 'hunter2'},
    {'password': 'hunter2'},
    {'otp_code': '123456'},
    {'private_key': '0xdeadbeef'},
    {'candidate': 3},
    {'pseudonym': 'pseudo-1'},
    {'ballot_id': 'B-001'},
    {'face_embedding': [0.1, 0.2]},
])
def test_sensitive_keys_are_redacted(metadata):
    key, value = next(iter(metadata.items()))
    clean = sanitize_metadata(metadata)
    assert clean[key] == REDACTED
    assert str(value) not in json.dumps(clean)


def test_unknown_keys_are_redacted_by_default():
    assert sanitize_metadata({'note': 'free text'})['note'] == REDACTED
    assert has_sensitive_keys({'note': 'free text'}) is True


def test_sensitive_keys_are_redacted_when_nested():
    clean = sanitize_metadata({
        'context': {'identity': {'email': 'leak@example.com', 'count': 2}},
        'items': [{'status': 'ok'}, {'otp': '123456'}],
    })
    serialized = json.dumps(clean)

    assert 'leak@example.com' not in serialized
    assert '123456' not in serialized
    assert clean['context']['identity']['email'] == REDACTED
    assert clean['context']['identity']['count'] == 2
    assert clean['items'][0]['status'] == 'ok'
    assert clean['items'][1]['otp'] == REDACTED


def test_sensitive_keys_are_redacted_regardless_of_naming_style():
    for key in ('USER_PASSWORD', 'UserPassword', 'user-password', 'user password'):
        assert sanitize_metadata({key: 'hunter2'})[key] == REDACTED


def test_safe_operational_keys_are_retained():
    clean = sanitize_metadata({
        'action': 'election.create',
        'phase': 'Phase 1',
        'status': 'ok',
        'duration_ms': 42,
        'election_id': 'E-1',
    })
    assert clean == {
        'action': 'election.create',
        'phase': 'Phase 1',
        'status': 'ok',
        'duration_ms': 42,
        'election_id': 'E-1',
    }


def test_non_serializable_metadata_does_not_raise():
    clean = sanitize_metadata({
        'count': 1,
        'when': datetime(2026, 1, 1, 12, 0, 0),
        'obj': object(),
        'blob': b'\x00\x01',
    })
    json.dumps(clean)  # must not raise
    assert clean['count'] == 1
    assert clean['obj'] == REDACTED


def test_deeply_nested_metadata_is_truncated_not_recursed_forever():
    payload = current = {}
    for _ in range(40):
        current['context'] = {}
        current = current['context']
    current['email'] = 'deep@example.com'

    clean = sanitize_metadata(payload)
    json.dumps(clean)
    assert 'deep@example.com' not in json.dumps(clean)


def test_audit_log_never_stores_identity_data(audit_logger):
    """End-to-end: nothing identifying is persisted, even when supplied."""
    audit_logger.log('voter.cast', {
        'action': 'ballot.cast',
        'voter_id': 'V-001',
        'email': 'voter@example.com',
        'full_name': 'Test Voter',
        'wallet_address': '0xabc123',
        'signature': 'deadbeef',
        'candidate': 3,
        'pseudonym': 'pseudo-1',
    })

    event = AuditLogger().load_chain()[0]
    serialized = json.dumps(event.event_metadata)

    for secret in ('V-001', 'voter@example.com', 'Test Voter',
                   '0xabc123', 'deadbeef', 'pseudo-1'):
        assert secret not in serialized
    assert contains_redacted_marker(event.event_metadata) is True
    assert event.event_metadata['action'] == 'ballot.cast'


def test_audit_logger_requires_a_non_empty_event_type(audit_logger):
    with pytest.raises(ValueError):
        audit_logger.log('')
    with pytest.raises(ValueError):
        audit_logger.log(None)


def test_get_chain_returns_serialisable_dicts(audit_logger):
    audit_logger.log('system.start', {'phase': 'Phase 1'})
    chain = AuditLogger().get_chain()

    assert len(chain) == 1
    json.dumps(chain)
    assert set(chain[0]) == {'id', 'event_type', 'created_at', 'metadata',
                             'previous_hash', 'current_hash'}


# ---------------------------------------------------------------------------
# SEC-D0-02 Regression Tests: Audit-Log Hash-Chain Concurrency & Serialization
# ---------------------------------------------------------------------------
from concurrent.futures import ThreadPoolExecutor


def test_sec_d0_02_concurrent_events_same_election(app, db, audit_logger):
    """
    SEC-D0-02: Concurrent audit events within the same election must be serialized
    so that every event links strictly to the preceding event without forking.
    """
    election_id = '101'
    num_threads = 10

    def _log_worker(idx):
        with app.app_context():
            logger = AuditLogger()
            event = logger.log('ballot.queued', {
                'election_id': election_id,
                'sequence': idx,
                'action': 'ballot.cast',
            })
            return event.id, event.current_hash, event.previous_hash

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_log_worker, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    assert len(results) == num_threads

    with app.app_context():
        logger = AuditLogger()
        chain = logger.load_chain()
        assert len(chain) == num_threads

        # Verify linear continuity
        ok, failed_idx = verify_events(chain)
        assert ok is True, f"Chain broken at index {failed_idx}"
        assert logger.verify_chain() is True


def test_sec_d0_02_concurrent_first_event_creation(app, db):
    """
    SEC-D0-02: Concurrent first-event creation on an empty audit log must safely
    produce exactly one root event (previous_hash=None) and serialize subsequent events.
    """
    with app.app_context():
        # Ensure audit log is empty
        AuditEvent.query.delete()
        db.session.commit()
        assert AuditLogger().chain_head() is None

    num_threads = 6

    def _first_event_worker(idx):
        with app.app_context():
            logger = AuditLogger()
            event = logger.log('election.created', {
                'election_id': '101',
                'thread_idx': idx,
            })
            return event.id, event.previous_hash

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_first_event_worker, i) for i in range(num_threads)]
        results = [f.result() for f in futures]

    assert len(results) == num_threads

    with app.app_context():
        logger = AuditLogger()
        chain = logger.load_chain()
        assert len(chain) == num_threads

        # Exactly one root event must exist
        root_events = [e for e in chain if e.previous_hash is None]
        assert len(root_events) == 1, "Only the first event may have previous_hash is None"

        # The chain must verify cleanly
        assert logger.verify_chain() is True


def test_sec_d0_02_concurrent_writes_different_elections(app, db, audit_logger):
    """
    SEC-D0-02: Concurrent events originating from different elections must all
    safely sequence into the unified audit hash chain without divergence.
    """
    elections = ['E-101', 'E-102', 'E-103', 'E-104']
    num_writes_per_election = 3

    def _election_worker(eid, idx):
        with app.app_context():
            logger = AuditLogger()
            return logger.log('election.activity', {
                'election_id': eid,
                'count': idx,
            })

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for eid in elections:
            for i in range(num_writes_per_election):
                futures.append(executor.submit(_election_worker, eid, i))
        results = [f.result() for f in futures]

    total_expected = len(elections) * num_writes_per_election
    assert len(results) == total_expected

    with app.app_context():
        logger = AuditLogger()
        chain = logger.load_chain()
        assert len(chain) == total_expected
        assert logger.verify_chain() is True


def test_sec_d0_02_transaction_rollback_and_retry(app, db, audit_logger):
    """
    SEC-D0-02: Transient operational errors trigger retry and rollback cleanly
    without producing orphaned or unlinked events.
    """
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError

    calls = 0
    real_commit = db.session.commit

    def mock_commit():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("mock lock timeout", params=None, orig=Exception())
        real_commit()

    with patch.object(db.session, 'commit', side_effect=mock_commit):
        event = audit_logger.log('system.retry_test', {'attempt': 1})
        assert event is not None
        assert event.event_type == 'system.retry_test'

    assert calls >= 2
    assert audit_logger.verify_chain() is True


def test_sec_d0_02_linear_chain_verification_after_high_concurrency(app, db, audit_logger):
    """
    SEC-D0-02: High-concurrency barrage across multiple worker threads must produce
    a 100% linear, unbroken, tamper-evident hash chain.
    """
    total_events = 20

    def _worker(idx):
        with app.app_context():
            logger = AuditLogger()
            return logger.log('stress.event', {'count': idx, 'status': 'ok'})

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_worker, i) for i in range(total_events)]
        results = [f.result() for f in futures]

    assert len(results) == total_events

    with app.app_context():
        logger = AuditLogger()
        chain = logger.load_chain()
        assert len(chain) == total_events

        ok, broken_idx = verify_events(chain)
        assert ok is True, f"Hash chain verification broke at index {broken_idx}"
        assert logger.verify_chain() is True