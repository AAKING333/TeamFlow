from __future__ import annotations

import pytest
from conftest import validate_test_database_url


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///:memory:",
        "postgresql+psycopg://teamflow_test@localhost/teamflow_test",
        "postgresql+psycopg://teamflow_test@localhost/teamflow_test_ci_123",
    ],
)
def test_test_database_guard_allows_isolated_databases(database_url):
    validate_test_database_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///teamflow.db",
        "sqlite:///teamflow_test.db",
        "postgresql+psycopg://teamflow@localhost/teamflow_dev",
        "postgresql+psycopg://teamflow@localhost/postgres",
    ],
)
def test_test_database_guard_rejects_persistent_or_non_test_databases(database_url):
    with pytest.raises(RuntimeError, match="SQLite|dedicated PostgreSQL"):
        validate_test_database_url(database_url)
