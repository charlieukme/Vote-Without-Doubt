"""
Test Suite: Election Timing & Authoritative Effective Status Semantics

Proves:
1. UTC timestamps are serialized with 'Z' suffix across public, admin, and voting planes.
2. Expired OPEN/ACTIVE elections dynamically report effective status CLOSED across all planes.
3. open_election rejects opening when now >= end_time with clear lifecycle error.
4. Valid in-window elections open normally.
5. Student voting authorization strictly rejects expired elections with ELECTION_CLOSED.
"""

from datetime import datetime, timedelta
import pytest

from app.extensions import db
from app.models.admin import AdminUser
from app.models.ballot import Election
from app.models.auth import User
from app.security.admin_auth import AdminAuthService
from app.security.totp import generate_totp_code
from app.services.election_admin_service import (
    ElectionAdminService,
    InvalidLifecycleTransitionError,
)
from tests.conftest import _seed_authorized_session


@pytest.fixture
def test_officer(db):
    officer, secret = AdminAuthService.create_admin(
        admin_id="OFFICER_TEST",
        name="Test Officer",
        email="officer_test@election.local",
        password="ValidPassword123!",
        role="OFFICER",
    )
    return officer, secret


def get_admin_auth_header(client, officer, secret):
    code = generate_totp_code(secret)
    res = client.post("/api/admin/auth/login", json={
        "admin_id": officer.admin_id,
        "password": "ValidPassword123!",
        "totp_code": code,
    })
    assert res.status_code == 200, res.get_json()
    token = res.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


from app.security.password import hash_password


