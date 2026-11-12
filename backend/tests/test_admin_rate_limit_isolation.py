"""
Admin Rate Limit Isolation Tests
Ensures independent rate limiting for administrative officers on shared IPs,
protecting against cross-officer denial of service while preserving brute force protection.
"""
import pytest
from app.security.rate_limit import _scope_for_request, get_limiter, rate_limit_key


def test_admin_rate_limit_rules_have_dedicated_login_and_import_budgets(app):
    rules = app.config.get('RATE_LIMIT_RULES', {})
    assert '/api/admin/auth/login' in rules
    assert rules['/api/admin/auth/login'][0] == 10
    assert rules['/api/admin/roll/import'] == (10, 300)
    assert rules['/api/admin'] == (60, 60)


def test_scope_for_request_prioritizes_admin_login_over_general_admin(app):
    with app.test_request_context('/api/admin/auth/login'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/admin/auth/login'
        assert limit == 10
        assert window == 300

    with app.test_request_context('/api/admin/elections'):
        scope, limit, window = _scope_for_request()
        assert scope == '/api/admin'
        assert limit == 60
        assert window == 60


def test_admin_login_rate_limit_isolated_per_admin_id(app, client):
    """OFFICER_01 exceeding login budget does not block OFFICER_02 from the same IP."""
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    app.config['ADMIN_RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_RULES'] = {'/api/admin/auth/login': (3, 300), '/api/admin': (60, 60)}
    get_limiter().reset()

    try:
        # 1. OFFICER_01 makes 3 login attempts (budget = 3)
        for i in range(3):
            res = client.post('/api/admin/auth/login', json={'admin_id': 'OFFICER_01', 'password': 'wrong'})
            assert res.status_code != 429, f"Attempt {i+1} for OFFICER_01 should not be 429"

        # 4th attempt for OFFICER_01 is throttled (429)
        blocked_o1 = client.post('/api/admin/auth/login', json={'admin_id': 'OFFICER_01', 'password': 'wrong'})
        assert blocked_o1.status_code == 429
        assert blocked_o1.get_json()['error'] == 'Too Many Requests'

        # 2. OFFICER_02 from the same IP is NOT blocked and has their own fresh budget
        res_o2 = client.post('/api/admin/auth/login', json={'admin_id': 'OFFICER_02', 'password': 'wrong'})
        assert res_o2.status_code != 429, "OFFICER_02 must not be blocked by OFFICER_01 rate limiting"
    finally:
        app.config['RATE_LIMIT_TESTING_ENABLED'] = False
        get_limiter().reset()


def test_general_admin_operations_do_not_exhaust_admin_login_budget(app, client):
    """General /api/admin calls do not consume the /api/admin/auth/login budget."""
    app.config['RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_TESTING_ENABLED'] = True
    app.config['ADMIN_RATE_LIMIT_ENABLED'] = True
    app.config['RATE_LIMIT_RULES'] = {'/api/admin/auth/login': (3, 300), '/api/admin': (60, 60)}
    get_limiter().reset()

    try:
        # Simulate 10 dashboard/election checks
        for _ in range(10):
            client.get('/api/admin/elections')

        # Admin login is still available and not blocked
        res = client.post('/api/admin/auth/login', json={'admin_id': 'OFFICER_02', 'password': 'wrong'})
        assert res.status_code != 429, "Admin login must not be exhausted by general dashboard requests"
    finally:
        app.config['RATE_LIMIT_TESTING_ENABLED'] = False
        get_limiter().reset()
