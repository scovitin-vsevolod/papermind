"""Integration tests for the Qdrant service.

Tests use ``QdrantClient(":memory:")`` — fully functional Qdrant
running in-process. No Docker container needed.
"""

from __future__ import annotations

import numpy as np
import pytest
from qdrant_client import QdrantClient

from app.services import qdrant as qdrant_service
from app.services.qdrant import (
    UpsertItem,
    delete_by_document,
    ensure_collection,
    search,
    upsert_chunks,
)

DIM = 384  # pinned in tests so the real embedding model never loads here


@pytest.fixture(autouse=True)
def _in_memory_qdrant():
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))
    ensure_collection(dim=DIM)
    yield
    # Reset for the next test — fresh in-memory instance.
    qdrant_service.use_client_for_tests(QdrantClient(":memory:"))


def _unit_vector(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _item(*, point_id: int, doc_id: int, position: int, seed: int, text: str = "x") -> UpsertItem:
    return UpsertItem(
        point_id=point_id,
        vector=_unit_vector(seed),
        document_id=doc_id,
        position=position,
        text=text,
    )


def test_ensure_collection_is_idempotent():
    ensure_collection(dim=DIM)  # second call on an already-created collection
    ensure_collection(dim=DIM)  # third — still fine


def test_upsert_then_search_returns_self_with_top_score():
    items = [
        _item(point_id=i, doc_id=1, position=i, seed=i, text=f"chunk {i}")
        for i in range(5)
    ]
    upsert_chunks(items)

    hits = search(items[2].vector, top_k=3)
    assert len(hits) == 3
    # The vector we queried with is identical to chunk 2 → must come first.
    assert hits[0].chunk_id == 2
    assert hits[0].text == "chunk 2"
    assert hits[0].score > 0.99  # cosine of identical unit vectors ≈ 1
    assert hits[0].score > hits[1].score


def test_search_respects_document_filter():
    d1 = [_item(point_id=i, doc_id=1, position=i, seed=i, text=f"d1-{i}") for i in range(3)]
    d2 = [
        _item(point_id=10 + i, doc_id=2, position=i, seed=10 + i, text=f"d2-{i}")
        for i in range(3)
    ]
    upsert_chunks(d1 + d2)

    hits = search(_unit_vector(0), top_k=10, document_id=2)
    assert {h.document_id for h in hits} == {2}
    assert len(hits) == 3


def test_delete_by_document_only_removes_that_documents_chunks():
    upsert_chunks(
        [_item(point_id=i, doc_id=1, position=i, seed=i) for i in range(3)]
        + [_item(point_id=10 + i, doc_id=2, position=i, seed=10 + i) for i in range(3)]
    )

    delete_by_document(1)

    hits = search(_unit_vector(0), top_k=100)
    assert {h.document_id for h in hits} == {2}


def test_empty_upsert_is_a_noop():
    upsert_chunks([])  # must not raise; must not create points
    hits = search(_unit_vector(0), top_k=10)
    assert hits == []


def test_top_k_caps_results():
    upsert_chunks(
        [_item(point_id=i, doc_id=1, position=i, seed=i) for i in range(20)]
    )
    hits = search(_unit_vector(0), top_k=3)
    assert len(hits) == 3
