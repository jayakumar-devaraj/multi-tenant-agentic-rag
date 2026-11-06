"""Integration fixtures: a real Postgres+pgvector connection (docker-compose.yml), schema migrated."""

import os
import uuid
from collections.abc import Iterator

import pytest

from src.db.connection import connect, database_url, run
from tests.migration_support import upgrade_head


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Bring the shared test database to the Alembic head, as the migrate job does in deployment.

    Without DATABASE_URL these tests skip on a developer machine, but still error under CI (which sets `CI`),
    so a lost CI setting cannot turn the suite green without them.
    """
    if not os.environ.get("DATABASE_URL") and not os.environ.get("CI"):
        pytest.skip("integration test: DATABASE_URL is not set (README, Testing)")
    upgrade_head(os.environ.get("MIGRATION_DATABASE_URL") or database_url())


@pytest.fixture
def tenant() -> str:
    """A fresh tenant id per test, so tests never share rows."""
    return f"t-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def conn() -> Iterator[object]:
    """Yield a live async connection to the migrated test database."""
    c = run(connect())
    yield c
    run(c.close())
