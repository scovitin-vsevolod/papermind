"""Tests for the paragraph-aware chunker.

The tests use small chunk_size / overlap values so traces are easy to
follow; the defaults are exercised implicitly by integration tests
later.
"""

from __future__ import annotations

import pytest

from app.services.chunker import Chunk, chunk_text


def test_short_text_returns_one_chunk():
    chunks = chunk_text("Hello world.")
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].position == 0


def test_invalid_chunk_size_raises():
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("x", chunk_size=0)


@pytest.mark.parametrize("bad_overlap", [-1, 10, 20])
def test_invalid_overlap_raises(bad_overlap: int):
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("x", chunk_size=10, overlap=bad_overlap)


def test_chunks_stay_within_size():
    words = [f"w{i}" for i in range(500)]
    chunks = chunk_text(" ".join(words), chunk_size=50, overlap=10)
    for c in chunks:
        assert len(c.text.split()) <= 50


def test_overlap_words_match_between_consecutive_chunks():
    words = [f"w{i}" for i in range(200)]
    chunks = chunk_text(" ".join(words), chunk_size=50, overlap=10)
    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        tail = chunks[i].text.split()[-10:]
        head = chunks[i + 1].text.split()[:10]
        assert tail == head, f"overlap mismatch between chunk {i} and {i + 1}"


def test_positions_are_sequential():
    chunks = chunk_text(" ".join(["w"] * 500), chunk_size=50, overlap=10)
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_paragraph_boundaries_preferred():
    para_a = " ".join(["a"] * 30)
    para_b = " ".join(["b"] * 30)
    chunks = chunk_text(f"{para_a}\n\n{para_b}", chunk_size=50, overlap=0)
    # Two short paragraphs that together (60w) exceed the budget should
    # be split at the paragraph boundary rather than mid-paragraph.
    assert len(chunks) == 2
    assert "b" not in chunks[0].text
    assert "a" not in chunks[1].text


def test_huge_paragraph_falls_back_to_word_split():
    # No sentence boundaries (no .!?) → must hard-split on words.
    paragraph = " ".join(["x"] * 500)
    chunks = chunk_text(paragraph, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text.split()) <= 100


def test_no_overlap_preserves_original_words_exactly():
    words = [f"w{i}" for i in range(100)]
    chunks = chunk_text(" ".join(words), chunk_size=25, overlap=0)
    rebuilt = " ".join(c.text for c in chunks).split()
    assert rebuilt == words


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_is_immutable():
    # Catch accidental dataclass(frozen=False) regressions.
    chunks = chunk_text("hello world")
    # dataclasses.FrozenInstanceError subclasses AttributeError.
    with pytest.raises(AttributeError):
        chunks[0].text = "mutated"  # type: ignore[misc]
    assert isinstance(chunks[0], Chunk)
