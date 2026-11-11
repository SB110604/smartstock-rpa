"""Test harness: a real PostgreSQL test database migrated with Alembic once per session; every test runs
inside an outer transaction that is rolled back afterwards (service-level commits become savepoints)."""

import os

os.environ["APP_ENV"] = "test"
os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://smartstock:smartstock@localhost:5433/smartstock_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ALEMBIC_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("STORAGE_DIR", os.path.join(os.path.dirname(__file__), ".data"))

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from app.db.session import engine, get_db
from app.main import create_app
from app.services import mailer
from tests import factories as f

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture()
def db(app) -> Iterator[Session]:
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False, autoflush=False)
    app.dependency_overrides[get_db] = lambda: session
    mailer.OUTBOX.clear()
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture()
def client(app, db) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def world(db: Session) -> f.World:
    """Two locations, one user per role, a supplier and a few products."""
    return f.build_world(db)


@pytest.fixture()
def auth(world: f.World):
    def headers(role: str) -> dict[str, str]:
        return f.headers_for(world.users[role])

    return headers
