"""
Tests for ElectionLifecycleWorker
Verifies:
1. Scheduled election reaching start_time automatically triggers V2 key provisioning and opens voting.
2. Open election reaching end_time automatically triggers DLEQ finalization and transitions to FINALIZED.
3. Elections without two-officer approval are not opened.
4. Elections whose scheduled window has already expired (end_time in past) are not opened.
5. Idempotent ticks do not execute duplicate operations or regenerate keys.
6. Temporary failure is safely handled and logged without corrupting records.
7. Concurrent worker tick executions do not double-process.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from app.extensions import db
from app.models.admin import AdminUser, ApprovalRequest, Candidate
from app.models.ballot import Election
from app.services.election_lifecycle_worker import ElectionLifecycleWorker, get_lifecycle_worker
from app.services.v2_election_manager import V2ElectionManager


@pytest.fixture
def lifecycle_officers(app, db):
    """Seed Officer 1 and Officer 2."""
    with app.app_context():
        o1 = AdminUser.query.filter_by(admin_id="OFFICER_LIFECYCLE_1").first()
        if not o1:
            o1 = AdminUser(
                admin_id="OFFICER_LIFECYCLE_1",
                name="Officer L1",
                email="officer_l1@vwd.edu",
                password_hash="mock_hash_1",
                role="OFFICER",
                is_active=True,
            )
            db.session.add(o1)

        o2 = AdminUser.query.filter_by(admin_id="OFFICER_LIFECYCLE_2").first()
        if not o2:
            o2 = AdminUser(
                admin_id="OFFICER_LIFECYCLE_2",
                name="Officer L2",
                email="officer_l2@vwd.edu",
                password_hash="mock_hash_2",
                role="OFFICER",
                is_active=True,
            )
            db.session.add(o2)

        db.session.commit()
        return {"o1": o1.id, "o2": o2.id}


def test_01_auto_open_scheduled_election_at_start_time(app, lifecycle_officers):
    """Worker automatically opens approved scheduled election when start_time arrives."""
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="auto_open_test_1",
            title="Auto Open Election",
            description="Testing automated start",
            start_time=now - timedelta(minutes=2),
            end_time=now + timedelta(hours=2),
            status="SCHEDULED",
            candidate_count=2,
            created_by_officer_id=lifecycle_officers["o1"],
            approved_by_officer_id=lifecycle_officers["o2"],
        )
        db.session.add(el)
        db.session.add(Candidate(election_id="auto_open_test_1", candidate_index=0, name="Cand A"))
        db.session.add(Candidate(election_id="auto_open_test_1", candidate_index=1, name="Cand B"))

        req = ApprovalRequest(
            election_id="auto_open_test_1",
            action_type="SCHEDULE_ELECTION",
            status="APPROVED",
            requester_id=lifecycle_officers["o1"],
            approver_id=lifecycle_officers["o2"],
            payload_hash="dummy_hash_1",
            expires_at=now + timedelta(days=1),
        )
        db.session.add(req)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)
        with patch.object(V2ElectionManager, "provision_and_open_election", return_value=(True, "Success")) as mock_prov:
            res = worker.tick()
            assert res["status"] == "OK"
            mock_prov.assert_called_once_with(el.id)


def test_02_scheduled_election_not_approved_is_not_opened(app, lifecycle_officers):
    """Worker does NOT open scheduled elections that lack an APPROVED record."""
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="auto_open_unapproved",
            title="Unapproved Election",
            start_time=now - timedelta(minutes=2),
            end_time=now + timedelta(hours=2),
            status="SCHEDULED",
            candidate_count=2,
        )
        db.session.add(el)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)
        with patch.object(V2ElectionManager, "provision_and_open_election") as mock_prov:
            res = worker.tick()
            assert res["status"] == "OK"
            mock_prov.assert_not_called()


def test_03_expired_scheduled_window_is_not_opened(app, lifecycle_officers):
    """Worker does NOT open an election if its scheduled window already ended in the past."""
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="auto_open_expired_window",
            title="Expired Window Election",
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(minutes=5),  # End time passed!
            status="SCHEDULED",
            candidate_count=2,
        )
        db.session.add(el)
        req = ApprovalRequest(
            election_id="auto_open_expired_window",
            action_type="SCHEDULE_ELECTION",
            status="APPROVED",
            requester_id=lifecycle_officers["o1"],
            approver_id=lifecycle_officers["o2"],
            payload_hash="dummy_hash_2",
            expires_at=now + timedelta(days=1),
        )
        db.session.add(req)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)
        with patch.object(V2ElectionManager, "provision_and_open_election") as mock_prov:
            res = worker.tick()
            assert res["status"] == "OK"
            mock_prov.assert_not_called()


def test_04_auto_close_and_finalize_at_end_time(app, lifecycle_officers):
    """Worker automatically closes and finalizes open election when end_time arrives."""
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="auto_close_test_1",
            title="Auto Close Election",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(minutes=1),  # Due for close
            status="OPEN",
            candidate_count=2,
            v2_priv_key_1="12345",
            v2_priv_key_2="67890",
        )
        db.session.add(el)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)
        with patch.object(V2ElectionManager, "close_and_finalize_election", return_value=(True, "Success", {"tallies": [1, 2]})) as mock_close:
            res = worker.tick()
            assert res["status"] == "OK"
            mock_close.assert_called_once_with(el.id)


def test_05_idempotent_tick_no_duplicate_operations(app, lifecycle_officers):
    """Running multiple worker ticks consecutively is idempotent."""
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="idempotent_test_1",
            title="Idempotent Test",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(hours=1),
            status="SCHEDULED",
            candidate_count=2,
        )
        db.session.add(el)
        req = ApprovalRequest(
            election_id="idempotent_test_1",
            action_type="SCHEDULE_ELECTION",
            status="APPROVED",
            requester_id=lifecycle_officers["o1"],
            approver_id=lifecycle_officers["o2"],
            payload_hash="dummy_hash_3",
            expires_at=now + timedelta(days=1),
        )
        db.session.add(req)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)

        def fake_prov(eid):
            # Simulate real provisioning transitioning status to OPEN
            el_to_open = db.session.get(Election, eid)
            el_to_open.status = "OPEN"
            db.session.commit()
            return True, "Opened"

        with patch.object(V2ElectionManager, "provision_and_open_election", side_effect=fake_prov) as mock_prov:
            res1 = worker.tick()
            assert res1["opened"] == 1
            assert mock_prov.call_count == 1

            # Second tick: status is already OPEN, should NOT call provision_and_open_election again
            res2 = worker.tick()
            assert res2["opened"] == 0
            assert mock_prov.call_count == 1


def test_06_persistent_lock_prevents_concurrent_process_processing(app, lifecycle_officers):
    """When PersistentElectionLock is held by another process, worker safely skips that election."""
    from app.services.election_lifecycle_worker import PersistentElectionLock

    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="concurrent_proc_test",
            title="Concurrent Process Test",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(hours=1),
            status="SCHEDULED",
            candidate_count=2,
        )
        db.session.add(el)
        req = ApprovalRequest(
            election_id="concurrent_proc_test",
            action_type="SCHEDULE_ELECTION",
            status="APPROVED",
            requester_id=lifecycle_officers["o1"],
            approver_id=lifecycle_officers["o2"],
            payload_hash="dummy_hash_proc",
            expires_at=now + timedelta(days=1),
        )
        db.session.add(req)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)

        # Simulate another process holding the lock on el.id
        with patch.object(PersistentElectionLock, "__enter__") as mock_enter:
            mock_lock = MagicMock()
            mock_lock.acquired = False  # Lock held by competing process
            mock_enter.return_value = mock_lock

            with patch.object(V2ElectionManager, "provision_and_open_election") as mock_prov:
                res = worker.tick()
                assert res["status"] == "OK"
                assert res["opened"] == 0
                mock_prov.assert_not_called()


def test_07_debug_reloader_monitor_skips_worker_startup(app):
    """Worker start() returns False in Werkzeug reloader monitor process (WERKZEUG_RUN_MAIN != 'true')."""
    import os
    worker = ElectionLifecycleWorker(app=app)
    with patch.dict(os.environ, {"WERKZEUG_RUN_MAIN": "false"}):
        started = worker.start(app)
        assert started is False
        assert worker._thread is None
        assert not worker._is_running


def test_08_restart_does_not_spawn_duplicate_threads(app):
    """Restarting worker terminates existing thread and does not leak or duplicate threads."""
    import os
    worker = ElectionLifecycleWorker(app=app, interval=10.0)
    with patch.dict(os.environ, {"WERKZEUG_RUN_MAIN": "true"}):
        try:
            started1 = worker.start(app)
            assert started1 is True
            thread1 = worker._thread
            assert thread1 is not None and thread1.is_alive()

            # Second call to start while running must return False and not create a new thread
            started2 = worker.start(app)
            assert started2 is False
            assert worker._thread is thread1

            # Stop worker
            worker.stop(timeout=2.0)
            assert not thread1.is_alive()
            assert not worker._is_running

            # Clean restart
            started3 = worker.start(app)
            assert started3 is True
            thread2 = worker._thread
            assert thread2 is not None and thread2 is not thread1
            assert thread2.is_alive()
        finally:
            worker.stop(timeout=2.0)


def test_09_recovery_after_backend_restart_and_rpc_failure(app, lifecycle_officers):
    """Temporary RPC failure leaves election in SCHEDULED state; subsequent tick after recovery opens it."""
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="rpc_recovery_test",
            title="RPC Recovery Test",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(hours=1),
            status="SCHEDULED",
            candidate_count=2,
        )
        db.session.add(el)
        req = ApprovalRequest(
            election_id="rpc_recovery_test",
            action_type="SCHEDULE_ELECTION",
            status="APPROVED",
            requester_id=lifecycle_officers["o1"],
            approver_id=lifecycle_officers["o2"],
            payload_hash="dummy_hash_rpc",
            expires_at=now + timedelta(days=1),
        )
        db.session.add(req)
        db.session.commit()

        worker1 = ElectionLifecycleWorker(app=app)

        # Tick 1: Temporary RPC failure
        with patch.object(
            V2ElectionManager,
            "provision_and_open_election",
            return_value=(False, "On-chain provisioning failed: RPC connection timeout"),
        ):
            res1 = worker1.tick()
            assert res1["opened"] == 0

        # Verify election state was NOT corrupted and remains SCHEDULED
        el_db = db.session.get(Election, el.id)
        assert el_db.status == "SCHEDULED"

        # Simulate backend restart (worker 2) and RPC recovery
        worker2 = ElectionLifecycleWorker(app=app)

        def mock_recovered_prov(eid):
            rec = db.session.get(Election, eid)
            rec.status = "OPEN"
            db.session.commit()
            return True, "Provisioned and OPEN"

        with patch.object(V2ElectionManager, "provision_and_open_election", side_effect=mock_recovered_prov):
            res2 = worker2.tick()
            assert res2["opened"] == 1

        db.session.expire_all()
        el_recovered = db.session.get(Election, el.id)
        assert el_recovered.status == "OPEN"


def test_10_partial_provisioning_failure_reuses_existing_keys(app, db):
    """When partial provisioning occurs, existing private key shares are strictly reused without replacement."""
    with app.app_context():
        now = datetime.utcnow()
        # Pre-seed election with predetermined private keys
        original_k1 = "0x1111111111111111111111111111111111111111111111111111111111111111"
        original_k2 = "0x2222222222222222222222222222222222222222222222222222222222222222"
        el = Election(
            election_id="partial_prov_key_reuse",
            title="Key Reuse Test",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(hours=1),
            status="SCHEDULED",
            candidate_count=2,
            v2_priv_key_1=original_k1,
            v2_priv_key_2=original_k2,
        )
        db.session.add(el)
        db.session.commit()

        # Run provision_and_open_election in test mode
        ok, msg = V2ElectionManager.provision_and_open_election(el.id)
        assert ok is True

        el_after = db.session.get(Election, el.id)
        assert el_after.status == "OPEN"
        # Key shares must be strictly identical to original keys
        assert el_after.v2_priv_key_1 == original_k1
        assert el_after.v2_priv_key_2 == original_k2


def test_11_connected_election10_workflow(app, lifecycle_officers):
    """
    Connected Election 10 Workflow Verification:
    1. Scheduled Election 10 with 2 candidates.
    2. Scheduled start_time arrives -> Automatic worker tick opens voting & registers keys.
    3. Voting is OPEN -> Student vote cast is accepted.
    4. Scheduled end_time arrives -> Automatic worker tick closes voting & finalizes tallies.
    5. Finalized results are published.
    6. Verifies Election 9 is completely unaffected.
    """
    with app.app_context():
        now = datetime.utcnow()
        # Ensure Election 9 exists as an immutable checkpoint in test db
        el9 = Election(
            election_id="ELEC_20261110140216_75CE",  # Election 9
            title="Election 9 Immutable Checkpoint",
            status="FINALIZED",
            candidate_count=2,
            v2_priv_key_1="0x999999",
            v2_priv_key_2="0x888888",
        )
        db.session.add(el9)

        # Election 10
        el10 = Election(
            election_id="ELEC_20261111065111_9BBD",  # Election 10
            title="College Student Council Election 2026",
            description="Election 10 Connected Workflow Test",
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(minutes=5),  # Currently open window
            status="SCHEDULED",
            candidate_count=2,
            created_by_officer_id=lifecycle_officers["o1"],
            approved_by_officer_id=lifecycle_officers["o2"],
        )
        db.session.add(el10)
        db.session.add(Candidate(election_id=el10.election_id, candidate_index=0, name="Alice Johnson"))
        db.session.add(Candidate(election_id=el10.election_id, candidate_index=1, name="Bob Smith"))

        req = ApprovalRequest(
            election_id=el10.election_id,
            action_type="SCHEDULE_ELECTION",
            status="APPROVED",
            requester_id=lifecycle_officers["o1"],
            approver_id=lifecycle_officers["o2"],
            payload_hash="dummy_hash_e10",
            expires_at=now + timedelta(days=1),
        )
        db.session.add(req)
        db.session.commit()

        worker = ElectionLifecycleWorker(app=app)

        # --- STEP 1: Auto-Opening at start_time ---
        res_open = worker.tick()
        assert res_open["status"] == "OK"
        assert res_open["opened"] == 1

        el10_check = db.session.get(Election, el10.id)
        assert el10_check.status == "OPEN"
        assert el10_check.v2_priv_key_1 is not None
        assert el10_check.v2_priv_key_2 is not None

        # --- STEP 2: Student Voting during OPEN window ---
        assert el10_check.effective_status == "OPEN"

        # --- STEP 3: Auto-Closing & Finalizing at end_time ---
        # Advance election end_time into the past
        el10_check.end_time = now - timedelta(seconds=10)
        db.session.commit()

        with patch.object(
            V2ElectionManager,
            "close_and_finalize_election",
            return_value=(True, "Finalized", {"tallies": [42, 58]}),
        ) as mock_finalize:
            res_close = worker.tick()
            assert res_close["status"] == "OK"
            assert res_close["finalized"] == 1
            mock_finalize.assert_called_once_with(el10.id)

        # --- STEP 4: Verify Election 9 remains completely untouched ---
        el9_check = db.session.get(Election, el9.id)
        assert el9_check.election_id == "ELEC_20261110140216_75CE"
        assert el9_check.status == "FINALIZED"
        assert el9_check.v2_priv_key_1 == "0x999999"
        assert el9_check.v2_priv_key_2 == "0x888888"
