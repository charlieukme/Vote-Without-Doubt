"""
Voting V2 Multi-Factor Authorization Lifecycle Tests
Vote Without Doubt - Backend

Explicit verification for:
- Already-bound wallet + successful face verification
- Wallet not bound
- Face verification not completed
- Face verification failed
- Expired voting authorization
- Invalid or missing authorization ID
- Face challenge from a different session
- Attempting to continue without completing both factors
"""

from datetime import datetime, timedelta
import pytest

from app.models import Election, FaceChallenge, FaceEnrollment, User, VotingAuthorization, WalletBinding
from app.services.voting_service import VotingService


@pytest.fixture
def lifecycle_env(app, db):
    """Sets up an active election and a registered student."""
    with app.app_context():
        user = User(
            username="student_factor_test",
            email="student_factor@college.test",
            password_hash="hashed_pw",
            is_active=True,
            is_verified=True,
        )
        election = Election(
            election_id="ELE_FACTOR_LIFECYCLE",
            title="Factor Lifecycle Test Election",
            status="OPEN",
            candidate_count=2,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=5),
        )
        db.session.add_all([user, election])
        db.session.commit()
        return {"user_id": user.id, "election_id": election.id}


def _create_challenge(uid, sid, aid=None, completed=True, success=True):
    return FaceChallenge(
        user_id=uid,
        challenge_id=f"chal_{uid}_{sid}_{int(datetime.utcnow().timestamp())}",
        authorization_id=aid,
        session_id=sid,
        challenge_sequence="",
        nonce="test_nonce_123",
        integrity_mac="test_mac_123",
        completed=completed,
        success=success,
        consumed=False,
        expires_at=datetime.utcnow() + timedelta(minutes=5),
        completed_at=datetime.utcnow() if completed else None,
    )


def test_scenario_already_bound_wallet_plus_successful_face(app, db, lifecycle_env):
    """Scenario 1: Already-bound wallet + successful face verification -> Authorized."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_success_01"

    with app.app_context():
        wb = WalletBinding(user_id=uid, wallet_address="0x1111111111111111111111111111111111111111", is_verified=True)
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add_all([wb, fe])
        db.session.commit()

        # Step 1: Voting authorization initialized on mount
        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid, ttl_sec=300)
        assert va.id is not None
        assert va.authorized is False

        # Step 2: Student completes face verification linked to this authorization
        fc = _create_challenge(uid, sid, aid=va.id, completed=True, success=True)
        db.session.add(fc)
        db.session.commit()

        # Step 3: mark_factors verifies both authentic records
        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is not None
        assert va_res.wallet_verified is True
        assert va_res.face_verified is True
        assert va_res.authorized is True

        fc_updated = db.session.get(FaceChallenge, fc.id)
        assert fc_updated.consumed is True


def test_scenario_wallet_not_bound(app, db, lifecycle_env):
    """Scenario 2: Wallet not bound -> Verification rejected."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_no_wallet_02"

    with app.app_context():
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add(fe)
        db.session.commit()

        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid, ttl_sec=300)
        fc = _create_challenge(uid, sid, aid=va.id, completed=True, success=True)
        db.session.add(fc)
        db.session.commit()

        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is not None
        assert va_res.wallet_verified is False
        assert va_res.authorized is False


def test_scenario_face_verification_not_completed(app, db, lifecycle_env):
    """Scenario 3: Face challenge exists but completed is False -> Verification rejected."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_not_completed_03"

    with app.app_context():
        wb = WalletBinding(user_id=uid, wallet_address="0x2222222222222222222222222222222222222222", is_verified=True)
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add_all([wb, fe])
        db.session.commit()

        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid, ttl_sec=300)
        fc = _create_challenge(uid, sid, aid=va.id, completed=False, success=False)
        db.session.add(fc)
        db.session.commit()

        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is not None
        assert va_res.wallet_verified is True
        assert va_res.face_verified is False
        assert va_res.authorized is False


def test_scenario_face_verification_failed(app, db, lifecycle_env):
    """Scenario 4: Face verification failed (biometric mismatch) -> Verification rejected."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_failed_face_04"

    with app.app_context():
        wb = WalletBinding(user_id=uid, wallet_address="0x3333333333333333333333333333333333333333", is_verified=True)
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add_all([wb, fe])
        db.session.commit()

        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid, ttl_sec=300)
        fc = _create_challenge(uid, sid, aid=va.id, completed=True, success=False)
        db.session.add(fc)
        db.session.commit()

        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is not None
        assert va_res.wallet_verified is True
        assert va_res.face_verified is False
        assert va_res.authorized is False


def test_scenario_expired_voting_authorization(app, db, lifecycle_env):
    """Scenario 5: Expired voting authorization -> returns None."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_expired_05"

    with app.app_context():
        wb = WalletBinding(user_id=uid, wallet_address="0x4444444444444444444444444444444444444444", is_verified=True)
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add_all([wb, fe])
        db.session.commit()

        va = VotingAuthorization(
            user_id=uid,
            election_id=eid,
            session_id=sid,
            expires_at=datetime.utcnow() - timedelta(seconds=10),
            wallet_verified=False,
            face_verified=False,
            authorized=False,
            consumed=False,
        )
        db.session.add(va)
        db.session.commit()

        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is None


def test_scenario_invalid_or_missing_authorization_id(app, db, lifecycle_env):
    """Scenario 6: Challenge created with null or mismatched authorization_id -> Rejected."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_mismatch_auth_06"

    with app.app_context():
        wb = WalletBinding(user_id=uid, wallet_address="0x5555555555555555555555555555555555555555", is_verified=True)
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add_all([wb, fe])
        db.session.commit()

        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid, ttl_sec=300)

        # Challenge has authorization_id = None (issued prematurely before authorization)
        fc = _create_challenge(uid, sid, aid=None, completed=True, success=True)
        db.session.add(fc)
        db.session.commit()

        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is not None
        assert va_res.face_verified is False
        assert va_res.authorized is False


def test_scenario_face_challenge_from_different_session(app, db, lifecycle_env):
    """Scenario 7: Face challenge from different session -> Session mismatch rejected."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid_student = "sess_legit_student_07"
    sid_attacker = "sess_different_session_07"

    with app.app_context():
        wb = WalletBinding(user_id=uid, wallet_address="0x6666666666666666666666666666666666666666", is_verified=True)
        fe = FaceEnrollment(user_id=uid, is_enrolled=True, consent_given=True, encrypted_embedding=b"embedding")
        db.session.add_all([wb, fe])
        db.session.commit()

        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid_student, ttl_sec=300)

        # Challenge issued to a different session
        fc = _create_challenge(uid, sid_attacker, aid=va.id, completed=True, success=True)
        db.session.add(fc)
        db.session.commit()

        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid_student)
        assert va_res is not None
        assert va_res.face_verified is False
        assert va_res.authorized is False


def test_scenario_cannot_continue_without_both_factors(app, db, lifecycle_env):
    """Scenario 8: Neither factor completed -> authorization remains false."""
    uid = lifecycle_env["user_id"]
    eid = lifecycle_env["election_id"]
    sid = "sess_no_factors_08"

    with app.app_context():
        va = VotingService.create_authorization(user_id=uid, election_id=eid, session_id=sid, ttl_sec=300)
        va_res = VotingService.mark_factors(user_id=uid, election_id=eid, session_id=sid)
        assert va_res is not None
        assert va_res.wallet_verified is False
        assert va_res.face_verified is False
        assert va_res.authorized is False
