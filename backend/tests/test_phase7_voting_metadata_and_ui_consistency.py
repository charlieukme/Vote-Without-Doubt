"""Phase 7 tests: Election candidate metadata integrity without hardcoded dummy fallbacks."""

from datetime import datetime, timedelta

from app.extensions import db
from app.models import Candidate, Election


def test_phase7_voting_election_never_returns_dummy_candidates(app, client):
    with app.app_context():
        now = datetime.utcnow()
        el = Election(
            election_id="ELEC_P7_EMPTY",
            title="Zero Candidate Election",
            status="OPEN",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            candidate_count=0,
        )
        db.session.add(el)
        db.session.commit()

        res = client.get(f"/api/voting/election/{el.election_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["candidates"] == []
        assert data["candidate_count"] == 0

        # Add a real candidate and verify it is returned faithfully
        db.session.add(
            Candidate(
                election_id=el.election_id,
                candidate_index=0,
                name="Real Candidate One",
                department="CSE",
            )
        )
        db.session.commit()

        res2 = client.get(f"/api/voting/election/{el.election_id}")
        assert res2.status_code == 200
        data2 = res2.get_json()
        assert data2["candidate_count"] == 1
        assert [c["name"] for c in data2["candidates"]] == ["Real Candidate One"]

