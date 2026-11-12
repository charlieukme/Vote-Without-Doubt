"""
Phase 10D Tests - Database Migration, V2 Crash Recovery & Reconciliation,
and Protocol Version Metadata Resolution (removing id < 9 heuristic).
"""

from datetime import datetime, timedelta
import os
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_migrate import Migrate, downgrade as flask_migrate_downgrade, upgrade as flask_migrate_upgrade
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa

from app.extensions import db as _db
from app.models.ballot import Election
from app.models.ballot_record_v2 import BallotQueueV2, VALID_V2_FINAL_STATES, is_v2_election
from app.models.reconciliation import ReconciliationIssue
from app.services.election_admin_service import ElectionAdminService
from app.services.reconciliation_service import ReconciliationService
from app.services.recovery import RecoveryService
from app.services.verification_service import VerificationService


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / 'migrations')
LIVE_DB_PATH = BACKEND_DIR / 'instance' / 'voting.db'


def _run_migrations_on_sqlite(db_path: Path, revision: str = 'head', downgrade_mode: bool = False) -> None:
    """Run Alembic upgrade or downgrade on an isolated SQLite DB without invoking create_all()."""
    mini_app = Flask('phase10d_migration_test')
    mini_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    mini_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    mini_db = SQLAlchemy(mini_app)
    Migrate(mini_app, mini_db, directory=MIGRATIONS_DIR)
    with mini_app.app_context():
        if downgrade_mode:
            flask_migrate_downgrade(directory=MIGRATIONS_DIR, revision=revision)
        else:
            flask_migrate_upgrade(directory=MIGRATIONS_DIR, revision=revision)
        mini_db.engine.dispose()


def _build_mock_v2_service(
    election_id: int,
    receipts=None,
    transactions=None,
    voter_seq: int = 0,
    total_active: int = 0,
    cast_events=None,
    contract_eid: int = None,
):
    """Build an in-memory mock of BlockchainV2Service with configurable web3/contract responses."""
    receipts = receipts or {}
    transactions = transactions or {}
    cast_events = cast_events or []
    effective_eid = int(contract_eid if contract_eid is not None else election_id)

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.get_transaction_receipt.side_effect = lambda tx_h: receipts.get(tx_h)
    mock_w3.eth.get_transaction.side_effect = lambda tx_h: transactions.get(tx_h)

    mock_contract = MagicMock()
    mock_contract.functions.electionId.return_value.call.return_value = effective_eid
    mock_contract.functions.voterSequence.return_value.call.return_value = voter_seq
    mock_contract.functions.totalActiveBallots.return_value.call.return_value = total_active
    mock_contract.events.BallotCastV2.get_logs.return_value = cast_events

    mock_svc = MagicMock()
    mock_svc.contract_address = '0x' + '11' * 20
    mock_svc.get_web3.return_value = mock_w3
    mock_svc.get_contract.return_value = mock_contract
    return mock_svc


# ---------------------------------------------------------------------------
# Part 2: Alembic Migration Tests (Temp DB & Copied Snapshot Preservation)
# ---------------------------------------------------------------------------

