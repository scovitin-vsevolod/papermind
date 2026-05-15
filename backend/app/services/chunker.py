"""Paragraph-aware text chunker for the RAG pipeline.

Design notes
------------
- "Tokens" here are approximated as whitespace-separated words. Real
  tokenizers (BPE, WordPiece) produce different counts, but for English
  the ratio is roughly 1 word ≈ 1.3 tokens, which is precise enough for
  sizing. Switching to a real tokenizer is a one-line change.

- Chunks respect paragraph boundaries (double newline) whenever they
  can. If a paragraph is bigger than the budget, fall back to sentence
  splits; if a sentence is still too big, hard-split on word boundaries.

- ``overlap`` words are carried from the end of chunk i to the start of
  chunk i+1, giving the embedding model cross-chunk context for queries
  that straddle a boundary. To keep chunk size bounded by ``chunk_size``,
  new material per chunk is capped at ``chunk_size - overlap``.

- Default 200 / 30 words is sized for
  ``sentence-transformers/all-MiniLM-L6-v2`` (256-token max window).
  200 words ≈ 250 tokens, comfortably inside the window. Tuned for
  embedding quality first — Claude's 200k context can swallow much more,
  so the embedding model is the binding constraint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 200
DEFAULT_OVERLAP = 30

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    text: str
    position: int


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")

    # Cap "new material" per chunk so that overlap from the prior chunk
    # plus new material together stay within chunk_size.
    budget = chunk_size - overlap if overlap > 0 else chunk_size

    units = _split_into_units(text, budget)

    chunks: list[Chunk] = []
    overlap_words: list[str] = []
    current: list[str] = []
    current_word_count = 0

    def flush() -> None:
        nonlocal overlap_words, current, current_word_count
        if not current:
            return
        prefix = " ".join(overlap_words) + " " if overlap_words else ""
        full_text = (prefix + " ".join(current)).strip()
        chunks.append(Chunk(text=full_text, position=len(chunks)))
        overlap_words = full_text.split()[-overlap:] if overlap > 0 else []
        current = []
        current_word_count = 0

    for unit in units:
        unit_words = _count_words(unit)
        if current_word_count + unit_words > budget and current_word_count > 0:
            flush()
        current.append(unit)
        current_word_count += unit_words

    flush()
    return chunks


def _count_words(s: str) -> int:
    return len(s.split())


def _normalise_paragraphs(text: str) -> list[str]:
    raw = _PARAGRAPH_BREAK.split(text.strip())
    return [re.sub(r"\s+", " ", p).strip() for p in raw if p.strip()]


def _split_paragraph_into_sentences(paragraph: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(paragraph.strip()) if s.strip()]


def _hard_split_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def _split_into_units(text: str, budget: int) -> list[str]:
    """Turn text into a list of units, each at most ``budget`` words long."""
    units: list[str] = []
    for paragraph in _normalise_paragraphs(text):
        if _count_words(paragraph) <= budget:
            units.append(paragraph)
            continue
        for sentence in _split_paragraph_into_sentences(paragraph):
            if _count_words(sentence) <= budget:
                units.append(sentence)
            else:
                units.extend(_hard_split_words(sentence, budget))
    return units
