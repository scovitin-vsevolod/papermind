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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.loaders.markitdown_loader import LoaderError, to_markdown
from app.models import Chunk, Document, DocumentStatus
from app.schemas import DocumentRead
from app.services import qdrant as qdrant_service
from app.services.chunker import chunk_text
from app.services.embeddings import embed

router = APIRouter(prefix="/documents", tags=["documents"])


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
    db.delete(doc)  # ORM cascade removes related Chunk rows
    db.commit()
