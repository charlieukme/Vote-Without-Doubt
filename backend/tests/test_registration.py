"""
Test electoral roll and registration - Phase 3
"""

import io
import pytest
from app import create_app
from app.utils.csv_import import validate_and_parse_roll, RollImportError


def test_csv_parse_valid():
    csv_data = "USN,Name,College Email,Department\nUSN001,John Doe,john@college.edu,CSE\n"
    rows, errors = validate_and_parse_roll(csv_data.encode('utf-8'))
    assert len(errors) == 0
    assert len(rows) == 1
    assert rows[0]['usn'] == 'USN001'
    assert rows[0]['name'] == 'John Doe'
    assert rows[0]['email'] == 'john@college.edu'


def test_csv_parse_missing_required():
    csv_data = "USN,Name\nUSN001,John\n"
    try:
        validate_and_parse_roll(csv_data.encode('utf-8'))
        assert False
    except RollImportError:
        pass


def test_csv_duplicate_usn():
    csv_data = "USN,Name,College Email\nUSN001,John,john@c.edu\nUSN001,Jane,jane@c.edu\n"
    rows, errors = validate_and_parse_roll(csv_data.encode('utf-8'))
    assert len(errors) > 0
    assert 'Duplicate USN' in errors[0]


def test_csv_invalid_email():
    csv_data = "USN,Name,College Email\nUSN001,John,invalidemail\n"
    rows, errors = validate_and_parse_roll(csv_data.encode('utf-8'))
    assert len(errors) > 0


def test_registration_check_not_found(db):
    """Uses the shared `db` fixture: the app no longer creates tables implicitly."""
    app = create_app('testing')
    client = app.test_client()
    res = client.post('/api/registration/check', json={'usn': 'NONEXIST'})
    assert res.status_code == 400