def test_upgrade_from_67074f333ab4_adds_v2_columns_and_preserves_data(tmp_path):
    temp_db = tmp_path / 'upgrade_from_prev.sqlite3'
    _run_migrations_on_sqlite(temp_db, revision='67074f333ab4')

    engine = sa.create_engine(f'sqlite:///{temp_db}')
    try:
        before_cols = {c['name'] for c in sa.inspect(engine).get_columns('elections')}
        assert 'v2_priv_key_1' not in before_cols
        assert 'v2_priv_key_2' not in before_cols
        assert 'protocol_version' not in before_cols

        # Insert a legacy V1 election and a V2-backed election before upgrading
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO elections "
                "(id, election_id, title, status, candidate_count, eligible_count, max_ballots, "
                "cancelled, is_archived, created_at, updated_at) "
                "VALUES (1, 'LEGACY_1', 'Legacy Election 1', 'CLOSED', 2, 10, 3, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            conn.execute(sa.text(
                "INSERT INTO elections "
                "(id, election_id, title, status, candidate_count, eligible_count, max_ballots, "
                "cancelled, is_archived, created_at, updated_at) "
                "VALUES (12, '12', 'V2 Election 12', 'FINALIZED', 3, 10, 3, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            conn.execute(sa.text(
                "INSERT INTO ballot_queue "
                "(id, election_id, candidate, pseudonym, sequence, is_null, state, retry_count, superseded, "
                "created_at, updated_at) "
                "VALUES (1, 1, 1, '0xaa', 1, 0, 'FINALIZED', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            conn.execute(sa.text(
                "INSERT INTO ballot_queue_v2 "
                "(id, election_id, pseudonym, sequence, ciphertexts_json, proof_json, state, "
                "retry_count, superseded, created_at, updated_at) "
                "VALUES (1, 12, '0xbb', 1, '[]', '{}', 'CONFIRMED', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
    finally:
        engine.dispose()

    _run_migrations_on_sqlite(temp_db, revision='head')

    engine2 = sa.create_engine(f'sqlite:///{temp_db}')
    try:
        after_cols = {c['name'] for c in sa.inspect(engine2).get_columns('elections')}
        assert 'v2_priv_key_1' in after_cols
        assert 'v2_priv_key_2' in after_cols
        assert 'protocol_version' in after_cols

        with engine2.connect() as conn:
            ver = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
            assert ver == 'f1a2b3c4d5e6'
            rows = conn.execute(
                sa.text("SELECT id, title, protocol_version FROM elections ORDER BY id")
            ).fetchall()
            assert rows == [
                (1, 'Legacy Election 1', 'V1'),
                (12, 'V2 Election 12', 'V2'),
            ]
    finally:
        engine2.dispose()


def test_upgrade_copied_live_db_preserves_all_records(tmp_path):
    if not LIVE_DB_PATH.exists():
        return

    live_stat_before = (LIVE_DB_PATH.stat().st_size, LIVE_DB_PATH.stat().st_mtime_ns)
    copied_db = tmp_path / 'voting_copy.db'
    shutil.copy2(LIVE_DB_PATH, copied_db)

    src_conn = sqlite3.connect(f'file:{LIVE_DB_PATH}?mode=ro', uri=True)
    try:
        before_elections = src_conn.execute(
            "SELECT id, election_id, title, status, merkle_root, v2_priv_key_1, v2_priv_key_2 "
            "FROM elections ORDER BY id"
        ).fetchall()
        before_candidates = src_conn.execute(
            "SELECT COUNT(*) FROM candidates"
        ).fetchone()[0]
        before_v2_ballots = src_conn.execute(
            "SELECT id, election_id, sequence, state, receipt_code, superseded "
            "FROM ballot_queue_v2 ORDER BY id"
        ).fetchall()
        before_audits = src_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        live_alembic_ver = src_conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        src_conn.close()

    # Apply Phase 10D migration only to the temporary copy
    _run_migrations_on_sqlite(copied_db, revision='head')

    dst_conn = sqlite3.connect(str(copied_db))
    try:
        assert dst_conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == 'f1a2b3c4d5e6'
        after_elections = dst_conn.execute(
            "SELECT id, election_id, title, status, merkle_root, v2_priv_key_1, v2_priv_key_2 "
            "FROM elections ORDER BY id"
        ).fetchall()
        assert after_elections == before_elections
        assert dst_conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == before_candidates
        assert dst_conn.execute(
            "SELECT id, election_id, sequence, state, receipt_code, superseded "
            "FROM ballot_queue_v2 ORDER BY id"
        ).fetchall() == before_v2_ballots
        assert dst_conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before_audits

        proto_map = dict(
            dst_conn.execute("SELECT id, protocol_version FROM elections ORDER BY id").fetchall()
        )
        assert proto_map.get(12) == 'V2'
        assert proto_map.get(1) == 'V1'
    finally:
        dst_conn.close()

    # Guarantee live DB file and revision remained completely untouched
    live_stat_after = (LIVE_DB_PATH.stat().st_size, LIVE_DB_PATH.stat().st_mtime_ns)
    assert live_stat_after == live_stat_before
    check_live = sqlite3.connect(f'file:{LIVE_DB_PATH}?mode=ro', uri=True)
    try:
        assert check_live.execute("SELECT version_num FROM alembic_version").fetchone()[0] == live_alembic_ver
    finally:
        check_live.close()


