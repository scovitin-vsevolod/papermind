"""Claude wrapper for the `/ask` endpoint.

Client lifecycle
----------------
Process-wide singleton with a test-swap point — same pattern as the
Qdrant service. Tests inject a ``FakeClaude``; production gets a real
``anthropic.Anthropic`` client lazily on first use.

Prompt structure
----------------
- **System prompt:** a fixed ~150-token block, the same on every call.
  Below the 4096-token minimum for Claude prompt caching, so adding
  ``cache_control`` would silently no-op (and the retrieved chunks
  vary per query anyway).
- **User message:** the question followed by retrieved excerpts,
  each tagged ``[chunk:<id>]`` so the model can cite back.

No sampling parameters, no thinking
-----------------------------------
- ``temperature`` / ``top_p`` / ``top_k`` are removed on Opus 4.7 (400)
  and unnecessary on Sonnet 4.6. Omitted.
- ``thinking`` is off by default. For grounded Q&A on retrieved chunks
  the model doesn't need extended reasoning; adaptive thinking would
  add latency for negligible quality gain. If a future query mode
  needs it, switch on per-request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import anthropic

from app.config import settings

SYSTEM_PROMPT = (
    "You are a research assistant. Answer questions using ONLY the provided "
    "document excerpts.\n\n"
    "Rules:\n"
    "- Use only information from the excerpts below. Do not use outside knowledge.\n"
    "- Cite supporting excerpts inline using their ID, like [chunk:42].\n"
    "- If the excerpts don't contain enough information to answer, say so plainly "
    "and explain what's missing.\n"
    "- Be concise. No preamble — no phrases like \"Based on the excerpts...\"."
)


@dataclass(frozen=True)
class ChunkContext:
    chunk_id: int
    text: str


@dataclass(frozen=True)
class AskResult:
    answer: str
    cited_chunk_ids: list[int]
    model: str


_CLIENT: anthropic.Anthropic | None = None


def _client() -> anthropic.Anthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _CLIENT


def use_client_for_tests(client) -> None:  # type: ignore[no-untyped-def]
    """Swap in a test client (typically a ``FakeClaude`` double)."""
    global _CLIENT
    _CLIENT = client


def ask(question: str, chunks: list[ChunkContext], max_tokens: int = 1024) -> AskResult:
    """Build the RAG prompt, call Claude, parse the citations.

    Empty chunks are passed through (rather than short-circuited) so
    the model can say "no relevant content found" in its own words —
    the same shape of response either way.
    """
    excerpts = (
        "\n\n".join(f"[chunk:{c.chunk_id}] {c.text}" for c in chunks)
        if chunks
        else "(no excerpts retrieved)"
    )
    user_msg = f"Question: {question}\n\nExcerpts:\n{excerpts}"

    response = _client().messages.create(
        model=settings.claude_model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    answer_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return AskResult(
        answer=answer_text,
        cited_chunk_ids=_extract_citations(answer_text),
        model=settings.claude_model,
    )


_CITATION_PATTERN = re.compile(r"\[chunk:(\d+)\]")


def _extract_citations(text: str) -> list[int]:
    """Return cited chunk IDs in first-appearance order, deduplicated."""
    seen: list[int] = []
    for match in _CITATION_PATTERN.finditer(text):
        chunk_id = int(match.group(1))
        if chunk_id not in seen:
            seen.append(chunk_id)
    return seen
