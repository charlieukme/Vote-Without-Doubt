import pytest
from app import create_app
from app.extensions import db
from app.models import User, WalletBinding, AuthSession
from app.security.rate_limit import is_rate_limited, _scope_for_request

def test_wallet_status_rate_limit_scope():
    app = create_app()
    with app.test_request_context('/api/wallet/status'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/wallet/status'
        assert limit == 120
        assert window == 60

def test_wallet_challenge_rate_limit_scope():
    app = create_app()
    with app.test_request_context('/api/wallet/challenge'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/wallet'
        assert limit == 30
        assert window == 60

def test_wallet_bind_rate_limit_scope():
    app = create_app()
    with app.test_request_context('/api/wallet/bind'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/wallet'
        assert limit == 30
        assert window == 60

