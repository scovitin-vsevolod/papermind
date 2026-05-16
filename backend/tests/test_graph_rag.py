"""Tests for GraphRAG augmentation.

The flow has three external dependencies — Claude (entity extraction),
Neo4j (neighbour lookup), Qdrant (per-document chunk fetch). Each is
stubbed via the existing fakes so the augment() function can be
exercised end-to-end without any container.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from app.services import (
    claude as claude_service,
)
from app.services import (
    graph_rag,
)
from app.services import (
    qdrant as qdrant_service,
)
from app.services.extraction import Entity, Relation
from tests.conftest import (
    FakeClaude,
    FakeNeo4jDriver,
    _FakeBlock,
    _FakeMessage,
)

DIM = 384


def _scripted_extraction(entities: list[Entity], relations: list[Relation]) -> _FakeMessage:
    """Wrap an extraction payload in the format Claude returns in JSON mode."""
    return _FakeMessage(
        content=[
            _FakeBlock(
                type="text",
                text=json.dumps(
                    {
                        "entities": [{"name": e.name, "type": e.type} for e in entities],
                        "relations": [
                            {"head": r.head, "relation": r.relation, "tail": r.tail}
                            for r in relations
                        ],
                    }
                ),
            )
        ]
    )


def _unit_vec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def populated_qdrant(fake_neo4j: FakeNeo4jDriver):
    """A real in-memory Qdrant with chunks seeded across two documents."""
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))
    qdrant_service.ensure_collection(dim=DIM)
    # Doc 1: a chunk we can find by vector similarity (the "obvious" hit).
    # Doc 2: a chunk only discoverable through the graph edge.
    qdrant_service.upsert_chunks(
        [
            qdrant_service.UpsertItem(
                point_id=11,
                vector=_unit_vec(1),
                document_id=1,
                position=0,
                text="Anthropic develops Claude. The company is based in San Francisco.",
            ),
            qdrant_service.UpsertItem(
                point_id=22,
                vector=_unit_vec(2),
                document_id=2,
                position=0,
                text="Claude is an AI assistant useful for grounded Q&A.",
            ),
        ]
    )
    return qdrant_service


def _seed_graph(
    fake_neo4j: FakeNeo4jDriver,
    entities: list[tuple[str, str, list[int]]],
    relations: list[tuple[str, str, str]],
) -> None:
    """Write directly into the fake driver's storage."""
    for name, etype, doc_ids in entities:
        fake_neo4j.entities[name] = {
            "name": name,
            "type": etype,
            "document_ids": list(doc_ids),
        }
    for head, label, tail in relations:
        fake_neo4j.relations[(head, label, tail)] = {
            "head": head,
            "label": label,
            "tail": tail,
            "document_ids": [1],
        }


def test_augment_returns_vector_hits_when_question_has_no_entities(
    fake_claude: FakeClaude, fake_neo4j: FakeNeo4jDriver, populated_qdrant
):
    fake_claude.responses = [_scripted_extraction(entities=[], relations=[])]
    vector_hits = qdrant_service.search(_unit_vec(1), top_k=1)
    augmented = graph_rag.augment(
        question="Tell me something.",
        question_vector=_unit_vec(1),
        vector_hits=vector_hits,
    )
    assert [a.source for a in augmented] == ["vector"]


def test_augment_pulls_chunks_from_neighbour_documents(
    fake_claude: FakeClaude, fake_neo4j: FakeNeo4jDriver, populated_qdrant
):
    # Graph: Anthropic --develops--> Claude. Anthropic is only in doc 1,
    # Claude is only in doc 2. The question only mentions Anthropic, so
    # plain vector retrieval (scoped via the seed=1 vector) finds doc 1.
    # Graph augmentation should also surface doc 2 via the edge.
    _seed_graph(
        fake_neo4j,
        entities=[
            ("Anthropic", "Organization", [1]),
            ("Claude", "Product", [2]),
        ],
        relations=[("Anthropic", "develops", "Claude")],
    )
    fake_claude.responses = [
        _scripted_extraction(entities=[Entity(name="Anthropic", type="Organization")], relations=[])
    ]

    vector_hits = qdrant_service.search(_unit_vec(1), top_k=1)
    augmented = graph_rag.augment(
        question="What does Anthropic do?",
        question_vector=_unit_vec(1),
        vector_hits=vector_hits,
    )
    sources = [a.source for a in augmented]
    chunk_ids = [a.hit.chunk_id for a in augmented]
    assert sources == ["vector", "graph"]
    assert chunk_ids == [11, 22]


