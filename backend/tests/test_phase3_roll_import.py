"""Phase 3 - electoral-roll import authorization and CSV validation.

Mandatory cases covered here: 1, 2, 3, 4, 5, 10, 11, 12, 13, 25, 26, 27, 32, 33, 34.
"""

import io

import pytest

from app.models import ElectoralRoll, RollImportBatch, User
from app.security.admin_bootstrap import ADMIN_TOKEN_HEADER, MIN_TOKEN_LENGTH
from app.services.registration_service import (
    compute_roll_digest,
    current_roll_rows,
)
from app.utils.csv_import import RollImportError, validate_and_parse_roll

GOOD_TOKEN = 'a' * MIN_TOKEN_LENGTH
VALID_CSV = (
    "USN,Name,College Email,Department,Year\n"
    "1CD22CS001,Asha Rao,asha@college.edu,CSE,2\n"
    "1CD22CS002,Bir Singh,bir@college.edu,CSE,3\n"
)


@pytest.fixture
def admin_headers(monkeypatch):
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    return {ADMIN_TOKEN_HEADER: GOOD_TOKEN}


def upload(app, csv_text=VALID_CSV, filename='roll.csv'):
    return app.test_client().post(
        '/api/admin/roll/import',
        data={'file': (io.BytesIO(csv_text.encode('utf-8')), filename)},
        content_type='multipart/form-data',
    )


# ------------------------------------------------------- C1 authorization

def test_anonymous_roll_import_is_rejected(app, db, monkeypatch):
    """1, 26: the central invariant - no anonymous roll modification."""
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    response = upload(app)
    assert response.status_code == 403
    assert ElectoralRoll.query.count() == 0


def test_anonymous_roll_import_is_rejected_even_with_forged_claims(app, db, monkeypatch):
    """27: client-asserted privilege must never be trusted."""
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    client = app.test_client()
    response = client.post(
        '/api/admin/roll/import',
        data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
        content_type='multipart/form-data',
        headers={'is_admin': 'true', 'role': 'admin', 'X-Admin': 'true'},
    )
    assert response.status_code == 403
    assert ElectoralRoll.query.count() == 0


def test_ordinary_voter_session_cannot_import(app, db, monkeypatch, auth_api,
                                             email_service, phase2_user):
    """2: a real authenticated voter is still not an administrator."""
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    from tests.conftest import PHASE2_PASSWORD, PHASE2_USERNAME
    auth_api.post('/api/auth/login',
                  json={'username': PHASE2_USERNAME, 'password': PHASE2_PASSWORD})
    auth_api.post('/api/auth/request-otp', json={})
    auth_api.post('/api/auth/verify-otp', json={'otp': email_service.last_otp})
    assert auth_api.get('/api/auth/session').status_code == 200

    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'],
                      auth_api.get_cookie(app.config['SESSION_COOKIE_NAME']).value)
    response = client.post(
        '/api/admin/roll/import',
        data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
        content_type='multipart/form-data')
    assert response.status_code == 403
    assert ElectoralRoll.query.count() == 0


def test_invalid_admin_credential_is_rejected(app, db, monkeypatch):
    """3"""
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    client = app.test_client()
    response = client.post(
        '/api/admin/roll/import',
        data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
        content_type='multipart/form-data',
        headers={ADMIN_TOKEN_HEADER: 'wrong-token'},
    )
    assert response.status_code == 403
    assert ElectoralRoll.query.count() == 0


def test_short_admin_credential_is_rejected(app, db, monkeypatch):
    """A too-short configured token disables the endpoint (fail closed)."""
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', 'short')
    assert upload(app).status_code == 403
    assert ElectoralRoll.query.count() == 0


def test_missing_admin_configuration_fails_closed(app, db, monkeypatch):
    """Without configuration the roll is read-only, not open."""
    monkeypatch.delenv('ROLL_ADMIN_TOKEN', raising=False)
    assert upload(app).status_code == 403
    assert ElectoralRoll.query.count() == 0


