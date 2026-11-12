"""
Application Factory - Phase 1 (remediated)
Vote Without Doubt - Backend

Boot sequence:
  1. load configuration and validate security invariants (fails fast);
  2. initialise extensions (SQLAlchemy, Flask-Migrate);
  3. register security middleware (headers, trusted hosts, CSRF, rate limits);
  4. register blueprints;
  5. create schema ONLY when ``AUTO_CREATE_SCHEMA`` is explicitly enabled.

Schema creation is no longer unconditional and is no longer wrapped in a bare
``except: pass``. An unreachable database is reported, not silently ignored.
"""

import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from .config import config
from .extensions import db, migrate
from .routes.face import bp as face_bp
from .routes.health import health_bp
from .routes.registration import reg_bp
from .routes.voting import bp as voting_bp
from .routes.wallet import wallet_bp
from .routes.auth import auth_bp
from .routes.admin import admin_bp
from .routes.public import public_bp
from .routes.voting_v2 import voting_v2_bp
from .security.middleware import (
    register_csrf_protection,
    register_security_headers,
    register_trusted_hosts,
    register_trusted_proxy,
)
from .security.rate_limit import register_rate_limiting
from .security.logging_filter import register_logging_filter

logger = logging.getLogger(__name__)

_MIGRATION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')


def _resolve_config_name(config_name=None):
    if config_name is None:
        return os.getenv('FLASK_ENV', 'development')
    if config_name not in config:
        raise ValueError(
            f'Unknown configuration "{config_name}". '
            f'Expected one of: {", ".join(sorted(config))}'
        )
    return config_name


def _init_database(app: Flask) -> None:
    """Create tables only when explicitly requested, and never hide failures."""
    if not app.config.get('AUTO_CREATE_SCHEMA'):
        logger.info(
            'AUTO_CREATE_SCHEMA is disabled; schema is owned by migrations. '
            'Run "flask db upgrade" to apply migrations.'
        )
        return
    with app.app_context():
        db.create_all()
    logger.info('AUTO_CREATE_SCHEMA enabled: tables created from ORM metadata.')


def create_app(config_name=None):
    # Ensure backend/.env is located even if current working directory is project root
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _backend_env = os.path.join(_backend_dir, '.env')
    if os.path.isfile(_backend_env):
        load_dotenv(_backend_env)
    load_dotenv()

    app = Flask(__name__)
    config_name = _resolve_config_name(config_name)
    app.config.from_object(config[config_name])

    # Resolved here rather than only at import time, so a DATABASE_URL exported
    # (or set by a test) after this module was imported still takes effect.
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url

    # Fail fast on a missing or insecure secret instead of booting a
    # predictable-signature application.
    config[config_name].validate(app.config)

    if app.debug and app.config.get('APP_ENV') == 'production':
        raise RuntimeError('Debug mode must never be enabled in production.')

    logging.basicConfig(
        level=getattr(logging, str(app.config.get('LOG_LEVEL', 'INFO')).upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )
    if app.config.get('LOG_REDACTION_ENABLED', True):
        register_logging_filter(app)

    CORS(
        app,
        resources={r'/api/*': {'origins': app.config.get('CORS_ALLOWED_ORIGINS', [])}},
        supports_credentials=True,
    )

    db.init_app(app)
    try:
        migrate.init_app(app, db, directory=_MIGRATION_DIR)
    except Exception as error:  # pragma: no cover - migration tooling optional
        logger.error('Flask-Migrate initialisation failed: %s', error)

    register_security_headers(app)
    register_trusted_hosts(app)
    register_csrf_protection(app)
    register_rate_limiting(app)

    if app.config.get('PROXY_FIX_ENABLED'):
        register_trusted_proxy(
            app,
            trusted_proxies=app.config.get('TRUSTED_PROXIES'),
            num_proxies=app.config.get('PROXY_FIX_NUM_PROXIES', 1),
        )

    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(reg_bp, url_prefix='/api')
    app.register_blueprint(wallet_bp, url_prefix='/api')
    app.register_blueprint(face_bp, url_prefix='/api')
    app.register_blueprint(voting_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(public_bp, url_prefix='/api')
    app.register_blueprint(voting_v2_bp)

    _init_database(app)

    # Phase 8 (F-8.7): Startup recovery of stale queued/submitted ballots
    try:
        with app.app_context():
            from app.services.recovery import RecoveryService
            RecoveryService.startup_recover()
    except Exception as exc:
        logger.warning('Startup recovery skipped or failed: %s', exc)

    # Fix 2 & Lifecycle Worker: Start background relayer dispatcher and lifecycle worker
    # Guard against Werkzeug reloader monitor process spawning duplicate background threads
    is_reloader_monitor = (
        (app.debug or os.getenv('FLASK_DEBUG') == 'true' or os.getenv('FLASK_RUN_FROM_CLI'))
        and os.environ.get('WERKZEUG_RUN_MAIN') is not None
        and os.environ.get('WERKZEUG_RUN_MAIN') != 'true'
    )
    if not is_reloader_monitor and (not app.config.get('TESTING') or app.config.get('ENABLE_TEST_ASYNC_RELAYER')):
        try:
            from app.relayer import get_dispatcher
            get_dispatcher(app).start(app)
        except Exception as d_exc:
            logger.warning('Relayer dispatcher startup skipped or failed: %s', d_exc)

        # Automatic Election Lifecycle Worker: auto-provisioning, opening, closing, and finalization
        try:
            from app.services.election_lifecycle_worker import get_lifecycle_worker
            get_lifecycle_worker(app).start(app)
        except Exception as l_exc:
            logger.warning('Election lifecycle worker startup skipped or failed: %s', l_exc)

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'error': 'Bad Request',
            'message': getattr(error, 'description', 'The request could not be understood or was malformed'),
        }), 400

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'error': 'Not Found',
            'message': 'The requested resource was not found',
        }), 404

    @app.errorhandler(413)
    def payload_too_large(error):
        return jsonify({
            'error': 'Payload Too Large',
            'message': 'The request payload exceeds the maximum permitted size limit',
        }), 413

    @app.errorhandler(500)
    def internal_error(error):
        # The exception is logged server-side; the client receives no internals.
        logger.exception('Unhandled server error: %s', error)
        db.session.rollback()
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred',
        }), 500

    return app