@pytest.fixture
def voter_client(app, db, signed_cookie_for):
    user = User(
        username='timing_voter',
        email='timing_voter@college.test',
        password_hash=hash_password('ValidPassword123!'),
        is_active=True,
        is_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    auth_sess = _seed_authorized_session(db, user)

    client = app.test_client()
    client.set_cookie(
        app.config['SESSION_COOKIE_NAME'],
        signed_cookie_for(auth_sess.session_id),
    )
    return client


def test_utc_timestamps_serialized_with_z_suffix(client, voter_client, test_officer):
    """Verify start_time and end_time are explicitly serialized with 'Z' suffix."""
    officer, secret = test_officer
    auth_header = get_admin_auth_header(client, officer, secret)

    start = datetime(2026, 10, 8, 16, 25, 0)
    end = datetime(2026, 10, 8, 17, 25, 0)

    elec = Election(
        election_id="ELEC_TIMEZONE_TEST",
        title="Timezone Serialization Test",
        status="DRAFT",
        start_time=start,
        end_time=end,
    )
    db.session.add(elec)
    db.session.commit()

    # 1. Public plane
    res_pub = client.get("/api/public/elections")
    assert res_pub.status_code == 200
    pub_data = res_pub.get_json()
    match_pub = next(e for e in pub_data["elections"] if e["election_id"] == "ELEC_TIMEZONE_TEST")
    assert match_pub["start_time"].endswith("Z")
    assert match_pub["end_time"].endswith("Z")
    assert match_pub["start_time"] == "2026-10-08T16:25:00Z"
    assert match_pub["end_time"] == "2026-10-08T17:25:00Z"

    # 2. Admin plane
    res_admin = client.get("/api/admin/elections", headers=auth_header)
    assert res_admin.status_code == 200
    admin_data = res_admin.get_json()
    match_admin = next(e for e in admin_data["elections"] if e["election_id"] == "ELEC_TIMEZONE_TEST")
    assert match_admin["start_time"].endswith("Z")
    assert match_admin["end_time"].endswith("Z")
    assert match_admin["start_time"] == "2026-10-08T16:25:00Z"

    # 3. Voting plane
    res_vote = voter_client.get("/api/voting/election/ELEC_TIMEZONE_TEST")
    assert res_vote.status_code == 200
    vote_data = res_vote.get_json()
    assert vote_data["start_time"].endswith("Z")
    assert vote_data["end_time"].endswith("Z")
    assert vote_data["start_time"] == "2026-10-08T16:25:00Z"


def test_expired_open_election_has_effective_status_closed(client, voter_client, test_officer):
    """An OPEN/ACTIVE election whose end_time has passed must report effective status CLOSED across all planes."""
    officer, secret = test_officer
    auth_header = get_admin_auth_header(client, officer, secret)

    now = datetime.utcnow()
    past_start = now - timedelta(hours=2)
    past_end = now - timedelta(minutes=15)

    elec = Election(
        election_id="ELEC_EXPIRED_OPEN",
        title="Expired Open Election",
        status="OPEN",  # Stored in DB as OPEN
        start_time=past_start,
        end_time=past_end,
    )
    db.session.add(elec)
    db.session.commit()

    # Raw database column remains OPEN
    assert elec.status == "OPEN"
    # Authoritative property evaluates to CLOSED
    assert elec.effective_status == "CLOSED"

    # 1. Public catalog reports CLOSED
    res_pub = client.get("/api/public/elections")
    pub_data = res_pub.get_json()
    match_pub = next(e for e in pub_data["elections"] if e["election_id"] == "ELEC_EXPIRED_OPEN")
    assert match_pub["status"] == "CLOSED"

    # 2. Admin register reports CLOSED
    res_admin = client.get("/api/admin/elections", headers=auth_header)
    admin_data = res_admin.get_json()
    match_admin = next(e for e in admin_data["elections"] if e["election_id"] == "ELEC_EXPIRED_OPEN")
    assert match_admin["status"] == "CLOSED"

    # 3. Voting election metadata reports CLOSED
    res_vote = voter_client.get("/api/voting/election/ELEC_EXPIRED_OPEN")
    assert res_vote.status_code == 200
    vote_data = res_vote.get_json()
    assert vote_data["status"] == "CLOSED"


def test_open_election_rejects_past_end_time(db, test_officer):
    """open_election must reject opening an election whose end_time has already elapsed."""
    officer, _ = test_officer

    now = datetime.utcnow()
    past_start = now - timedelta(hours=2)
    past_end = now - timedelta(minutes=5)

    elec = Election(
        election_id="ELEC_SCHEDULED_EXPIRED",
        title="Expired Scheduled Election",
        status="SCHEDULED",
        start_time=past_start,
        end_time=past_end,
    )
    db.session.add(elec)
    db.session.commit()

    with pytest.raises(InvalidLifecycleTransitionError) as exc_info:
        ElectionAdminService.open_election("ELEC_SCHEDULED_EXPIRED", officer)

    assert "Cannot open election after end_time has passed." in str(exc_info.value)
    # Status must remain SCHEDULED, not OPEN
    reloaded = Election.query.filter_by(election_id="ELEC_SCHEDULED_EXPIRED").first()
    assert reloaded.status == "SCHEDULED"


def test_valid_in_window_election_opens_normally(db, test_officer):
    """open_election succeeds when current time is between start_time and end_time."""
    officer, _ = test_officer

    now = datetime.utcnow()
    valid_start = now - timedelta(minutes=5)
    valid_end = now + timedelta(hours=2)

    elec = Election(
        election_id="ELEC_VALID_IN_WINDOW",
        title="Valid In-Window Election",
        status="SCHEDULED",
        start_time=valid_start,
        end_time=valid_end,
    )
    db.session.add(elec)
    db.session.commit()

    opened = ElectionAdminService.open_election("ELEC_VALID_IN_WINDOW", officer)
    assert opened.status == "OPEN"
    assert opened.effective_status == "OPEN"


def test_voting_rejected_after_end_time(voter_client):
    """Student voting authorization must reject expired elections with ELECTION_CLOSED."""
    now = datetime.utcnow()
    past_start = now - timedelta(hours=2)
    past_end = now - timedelta(minutes=10)

    elec = Election(
        election_id="ELEC_EXPIRED_VOTING",
        title="Expired Election Voting Test",
        status="OPEN",
        start_time=past_start,
        end_time=past_end,
    )
    db.session.add(elec)
    db.session.commit()

    res = voter_client.post("/api/voting/authorize", json={
        "election_id": "ELEC_EXPIRED_VOTING",
    })
    assert res.status_code == 400
    assert res.get_json()["error"] == "ELECTION_CLOSED"


def test_string_election_id_accepted_across_voting_endpoints(voter_client):
    """Ensure voting authorize, mark_factors, and status endpoints accept string election_id."""
    now = datetime.utcnow()
    valid_start = now - timedelta(minutes=5)
    valid_end = now + timedelta(hours=2)

    elec = Election(
        election_id="ELEC_STRING_FLOW_TEST",
        title="String Flow Test Election",
        status="OPEN",
        start_time=valid_start,
        end_time=valid_end,
    )
    db.session.add(elec)
    db.session.commit()

    # 1. Authorize accepts string election_id
    res_auth = voter_client.post("/api/voting/authorize", json={
        "election_id": "ELEC_STRING_FLOW_TEST",
    })
    assert res_auth.status_code == 200
    auth_data = res_auth.get_json()
    assert auth_data["election_id"] == "ELEC_STRING_FLOW_TEST"
    assert "authorization_id" in auth_data

    # 2. Status accepts string election_id as query param
    res_status = voter_client.get("/api/voting/status?election_id=ELEC_STRING_FLOW_TEST")
    assert res_status.status_code == 200
    assert "status" in res_status.get_json()

    # 3. Mark factors accepts string election_id
    res_mf = voter_client.post("/api/voting/mark-factors", json={
        "election_id": "ELEC_STRING_FLOW_TEST",
    })
    assert res_mf.status_code == 200
    mf_data = res_mf.get_json()
    assert mf_data["election_id"] == "ELEC_STRING_FLOW_TEST"
    assert "status" in mf_data


def test_scheduled_election_effective_status_lifecycle(client, voter_client):
    """
    Regression test: SCHEDULED election dynamically transitions:
    - now < start_time -> SCHEDULED
    - start_time <= now < end_time -> OPEN (authorizes voting without manual admin intervention)
    - now >= end_time -> CLOSED
    """
    now = datetime.utcnow()

    # 1. Before start: SCHEDULED
    e_future = Election(
        election_id="ELEC_SCHED_FUTURE",
        title="Future Scheduled Election",
        status="SCHEDULED",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
    )
    db.session.add(e_future)

    # 2. Inside window: OPEN
    e_current = Election(
        election_id="ELEC_SCHED_CURRENT",
        title="Current Scheduled In Window",
        status="SCHEDULED",
        start_time=now - timedelta(minutes=5),
        end_time=now + timedelta(hours=1),
    )
    db.session.add(e_current)

    # 3. Past end: CLOSED
    e_past = Election(
        election_id="ELEC_SCHED_PAST",
        title="Past Scheduled Ended",
        status="SCHEDULED",
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(minutes=10),
    )
    db.session.add(e_past)
    db.session.commit()

    assert e_future.effective_status == "SCHEDULED"
    assert e_current.effective_status == "OPEN"
    assert e_past.effective_status == "CLOSED"

    # Verify public listing reflects effective status
    res_pub = client.get("/api/public/elections")
    assert res_pub.status_code == 200
    pub_data = {e["election_id"]: e["status"] for e in res_pub.get_json()["elections"]}
    assert pub_data["ELEC_SCHED_FUTURE"] == "SCHEDULED"
    assert pub_data["ELEC_SCHED_CURRENT"] == "OPEN"
    assert pub_data["ELEC_SCHED_PAST"] == "CLOSED"

    # Verify voting election info endpoint returns OPEN for e_current
    res_vinfo = voter_client.get(f"/api/voting/election/{e_current.election_id}")
    assert res_vinfo.status_code == 200
    assert res_vinfo.get_json()["status"] == "OPEN"

    # Verify voting authorization succeeds for e_current without manual open
    res_auth = voter_client.post("/api/voting/authorize", json={
        "election_id": e_current.election_id,
    })
    assert res_auth.status_code == 200
    assert res_auth.get_json()["election_id"] == e_current.election_id

    # Verify authorization fails for e_future and e_past
    res_future_auth = voter_client.post("/api/voting/authorize", json={
        "election_id": e_future.election_id,
    })
    assert res_future_auth.status_code == 400
    assert res_future_auth.get_json()["error"] == "ELECTION_NOT_ACTIVE"

    res_past_auth = voter_client.post("/api/voting/authorize", json={
        "election_id": e_past.election_id,
    })
    assert res_past_auth.status_code == 400
    assert res_past_auth.get_json()["error"] == "ELECTION_CLOSED"


def test_candidate_retrieval_and_validation_with_string_id(voter_client):
    """
    Regression test: Candidate retrieval and validation uses string election ID throughout
    and correctly handles 3+ candidates without defaulting to 2 or failing back to ID 1.
    """
    from app.models.admin import Candidate
    from app.services.voting_service import VotingService

    now = datetime.utcnow()
    str_eid = "ELEC_CANDIDATE_3_TEST"
    elec = Election(
        election_id=str_eid,
        title="3 Candidates Election",
        status="SCHEDULED",
        start_time=now - timedelta(minutes=5),
        end_time=now + timedelta(hours=1),
        candidate_count=3,
    )
    db.session.add(elec)

    c1 = Candidate(election_id=str_eid, candidate_index=0, name="Alpha", department="CS")
    c2 = Candidate(election_id=str_eid, candidate_index=1, name="Beta", department="EE")
    c3 = Candidate(election_id=str_eid, candidate_index=2, name="Gamma", department="ME")
    db.session.add_all([c1, c2, c3])
    db.session.commit()

    # 1. GET /api/voting/election/<election_id> returns all 3 candidates
    res = voter_client.get(f"/api/voting/election/{str_eid}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["election_id"] == str_eid
    assert data["candidate_count"] == 3
    assert len(data["candidates"]) == 3
    assert [c["name"] for c in data["candidates"]] == ["Alpha", "Beta", "Gamma"]

    # 2. VotingService validate_election_and_candidate accepts candidate index 0, 1, 2
    for idx in [0, 1, 2]:
        valid, err, count = VotingService.validate_election_and_candidate(str_eid, candidate=idx)
        assert valid is True
        assert err == "OK"
        assert count == 3

    # 3. Candidate index 3 is out of bounds
    valid, err, count = VotingService.validate_election_and_candidate(str_eid, candidate=3)
    assert valid is False
    assert err == "INVALID_CANDIDATE"



