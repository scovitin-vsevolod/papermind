"""Pydantic schemas for API request/response bodies.

Kept separate from SQLAlchemy models so the wire format can evolve
independently of the storage schema. ``from_attributes=True`` lets us
return ORM rows directly and FastAPI serialises them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: int | None = None
    use_tools: bool = Field(
        default=False,
        description=(
            "If true, Claude may call web_search / web_fetch (Anthropic-hosted) "
            "and the client-side calculator tool while answering. "
            "Only applies when provider='claude'."
        ),
    )
    use_graph: bool = Field(
        default=False,
        description=(
            "If true, augment vector retrieval with graph-derived chunks: "
            "extract entities from the question, expand via Neo4j neighbours, "
            "pull additional candidates from related documents."
        ),
    )
    provider: Literal["claude", "openai"] = Field(
        default="claude",
        description="Which LLM to ask. 'openai' uses GPT-4 via the OpenAI SDK.",
    )


class CitationOut(BaseModel):
    chunk_id: int
    document_id: int
    position: int
    text: str
    source: Literal["vector", "graph"] = Field(
        default="vector",
        description="How this chunk was surfaced — 'vector' is plain Qdrant "
        "search, 'graph' means it was pulled in via knowledge-graph expansion.",
    )


class ToolUseOut(BaseModel):
    name: str
    input: dict
    result: str


class AskResponse(BaseModel):
    answer: str
    model: str
    citations: list[CitationOut]
    tool_uses: list[ToolUseOut] = Field(default_factory=list)


class GraphNodeOut(BaseModel):
    name: str
    type: str
    document_ids: list[int]


class GraphEdgeOut(BaseModel):
    head: str
    label: str
    tail: str
    document_ids: list[int]


class GraphResponse(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


# ── Auth ─────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class LoginResponse(BaseModel):
    """Returned on successful login. The cookie is set in the same response;
    the body is here so non-browser clients (curl, scripts) can grab the
    token if they want to use `Authorization: Bearer ...` instead of cookies.
    """

    user: UserOut
    access_token: str
    token_type: Literal["bearer"] = "bearer"
