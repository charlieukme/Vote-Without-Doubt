from app import create_app
from app.models import BallotRecord, VotingAuthorization
from app.security.pseudonym import derive_pseudonym


def test_pseudonym_not_returned_to_frontend():
    app = create_app()
    c = app.test_client()
    r = c.post('/api/voting/authorize', json={})
    assert r.status_code == 401


def test_ballot_has_no_identity_fields():
    from app.models.ballot_record import BallotQueue as Ballot
    cols = [c.name for c in Ballot.__table__.columns]
    for bad in ['user_id', 'usn', 'email', 'wallet_address', 'session_id', 'face_id']:
        assert bad not in cols


def test_pseudonyms_election_specific():
    assert derive_pseudonym(1, 1) != derive_pseudonym(1, 2)
    assert derive_pseudonym(1, 1) != derive_pseudonym(2, 1)
    assert derive_pseudonym(5, 5) == derive_pseudonym(5, 5)

