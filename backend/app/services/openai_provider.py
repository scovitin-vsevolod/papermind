"""OpenAI provider for the /ask endpoint — the GPT-4 side of side-by-side.

Mirrors the surface of ``services.claude`` so the router can call either
one through a common adapter (see :func:`ask_with_provider`).

Tool use is intentionally NOT wired here — Phase 2 keeps the comparison
fair-ish by sending the same prompt to both models without giving one an
extra tool surface. (Function calling on OpenAI works very similarly to
Claude's tool_use but the round-trip semantics differ; that comparison
deserves its own phase.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.config import settings
from app.services.claude import SYSTEM_PROMPT  # reuse the same RAG instructions


@dataclass(frozen=True)
class ChunkContext:
    chunk_id: int
    text: str


@dataclass(frozen=True)
class AskResult:
    answer: str
    cited_chunk_ids: list[int]
    model: str


_CLIENT: OpenAI | None = None


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(api_key=settings.openai_api_key)
    return _CLIENT


def use_client_for_tests(client: Any) -> None:
    """Swap in a test double (typically a FakeOpenAI)."""
    global _CLIENT
    _CLIENT = client


def ask(question: str, chunks: list[ChunkContext], max_tokens: int = 1024) -> AskResult:
    """Build the same RAG prompt as the Claude side, call GPT-4, parse citations.

    Sharing the system prompt and excerpt format ensures the side-by-side
    comparison shows *model* differences, not *prompt* differences.
    """
    excerpts = (
        "\n\n".join(f"[chunk:{c.chunk_id}] {c.text}" for c in chunks)
        if chunks
        else "(no excerpts retrieved)"
    )
    user_msg = f"Question: {question}\n\nExcerpts:\n{excerpts}"

    response = _client().chat.completions.create(
        model=settings.openai_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    answer_text = (response.choices[0].message.content or "").strip()
    return AskResult(
        answer=answer_text,
        cited_chunk_ids=_extract_citations(answer_text),
        model=settings.openai_model,
    )


_CITATION_PATTERN = re.compile(r"\[chunk:(\d+)\]")


def _extract_citations(text: str) -> list[int]:
    """Return cited chunk IDs in first-appearance order, deduplicated.

    Duplicated from the Claude module deliberately — the parser is a tiny
    function and keeping it next to the provider means the two SDK
    integrations stay independently swappable. If a third provider appears,
    pull this helper out.
    """
    seen: list[int] = []
    for match in _CITATION_PATTERN.finditer(text):
        chunk_id = int(match.group(1))
        if chunk_id not in seen:
            seen.append(chunk_id)
    return seen
