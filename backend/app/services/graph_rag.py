"""GraphRAG — use the knowledge graph to surface chunks that pure vector
search would miss.

The pipeline when ``use_graph=True`` is sent to /ask:

1. Extract entities from the **question** (same Claude JSON-schema mode
   we use during ingestion).
2. Look those entities up in Neo4j and pull their 1-hop neighbours.
3. For each related entity's documents, fetch the single highest-scoring
   chunk via the same Qdrant search (using the question vector, but
   scoped to that document).
4. Return the chunks that AREN'T already in the vector hit list, marked
   ``source="graph"`` so the UI can show them as graph-derived.

Why this matters
----------------
A pure vector RAG misses chunks whose text doesn't lexically or
semantically overlap with the question but whose *entities* are
related. Classic example: question mentions "Anthropic"; a relevant
chunk talks about "Claude" without mentioning Anthropic. The graph
edge `Anthropic --develops--> Claude` is what bridges them.

Cost
----
One Claude call per /ask (entity extraction on the question) +
N Qdrant per-document searches where N = number of related entities
with documents. We cap N below to keep it bounded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services import extraction as extraction_service
from app.services import graph as graph_service
from app.services import qdrant as qdrant_service

# Tunables — small for Phase 5; bigger corpora need tuning.
_MAX_RELATED_DOCS = 8       # documents to probe via the graph
_MAX_EXTRA_HITS = 3         # chunks to return beyond the vector top-K


@dataclass(frozen=True)
class AugmentedHit:
    """A vector-search hit + provenance tag.

    `source = "vector"` for results from plain Qdrant search;
    `source = "graph"` for results pulled in via graph augmentation.
    """

    hit: qdrant_service.SearchHit
    source: str  # "vector" or "graph"


def augment(
    question: str,
    question_vector: np.ndarray,
    vector_hits: list[qdrant_service.SearchHit],
    *,
    document_id: int | None = None,
) -> list[AugmentedHit]:
    """Return the vector hits plus graph-derived extra hits, in order.

    ``document_id``: if the caller scoped the original search to one
    document, we keep that scoping for the graph-derived chunks too.
    """
    # Vector hits first, marked as such — they're the trusted baseline.
    augmented: list[AugmentedHit] = [
        AugmentedHit(hit=h, source="vector") for h in vector_hits
    ]

    # Question entity extraction. Empty result = nothing to expand on;
    # bail before any Neo4j or Qdrant calls.
    try:
        extraction = extraction_service.extract(question)
    except Exception:  # noqa: BLE001 — extraction is auxiliary, never block /ask
        return augmented
    if not extraction.entities:
        return augmented

    seed_names = [e.name for e in extraction.entities]

    # Graph lookup. If Neo4j is unreachable, swallow and degrade — the
    # /ask flow still gets vector hits.
    try:
        related = graph_service.find_neighbours(seed_names, depth=1)
    except Exception:  # noqa: BLE001
        return augmented
    if not related:
        return augmented

    # Collect candidate documents. Cap the size so a hub entity ("Python")
    # doesn't drag in dozens of off-topic documents.
    seen_doc_ids: set[int] = set()
    for entity in related:
        for doc_id in entity.document_ids:
            seen_doc_ids.add(doc_id)
            if len(seen_doc_ids) >= _MAX_RELATED_DOCS:
                break
        if len(seen_doc_ids) >= _MAX_RELATED_DOCS:
            break

    # If the original query was scoped, restrict graph hits to the same
    # document — graph expansion shouldn't bleed in unrelated docs when
    # the user explicitly asked about one.
    if document_id is not None:
        seen_doc_ids &= {document_id}

    existing_chunk_ids = {ah.hit.chunk_id for ah in augmented}
    extras: list[AugmentedHit] = []

    for doc_id in seen_doc_ids:
        if len(extras) >= _MAX_EXTRA_HITS:
            break
        # Best single chunk from this document, by the original question
        # vector. This re-uses Qdrant's relevance ranking inside the
        # document — we just changed WHICH documents are candidates.
        doc_hits = qdrant_service.search(
            query_vector=question_vector,
            top_k=1,
            document_id=doc_id,
        )
        for hit in doc_hits:
            if hit.chunk_id not in existing_chunk_ids:
                extras.append(AugmentedHit(hit=hit, source="graph"))
                existing_chunk_ids.add(hit.chunk_id)
                break

    return augmented + extras
