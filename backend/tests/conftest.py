"""Shared pytest fixtures: in-memory SQLite + in-memory Qdrant + a
TestClient with both wired into the FastAPI dependency graph.

Why in-memory for both stores:
- Tests have no network or Docker dependency
- Each test gets a clean slate — no cross-test pollution
- The full pipeline runs end-to-end against real client APIs (not
  mocks), so contract drift in qdrant-client or SQLAlchemy will
  surface here, not in production
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.services import claude as claude_service
from app.services import qdrant as qdrant_service

# ── Fake Claude ───────────────────────────────────────────────────────────────


@dataclass
class _FakeBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeMessage:
    content: list[_FakeBlock]


@dataclass
class FakeClaude:
    """Test double for ``anthropic.Anthropic``.

    Mimics the ``client.messages.create(...)`` shape: returns a message
    whose first content block carries ``response_text``. Each call is
    recorded in ``calls`` so tests can assert on the prompt that was
    sent (model, system prompt, message contents).
    """

    response_text: str = "Default fake answer."
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self) -> FakeClaude:
        return self

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        return _FakeMessage(content=[_FakeBlock(text=self.response_text)])


@pytest.fixture
def db_session() -> Iterator[Session]:
    # StaticPool pins all sessions to one connection so the in-memory
    # database persists across the test (default behaviour is one fresh
    # in-memory DB per connection — tables created on one connection
    # are invisible to the next).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def fake_claude() -> Iterator[FakeClaude]:
    """Install a FakeClaude as the process-wide Claude client.

    Any test depending on ``client`` gets this fixture transitively, so
    no test can accidentally hit the real Anthropic API.
    """
    fake = FakeClaude()
    claude_service.use_client_for_tests(fake)
    try:
        yield fake
    finally:
        # Leave a fresh fake in place so a later test without the fixture
        # still can't reach the real client.
        claude_service.use_client_for_tests(FakeClaude())


@pytest.fixture
def client(db_session: Session, fake_claude: FakeClaude) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