def test_augment_does_not_duplicate_chunks_already_in_vector_hits(
    fake_claude: FakeClaude, fake_neo4j: FakeNeo4jDriver, populated_qdrant
):
    _seed_graph(
        fake_neo4j,
        entities=[("Anthropic", "Organization", [1])],
        relations=[],
    )
    fake_claude.responses = [
        _scripted_extraction(entities=[Entity(name="Anthropic", type="Organization")], relations=[])
    ]

    # top_k=2 will already pull both seeded chunks.
    vector_hits = qdrant_service.search(_unit_vec(1), top_k=2)
    augmented = graph_rag.augment(
        question="Anthropic?",
        question_vector=_unit_vec(1),
        vector_hits=vector_hits,
    )
    chunk_ids = [a.hit.chunk_id for a in augmented]
    assert len(chunk_ids) == len(set(chunk_ids)), "no duplicates"
    assert all(a.source == "vector" for a in augmented), "nothing left to add via graph"


def test_augment_swallows_extraction_failure(
    fake_claude: FakeClaude, fake_neo4j: FakeNeo4jDriver, populated_qdrant
):
    # Force extraction to raise — augment() must return vector hits intact.
    class _Boom:
        @property
        def messages(self):
            return self

        def create(self, **_kwargs):
            raise RuntimeError("extraction down")

    claude_service.use_client_for_tests(_Boom())
    try:
        vector_hits = qdrant_service.search(_unit_vec(1), top_k=1)
        augmented = graph_rag.augment(
            question="anything",
            question_vector=_unit_vec(1),
            vector_hits=vector_hits,
        )
    finally:
        claude_service.use_client_for_tests(fake_claude)
    assert len(augmented) == 1
    assert augmented[0].source == "vector"


def test_augment_respects_document_id_scope(
    fake_claude: FakeClaude, fake_neo4j: FakeNeo4jDriver, populated_qdrant
):
    # Graph would surface doc 2 via Claude→neighbour, but the caller
    # scoped to doc 1 — graph hits must NOT bleed in extra documents.
    _seed_graph(
        fake_neo4j,
        entities=[
            ("Anthropic", "Organization", [1]),
            ("Claude", "Product", [2]),
        ],
        relations=[("Anthropic", "develops", "Claude")],
    )
    fake_claude.responses = [
        _scripted_extraction(entities=[Entity(name="Anthropic", type="Organization")], relations=[])
    ]

    vector_hits = qdrant_service.search(_unit_vec(1), top_k=1, document_id=1)
    augmented = graph_rag.augment(
        question="Anthropic?",
        question_vector=_unit_vec(1),
        vector_hits=vector_hits,
        document_id=1,
    )
    assert [a.hit.document_id for a in augmented] == [1]


# ── End-to-end /ask?use_graph=true ───────────────────────────────────────────


def _upload(client: TestClient, name: str, body: bytes):
    return client.post("/documents", files={"file": (name, body, "text/plain")})


def test_use_graph_flag_marks_extra_citations_as_graph_source(
    client: TestClient, fake_claude: FakeClaude, fake_neo4j: FakeNeo4jDriver
):
    # Ingest two docs (the extraction hook will hit Claude — that's OK,
    # we reset and script for the /ask call below).
    _upload(client, "anthropic.txt", b"Anthropic builds Claude.")
    _upload(client, "claude.txt", b"Claude is an AI assistant.")
    fake_claude.calls.clear()

    # Seed the graph manually (extraction during upload returned default
    # FakeClaude text which doesn't parse — the fake's two docs are
    # there in SQLite/Qdrant but the graph is empty).
    _seed_graph(
        fake_neo4j,
        entities=[
            ("Anthropic", "Organization", [1]),
            ("Claude", "Product", [2]),
        ],
        relations=[("Anthropic", "develops", "Claude")],
    )

    # Script Claude responses for the /ask flow: first the question's
    # entity extraction, then the final answer citing both chunks.
    fake_claude.responses = [
        _scripted_extraction(
            entities=[Entity(name="Anthropic", type="Organization")],
            relations=[],
        ),
        _FakeMessage(
            content=[
                _FakeBlock(
                    type="text",
                    text="Anthropic builds Claude [chunk:1]. Claude is an AI [chunk:2].",
                )
            ]
        ),
    ]

    r = client.post(
        "/ask",
        json={
            "question": "What does Anthropic build?",
            "use_graph": True,
            # top_k=1 forces vector search to return only one chunk so the
            # graph augmentation has room to add the second one — that's
            # the whole point of the demo.
            "top_k": 1,
        },
    )
    assert r.status_code == 200, r.text
    citations = r.json()["citations"]
    by_id = {c["chunk_id"]: c["source"] for c in citations}
    # chunk 1 was the vector hit; chunk 2 was pulled in via the graph.
    assert by_id == {1: "vector", 2: "graph"}


def test_use_graph_false_returns_only_vector_source(
    client: TestClient, fake_claude: FakeClaude
):
    _upload(client, "doc.txt", b"PaperMind is a tool.")
    fake_claude.calls.clear()
    fake_claude.response_text = "PaperMind is a tool [chunk:1]."

    r = client.post("/ask", json={"question": "What is PaperMind?"})
    citations = r.json()["citations"]
    assert all(c["source"] == "vector" for c in citations)
