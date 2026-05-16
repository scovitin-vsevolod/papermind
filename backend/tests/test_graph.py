"""Tests for the Neo4j graph service.

Uses the in-memory FakeNeo4jDriver — covers MERGE semantics for both
entities and relations, document-scoped reads, and the delete-cleanup
path that runs after `DELETE /documents/{id}`.
"""

from __future__ import annotations

from app.services import graph as graph_service
from app.services.extraction import Entity, ExtractionResult, Relation
from tests.conftest import FakeNeo4jDriver


def _extraction(
    entities: list[tuple[str, str]],
    relations: list[tuple[str, str, str]],
) -> ExtractionResult:
    return ExtractionResult(
        entities=[Entity(name=n, type=t) for n, t in entities],
        relations=[Relation(head=h, relation=r, tail=t) for h, r, t in relations],
    )


def test_write_extraction_creates_entities_and_edge(fake_neo4j: FakeNeo4jDriver):
    graph_service.write_extraction(
        document_id=1,
        extraction=_extraction(
            [("Anthropic", "Organization"), ("Claude", "Product")],
            [("Anthropic", "develops", "Claude")],
        ),
    )
    payload = graph_service.read_graph()
    assert {n.name for n in payload.nodes} == {"Anthropic", "Claude"}
    assert len(payload.edges) == 1
    e = payload.edges[0]
    assert (e.head, e.label, e.tail) == ("Anthropic", "develops", "Claude")
    assert e.document_ids == [1]


def test_merge_dedupes_entities_across_documents(fake_neo4j: FakeNeo4jDriver):
    graph_service.write_extraction(1, _extraction([("Claude", "Product")], []))
    graph_service.write_extraction(2, _extraction([("Claude", "Product")], []))
    nodes = graph_service.read_graph().nodes
    assert len(nodes) == 1
    assert sorted(nodes[0].document_ids) == [1, 2]


def test_merge_dedupes_relations(fake_neo4j: FakeNeo4jDriver):
    payload = _extraction(
        [("Anthropic", "Organization"), ("Claude", "Product")],
        [("Anthropic", "develops", "Claude")],
    )
    graph_service.write_extraction(1, payload)
    graph_service.write_extraction(1, payload)  # same doc, same fact
    graph_service.write_extraction(2, payload)  # different doc, same fact
    edges = graph_service.read_graph().edges
    assert len(edges) == 1
    assert sorted(edges[0].document_ids) == [1, 2]


def test_empty_extraction_is_noop(fake_neo4j: FakeNeo4jDriver):
    graph_service.write_extraction(1, _extraction([], []))
    payload = graph_service.read_graph()
    assert payload.nodes == []
    assert payload.edges == []


def test_read_graph_scoped_to_document(fake_neo4j: FakeNeo4jDriver):
    graph_service.write_extraction(
        1,
        _extraction([("Alice", "Person"), ("Bob", "Person")], [("Alice", "knows", "Bob")]),
    )
    graph_service.write_extraction(
        2,
        _extraction([("Carol", "Person"), ("Dan", "Person")], [("Carol", "knows", "Dan")]),
    )

    only_doc1 = graph_service.read_graph(document_id=1)
    names = {n.name for n in only_doc1.nodes}
    assert names == {"Alice", "Bob"}
    assert {(e.head, e.tail) for e in only_doc1.edges} == {("Alice", "Bob")}


def test_delete_for_document_removes_solo_entities_and_edges(fake_neo4j: FakeNeo4jDriver):
    graph_service.write_extraction(
        1,
        _extraction([("Alice", "Person"), ("Bob", "Person")], [("Alice", "knows", "Bob")]),
    )
    graph_service.delete_for_document(1)
    payload = graph_service.read_graph()
    assert payload.nodes == []
    assert payload.edges == []


def test_delete_keeps_entities_shared_with_other_documents(fake_neo4j: FakeNeo4jDriver):
    graph_service.write_extraction(1, _extraction([("Claude", "Product")], []))
    graph_service.write_extraction(2, _extraction([("Claude", "Product")], []))
    graph_service.delete_for_document(1)
    nodes = graph_service.read_graph().nodes
    assert len(nodes) == 1
    assert nodes[0].document_ids == [2]


def test_ensure_schema_runs_constraint_query(fake_neo4j: FakeNeo4jDriver):
    graph_service.ensure_schema()
    assert any(
        "CREATE CONSTRAINT" in q.upper() for q, _ in fake_neo4j.queries
    )
