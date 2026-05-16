"""Documents API — the full ingest pipeline behind one POST.

``POST /documents``
    multipart upload → parse (markitdown) → chunk → embed → upsert into
    Qdrant + Chunk rows in SQLite. Synchronous for Phase 1: simple,
    blocks the request for a few seconds per doc, no queue needed.

``GET /documents`` / ``GET /documents/{id}``
    Read metadata. Chunks aren't returned here — they're search hits.

``DELETE /documents/{id}``
    Drops chunks from both stores. SQLite cascade handles ``Chunk``
    rows; Qdrant is wiped via a payload filter.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.db import get_db
from app.loaders.markitdown_loader import LoaderError, to_markdown
from app.models import Chunk, Document, DocumentStatus
from app.schemas import DocumentRead
from app.services import extraction as extraction_service
from app.services import graph as graph_service
from app.services import qdrant as qdrant_service
from app.services.chunker import chunk_text
from app.services.embeddings import embed

log = logging.getLogger(__name__)

# All routes in this router require an authenticated user. Applying the
# dependency at the router level (rather than on every function) means
# protected-by-default — adding a new endpoint can't accidentally skip auth.
router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[DocumentRead])
def list_documents(db: Session = Depends(get_db)) -> list[Document]:
    return (
        db.query(Document)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .all()
    )


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db)) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return doc


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Document:
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "filename is required")

    content = file.file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file is empty")

    doc = Document(
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        status=DocumentStatus.PARSING.value,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        markdown = to_markdown(content, file.filename)
    except LoaderError as exc:
        doc.status = DocumentStatus.ERROR.value
        doc.error = str(exc)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    doc.status = DocumentStatus.EMBEDDING.value
    db.commit()

    # Wrap the chunk → embed → upsert phase so any crash (Qdrant unreachable,
    # embedding model failed to load, ORM mismatch) lands on the Document
    # row as a status=ERROR with the real error text, AND comes back to the
    # client as a 500 with the same text — not as an opaque "Internal
    # Server Error" with the traceback only in uvicorn stderr.
    try:
        chunks = chunk_text(markdown)

        # Insert Chunk rows first so SQLite hands us their ids — those ids
        # double as Qdrant point ids.
        chunk_rows = [
            Chunk(document_id=doc.id, position=c.position, text=c.text) for c in chunks
        ]
        db.add_all(chunk_rows)
        db.flush()

        vectors = embed([c.text for c in chunks])
        qdrant_service.ensure_collection()
        qdrant_service.upsert_chunks(
            [
                qdrant_service.UpsertItem(
                    point_id=row.id,
                    vector=vectors[i],
                    document_id=doc.id,
                    position=row.position,
                    text=row.text,
                )
                for i, row in enumerate(chunk_rows)
            ]
        )

        # Knowledge-graph extraction is best-effort: each chunk gets its
        # own Claude call, and we don't want a Neo4j outage (or one bad
        # chunk) to fail the whole ingest. Log + swallow per-chunk
        # failures; the document still becomes READY.
        try:
            graph_service.ensure_schema()
            for row in chunk_rows:
                try:
                    result = extraction_service.extract(row.text)
                except Exception as exc:  # noqa: BLE001 — wide on purpose
                    log.warning("extraction failed for chunk %s: %s", row.id, exc)
                    continue
                graph_service.write_extraction(doc.id, result)
        except Exception as exc:  # noqa: BLE001 — Neo4j whole-graph errors
            log.warning("graph build skipped for document %s: %s", doc.id, exc)
    except Exception as exc:
        db.rollback()
        # Reattach a fresh row reference so we can persist the error state
        # (rollback detaches the in-flight Chunk inserts but the Document
        # row was committed earlier).
        doc = db.get(Document, doc.id)
        if doc is not None:
            doc.status = DocumentStatus.ERROR.value
            doc.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"ingestion failed at chunk/embed/upsert: {type(exc).__name__}: {exc}",
        ) from exc

    doc.status = DocumentStatus.READY.value
    doc.chunk_count = len(chunks)
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: Session = Depends(get_db)) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    qdrant_service.delete_by_document(document_id)
    # Best-effort graph cleanup — same reasoning as the ingest hook:
    # a Neo4j outage shouldn't block deleting from the primary stores.
    try:
        graph_service.delete_for_document(document_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("graph cleanup skipped for document %s: %s", document_id, exc)
    db.delete(doc)  # ORM cascade removes related Chunk rows
    db.commit()
