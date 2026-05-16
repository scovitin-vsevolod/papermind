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
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.config import settings
from app.services.tools import ALL_TOOLS, execute_custom_tool

# Custom tool names (client-side) — we execute these and feed results back.
# Server-side tools (`web_search`, `web_fetch`) are handled inside Anthropic;
# their results come back inline and we don't need to act on them.
_CUSTOM_TOOL_NAMES = {"calculator"}

# Hard cap on the multi-turn loop so a buggy / hostile model can't burn the
# budget. Five turns covers any realistic RAG query.
_MAX_TOOL_ITERATIONS = 5

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
class ToolUseRecord:
    """One observed tool invocation, for transparency in the API response."""

    name: str
    input: dict[str, Any]
    result: str  # truncated for client-side; "(server-handled)" for server tools


@dataclass(frozen=True)
class AskResult:
    answer: str
    cited_chunk_ids: list[int]
    model: str
    tool_uses: list[ToolUseRecord] = field(default_factory=list)


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


def ask(
    question: str,
    chunks: list[ChunkContext],
    *,
    use_tools: bool = False,
    max_tokens: int = 1024,
) -> AskResult:
    """Build the RAG prompt, call Claude, parse citations.

    When ``use_tools=True``, Claude can optionally call ``web_search``
    or ``web_fetch`` (Anthropic-hosted) for fresh info, or ``calculator``
    (client-side, we execute it) for arithmetic. The function runs a
    multi-turn loop until Claude stops calling tools, capped at
    ``_MAX_TOOL_ITERATIONS`` to bound cost.

    Empty chunks are passed through (rather than short-circuited) so
    the model can say "no relevant content found" in its own words.
    """
    excerpts = (
        "\n\n".join(f"[chunk:{c.chunk_id}] {c.text}" for c in chunks)
        if chunks
        else "(no excerpts retrieved)"
    )
    user_msg = f"Question: {question}\n\nExcerpts:\n{excerpts}"
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

    tool_uses: list[ToolUseRecord] = []
    response = _create_message(messages, use_tools=use_tools, max_tokens=max_tokens)

    for _ in range(_MAX_TOOL_ITERATIONS):
        # Record any server-side tool invocations (web_search / web_fetch)
        # for transparency. Their results are already inline in the response.
        for block in response.content:
            if getattr(block, "type", None) == "server_tool_use":
                tool_uses.append(
                    ToolUseRecord(
                        name=getattr(block, "name", "<unknown>"),
                        input=dict(getattr(block, "input", {}) or {}),
                        result="(server-handled)",
                    )
                )

        # Did Claude ask us to run any *custom* tools? If not, we're done.
        custom_calls = [
            b
            for b in response.content
            if getattr(b, "type", None) == "tool_use"
            and getattr(b, "name", None) in _CUSTOM_TOOL_NAMES
        ]
        if not custom_calls or response.stop_reason != "tool_use":
            break

        # Execute each custom tool, build tool_result blocks for the reply.
        tool_results: list[dict[str, Any]] = []
        for call in custom_calls:
            result = execute_custom_tool(call.name, dict(call.input))
            tool_uses.append(
                ToolUseRecord(name=call.name, input=dict(call.input), result=result)
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": result,
                }
            )

        # Echo the assistant turn + our tool results, then ask Claude to continue.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        response = _create_message(messages, use_tools=use_tools, max_tokens=max_tokens)

    answer_text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    return AskResult(
        answer=answer_text,
        cited_chunk_ids=_extract_citations(answer_text),
        model=settings.claude_model,
        tool_uses=tool_uses,
    )


def _create_message(
    messages: list[dict[str, Any]], *, use_tools: bool, max_tokens: int
) -> Any:
    """Call ``messages.create`` with or without the tool list, depending on
    ``use_tools``. Centralised so the loop body stays small.
    """
    kwargs: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }
    if use_tools:
        kwargs["tools"] = ALL_TOOLS
    return _client().messages.create(**kwargs)


_CITATION_PATTERN = re.compile(r"\[chunk:(\d+)\]")


def _extract_citations(text: str) -> list[int]:
    """Return cited chunk IDs in first-appearance order, deduplicated."""
    seen: list[int] = []
    for match in _CITATION_PATTERN.finditer(text):
        chunk_id = int(match.group(1))
        if chunk_id not in seen:
            seen.append(chunk_id)
    return seen
