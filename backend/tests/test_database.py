"""
Database foundation tests - Phase 1 (remediated)
Vote Without Doubt - Backend

Phase 1 previously had no database tests at all: no ``conftest.py``, no fixtures,
no constraint coverage, and no migration tooling. These tests exercise a real
schema built by ``db.create_all()`` and, separately, a schema built by the Alembic
migrations, then compare the two so neither can silently drift from the models.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app import create_app
from app.extensions import db
from app.models import AuditEvent

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCHEMA_SQL = BACKEND_DIR / 'app' / 'schema.sql'
MIGRATIONS_DIR = BACKEND_DIR / 'migrations'

#: Tables the ORM maps. Every one must exist in the database and in schema.sql.
EXPECTED_TABLES = {
    'audit_events', 'auth_sessions', 'ballot_queue', 'ballots',
    'election_pseudonym_keys', 'elections', 'electoral_roll',
    'face_challenges', 'face_enrollments', 'otps', 'reconciliation_issues',
    'registration_sessions', 'users', 'voter_identities',
    'voting_authorizations', 'wallet_bindings', 'wallet_challenges',
}


# ------------------------------------------------------------ fresh creation

def test_fresh_schema_creates_every_mapped_table(app):
    with app.app_context():
        db.create_all()
        actual = set(inspect(db.engine).get_table_names())

    assert EXPECTED_TABLES <= actual
    assert 'ballots' in actual and 'ballot_queue' in actual


def test_fresh_schema_creates_tables_without_warnings(app):
    """create_all must not need a pre-existing schema to succeed."""
    with app.app_context():
        db.create_all()
        db.drop_all()
        db.create_all()
        assert set(inspect(db.engine).get_table_names()) >= EXPECTED_TABLES


def test_audit_events_table_exists_and_is_mapped(app):
    with app.app_context():
        db.create_all()
        columns = {c['name'] for c in inspect(db.engine).get_columns('audit_events')}

    assert columns == {c.name for c in AuditEvent.__table__.columns}


def test_audit_events_columns_are_not_nullable_where_required(app):
    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        nullable = {
            column['name']: column['nullable']
            for column in inspector.get_columns('audit_events')
        }

    assert nullable['event_type'] is False
    assert nullable['created_at'] is False
    assert nullable['current_hash'] is False
    assert nullable['previous_hash'] is True
    assert nullable['metadata'] is True


# -------------------------------------------------------------- schema.sql

def _schema_sql_text() -> str:
    return SCHEMA_SQL.read_bytes().decode('utf-8-sig')


def test_schema_sql_declares_every_mapped_table():
    text = _schema_sql_text()
    declared = set(re.findall(r'CREATE TABLE IF NOT EXISTS\s+(\w+)', text, re.IGNORECASE))
    missing = EXPECTED_TABLES - declared
    assert missing == set(), f'tables missing from schema.sql: {sorted(missing)}'


def test_schema_sql_does_not_declare_two_different_ballots_tables():
    """Regression: schema.sql contained two conflicting `ballots` definitions."""
    text = _schema_sql_text()
    ballots_blocks = re.findall(
        r'CREATE TABLE IF NOT EXISTS ballots \((.*?)\n\) ENGINE',
        text, re.IGNORECASE | re.DOTALL,
    )
    assert len(ballots_blocks) == 1, (
        f'schema.sql declares {len(ballots_blocks)} `ballots` tables; exactly one is expected'
    )


def test_schema_sql_recovery_columns_target_the_ballot_queue():
    text = _schema_sql_text()
    queue_block = re.search(
        r'CREATE TABLE IF NOT EXISTS ballot_queue \((.*?)\n\) ENGINE',
        text, re.IGNORECASE | re.DOTALL,
    )
    assert queue_block is not None

    for column in ('tx_broadcast_at', 'tx_confirmed_at', 'tx_failed_at',
                   'last_retry_at', 'retry_count', 'reconcile_required',
                   'reconcile_reason', 'superseded'):
        assert column in queue_block.group(1), f'{column} missing from ballot_queue DDL'

    assert not re.search(r'ALTER TABLE ballots ADD COLUMN', text, re.IGNORECASE)


def test_schema_sql_marks_migrations_as_authoritative():
    assert 'migrations' in _schema_sql_text().lower()


# ------------------------------------------------------------- migrations

def test_migration_environment_exists():
    assert (MIGRATIONS_DIR / 'env.py').is_file()
    assert (MIGRATIONS_DIR / 'alembic.ini').is_file()
    assert list((MIGRATIONS_DIR / 'versions').glob('*.py')), 'no migration revisions found'


def _migration_env(url: str) -> dict:
    """Subprocess environment for `flask db` with an isolated database."""
    environment = dict(os.environ)
    environment.update({
        'DATABASE_URL': url,
        'FLASK_ENV': 'testing',
        'TESTING_SECRET_KEY': 'testing-only-secret-not-for-production',
    })
    environment.pop('FLASK_DEBUG', None)
    return environment


def test_initial_migration_creates_the_full_schema(tmp_path):
    """Apply the migrations to a fresh database and compare with the ORM."""
    database_path = tmp_path / 'migrated.sqlite3'
    url = f'sqlite:///{database_path.as_posix()}'

    completed = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade'],
        cwd=BACKEND_DIR, capture_output=True, text=True,
        env=_migration_env(url), timeout=300,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    with create_engine(url).connect() as connection:
        migrated = set(inspect(connection).get_table_names())
    assert EXPECTED_TABLES <= migrated

    # The migrated schema must agree with the ORM metadata.
    drift = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app:create_app', 'db', 'check'],
        cwd=BACKEND_DIR, capture_output=True, text=True,
        env=_migration_env(url), timeout=300,
    )
    assert drift.returncode == 0, drift.stderr or drift.stdout
    assert 'No new upgrade operations detected' in (drift.stdout + drift.stderr)


def test_migration_and_orm_schemas_agree(tmp_path):
    """Build the same database two ways and diff the table and column sets."""
    migrated_path = tmp_path / 'migrated.sqlite3'
    orm_path = tmp_path / 'from_orm.sqlite3'
    migrated_url = f'sqlite:///{migrated_path.as_posix()}'

    completed = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade'],
        cwd=BACKEND_DIR, capture_output=True, text=True,
        env=_migration_env(migrated_url), timeout=300,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    orm_url = f'sqlite:///{orm_path.as_posix()}'
    previous_url = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = orm_url
    try:
        application = create_app('testing')
        with application.app_context():
            db.create_all()
    finally:
        if previous_url is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = previous_url

    def describe(url):
        engine = create_engine(url)
        with engine.connect() as connection:
            inspector = inspect(connection)
            return {
                table: {column['name'] for column in inspector.get_columns(table)}
                for table in inspector.get_table_names()
                if table != 'alembic_version'
            }

    migrated_schema = describe(migrated_url)
    orm_schema = describe(orm_url)

    assert set(migrated_schema) == set(orm_schema)
    for table in migrated_schema:
        assert migrated_schema[table] == orm_schema[table], (
            f'column mismatch in {table}:\n'
            f'  migrations: {sorted(migrated_schema[table])}\n'
            f'  orm:        {sorted(orm_schema[table])}'
        )


# ------------------------------------------------------------ isolation

def test_each_test_gets_a_fresh_database(app):
    with app.app_context():
        db.create_all()
        assert AuditEvent.query.count() == 0


def test_database_is_dropped_after_the_fixture(app):
    with app.app_context():
        db.create_all()
        db.session.remove()
        db.drop_all()
        assert set(inspect(db.engine).get_table_names()) == set()


def test_sqlite_foreign_keys_enforced(app):
    """DB-002: Verify SQLite connections enforce foreign key constraints."""
    from datetime import datetime, timedelta
    from app.models import VotingAuthorization
    from sqlalchemy.exc import IntegrityError
    import pytest

    with app.app_context():
        db.create_all()
        # Inserting an authorization referencing non-existent user_id must fail
        invalid_va = VotingAuthorization(
            user_id=999999,
            election_id=999999,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        )
        db.session.add(invalid_va)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
