"""SQLAlchemy engine, session, and lifecycle helpers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _):  # pragma: no cover - sqlite glue
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Programmatic context manager for scripts/tests."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables + apply lightweight in-place column migrations. Idempotent."""
    from . import models  # noqa: F401 — register mappers
    from sqlalchemy import inspect, text

    Base.metadata.create_all(bind=engine)

    # Lightweight schema additions for already-deployed DBs. Each entry is
    # (table, column, ddl) and is only run if the column is missing.
    additions = [
        ("children", "ai_digests_enabled", "BOOLEAN"),
        ("children", "ai_digests_decided_at", "DATETIME"),
        ("children", "family_id", "INTEGER REFERENCES families(id)"),
    ]
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, col, ddl in additions:
            if table not in insp.get_table_names():
                continue
            existing_cols = {c["name"] for c in insp.get_columns(table)}
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
