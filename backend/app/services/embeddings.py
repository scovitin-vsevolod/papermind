"""Embedding backends — sentence-transformers (local) or voyage-3 (API).

Phase 1 used only sentence-transformers/all-MiniLM-L6-v2 (384 dim, free,
local). Phase 2 adds Voyage's ``voyage-3`` (1024 dim, paid, API call) so
we can measure whether the API model retrieves better on real documents.

The two backends are NOT a drop-in swap at the Qdrant layer: different
output dimensions need different collections. The Qdrant service picks
the collection name based on the current backend (see :func:`current_backend`
and ``qdrant.collection_name_for_backend``).

Selection
---------
``settings.embedding_provider`` chooses at process start. The local backend
loads its model lazily on first call. The voyage backend constructs its
client lazily (no network call until you actually embed).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

from app.config import settings

# ── Local backend (sentence-transformers / all-MiniLM-L6-v2) ─────────────────


@lru_cache(maxsize=1)
def _st_model() -> Any:
    # Import inside the cached factory so the heavy torch/transformers
    # import only happens if the local backend is actually used.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def _st_embed(texts: list[str]) -> np.ndarray:
    return _st_model().encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )


def _st_dim() -> int:
    return _st_model().get_embedding_dimension()


# ── Voyage backend (voyage-3) ────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _voyage_client() -> Any:
    import voyageai

    return voyageai.Client(api_key=settings.voyage_api_key or None)


def _voyage_embed(texts: list[str], *, input_type: str = "document") -> np.ndarray:
    # voyage-3 distinguishes "document" (corpus, what you upsert) from "query"
    # (what you search with). We default to "document" because most embed()
    # calls in the pipeline are for chunks; the search path passes "query".
    result = _voyage_client().embed(
        texts,
        model=settings.voyage_model,
        input_type=input_type,
    )
    vectors = np.asarray(result.embeddings, dtype=np.float32)
    # Voyage embeddings are L2-normalised by the API in current versions,
    # but normalise defensively so cosine == dot product downstream regardless.
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _voyage_dim() -> int:
    # voyage-3 is documented as 1024-dim. Hardcoded rather than probed so
    # we can compute the dim without spending an API call.
    return 1024


# ── Public API — switches on settings.embedding_provider ─────────────────────


def current_backend() -> str:
    """The active backend identifier — used by Qdrant for collection naming."""
    return settings.embedding_provider


def embedding_dim() -> int:
    if settings.embedding_provider == "voyage":
        return _voyage_dim()
    return _st_dim()


def embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
    """Embed a batch of texts as unit-length float32 vectors.

    ``is_query`` only matters for the voyage backend, which distinguishes
    document and query embeddings. The local model treats both the same.
    """
    if not texts:
        return np.empty((0, embedding_dim()), dtype=np.float32)
    if settings.embedding_provider == "voyage":
        return _voyage_embed(texts, input_type="query" if is_query else "document")
    return _st_embed(texts)


def reset_caches_for_tests() -> None:
    """Clear cached clients so a settings change in tests actually takes effect."""
    _st_model.cache_clear()
    _voyage_client.cache_clear()
