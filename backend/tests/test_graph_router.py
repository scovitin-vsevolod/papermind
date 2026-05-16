"""End-to-end tests for GET /graph."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services import graph as graph_service
from app.services.extraction import Entity, ExtractionResult, Relation
from tests.conftest import FakeNeo4jDriver


def _seed(doc_id: int, entities: list[tuple[str, str]], relations: list[tuple[str, str, str]]):
    graph_service.write_extraction(
        document_id=doc_id,
        extraction=ExtractionResult(
            entities=[Entity(name=n, type=t) for n, t in entities],
            relations=[Relation(head=h, relation=r, tail=t) for h, r, t in relations],
        ),
    )


def test_get_graph_returns_full_graph(client: TestClient, fake_neo4j: FakeNeo4jDriver):
    _seed(
        1,
        [("Anthropic", "Organization"), ("Claude", "Product")],
        [("Anthropic", "develops", "Claude")],
    )
    r = client.get("/graph")
    assert r.status_code == 200
    body = r.json()
    names = {n["name"] for n in body["nodes"]}
    assert names == {"Anthropic", "Claude"}
    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert (edge["head"], edge["label"], edge["tail"]) == (
        "Anthropic",
        "develops",
        "Claude",
    )


def test_get_graph_filters_by_document(client: TestClient, fake_neo4j: FakeNeo4jDriver):
    _seed(1, [("Alice", "Person"), ("Bob", "Person")], [("Alice", "knows", "Bob")])
    _seed(2, [("Carol", "Person"), ("Dan", "Person")], [("Carol", "knows", "Dan")])

    r = client.get("/graph", params={"document_id": 1})
    body = r.json()
    assert {n["name"] for n in body["nodes"]} == {"Alice", "Bob"}
    assert all(e["head"] in {"Alice", "Bob"} for e in body["edges"])


def test_get_graph_empty_when_nothing_extracted(
    client: TestClient, fake_neo4j: FakeNeo4jDriver
):
    r = client.get("/graph")
    assert r.status_code == 200
    assert r.json() == {"nodes": [], "edges": []}


def test_get_graph_503_when_neo4j_unreachable(client: TestClient):
    # Force the driver to raise on every session() call.
    class BrokenDriver:
        def session(self):
            raise ConnectionError("neo4j down")

    graph_service.use_driver_for_tests(BrokenDriver())
    try:
        r = client.get("/graph")
    finally:
        graph_service.use_driver_for_tests(FakeNeo4jDriver())
    assert r.status_code == 503
    assert "ConnectionError" in r.json()["detail"]