def test_migration_downgrade_and_reupgrade_clean(tmp_path):
    temp_db = tmp_path / 'rollback_check.sqlite3'
    _run_migrations_on_sqlite(temp_db, revision='head')

    engine = sa.create_engine(f'sqlite:///{temp_db}')
    try:
        cols_head = {c['name'] for c in sa.inspect(engine).get_columns('elections')}
        assert {'v2_priv_key_1', 'v2_priv_key_2', 'protocol_version'}.issubset(cols_head)
    finally:
        engine.dispose()

    # Rollback to 67074f333ab4
    _run_migrations_on_sqlite(temp_db, revision='67074f333ab4', downgrade_mode=True)
    engine_down = sa.create_engine(f'sqlite:///{temp_db}')
    try:
        cols_down = {c['name'] for c in sa.inspect(engine_down).get_columns('elections')}
        assert 'v2_priv_key_1' not in cols_down
        assert 'v2_priv_key_2' not in cols_down
        assert 'protocol_version' not in cols_down
        with engine_down.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == '67074f333ab4'
    finally:
        engine_down.dispose()

    # Re-upgrade to head cleanly
    _run_migrations_on_sqlite(temp_db, revision='head')
    engine_reup = sa.create_engine(f'sqlite:///{temp_db}')
    try:
        cols_reup = {c['name'] for c in sa.inspect(engine_reup).get_columns('elections')}
        assert {'v2_priv_key_1', 'v2_priv_key_2', 'protocol_version'}.issubset(cols_reup)
        with engine_reup.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == 'f1a2b3c4d5e6'
    finally:
        engine_reup.dispose()


# ---------------------------------------------------------------------------
# Part 3: V2 Crash Recovery & Reconciliation Tests
# ---------------------------------------------------------------------------

def _create_v2_election_row(eid: int = 20, status: str = 'OPEN', merkle_root: str = None) -> Election:
    now = datetime.utcnow()
    elec = Election(
        id=eid,
        election_id=str(eid),
        title=f'Test V2 Election {eid}',
        status=status,
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
        candidate_count=2,
        eligible_count=10,
        max_ballots=3,
        protocol_version='V2',
        merkle_root=merkle_root,
    )
    _db.session.add(elec)
    _db.session.commit()
    return elec


def test_v2_recovery_confirmed_submitted_ballot_generates_receipt_and_supersedes_prior(app, db):
    with app.app_context():
        elec = _create_v2_election_row(eid=21)
        pseudonym = 'aa' * 32
        b1 = BallotQueueV2(
            election_id=elec.id,
            pseudonym=pseudonym,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='CONFIRMED',
            tx_hash='0x' + '01' * 32,
            block_number=10,
            receipt_code='REC-21-OLD1',
            superseded=False,
        )
        b2 = BallotQueueV2(
            election_id=elec.id,
            pseudonym=pseudonym,
            sequence=2,
            ciphertexts_json='["c2"]',
            proof_json='{"p":2}',
            state='SUBMITTED',
            tx_hash='0x' + '02' * 32,
            receipt_code=None,
            superseded=False,
        )
        db.session.add_all([b1, b2])
        db.session.commit()

        mock_svc = _build_mock_v2_service(
            elec.id,
            receipts={b2.tx_hash: {'status': 1, 'blockNumber': 42}},
            voter_seq=2,
            total_active=1,
        )

        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc):
            summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert summary['v2_recovered'] == 1
            assert summary['v2_confirmed'] == 1

            db.session.refresh(b1)
            db.session.refresh(b2)
            assert b2.state == 'CONFIRMED'
            assert b2.block_number == 42
            assert b2.receipt_code and b2.receipt_code.startswith(f'REC-{elec.id}-')
            assert b2.superseded is False
            assert b1.superseded is True
            assert RecoveryService.is_idempotent_ok(elec.id) is True


