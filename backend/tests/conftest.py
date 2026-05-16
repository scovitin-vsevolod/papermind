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
from app.services import openai_provider as openai_service
from app.services import qdrant as qdrant_service

# ── Fake Claude ───────────────────────────────────────────────────────────────


@dataclass
class _FakeBlock:
    """Polymorphic content block.

    For text blocks: ``type="text"`` + ``text`` set.
    For tool_use blocks: ``type="tool_use"`` + ``id`` + ``name`` + ``input``.
    For server_tool_use blocks: ``type="server_tool_use"`` + ``name`` + ``input``.
    """

    type: str = "text"
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeMessage:
    content: list[_FakeBlock]
    stop_reason: str = "end_turn"


@dataclass
class FakeClaude:
    """Test double for ``anthropic.Anthropic``.

    Two modes:
    - **Simple:** ``response_text`` is returned as one text block per call.
      Stop reason is "end_turn". Default behaviour.
    - **Scripted:** ``responses`` is a list of ``_FakeMessage`` — one per
      successive ``create()`` call. Used for tool-loop tests where Claude
      needs to emit a tool_use first, then a final text answer.

    Each call is recorded in ``calls`` so tests can assert on the prompt
    that was sent (model, system, messages, tools).
    """

    response_text: str = "Default fake answer."
    responses: list[_FakeMessage] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self) -> FakeClaude:
        return self

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        if self.responses:
            # Pop scripted responses in order; the last one repeats forever
            # so a runaway loop doesn't IndexError mid-test.
            if len(self.responses) > 1:
                return self.responses.pop(0)
            return self.responses[0]
        return _FakeMessage(content=[_FakeBlock(type="text", text=self.response_text)])


def make_text_message(text: str) -> _FakeMessage:
    return _FakeMessage(content=[_FakeBlock(type="text", text=text)])


# ── Fake OpenAI ──────────────────────────────────────────────────────────────


@dataclass
class _FakeChoiceMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeChoiceMessage


@dataclass
class _FakeChatCompletion:
    choices: list[_FakeChoice]


@dataclass
class FakeOpenAI:
    """Test double for ``openai.OpenAI``.

    Implements only the slice we use: ``client.chat.completions.create()``.
    Every call is recorded in ``calls``.
    """

    response_text: str = "OpenAI fake answer."
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def chat(self) -> FakeOpenAI:
        return self

    @property
    def completions(self) -> FakeOpenAI:
        return self

    def create(self, **kwargs: Any) -> _FakeChatCompletion:
        self.calls.append(kwargs)
        return _FakeChatCompletion(
            choices=[_FakeChoice(message=_FakeChoiceMessage(content=self.response_text))]
        )


def make_tool_use_message(
    tool_use_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    leading_text: str = "",
) -> _FakeMessage:
    """A message that asks the host to run a custom tool (calculator etc.)."""

    blocks: list[_FakeBlock] = []
    if leading_text:
        blocks.append(_FakeBlock(type="text", text=leading_text))
    blocks.append(
        _FakeBlock(type="tool_use", id=tool_use_id, name=tool_name, input=tool_input)
    )
    return _FakeMessage(content=blocks, stop_reason="tool_use")


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
def fake_openai() -> Iterator[FakeOpenAI]:
    """Same defensive pattern for the OpenAI side of the comparison."""

    fake = FakeOpenAI()
    openai_service.use_client_for_tests(fake)
    try:
        yield fake
    finally:
        openai_service.use_client_for_tests(FakeOpenAI())


@pytest.fixture
def client(
    db_session: Session,
    fake_claude: FakeClaude,
    fake_openai: FakeOpenAI,
) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
