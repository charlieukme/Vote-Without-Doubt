"""
Application Configuration
Vote Without Doubt - Backend
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration class"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Application
    APP_NAME = os.getenv('APP_NAME', 'Vote Without Doubt')
    APP_ENV = os.getenv('APP_ENV', 'production')
    
    # Database
    MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
    MYSQL_DATABASE = os.getenv('MYSQL_DATABASE', 'voting_sys')
    MYSQL_USER = os.getenv('MYSQL_USER', 'voting_sys_user')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
    
    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@"
        f"{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 5))
    SQLALCHEMY_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', 3600))
    
    # CORS
    CORS_ALLOWED_ORIGINS = os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5173,http://localhost:3000'
    ).split(',')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Security
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour (foundation - will be tightened later)
    
    # Rate Limiting (Foundation - disabled for Phase 1)
    RATE_LIMIT_ENABLED = os.getenv('RATE_LIMIT_ENABLED', 'False').lower() == 'true'


class DevelopmentConfig(Config):
    """Development configuration"""
    FLASK_DEBUG = True
    APP_ENV = 'development'
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    FLASK_DEBUG = True
    APP_ENV = 'testing'
    # Use in-memory SQLite for tests if needed, but we test config
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class ProductionConfig(Config):
    """Production configuration"""
    FLASK_DEBUG = False
    APP_ENV = 'production'
    SESSION_COOKIE_SECURE = True  # Requires HTTPS


config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