def test_v2_recovery_recovers_missing_tx_hash_from_ballot_cast_v2_event_without_duplicate(app, db):
    with app.app_context():
        elec = _create_v2_election_row(eid=22)
        pseudonym = 'bb' * 32
        pseudo_bytes = bytes.fromhex(pseudonym)
        b1 = BallotQueueV2(
            election_id=elec.id,
            pseudonym=pseudonym,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='SUBMITTED',
            tx_hash=None,
            receipt_code=None,
        )
        db.session.add(b1)
        db.session.commit()

        ev_tx = bytes.fromhex('cc' * 32)
        mock_svc = _build_mock_v2_service(
            elec.id,
            voter_seq=1,
            cast_events=[
                {
                    'args': {'electionId': elec.id, 'pseudonym': pseudo_bytes, 'sequence': 1},
                    'transactionHash': ev_tx,
                    'blockNumber': 55,
                }
            ],
        )

        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc):
            summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert summary['v2_confirmed'] == 1
            db.session.refresh(b1)
            assert b1.state == 'CONFIRMED'
            assert b1.tx_hash == '0x' + 'cc' * 32
            assert b1.block_number == 55
            assert b1.receipt_code is not None
            mock_svc.cast_ballot.assert_not_called()


def test_v2_recovery_reverted_tx_marks_reverted_and_records_v2_issue(app, db):
    with app.app_context():
        elec = _create_v2_election_row(eid=23)
        b1 = BallotQueueV2(
            election_id=elec.id,
            pseudonym='dd' * 32,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='SUBMITTED',
            tx_hash='0x' + 'dd' * 32,
        )
        db.session.add(b1)
        db.session.commit()

        mock_svc = _build_mock_v2_service(
            elec.id,
            receipts={b1.tx_hash: {'status': 0, 'blockNumber': 60}},
        )

        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc):
            summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert summary['v2_failed'] == 1
            db.session.refresh(b1)
            assert b1.state == 'REVERTED'
            assert b1.block_number == 60
            assert b1.tx_failed_at is not None

            issue = ReconciliationIssue.query.filter_by(
                election_id=elec.id,
                issue_type='V2_TX_REVERTED',
                status='OPEN',
            ).first()
            assert issue is not None
            assert issue.protocol_version == 'V2'


def test_v2_recovery_pending_mempool_and_dropped_uncertain_never_silently_confirmed(app, db):
    with app.app_context():
        elec = _create_v2_election_row(eid=24)
        b_pending = BallotQueueV2(
            election_id=elec.id,
            pseudonym='e1' * 32,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='SUBMITTED',
            tx_hash='0x' + 'e1' * 32,
        )
        b_dropped = BallotQueueV2(
            election_id=elec.id,
            pseudonym='e2' * 32,
            sequence=1,
            ciphertexts_json='["c2"]',
            proof_json='{"p":2}',
            state='SUBMITTED',
            tx_hash='0x' + 'e2' * 32,
        )
        db.session.add_all([b_pending, b_dropped])
        db.session.commit()

        mock_svc = _build_mock_v2_service(
            elec.id,
            receipts={},
            transactions={b_pending.tx_hash: {'hash': b_pending.tx_hash}},
            voter_seq=0,
            cast_events=[],
        )

        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc):
            summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert summary['v2_pending'] == 1
            assert summary['v2_uncertain'] == 1
            assert summary['v2_confirmed'] == 0

            db.session.refresh(b_pending)
            db.session.refresh(b_dropped)
            assert b_pending.state == 'SUBMITTED'
            assert b_dropped.state == 'UNCERTAIN'
            assert b_pending.receipt_code is None
            assert b_dropped.receipt_code is None

            issue = ReconciliationIssue.query.filter_by(
                election_id=elec.id,
                issue_type='V2_UNCERTAIN_TX',
                status='OPEN',
            ).first()
            assert issue is not None
            assert issue.protocol_version == 'V2'

            # Second pass must be idempotent (no duplicate state transitions)
            assert RecoveryService.is_idempotent_ok(elec.id) is True


