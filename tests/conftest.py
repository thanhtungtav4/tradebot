"""Integration test fixtures. Uses a dedicated tradebot_test DB, migrated via Alembic once."""

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://tradebot:tradebot@localhost:5432/tradebot_test",
)


@pytest.fixture(scope="session")
def migrated_db():
    """Create+migrate the test DB once per session. Requires Postgres running."""
    admin = create_engine(
        "postgresql+psycopg://tradebot:tradebot@localhost:5432/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS tradebot_test WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE tradebot_test OWNER tradebot"))
    admin.dispose()

    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    # Use the current Python interpreter explicitly so tests work even when PATH
    # does not expose the venv's alembic entrypoint (CI/sandboxed environments).
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
    )

    engine = create_engine(TEST_DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_db):
    """Per-test session wrapped in a rolled-back transaction for isolation."""
    conn = migrated_db.connect()
    trans = conn.begin()
    Session = sessionmaker(bind=conn, expire_on_commit=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        if trans.is_active:
            trans.rollback()
        conn.close()


# --- Known test secrets used by API tests ---
TEST_WEBHOOK_TOKEN = "test-webhook-token-abcdefghijklmnop"
TEST_BODY_SECRET = "test-body-secret-abcdefghijklmnop"
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture
def client(db, monkeypatch):
    """FastAPI TestClient bound to the rolled-back test session + known secrets.

    Secrets are injected via env before get_settings() is (re)built, so every
    module that reads settings sees the same test values.
    """
    from fastapi.testclient import TestClient

    from app.security.secrets import hash_password

    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-api-key-abcdefghijklmnop")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password(TEST_ADMIN_PASSWORD))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-session-secret-abcdefghijkl")
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TEST_WEBHOOK_TOKEN)
    monkeypatch.setenv("TRADINGVIEW_BODY_SECRET", TEST_BODY_SECRET)

    from app.config.settings import get_settings
    from app.db.session import get_db
    from app.security.secrets import sha256_hex

    get_settings.cache_clear()

    from app.seed import seed

    seed(db)
    db.flush()
    # seed hashed from env, which now match our test token/secret; assert alignment
    from app.models import DataSource

    src = db.query(DataSource).first()
    assert src.webhook_token_hash == sha256_hex(TEST_WEBHOOK_TOKEN)

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def logged_in_client(client):
    """A TestClient with an active admin session."""
    client.get("/admin/login")
    csrf = client.cookies.get("admin_csrf")
    client.post(
        "/admin/login",
        data={"username": "admin", "password": TEST_ADMIN_PASSWORD, "csrf_token": csrf},
        follow_redirects=False,
    )
    return client
