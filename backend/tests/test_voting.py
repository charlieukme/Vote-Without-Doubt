from app import create_app


def test_voting_authorize_unauth():
    app = create_app()
    c = app.test_client()
    r = c.post('/api/voting/authorize', json={})
    assert r.status_code == 401


def test_voting_submit_unauth():
    app = create_app()
    c = app.test_client()
    r = c.post('/api/voting/submit', json={'election_id':1, 'candidate':0})
    assert r.status_code == 401


def test_voting_status_unauth():
    app = create_app()
    c = app.test_client()
    r = c.get('/api/voting/status')
    assert r.status_code == 401


def test_pseudonym_deterministic():
    from app.security.pseudonym import derive_pseudonym
    p1 = derive_pseudonym(1, 1)
    p2 = derive_pseudonym(1, 1)
    assert p1 == p2


def test_pseudonym_diff_election():
    from app.security.pseudonym import derive_pseudonym
    assert derive_pseudonym(1, 1) != derive_pseudonym(1, 2)


def test_pseudonym_diff_user():
    from app.security.pseudonym import derive_pseudonym
    assert derive_pseudonym(1, 1) != derive_pseudonym(2, 1)