def test_authorized_roll_import_succeeds(app, db, admin_headers):
    """4"""
    client = app.test_client()
    response = client.post(
        '/api/admin/roll/import',
        data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
        content_type='multipart/form-data', headers=admin_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['imported'] == 2
    assert payload['status'] == 'APPLIED'
    assert len(payload['roll_digest']) == 64
    assert ElectoralRoll.query.count() == 2


def test_admin_token_is_never_echoed_to_the_client(app, db, admin_headers):
    client = app.test_client()
    response = client.post(
        '/api/admin/roll/import',
        data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
        content_type='multipart/form-data', headers=admin_headers)
    assert GOOD_TOKEN not in response.get_data(as_text=True)


def test_admin_token_is_not_hardcoded_in_source():
    import pathlib
    backend = pathlib.Path(__file__).resolve().parents[1]
    for path in backend.rglob('*.py'):
        if 'venv' in path.parts or 'tests' in path.parts:
            continue
        text = path.read_bytes().decode('utf-8-sig')
        assert 'ROLL_ADMIN_TOKEN=' not in text.replace("ROLL_ADMIN_TOKEN'", '')


def test_dry_run_writes_no_voter_rows(app, db, admin_headers):
    client = app.test_client()
    response = client.post(
        '/api/admin/roll/dry-run',
        data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
        content_type='multipart/form-data', headers=admin_headers)
    assert response.status_code == 200
    assert response.get_json()['status'] == 'DRY_RUN'
    assert ElectoralRoll.query.count() == 0
    assert RollImportBatch.query.count() == 1


def test_roll_import_is_rate_limited(app, db, admin_headers, monkeypatch):
    """5"""
    from app.security.rate_limit import get_limiter
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    app.config['RATE_LIMIT_RULES'] = {'/api/admin': (3, 300)}
    with app.app_context():
        get_limiter().reset()
    statuses = [upload(app, VALID_CSV.replace('1CD22CS001', f'1CS2{i:04d}')
                       .replace('1CD22CS002', f'2CS2{i:04d}')).status_code
                for i in range(5)]
    assert 429 in statuses


# ------------------------------------------------------ C4 roll integrity

def test_digest_is_deterministic_and_order_independent():
    rows = [
        {'usn': 'U2', 'full_name': 'B', 'college_email': 'b@x.edu'},
        {'usn': 'U1', 'full_name': 'A', 'college_email': 'a@x.edu'},
    ]
    reversed_rows = list(reversed(rows))
    assert compute_roll_digest(rows) == compute_roll_digest(reversed_rows)
    assert compute_roll_digest(rows) == compute_roll_digest(rows)


def test_digest_changes_when_meaningful_data_changes():
    base = [{'usn': 'U1', 'full_name': 'A', 'college_email': 'a@x.edu'}]
    for field, value in [('full_name', 'Changed'), ('college_email', 'new@x.edu'),
                         ('department', 'CSE'), ('year_of_study', 3),
                         ('is_eligible', False)]:
        mutated = [dict(base[0])]
        mutated[0][field] = value
        assert compute_roll_digest(base) != compute_roll_digest(mutated), field


def test_digest_detects_tampering_after_import(app, db, admin_headers):
    """33"""
    client = app.test_client()
    client.post('/api/admin/roll/import',
                data={'file': (io.BytesIO(VALID_CSV.encode()), 'roll.csv')},
                content_type='multipart/form-data', headers=admin_headers)

    assert client.get('/api/admin/roll/verify', headers=admin_headers).status_code == 200

    record = ElectoralRoll.query.filter_by(usn='1CD22CS001').one()
    record.college_email = 'attacker@evil.example'
    db.session.commit()

    response = client.get('/api/admin/roll/verify', headers=admin_headers)
    assert response.status_code == 409
    assert response.get_json()['verified'] is False


def test_verify_endpoint_requires_authorization(app, db, monkeypatch):
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', GOOD_TOKEN)
    assert app.test_client().get('/api/admin/roll/verify').status_code == 403


# --------------------------------------------------------- CSV validation

def test_valid_csv_is_parsed(app):
    rows, errors = validate_and_parse_roll(VALID_CSV.encode())
    assert errors == []
    assert [r['usn'] for r in rows] == ['1CD22CS001', '1CD22CS002']
    assert rows[0]['year'] == 2


@pytest.mark.parametrize('payload', [
    b'', b'\xff\xfe\x00binary',
    "USN,Name\n1CD22CS001,A\n",
    "random,text\n1,2\n",
])
def test_malformed_csv_is_rejected(app, payload):
    """10, 11"""
    with pytest.raises(RollImportError):
        validate_and_parse_roll(payload)


@pytest.mark.parametrize('usn', ["' OR 1=1--", 'not-a-usn!!', 'ab', 'USN 001',
                                 'USN;DROP TABLE users', '<script>x</script>',
                                 'USN' + '0' * 60])
def test_invalid_usn_is_rejected(usn):
    """12"""
    csv_text = f"USN,Name,College Email\n{usn},Test,test@college.edu\n"
    rows, errors = validate_and_parse_roll(csv_text.encode())
    assert rows == []
    assert any('Invalid USN' in error for error in errors)


@pytest.mark.parametrize('email', ['invalidemail', 'no@domain', 'a@b', 'a b@c.edu'])
def test_invalid_email_is_rejected(email):
    csv_text = f"USN,Name,College Email\n1CD22CS001,Test,{email}\n"
    rows, errors = validate_and_parse_roll(csv_text.encode())
    assert rows == []
    assert any('email' in error.lower() for error in errors)


def test_duplicate_csv_rows_are_dropped_not_double_imported():
    """13"""
    csv_text = ("USN,Name,College Email\n"
                "1CD22CS001,Asha,a@college.edu\n"
                "1CD22CS001,Impostor,b@college.edu\n")
    rows, errors = validate_and_parse_roll(csv_text.encode())
    assert len(rows) == 1
    assert rows[0]['name'] == 'Asha'
    assert any('Duplicate USN' in error for error in errors)


def test_ragged_row_is_reported():
    rows, errors = validate_and_parse_roll(
        "USN,Name,College Email\n1CD22CS001,OnlyName\n".encode())
    assert rows == []
    assert errors


def test_out_of_range_year_is_rejected():
    rows, errors = validate_and_parse_roll(
        "USN,Name,College Email,Year\n1CD22CS001,A,a@college.edu,99\n".encode())
    assert rows == []
    assert any('Year' in error for error in errors)


def test_rejected_usn_value_is_not_echoed_back():
    """Error text must not reflect attacker-controlled content."""
    secret = "' OR 1=1--"
    _rows, errors = validate_and_parse_roll(
        f"USN,Name,College Email\n{secret},A,a@college.edu\n".encode())
    assert all(secret not in error for error in errors)