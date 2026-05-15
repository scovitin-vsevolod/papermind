"""Pydantic schemas for API request/response bodies.

Kept separate from SQLAlchemy models so the wire format can evolve
independently of the storage schema. ``from_attributes=True`` lets us
return ORM rows directly and FastAPI serialises them.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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


class CitationOut(BaseModel):
    chunk_id: int
    document_id: int
    position: int
    text: str


class AskResponse(BaseModel):
    answer: str
    model: str
    citations: list[CitationOut]
