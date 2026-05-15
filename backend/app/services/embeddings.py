"""Local sentence-transformers embeddings.

Why local + lazy load
---------------------
- **Free.** Phase 1 has no embedding-API budget; ``voyage-3`` joins in
  Phase 2 as a quality comparison.
- **Lazy load.** Importing this module is cheap — FastAPI startup stays
  fast and tests that don't need real embeddings don't pay the cost.
  The ~80 MB model download happens on the first call to
  :func:`embed`. After that the model lives in process memory.
- **Singleton via ``lru_cache``.** Loading the model twice in the same
  process wastes ~250 MB of RAM. ``lru_cache(maxsize=1)`` gives a
  thread-safe singleton with no extra plumbing.

Why ``normalize_embeddings=True``
---------------------------------
We normalize to unit length so cosine similarity reduces to a plain
dot product. Qdrant's ``COSINE`` distance does the normalization
internally if vectors aren't normalized, but doing it once at encode
time saves the work on every search. It also means we can use
``DOT`` distance later without changing the index.

Sync vs async
-------------
``SentenceTransformer.encode`` is synchronous (torch under the hood).
For Phase 1 we call it directly from request handlers. In a higher-
load setup we'd wrap with ``asyncio.to_thread`` — Phase 4 territory.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model)


def embedding_dim() -> int:
    """Return the output dimension of the configured model.

    Triggers model load on first call.
    """
    return _model().get_embedding_dimension()


def embed(texts: list[str]) -> np.ndarray:
    """Encode a batch of texts into unit-length vectors.

    Returns a ``(len(texts), embedding_dim)`` float32 array. Empty
    input returns an empty array of the right shape (handy for callers
    that want a uniform return type).
    """
    if not texts:
        return np.empty((0, embedding_dim()), dtype=np.float32)
    return _model().encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
