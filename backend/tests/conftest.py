from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db


def validate_test_database_url(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        if url.database in {None, "", ":memory:"}:
            return
        raise RuntimeError("Tests only allow in-memory SQLite databases.")

    if url.get_backend_name() == "postgresql" and (
        url.database == "teamflow_test" or (url.database or "").startswith("teamflow_test_")
    ):
        return

    raise RuntimeError(
        "Tests require in-memory SQLite or a dedicated PostgreSQL database "
        "named teamflow_test or teamflow_test_<suffix>."
    )


@pytest.fixture()
def app():
    application = create_app("testing")
    validate_test_database_url(application.config["SQLALCHEMY_DATABASE_URI"])
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()
