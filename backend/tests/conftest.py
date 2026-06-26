"""Shared fixtures for backend tests."""

import os
import sys
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure backend/app is importable as `app.*`
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Use a throwaway SQLite file for tests so pgvector monkey-patch stays intact.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_poe2li.db")


def _build_client() -> TestClient:
    """Import the FastAPI app lazily to avoid side-effects at module load."""
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def client():
    """FastAPI test client."""
    return _build_client()


@pytest.fixture()
def db_session(monkeypatch):
    """Create a fresh SQLite in-memory DB with all tables, yield a session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, DeclarativeBase

    # We need the same Base and models as the app, but we'll create tables
    # on a separate engine so each test is fully isolated.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    # Apply the same pgvector -> SQLite JSON fallback the app uses in dev
    import pgvector.sqlalchemy
    from sqlalchemy.types import TypeDecorator
    import json as _json
    import sqlalchemy as _sa

    class _SQLiteVector(TypeDecorator):
        impl = _sa.JSON
        cache_ok = True

        def process_bind_param(self, value, dialect):
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return _json.dumps(list(value))

        def process_result_value(self, value, dialect):
            if value is None:
                return None
            if isinstance(value, str):
                return _json.loads(value)
            return value

    pgvector.sqlalchemy.Vector = _SQLiteVector

    # Import Base and models AFTER the Vector swap
    from app.core.database import Base
    import app.models.build  # noqa: F401
    import app.models.knowledge_graph  # noqa: F401

    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    # Patch get_db for the duration of the test
    monkeypatch.setattr("app.core.database.get_db", _get_db)
    monkeypatch.setattr("app.api.builds.get_db", _get_db)

    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def mock_llm(monkeypatch):
    """Replace LLM calls with a fixed, deterministic response."""

    class _FakeMessage:
        def __init__(self, content: str):
            self.content = content

    class _FakeChoice:
        def __init__(self, content: str):
            self.message = _FakeMessage(content)

    class _FakeCompletions:
        def create(self, *args, **kwargs):
            return _FakeChoice(
                '{"core_idea":"测试核心思路","core_items":"测试核心装备",'
                '"budget_alternatives":"测试替代","talent_highlights":"测试天赋",'
                '"strength_review":"测试强度"}'
            )

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = _FakeChat()

    fixed_response = (
        '{"core_idea":"测试核心思路","core_items":"测试核心装备",'
        '"budget_alternatives":"测试替代","talent_highlights":"测试天赋",'
        '"strength_review":"测试强度"}'
    )

    monkeypatch.setattr("app.core.llm_client.get_llm_client", _FakeClient)
    monkeypatch.setattr("app.services.ai_service.get_llm_client", _FakeClient)
    monkeypatch.setattr("app.services.chat_agent.get_llm_client", _FakeClient)
    monkeypatch.setattr("app.services.chat_orchestrator.get_llm_client", _FakeClient)

    return fixed_response
