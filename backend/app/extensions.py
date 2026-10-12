from __future__ import annotations

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Extension instances are initialized in the app factory to avoid global state.
db = SQLAlchemy()
migrate = Migrate()