def test_v2_recovery_out_of_order_and_sealed_merkle_immutability(app, db):
    with app.app_context():
        sealed_root = '0x' + 'ab' * 32
        elec = _create_v2_election_row(eid=25, status='FINALIZED', merkle_root=sealed_root)
        pseudonym = 'f1' * 32

        b1_late = BallotQueueV2(
            election_id=elec.id,
            pseudonym=pseudonym,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='SUBMITTED',
            tx_hash='0x' + '1a' * 32,
            receipt_code=None,
            superseded=False,
        )
        b2_active = BallotQueueV2(
            election_id=elec.id,
            pseudonym=pseudonym,
            sequence=2,
            ciphertexts_json='["c2"]',
            proof_json='{"p":2}',
            state='CONFIRMED',
            tx_hash='0x' + '2b' * 32,
            block_number=90,
            receipt_code='REC-25-ACTIVE2',
            superseded=False,
        )
        db.session.add_all([b1_late, b2_active])
        db.session.commit()

        mock_svc = _build_mock_v2_service(
            elec.id,
            receipts={b1_late.tx_hash: {'status': 1, 'blockNumber': 99}},
        )

        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc):
            summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert summary['v2_confirmed'] == 1

            db.session.refresh(elec)
            db.session.refresh(b1_late)
            db.session.refresh(b2_active)

            # Out-of-order late seq=1 must stay superseded by active seq=2
            assert b1_late.state == 'CONFIRMED'
            assert b1_late.superseded is True
            assert b2_active.superseded is False
            # Sealed Merkle root and post-seal receipt invariance
            assert elec.merkle_root == sealed_root
            assert b1_late.receipt_code is None

            issue = ReconciliationIssue.query.filter_by(
                election_id=elec.id,
                issue_type='V2_LATE_RECOVERY_AFTER_MERKLE_SEAL',
                status='OPEN',
            ).first()
            assert issue is not None
            assert issue.severity == 'HIGH'
            assert issue.protocol_version == 'V2'


def test_v2_recovery_unbroadcast_queued_and_reconciliation_service(app, db):
    with app.app_context():
        elec = _create_v2_election_row(eid=26, status='CLOSED')
        pseudonym = 'f2' * 32
        b_queued = BallotQueueV2(
            election_id=elec.id,
            pseudonym=pseudonym,
            sequence=1,
            ciphertexts_json='["c1"]',
            proof_json='{"p":1}',
            state='QUEUED',
            tx_hash=None,
        )
        b_confirmed = BallotQueueV2(
            election_id=elec.id,
            pseudonym='f3' * 32,
            sequence=1,
            ciphertexts_json='["c2"]',
            proof_json='{"p":2}',
            state='CONFIRMED',
            tx_hash='0x' + '3c' * 32,
            receipt_code='REC-26-CONF1',
            superseded=False,
        )
        db.session.add_all([b_queued, b_confirmed])
        db.session.commit()

        # Step 1: When on-chain voterSequence=0, unbroadcast QUEUED ballot on CLOSED election stays QUEUED
        # (never silently confirmed or cast) and records STRANDED_QUEUED with protocol_version='V2'.
        mock_svc_recovery = _build_mock_v2_service(
            elec.id,
            voter_seq=0,
            total_active=1,
            cast_events=[],
        )

        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc_recovery):
            rec_summary = RecoveryService.startup_recover(app=app, detailed=True)
            assert rec_summary['v2_queued'] == 1
            db.session.refresh(b_queued)
            assert b_queued.state == 'QUEUED'
            assert b_queued.receipt_code is None

            stranded = ReconciliationIssue.query.filter_by(
                election_id=elec.id,
                issue_type='STRANDED_QUEUED',
                status='OPEN',
            ).first()
            assert stranded is not None
            assert stranded.protocol_version == 'V2'

        # Step 2: Reconcile when on-chain totalActiveBallots=2 & voterSequence=2 vs DB active=1
        mock_svc_reconcile = _build_mock_v2_service(
            elec.id,
            voter_seq=2,
            total_active=2,
            cast_events=[],
        )
        with patch('app.services.blockchain_v2_service.BlockchainV2Service.for_election', return_value=mock_svc_reconcile):
            reconcile_report = ReconciliationService.reconcile_election(elec.id)
            assert reconcile_report['protocol_version'] == 'V2'
            assert reconcile_report['status'] == 'MISMATCH'
            assert reconcile_report['distinct_voters'] == {'chain': 2, 'db': 1, 'match': False}

            cnt_issue = ReconciliationIssue.query.filter_by(
                election_id=elec.id,
                issue_type='V2_ACTIVE_BALLOT_COUNT_MISMATCH',
                status='OPEN',
            ).first()
            seq_issue = ReconciliationIssue.query.filter_by(
                election_id=elec.id,
                issue_type='V2_SEQUENCE_MISMATCH',
                status='OPEN',
            ).first()
            assert cnt_issue is not None and cnt_issue.protocol_version == 'V2'
            assert seq_issue is not None and seq_issue.protocol_version == 'V2'


