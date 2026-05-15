"""POST /ask — the RAG entry point.

Pipeline per request:
1. Embed the question.
2. Search Qdrant (optionally scoped to a single document).
3. Build a prompt from retrieved chunks and call Claude.
4. Parse citations out of the answer and persist the query for history.
5. Return the answer + the chunks Claude actually cited (not every
   retrieved chunk — keeps the response honest about what was used).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Query
from app.schemas import AskRequest, AskResponse, CitationOut
from app.services import claude, qdrant
from app.services.embeddings import embed

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
def ask(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    qdrant.ensure_collection()  # idempotent — handles /ask before any upload
    query_vector = embed([payload.question])[0]
    hits = qdrant.search(
        query_vector=query_vector,
        top_k=payload.top_k,
        document_id=payload.document_id,
    )
    if not hits and payload.document_id is not None:
        # Document filter found nothing — more useful as 404 than as
        # an empty-context call to Claude.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no chunks found for document_id={payload.document_id}",
        )

    contexts = [claude.ChunkContext(chunk_id=h.chunk_id, text=h.text) for h in hits]
    result = claude.ask(payload.question, contexts)

    db.add(
        Query(
            question=payload.question,
            answer=result.answer,
            model=result.model,
            chunk_ids=json.dumps(result.cited_chunk_ids),
        )
    )
    db.commit()

    cited = set(result.cited_chunk_ids)
    citations = [
        CitationOut(
            chunk_id=h.chunk_id,
            document_id=h.document_id,
            position=h.position,
            text=h.text,
        )
        for h in hits
        if h.chunk_id in cited
    ]
    return AskResponse(answer=result.answer, model=result.model, citations=citations)
