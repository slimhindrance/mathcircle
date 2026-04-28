"""Test fixtures.

We set MATHCIRCLE_DATABASE_URL before any app import so a single, isolated
SQLite file is used across the whole test session. Between tests we wipe
mutable tables and re-seed defaults — fast, no module reloads, no SQLAlchemy
mapper duplication.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# IMPORTANT: env var must be set before importing app.*
_TMP = tempfile.TemporaryDirectory()
os.environ["MATHCIRCLE_DATABASE_URL"] = f"sqlite:///{Path(_TMP.name) / 'test.db'}"


@pytest.fixture(scope="session")
def _initialized_app():
    from app.database import SessionLocal, init_db
    from app.seed import ensure_default_children, seed_database

    init_db()
    with SessionLocal() as db:
        seed_database(db)
        ensure_default_children(db)
        db.commit()
    yield


@pytest.fixture(autouse=True)
def _clean_state(_initialized_app):
    """Wipe per-test state, leaving strands/problems/templates intact."""
    from app.database import SessionLocal
    from app.models import Attempt, Child, Note, Session as SessionRow, Skill
    from app.seed import ensure_default_children

    with SessionLocal() as db:
        db.query(Attempt).delete()
        db.query(SessionRow).delete()
        db.query(Skill).delete()
        db.query(Note).delete()
        db.query(Child).delete()
        db.commit()
        ensure_default_children(db)
        db.commit()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c
