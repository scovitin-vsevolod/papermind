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

from app.auth_deps import get_current_user
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.services import claude as claude_service
from app.services import graph as graph_service
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


# ── Fake Neo4j ───────────────────────────────────────────────────────────────


@dataclass
class _FakeNeo4jResult:
    """Mimics the result of ``session.run(cypher, **params)``.

    The real driver returns an object with ``.data()`` for list-of-dicts
    and is iterable. Tests for the writer don't read results back; only
    the reader needs ``.data()``, which we synthesise from the in-memory
    graph kept on the parent FakeNeo4jDriver.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)

    def data(self) -> list[dict[str, Any]]:
        return self.rows


@dataclass
class _FakeNeo4jSession:
    driver: FakeNeo4jDriver

    def __enter__(self) -> _FakeNeo4jSession:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def run(self, cypher: str, **params: Any) -> _FakeNeo4jResult:
        self.driver.queries.append((cypher, dict(params)))
        # Tiny built-in interpreter for the handful of queries we actually
        # need to round-trip in tests. Not real Cypher — just enough so the
        # extraction → graph → /graph flow is exercisable without Neo4j.
        cypher_lower = cypher.lower()
        if cypher_lower.startswith("create constraint"):
            return _FakeNeo4jResult()
        if "merge (e:entity" in cypher_lower:
            name = params["name"]
            existing = self.driver.entities.get(name)
            doc_id = params["doc_id"]
            if existing is None:
                self.driver.entities[name] = {
                    "name": name,
                    "type": params["type"],
                    "document_ids": [doc_id],
                }
            else:
                if doc_id not in existing["document_ids"]:
                    existing["document_ids"].append(doc_id)
            return _FakeNeo4jResult()
        if "merge (h)-[r:relates" in cypher_lower:
            key = (params["head"], params["label"], params["tail"])
            doc_id = params["doc_id"]
            existing = self.driver.relations.get(key)
            if existing is None:
                self.driver.relations[key] = {
                    "head": params["head"],
                    "label": params["label"],
                    "tail": params["tail"],
                    "document_ids": [doc_id],
                }
            else:
                if doc_id not in existing["document_ids"]:
                    existing["document_ids"].append(doc_id)
            return _FakeNeo4jResult()
        # Phase 5 first: graph-RAG neighbour queries use `WHERE e.name IN $names`
        # which doesn't overlap with the legacy $doc_id queries below. Match
        # this one early so the broader checks below don't intercept it.
        if "where e.name in $names" in cypher_lower:
            names = set(params["names"])
            if "(e:entity)-[:relates]-(n:entity)" in cypher_lower:
                # Neighbours of the seed set.
                related: list[dict[str, Any]] = []
                seen: set[str] = set()
                for r in self.driver.relations.values():
                    for side, other in (("head", "tail"), ("tail", "head")):
                        if r[side] in names and r[other] not in seen:
                            entity = self.driver.entities.get(r[other])
                            if entity is not None:
                                seen.add(r[other])
                                related.append(entity)
                return _FakeNeo4jResult(rows=related)
            # Seeds-only query.
            return _FakeNeo4jResult(
                rows=[e for n, e in self.driver.entities.items() if n in names]
            )
        if (
            "match (e:entity)" in cypher_lower
            and "$doc_id" in cypher_lower
            and "return" in cypher_lower
        ):
            doc_id = params["doc_id"]
            return _FakeNeo4jResult(
                rows=[
                    e for e in self.driver.entities.values()
                    if doc_id in e["document_ids"]
                ]
            )
        if "match (e:entity)" in cypher_lower and "return" in cypher_lower:
            return _FakeNeo4jResult(rows=list(self.driver.entities.values()))
        if (
            "match (h:entity)-[r:relates]->(t:entity)" in cypher_lower
            and "$doc_id" in cypher_lower
        ):
            doc_id = params["doc_id"]
            head_names = {n for n, e in self.driver.entities.items() if doc_id in e["document_ids"]}
            return _FakeNeo4jResult(
                rows=[
                    r
                    for r in self.driver.relations.values()
                    if r["head"] in head_names and r["tail"] in head_names
                ]
            )
        if "match (h:entity)-[r:relates]->(t:entity)" in cypher_lower:
            return _FakeNeo4jResult(rows=list(self.driver.relations.values()))
        if "delete r" in cypher_lower:
            doc_id = params["doc_id"]
            for key in list(self.driver.relations.keys()):
                r = self.driver.relations[key]
                r["document_ids"] = [d for d in r["document_ids"] if d != doc_id]
                if not r["document_ids"]:
                    del self.driver.relations[key]
            return _FakeNeo4jResult()
        if "detach delete e" in cypher_lower:
            doc_id = params["doc_id"]
            for name in list(self.driver.entities.keys()):
                e = self.driver.entities[name]
                e["document_ids"] = [d for d in e["document_ids"] if d != doc_id]
                if not e["document_ids"]:
                    del self.driver.entities[name]
            return _FakeNeo4jResult()
        return _FakeNeo4jResult()


@dataclass
class FakeNeo4jDriver:
    """Test double for ``neo4j.Driver``. Implements the slice we use.

    Backed by two dicts that simulate Neo4j storage — enough to verify the
    extraction → write → read cycle without a running container.
    """

    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    relations: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    queries: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def session(self) -> _FakeNeo4jSession:
        return _FakeNeo4jSession(driver=self)


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
def fake_neo4j() -> Iterator[FakeNeo4jDriver]:
    """In-memory Neo4j double for graph tests.

    Every test gets a fresh instance so the entity/relation dicts don't
    leak between cases. The fake also reverts to a fresh empty instance
    on teardown so a test that doesn't request it can't reach real Neo4j.
    """

    fake = FakeNeo4jDriver()
    graph_service.use_driver_for_tests(fake)
    try:
        yield fake
    finally:
        graph_service.use_driver_for_tests(FakeNeo4jDriver())


@pytest.fixture
def fake_user(db_session: Session) -> User:
    """A persisted test user. Inserted into the per-test in-memory DB so
    foreign-key references and joins behave like the real thing.
    """
    user = User(
        email="test@example.com",
        password_hash="$2b$12$placeholder.placeholder.placeholder.placeholder.plac",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(
    db_session: Session,
    fake_claude: FakeClaude,
    fake_openai: FakeOpenAI,
    fake_neo4j: FakeNeo4jDriver,
    fake_user: User,
) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    def _override_get_current_user() -> User:
        # Existing tests for /documents, /ask, /graph all assume an
        # authenticated session; override the auth dependency to return
        # our test user. Auth-specific tests use `unauthenticated_client`
        # below instead.
        return fake_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(
    db_session: Session,
    fake_claude: FakeClaude,
    fake_openai: FakeOpenAI,
    fake_neo4j: FakeNeo4jDriver,
) -> Iterator[TestClient]:
    """Like `client`, but WITHOUT the auth override.

    Used by tests that exercise the login flow itself or the 401 path on
    protected endpoints.
    """

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
