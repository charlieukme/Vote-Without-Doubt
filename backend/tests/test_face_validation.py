def test_face_status_unauth():
    from app import create_app
    app = create_app()
    c = app.test_client()
    r = c.get('/api/face/status')
    assert r.status_code == 401


def test_face_consent_unauth():
    from app import create_app
    app = create_app()
    c = app.test_client()
    r = c.post('/api/face/consent')
    assert r.status_code == 401


def test_face_challenge_enroll_unauth():
    from app import create_app
    app = create_app()
    c = app.test_client()
    r = c.post('/api/face/challenge/enroll')
    assert r.status_code == 401


def test_face_challenge_verify_unauth():
    from app import create_app
    app = create_app()
    c = app.test_client()
    r = c.post('/api/face/challenge/verify')
    assert r.status_code == 401