# ---------------------------------------------------------------------------
# Part 4: Protocol Version Metadata Resolution (No id < 9 Heuristic)
# ---------------------------------------------------------------------------

def test_protocol_resolution_no_id_lt_9_heuristic(app, db):
    with app.app_context():
        app.config['BALLOTBOX_CONTRACT_ADDRESS'] = '0x' + '99' * 20

        # Election id=1 explicitly marked protocol_version='V2' MUST NEVER fall back to V1 contract
        elec_v2_id1 = Election(
            id=1,
            election_id='V2_NUM_1',
            title='V2 Election With Small ID',
            status='SCHEDULED',
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1),
            protocol_version='V2',
        )
        # Election id=15 explicitly marked protocol_version='V1' MUST still resolve V1 contract cleanly
        elec_v1_id15 = Election(
            id=15,
            election_id='V1_NUM_15',
            title='V1 Election With Large ID',
            status='CLOSED',
            start_time=datetime.utcnow() - timedelta(hours=2),
            end_time=datetime.utcnow() - timedelta(hours=1),
            protocol_version='V1',
        )
        db.session.add_all([elec_v2_id1, elec_v1_id15])
        db.session.commit()

        app.config['ENABLE_V2_DEPLOY_IN_TESTS'] = True

        assert is_v2_election(elec_v2_id1) is True
        assert VerificationService._resolve_target_contract(elec_v2_id1) is None

        assert is_v2_election(elec_v1_id15) is False
        assert VerificationService._resolve_target_contract(elec_v1_id15) == '0x' + '99' * 20

        # Verify ElectionAdminService.create_election persists protocol_version explicitly
        from app.models.admin import AdminUser
        officer = AdminUser(
            admin_id='proto_officer',
            name='Proto Officer',
            email='proto_officer@test.local',
            password_hash='x',
            role='OFFICER',
            is_active=True,
        )
        db.session.add(officer)
        db.session.commit()

        created_v2 = ElectionAdminService.create_election(
            election_id='AUTO_V2_PROTO',
            title='Auto V2 Protocol Election',
            description='test',
            start_time=datetime.utcnow() + timedelta(minutes=5),
            end_time=datetime.utcnow() + timedelta(hours=2),
            officer=officer,
        )
        assert created_v2.protocol_version == 'V2'
        assert is_v2_election(created_v2) is True

        created_v1 = ElectionAdminService.create_election(
            election_id='EXPLICIT_V1_PROTO',
            title='Explicit V1 Protocol Election',
            description='test',
            start_time=datetime.utcnow() + timedelta(minutes=5),
            end_time=datetime.utcnow() + timedelta(hours=2),
            officer=officer,
            protocol_version='V1',
        )
        assert created_v1.protocol_version == 'V1'
        assert is_v2_election(created_v1) is False
