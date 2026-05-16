"""Knowledge graph writes and reads against Neo4j.

Data model in the graph
-----------------------
- ``(:Entity {name, type})`` — vertex. ``name`` is the unique key; the
  ``type`` is one of the labels enumerated in :mod:`extraction`.
- ``(:Entity)-[:RELATES {label, document_ids}]->(:Entity)`` — directed
  edge. ``label`` is the verb phrase Claude wrote; ``document_ids`` is
  a list of every Document.id whose chunks contributed this edge so the
  UI can show "which file says this?".

Why ``MERGE`` everywhere
------------------------
Re-ingesting the same document twice must not create duplicate vertices
or edges. ``MERGE`` is upsert in Cypher; combined with the uniqueness
constraint on ``Entity.name`` (set in :func:`ensure_schema`), nodes are
deduplicated by name. Edges are deduplicated by (head, label, tail).

Client lifecycle
----------------
Same pattern as Qdrant: a process-wide driver, swappable for tests via
:func:`use_driver_for_tests`. Lazy connect so a missing Neo4j doesn't
break unrelated endpoints at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neo4j import Driver, GraphDatabase

from app.config import settings
from app.services.extraction import ExtractionResult


@dataclass(frozen=True)
class GraphNode:
    name: str
    type: str
    document_ids: list[int]


@dataclass(frozen=True)
class GraphEdge:
    head: str
    label: str
    tail: str
    document_ids: list[int]


@dataclass(frozen=True)
class GraphPayload:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


_DRIVER: Driver | None = None


def _driver() -> Driver:
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _DRIVER


def use_driver_for_tests(driver: Any) -> None:
    """Swap in a test driver (typically a FakeNeo4jDriver)."""
    global _DRIVER
    _DRIVER = driver


def ensure_schema() -> None:
    """Idempotent uniqueness constraint on Entity.name.

    Without this, every ``MERGE (e:Entity {name: $n})`` would still work
    but Neo4j wouldn't index lookups, and ``MERGE`` on a large dataset
    becomes O(n) per call. The constraint adds a unique-index for free.
    """
    with _driver().session() as session:
        session.run(
            "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.name IS UNIQUE"
        )


def write_extraction(document_id: int, extraction: ExtractionResult) -> None:
    """Merge entities + relations from one chunk into the graph.

    Idempotent: re-running for the same (document, chunk) is safe and
    won't duplicate edges. ``document_ids`` accumulates uniquely so we
    can later answer "which documents contributed this edge?".
    """
    if not extraction.entities:
        return
    with _driver().session() as session:
        for entity in extraction.entities:
            session.run(
                # Set on create so we don't downgrade type on re-merge; the
                # first chunk to claim the entity wins its type.
                "MERGE (e:Entity {name: $name}) "
                "ON CREATE SET e.type = $type, e.document_ids = [$doc_id] "
                "ON MATCH SET e.document_ids = "
                "  CASE WHEN $doc_id IN coalesce(e.document_ids, []) "
                "       THEN e.document_ids "
                "       ELSE coalesce(e.document_ids, []) + $doc_id END",
                name=entity.name,
                type=entity.type,
                doc_id=document_id,
            )
        for relation in extraction.relations:
            session.run(
                "MATCH (h:Entity {name: $head}), (t:Entity {name: $tail}) "
                "MERGE (h)-[r:RELATES {label: $label}]->(t) "
                "ON CREATE SET r.document_ids = [$doc_id] "
                "ON MATCH SET r.document_ids = "
                "  CASE WHEN $doc_id IN coalesce(r.document_ids, []) "
                "       THEN r.document_ids "
                "       ELSE coalesce(r.document_ids, []) + $doc_id END",
                head=relation.head,
                tail=relation.tail,
                label=relation.relation,
                doc_id=document_id,
            )


def read_graph(document_id: int | None = None) -> GraphPayload:
    """Return the (sub)graph for one document, or the entire graph if no id.

    "Subgraph for document N" means: every entity that appears in any
    chunk of document N, plus every edge between two such entities
    (regardless of which document supplied the edge).
    """
    with _driver().session() as session:
        if document_id is None:
            node_records = session.run(
                "MATCH (e:Entity) RETURN e.name AS name, e.type AS type, "
                "coalesce(e.document_ids, []) AS document_ids"
            ).data()
            edge_records = session.run(
                "MATCH (h:Entity)-[r:RELATES]->(t:Entity) "
                "RETURN h.name AS head, r.label AS label, t.name AS tail, "
                "coalesce(r.document_ids, []) AS document_ids"
            ).data()
        else:
            node_records = session.run(
                "MATCH (e:Entity) WHERE $doc_id IN coalesce(e.document_ids, []) "
                "RETURN e.name AS name, e.type AS type, "
                "coalesce(e.document_ids, []) AS document_ids",
                doc_id=document_id,
            ).data()
            # An edge counts as "in document N" if both endpoints do — keeps
            # the subgraph tight and avoids dragging in unrelated neighbours.
            edge_records = session.run(
                "MATCH (h:Entity)-[r:RELATES]->(t:Entity) "
                "WHERE $doc_id IN coalesce(h.document_ids, []) "
                "  AND $doc_id IN coalesce(t.document_ids, []) "
                "RETURN h.name AS head, r.label AS label, t.name AS tail, "
                "coalesce(r.document_ids, []) AS document_ids",
                doc_id=document_id,
            ).data()

    nodes = [
        GraphNode(
            name=rec["name"],
            type=rec["type"],
            document_ids=list(rec["document_ids"]),
        )
        for rec in node_records
    ]
    edges = [
        GraphEdge(
            head=rec["head"],
            label=rec["label"],
            tail=rec["tail"],
            document_ids=list(rec["document_ids"]),
        )
        for rec in edge_records
    ]
    return GraphPayload(nodes=nodes, edges=edges)


def delete_for_document(document_id: int) -> None:
    """Remove this document's contribution to the graph.

    Strategy: for each entity, drop the document id from its list; if
    the list becomes empty, the entity belongs only to this document
    and we delete it (along with its edges). Edges follow the same
    rule. Keeps the graph honest after a `DELETE /documents/{id}`.
    """
    with _driver().session() as session:
        session.run(
            "MATCH ()-[r:RELATES]->() "
            "WHERE $doc_id IN coalesce(r.document_ids, []) "
            "SET r.document_ids = [x IN r.document_ids WHERE x <> $doc_id] "
            "WITH r WHERE size(r.document_ids) = 0 "
            "DELETE r",
            doc_id=document_id,
        )
        session.run(
            "MATCH (e:Entity) "
            "WHERE $doc_id IN coalesce(e.document_ids, []) "
            "SET e.document_ids = [x IN e.document_ids WHERE x <> $doc_id] "
            "WITH e WHERE size(e.document_ids) = 0 "
            "DETACH DELETE e",
            doc_id=document_id,
        )
