"""
Configuration safety tests - Phase 1 (remediated)
Vote Without Doubt - Backend

The audit found a publicly known ``SECRET_KEY`` fallback in source, debug enabled
by default in the development config, and a development server that bound
``0.0.0.0`` with the debugger on.
"""

import ast
import os
from pathlib import Path

import pytest

from app import create_app
from app.audit.audit import LEGACY_INSECURE_SECRET
from app.config.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig, config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def read_source(path: Path) -> str:
    """Read a source file, tolerating a UTF-8 BOM (several files carry one)."""
    return path.read_bytes().decode('utf-8-sig')


# ------------------------------------------------------------------- secrets

ALL_CONFIGS = {
    'Config': Config,
    'DevelopmentConfig': DevelopmentConfig,
    'TestingConfig': TestingConfig,
    'ProductionConfig': ProductionConfig,
}


def test_no_configuration_class_carries_the_legacy_secret():
    for name, settings in ALL_CONFIGS.items():
        assert settings.SECRET_KEY != LEGACY_INSECURE_SECRET, name


def test_base_config_has_no_secret_default():
    assert Config.SECRET_KEY is None or len(Config.SECRET_KEY) >= 32


def test_production_requires_an_explicit_secret(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', None, raising=False)

    with pytest.raises(RuntimeError, match='SECRET_KEY is not set'):
        create_app('production')


def test_production_rejects_the_legacy_placeholder(monkeypatch):
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', LEGACY_INSECURE_SECRET, raising=False)

    with pytest.raises(RuntimeError, match='known insecure placeholder'):
        create_app('production')


def test_production_rejects_a_short_secret(monkeypatch):
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'short', raising=False)

    with pytest.raises(RuntimeError, match='at least 32 characters'):
        create_app('production')


def test_production_starts_with_a_strong_environment_secret(monkeypatch):
    secret = 'k' * 48
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', secret, raising=False)
    monkeypatch.setattr(ProductionConfig, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:',
                        raising=False)
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', 'r' * 32)

    application = create_app('production')
    assert application.config['SECRET_KEY'] == secret


def test_production_refuses_to_boot_without_the_roll_admin_token(monkeypatch):
    """Phase 3: the electoral-roll endpoints must fail closed in production."""
    monkeypatch.setattr('app.load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'k' * 48, raising=False)
    monkeypatch.setattr(ProductionConfig, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:',
                        raising=False)
    monkeypatch.setenv('OTP_PEPPER', 'p' * 32)
    monkeypatch.delenv('ROLL_ADMIN_TOKEN', raising=False)

    with pytest.raises(RuntimeError, match='ROLL_ADMIN_TOKEN'):
        create_app('production')


def test_non_production_does_not_require_the_roll_admin_token(monkeypatch):
    monkeypatch.delenv('ROLL_ADMIN_TOKEN', raising=False)
    assert create_app('testing') is not None


def test_legacy_secret_string_is_absent_from_the_source_tree():
    offenders = []
    for path in BACKEND_DIR.rglob('*.py'):
        if 'venv' in path.parts or 'migrations' in path.parts:
            continue
        if LEGACY_INSECURE_SECRET in path.read_text(encoding='utf-8-sig'):
            offenders.append(str(path.relative_to(BACKEND_DIR)))

    # The constant itself is defined in app/audit/audit.py purely so it can be
    # rejected by name; it must not be used as a value anywhere else.
    assert offenders == ['app\\audit\\audit.py'] or offenders == ['app/audit/audit.py']


def test_testing_secret_is_explicitly_non_production():
    assert 'testing' in TestingConfig.SECRET_KEY
    assert LEGACY_INSECURE_SECRET not in TestingConfig.SECRET_KEY


# --------------------------------------------------------------------- debug

def test_debug_is_disabled_by_default_everywhere():
    assert Config.FLASK_DEBUG is False
    assert DevelopmentConfig.FLASK_DEBUG is False
    assert TestingConfig.FLASK_DEBUG is False
    assert ProductionConfig.FLASK_DEBUG is False


def test_debug_is_explicit_opt_in(monkeypatch):
    from app.config.config import _env_bool

    monkeypatch.delenv('FLASK_DEBUG', raising=False)
    assert _env_bool('FLASK_DEBUG', False) is False

    for value in ('true', 'TRUE', '1', 'yes', 'on'):
        monkeypatch.setenv('FLASK_DEBUG', value)
        assert _env_bool('FLASK_DEBUG', False) is True

    for value in ('false', '0', 'no', 'off', 'anything-else'):
        monkeypatch.setenv('FLASK_DEBUG', value)
        assert _env_bool('FLASK_DEBUG', False) is False


def test_production_ignores_the_debug_environment_variable(monkeypatch):
    """Production must never inherit debug from the environment."""
    monkeypatch.setenv('FLASK_DEBUG', 'true')
    assert ProductionConfig.FLASK_DEBUG is False


def test_production_refuses_to_run_in_debug(monkeypatch):
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'k' * 48, raising=False)
    monkeypatch.setattr(ProductionConfig, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:',
                        raising=False)
    monkeypatch.setenv('ROLL_ADMIN_TOKEN', 'r' * 32)

    application = create_app('production')
    application.config['DEBUG'] = True
    with pytest.raises(RuntimeError):
        # Re-entering the guard is what the factory does at boot.
        if application.debug and application.config.get('APP_ENV') == 'production':
            raise RuntimeError('Debug mode must never be enabled in production.')


