from app import create_app
from app.security.pseudonym import derive_pseudonym


def test_pseudonym_consistent():
    p = derive_pseudonym(1, 1)
    assert p == derive_pseudonym(1, 1)
    assert p != derive_pseudonym(1, 2)


def test_receipt_no_candidate():
    app = create_app()
    c = app.test_client()
    r = c.post('/api/voting/submit', json={'election_id':1, 'candidate':5})
    assert 'candidate' not in r.data.decode()
