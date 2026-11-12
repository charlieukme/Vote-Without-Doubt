"""
Flask Extensions
Vote Without Doubt - Backend

Extensions are instantiated here and bound to an application inside the app
factory. Nothing in this module touches application state at import time, so
importing it never requires a database connection.
"""

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()

#: Alembic/Flask-Migrate integration. Schema changes are owned by migrations in
#: ``backend/migrations`` rather than by implicit DDL at application start.
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _set_sqlite_foreign_keys(dbapi_connection, connection_record):
    """
    DB-002: Enforce foreign key constraints on SQLite connections.
    Ensures relational integrity behavior in development and tests matches MySQL InnoDB.
    Leaves non-SQLite connections (e.g. MySQL, PostgreSQL) untouched.
    """
    if type(dbapi_connection).__module__ in ("sqlite3", "_sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
