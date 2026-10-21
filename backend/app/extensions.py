from __future__ import annotations

import sqlite3

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    autocommit = getattr(dbapi_connection, "autocommit", None)
    if autocommit is not None:
        dbapi_connection.autocommit = True
    else:
        isolation_level = dbapi_connection.isolation_level
        dbapi_connection.isolation_level = None

    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
    finally:
        if autocommit is not None:
            dbapi_connection.autocommit = autocommit
        else:
            dbapi_connection.isolation_level = isolation_level


# Extension instances are initialized in the app factory to avoid global state.
db = SQLAlchemy()
migrate = Migrate()
