"""Integration tests for the embeddings service.

These tests load the real sentence-transformers model. First run
downloads ~80 MB; subsequent runs are fast (cached under
``~/.cache/huggingface/``). Mocked tests live next to the routers
that depend on this service.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.embeddings import embed, embedding_dim

EXPECTED_DIM = 384  # all-MiniLM-L6-v2


@pytest.fixture(scope="module")
def dim() -> int:
    return embedding_dim()


def test_embedding_dim_matches_expected(dim: int):
    assert dim == EXPECTED_DIM


def test_embed_returns_correct_shape(dim: int):
    vectors = embed(["hello", "world"])
    assert vectors.shape == (2, dim)
    assert vectors.dtype == np.float32


def test_embed_returns_unit_vectors(dim: int):
    vectors = embed(["the quick brown fox", "lazy dog"])
    norms = np.linalg.norm(vectors, axis=1)
    # Normalised to length 1 within float-precision wiggle room.
    np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-5)


def test_embed_is_deterministic(dim: int):
    a = embed(["test sentence"])
    b = embed(["test sentence"])
    np.testing.assert_allclose(a, b, atol=1e-6)


def test_similar_sentences_score_higher_than_unrelated(dim: int):
    # Cheap semantic sanity-check: a near-paraphrase should land closer
    # in vector space than an unrelated sentence. Vectors are unit
    # length so dot product == cosine similarity.
    a, paraphrase, unrelated = embed(
        [
            "The cat sat on the mat.",
            "A cat was sitting on a rug.",
            "Quantum chromodynamics describes the strong force.",
        ]
    )
    sim_paraphrase = float(np.dot(a, paraphrase))
    sim_unrelated = float(np.dot(a, unrelated))
    assert sim_paraphrase > sim_unrelated


def test_embed_empty_input_returns_empty_array(dim: int):
    vectors = embed([])
    assert vectors.shape == (0, dim)