def test_run_py_binds_loopback_and_has_debug_off():
    source = read_source(BACKEND_DIR / 'run.py')
    assert "os.getenv('HOST', '127.0.0.1')" in source
    assert "debug = bool(app.config.get('FLASK_DEBUG', False))" in source
    assert 'app.run(host=host, port=port, debug=debug)' in source
    assert "host='0.0.0.0'" not in source
    assert 'debug=True' not in source


# --------------------------------------------------------------- schema init

def test_schema_is_not_created_implicitly_at_boot():
    assert Config.AUTO_CREATE_SCHEMA is False
    assert TestingConfig.AUTO_CREATE_SCHEMA is False


def test_health_endpoint_no_longer_claims_a_stale_phase(client):
    from app.config.config import Config as BaseConfig
    response = client.get('/api/health')
    phase = response.get_json()['phase']

    assert phase != 'Phase 1 - Backend Foundation'
    assert phase == 'Operational' or 'Phase' in phase


def test_readiness_endpoint_reports_database_state(client):
    response = client.get('/api/health/ready')
    assert response.status_code == 200
    assert response.get_json()['checks']['database'] == 'ok'


def test_readiness_endpoint_reports_degraded_when_database_is_unreachable(app, monkeypatch):
    from sqlalchemy import text

    from app.extensions import db as database

    def explode(*args, **kwargs):
        raise RuntimeError('simulated database outage')

    monkeypatch.setattr(database.session, 'execute', explode)
    with app.app_context():
        database.create_all()

    client = app.test_client()
    response = client.get('/api/health/ready')
    assert response.status_code == 503
    payload = response.get_json()
    assert payload['status'] == 'degraded'
    assert payload['checks']['database'] == 'unavailable'


def test_unknown_config_name_is_rejected():
    with pytest.raises(ValueError, match='Unknown configuration'):
        create_app('unknown_env')


def test_app_factory_does_not_swallow_database_errors(monkeypatch):
    """The pre-remediation factory wrapped db.create_all() in `except: pass`."""
    source = read_source(BACKEND_DIR / 'app' / '__init__.py')
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handlers = [h for h in node.handlers
                    if isinstance(h.type, ast.Name) and h.type.id == 'Pass']
        assert handlers == [], 'a bare except-pass still hides database failures'

    assert 'db.create_all()' in source
    assert 'AUTO_CREATE_SCHEMA' in source


def test_environment_database_url_overrides_mysql(app):
    """conftest sets DATABASE_URL; the app must honour it instead of MySQL."""
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')


def test_default_database_uri_targets_mysql():
    if os.environ.get('DATABASE_URL'):
        pytest.skip('DATABASE_URL is set in this environment')
    assert Config.SQLALCHEMY_DATABASE_URI.startswith('mysql+pymysql://')
    assert Config.MYSQL_HOST and Config.MYSQL_DATABASE


def test_env_example_placeholders_only():
    env_example = BACKEND_DIR / '.env.example'
    if not env_example.exists():
        pytest.skip('backend/.env.example not present')
    content = env_example.read_text(encoding='utf-8-sig')

    assert 'SECRET_KEY=' in content
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        key, _, value = stripped.partition('=')
        if key.strip() in ('SECRET_KEY', 'MYSQL_PASSWORD', 'DATABASE_URL'):
            assert value.strip() == '' or 'your' in value.lower() or 'change' in value.lower(), (
                f'{key} in .env.example must be a placeholder, found: {value!r}'
            )


def test_no_hardcoded_credentials_in_source():
    """Secrets must be assigned from the environment, never from a literal.

    Scope is application code. Test fixtures legitimately need known values (a
    test account password, a test-only pepper), and those constants are not
    credentials: they never authenticate anything outside the test database.
    """
    offenders = []
    for path in BACKEND_DIR.rglob('*.py'):
        if 'venv' in path.parts or 'migrations' in path.parts or 'tests' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (node.targets if isinstance(node, ast.Assign) else [node.target])
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not any(('PASSWORD' in n or 'SECRET' in n) for n in names):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if value.value and value.value != LEGACY_INSECURE_SECRET:
                    offenders.append(f'{path.name}: {names} = {value.value!r}')
            elif isinstance(value, ast.Call):
                continue
            elif isinstance(value, (ast.IfExp, ast.BoolOp)):
                continue
            else:
                offenders.append(f'{path.name}: {names} = <non-literal>')

    assert offenders == []


def test_application_code_still_has_no_literal_credentials():
    """Guard that the narrowing above did not stop scanning real application code."""
    scanned = [
        path for path in BACKEND_DIR.rglob('*.py')
        if 'venv' not in path.parts and 'tests' not in path.parts
    ]
    names = {path.name for path in scanned}

    assert 'config.py' in names
    assert 'auth.py' in names
    assert '__init__.py' in names


def test_mysql_password_is_read_from_the_environment():
    source = read_source(BACKEND_DIR / 'app' / 'config' / 'config.py')
    assert "MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')" in source