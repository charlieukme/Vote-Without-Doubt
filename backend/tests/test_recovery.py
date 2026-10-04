from app import create_app
from app.services.recovery import RecoveryService


def test_recovery_idempotent():
    assert RecoveryService.is_idempotent_ok() is True


def test_reconcile_required_state_safe():
    app = create_app()
    c = app.test_client()
    r = c.post('/api/voting/submit', json={})
    assert b'reconcile_required' not in r.data
