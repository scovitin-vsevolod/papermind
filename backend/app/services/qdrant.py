"""Qdrant client + chunk read/write/search.

Client lifecycle
----------------
The Qdrant client is a process-wide singleton — one connection pool
per process. Tests swap it for an in-memory Qdrant via
:func:`use_client_for_tests`, which means the test suite never needs
the Docker container to be running.

Point identity
--------------
The Qdrant point_id for a chunk is the chunk's SQLite primary key.
One ID space across both stores, no UUID synchronisation needed.

Collection layout
-----------------
- **Vectors:** ``embedding_dim()`` dimensions, COSINE distance. Since
  the embeddings service unit-normalises outputs, cosine reduces to a
  plain dot product — one multiply per dim per candidate.
- **Payload:**
    - ``document_id`` (int): used by the search filter
    - ``position`` (int): chunk index within the document
    - ``text`` (str): the chunk text itself, so the LLM-context
      builder doesn't need a separate DB round-trip to fetch it
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from qdrant_client import QdrantClient, models

from app.config import settings
from app.services.embeddings import embedding_dim


@dataclass(frozen=True)
class UpsertItem:
    point_id: int      # == Chunk.id in SQLite
    vector: np.ndarray
    document_id: int
    position: int
    text: str


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int      # == point_id, named for clarity at the API boundary
    score: float
    document_id: int
    position: int
    text: str


_CLIENT: QdrantClient | None = None


def _client() -> QdrantClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = QdrantClient(url=settings.qdrant_url)
    return _CLIENT


def use_client_for_tests(client: QdrantClient) -> None:
    """Swap in a test client (typically ``QdrantClient(':memory:')``)."""
    global _CLIENT
    _CLIENT = client


def ensure_collection(dim: int | None = None) -> None:
    """Create the collection if it doesn't exist. Idempotent.

    ``dim`` lets tests pin the dimension without triggering a real
    embedding-model load. In production callers pass nothing.
    """
    name = settings.qdrant_collection
    client = _client()
    if client.collection_exists(name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(
            size=dim if dim is not None else embedding_dim(),
            distance=models.Distance.COSINE,
        ),
    )


def upsert_chunks(items: list[UpsertItem]) -> None:
    if not items:
        return
    points = [
        models.PointStruct(
            id=item.point_id,
            vector=item.vector.tolist(),
            payload={
                "document_id": item.document_id,
                "position": item.position,
                "text": item.text,
            },
        )
        for item in items
    ]
    _client().upsert(collection_name=settings.qdrant_collection, points=points)


def search(
    query_vector: np.ndarray,
    top_k: int = 5,
    document_id: int | None = None,
) -> list[SearchHit]:
    """Find ``top_k`` most similar chunks, optionally scoped to one document."""
    flt = _document_filter(document_id) if document_id is not None else None
    response = _client().query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector.tolist(),
        query_filter=flt,
        limit=top_k,
        with_payload=True,
    )
    return [
        SearchHit(
            chunk_id=int(p.id),
            score=float(p.score),
            document_id=p.payload["document_id"],
            position=p.payload["position"],
            text=p.payload["text"],
        )
        for p in response.points
    ]


def delete_by_document(document_id: int) -> None:
    """Remove all points belonging to a document. No-op if none match."""
    _client().delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(filter=_document_filter(document_id)),
    )


def _document_filter(document_id: int) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            )
        ]
    )
