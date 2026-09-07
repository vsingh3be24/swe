"""Pytest fixtures: in-process TestClient bound to a temporary SQLite database.

We point FINALSAY_DATABASE_URL at a temp file *before* importing the app so the
module-level engine in ``finalsay.db`` binds to the test database. A fresh
schema is created per test and the get_db dependency is overridden to use the
test session (no persistent server is involved).
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import Iterator

import pytest

# Configure an isolated temp SQLite DB before any finalsay import. We keep the
# DB under the backend tree (not /tmp, which is wiped between tool invocations).
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TMP_DIR = tempfile.mkdtemp(prefix="finalsay-test-", dir=_BACKEND_DIR)
_DB_PATH = os.path.join(_TMP_DIR, "test.db")
os.environ["FINALSAY_DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["FINALSAY_JWT_SECRET"] = "test-secret"

atexit.register(lambda: shutil.rmtree(_TMP_DIR, ignore_errors=True))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from finalsay.db import Base, SessionLocal, engine, get_db  # noqa: E402
from finalsay.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema() -> Iterator[None]:
    """Recreate all tables before each test for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user():
    """Factory that provisions a user with an arbitrary role directly in the DB.

    Public self-registration only ever creates ``student`` accounts, so tests
    that need a privileged actor (reviewer/admin/issuer) must provision it the
    way production does: out of band (the seed script). This helper mirrors that
    by writing the user row directly, then callers log in via the normal flow.
    """
    from finalsay.auth import hash_password  # noqa: E402
    from finalsay.models import User  # noqa: E402

    def _make(email: str, password: str, role: str = "student", display_name=None) -> User:
        session = SessionLocal()
        try:
            existing = session.query(User).filter(User.email == email).one_or_none()
            if existing is not None:
                return existing
            user = User(
                email=email,
                hashed_password=hash_password(password),
                role=role,
                display_name=display_name,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        finally:
            session.close()

    return _make
