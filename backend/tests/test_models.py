"""
Model foundation tests - Phase 1 (remediated)
Vote Without Doubt - Backend

Phase 1 previously asserted identity/ballot separation by checking a single
attribute on an object that was never persisted. These tests create real rows in
an isolated database and assert the invariants against the actual schema.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    AuditEvent,
    Ballot,
    BallotQueue,
    BaseModel,
    Election,
    ReconciliationIssue,
    User,
    VoterIdentity,
    VotingAuthorization,
)


def _make_election(**overrides):
    payload = {'election_id': 'E-001', 'title': 'Test Election', 'status': 'DRAFT'}
    payload.update(overrides)
    election = Election(**payload)
    db.session.add(election)
    db.session.commit()
    return election


def _make_identity(**overrides):
    payload = {
        'voter_id': 'V001',
        'full_name': 'Test Voter',
        'email': 'test@example.com',
        'is_eligible': True,
        'is_registered': False,
    }
    payload.update(overrides)
    identity = VoterIdentity(**payload)
    db.session.add(identity)
    db.session.commit()
    return identity


def _make_ballot(**overrides):
    payload = {'ballot_id': 'B001', 'election_id': 'E-001', 'ballot_state': 'QUEUED'}
    payload.update(overrides)
    ballot = Ballot(**payload)
    db.session.add(ballot)
    db.session.commit()
    return ballot


# ------------------------------------------------------------- importability

def test_models_can_be_imported():
    for model in (VoterIdentity, Ballot, Election, BaseModel, AuditEvent,
                  BallotQueue, ReconciliationIssue, User):
        assert model is not None


# -------------------------------------------------------------- persistence

def test_voter_identity_persists(db):
    identity = _make_identity()
    stored = db.session.get(VoterIdentity, identity.id)

    assert stored.voter_id == 'V001'
    assert stored.full_name == 'Test Voter'
    assert stored.email == 'test@example.com'
    assert stored.is_eligible is True


def test_ballot_persists(db):
    ballot = _make_ballot()
    stored = db.session.get(Ballot, ballot.id)

    assert stored.ballot_id == 'B001'
    assert stored.election_id == 'E-001'
    assert stored.ballot_state == 'QUEUED'


def test_election_persists(db):
    election = _make_election()
    stored = db.session.get(Election, election.id)

    assert stored.election_id == 'E-001'
    assert stored.title == 'Test Election'
    assert stored.status == 'DRAFT'


def test_timestamps_are_populated_by_the_base_model(db):
    ballot = _make_ballot()
    assert ballot.created_at is not None
    assert ballot.updated_at is not None


# --------------------------------------------------------------- constraints

def test_ballot_id_must_be_unique(db):
    _make_ballot()
    with pytest.raises(IntegrityError):
        _make_ballot(ballot_id='B001')
    db.session.rollback()


def test_election_id_must_be_unique(db):
    _make_election()
    with pytest.raises(IntegrityError):
        _make_election(election_id='E-001')
    db.session.rollback()


def test_voter_id_must_be_unique(db):
    _make_identity()
    with pytest.raises(IntegrityError):
        _make_identity(email='other@example.com')
    db.session.rollback()


def test_ballot_id_is_required(db):
    with pytest.raises(IntegrityError):
        db.session.add(Ballot(ballot_id=None, election_id='E-001'))
        db.session.commit()
    db.session.rollback()


def test_ballot_state_has_a_default(db):
    ballot = Ballot(ballot_id='B-DEFAULT', election_id='E-001')
    db.session.add(ballot)
    db.session.commit()

    assert ballot.ballot_state == 'QUEUED'


# --------------------------------------------------------- plane separation

BALLOT_PLANE_MODELS = (Ballot, Election, BallotQueue, ReconciliationIssue)
IDENTITY_PLANE_TABLES = ('voter_identities', 'users', 'auth_sessions', 'otps',
                         'electoral_roll', 'registration_sessions',
                         'wallet_bindings', 'wallet_challenges',
                         'face_enrollments', 'face_challenges',
                         'voting_authorizations')


def test_ballot_plane_has_no_identity_foreign_keys():
    for model in BALLOT_PLANE_MODELS:
        for column in model.__table__.columns:
            for foreign_key in column.foreign_keys:
                assert foreign_key.column.table.name not in IDENTITY_PLANE_TABLES, (
                    f'{model.__tablename__}.{column.name} links to the identity plane'
                )


def test_ballot_has_no_voter_reference_at_all(db):
    columns = {c.name for c in Ballot.__table__.columns}
    assert 'voter_id' not in columns
    assert 'user_id' not in columns
    assert 'email' not in columns

    ballot = _make_ballot()
    assert not hasattr(ballot, 'voter_id')


def test_ballot_queue_has_no_identity_reference(db):
    columns = {c.name for c in BallotQueue.__table__.columns}
    assert 'voter_id' not in columns
    assert 'user_id' not in columns


def test_ballot_records_do_not_reference_an_identity_table(db):
    """Neither ballots nor ballot_queue may carry an identity foreign key."""
    for model in (Ballot, BallotQueue):
        referenced = {
            fk.column.table.name
            for column in model.__table__.columns
            for fk in column.foreign_keys
        }
        assert not (referenced & set(IDENTITY_PLANE_TABLES)), (
            f'{model.__tablename__} references identity tables: {referenced}'
        )


def test_audit_events_carry_no_identity_reference():
    columns = {c.name for c in AuditEvent.__table__.columns}
    assert columns == {'id', 'event_type', 'created_at', 'metadata',
                       'previous_hash', 'current_hash'}


# ------------------------------------------------------- schema reconciliation

def test_ballots_and_ballot_queue_are_distinct_tables():
    """Regression: two conflicting CREATE TABLE statements both named `ballots`."""
    assert Ballot.__tablename__ == 'ballots'
    assert BallotQueue.__tablename__ == 'ballot_queue'
    assert Ballot.__table__ is not BallotQueue.__table__


def test_recovery_columns_live_on_the_ballot_queue():
    """Regression: these columns were indented into VotingAuthorization."""
    queue_columns = {c.name for c in BallotQueue.__table__.columns}
    authorization_columns = {c.name for c in VotingAuthorization.__table__.columns}

    for column in ('tx_broadcast_at', 'tx_confirmed_at', 'tx_failed_at',
                   'last_retry_at', 'retry_count', 'reconcile_required',
                   'reconcile_reason', 'superseded'):
        assert column in queue_columns, f'{column} missing from ballot_queue'
        assert column not in authorization_columns, (
            f'{column} must not be on voting_authorizations'
        )


def test_recovery_columns_are_nullable_or_defaulted(db):
    queue = BallotQueue(election_id=1, pseudonym='pseudo-1', candidate=1)
    db.session.add(queue)
    db.session.commit()

    assert queue.retry_count == 0
    assert queue.reconcile_required is False
    assert queue.superseded is False
    assert queue.tx_broadcast_at is None


def test_reconciliation_issue_table_is_mapped(db):
    issue = ReconciliationIssue(election_id=1, issue_type='MISMATCH', severity='WARNING')
    db.session.add(issue)
    db.session.commit()

    assert issue.status == 'OPEN'
    assert db.session.get(ReconciliationIssue, issue.id) is not None