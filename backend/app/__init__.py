import os
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from .config import config
from .extensions import db
from .routes.health import health_bp
from .routes.auth import auth_bp
from .routes.registration import reg_bp
from .routes.wallet import wallet_bp
from .routes.face import bp as face_bp
from .routes.voting import bp as voting_bp


def create_app(config_name=None):
    load_dotenv()
    app = Flask(__name__)
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')
    app.config.from_object(config[config_name])
    CORS(app, origins=app.config.get('CORS_ALLOWED_ORIGINS', '*'))
    db.init_app(app)
    app.register_blueprint(health_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(reg_bp, url_prefix='/api')
    app.register_blueprint(wallet_bp, url_prefix='/api')
    app.register_blueprint(face_bp, url_prefix='/api')
    app.register_blueprint(voting_bp, url_prefix='/api')
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not Found', 'message': 'The requested resource was not found'}), 404
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred'}), 500
    return app