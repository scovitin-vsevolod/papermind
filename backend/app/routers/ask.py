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

from app.auth_deps import get_current_user
from app.db import get_db
from app.models import Query
from app.schemas import AskRequest, AskResponse, CitationOut, ToolUseOut
from app.services import claude, graph_rag, openai_provider, qdrant
from app.services.embeddings import embed

router = APIRouter(
    prefix="/ask",
    tags=["ask"],
    dependencies=[Depends(get_current_user)],
)


@router.post("", response_model=AskResponse)
def ask(payload: AskRequest, db: Session = Depends(get_db)) -> AskResponse:
    qdrant.ensure_collection()  # idempotent — handles /ask before any upload
    query_vector = embed([payload.question])[0]
    vector_hits = qdrant.search(
        query_vector=query_vector,
        top_k=payload.top_k,
        document_id=payload.document_id,
    )
    if not vector_hits and payload.document_id is not None:
        # Document filter found nothing — more useful as 404 than as
        # an empty-context call to Claude.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no chunks found for document_id={payload.document_id}",
        )

    # Phase 5: optionally augment the hit list with graph-derived chunks.
    # When the flag is off, we still wrap each hit as source="vector" so
    # the downstream code path stays uniform.
    if payload.use_graph:
        augmented = graph_rag.augment(
            question=payload.question,
            question_vector=query_vector,
            vector_hits=vector_hits,
            document_id=payload.document_id,
        )
    else:
        augmented = [
            graph_rag.AugmentedHit(hit=h, source="vector") for h in vector_hits
        ]
    hits = [ah.hit for ah in augmented]
    source_by_chunk = {ah.hit.chunk_id: ah.source for ah in augmented}

    if payload.provider == "openai":
        oa_contexts = [
            openai_provider.ChunkContext(chunk_id=h.chunk_id, text=h.text) for h in hits
        ]
        oa = openai_provider.ask(payload.question, oa_contexts)
        # Bridge the OpenAI result into the same shape Claude returns, so the
        # rest of the handler (DB log, response shaping) stays one code path.
        result = claude.AskResult(
            answer=oa.answer,
            cited_chunk_ids=oa.cited_chunk_ids,
            model=oa.model,
            tool_uses=[],
        )
    else:
        contexts = [claude.ChunkContext(chunk_id=h.chunk_id, text=h.text) for h in hits]
        result = claude.ask(payload.question, contexts, use_tools=payload.use_tools)

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
            source=source_by_chunk.get(h.chunk_id, "vector"),
        )
        for h in hits
        if h.chunk_id in cited
    ]
    tool_uses_out = [
        ToolUseOut(name=t.name, input=t.input, result=t.result) for t in result.tool_uses
    ]
    return AskResponse(
        answer=result.answer,
        model=result.model,
        citations=citations,
        tool_uses=tool_uses_out,
    )
