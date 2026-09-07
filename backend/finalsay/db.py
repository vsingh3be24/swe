"""SQLAlchemy 2.x engine, session factory, declarative Base and get_db dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from finalsay.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _make_engine(database_url: str):
    """Build an engine, applying SQLite-specific connect args when needed."""
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        # Allow use across FastAPI's threadpool without per-thread checks.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, future=True)


settings = get_settings()
engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
